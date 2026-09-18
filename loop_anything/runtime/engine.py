"""Thin host for the Timeline scheduler. It never constructs or routes Tasks."""
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
        if not isinstance(event_id, str) or not event_id or not isinstance(payload, dict):
            raise Invalid('Event id and object payload required')
        with self.store.edit(run_id) as run:
            if run['status'] in ('terminated', 'completed'):
                raise Conflict('Run has ended')
            old = next((x for x in run['events'] if x['id'] == event_id), None)
            if old:
                if old['name'] != name or old['payload'] != payload or old.get('key') != key:
                    raise Conflict('Event id already used for different data')
                return
            run['events'].append({'id': event_id, 'name': name, 'key': key, 'payload': payload, 'at': time.time()})
            Store.log(run, 'event', 'External event received: ' + name)

    def recover(self):
        for summary in self.store.list():
            if summary.get('schema_version') != 2:
                continue
            with self.store.edit(summary['id']) as run:
                self.timeline_runtime.recover(run)
