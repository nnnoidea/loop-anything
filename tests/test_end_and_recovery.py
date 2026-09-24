"""Terminal transitions and bounded Agent recovery use actual Timeline/Engine paths."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from loop_anything.interfaces.agent_tasks import RunTools, acquire, recover_owner, agent_calls
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.host_runtime import run_command, CommandNotStopped
from loop_anything.runtime.model import Conflict
from loop_anything.runtime.store import Store
from test_run_agent import definition, task_spec, enable_fallback


class EndAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'runs.db')
        self.engine = Engine(self.store)
        self.bp, self.implementations = definition()

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def create(self, owned=True):
        key = self.store.publish(self.bp, self.implementations)['key']
        run = self.store.create(key, 'Recovery test', acquire=owned)
        self.id = run['id']
        if owned:
            self.tools = RunTools(self.store, self.id, run['agent_sessions'][0]['token'])

    def complete(self, id, **envelope):
        info = self.tools.call('read_task', {'task_id': id})
        self.tools.call('complete_task', {'task_id': id, 'task_version': info['task_version'],
                                        'envelope': dict(outputs={'result': 'done'}, **envelope)})

    def until(self, condition):
        for _ in range(250):
            self.engine.tick(self.id)
            run = self.store.get(self.id)
            if condition(run):
                return run
            time.sleep(.02)
        self.fail(str(self.store.get(self.id)))

    def test_settings_rule_waits_for_multiple_rounds_then_engine_ends(self):
        self.create()
        rule = {'op': 'and', 'args': [
            {'op': 'ge', 'args': [{'path': ['completed', 'reason']}, 2]},
            {'op': 'eq', 'args': [{'path': ['records', 'round.2.result']}, 'done']}]}
        self.complete('init', settings={'objective': 'Two rounds', 'completion_rule': rule},
                      tasks=[task_spec('round.1', 'reason')])
        self.complete('round.1', tasks=[task_spec('round.2', 'reason')])
        self.engine.tick(self.id)
        self.assertEqual('running', self.store.get(self.id)['status'])
        self.complete('round.2')
        self.assertEqual('running', self.store.get(self.id)['status'])  # A write does not bypass Engine.
        self.engine.tick(self.id)
        run = self.store.get(self.id)
        self.assertEqual('completed', run['status'])
        self.assertEqual({'init', 'round.1', 'round.2'}, set(run['tasks']))
        self.assertEqual('Timeline completion rule matched', run['completion']['reason'])
        self.tools.call('finish', {})

    def test_agent_signal_ends_via_engine_without_a_completion_task(self):
        self.create()
        self.complete('init', settings={'objective': 'User purpose'})
        self.tools.call('finish', {})
        self.engine.tick(self.id)
        self.assertEqual('running', self.store.get(self.id)['status'])
        self.assertEqual([], self.store.get(self.id)['diagnostics'])
        owner = acquire(self.store, self.id)
        self.tools = RunTools(self.store, self.id, owner['token'])
        self.tools.call('command', {'action': 'pause'})
        self.tools.call('change_settings', {'revision': 1, 'change': {'termination_signal': 'Purpose achieved'}})
        self.assertIn(self.id, [r['id'] for r in self.store.scheduling_list()])
        self.engine.tick(self.id)
        run = self.store.get(self.id)
        self.assertEqual('completed', run['status'])
        self.assertEqual('Purpose achieved', run['completion']['reason'])
        self.assertEqual(['init'], list(run['tasks']))

    def test_disabled_fallback_keeps_uncovered_state_without_choosing_an_agent(self):
        self.create()
        self.complete('init', settings={'objective': 'Wait for user choices'})
        self.tools.call('finish', {})
        self.engine.event(self.id, 'unknown', 'not-declared', {})
        for _ in range(5):
            self.engine.tick(self.id)
        run = self.store.get(self.id)
        self.assertEqual(0, agent_calls(run))
        self.assertEqual(['init'], list(run['tasks']))
        self.assertEqual('unexpected', run['attention_state'])
        self.assertEqual([], run['agent_sessions'])

    def test_selected_fallback_uses_normal_node_skill_binding_and_pause_hook(self):
        marker = self.root / 'selected-agent.txt'
        script = """import json,sys
