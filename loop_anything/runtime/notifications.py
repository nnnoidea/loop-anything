"""Named local notification outlets and one durable outbox in each Timeline."""
import copy
import json
import re
import time
from loop_anything.runtime.model import Invalid, Conflict, digest, check_schema
from loop_anything.runtime.store import Store


class NotificationConfigurationError(Invalid):
    """Delivery must wait for an explicitly configured outlet."""


class NotificationNotSent(Invalid):
    """The authorized adapter confirms that no send was attempted."""


def deliver_command(adapter, payload, runner):
    """Shared receipt contract for Timeline and standalone request notifications."""
    if adapter.get('configuration_error'):
        raise NotificationConfigurationError(adapter['configuration_error'])
    if not adapter.get('command'):
        raise NotificationConfigurationError('No notification transport configured')
    result=runner(adapter['command'],json.dumps(payload),adapter.get('timeout',30),adapter.get('cwd'))
    try:receipt=json.loads(result.stdout)
    except (ValueError,TypeError):receipt=None
    if isinstance(receipt,dict) and receipt.get('delivered') is False and receipt.get('not_sent') is True:
        raise NotificationNotSent(str(receipt.get('error') or 'Unavailable before sending'))
    if result.returncode:
        try:detail=json.loads(result.stdout).get('error')
        except (ValueError,AttributeError):detail=None
        raise Invalid('Notification transport failed: '+str(detail or result.stderr or result.returncode)[-1500:])
    receipt=json.loads(result.stdout)
    if not isinstance(receipt,dict) or receipt.get('delivered') is not True:
        raise Invalid('Transport did not confirm delivery')
    return receipt


def waiting_configuration(notice):
    # Recognize older outbox rows as well, before the next recovery/save.
    error = notice.get('error') or ''
    return notice['status'] == 'waiting_configuration' or (notice['status'] == 'fault' and
        (error == 'No notification transport configured' or error.startswith('Notification outlet is not configured: ')))


def validate_notice(value):
    if not isinstance(value, dict) or set(value) - {'message', 'route', 'reply'} or not isinstance(value.get('message'), str) or not value['message'].strip():
        raise Invalid('Notification needs message and optional route/reply')
    if not isinstance(value.get('route', 'default'), str) or not value.get('route', 'default'):
        raise Invalid('Notification route must be nonempty')
    reply = value.get('reply')
    if reply is not None:
        if not isinstance(reply, dict) or set(reply) != {'event', 'key', 'schema'} or not all(isinstance(reply[k], str) and reply[k] for k in ('event', 'key')):
            raise Invalid('A question needs reply event, key and object schema')
        check_schema(reply['schema'])
        if reply['schema']['type'] != 'object':
            raise Invalid('Reply schema must describe an object of outputs')


def validate_channels(channels):
    if not isinstance(channels, dict):
        raise Invalid('channels must be an object')
    from loop_anything.runtime.implementations import validate_implementation
    for key, value in channels.items():
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', key) or key in ('workspace', 'default', 'user', 'external'):
            raise Invalid('Use a non-reserved channel ID')
        if not isinstance(value, dict) or set(value) - {'label', 'channel', 'identity', 'destination', 'command', 'cwd', 'timeout'}:
            raise Invalid('Channel supports label, channel, identity, destination, command, cwd, timeout')
        for field in ('label', 'channel', 'identity', 'destination'):
            if not isinstance(value.get(field, ''), str):raise Invalid('Channel metadata must be text')
        validate_implementation(dict(value, kind='command'))


def sender_for(store, run, route):
    requested=route
    route = run['settings'].get('notification_route', 'user') if route == 'default' else route
    if route == 'workspace':return route, {}
    if route in ('user','external'):
        command = run['settings'].get('notification_command')
        sender = {'command': command} if command else {}
        if run.get('notification_conversation_id'):
            from loop_anything.runtime.communication import service
            from loop_anything.runtime.communication_conversations import resolve
            binding=resolve(service(store),run['notification_conversation_id'],include_sender=True)
            sender=copy.deepcopy(binding['sender'])
            if sender.get('configuration_error'):
                from loop_anything.runtime.communication_conversations import entry_sender
                sender=entry_sender(service(store),binding['conversation'])
            if sender.get('configuration_error'):raise NotificationConfigurationError(sender['configuration_error'])
        if not sender.get('command') and requested=='default':
            # New installations work out of the box inside the platform.
            return 'workspace', {}
        if not sender.get('command'):
            raise NotificationConfigurationError('No notification transport configured')
        return route, copy.deepcopy(sender)
    config = store.notification_channels()['channels'].get(route)
    if config is None:raise NotificationConfigurationError('Notification outlet is not configured: ' + route)
    return route, copy.deepcopy(config)


def enqueue(store, run, key, notice, task_id=None, execution_id=None):
    validate_notice(notice)
    if not isinstance(key, str) or not key:raise Invalid('Notification key is required')
    fingerprint = digest([notice, task_id])
    old = next((n for n in run['notifications'] if n['id'] == key), None)
    if old:
        if old.get('fingerprint') != fingerprint:raise Conflict('Notification key already used for different content')
        return old
    row = dict(id=key, tasks=task_id, execution=execution_id, message=notice['message'], requested_route=notice.get('route','default'),
               status='pending', attempt=0, at=time.time(), fingerprint=fingerprint)
    if notice.get('reply'):row['reply'] = copy.deepcopy(notice['reply'])
    try:row['route'], row['sender'] = sender_for(store, run, row['requested_route'])
    except NotificationConfigurationError as exc:
        route=run['settings'].get('notification_route','user') if row['requested_route']=='default' else row['requested_route']
        row.update(route=route, status='waiting_configuration', error=str(exc))
    if run.get('notification_conversation_id') and row.get('route') in ('user','external'):
        from loop_anything.runtime.communication import service
        from loop_anything.runtime.communication_conversations import resolve
        row['conversation']=resolve(service(store),run['notification_conversation_id'])['conversation']
    run['notifications'].append(row)
    Store.log(run, 'notification', 'Notification queued', execution_id, {'notification_id':key, 'task_id':task_id})
    return row


def receive_event(run, event_id, name, payload, key=None, task_id=None):
    if run['status'] in ('terminated', 'completed'):raise Conflict('Run has ended')
    if not all(isinstance(v,str) and v for v in (event_id,name)) or not isinstance(payload,dict) or key is not None and not isinstance(key,str):
        raise Invalid('Event needs nonempty id/name, object payload and optional string key')
    old = next((x for x in run['events'] if x['id']==event_id), None)
    if old:
        if (old['name'],old['payload'],old.get('key'),old.get('task_id')) != (name,payload,key,task_id):raise Conflict('Event id already used for different data')
        return old
    row={'id':event_id,'name':name,'key':key,'payload':copy.deepcopy(payload),'at':time.time(),**({'task_id':task_id} if task_id else {})}
    run['events'].append(row);Store.log(run,'event','External event received: '+name)
    return row
