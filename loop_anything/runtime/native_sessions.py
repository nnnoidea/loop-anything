"""Explicit native CLI identity and user-requested continuation of one execution."""
import copy
import json
import os
import re
import time
from pathlib import Path
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.store import Store, uid
from loop_anything.runtime.host_runtime import run_command, CommandNotStopped

PROVIDERS = ('codex', 'claude', 'custom')


def provider_for(config):
    name = Path((config.get('command') or [''])[0]).name.lower().removesuffix('.exe')
    return config.get('agent_cli') or (name if name in PROVIDERS else 'custom')


def validate_identity(provider, ident):
    if provider not in PROVIDERS or not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', ident):
        raise Invalid('CLI provider and a concrete native session ID are required; never use --last')


def validate_resume(command):
    if not isinstance(command, list) or not command or any(not isinstance(a, str) or not a or '\0' in a for a in command):
        raise Invalid('resume_command must be nonempty argv')
    if any(a in ('--last','--continue','--fork-session') for a in command):
        raise Invalid('Resume must target the recorded session, without latest/continue/fork flags')
    if not any('{{session_id}}' in a for a in command) or not any('{{prompt}}' in a or '{{prompt_file}}' in a for a in command):
        raise Invalid('resume_command needs {{session_id}} and {{prompt}} or {{prompt_file}}')
    executable=Path(command[0]).name.lower().removesuffix('.exe')
    if executable=='codex' and not any(command[i:i+2]==['resume','{{session_id}}'] for i in range(len(command)-1)):
        raise Invalid('Codex must use resume followed by the exact {{session_id}} argument')
    if executable=='claude':
        exact=any(command[i:i+2] in (['--resume','{{session_id}}'],['-r','{{session_id}}']) for i in range(len(command)-1)) or '--resume={{session_id}}' in command
        if '-c' in command or not exact:raise Invalid('Claude must use --resume with the exact {{session_id}}, without -c')



def default_resume(config, provider):
    if config.get('resume_command'):
        return list(config['resume_command'])
    executable = (config.get('command') or [provider])[0]
    if Path(executable).name.lower().removesuffix('.exe') != provider:
        executable = provider  # A wrapper needs an explicitly supplied resume command.
    if provider == 'codex':return [executable, 'resume', '{{session_id}}', '{{prompt}}']
    if provider == 'claude':return [executable, '--resume', '{{session_id}}', '{{prompt}}']
    return []


def resume_config(config, native):
    if not native:raise Invalid('Record the actual native CLI session before waiting for assistance')
    validate_identity(native.get('provider'),native.get('id'))
    if os.name!='posix':raise Invalid('Automatic session continuation currently requires macOS/Linux')
    command=default_resume(config,native['provider'])
    validate_resume(command)
    result=dict(copy.deepcopy(config),command=command,terminal=True)
    if native.get('cwd'):result['cwd']=native['cwd']
    return result


def bind(run, execution, provider, ident, source, cwd=None):
    validate_identity(provider, ident)
    if cwd is not None and (not isinstance(cwd,str) or not cwd or '\0' in cwd):raise Invalid('CLI cwd must be a nonempty path')
    previous = execution.get('native_session')
    value = {'provider': provider, 'id': ident}
    if previous and any(previous[k] != value[k] for k in value):
        raise Conflict('This execution is already associated with another native session')
    if not previous:
        execution['native_session'] = dict(value, source=source, recorded_at=time.time(), cwd=cwd or execution['implementation'].get('cwd'))
        Store.log(run, 'native_session', 'CLI session recorded', execution['id'], value)
    return execution['native_session']


class Capture:
    def __init__(self, provider, callback):
        self.provider, self.callback = provider, callback
        self.buffers = {'stdout': '', 'stderr': ''}
        self.found = False

    def feed(self, stream, text, final=False):
        if self.found or self.provider not in ('codex', 'claude'):return
        text = self.buffers[stream] + text
        lines = text.splitlines(keepends=True)
        self.buffers[stream] = ''
        if lines and not final and not lines[-1].endswith(('\n', '\r')):
            self.buffers[stream] = lines.pop()[-32768:]
        for line in lines:
            line = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', line).strip()
            ident = None
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    if self.provider == 'codex' and event.get('type') == 'thread.started':ident = event.get('thread_id')
                    if self.provider == 'claude' and event.get('type') in ('system', 'result') and event.get('session_id'):ident = event['session_id']
            except (ValueError, TypeError):pass
            if self.provider == 'codex' and re.fullmatch(r'session id:\s*[A-Za-z0-9_.:-]+', line, re.I):ident = line.split(':', 1)[1].strip()
            if ident:
                try:validate_identity(self.provider, ident)
                except Invalid:continue
                self.callback(self.provider, ident)
                self.found = True
                return


