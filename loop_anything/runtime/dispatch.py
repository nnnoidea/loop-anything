"""Direct dispatch admission; existing runtime owns execution and session restoration."""
import copy
import json
import secrets
import time

from loop_anything.runtime.model import Invalid, Conflict, check_schema, digest
from loop_anything.runtime.team_transport import core


def choose(*args, **kwargs):
    try:return core.choose(*args, **kwargs)
    except ValueError as exc:raise Invalid(str(exc)) from exc


def accept(comm, message):
    from loop_anything.runtime.communication import identifier, clean
    config=comm.settings();gid=message['group_id'];instance=config['instance_id']
    payload=message['payload']
    for value in (message['id'],message['sender'],message['request_id'],message['assignment_id']):identifier(value)
    if (gid not in config['groups'] or message.get('version')!=1 or message['target']!=instance or
        payload.get('origin')!=message['sender'] or payload.get('id')!=message['request_id'] or
        payload.get('group_id')!=gid or payload.get('executor')!=instance or payload.get('target_instance')!=instance or
        payload.get('assignment_id')!=message['assignment_id'] or payload.get('protocol')!='direct-v1'):
        raise Invalid('Dispatch scope does not match its selected executor')
    identifier(payload['agent_id'])
    detached=payload.get('dispatch_client') is True
    if detached and (payload.get('kind')!='assistance' or payload.get('source') or payload.get('parent_request')):
        raise Invalid('Standalone dispatch cannot claim a source Run or worker scope')
    if not isinstance(payload.get('message'),str) or not payload['message'].strip() or not isinstance(payload.get('context'),dict):
        raise Invalid('Dispatch requires instructions and object context')
    check_schema(payload.get('result_schema',{'type':'object'}))
    if type(payload.get('deadline')) not in (int,float):raise Invalid('Dispatch requires an acceptance deadline')
    if payload.get('session',{}).get('mode') not in ('new','resume'):raise Invalid('Unknown session mode')
    # No command, local credential or mutable runtime bookkeeping comes from the medium.
    allowed={'id','origin','location','group_id','scope_group_id','kind','agent_id','target_instance','capability',
             'source','message','context','result_schema','session','source_summary','origin_name','created_at','deadline',
             'notification_origin','notification_route','notification_level','notification_policy','notification_level_explicit',
             'notification_conversation','previous_request_id','source_reference','parent_request','protocol','executor',
             'assignment_id','dispatch_client'}
    row={k:copy.deepcopy(v) for k,v in payload.items() if k in allowed}
    row.update(state='assigned',history=[],rpc={},logs=[],access_token=secrets.token_urlsafe(32))
    if detached:
        from loop_anything.runtime.collaboration import ensure_loop
        loop_key=ensure_loop(comm.store)
        row['notification_origin']=instance
        if payload.get('chat_context'):
            from loop_anything.runtime.communication_conversations import from_source
            row['notification_conversation']=from_source(comm,payload['chat_context'])
            row['notification_policy']='conversation'
    with comm.transaction() as db:
        old=db.execute('SELECT document FROM communication_requests WHERE id=?',(row['id'],)).fetchone()
        if old:
            old=json.loads(old[0])
            if old.get('dispatch_digest',digest(old.get('dispatch_envelope')))!=digest(message):raise Conflict('Request ID already used for different dispatch')
        else:
            continuation=comm.continuing_wait(row,db)
            agent=config['agents'].get(row['agent_id'])
            if row['deadline']<time.time():row.update(state='unavailable',error='Acceptance deadline expired before receiver admission')
            elif continuation and continuation['executor']==instance:
                row.update(accepted_at=time.time(),launch=copy.deepcopy(continuation['launch']),agent_label=continuation.get('agent_label',row['agent_id']))
            elif not agent or not comm.eligible(agent,row,config):row.update(state='unavailable',error='Named Agent is not accepting work in this team')
            else:row.update(accepted_at=time.time(),launch=copy.deepcopy(agent['implementation']),agent_label=agent['name'])
            row['executor_name']=config['name']
            row['dispatch_digest']=digest(message)
            if detached:
                from loop_anything.runtime.collaboration import attach
                previous=row.get('session',{}).get('request_id') or row.get('previous_request_id')
                collaboration_id=None
                if previous:
                    before=comm.get(previous,db)
                    if before['origin']!=row['origin'] or before.get('agent_id')!=row['agent_id']:raise Conflict('Follow-up source or Agent changed')
                    collaboration_id=before.get('collaboration',{}).get('run_id')
                attach(comm,row,loop_key,collaboration_id,db)
            comm.event(row,'accepted' if row['state']=='assigned' else 'unavailable')
            comm.save(db,row)
        from loop_anything.runtime.communication_archive import received
        db.execute('INSERT OR IGNORE INTO communication_inbox VALUES (?,?)',(message['id'],json.dumps(received(message))))
        if detached:
            from loop_anything.runtime.communication_archive import enqueue
            enqueue(db,message)
        else:comm.emit(db,row,message['sender'],'ack',{'message_id':message['id']})


