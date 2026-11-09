"""Executor discovery plus the small receiver protocol, over either tool transport."""
from loop_anything.runtime.executors import service
from loop_anything.runtime.model import Invalid


def definitions():
    text={'type':'string'};obj={'type':'object'}
    session={'run_id':text,'execution_id':text,'session_id':text}
    items=[
        ('list_executors','List registered headless receivers and current availability. Use an exact returned id in implementation.executor for Agent, command, or external submit/observe execution. Registration does not start a personal receiver task.',{},[],True),
        ('read_executor_call','Inspect one remote process outcome, complete delivered result, original execution association, and exact native session. delivering means the process ended but the same result is still transferring; do not rerun it. Unknown is not proof of stopped; no automatic reassignment.',{'id':text},['id'],True),
        ('executor_poll','Receiver protocol: publish receiver heartbeat and read its already assigned process calls. Ordinary Agents should use list_executors and existing workflow tools.',{'worker':obj},['worker'],False),
        ('executor_report','Receiver protocol: persist progress/result for an assigned process using its exact delivery token. Retries retain the call ID.',{'id':text,'token':text,'update':obj},['id','token','update'],False),
        ('confirm_executor_stopped','After the operator has verified the unknown remote process stopped, release its execution claim. Also accepts a late terminal receipt whose retained claim remains unresolved; inspect its saved result first. Does not retry, resume or start work. Silence is not confirmation.',{'id':text,'confirmed_stopped':{'type':'boolean'}},['id','confirmed_stopped'],False),
        ('read_execution_session','Read existing terminal output with after cursor, or prepare=true to read the saved native identity and exact resume configuration. Works over NAS and HTTP; does not start a CLI.',dict(session,after={'type':'integer'},prepare={'type':'boolean'}),['run_id','execution_id'],True),
        ('control_execution_session','Use existing terminal operations without a browser: input sends data/size to the same process; resume uses continuation={provider,native_session_id,command,cwd,message,previous_native_session?} returned by preparation and explicitly chosen by the user; confirm_stopped releases an interrupted session only after verified stop. No new conversation or automatic retry.',dict(session,action={'type':'string','enum':['input','resume','confirm_stopped']},data=text,cols={'type':'integer'},rows={'type':'integer'},continuation=obj,confirmed_stopped={'type':'boolean'}),['run_id','execution_id','action'],False),
    ]
    return [{'name':n,'description':d,'inputSchema':{'type':'object','properties':p,'required':r,'additionalProperties':False},'annotations':{'readOnlyHint':ro}} for n,d,p,r,ro in items]


def call(store,name,args):
    backend=service(store)
    if name=='list_executors':return {'executors':backend.list()}
    if name=='read_executor_call':
        job=backend.get(args['id'])
        if job.get('result_file'):job=dict(job,result=backend.result(job))
        worker=next((w for w in backend.list() if w['id']==job['executor']),{})
        return {'call':{k:job[k] for k in ('id','executor','state','execution_state','delivery_error','metadata','created_at','seen_at','result','error','session') if k in job},'executor_online':worker.get('online',False)}
    if name=='executor_poll':return backend.poll(args['worker'])
    if name=='executor_report':return backend.report(args['id'],args['token'],args['update'])
    if name=='confirm_executor_stopped':
        if args['confirmed_stopped'] is not True:raise Invalid('Verify the old process stopped before confirming')
        return backend.confirm_stopped(args['id'])
    if name in ('read_execution_session','control_execution_session'):
        engine=backend.engine
        if not engine:raise Invalid('Connect to the running service for execution sessions')
        run_id,execution_id=args['run_id'],args['execution_id'];engine.execution(store.get(run_id),execution_id)
        from loop_anything.runtime.native_sessions import preparation,resume,confirm_stopped
        if name=='read_execution_session':
            if args.get('prepare'):return preparation(engine,run_id,execution_id)
            return engine.terminals.read(run_id,execution_id,args.get('session_id'),args.get('after',0))
        if args['action']=='resume':return resume(engine,run_id,execution_id,args.get('continuation',{}))
        if args['action']=='confirm_stopped':
            if args.get('confirmed_stopped') is not True:raise Invalid('Verify the old process stopped before confirming')
            return confirm_stopped(engine,run_id,execution_id,args.get('session_id'))
        return engine.terminals.control(run_id,execution_id,args.get('session_id'),args.get('data'),args.get('cols'),args.get('rows'))
    raise Invalid('Unknown executor tool')
