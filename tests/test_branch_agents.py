"""Disjoint branch planning, cross-branch denial, shared joins and real concurrent CLI calls."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.interfaces.agent_tasks import RunTools, acquire, edit_tasks, recover_owner
from loop_anything.runtime.model import Conflict, Invalid
from test_run_agent import definition, task_spec, enable_fallback


class BranchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
        self.engine = Engine(self.store)
        self.bp, self.impl = definition()

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def start(self):
        key = self.store.publish(self.bp, self.impl)['key']
        self.id = self.store.create(key, 'Branches', acquire=True)['id']
        root = RunTools(self.store, self.id, self.read()['agent_sessions'][0]['token'])
        info = root.call('read_task', {'task_id': 'init'})
        root.call('complete_task', {'task_id': 'init', 'task_version': info['task_version'], 'envelope': {
            'settings': {'objective': 'Compare two independent branches'}, 'outputs': {'result': 'start'},
            'tasks': [task_spec('a', 'reason'), task_spec('b', 'reason'),
                      task_spec('join', 'finish', {'value': {'record': 'a.result'}}, after=['a', 'b'])]}})
        root.call('finish', {})
        self.engine.tick(self.id)
        return {o['task_id']: RunTools(self.store, self.id, o['token']) for o in self.read()['agent_sessions']}

    def read(self):
        return self.store.get(self.id)

    def complete(self, tools, task, **extra):
        info = tools.call('read_task', {'task_id': task})
        return tools.call('complete_task', {'task_id': task, 'task_version': info['task_version'],
            'envelope': dict(outputs={'result': task}, **extra)})

    def test_branch_planning_cannot_edit_peer_ancestor_or_shared_join(self):
        agents = self.start()
        self.assertEqual({'a', 'b'}, set(agents))
        a, b = agents['a'], agents['b']
        self.assertEqual({'a', 'b'}, {o['scope_task'] for o in self.read()['agent_sessions']})
        self.assertEqual('init', self.read()['tasks']['join']['parent_id'])
        a.call('read_task', {'task_id': 'b'})  # Reading does not confer write permission.
        for ident in ['b', 'join', 'init']:
            before = self.read()
            with self.assertRaises(Conflict):
                a.call('change_task', {'task_id': ident, 'operation': 'cancel', 'reason': 'out of scope'})
            self.assertEqual(before, self.read())
        with self.assertRaises(Conflict):
            self.complete(a, 'b')
        with self.assertRaises(Conflict):
            a.call('change_settings', {'revision': self.read()['settings']['revision'], 'change': {'objective': 'steal'}})
        with self.assertRaises(Conflict):
            a.call('add_task', {'key': 'outside', 'node_id': 'reason', 'inputs': {}, 'parent_id': 'b'})
        with self.assertRaises(Conflict):
            self.complete(a, 'a', tasks=[task_spec('fake', 'reason', parent_id='b')])
        with self.assertRaises(Conflict):
            self.complete(a, 'a', tasks=[dict(task_spec('fake', 'reason'), outputs={'result': {'id': 'b.result', 'expected_revision': 1}})])
        child_a = a.call('add_task', {'key': 'next', 'node_id': 'reason', 'inputs': {}})['tasks'][0]
        child_b = b.call('add_task', {'key': 'next', 'node_id': 'reason', 'inputs': {}})['tasks'][0]
        self.assertNotEqual(child_a['id'], child_b['id'])
        self.assertEqual('a', self.read()['tasks'][child_a['id']]['parent_id'])
        a.call('change_task', {'task_id': child_a['id'], 'operation': 'update', 'parameters': {'topic': 'changed'}, 'reason': 'my branch'})
        with self.assertRaises(Conflict):
            acquire(self.store, self.id, 'init')
        self.complete(a, 'a');a.call('finish', {})
        self.assertEqual([b.token], [o['token'] for o in self.read()['agent_sessions']])
        self.engine.tick(self.id)
        scopes = {o['scope_task'] for o in self.read()['agent_sessions']}
        self.assertEqual({'b', child_a['id']}, scopes)
        with self.assertRaises(Conflict):
            acquire(self.store, self.id, 'a')
        with self.assertRaises(Conflict):
            acquire(self.store, self.id)
        self.complete(b, 'b');b.call('finish', {})

    def test_scope_recovery_keeps_other_operators_and_global_node_waits(self):
        self.bp['global_agent_node'] = 'finish'
        agents = self.start()
        a, b = agents['a'], agents['b']
        with self.store.edit(self.id) as run:
            next(o for o in run['agent_sessions'] if o['token'] == a.token)['recovery_required'] = True
        with self.assertRaises(Conflict):
            recover_owner(self.store, self.id, a.token)
        recover_owner(self.store, self.id, a.token, confirmed_stopped=True)
        self.assertEqual([b.token], [o['token'] for o in self.read()['agent_sessions']])
        # A confirmed exit changes only its scope's counter, not another branch's.
        self.assertEqual(0, self.read().get('agent_failures', 0))
        # Explicit recovery releases only the confirmed operator; its task is still unresolved.
        with self.assertRaises(Conflict):
            acquire(self.store, self.id)
        resumed = acquire(self.store, self.id, 'a')
        a = RunTools(self.store, self.id, resumed['token'])
        self.complete(a, 'a');a.call('finish', {})
        self.complete(b, 'b');b.call('finish', {})
        self.engine.tick(self.id)
        global_owner = self.read()['agent_sessions'][0]
        self.assertEqual('join', global_owner['task_id'])
        self.assertIsNone(global_owner['scope_task'])

    def test_existing_operator_keeps_its_global_scope(self):
        key = self.store.publish(self.bp, self.impl)['key']
        run = self.store.create(key, 'Existing owner', acquire=True)
        self.id = run['id']
        original = run['agent_sessions'][0]
        with self.store.connection() as db:
            header = json.loads(db.execute('SELECT document FROM runs WHERE id=?', (self.id,)).fetchone()[0])
            header['agent_session'] = header.pop('agent_sessions')[0]
            header['agent_session'].pop('scope_task', None)
            header['agent_session'].pop('task_id', None)
            db.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(header), self.id))
            db.commit()
        converted = self.read()
        self.assertEqual(original['token'], converted['agent_sessions'][0]['token'])
        self.assertIsNone(converted['agent_sessions'][0]['scope_task'])
        with self.assertRaises(Conflict):
            acquire(self.store, self.id, 'init')
        with self.assertRaises(Conflict):
            RunTools(self.store, self.id, original['token']).call('finish', {})

    def test_two_real_agent_commands_overlap_without_sharing_tokens(self):
        directory = Path(self.tmp.name)
        script = directory / 'agent.py'
        script.write_text('''import json,sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
p=json.loads(sys.stdin.read().split('Run context:\\n',1)[1])
root=Path(sys.argv[1]);root.joinpath(p['task_id']+'.started').write_text(p['token'])
limit=time.time()+8
while len(list(root.glob('*.started')))<2 and time.time()<limit:time.sleep(.02)
assert len(list(root.glob('*.started')))==2, 'Agents were serialized'
t=RunTools(Store(sys.argv[3]),p['run_id'],p['token'])
i=t.call('read_task',{'task_id':p['task_id']})
t.call('complete_task',{'task_id':p['task_id'],'task_version':i['task_version'],'envelope':{'outputs':{'result':p['task_id']}}})
t.call('finish',{})
''')
        self.impl['reason'] = {'kind': 'agent', 'command': [sys.executable, str(script), str(directory), str(Path.cwd()), str(self.store.filename)], 'cwd': str(Path.cwd()), 'timeout': 12}
        self.start()
        limit = time.time()+12
        while time.time()<limit:
            self.engine.tick(self.id)
            run = self.read()
            if all(run['tasks'][k]['status']=='completed' for k in ['a','b']):
                break
            time.sleep(.02)
        self.assertEqual({'a','b'}, {p.stem for p in directory.glob('*.started')})
        self.assertNotEqual((directory/'a.started').read_text(), (directory/'b.started').read_text())
        self.assertEqual(['completed','completed'], [self.read()['tasks'][k]['status'] for k in ['a','b']])