def result_receipt(row):
    from loop_anything.runtime.model import digest
    return digest({k:row.get(k) for k in ('id','assignment_id','state','result','error','native_session')})


def publish_results(comm,media,gid):
    from loop_anything.runtime.communication_views import summary
    from loop_anything.runtime.model import digest
    published=getattr(comm,'_dispatch_result_revisions',{})
    compact=comm.settings()['groups'][gid].get('transport')=='feishu_base'
    for row in comm.requests():
        if not row.get('dispatch_client') or row.get('group_id')!=gid or row.get('executor')!=comm.settings()['instance_id']:continue
        result=summary(row)
        result.update(origin=row['origin'],executor=row['executor'],assignment_id=row['assignment_id'],
                      group_id=gid,session=row['session'],protocol='direct-v1',dispatch_client=True)
        if compact:
            result.pop('revision',None)
        fingerprint=digest({k:v for k,v in result.items() if k!='updated_at'}) if compact else row.get('revision',0)
        if published.get(row['id'])==fingerprint:continue
        media.put('results/'+row['id']+'.json',result)
        published[row['id']]=fingerprint
    comm._dispatch_result_revisions=published


def read_remote_logs(comm,row,after,offset,max_chars):
    from loop_anything.runtime.model import digest
    if row.get('mirror') or row['origin']!=comm.settings()['instance_id']:
        return {'logs':[],'logs_pending':False,'logs_error':'Read logs on the child request origin or executor platform','log_executor':row.get('executor')}
    args={'after':after,'offset':offset,'max_chars':max_chars};key=digest(args)
    with comm.transaction() as db:
        current=comm.get(row['id'],db);reads=current.setdefault('log_reads',{})
        query=reads.get(key)
        if query and query.get('result') is not None and (row['state'] in {'completed','failed','cancelled','unavailable','not_selected'} or time.time()-query['at']<15):
            return dict(query['result'],logs_pending=False)
        if not query or query.get('result') is not None:
            from loop_anything.runtime.store import uid
            query={'id':uid('logs'),'arguments':args,'at':time.time()};reads[key]=query
            comm.emit(db,current,current['executor'],'logs_request',query)
            # Only retain a small diagnostic cache; execution logs remain on the executor.
            completed=sorted((k for k,v in reads.items() if v.get('result') is not None),key=lambda k:reads[k]['at'])
            for k in completed[:-8]:reads.pop(k,None)
            comm.save(db,current)
    return {'logs':[],'log_cursor':after,'log_offset':offset,'log_more':True,'logs_pending':True,'log_query_id':query['id']}


def receive_read(comm,db,row,message):
    kind=message['kind'];payload=message['payload'];instance=comm.settings(db)['instance_id']
    if kind=='logs_response':
        if message['sender']!=row.get('executor') or row['origin']!=instance:raise Conflict('Log response is not from the executor')
        query=next((q for q in row.get('log_reads',{}).values() if q['id']==payload['id']),None)
        if query:
            page=payload['page']
            if not isinstance(page.get('logs'),list) or sum(len(x.get('text','')) for x in page['logs'])>query['arguments']['max_chars']:
                raise Invalid('Invalid diagnostic log page')
            query['result']={k:page[k] for k in ('logs','log_cursor','log_offset','log_more')}
            query['at']=time.time()
        return
    if message['sender']!=row['origin'] or row.get('executor')!=instance:raise Conflict('Read request has wrong owner')
    if kind=='logs_request':
        page=comm.read(row['id'],include_logs=True,**payload['arguments'])['request']
        comm.emit(db,row,row['origin'],'logs_response',{'id':payload['id'],
            'page':{k:page[k] for k in ('logs','log_cursor','log_offset','log_more')}})
    elif kind=='result_read':
        from loop_anything.runtime.communication import END
        if not row.get('dispatch_client') or row['state'] not in END or payload.get('receipt')!=result_receipt(row):
            raise Conflict('Read receipt does not match the completed result')
        row.update(result_consumed=True,result_read_at=time.time())