def configure_capture(store, run_id, execution_id, session, config, native=None):
    provider = native['provider'] if native else provider_for(config)
    def save(provider, ident, source="cli_output"):
        with store.edit(run_id) as run:
            execution = next(e for e in run['executions'] if e['id'] == execution_id)
            native=bind(run, execution, provider, ident, source, config.get("cwd") or os.getcwd())
        session.doc['native_session']=copy.deepcopy(native)
        session.save()
    session.capture = Capture(provider, save)
    if native:
        session.native_id=native['id']
        session.doc['native_session']=copy.deepcopy(native)
        session.on_started=lambda:save(native['provider'],native['id'],'assistance_resume')
    elif any('{{session_id}}' in arg for arg in config.get('command', [])):
        import uuid
        session.native_id = str(uuid.uuid4())
        session.on_started = lambda: save(provider, session.native_id, "configured_id")


def active_execution(db,run_id,execution_id):
    for row in db.execute('SELECT document FROM execution_sessions WHERE run_id=? AND execution_id=? ORDER BY rowid DESC',(run_id,execution_id)):
        doc=json.loads(row[0])
        if doc['state'] in ('starting','running','interrupted'):return doc


def active_native(db, provider, ident, store):
    # ponytail: resume is user-triggered; index native identity if large archives make this scan slow.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='communication_requests'").fetchone():
        config=json.loads(db.execute('SELECT document FROM communication_settings WHERE id=1').fetchone()[0])
        for row in db.execute('SELECT document FROM communication_requests'):
            request=json.loads(row[0]);native=request.get('native_session') or {}
            if not request.get('mirror') and request.get('executor')==config['instance_id'] and request['state'] in ('starting','running','unknown','cancelling') and (native.get('provider'),native.get('id'))==(provider,ident):
                return {'state':'external','id':None,'run_id':'','execution_id':request['id'],'communication_id':request['id']}
    from loop_anything.runtime.collaboration import caller_active
    for saved in db.execute('SELECT id FROM runs'):
        run=store._load(db,saved[0])
        for execution in run.get('executions',[]):
            native=execution.get('native_session') or {}
            if (native.get('provider'),native.get('id'))==(provider,ident) and caller_active(execution):
                return {'state':'external','id':None,'run_id':run['id'],'execution_id':execution['id']}
    for row in db.execute('SELECT document FROM execution_sessions ORDER BY rowid DESC'):
        doc=json.loads(row[0]);native=doc.get('native_session') or {}
        if doc['state'] not in ('starting','running','interrupted'):continue
        if not native:
            try:
                run=store._load(db,doc['run_id'])
                native=next((e.get('native_session') or {} for e in run['executions'] if e['id']==doc['execution_id']),{})
            except Invalid:continue
        if (native.get('provider'),native.get('id'))==(provider,ident):return doc

    # An externally operated Agent has no platform terminal, but its active scope still owns its ID.
    for row in db.execute('SELECT id,document FROM runs'):
        root=json.loads(row['document'])
        owners={o['token'] for o in root.get('agent_sessions',[])}
        if not owners:continue
        run=store._load(db,row['id'])
        for execution in run.get('executions',[]):
            if execution['implementation'].get('dispatch'):continue
            native=execution.get('native_session') or {}
            if execution.get('token') in owners and (native.get('provider'),native.get('id'))==(provider,ident):
                return {'state':'external','id':None,'run_id':run['id'],'execution_id':execution['id']}


def confirm_stopped(engine, run_id, execution_id, session_id):
    from loop_anything.interfaces.agent_tasks import recover_owner
    with engine.terminals.lock:
        if session_id in engine.terminals.live:raise Conflict('Process is still managed by this platform; wait for it to stop')
        with engine.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT document FROM execution_sessions WHERE id=? AND run_id=? AND execution_id=?',(session_id,run_id,execution_id)).fetchone()
            if not row:raise Invalid('Unknown execution session')
            doc=json.loads(row[0])
            if doc['state']!='interrupted':raise Conflict('Only an interrupted session needs stop confirmation')
            # Reuse the existing explicit process recovery protocol for any retained operation scope.
            run=engine.store._load(db,run_id)
            owners=[o for o in run.get('agent_sessions',[]) if o.get('resume_session')==session_id or (not o.get('resume_session') and o.get('execution_id')==execution_id)]
            doc.update(state='released',error=None,stop_confirmed_at=time.time())
            for owner in owners:recover_owner(engine.store,run_id,owner['token'],confirmed_stopped=True,_db=db)
            db.execute('UPDATE execution_sessions SET document=? WHERE id=?',(json.dumps(doc),session_id));db.commit()
    return {'confirmed':True}