from pathlib import Path
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
r=json.loads(sys.stdin.read().split('Run context:'+chr(10),1)[1]);t=RunTools(Store(sys.argv[-1]),r['run_id'],r['token'])
i=t.call('read_task',{'task_id':r['task_id']})
assert i['skills'][0]['name']=='recovery'
assert i['task']['origin']['issues']
for item in t.call('next_tasks',{})['items']:
 if item['kind']!='task':t.call('defer_task',{'task_id':item['id'],'reason':'User must classify this event'})
t.call('complete_task',{'task_id':r['task_id'],'task_version':i['task_version'],'envelope':{'outputs':{}}})
t.call('finish',{})
Path(sys.argv[1]).write_text(sys.argv[2])
"""
        configs = {key: {'kind': 'agent', 'command': [sys.executable, '-c', script, str(marker), key, str(self.store.filename)],
                         'cwd': str(Path(__file__).resolve().parents[1])} for key in ('first', 'chosen')}
        enable_fallback(self.bp, self.implementations, {'options': configs, 'default': 'first'})
        self.create()
        self.complete('init', settings={'objective': 'Explicit fallback'})
        self.tools.call('change_settings', {'revision': 1, 'change': {'bindings': {'fallback': 'chosen'},
            'hooks': [{'id': 'fallback-gate', 'action': 'pause', 'phase': 'before', 'frequency': 'once', 'target': {'node': 'fallback'}}]}})
        self.tools.call('finish', {})
        self.engine.event(self.id, 'unknown', 'not-declared', {})
        run = self.until(lambda r: any(w['status'] == 'held' for w in r['tasks'].values()))
        self.assertFalse(marker.exists())
        self.assertEqual(0, agent_calls(run))
        self.engine.command(self.id, 'release_gate', hook_firing=run['hook_firings'][0]['id'])
        run = self.until(lambda r: marker.exists() and r['agent_sessions'] == [])
        self.assertEqual('chosen', marker.read_text())
        self.assertEqual(1, agent_calls(run))
        fallback = next(w for w in run['tasks'].values() if w['origin'].get('fallback'))
        self.assertEqual('fallback', fallback['spec']['node'])
        self.assertEqual('completed', fallback['status'])
        self.assertEqual('chosen', next(e for e in run['executions'] if e['task_id'] == fallback['id'])['implementation_id'])

    def test_three_failures_pause_and_notify_using_user_sender_once(self):
        self.implementations['init'] = {'kind': 'agent', 'command': [sys.executable, '-c', 'raise SystemExit(2)']}
        enable_fallback(self.bp, self.implementations, self.implementations['init'])
        delivered = self.root / 'notification.json'
        sender = "import json,sys;from pathlib import Path;r=json.load(sys.stdin);Path(sys.argv[1]).write_text(json.dumps(r));print(json.dumps({'delivered':True}))"
        self.store.notification_channels({'test-chat':{'command':[sys.executable,'-c',sender,str(delivered)]}},0)
        self.create(owned=False)
        self.engine.change_settings(self.id,1,{'notification_route':'test-chat'})
        run = self.until(lambda r: r['status'] == 'paused' and r['notifications'] and r['notifications'][0]['status'] == 'delivered')
        self.assertEqual(3, run['agent_failures'])
        self.assertEqual(3, agent_calls(run))
        fallback_tasks = [t for t in run['tasks'].values() if t['origin'].get('fallback')]
        self.assertEqual(1, len(fallback_tasks))
        self.assertEqual(2, fallback_tasks[0]['attempts'])
        self.assertEqual([], run['agent_sessions'])
        self.assertEqual(self.id, json.loads(delivered.read_text())['run_id'])
        self.engine.recover()
        for _ in range(5):
            self.engine.tick(self.id)
        self.assertEqual(1, len(self.store.get(self.id)['notifications']))
        self.assertEqual(3, agent_calls(self.store.get(self.id)))
        self.engine.command(self.id, 'resume')
        self.assertEqual(0, self.store.get(self.id)['agent_failures'])

    def test_branch_failure_then_fallback_pauses_after_three_total_calls(self):
        failure = {'kind': 'agent', 'command': [sys.executable, '-c', 'raise SystemExit(2)']}
        self.implementations['reason'] = failure
        enable_fallback(self.bp, self.implementations, failure)
        self.create()
        self.complete('init', settings={'objective': 'Recover one branch'}, tasks=[task_spec('branch', 'reason')])
        self.tools.call('finish', {})
        run = self.until(lambda r: r['status'] == 'paused' and not r['agent_sessions'])
        self.assertEqual(3, agent_calls(run))
        self.assertEqual(['reason', 'fallback', 'fallback'], [e['node'] for e in run['executions'] if e['status'] == 'fault'])
        self.assertEqual(1, run['tasks']['branch']['agent_failures'])
        self.engine.command(self.id, 'resume')
        self.assertEqual(0, self.store.get(self.id)['agent_failures'])
        self.assertTrue(all(not t.get('agent_failures') for t in self.store.get(self.id)['tasks'].values()))

    def test_boolean_rule_short_circuits_unneeded_missing_results(self):
        from loop_anything.runtime.timeline_runtime import end_condition
        self.create()
        run = self.store.get(self.id)
        missing = {'op': 'eq', 'args': [{'path': ['records', 'later']}, 'done']}
        run['settings']['completion_rule'] = {'op': 'or', 'args': [True, missing]}
        self.assertIsNotNone(end_condition(run)[0])
        run['settings']['completion_rule'] = {'op': 'and', 'args': [False, missing]}
        self.assertEqual((None, None), end_condition(run))

    def test_successful_recovery_resets_consecutive_failure_count(self):
        marker = self.root / 'calls.txt'
        script = """import json,sys
