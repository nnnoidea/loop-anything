"""Workspace web controls for registrations executed on the server host."""
from pathlib import Path
import socket
import threading
import traceback

from loop_anything.runtime.local_tasks import LocalRuntime, TaskRegistry, registry_directory, schedule_summary
from loop_anything.runtime.model import Conflict, Invalid


ACTIVE_STATES = ('waiting', 'checking', 'running')


class ScheduleControls:
    def __init__(self, database, local=True, *, registry_root=None, read_only=False):
        self.database = Path(database).resolve()
        self.local = local
        self.registry_root = registry_root
        self.read_only = read_only
        self.active = {}
        self.lock = threading.Lock()
        self.closed = False

    @property
    def registry(self):
        if self.registry_root is not None:
            return TaskRegistry(self.registry_root)
        directory = registry_directory(self.database) if self.local else str(self.database) + '.schedules'
        return TaskRegistry(directory)

    def list(self):
        registry = self.registry
        tasks = []
        for item in registry.list():
            definition = item['definition']
            state = item['runtime']
            active_schedule = state.get('schedule') if state['status'] in ACTIVE_STATES else None
            if (active_schedule or definition).get('receiver'):
                continue
            runtime = {key: state[key] for key in (('status', 'next_at', 'definition_revision') if self.read_only else
                       ('status', 'owner', 'next_at', 'last_result', 'error', 'definition_revision'))
                       if key in state}
            if self.read_only and state.get('last_result'):
                result = state['last_result']
                runtime['last_result'] = {key: result[key] for key in ('at', 'returncode') if key in result}
            if active_schedule and state['definition_revision'] != item['revision']:
                runtime['schedule'] = schedule_summary(active_schedule)
                if self.read_only:
                    runtime['schedule'].pop('description', None)
            execution = item['execution']
            summary = schedule_summary(definition)
            if self.read_only:
                summary.pop('description', None)
            tasks.append({'id': item['id'], 'revision': item['revision'], 'definition': summary,
                          'runtime': runtime, 'execution': {'state': execution['state']} if execution else None})
        tasks.sort(key=lambda item: (item['definition']['name'].casefold(), item['id']))
        return {'directory': '本机登记目录' if self.read_only else str(registry.root),
                'machine': '平台所在机器' if self.read_only else socket.gethostname(),
                'read_only': self.read_only, 'tasks': tasks}

    def control(self, ident, action, body):
        if self.read_only:
            raise Conflict('Schedules are read-only in this workspace')
        if action not in ('start', 'stop'):
            raise Invalid('Unknown schedule action')
        with self.lock:
            if self.closed:
                raise Conflict('Platform is stopping')
            registry = self.registry
            if body.get('directory') != str(registry.root):
                raise Conflict('Schedule directory changed; refresh the page')
            item = registry.show(ident)
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
                return registry.stop(ident, expected_owner=owner)
            if type(body.get('revision')) is not int or body['revision'] != item['revision']:
                raise Conflict('Schedule definition changed; refresh the page')
            key = (registry.root, ident)
            if key in self.active:
                raise Conflict('This schedule is still active')
            runtime = LocalRuntime(registry, [ident], jobs=1, expected={ident: (item['revision'], owner)})
            thread = threading.Thread(target=self.run, args=(key, runtime), name='web-schedule-' + ident)
            self.active[key] = (runtime, thread)
            try:
                thread.start()
            except BaseException:
                self.active.pop(key)
                runtime.close()
                raise
        return {'id': ident, 'started': True}

    def run(self, key, runtime):
        try:
            runtime.run()
        except Exception:
            traceback.print_exc()
        finally:
            with self.lock:
                self.active.pop(key, None)

    def close(self):
        with self.lock:
            self.closed = True
            active = list(self.active.values())
            for runtime, _ in active:
                runtime.stop.set()
        for _, thread in active:
            thread.join()
