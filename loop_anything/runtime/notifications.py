"""Named local notification outlets and one durable outbox in each Timeline."""
import copy
import re
import time
from loop_anything.runtime.model import Invalid, Conflict, digest, check_schema
from loop_anything.runtime.store import Store


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
        if not sender.get('command') and requested=='default':
            # New installations work out of the box inside the platform.
            return 'workspace', {}
        return route, copy.deepcopy(sender)
    config = store.notification_channels()['channels'].get(route)
    if config is None:raise Invalid('Notification outlet is not configured: ' + route)
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
    except Invalid as exc:
        route=run['settings'].get('notification_route','user') if row['requested_route']=='default' else row['requested_route']
        row.update(route=route, status='fault', error=str(exc))
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