def preparation(engine, run_id, execution_id):
    run = engine.store.get(run_id)
    execution = engine.execution(run, execution_id)
    if execution['implementation']['kind'] != 'agent':raise Invalid('Only Agent executions have CLI sessions')
    native = execution.get('native_session')
    provider = (native or {}).get('provider') or provider_for(execution['implementation'])
    if not native:
        captured = []
        detector = Capture(provider, lambda p, i: captured.append({'provider':p, 'id':i, 'source':'saved_output'}))
        # Inspect only this execution's recorded startup output, never unrelated CLI history.
        with engine.store.connection() as db:
            for row in db.execute('SELECT o.text FROM execution_output o JOIN execution_sessions s ON s.id=o.session_id WHERE s.run_id=? AND s.execution_id=? ORDER BY s.rowid,o.sequence LIMIT 128', (run_id,execution_id)):
                detector.feed('stdout',row[0])
                if captured:break
        native = captured[0] if captured else None
    owners = [o for o in run.get('agent_sessions', []) if o.get('resume_execution') == execution_id]
    active = owners[0].get('resume_session') if owners else execution.get('worker_active')
    if not active:
        with engine.store.connection() as db:pending=active_execution(db,run_id,execution_id)
        if pending:active=pending['id']
    if not active and native:
        with engine.store.connection() as db:prior=active_native(db,native['provider'],native['id'],engine.store)
        if prior and (prior['run_id'],prior['execution_id'])==(run_id,execution_id):active=prior['id']
    return {'revision':run['revision'], 'native_session':native, 'provider':provider,
            'resume_command':execution.get('resume_command') or default_resume(execution['implementation'],provider),
            'cwd':execution.get('resume_cwd') or (native or {}).get('cwd') or execution['implementation'].get('cwd'), 'active_session':active,
            'can_resume':run['status'] in ('running','paused') and os.name == 'posix',
            'notice':'恢复会启动 CLI，并携带最新任务上下文；已提交结果保留。请核对恢复命令中所需的模型、权限和配置参数。'}


