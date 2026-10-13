"""Per-machine group outlets and durable delivery through one selected sender.

Only public routing metadata crosses NAS. Commands are frozen locally when the
owner binds an outlet; a remote request can never supply a command or destination.
"""
import copy
import json
import time
from pathlib import Path

from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.store import uid


def configure(comm, args):
    from loop_anything.runtime.communication import atomic_json
    from loop_anything.runtime.notifications import sender_for
    if comm.identity_conflict:raise Conflict('Resolve this machine identity before binding notifications')
    config=comm.settings();gid=args['group_id'];group=config['groups'].get(gid)
    if not group or not group['enabled']:raise Invalid('Choose a joined group')
    root=Path(group['path'])
    if json.loads((root/'group.json').read_text()).get('id')!=gid:raise Invalid('Group identity changed')
    refresh(comm,gid,group)
    previous=group.get('notification_bindings',{}).get(config['instance_id'])
    path=root/'notification-bindings'/(config['instance_id']+'.json')
    if (previous or {}).get('id','')!=args.get('binding_id',''):
        raise Conflict('This machine notification binding changed; reload before replacing it')
    enabled=args.get('enabled',True);level=args.get('notification_level','key')
    if type(enabled) is not bool or level not in ('attention','key','detailed'):raise Invalid('Invalid notification setting')
    binding={'id':uid('binding'),'group_id':gid,'enabled':enabled,'sender_instance':config['instance_id'],
             'sender_name':config['name'],'level':level,'created_at':time.time()}
    sender=None
    if enabled:
        route=args.get('notification_route')
        if route not in comm.store.notification_channels()['channels']:raise Invalid('Select a named outlet configured on this sending machine')
        _,sender=sender_for(comm.store,{'settings':{}},route)
        binding.update(route=route,**{k:sender.get(k,'') for k in ('label','channel','identity','destination')})
    # Authorize the immutable binding locally before making it discoverable.
    with comm.transaction() as db:
        db.execute('INSERT INTO communication_notification_bindings VALUES (?,?)',(binding['id'],json.dumps(dict(binding,sender=sender))))
    atomic_json(path,binding)
    refresh(comm,gid,group)
    return {'configuration':comm.settings(),'notification_binding':binding}


def validate_binding(binding,gid,instance=None):
    from loop_anything.runtime.communication import identifier
    allowed={'id','group_id','enabled','sender_instance','sender_name','level','created_at','route','label','channel','identity','destination'}
    if not isinstance(binding,dict) or set(binding)-allowed or binding.get('group_id')!=gid or type(binding.get('enabled')) is not bool:
        raise Invalid('Invalid group notification binding')
    identifier(binding['id']);identifier(binding['sender_instance'])
    if instance and binding['sender_instance']!=instance:raise Invalid('Binding file belongs to another machine')
    if binding.get('level') not in ('attention','key','detailed'):raise Invalid('Invalid notification level')
    if binding.get('enabled') and not isinstance(binding.get('route'),str):raise Invalid('Missing group outlet')
    return binding


def refresh(comm,gid,group):
    root=Path(group['path'])
    bindings=copy.deepcopy(group.get('notification_bindings',{}))
    # Legacy single-sender configuration becomes an entry for that machine, not a group-wide fallback.
    legacy=root/'notifications.json'
    if legacy.exists():
        binding=validate_binding(json.loads(legacy.read_text()),gid)
        bindings.setdefault(binding['sender_instance'],binding)
    for path in (root/'notification-bindings').glob('*.json'):
        binding=validate_binding(json.loads(path.read_text()),gid,path.stem)
        bindings[binding['sender_instance']]=binding
    if group.get('notification_bindings')==bindings:return
    with comm.transaction() as db:
        config=comm.settings(db)
        config['groups'][gid]['notification_bindings']=bindings;config['revision']+=1
        config['groups'][gid].pop('notification_binding',None)
        db.execute('UPDATE communication_settings SET document=? WHERE id=1',(json.dumps(config),))
    group['notification_bindings']=bindings
    group.pop('notification_binding',None)


def select_binding(comm,request,state):
    group_id=request.get('scope_group_id') or request.get('group_id')
    config=comm.settings()
    bindings=config['groups'].get(group_id,{}).get('notification_bindings',{})
    origin=request['origin']
    actor=request.get('executor') if state in ('running','completed','failed') else origin
    actor=actor or origin
    route={'policy':'actor_first','actor_instance':actor,'request_origin':origin,'sender_instance':None,'reason':'no_bound_outlet'}
    for instance,reason in ((actor,'action_machine'),(origin,'request_origin')):
        binding=bindings.get(instance)
        if binding and binding['enabled']:
            route.update(sender_instance=instance,reason=reason,binding_id=binding['id'])
            return copy.deepcopy(binding),route
    return None,route


