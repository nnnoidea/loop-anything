"""Thin host for the Timeline scheduler; declared report routes use the Timeline writer."""
import time
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime.store import Store
from loop_anything.runtime.timeline_runtime import TimelineRuntime


class Engine:
    def __init__(self, store):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=8)
        self.futures = set()
        self.stopping = Event()
        self.timeline_runtime = TimelineRuntime(self)
        from loop_anything.runtime.terminal import TerminalSessions
        self.terminals = TerminalSessions(store)
        from loop_anything.runtime.executors import service as executors
        self.executors=executors(store);self.executors.engine=self
        self.executors.waiting.clear();self.executors.completing.clear()
        from loop_anything.runtime.communication import service
        self.communication = service(store)
        self.communication.engine = self

    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=True)

    def mounted_path(self, value):
        if not getattr(self,'team_root',None):return value
        from loop_anything.runtime.tool_client import module
        return module('platform_transport').mount_path(value,self.team_roots,self.team_root)

    def implementation(self, value):
        value=dict(value)
        if 'cwd' in value:value['cwd']=self.mounted_path(value['cwd'])
        # Authors explicitly mark team-relative argv; ordinary arguments stay verbatim.
        for key in ('command','observe','resume_command'):
            if key in value and getattr(self,'team_root',None):
                value[key]=[s.replace('{{team_root}}',self.team_root) for s in value[key]] if not value.get('executor') else value[key]
        return value

    @staticmethod
    def execution(run, execution_id):
        try:
            return next(e for e in run['executions'] if e['id'] == execution_id)
        except StopIteration:
            raise Invalid('Unknown execution')

    def current(self, run_id):
        run = self.store.get(run_id)
        if run.get('schema_version') != 2:
            raise Invalid('Legacy v1 Runs are inspect-only; publish a Timeline-based Loop to execute')
        return run

    def tick(self, run_id):
        self.executors.advance()
        if self.store.get(run_id).get('identity_read_only'):return
        if self.communication.identity_conflict:
            raise Invalid('Copied workspace or mismatched machine identity; configure a new workspace identity before starting new work')
        self.current(run_id)
        return self.timeline_runtime.tick(run_id)

    def change_settings(self, run_id, revision, change, operator_token=None):
        self.current(run_id)
        return self.timeline_runtime.change_settings(run_id, revision, change, operator_token)

    def command(self, run_id, action, execution_id=None, **options):
        self.current(run_id)
        self.timeline_runtime.command(run_id, action, execution_id, **options)
        return self.store.get(run_id)

    def submit(self, run_id, execution_id, token, envelope):
        self.current(run_id)
        return self.timeline_runtime.submit(run_id, execution_id, token, envelope)

    def event(self, run_id, event_id, name, payload, key=None):
        self.current(run_id)
        from loop_anything.runtime.notifications import receive_event
        with self.store.edit(run_id) as run:
            receive_event(run, event_id, name, payload, key)

    def recover(self):
        if self.communication.identity_conflict:return
        claims=[j for j in self.executors.pending() if j['metadata'].get('kind') in ('task','communication','resume')]
        self.remote_claims={j['id']:j for j in claims}
        pending=[j for j in claims if j['state']!='unknown']
        self.remote_recovery={j['id']:j for j in pending}
        self.terminals.recover(self.remote_recovery)
        self.communication.recover()
        for summary in self.store.list():
            if summary.get('schema_version') != 2 or summary.get('identity_read_only'):
                continue
            with self.store.edit(summary['id']) as run:
                self.timeline_runtime.recover(run)
        for job in pending:
            self.futures.add(self.pool.submit(self.resume_remote,job))

    def resume_remote(self, job):
        metadata=job['metadata']
        if metadata['kind']=='task':
            run=self.store.get(metadata['run_id']);execution=self.execution(run,metadata['execution_id'])
            self.timeline_runtime.execute(run['id'],execution,run,metadata.get('observe',False),job['id'],True)
        elif metadata['kind']=='communication':
            ident=metadata['request_id'];self.communication.live[ident]=True
            self.communication.execute(ident,reconnect=True)
        else:
            from loop_anything.runtime.executors import reattach_resume
            reattach_resume(self,job)