from pathlib import Path
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
p=Path(sys.argv[1]);n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n))
if n==1: raise SystemExit(2)
r=json.loads(sys.stdin.read().split('Run context:'+chr(10),1)[1]);t=RunTools(Store(sys.argv[-1]),r['run_id'],r['token'])
t.call('change_task',{'task_id':'init','operation':'retry','reason':'Previous Agent exited before producing output'})
i=t.call('read_task',{'task_id':'init'})
t.call('complete_task',{'task_id':'init','task_version':i['task_version'],'envelope':{'outputs':{'result':'recovered'},'settings':{'objective':'Recovered'}}})
i=t.call('read_task',{'task_id':r['task_id']})
t.call('complete_task',{'task_id':r['task_id'],'task_version':i['task_version'],'envelope':{'outputs':{}}})
t.call('finish',{})
"""
        self.implementations['init'] = {'kind': 'agent', 'command': [sys.executable, '-c', script, str(marker), str(self.store.filename)],
                                 'cwd': str(Path(__file__).resolve().parents[1])}
        enable_fallback(self.bp, self.implementations, self.implementations['init'])
        self.create(owned=False)
        run = self.until(lambda r: r['initialized'] and r['agent_sessions'] == [] and r['agent_failures'] == 0)
        self.assertEqual(2, agent_calls(run))
        self.assertEqual('recovered', run['records']['init.result'][0]['value'])
        self.assertEqual('running', run['status'])  # No rule or signal inferred from success.

    def test_interactive_recovery_and_unconfirmed_stop_keep_single_owner(self):
        self.create()
        old = self.tools.token
        self.engine.recover()
        with self.assertRaises(Conflict):
            acquire(self.store, self.id)
        with self.assertRaises(Conflict):
            recover_owner(self.store, self.id, old)
        recover_owner(self.store, self.id, old, confirmed_stopped=True)
        new = acquire(self.store, self.id)
        self.assertNotEqual(old, new['token'])
        with self.assertRaises(Conflict):
            self.tools.call('read_timeline', {})
        process = Mock()
        process.pid = 12345
        process.communicate.side_effect = subprocess.TimeoutExpired(['test'], 1)
        with patch('loop_anything.runtime.host_runtime.subprocess.Popen', return_value=process), patch('loop_anything.runtime.host_runtime.os.killpg', side_effect=PermissionError('denied')):
            with self.assertRaises(CommandNotStopped):
                run_command(['test'], '{}', 1)