def queue(comm,db,request,notice):
    binding=notice['group_binding']
    notice['status']='awaiting_delivery'
    packet={'notice_id':notice['id'],'binding_id':binding['id'],'attempt':notice['attempt'],'payload':notice['payload']}
    reference={'id':request['id'],'group_id':binding['group_id']}
    if binding['sender_instance']==comm.settings(db)['instance_id']:
        accept(comm,db,dict(reference,request_id=request['id'],sender=comm.settings(db)['instance_id'],payload=packet))
    else:comm.emit(db,reference,binding['sender_instance'],'notification_deliver',packet)


def save(db,delivery):
    db.execute('INSERT INTO communication_deliveries VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
               (delivery.get('delivery_key',delivery['id']),json.dumps(delivery)))


def accept(comm,db,message):
    from loop_anything.runtime.communication import identifier
    p=message['payload'];ident=identifier(p['notice_id']);attempt=p['attempt']
    if type(attempt) is not int or attempt<1 or not isinstance(p.get('payload'),dict):raise Invalid('Invalid notification delivery')
    key=ident+':'+p['binding_id']
    old=db.execute('SELECT document FROM communication_deliveries WHERE id=?',(key,)).fetchone()
    if not old:old=db.execute('SELECT document FROM communication_deliveries WHERE id=?',(ident,)).fetchone()
    if not old:
        previous=db.execute("SELECT document FROM communication_deliveries WHERE json_extract(document,'$.id')=?",(ident,)).fetchall()
        for record in previous:
            prior=json.loads(record[0])
            if not p['payload'].get('conversation') or prior['status']!='not_sent' or (prior['source_instance'],prior['request_id'],prior['payload'])!=(message['sender'],message['request_id'],p['payload']):
                raise Conflict('Notification ID already attempted through another binding')
    if old:
        row=json.loads(old[0])
        if (row['source_instance'],row['request_id'],row['group_id'],row['binding_id'],row['payload'])!=(message['sender'],message['request_id'],message['group_id'],p['binding_id'],p['payload']):
            raise Conflict('Notification ID reused with different delivery')
        if attempt<=row['attempt']:
            if row['status'] not in ('queued','sending'):reply(comm,db,row)
            return
        if attempt!=row['attempt']+1 or row['status'] not in ('fault','waiting_configuration','not_sent'):
            raise Conflict('Only explicitly retry a failed delivery')
        row.setdefault('history',[]).append({k:row.get(k) for k in ('attempt','status','receipt','error')})
    else:
        if attempt!=1:raise Invalid('First delivery attempt must be 1')
        row={'id':ident,'delivery_key':key,'source_instance':message['sender'],'request_id':message['request_id'],
             'group_id':message['group_id'],'binding_id':p['binding_id'],'payload':p['payload'],'history':[]}
    row.update(attempt=attempt,status='queued',error=None,receipt=None)
    record=db.execute('SELECT document FROM communication_notification_bindings WHERE id=?',(p['binding_id'],)).fetchone()
    binding=json.loads(record[0]) if record else None
    if not binding or binding['group_id']!=row['group_id'] or binding['sender_instance']!=comm.settings(db)['instance_id'] or not binding['enabled']:
        row.update(status='waiting_configuration',error='This machine has not authorized the requested group notification binding')
    elif row['group_id'] and not comm.settings(db)['groups'].get(row['group_id'],{}).get('enabled'):
        row.update(status='waiting_configuration',error='Notification sender has left this group; rejoin before retry')
    else:row['sender']=binding['sender']
    if row['status']=='waiting_configuration' and p['payload'].get('conversation'):row['status']='not_sent'
    save(db,row)
    if row['status']!='queued':reply(comm,db,row)


def reply(comm,db,row):
    result={k:row.get(k) for k in ('attempt','status','receipt','error')}
    result.update(notice_id=row['id'],binding_id=row['binding_id'])
    if row['source_instance']==comm.settings(db)['instance_id']:
        receive_receipt(comm,db,{'request_id':row['request_id'],'group_id':row['group_id'],
                              'sender':comm.settings(db)['instance_id'],'payload':result})
    else:comm.emit(db,{'id':row['request_id'],'group_id':row['group_id']},row['source_instance'],'notification_receipt',result)


