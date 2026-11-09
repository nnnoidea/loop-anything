"""Service-owned remote process calls. Workflow decisions stay in Timeline."""
import copy
import json
from pathlib import Path
import secrets
import subprocess
import time
import traceback
import threading
from types import SimpleNamespace
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.host_runtime import CommandNotStopped
from loop_anything.runtime.team_transport import core
from loop_anything.runtime import process_results

FINAL={'completed','failed','unknown'}


class RemotePending(Exception):
    """The durable call continues; release the Python worker, not its Task/session claim."""


class Executors:
    def __init__(self, store, engine=None):
        self.store,self.engine=store,engine
        with store.connection() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS executors (id TEXT PRIMARY KEY, document TEXT NOT NULL);'
                'CREATE TABLE IF NOT EXISTS executor_calls (id TEXT PRIMARY KEY, document TEXT NOT NULL);'
                "CREATE INDEX IF NOT EXISTS executor_pending ON executor_calls(id) WHERE json_extract(document,'$.applied') IS NOT 1;"
                "CREATE INDEX IF NOT EXISTS executor_dispatch ON executor_calls(json_extract(document,'$.executor')) WHERE json_extract(document,'$.state') NOT IN ('completed','failed','unknown');")
        self.root=None
        self.waiting={};self.completing=set();self.lock=threading.RLock()

    def list(self):
        with self.store.connection() as db:rows=[json.loads(r[0]) for r in db.execute('SELECT document FROM executors')]
        return [dict(row,online=time.time()-row.get('heartbeat',0)<30) for row in rows]

    def register(self, worker):
        ident=core.address(worker['id'])
        if not isinstance(worker.get('name'),str) or not worker.get('owner'):raise Invalid('Executor needs name and process owner')
        capacity=worker.get('capacity',1)
        if type(capacity) is not int or not 1<=capacity<=8:raise Invalid('Executor capacity must be 1–8')
        value={k:worker.get(k) for k in ('id','name','owner','machine')}
        value.update(capacity=capacity,heartbeat=min(time.time(),worker.get('heartbeat',time.time())))
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT document FROM executors WHERE id=?',(ident,)).fetchone()
            if old:
                old=json.loads(old[0])
                if old['owner']!=value['owner'] and time.time()-old['heartbeat']<30:raise Conflict('This executor is still owned by another running receiver')
                if old==value:return {'registered':True,'executor_id':ident}
            db.execute('INSERT OR REPLACE INTO executors VALUES (?,?)',(ident,json.dumps(value)));db.commit()
        return {'registered':True,'executor_id':ident}

    def calls(self):
        with self.store.connection() as db:return [json.loads(r[0]) for r in db.execute('SELECT document FROM executor_calls')]

    def get(self, ident, db=None):
        if db is None:
            with self.store.connection() as conn:return self.get(ident,conn)
        row=db.execute('SELECT document FROM executor_calls WHERE id=?',(ident,)).fetchone()
        if not row:raise Invalid('Unknown executor call')
        return json.loads(row[0])

    def save(self, db, job):db.execute('INSERT OR REPLACE INTO executor_calls VALUES (?,?)',(job['id'],json.dumps(job,ensure_ascii=False)))

    def result_path(self, ident):
        return Path(self.store.filename).parent/'executor-results'/(core.address(ident)+'.json')

    def result(self, job):
        return process_results.read(self.result_path(job['id'])) if job.get('result_file') else job.get('result')

    def result_offset(self, ident):
        path=self.result_path(ident)
        if path.exists():return path.stat().st_size
        path=path.with_suffix('.part')
        return path.stat().st_size if path.exists() else 0

    def poll(self, worker):
        self.register(worker)
        with self.store.connection() as db:
            jobs=[json.loads(r[0]) for r in db.execute("SELECT document FROM executor_calls WHERE json_extract(document,'$.executor')=? AND json_extract(document,'$.state') NOT IN ('completed','failed','unknown')",(worker['id'],))]
        return {'jobs':[self.packet(j) for j in jobs],'controls':{j['id']:j.get('controls',[]) for j in jobs}}

    @staticmethod
    def packet(job):return {k:copy.deepcopy(job[k]) for k in ('id','executor','token','payload')}

    def report(self, ident, token, update):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');job=self.get(ident,db)
            if not secrets.compare_digest(token,job['token']):raise Conflict('Wrong execution receipt identity')
            if update.get('state') not in {'starting','running','delivering',*FINAL}:raise Invalid('Invalid execution state')
            if job['state'] in ('completed','failed'):return {'accepted':True,'terminal':True}
            if int(update.get('sequence',0))>job.get('sequence',-1):
                job.update({k:copy.deepcopy(update[k]) for k in ('state','sequence','result','error','session','events','control_cursor','execution_state','delivery_error') if k in update})
            if update.get('result_manifest'):
                if job.get('result_manifest') and job['result_manifest']!=update['result_manifest']:raise Conflict('Execution result identity changed')
                job['result_manifest']=copy.deepcopy(update['result_manifest'])
                offset=process_results.receive(self.result_path(ident),job['result_manifest'],update.get('result_chunk'))
                if offset==job['result_manifest']['bytes']:
                    job.update(state='completed',execution_state='completed',result_file=True)
                    job.pop('delivery_error',None)
            job['seen_at']=time.time();self.save(db,job);db.commit()
        self.advance()
        return {'accepted':True,'terminal':job['state'] in FINAL,'result_offset':self.result_offset(ident)}

    def control(self, ident, *, data=None, cols=None, rows=None, reason=None):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');job=self.get(ident,db)
            controls=job.setdefault('controls',[])
            if reason and any(c.get('reason')==reason for c in controls):return
            number=job.get('control_sequence',0)+1;job['control_sequence']=number
            controls[:]=[c for c in controls if c['id']>job.get('control_cursor',0)]
            if len(controls)>=32:raise Conflict('Executor input is busy')
            controls.append({'id':number,'data':data,'cols':cols,'rows':rows,'reason':reason})
            self.save(db,job);db.commit()

    def pending(self):
        with self.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT document FROM executor_calls WHERE json_extract(document,'$.applied') IS NOT 1")]

    def applied(self, ident):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');job=self.get(ident,db);job['applied']=True
            if job['state'] not in ('completed','failed'):return
            # Complete answers are already in Timeline; retain process outcome and native identity.
            job['payload'].pop('prompt',None)
            job['payload'].pop('prompt_context',None)
            recorded=db.execute('SELECT document FROM execution_sessions WHERE id=?',(ident,)).fetchone()
            native=(job.get('session') or {}).get('native_session') or (json.loads(recorded[0]).get('native_session') if recorded else None)
            if native:
                job.pop('events',None)
                if job.get('result'):job['result'].update(stdout='',stderr='')
                if job.get('result_file'):
                    result=self.result(job);job['result']={'returncode':result['returncode'],'stdout':'','stderr':''}
                    job.pop('result_file',None)
            self.save(db,job);db.commit()
        if native:self.result_path(ident).unlink(missing_ok=True)

    def confirm_stopped(self, ident):
        """Explicit operator confirmation releases an unknown process claim, without retrying work."""
        from loop_anything.interfaces.agent_tasks import recover_owner
        if not self.engine:raise Conflict('Execution service is not running')
        if ident in self.engine.terminals.live:raise Conflict('Wait for the active process connection to finish')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');job=self.get(ident,db)
            if job['state'] not in FINAL or job.get('applied'):raise Conflict('Only an unresolved execution receipt needs stop confirmation')
            meta=job['metadata']
            if meta.get('kind') in ('task','resume'):
                run=self.store._load(db,meta['run_id']);attempt=self.engine.execution(run,meta['execution_id'])
                if attempt.get('worker_active')==ident:
                    owners=[o for o in run.get('agent_sessions',[]) if o.get('resume_session')==ident or not o.get('resume_session') and o.get('execution_id')==attempt['id']]
                    for owner in owners:recover_owner(self.store,run['id'],owner['token'],confirmed_stopped=True,_db=db)
                    with self.store.edit(run['id'],_db=db) as current:
                        self.engine.execution(current,attempt['id']).pop('worker_active',None)
                        from loop_anything.runtime.store import Store
                        Store.log(current,'stop_confirmed','Remote process explicitly confirmed stopped',attempt['id'])
            elif meta.get('kind')=='communication':
                comm=self.engine.communication;row=comm.get(meta['request_id'],db)
                comm.confirm_execution_stopped(db,row);comm.save(db,row)
            row=db.execute('SELECT document FROM execution_sessions WHERE id=?',(ident,)).fetchone()
            if row:
                doc=json.loads(row[0]);doc.update(state='released',stop_confirmed_at=time.time())
                db.execute('UPDATE execution_sessions SET document=? WHERE id=?',(json.dumps(doc),ident))
            if job['state']=='unknown':job.update(state='failed',error='Operator confirmed the old process stopped')
            job.update(applied=True,stop_confirmed_at=time.time())
            self.save(db,job);db.commit()
        if self.root:self.sync_job(Path(self.root)/'executors',job)
        return {'confirmed':True,'retried':False}

    def sync(self):
        if self.root:
            root=Path(self.root)/'executors'
            for path in root.glob('*/worker.json'):
                try:self.register(core.read_message(path))
                except Exception:traceback.print_exc()
            for job in self.pending():
                try:self.sync_job(root,job)
                except Exception:traceback.print_exc()
        self.advance()

    def advance(self):
        if not self.engine or self.engine.stopping.is_set():return
        with self.lock:
            for ident,session in list(self.waiting.items()):
                if ident in self.completing:continue
                job=self.get(ident)
                self.refresh(job,session)
                if job['state'] in FINAL and job['metadata'].get('kind') in ('task','communication','resume'):
                    self.completing.add(ident);self.waiting.pop(ident,None)
                    self.engine.futures.add(self.engine.pool.submit(self.complete,job))

    def complete(self, job):
        try:self.engine.resume_remote(job)
        finally:
            with self.lock:self.completing.discard(job['id'])

    def refresh(self, job, session):
        ident=job['id'];remote=job.get('session') or {}
        if session:
            cursor=session.doc.get('remote_cursor',0)
            if remote.get('pid') and session.process is None:
                session.process=SimpleNamespace(pid=remote['pid'],poll=lambda:None if self.get(ident)['state'] not in FINAL else self.get(ident).get('result',{}).get('returncode',1))
                if session.on_started:session.on_started()
            for event in job.get('events',[]):
                if event['id']>cursor:
                    session.append(event['stream'],event['text']);cursor=event['id']
            native=remote.get('native_session')
            if native and session.capture and not session.capture.found:
                session.capture.callback(native['provider'],native['id']);session.capture.found=True
            changed={k:v for k,v in remote.items() if k in ('state','pid','native_session','native_session_error','returncode','ended_at') and session.doc.get(k)!=v}
            if session.doc.get('remote_cursor')!=cursor:changed['remote_cursor']=cursor
            if changed:session.doc.update(changed);session.save()
        if job['state'] in FINAL:return
        if session and session.check:
            reason=session.check()
            if reason:self.control(ident,reason=reason)
        elif job['metadata'].get('kind')=='task':
            meta=job['metadata'];current=self.store.get(meta['run_id'])
            attempt=self.engine.execution(current,meta['execution_id'])
            if current['status']=='terminated' or attempt['status'] in ('cancelled','stale'):
                self.control(ident,reason='revoked')

    def sync_job(self, root, job):
        folder=root/job['executor'];folder.mkdir(parents=True,exist_ok=True)
        files=core.Nas({'path':str(folder)})
        report=folder/'reports'/(job['id']+'.json')
        if report.exists():
            value=core.read_message(report)
            self.report(job['id'],value['token'],value['update'])
            job=self.get(job['id'])
            if job['state']=='delivering' and job.get('result_manifest'):
                for _ in range(4):
                    offset=self.result_offset(job['id']);part=folder/'results'/job['id']/(str(offset)+'.json')
                    if not part.exists():break
                    self.report(job['id'],value['token'],dict(value['update'],result_chunk=core.read_message(part)))
                    job=self.get(job['id'])
                    if job['state'] in FINAL:break
        if job['state'] not in FINAL:
            files.put('inbox/'+job['id']+'.json',self.packet(job),immutable=True)
            files.put('controls/'+job['id']+'.json',job.get('controls',[]))
        else:
            files.put('acks/'+job['id']+'.json',{'accepted':True},immutable=True)
            (folder/'inbox'/(job['id']+'.json')).unlink(missing_ok=True)

    def run(self, config, command, prompt, timeout, cwd, stop, session, ident, metadata):
        executor=core.address(config['executor'])
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT document FROM executor_calls WHERE id=?',(ident,)).fetchone()
            if not row:
                if not db.execute('SELECT 1 FROM executors WHERE id=?',(executor,)).fetchone():raise Invalid('Select an executor from list_executors before dispatch')
                payload={'command':command,'prompt':prompt,'timeout':timeout,'cwd':cwd,
                    'terminal':session.doc['interactive'] if session else bool(config.get('terminal')),'agent_cli':config.get('agent_cli'),
                    'kind':config['kind'],'skill_root':str(__import__('loop_anything.paths',fromlist=['platform_skill_directory']).platform_skill_directory())}
                if self.root:payload['team_root']=str(self.root)
                if '_prompt_context' in config:
                    payload['prompt_context']=config['_prompt_context']
                    payload['prompt_template']=config.get('_prompt_template')
                    payload['prompt_indent']=config.get('_prompt_indent')
                    payload['prompt']=''  # Render once on the receiver, with its explicit platform paths.
                if session:
                    payload['native_session']=session.doc.get('native_session')
                    payload['native_id']=session.native_id
                    payload['native_history']=session.doc.get('native_history',False)
                job={'id':ident,'executor':executor,'token':secrets.token_urlsafe(32),'payload':payload,
                    'state':'queued','created_at':time.time(),'metadata':metadata}
                if len(json.dumps(job,ensure_ascii=False).encode())>core.MAX_BYTES:raise Invalid('Execution context exceeds 32 MiB; use artifact references')
                self.save(db,job);db.commit()
            elif json.loads(row[0])['executor']!=executor or json.loads(row[0])['metadata']!=metadata:
                raise Conflict('Execution ID already belongs to another task or executor')
        if session:
            session.doc['executor_id']=executor;session.save()
            session.remote_control=lambda **kw:self.control(ident,**kw)
            with session.manager.lock:session.manager.live[session.doc['id']]=session
        deferred=False
        try:
            with self.lock:
                job=self.get(ident);self.refresh(job,session)
                if job['state'] not in FINAL:
                    self.waiting[ident]=session;deferred=True
                    raise RemotePending(ident)
            if session:
                if job['state']=='completed':session.doc.update(state='exited',returncode=self.result(job)['returncode'])
                else:session.doc.update(state='interrupted' if job['state']=='unknown' else 'error',error=job.get('error'))
            if job['state']=='unknown':raise CommandNotStopped(job.get('error','Remote process state is unknown'))
            if job['state']=='failed':raise Invalid(job.get('error','Remote process failed'))
            result=self.result(job);return subprocess.CompletedProcess(command,result['returncode'],result.get('stdout',''),result.get('stderr',''))
        finally:
            if not deferred:
                with self.lock:self.waiting.pop(ident,None)
            if session and not deferred:
                with session.manager.lock:session.manager.live.pop(session.doc['id'],None)
                if self.get(ident)['state'] in FINAL:
                    session.doc['ended_at']=time.time();session.finish_recording();session.save()


