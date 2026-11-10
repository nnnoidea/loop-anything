"""Workspace web controls for registrations executed on the server host."""
from pathlib import Path
import socket
import threading
import traceback

from loop_anything.runtime.local_tasks import LocalRuntime, TaskRegistry, schedule_summary
from loop_anything.runtime.model import Conflict, Invalid


ACTIVE_STATES = ('waiting', 'checking', 'running')


class ScheduleControls:
    def __init__(self, database):
        self.registry = TaskRegistry(str(Path(database).resolve()) + '.schedules')
        self.active = {}
        self.lock = threading.Lock()
        self.closed = False

    def list(self):
        tasks = []
        for item in self.registry.list():
            definition = item['definition']
            state = item['runtime']
            active_schedule = state.get('schedule') if state['status'] in ACTIVE_STATES else None
            if (active_schedule or definition).get('receiver'):
                continue
            runtime = {key: state[key] for key in ('status', 'owner', 'next_at', 'last_result', 'error', 'definition_revision')
                       if key in state}
            if active_schedule and state['definition_revision'] != item['revision']:
                runtime['schedule'] = active_schedule
            execution = item['execution']
            tasks.append({'id': item['id'], 'revision': item['revision'], 'definition': schedule_summary(definition),
                          'runtime': runtime, 'execution': {'state': execution['state']} if execution else None})
        tasks.sort(key=lambda item: (item['definition']['name'].casefold(), item['id']))
        return {'directory': str(self.registry.root), 'machine': socket.gethostname(), 'tasks': tasks}

    def control(self, ident, action, body):
        if action not in ('start', 'stop'):
            raise Invalid('Unknown schedule action')
        with self.lock:
            if self.closed:
                raise Conflict('Platform is stopping')
            item = self.registry.show(ident)
            state = item['runtime']
            definition = (state.get('schedule') or item['definition']) if action == 'stop' and state['status'] in ACTIVE_STATES else item['definition']
            if definition.get('receiver'):
                raise Invalid('Use the client CLI to control a receiver registration')
            owner = state.get('owner')
            if 'owner' not in body or body['owner'] != owner:
                raise Conflict('Schedule execution changed; refresh the page')
            if action == 'stop':
                if not owner or state['status'] not in ACTIVE_STATES:
                    raise Conflict('This schedule has no active execution to stop')
                return self.registry.stop(ident, expected_owner=owner)
            if type(body.get('revision')) is not int or body['revision'] != item['revision']:
                raise Conflict('Schedule definition changed; refresh the page')
            if ident in self.active:
                raise Conflict('This schedule is still active')
            runtime = LocalRuntime(self.registry, [ident], jobs=1, expected={ident: (item['revision'], owner)})
            thread = threading.Thread(target=self.run, args=(ident, runtime), name='web-schedule-' + ident)
            self.active[ident] = (runtime, thread)
            try:
                thread.start()
            except BaseException:
                self.active.pop(ident)
                runtime.close()
                raise
        return {'id': ident, 'started': True}

    def run(self, ident, runtime):
        try:
            runtime.run()
        except Exception:
            traceback.print_exc()
        finally:
            with self.lock:
                self.active.pop(ident, None)

    def close(self):
        with self.lock:
            self.closed = True
            active = list(self.active.values())
            for runtime, _ in active:
                runtime.stop.set()
        for _, thread in active:
            thread.join()
