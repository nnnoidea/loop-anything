"""Shared monitor instances and durable waits for an exact server Agent session."""
import copy
import json
import math
import os
import time
from contextlib import contextmanager

from loop_anything.runtime.model import Invalid, Conflict, digest, contract
from loop_anything.runtime.store import uid
from loop_anything.runtime import events, observations, timelines


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS work_objects(kind TEXT NOT NULL,id TEXT NOT NULL,document TEXT NOT NULL,
            PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS monitor_samples(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,monitor_id TEXT NOT NULL,call_id TEXT NOT NULL,
            document TEXT NOT NULL,UNIQUE(monitor_id,call_id));
    """)


def get(db, kind, ident):
    row=db.execute('SELECT document FROM work_objects WHERE kind=? AND id=?',(kind,ident)).fetchone()
    if row is None:raise Invalid('Unknown '+kind)
    return json.loads(row[0])


def put(db, kind, value):
    db.execute('INSERT INTO work_objects VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET document=excluded.document',
               (kind,value['id'],json.dumps(value,ensure_ascii=False)))


def rows(db, kind):
    return [json.loads(r[0]) for r in db.execute('SELECT document FROM work_objects WHERE kind=?',(kind,))]


@contextmanager
def transaction(store):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()


def session_auth(db, ident, token):
    session=get(db,'session',ident)
    if session['token']!=token:raise Conflict('Use your registered session token')
    return session


def public_session(value):
    result={k:v for k,v in value.items() if k not in ('token','implementation','process')}
    if value.get('process'):result['process']={k:value['process'].get(k) for k in ('pid','state','returncode')}
    if result.get('error'):result['error']=result['error'].replace(value['token'],'[REDACTED]')
    return result


def alive(pid):
    if not pid:return False
    try:os.kill(pid,0)
    except ProcessLookupError:return False
    except PermissionError:return True
    return True


def register_session(store, a):
    from loop_anything.runtime.native_sessions import resume_config
    from loop_anything.runtime.implementations import validate_implementation
    config=copy.deepcopy(a['implementation'])
    validate_implementation(config)
    if config['kind']!='agent' or config.get('executor') or config.get('dispatch'):
        raise Invalid('Register the actual server Agent session')
    native=a['native_session']
    resume_config(config,native)
    if type(a['process_id']) is not int or a['process_id']<=1 or not alive(a['process_id']):
        raise Invalid('Supply the current Agent process PID, not a tool subprocess')
    ident='session-'+digest([native['provider'],native['id']])[:24]
    with transaction(store) as db:
        prior=next((r for r in rows(db,'session') if r['id']==ident),None)
        if prior:
            if prior['process_id']!=a['process_id']:
                raise Conflict('Session is already registered; use its token and resume/handoff tools')
            return {'session_id':ident,'session_token':prior['token']}
        value=dict(id=ident,token=uid('session-token'),native_session=native,implementation=config,
                   process_id=a['process_id'],state='active',created_at=time.time(),wake=None)
        put(db,'session',value)
    return {'session_id':ident,'session_token':value['token']}


def steward_for(session):
    return dict(agent_id=session['id'],name=session['native_session']['id'],session_id=session['id'],
                implementation=copy.deepcopy(session['implementation']))


def claim_in_run(store, run, session):
    from loop_anything.runtime.steward import management_task
    from loop_anything.interfaces.agent_tasks import acquire_in_run
    from loop_anything.runtime.timeline_runtime import TimelineRuntime
    from loop_anything.runtime.implementations import selected
    from loop_anything.runtime.native_sessions import bind
    from types import SimpleNamespace
    if run.get('superseded_by'):raise Conflict('Use the continuation Run')
    if run.get('steward',{}).get('session_id')!=session['id']:raise Conflict('This session is not the Run owner')
    runtime=TimelineRuntime(SimpleNamespace(store=store))
    for task in run['tasks'].values():
        if not management_task(task):continue
        if task['status'] in ('executing','decision'):
            e=next(e for e in run['executions'] if e['id']==task['execution_id'])
            e['collaboration_caller_pid']=session.get('process_id')
            return dict(run_id=run['id'],task_id=task['id'],execution_id=e['id'],token=e['token'],timeline_id=run['timeline_id'])
        if task['status'] not in ('planned','ready','blocked'):continue
        values,sources,missing=runtime.resolve_inputs(run,task)
        if missing:continue
        e=runtime.new_execution(run,task,selected(run,task)[1],values,sources)
        e['status']=task['status']='decision'
        e['collaboration_caller_pid']=session.get('process_id')
        bind(run,e,session['native_session']['provider'],session['native_session']['id'],'starter',
             session['native_session'].get('cwd'))
        acquire_in_run(run,'background',e['token'],e['id'])
        return dict(run_id=run['id'],task_id=task['id'],execution_id=e['id'],token=e['token'],timeline_id=run['timeline_id'])
    return {'run_id':run['id'],'waiting':True,'timeline_id':run['timeline_id']}


def transfer_waits(db, timeline_id, previous_session, current_session):
    """Explicit takeover changes the recipient, never the observed conditions."""
    moved=[]
    for wait in rows(db,'wait'):
        if wait['timeline_id']==timeline_id and wait['session_id']==previous_session and wait['state'] in ('waiting','ready'):
            wait['previous_session_id']=previous_session
            wait['session_id']=current_session
            put(db,'wait',wait);moved.append(wait['id'])
    if moved:
        timelines.append(db,timeline_id,'wait-handoff:'+uid('handoff'),'接续会话接管已有等待；条件与来源保持不变。','action',
                         [{'wait_ids':moved,'session_id':current_session}],actor='platform')
    return moved


def start_run(store, a):
    from loop_anything.runtime import steward
    context=steward.request_context(store,a)
    with transaction(store) as db:
        session=session_auth(db,a['session_id'],a['session_token'])
        fingerprint=digest({k:v for k,v in a.items() if k!='session_token'})
        prior=db.execute('SELECT run_id,fingerprint,receipt FROM run_requests WHERE id=?',(a['request_id'],)).fetchone()
        if prior:
            if prior[1]!=fingerprint:raise Conflict('Request ID already used')
            return json.loads(prior[2])
        timeline_id=a.get('timeline_id')
        source=a.get('continue_run_id')
        if timeline_id and not source:
            source=timelines.get(db,timeline_id).get('active_run_id')
        if source:
            old=store._load(db,source)
            previous_session=old.get('steward',{}).get('session_id')
            if previous_session:
                previous=get(db,'session',previous_session)
                if previous['state']=='unknown' or (previous.get('wake') and previous_session!=session['id']):
                    raise Conflict('Previous session wake is active or unconfirmed; resolve it before continuing')
            if timeline_id and timeline_id!=old['timeline_id']:raise Invalid('Continuation must retain the original Timeline')
            timeline_id=old['timeline_id']
        if timeline_id:
            timeline=timelines.get(db,timeline_id)
            if timeline.get('active_run_id'):
                current=store._load(db,timeline['active_run_id'])
                if current['status'] not in ('completed','terminated') and source!=current['id']:
                    raise Conflict('This Timeline already has a Run; explicitly continue that Run after interruption')
        fields={k:a[k] for k in ('inputs','bindings','created_by','notification_route','notification_command') if k in a}
        if context.get('conversation_id'):fields['conversation_id']=context['conversation_id']
        run=store.create(a['key'],a['title'],authorization=a.get('constraints',''),timeline_id=timeline_id,
                         continue_run_id=source,_db=db,**fields)
        if not timeline_id and (a.get('objective') or a.get('message')):
            value=timelines.get(db,run['timeline_id'])
            timelines.update(db,value['id'],value['revision'],{'objective':a.get('objective') or a['message']})
            timelines.project(run,timelines.get(db,value['id']))
        if source and old.get('steward',{}).get('session_id')!=session['id']:
            transfer_waits(db,run['timeline_id'],old.get('steward',{}).get('session_id'),session['id'])
        current_timeline=timelines.get(db,run['timeline_id'])
        current_timeline['active_run_id']=run['id'];timelines.save(db,current_timeline)
        timelines.project(run,current_timeline)
        request=steward.start_in_run(run,steward_for(session),a['request_id'],a.get('message',''),
                                    {'inputs':run['inputs'],'timeline_id':run['timeline_id']},context=context)
        claim=claim_in_run(store,run,session)
        store._save(db,run)
        result=dict(claim,request_id=a['request_id'],status='accepted',
                    next='Read Timeline progress and the current Loop handbook; arrange the next work. Finish the management task after arranging work.')
        db.execute('INSERT INTO run_requests VALUES (?,?,?,?)',(a['request_id'],run['id'],fingerprint,json.dumps(result)))
        return result


def validate_script(script):
    if not isinstance(script,dict) or set(script)-{'command','cwd','timeout','description','parameter_schema','metrics'}:
        raise Invalid('Monitor script accepts command, cwd, timeout, description, parameter_schema and metrics')
    metrics=script.get('metrics',[])
    if not isinstance(metrics,list):raise Invalid('metrics must be an array')
    keys=set()
    for metric in metrics:
        if not isinstance(metric,dict) or set(metric)-{'key','label','unit'} or not isinstance(metric.get('key'),str) or not metric['key']:
            raise Invalid('Metric needs key and optional label/unit')
        if metric['key'] in keys or any(not isinstance(metric.get(k,''),str) for k in ('label','unit')):raise Invalid('Invalid or duplicate metric')
        keys.add(metric['key'])
    from loop_anything.runtime.implementations import validate_implementation
    validate_implementation(dict(kind='command',**{k:v for k,v in script.items() if k in ('command','cwd','timeout','parameter_schema')}))


def register_monitor(store,a):
    validate_script(a['script'])
    with transaction(store) as db:
        old=next((r for r in rows(db,'monitor_script') if r['id']==a['script_id']),None)
        revision=old['revision'] if old else 0
        if a['revision']!=revision:raise Conflict('Monitor script changed')
        value=dict(id=a['script_id'],revision=revision+1,script=a['script'])
        put(db,'monitor_script',value)
        return value


def start_monitor(store,a):
    interval=a['interval']
    if type(interval) not in (int,float) or not math.isfinite(interval) or interval<=0:raise Invalid('Positive finite interval required')
    if bool(a.get('script_id'))==bool(a.get('script')):raise Invalid('Use registered script_id or inline script')
    with transaction(store) as db:
        script=get(db,'monitor_script',a['script_id']) if a.get('script_id') else {'script':a['script']}
        validate_script(script['script'])
        if a.get('run_id'):store._load(db,a['run_id'])
        if script['script'].get('parameter_schema'):contract(a.get('parameters',{}),script['script']['parameter_schema'],'parameters')
        ident='monitor-'+digest(a['request_id'])[:24]
        fingerprint=digest(a)
        prior=next((r for r in rows(db,'monitor') if r['id']==ident),None)
        if prior:
            if prior['fingerprint']!=fingerprint:raise Conflict('Monitor request already used')
            return prior
        value=dict(id=ident,fingerprint=fingerprint,script=script,parameters=a.get('parameters',{}),
                   run_id=a.get('run_id'),interval=interval,status='running',next_at=time.time(),
                   sample=None,error=None,call_id=None,created_at=time.time())
        put(db,'monitor',value)
        return value


def result_columns(condition, alias, field):
    """Return the result names read by this condition, or None for the entire mapping."""
    names=set()
    for expr in expression_paths(condition):
        if not expr or expr == [alias] or expr == [alias,field]:
            return None
        if expr[:2] == [alias,field]:
            names.add(expr[2])
    return names


def expression_paths(expr):
    if isinstance(expr,dict):
        if 'path' in expr:
            path=expr['path']
            yield path.split('.') if isinstance(path,str) and path else list(path)
        for arg in expr.get('args',[]):
            yield from expression_paths(arg)


def retain_wait_sources(db,run,timeline):
    """Keep only deleted observations still needed by registered waits, in the deletion transaction."""
    for row in db.execute("SELECT document FROM work_objects WHERE kind='wait' AND json_extract(document,'$.state')='waiting'").fetchall():
        wait=json.loads(row[0])
        changed=False
        for alias,source in wait['sources'].items():
            kind=source['kind']
            if kind=='task' and source['id']==run['id']:
                task=run['tasks'].get(source.get('task_id'))
                if not task:continue
                state={'status':task['status'],'revision':task['revision']}
                field='outputs'
                records=timelines.output_records(run,task)
            elif kind=='run':
                old=wait.get('retained_sources',{}).get(alias)
                if source['id']!=run['id']:
                    if timeline['active_run_id']!=run['id']:continue
                    if old:
                        if old['timeline_id']!=timeline['id']:continue
                    elif not db.execute("SELECT 1 FROM runs WHERE id=? AND json_extract(document,'$.timeline_id')=?",
                                        (source['id'],timeline['id'])).fetchone():continue
                if old and timeline['active_run_id']!=run['id']:continue
                state={'id':run['id'],'timeline_id':timeline['id'],'status':run['status'],'revision':run['revision']}
                field='records'
                records={key:versions[-1] for key,versions in run['records'].items() if versions}
            else:
                continue
            needed=result_columns(wait['condition'],alias,field)
            refs={key:[r['id'],r['revision']] for key,r in records.items() if needed is None or key in needed}
            wait.setdefault('retained_sources',{})[alias]={'timeline_id':timeline['id'],'state':state,'refs':refs}
            changed=True
        if changed:put(db,'wait',wait)


def observe(store, source):
    with store.connection() as db:
        db.execute('BEGIN')
        return observe_in_db(store,db,source)


def observe_in_db(store,db,source,retained=None):
    kind=source['kind']
    if retained:
        ident=timelines.get(db,retained['timeline_id'])['active_run_id'] if kind=='run' else None
        if not ident:
            field='records' if kind=='run' else 'outputs'
            values={}
            for key,(rid,revision) in retained['refs'].items():
                row=db.execute('SELECT document FROM work_results WHERE timeline_id=? AND id=? AND revision=?',
                               (retained['timeline_id'],rid,revision)).fetchone()
                values[key]=json.loads(row[0])['value']
            return dict(retained['state'],**{field:values})
        source=dict(source,id=ident)
    if kind=='monitor':
        value=get(db,'monitor',source['id'])
        sample=value.get('sample')
        if not sample or value.get('error'):raise Invalid(value.get('error') or 'No monitor sample yet')
        if (value['status']!='completed' or 'max_age' in source) and time.time()-sample['at']>source.get('max_age',value['interval']*2+value['script']['script'].get('timeout',60)):
            raise Invalid('Monitor sample is stale')
        return dict(sample,status=value['status'])
    run=store._load(db,source['id'])
    if kind=='run':
        current_id=timelines.current_run_id(db,run)
        if run['id']!=current_id:run=store._load(db,current_id)
        return {'id':run['id'],'timeline_id':run['timeline_id'],'status':run['status'],'revision':run['revision'],
                'records':{k:v[-1]['value'] for k,v in run['records'].items() if v}}
    if kind=='task':
        task=run['tasks'].get(source.get('task_id'))
        if task is None:raise Invalid('Unknown observed Task')
        return dict(status=task['status'],revision=task['revision'],
                    outputs={port:record['value'] for port,record in timelines.output_records(run,task).items()})
    raise Invalid('Wait source must be run, task or monitor')


def register_wait(store,a):
    from loop_anything.runtime.checks import validate_expression
    if not a['sources']:raise Invalid('Wait needs sources')
    validate_expression(a['condition'])
    for alias,source in a['sources'].items():
        if not isinstance(source,dict) or set(source)-{'kind','id','task_id','max_age'} or source.get('kind') not in ('run','task','monitor') or not source.get('id'):
            raise Invalid('Invalid wait source')
        if 'max_age' in source and (type(source['max_age']) not in (int,float) or source['max_age']<=0 or not math.isfinite(source['max_age'])):raise Invalid('Invalid max_age')
    with transaction(store) as db:
        session=session_auth(db,a['session_id'],a['session_token'])
        timelines.get(db,a['timeline_id'])
        ident='wait-'+digest([session['id'],a['key']])[:24]
        fingerprint=digest({k:v for k,v in a.items() if k!='session_token'})
        prior=next((r for r in rows(db,'wait') if r['id']==ident),None)
        if prior:
            if prior['fingerprint']!=fingerprint:raise Conflict('Wait key already used; cancel it before registering a new key')
            return prior
        value=dict(id=ident,session_id=session['id'],timeline_id=a['timeline_id'],sources=a['sources'],
                   condition=a['condition'],message=a.get('message',''),fingerprint=fingerprint,
                   state='waiting',created_at=time.time(),next_at=0,error=None)
        put(db,'wait',value)
        timelines.append(db,a['timeline_id'],ident,'已登记等待','action',[{'wait_id':ident}],actor='platform')
        return value


def poll_wait(store, ident, *, changes_only=False):
    from loop_anything.runtime.checks import evaluate
    with transaction(store) as db:
        current=get(db,'wait',ident)
        if current['state']!='waiting':return current
        high=events.position(db)
        due=current.get('next_at')
        if changes_only and 'cursor' in current and (due is None or due>time.time()):
            if high==current['cursor']:return current
            if not events.wait_changed(db,current,current['cursor']):
                current['cursor']=high
                put(db,'wait',current)
                return current
        deadlines=[]
        for source in current['sources'].values():
            if source['kind']!='monitor':continue
            try:monitor=get(db,'monitor',source['id'])
            except Invalid:continue
            if monitor.get('sample') and (monitor['status']!='completed' or 'max_age' in source):
                expiry=monitor['sample']['at']+source.get('max_age',2*monitor['interval']+monitor['script']['script'].get('timeout',60))
                if expiry>time.time():deadlines.append(expiry)
        try:
            evidence={alias:observe_in_db(store,db,source,current.get('retained_sources',{}).get(alias))
                      for alias,source in current['sources'].items()}
            result=evaluate(current['condition'],evidence)
            if type(result) is not bool:raise Invalid('Wait condition must return boolean')
            error=None
        except (Invalid,KeyError,IndexError,TypeError,ValueError) as exc:
            result=False;error=str(exc);evidence={}
        current.update(error=error,next_at=min(deadlines,default=None),cursor=high)
        if result:
            current.pop('retained_sources',None)
            current.update(state='ready',evidence=evidence,triggered_at=time.time())
            timelines.append(db,current['timeline_id'],ident+':ready','等待条件已满足','action',
                             [{'wait_id':ident,'evidence':evidence}],actor='platform')
        put(db,'wait',current)
        return current


class WorkRuntime:
    def __init__(self,engine):
        self.engine=engine;self.store=engine.store
        with transaction(self.store) as db:
            observations.recover(db)
            for kind in ('monitor','session'):
                for value in rows(db,kind):
                    if value.get('call_id') or value.get('wake'):
                        value['status' if kind=='monitor' else 'state']='unknown'
                        value['error']='Service interrupted; inspect the recorded process before confirming stopped'
                        put(db,kind,value)

    def tick(self):
        with self.store.connection() as db:
            monitors=rows(db,'monitor');waits=rows(db,'wait');sessions=rows(db,'session')
            high=events.position(db)
        for item in monitors:
            if item['status']=='running' and not item.get('call_id') and item['next_at']<=time.time():
                with transaction(self.store) as db:
                    current=get(db,'monitor',item['id'])
                    if current['status']!='running' or current.get('call_id'):continue
                    current['call_id']=uid('monitor-call');put(db,'monitor',current)
                self.engine.futures.add(self.engine.pool.submit(self.monitor,current))
        for item in waits:
            if item['state']=='waiting' and (item.get('cursor')!=high or
                    (item.get('next_at') is not None and item['next_at']<=time.time())):
                poll_wait(self.store,item['id'],changes_only=True)
        observations.release_receipts(self.engine)
        for job in observations.collect(self.store):
            self.engine.futures.add(self.engine.pool.submit(observations.execute,self.engine,job))
        for session in sessions:
            self.wake(session['id'])

    def monitor(self,value):
        from loop_anything.runtime.host_runtime import run_command,CommandNotStopped
        from loop_anything.runtime.process_session import ProcessSession
        ident=value['id'];call_id=value['call_id'];script=value['script']['script']
        def changed(doc):
            with transaction(self.store) as db:
                current=get(db,'monitor',ident)
                if current.get('call_id')==call_id:current['process']=doc;put(db,'monitor',current)
        session=ProcessSession(call_id,script,changed)
        try:
            result=run_command(script['command'],json.dumps({'monitor_id':ident,'run_id':value['run_id'],'parameters':value['parameters']}),
                               script.get('timeout',60),script.get('cwd'),self.engine.stopping,session)
            if result.returncode:raise Invalid('Monitor failed: '+result.stderr[-2000:])
            data=json.loads(result.stdout)
            if not isinstance(data,dict):raise Invalid('Monitor must return a JSON object')
            error=None;unknown=False
        except Exception as exc:
            data=None;error=str(exc);unknown=isinstance(exc,CommandNotStopped)
        with transaction(self.store) as db:
            current=get(db,'monitor',ident)
            if current.get('call_id')!=call_id:return
            from loop_anything.runtime.monitoring import record_sample
            record_sample(db,ident,call_id,data,error)
            current.update(call_id=None if not unknown else call_id,error=error,next_at=time.time()+current['interval'])
            if unknown:current['status']='unknown'
            if data is not None:
                current['sample']={'at':time.time(),'data':data,'call_id':call_id}
                if data.get('done') is True:current['status']='completed'
            put(db,'monitor',current)

    def pending(self,session_id):
        with self.store.connection() as db:
            waits=[v for v in rows(db,'wait') if v['session_id']==session_id and v['state']=='ready']
        requests=[]
        from loop_anything.runtime.steward import management_task
        for run in self.store.list():
            if run.get('steward',{}).get('session_id')!=session_id or run.get('superseded_by'):continue
            for task in run['tasks'].values():
                if management_task(task) and task['status'] in ('planned','ready','blocked'):
                    _,_,missing=self.engine.timeline_runtime.resolve_inputs(run,task)
                    if not missing:requests.append({'run_id':run['id'],'task_id':task['id'],'timeline_id':run['timeline_id']})
        return waits,requests

    def wake(self,ident):
        waits,requests=self.pending(ident)
        if not waits and not requests:return
        with transaction(self.store) as db:
            session=get(db,'session',ident)
            if session['state'] not in ('idle','active') or session.get('wake') or alive(session.get('process_id')):return
            from loop_anything.runtime.native_sessions import active_native
            native=session['native_session']
            if active_native(db,native['provider'],native['id'],self.store):return
            call=uid('wake')
            session.update(state='running',wake=call)
            put(db,'session',session)
        self.engine.futures.add(self.engine.pool.submit(self.resume,session,waits,requests))

    def resume(self,session,waits,requests):
        from loop_anything.runtime.native_sessions import resume_config
        from loop_anything.runtime.process_session import ProcessSession
        from loop_anything.runtime.host_runtime import run_command,CommandNotStopped
        from loop_anything.paths import platform_skill_directory
        ident=session['id'];call=session['wake']
        with self.store.connection() as db:
            waits=[get(db,'wait',w['id']) for w in waits if get(db,'wait',w['id'])['state']=='ready']
        if not waits and not requests:
            with transaction(self.store) as db:
                current=get(db,'session',ident)
                if current.get('wake')==call:
                    current.update(state='idle',wake=None);put(db,'session',current)
            return
        config=resume_config(session['implementation'],session['native_session'])
        config['native_session']=session['native_session']
        def changed(doc):
            with transaction(self.store) as db:
                current=get(db,'session',ident)
                if current.get('wake')==call:
                    current['process']=doc
                    if doc.get('pid'):current['process_id']=doc['pid']
                    put(db,'session',current)
        process=ProcessSession(call,config,changed)
        context={'workspace_id':self.engine.communication.settings()['instance_id'],'session_id':ident,'session_token':session['token'],'waits':waits,'run_requests':requests,
                 'platform_url':getattr(self.engine,'platform_url',None),
                 'platform_client':str(platform_skill_directory()/'scripts/call.py')}
        prompt='继续当前会话。先读取关联 Timeline 的最新目标、限制和进度。用 claim_run 取得待处理 Run 的操作身份。等待已满足仅表示需要判断，不能重复启动已有工作。目标或限制修改后检查并向用户汇报，由用户决定额外调整。处理完用 acknowledge_wait 确认收到等待结果。\n'+json.dumps(context,ensure_ascii=False)
        unknown=False
        try:
            result=run_command(config['command'],prompt,config.get('timeout'),config.get('cwd'),self.engine.stopping,process,context=context)
            error=None if result.returncode==0 else 'Agent exited: '+str(result.returncode)
        except Exception as exc:
            error=str(exc);unknown=isinstance(exc,CommandNotStopped)
        _,remaining_requests=self.pending(ident)
        with transaction(self.store) as db:
            current=get(db,'session',ident)
            if current.get('wake')!=call:return
            current.update(state='unknown' if unknown else 'failed' if error else 'idle',
                           wake=call if unknown else None,error=error)
            if not unknown:current['process_id']=None
            # Require an explicit retry for unacknowledged work after a successful but incomplete turn.
            if not error and (remaining_requests or any(get(db,'wait',w['id'])['state']=='ready' for w in waits)):
                current.update(state='failed',error='Wake finished without acknowledging its waits; inspect before retry')
            put(db,'session',current)