def service(store):
    if not hasattr(store,'_executors'):store._executors=Executors(store)
    return store._executors


def run(engine, config, command, prompt, timeout=None, cwd=None, stop=None, session=None, ident=None, metadata=None):
    if not config.get('executor'):
        from loop_anything.runtime.host_runtime import run_command
        return run_command(command,prompt,timeout,cwd,stop,session)
    return service(engine.store).run(config,command,prompt,timeout,cwd,stop,session,ident or session.doc['id'],metadata or {})


def reattach_resume(engine, job):
    """Reattach the existing process receipt; never launch another CLI on recovery."""
    from loop_anything.interfaces.agent_tasks import owner_for,release_in_run
    metadata=job['metadata'];run_id=metadata['run_id'];execution_id=metadata['execution_id']
    current=engine.store.get(run_id)
    owner=next((o for o in current.get('agent_sessions',[]) if o.get('resume_session')==job['id']),None)
    token=owner['token'] if owner else None
    session=engine.terminals.attach(job['id'],[token] if token else [])
    def check():
        latest=engine.store.get(run_id)
        if not token or not owner_for(latest,token):return 'finished'
        if latest['status'] in ('completed','terminated'):return 'revoked'
    session.check=check
    uncertain=False
    try:
        spec=job['payload'];config=dict(spec,executor=job['executor'])
        service(engine.store).run(config,spec['command'],spec['prompt'],spec.get('timeout'),spec.get('cwd'),engine.stopping,session,job['id'],metadata)
    except (CommandNotStopped,RemotePending):uncertain=True
    finally:
        if not uncertain:
            with engine.store.edit(run_id) as latest:
                attempt=engine.execution(latest,execution_id)
                if attempt.get('worker_active')==job['id']:attempt.pop('worker_active')
                if token and owner_for(latest,token):release_in_run(latest,token)
            service(engine.store).applied(job['id'])
