"""Workspace tools for independent Timelines, current sessions, monitoring and waits."""
import copy
from loop_anything.interfaces.agent_tasks import object_schema
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime import timelines, work

T={'type':'string','minLength':1}
TEXT={'type':'string'}
O={'type':'object'}
N={'type':'integer','minimum':0}
SESSION={'session_id':T,'session_token':T}


def definitions():
    page = {'timeline_id':T,'type':T,'id':T,'offset':N,'limit':{'type':'integer','minimum':1,'maximum':200},'as_of':N}
    entries=[
        ('query_run_facts','Read compact facts for selected Runs. Omit group_by for individual rows; [] gives totals. Group and filter on this source’s fields, e.g. attempts by node/version/status, history by kind/event or observations by subject/status. Pagination applies to output rows after aggregation. Filters match exact scalar values. Times are seconds; missing values are unknown.',
         {'run_ids':{'type':'array','items':T},'source':{'enum':['runs','tasks','attempts','history','diagnostics','notifications','observations']},
          'filters':O,'group_by':{'type':'array','items':T},'order_by':T,'descending':{'type':'boolean'},'offset':N,'limit':{'type':'integer','minimum':1,'maximum':200}},['run_ids','source'],True),
        ('read_execution_attempt','Read the timing, progress, error and result references for one exact execution, including earlier attempts.',{'run_id':T,'execution_id':T},['run_id','execution_id'],True),
        ('read_observations','Read the saved views and effective observation arrangements for a Timeline.',{'timeline_id':T},['timeline_id'],True),
        ('update_run_method','Hot-apply an installed version or opt in/out of published updates. Patch named observations; null disables, inherit restores Loop defaults. Existing tasks keep their method.',{'run_id':T,'token':T,'key':T,'follow':{'type':'boolean'},'observations':O,'inherit':{'type':'array','items':T}},['run_id','token'],False),
        ('refresh_observation','Generate the current view now, without sending a notification. Confirm a stopped process only when explicitly recovering an interrupted attempt.',{'run_id':T,'token':T,'name':T,'confirmed_stopped':{'type':'boolean'}},['run_id','token','name'],False),
        ('read_monitor_dashboard','Read-only monitoring overview: Run states, saved result charts, external monitor samples and pending waits. Never starts or polls scripts. Run summaries exclude execution archives and credentials.',
         {'offset':N,'limit':{'type':'integer','minimum':1,'maximum':100}},[],True),
        ('read_monitor_history','Read up to 240 retained checks for one monitor. Supply metric to receive only its timestamp/value points, with gaps for failed or missing readings.',
         {'monitor_id':T,'metric':T,'limit':{'type':'integer','minimum':1,'maximum':240}},['monitor_id'],True),
        ('create_timeline','Create work context without a Loop/Run. Only objective and constraints are fixed user semantic fields.',
         {'objective':TEXT,'constraints':TEXT,'title':TEXT},[],False),
        ('export_timeline','Download complete Timeline progress, business record history, saved results and progress entries. Never exports sessions, implementations or executable authority; external files remain references.',
         {'timeline_id':T},['timeline_id'],True),
        ('import_timeline','Import a Timeline progress document into this platform as independent work. Keep request_id stable for retries. Creates no Run or executable task. The receiving Agent reads the progress and arranges its own method.',
         {'document':O,'request_id':T},['document','request_id'],False),
        ('list_timelines','List Timelines by recent business progress with a compact preview and Loop group counts. Groups use Loop identity across versions; unbound=true selects temporary work without an associated Run. Follow next_offset for further pages.',
         {'loop_id':T,'unbound':{'type':'boolean'},'limit':{'type':'integer','minimum':1,'maximum':100},'offset':N},[],True),
        ('read_work_timeline','Read current intent, Loop-defined business state, saved results, related Run links and paged history. Set newest_first=true to read newest to oldest using the returned cursor as after. Execution state is available through read_run(view=snapshot). No handoff or original chat transcript is required.',
         {'timeline_id':T,'after':N,'newest_first':{'type':'boolean'},'limit':{'type':'integer','minimum':1,'maximum':200}},['timeline_id'],True),
        ('read_work_result','Read an exact saved result through its Timeline, including imported results; no original Run or Loop is required. Omit revision for the latest saved version.',
         {'timeline_id':T,'id':T,'revision':{'type':'integer','minimum':1},'as_of':N},['timeline_id','id'],True),
        ('read_work_results','Read a filtered page of formal result versions in commit order. Use the observation results cutoff for a pinned read.',page,['timeline_id'],True),
        ('read_business_state','Read Loop-defined current or historical business records through a Timeline; omitted type/id lists current records with explicit pagination.',
         dict(page,revision=N),['timeline_id'],True),
        ('update_timeline','Edit objective/constraints at the read revision. Follow the returned notice: inspect the whole Timeline, especially running tasks, and report to the user. Does NOT pause, cancel, invalidate, or reschedule any work.',
         {'timeline_id':T,'revision':N,'change':O,'message':TEXT},['timeline_id','revision','change'],False),
        ('append_timeline','Append a note, progress or decision. Stable key deduplicates. References identify evidence. To publish a Loop review to RSI from any entry point, supply review={loop_id,run_count}.',
         {'timeline_id':T,'key':T,'text':TEXT,'kind':{'enum':['note','progress','decision']},'refs':{'type':'array','items':O},
          'review':object_schema({'loop_id':T,'run_count':N},['loop_id'])},
         ['timeline_id','key','text'],False),
        ('register_work_session','Register this exact server Agent session and actual Agent PID, with implementation and resumable native identity. Does not start a Run or launch another Agent. Retain returned session token.',
         {'native_session':O,'implementation':O,'process_id':{'type':'integer','minimum':2}},['native_session','implementation','process_id'],False),
        ('read_work_session','Inspect your session and ready waits; does not resume anything.',SESSION,list(SESSION),True),
        ('resolve_continuation','Explicitly resolve a continued Task: retry_monitor restarts only the original failed observer; retry starts new work only after confirming the original job stopped; cancel stops this wait, not the original job.',
         dict(run_id=T,task_id=T,operation={'enum':['retry_monitor','retry','cancel']},reason=T,confirmed_stopped={'type':'boolean'}),
         ['run_id','task_id','operation','reason'],False),
        ('resume_work_session','Explicitly retry a failed/unknown wake after confirming the previous process stopped. Does not acknowledge pending events.',
         dict(SESSION,confirmed_stopped={'const':True}),[*SESSION,'confirmed_stopped'],False),
        ('wait_for','Persist a wait for named Run/Task/monitor/schedule sources and a deterministic condition. source={kind:run|task|monitor|schedule,id,task_id?,max_age?}; condition reads sources by alias using path/op/args. A run source follows its Timeline current Run across continuation; a task source observes that exact Task and its committed output versions. A schedule source reads the current platform host registry and exposes status, terminal, last_result and error. For a managed plan, use message to describe the trigger and what to do after waking. Keeps this exact session. Finish active Run turns and exit the Agent process so it can be resumed. Does not create a Loop.',
         dict(SESSION,timeline_id=T,key=T,sources=O,condition=O,message=TEXT),[*SESSION,'timeline_id','key','sources','condition'],False),
        ('read_wait','Read state, evidence or query error of a wait.',{'wait_id':T},['wait_id'],True),
        ('cancel_wait','Cancel your wait, without cancelling observed Runs or monitors.',dict(SESSION,wait_id=T),[*SESSION,'wait_id'],False),
        ('acknowledge_wait','Acknowledge that this session has handled a ready wait; original evidence remains recorded.',
         dict(SESSION,wait_id=T),[*SESSION,'wait_id'],False),
        ('register_monitor','Register/update a reusable script definition; revision=0 creates. Does not execute. script has command argv, optional cwd/timeout/description/parameter_schema and optional metrics=[{key,label,unit}] and display (stat, table, bars, trend). Each check reads JSON {parameters,run_id,monitor_id} on stdin and writes a JSON object; done=true ends an instance.',
         {'script_id':T,'revision':N,'script':O},['script_id','revision','script'],False),
        ('list_monitor_scripts','List reusable monitor definitions.',{},[],True),
        ('start_monitor','Explicitly start an instance from script_id or an inline script (exactly one). Optional run_id associates an experiment-specific instance; omit for a standing monitor. Parameters isolate instances. Existing Loop observe scripts remain supported. Snapshot the script for this instance.',
         {'request_id':T,'script_id':T,'script':O,'parameters':O,'run_id':T,'interval':{'type':'number','exclusiveMinimum':0}},
         ['request_id','interval'],False),
        ('read_monitor','Read latest sample, sample time, execution state and errors.',{'monitor_id':T},['monitor_id'],True),
        ('list_monitors','List monitor instances; optional run_id filters.',{'run_id':T},[],True),
        ('stop_monitor','Stop future checks only; does not stop the observed experiment or shared waiters.',{'monitor_id':T},['monitor_id'],False),
        ('restart_monitor','Explicitly restart stopped/failed monitoring; unknown processes require confirmed_stopped=true.',
         {'monitor_id':T,'confirmed_stopped':{'type':'boolean'}},['monitor_id'],False)
    ]
    return [dict(name=n,description=d,inputSchema=object_schema(p,r),annotations={'readOnlyHint':ro}) for n,d,p,r,ro in entries]


