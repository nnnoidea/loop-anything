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
        from loop_anything.runtime.communication import service
        self.communication = service(store)
        self.communication.engine = self

    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=True)

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
        if self.communication.identity_conflict:
            raise Invalid('Copied/moved platform identity; configure a new instance before running copied work')
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
        self.terminals.recover()
        self.communication.recover()
        for summary in self.store.list():
            if summary.get('schema_version') != 2:
                continue
            with self.store.edit(summary['id']) as run:
                self.timeline_runtime.recover(run)