def resume(engine, run_id, execution_id, arguments):
    from loop_anything.interfaces.agent_tasks import acquire_in_run
    if os.name != 'posix':raise Invalid('Interactive resume requires macOS/Linux')
    message = arguments.get('message')
    if not isinstance(message,str) or not message.strip() or len(message)>20000:raise Invalid('Supply a continuation message (1–20000 characters)')
    command = arguments.get('command'); validate_resume(command)
    provider, ident = arguments.get('provider'), arguments.get('native_session_id')
    validate_identity(provider,ident)
    cwd=arguments.get('cwd')
    if cwd is not None and (not isinstance(cwd,str) or not cwd or '\0' in cwd):raise Invalid('Resume cwd must be a nonempty path')
    with engine.terminals.lock, engine.store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        with engine.store.edit(run_id,_db=db) as run:
            execution=engine.execution(run,execution_id)
            if execution['implementation'].get('dispatch'):raise Invalid('Resume this session through its communication request on the executor machine')
            if execution['implementation']['kind']!='agent':raise Invalid('Only Agent executions can resume')
            for owner in run.get('agent_sessions',[]):
                if owner.get('resume_execution')==execution_id:
                    if owner.get('recovery_required'):raise Conflict('Previous process state is unknown; confirm it stopped before resuming')
                    return {'session_id':owner['resume_session'],'attached':True}
            if run['status'] not in ('running','paused'):raise Conflict('Run ended; historical results remain read-only')
            pending=active_execution(db,run_id,execution_id)
            if pending:
                if pending['state']=='interrupted':raise Conflict('This execution has an unconfirmed CLI process; confirm it stopped first')
                return {'session_id':pending['id'],'attached':True}
            if execution.get('worker_active'):return {'session_id':execution['worker_active'],'attached':True}
            current=next((e for e in run['executions'] if e['id']==run['tasks'][execution['task_id']].get('execution_id')),None)
            if current and current.get('worker_active'):raise Conflict('The task has an active execution; open its current session')
            prior=active_native(db,provider,ident,engine.store)
            if prior:
                if prior['state']=='external':raise Conflict('The original Agent still owns this CLI conversation; finish its operation first')
                if prior['state']=='interrupted':raise Conflict('Native CLI process state is unknown; confirm it stopped before restoring')
                if (prior['run_id'],prior['execution_id'])==(run_id,execution_id):return {'session_id':prior['id'],'attached':True}
                raise Conflict('This native CLI session is active in another task or Run')
            previous=execution.get('native_session')
            if previous and (previous['provider'],previous['id'])!=(provider,ident):
                expected=arguments.get('previous_native_session')
                if not isinstance(expected,dict) or any(expected.get(k)!=previous[k] for k in ('provider','id')):
                    raise Conflict('Native association changed; reload before explicitly changing it')
                if active_native(db,previous['provider'],previous['id'],engine.store):
                    raise Conflict('The previously associated CLI session is still active or unconfirmed')
                execution.pop('native_session')
                Store.log(run,'native_session_reassociated','User corrected the native CLI association',execution_id,{'before':previous,'after':{'provider':provider,'id':ident}})
            native=bind(run,execution,provider,ident,'user_confirmed',cwd)
            cwd=cwd or execution.get('resume_cwd') or native.get('cwd') or execution['implementation'].get('cwd')
            owner=acquire_in_run(run,'interactive',execution_id=execution_id)
            session_id=uid('resume')
            owner.update(resume_session=session_id,resume_execution=execution_id)
            session=engine.terminals.create(run_id,execution_id,session_id,True,[owner['token'],execution.get('token')],
                metadata={'mode':'resume','native_session':copy.deepcopy(native),'command':list(command),'cwd':cwd},_db=db)
            execution['resume_command']=list(command)
            execution['resume_cwd']=cwd
            Store.log(run,'agent_resume','User resumed the CLI conversation',execution_id,{'session_id':session_id,'native_session':dict(native),'message':message})
            token=owner['token']
        db.commit()
    def execute():
        from loop_anything.interfaces.agent_tasks import owner_for, release_in_run
        from loop_anything.runtime.agent_prompt import task_context
        error=None
        try:
            config=execution['implementation']
            current=engine.store.get(run_id)
            if not owner_for(current,token):raise Conflict('Resume ownership expired before startup')
            context=task_context(engine.store,current,dict(execution,token=token),getattr(engine,'platform_url',None),execution['task_id'])
            context.update(source_execution_id=execution_id, task_status=current['tasks'][execution['task_id']]['status'], user_message=message)
            prompt=('Continue this exact saved CLI conversation for the user. All earlier platform tokens are obsolete. '
                'Use only the fresh Run context below and re-read read_task/read_timeline before acting. '
                'The native session identity is already recorded; do not register the historical execution again. '
                'The source execution and committed outputs are history; do not repeat completed work or overwrite results merely because this conversation resumed. '
                'Explain results when asked; make new tasks or explicit corrections only when requested and within this Task branch. '
                'Finish this continuation by calling the platform finish tool; it releases this conversation scope and closes this terminal, without marking the historical Task complete. '
                'Use platform_client with run_id/token from this context for existing Run tools.\nRun context:\n'+json.dumps(context,ensure_ascii=False))
            session.native_id=ident
            def state():
                latest=engine.store.get(run_id)
                if not owner_for(latest,token):return 'finished'
                if latest['status'] in ('terminated','completed'):return 'revoked'
            session.check=state
            result=run_command(command,prompt,config.get('timeout'),cwd,engine.stopping,session)
            if result.returncode:raise Invalid('Resume command failed: '+result.stdout[-1500:])
        except Exception as exc:
            error=exc
            # Also surface errors that occur before Session.run gets control.
            if session.doc['state']=='starting':
                session.doc.update(state='error',error=str(exc),ended_at=time.time());session.save()
        finally:
            with engine.store.edit(run_id) as latest:
                owner=owner_for(latest,token)
                if owner:
                    if isinstance(error,CommandNotStopped):owner['recovery_required']=True
                    else:release_in_run(latest,token)
                Store.log(latest,'agent_resume_exit',str(error) if error else 'CLI continuation ended',execution_id,{'session_id':session_id,'error':bool(error)})
    try:engine.futures.add(engine.pool.submit(execute))
    except RuntimeError:
        from loop_anything.interfaces.agent_tasks import release_in_run
        with engine.store.edit(run_id) as run:release_in_run(run,token)
        session.doc.update(state='error',error='Platform is stopping',ended_at=time.time());session.save()
        raise Conflict('Platform is stopping')
    return {'session_id':session_id,'attached':False}