def call(store,name,a):
    if name=='read_execution_attempt':
        from loop_anything.runtime.run_facts import read_attempt
        return read_attempt(store,**a)
    if name=='query_run_facts':
        from loop_anything.runtime.run_facts import query
        return query(store,**a)
    if name=='read_observations':
        from loop_anything.runtime.observations import overview
        with store.connection() as db:
            db.execute('BEGIN')
            timelines.get(db,a['timeline_id'])
            return overview(db,a['timeline_id'])
    if name in ('update_run_method','refresh_observation'):
        from loop_anything.runtime import run_methods,observations
        from loop_anything.interfaces.agent_tasks import guard_write
        with work.transaction(store) as db,store.edit(a['run_id'],_db=db) as run:
            if name=='update_run_method':return run_methods.configure(store,db,run,a)
            guard_write(run,a['token'])
            return observations.refresh(db,run,a['name'],a.get('confirmed_stopped',False))
    if name in ('read_monitor_dashboard','read_monitor_history'):
        from loop_anything.runtime import monitoring
        return monitoring.overview(store,**a) if name=='read_monitor_dashboard' else monitoring.history(store,**a)
    if name in ('export_timeline','import_timeline'):
        from loop_anything.runtime import timeline_transfer
        return getattr(timeline_transfer,name)(store,**a)
    if name=='list_timelines':return timelines.list_timelines(store,**a)
    if name=='read_work_result':
        from loop_anything.runtime.business_state import read_result
        return read_result(store,**a)
    if name in ('read_business_state','read_work_results'):
        from loop_anything.runtime.business_state import read
        return read(store,collection='state' if name=='read_business_state' else 'results',**a)
    if name=='read_work_timeline':return timelines.read(store,a['timeline_id'],a.get('after',0),a.get('limit',100),a.get('newest_first',False))
    if name=='register_work_session':return work.register_session(store,a)
    if name=='register_monitor':return {'script':work.register_monitor(store,a)}
    if name=='start_monitor':return {'monitor':work.start_monitor(store,a)}
    if name=='wait_for':
        result=work.register_wait(store,a)
        return {'wait':work.poll_wait(store,result['id']),'next':'Finish current Run turns and exit; platform will resume the recorded session.'}
    with work.transaction(store) as db:
        if name=='create_timeline':return {'timeline':timelines.create(db,**a)}
        if name=='update_timeline':return timelines.update(db,a['timeline_id'],a['revision'],a['change'],a.get('message',''))
        if name=='append_timeline':
            return {'entry':timelines.append(db,a['timeline_id'],a['key'],a['text'],a.get('kind','note'),a.get('refs'),actor='agent',review=a.get('review'))}
        if name=='list_monitor_scripts':return {'scripts':work.rows(db,'monitor_script')}
        if name=='list_monitors':return {'monitors':[v for v in work.rows(db,'monitor') if not a.get('run_id') or v.get('run_id')==a['run_id']]}
        if name=='read_monitor':return {'monitor':work.get(db,'monitor',a['monitor_id'])}
        if name in ('stop_monitor','restart_monitor'):
            value=work.get(db,'monitor',a['monitor_id'])
            if name=='stop_monitor':value['status']='stopped'
            else:
                if value.get('call_id') and not a.get('confirmed_stopped'):raise Conflict('Check previous monitor process and confirm stopped')
                if value.get('process',{}).get('pid') and work.alive(value['process']['pid']) and value.get('call_id'):raise Conflict('Monitor process is still alive')
                value.update(status='running',call_id=None,next_at=0,error=None)
            work.put(db,'monitor',value);return {'monitor':value}
        if name=='read_wait':return {'wait':work.get(db,'wait',a['wait_id'])}
        if name=='resolve_continuation':
            from loop_anything.interfaces.agent_tasks import change_task_in_run
            from loop_anything.runtime.task_scope import process_active
            with store.edit(a['run_id'],_db=db) as run:
                task=run['tasks'].get(a['task_id'],{})
                ref=task.get('continuation_source')
                if not ref:raise Invalid('Task is not awaiting an original execution')
                with store.edit(ref['run_id'],_db=db) as source:
                    old=source['tasks'][ref['task_id']]
                    attempt=next((e for e in source['executions'] if e['id']==old.get('execution_id')), {})
                    if a['operation']=='retry_monitor':
                        if not attempt.get('observation_error'):raise Invalid('Original observer has no retryable check error')
                        change_task_in_run(source,{'task_id':old['id'],'operation':'retry','reason':a['reason']})
                    elif a['operation']=='cancel':
                        task['status']='cancelled';task.pop('continuation_source')
                    else:
                        if not a.get('confirmed_stopped') or process_active(attempt):raise Conflict('Confirm original job stopped before retrying')
                        if old['status'] not in ('fault','stale','cancelled','waiting_user'):raise Conflict('Original execution is not in a retryable state')
                        task.pop('continuation_source');task['status']='fault'
                        change_task_in_run(run,{'task_id':task['id'],'operation':'retry','reason':a['reason']})
                store.log(run,'agent_action_change',a['reason'],detail={'task_id':task['id'],'operation':a['operation'],'source':ref})
                return {'task':task}
        session=work.session_auth(db,a['session_id'],a['session_token'])
        if name=='read_work_session':
            return {'session':work.public_session(session),'waits':[v for v in work.rows(db,'wait') if v['session_id']==session['id']]}
        if name=='resume_work_session':
            work.retry_session(session,a['confirmed_stopped'])
            work.put(db,'session',session);return {'session':work.public_session(session)}
        if name in ('cancel_wait','acknowledge_wait'):
            value=work.get(db,'wait',a['wait_id'])
            if value['session_id']!=session['id']:raise Conflict('Wait belongs to another session')
            if name=='acknowledge_wait' and value['state'] not in ('ready','handled'):raise Conflict('Wait is not ready')
            value.pop('retained_sources',None)
            value['state']='cancelled' if name=='cancel_wait' else 'handled'
            work.put(db,'wait',value);return {'wait':value}
    raise Invalid('Unknown work tool')
