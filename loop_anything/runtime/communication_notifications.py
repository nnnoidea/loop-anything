"""Group notification bindings and durable delivery through one configured machine.

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
    path=root/'notifications.json'
    previous=json.loads(path.read_text()) if path.exists() else None
    if (previous or {}).get('id','')!=args.get('binding_id',''):
        raise Conflict('Group notification binding changed; reload before replacing it')
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


def refresh(comm,gid,group):
    from loop_anything.runtime.communication import identifier
    path=Path(group['path'])/'notifications.json'
    if not path.exists():return  # A missing mount/file must not erase an already selected destination.
    binding=json.loads(path.read_text())
    allowed={'id','group_id','enabled','sender_instance','sender_name','level','created_at','route','label','channel','identity','destination'}
    if not isinstance(binding,dict) or set(binding)-allowed or binding.get('group_id')!=gid or type(binding.get('enabled')) is not bool:
        raise Invalid('Invalid group notification binding')
    identifier(binding['id']);identifier(binding['sender_instance'])
    if binding.get('level') not in ('attention','key','detailed'):raise Invalid('Invalid notification level')
    if binding.get('enabled') and not isinstance(binding.get('route'),str):raise Invalid('Missing group outlet')
    if group.get('notification_binding')==binding:return
    with comm.transaction() as db:
        config=comm.settings(db)
        config['groups'][gid]['notification_binding']=binding;config['revision']+=1
        db.execute('UPDATE communication_settings SET document=? WHERE id=1',(json.dumps(config),))
    group['notification_binding']=binding


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
               (delivery['id'],json.dumps(delivery)))


def accept(comm,db,message):
    from loop_anything.runtime.communication import identifier
    p=message['payload'];ident=identifier(p['notice_id']);attempt=p['attempt']
    if type(attempt) is not int or attempt<1 or not isinstance(p.get('payload'),dict):raise Invalid('Invalid notification delivery')
    old=db.execute('SELECT document FROM communication_deliveries WHERE id=?',(ident,)).fetchone()
    if old:
        row=json.loads(old[0])
        if (row['source_instance'],row['request_id'],row['group_id'],row['binding_id'],row['payload'])!=(message['sender'],message['request_id'],message['group_id'],p['binding_id'],p['payload']):
            raise Conflict('Notification ID reused with different delivery')
        if attempt<=row['attempt']:
            if row['status'] not in ('queued','sending'):reply(comm,db,row)
            return
        if attempt!=row['attempt']+1 or row['status'] not in ('fault','waiting_configuration'):
            raise Conflict('Only explicitly retry a failed delivery')
        row.setdefault('history',[]).append({k:row.get(k) for k in ('attempt','status','receipt','error')})
    else:
        if attempt!=1:raise Invalid('First delivery attempt must be 1')
        row={'id':ident,'source_instance':message['sender'],'request_id':message['request_id'],
             'group_id':message['group_id'],'binding_id':p['binding_id'],'payload':p['payload'],'history':[]}
    row.update(attempt=attempt,status='queued',error=None,receipt=None)
    record=db.execute('SELECT document FROM communication_notification_bindings WHERE id=?',(p['binding_id'],)).fetchone()
    binding=json.loads(record[0]) if record else None
    if not binding or binding['group_id']!=row['group_id'] or binding['sender_instance']!=comm.settings(db)['instance_id'] or not binding['enabled']:
        row.update(status='waiting_configuration',error='This machine has not authorized the requested group notification binding')
    elif not comm.settings(db)['groups'].get(row['group_id'],{}).get('enabled'):
        row.update(status='waiting_configuration',error='Notification sender has left this group; rejoin before retry')
    else:row['sender']=binding['sender']
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
    if not notice or request.get('notification_origin',request['origin'])!=comm.settings(db)['instance_id'] or (binding.get('id'),binding.get('group_id'),binding.get('sender_instance'))!=(p['binding_id'],message['group_id'],message['sender']):
        raise Conflict('Receipt does not belong to this source/binding')
    if type(p['attempt']) is not int or p['attempt']>notice['attempt']:raise Invalid('Unexpected delivery attempt')
    if p['attempt']<notice['attempt']:return
    if p['status'] not in ('delivered','fault','waiting_configuration'):raise Invalid('Invalid delivery receipt state')
    if p['status']=='delivered' and (not isinstance(p.get('receipt'),dict) or p['receipt'].get('delivered') is not True):raise Invalid('Delivery needs a positive transport receipt')
    if notice['status']=='delivered':return
    notice.update({k:p.get(k) for k in ('status','receipt','error')})
    comm.save(db,request)


def recover(comm,db):
    if comm.identity_conflict:return
    for record in db.execute('SELECT document FROM communication_deliveries').fetchall():
        row=json.loads(record[0])
        if row['status']=='sending':
            row.update(status='fault',error='Interrupted delivery: outcome unknown; verify before retry')
            save(db,row);reply(comm,db,row)


def deliver(comm):
    from loop_anything.runtime.notifications import deliver_command
    from loop_anything.runtime.host_runtime import run_command
    with comm.store.connection() as db:
        pending=[json.loads(r[0]) for r in db.execute("SELECT document FROM communication_deliveries WHERE json_extract(document,'$.status')='queued'")]
    for item in pending:
        with comm.transaction() as db:
            row=json.loads(db.execute('SELECT document FROM communication_deliveries WHERE id=?',(item['id'],)).fetchone()[0])
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
                row.update(receipt=deliver_command(sender,payload,run_command),status='delivered',error=None)
            except Exception as exc:row.update(status='fault',error=str(exc))
            with comm.transaction() as db:
                save(db,row);reply(comm,db,row)
        comm.engine.futures.add(comm.engine.pool.submit(send))