def receive_receipt(comm,db,message):
    p=message['payload'];request=comm.get(message['request_id'],db)
    notice=next((n for n in request.get('notifications',[]) if n['id']==p['notice_id']),None)
    binding=(notice or {}).get('group_binding',{})
    if notice and any(a['binding']['id']==p['binding_id'] and a['binding']['sender_instance']==message['sender'] for a in notice.get('routing_attempts',[])):return
    if not notice or request.get('notification_origin',request['origin'])!=comm.settings(db)['instance_id'] or (binding.get('id'),binding.get('group_id'),binding.get('sender_instance'))!=(p['binding_id'],message['group_id'],message['sender']):
        raise Conflict('Receipt does not belong to this source/binding')
    if type(p['attempt']) is not int or p['attempt']>notice['attempt']:raise Invalid('Unexpected delivery attempt')
    if p['attempt']<notice['attempt']:return
    if p['status'] not in ('delivered','fault','waiting_configuration','not_sent'):raise Invalid('Invalid delivery receipt state')
    if p['status']=='delivered' and (not isinstance(p.get('receipt'),dict) or p['receipt'].get('delivered') is not True):raise Invalid('Delivery needs a positive transport receipt')
    if notice['status']=='delivered':return
    if p['status']=='not_sent' and notice.get('fallback_binding'):
        notice.setdefault('routing_attempts',[]).append({'binding':binding,'error':p.get('error'),'status':'not_sent'})
        notice['group_binding']=notice.pop('fallback_binding')
        notice['routing'].update(reason='entry_bot_fallback',sender_instance=notice['group_binding']['sender_instance'],binding_id=notice['group_binding']['id'])
        notice.update(status='awaiting_delivery',attempt=1,error=None)
        comm.save(db,request)
        queue(comm,db,request,notice)
        return
    if p['status']=='not_sent':p=dict(p,status='fault')
    notice.update({k:p.get(k) for k in ('status','receipt','error')})
    if p['status']=='delivered' and request.get('notification_conversation'):
        from loop_anything.runtime.communication_conversations import remember_context
        remember_context(comm,db,request['notification_conversation'],p.get('receipt'))
    comm.save(db,request)


def recover(comm,db):
    if comm.identity_conflict:return
    for record in db.execute('SELECT document FROM communication_deliveries').fetchall():
        row=json.loads(record[0])
        if row.get('identity_read_only'):continue
        if row['status']=='sending':
            row.update(status='fault',error='Interrupted delivery: outcome unknown; verify before retry')
            save(db,row);reply(comm,db,row)


def deliver(comm):
    from loop_anything.runtime.notifications import deliver_command, NotificationNotSent, NotificationConfigurationError
    from loop_anything.runtime.host_runtime import run_command
    with comm.store.connection() as db:
        pending=[json.loads(r[0]) for r in db.execute("SELECT document FROM communication_deliveries WHERE json_extract(document,'$.status')='queued'")]
    for item in pending:
        if item.get('identity_read_only'):continue
        with comm.transaction() as db:
            row=json.loads(db.execute('SELECT document FROM communication_deliveries WHERE id=?',(item.get('delivery_key',item['id']),)).fetchone()[0])
            if row['status']!='queued':continue
            binding=db.execute('SELECT document FROM communication_notification_bindings WHERE id=?',(row['binding_id'],)).fetchone()
            if not binding or json.loads(binding[0])['sender_instance']!=comm.settings(db)['instance_id']:
                row.update(status='waiting_configuration',error='Binding belongs to a different platform identity')
                save(db,row)
                continue  # A copied workspace cannot send or issue receipts as its original machine.
            row['status']='sending';save(db,row)
        def send(row=copy.deepcopy(row)):
            try:
                sender=row['sender'];payload=dict(row['payload'],id=row['id'])
                payload['outlet']={k:sender[k] for k in ('channel','identity','destination') if k in sender}
                if payload.get('conversation'):payload['outlet']['destination']=payload['conversation']['session_key']
                row.update(receipt=deliver_command(sender,payload,run_command),status='delivered',error=None)
            except NotificationNotSent as exc:row.update(status='not_sent',error=str(exc))
            except NotificationConfigurationError as exc:row.update(status='waiting_configuration',error=str(exc))
            except Exception as exc:row.update(status='fault',error=str(exc))
            with comm.transaction() as db:
                save(db,row);reply(comm,db,row)
        comm.engine.futures.add(comm.engine.pool.submit(send))
