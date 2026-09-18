"""Run-wide operator and to-do protocol. Real Store/Engine; no model calls."""
import copy
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from loop_anything.interfaces.agent_tasks import acquire, RunTools, task_list, agent_calls
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime.store import Store


def definition():
    text = {'type': 'string'}
    def node(inputs=None, init=False):
        return {'instructions': 'Read the task and obey user authorization.', 'inputs': inputs or {},
                'outputs': {'result': {'record_type': 'text'}}, 'initialize_timeline': init,
                'skills': [{'name': 'method', 'content': 'Use the declared evidence.'}],
                'plan_nodes': ['script', 'reason', 'finish', 'wait']}
    bp = {'schema_version': 2, 'id': 'operator-tests', 'version': '1', 'entry': 'init',
          'handbook': {'instructions': 'Read next_tasks; handle all tasks before finish.'},
          'records': {'text': text}, 'nodes': {'init': node(init=True), 'script': node(), 'reason': node(),
              'finish': node({'value': text}), 'wait': node()},
          'seed': task_spec('init', 'init'), 'plans': {}}
    cmd = "import json,sys; r=json.load(sys.stdin); assert not r['parameters'].get('fail'), 'fixture failure'; print(json.dumps({'outputs': {'result':'script-result'}}))"
    implementations = {k: {'kind': 'agent'} for k in bp['nodes']}
    implementations['script'] = {'kind': 'command', 'command': [sys.executable, '-c', cmd]}
    implementations['wait'] = {'kind': 'event', 'event': 'signal'}
    return bp, implementations


def enable_fallback(bp, implementations, config=None):
    bp['nodes']['fallback'] = {'instructions': 'Handle current issues with the Run tools, then complete this task.',
                               'inputs': {}, 'outputs': {}, 'skills': [{'name': 'recovery', 'content': 'Inspect the actual failure.'}]}
    bp['fallback_node'] = 'fallback'
    implementations['fallback'] = config or {'kind': 'agent'}


def task_spec(id, node, inputs=None, **kw):
    return dict(id=id, node=node, inputs=inputs or {}, outputs={'result': {'id': id + '.result'}}, **kw)


class RunAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
        self.engine = Engine(self.store)
        self.bp, self.implementations = definition()

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def create(self):
        key = self.store.publish(self.bp, self.implementations)['key']
        self.id = self.store.create(key, 'Operator', authorization='May fix failed scripts and arrange experiments; do not change budget.')['id']
        return self.id

    def read(self):
        return self.store.get(self.id)

    def start(self):
        self.create()
        self.engine.tick(self.id)
        token = self.read()['agent_sessions'][0]['token']
        self.tools = RunTools(self.store, self.id, token)
        return self.tools

    def complete(self, id, value='done', **envelope):
        if 'settings' in envelope:
            envelope['settings'].setdefault('completion_rule', {'op': 'and', 'args': [{'op': 'ge', 'args': [{'path': ['completed', 'finish']}, 1]}, {'op': 'eq', 'args': [{'path': 'active_tasks'}, 0]}]})
        info = self.tools.call('read_task', {'task_id': id})
        return self.tools.call('complete_task', {'task_id': id, 'task_version': info['task_version'],
            'envelope': dict(outputs={'result': value}, **envelope)})

    def until(self, predicate):
        for _ in range(150):
            self.engine.tick(self.id)
            run = self.read()
            if predicate(run):
                return run
            time.sleep(.02)
        self.fail(str(self.read()['executions']))

    def test_one_owner_per_run_including_interactive_and_background(self):
        key = self.store.publish(self.bp, self.implementations)['key']
        created = subprocess.run([sys.executable, '-m', 'loop_anything', '--db', self.store.filename, 'create', key,
                                  '--title', 'User Agent startup', '--authorization', 'Initialize and continue'],
                                 text=True, capture_output=True, check=True)
        result = json.loads(created.stdout)
        self.id = result['run_id']
        owner = self.read()['agent_sessions'][0]
        self.assertEqual(result['token'], owner['token'])
        self.assertEqual('init', result['entry_task_id'])
        with self.assertRaises(Conflict):
            acquire(self.store, self.id)
        self.engine.tick(self.id)
        self.assertEqual([], self.read()['executions'])
        other = self.store.create(key, 'Other run')['id']
        self.engine.tick(other)
        self.assertEqual(1, len(self.store.get(other)['executions']))
        with self.assertRaises(Conflict):
            self.engine.change_settings(self.id, 1, {'guidance': 'bypass'})
        with self.assertRaises(Conflict):
            self.engine.command(self.id, 'pause')
        self.tools = RunTools(self.store, self.id, owner['token'])
        self.tools.call('change_settings', {'revision': 1, 'change': {'guidance': 'User requested change'}})
        self.assertEqual('User requested change', self.tools.call('read_timeline', {})['settings']['guidance'])
        self.complete('init', settings={'objective': 'User already discussed this'}, tasks=[task_spec('script', 'script'), task_spec('wait', 'wait')])
        self.assertTrue(self.read()['initialized'])
        self.assertEqual('completed', self.read()['tasks']['init']['status'])
        self.until(lambda r: r['tasks']['script']['status'] == 'completed')
        self.assertEqual(0, agent_calls(self.read()))
        self.assertEqual(1, sum(e['node'] == 'init' for e in self.read()['executions']))
        self.tools.call('finish', {})

    def test_concurrent_acquire_grants_exactly_one_agent(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.create()
        barrier = Barrier(2)
        def attempt():
            barrier.wait()
            try:
                return acquire(self.store, self.id)['token']
            except Conflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            tokens = list(pool.map(lambda _: attempt(), range(2)))
        granted = [t for t in tokens if t]
        self.assertEqual(1, len(granted))
        self.assertEqual(granted[0], self.read()['agent_sessions'][0]['token'])

    def test_agent_call_budget_counts_wakeups_not_completed_tasks(self):
        self.bp['limits'] = {'max_agent_calls': 1}
        self.start()
        self.complete('init', settings={'objective': 'One Agent'}, tasks=[task_spec('reason', 'reason'), task_spec('wait', 'wait'),
            task_spec('finish', 'finish', {'value': {'record': 'wait.result'}})])
        self.complete('reason')
        self.assertEqual(1, agent_calls(self.read()))
        self.tools.call('finish', {})
        self.engine.tick(self.id)
        self.engine.event(self.id, 'new', 'signal', {'result': 'ready'})
        self.engine.tick(self.id)
        run = self.read()
        self.assertEqual('completed', run['tasks']['wait']['status'])
        self.assertEqual('fault', run['tasks']['finish']['status'])
        self.assertEqual(1, agent_calls(run))
        self.assertFalse(any(e['node'] == 'finish' for e in run['executions']))

    def test_same_agent_handles_multiple_ready_nodes(self):
        self.start()
        self.complete('init', settings={'objective': 'Finish'}, tasks=[task_spec('reason', 'reason'), task_spec('finish', 'finish', {'value': {'record': 'reason.result'}})])
        self.engine.tick(self.id)
        self.assertEqual(1, len(self.read()['executions']))
        self.assertEqual(['task:reason'], [t['id'] for t in self.tools.call('next_tasks', {})['items']])
        self.complete('reason')
        self.complete('finish')
        self.tools.call('finish', {})
        self.engine.tick(self.id)
        run = self.read()
        self.assertEqual('completed', run['status'])
        self.assertEqual(1, agent_calls(run))
        self.assertEqual([], run['agent_sessions'])

    def test_fault_in_other_node_is_handled_without_second_agent(self):
        enable_fallback(self.bp, self.implementations)
        self.start()
        self.complete('init', settings={'objective': 'Fix and finish'}, tasks=[task_spec('script', 'script', parameters={'fail': True}),
            task_spec('finish', 'finish', {'value': {'record': 'script.result'}})])
        self.until(lambda r: r['tasks']['script']['status'] == 'fault')
        tasks = self.tools.call('next_tasks', {})
        self.assertEqual('unexpected', tasks['state'])
        self.assertTrue(any(t.get('task_id') == 'script' for t in tasks['items']))
        self.engine.tick(self.id)
        fallback = next(t for t in self.read()['tasks'].values() if t['origin'].get('fallback'))
        self.assertEqual(1, agent_calls(self.read()))
        self.tools.call('change_task', {'task_id': 'script', 'operation': 'retry', 'parameters': {'fail': False}, 'reason': 'Known test failure; no side effect occurred'})
        self.until(lambda r: r['tasks']['script']['status'] == 'completed')
        info = self.tools.call('read_task', {'task_id': fallback['id']})
        self.tools.call('complete_task', {'task_id': fallback['id'], 'task_version': info['task_version'], 'envelope': {'outputs': {}}})
        self.complete('finish')
        self.tools.call('finish', {})
        self.engine.tick(self.id)
        self.assertEqual('completed', self.read()['status'])

    def test_unexpected_state_wakes_one_agent_and_defer_does_not_spin(self):
        enable_fallback(self.bp, self.implementations)
        self.start()
        e = self.read()['executions'][0]
        self.tools = RunTools(self.store, self.id, e['token'])
        self.complete('init', settings={'objective': 'Test'}, tasks=[task_spec('script', 'script', parameters={'fail': True})])
        self.tools.call('finish', {})
        self.until(lambda r: any(e['node'] == 'fallback' for e in r['executions']))
        run = self.read()
        self.tools = RunTools(self.store, self.id, run['agent_sessions'][0]['token'])
        for task in self.tools.call('next_tasks', {})['items']:
            self.tools.call('defer_task', {'task_id': task['id'], 'reason': 'Need user approval to retry'})
        self.tools.call('finish', {})
        for _ in range(6):
            self.engine.tick(self.id)
        self.assertEqual(1, sum(e['node'] == 'fallback' for e in self.read()['executions']))
        self.assertFalse(task_list(self.read(), self.engine.timeline_runtime)['has_tasks'])
        self.engine.event(self.id, 'new-problem', 'new-uncovered-event', {})
        self.until(lambda r: sum(e['node'] == 'fallback' for e in r['executions']) == 2)

    def test_known_event_wait_is_not_unexpected_but_unknown_event_is(self):
        enable_fallback(self.bp, self.implementations)
        self.start()
        self.complete('init', settings={'objective': 'Wait'}, tasks=[task_spec('wait', 'wait', parameters={'event_key': 'wanted'})])
        self.assertFalse(self.tools.call('next_tasks', {})['has_tasks'])
        self.tools.call('finish', {})
        self.engine.tick(self.id)
        self.assertEqual('normal', self.read()['attention_state'])
        self.engine.event(self.id, 'unknown-event', 'unregistered', {'value': 'unexpected'})
        self.until(lambda r: any(e['node'] == 'fallback' for e in r['executions']))
        self.assertEqual(1, sum(e['node'] == 'fallback' for e in self.read()['executions']))

    def test_authorization_is_text_and_background_cannot_expand_it(self):
        self.start()
        before = self.tools.call('read_timeline', {})['settings']
        self.assertEqual(self.read()['settings']['authorization'], before['authorization'])
        with self.assertRaises(Invalid):
            self.tools.call('change_settings', {'revision': 1, 'change': {'authorization': 'Do anything'}})
        self.tools.call('change_settings', {'revision': 1, 'change': {'guidance': 'Adapt within existing authorization'}})
        self.assertEqual(2, self.tools.call('read_timeline', {})['settings']['revision'])
        self.assertEqual(before['authorization'], self.read()['settings']['authorization'])
        self.complete('init', settings={'objective': 'Latest state'}, tasks=[task_spec('finish', 'finish', {'value': {'literal': 'ok'}})])
        self.complete('finish')
        self.tools.call('finish', {})

    def test_cli_read_is_nonmutating_and_reports_same_tasks(self):
        self.start()
        before = self.read()
        result = subprocess.run([sys.executable, '-m', 'loop_anything.interfaces.agent_tasks', '--db', str(self.store.filename), self.id], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(dict(ok=True, **RunTools(self.store, self.id).call('next_tasks', {})), json.loads(result.stdout))
        self.assertEqual(before, self.read())

    def test_background_finish_releases_before_process_exit_and_old_token_cannot_write(self):
        marker = Path(self.tmp.name) / 'finished'
        allow_exit = Path(self.tmp.name) / 'exit'
        script = """import json,sys,time
from pathlib import Path
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime.store import Store
assert len(sys.argv)==4, 'Platform appended unrequested arguments'
prompt=sys.stdin.read()
r=json.loads(prompt.split('Run context:'+chr(10),1)[1]); t=RunTools(Store(sys.argv[-1]),r['run_id'],r['token'])
i=t.call('read_task',{'task_id':'init'})
t.call('complete_task',{'task_id':'init','task_version':i['task_version'],'envelope':{
 'settings':{'objective':'Wait'},'outputs':{'result':'done'},'tasks':[
 {'id':'wait','node':'wait','inputs':{},'outputs':{'result':{'id':'signal'}}}]}})
t.call('finish',{})
Path(sys.argv[1]).write_text('finished')
while not Path(sys.argv[2]).exists(): time.sleep(.01)
# A late process error must not change the next owner's tasks or operation right.
raise RuntimeError('failure after finish')
"""
        self.implementations['init'] = {'kind': 'agent', 'command': [sys.executable, '-c', script, str(marker), str(allow_exit), str(self.store.filename)], 'cwd': str(Path(__file__).resolve().parents[1])}
        self.create()
        try:
            self.until(lambda r: marker.exists())
            run = self.read()
            old_token = run['executions'][0]['token']
            self.assertEqual([], run['agent_sessions'])
            self.assertTrue(any(not f.done() for f in self.engine.futures))
            owner = acquire(self.store, self.id)
            old = RunTools(self.store, self.id, old_token)
            with self.assertRaises(Conflict):
                old.call('change_settings', {'revision': 1, 'change': {'guidance': 'late write'}})
            allow_exit.write_text('exit')
            for future in list(self.engine.futures):
                future.result(timeout=5)
            self.assertEqual(owner['token'], self.read()['agent_sessions'][0]['token'])
            self.assertEqual({}, self.read()['task_dispositions'])
            self.assertEqual('completed', self.read()['tasks']['init']['status'])
        finally:
            allow_exit.write_text('exit')

    def test_queued_command_records_worker_start_and_has_no_default_agent_timeout(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        from loop_anything.runtime.host_runtime import run_command
        self.engine.pool.shutdown()
        self.engine.pool = ThreadPoolExecutor(max_workers=1)
        release = Event()
        self.engine.pool.submit(release.wait, 5)
        self.implementations['init'] = {'kind': 'agent', 'command': [sys.executable, '-c', 'raise SystemExit(2)']}
        self.create()
        try:
            with patch('loop_anything.runtime.timeline_runtime.run_command', wraps=run_command) as command:
                self.engine.tick(self.id)
                queued = self.read()['executions'][0]
                self.assertIsNone(queued['started_at'])
                release.set()
                for future in list(self.engine.futures):
                    future.result(timeout=5)
                self.assertGreater(self.read()['executions'][0]['started_at'], queued['created_at'])
                self.assertIsNone(command.call_args.args[2])
        finally:
            release.set()

    def test_platform_exit_stops_an_agent_without_a_timeout(self):
        marker = Path(self.tmp.name) / 'pid'
        code = "import os,time;from pathlib import Path;Path(%r).write_text(str(os.getpid()));time.sleep(30)" % str(marker)
        self.implementations['init'] = {'kind': 'agent', 'command': [sys.executable, '-c', code]}
        self.create()
        self.until(lambda r: marker.exists())
        self.engine.close()
        import os
        with self.assertRaises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)
        self.assertEqual([], self.read()['agent_sessions'])
        self.assertEqual(0, self.read()['agent_failures'])

    def test_exiting_without_finish_keeps_committed_results_and_allows_next_agent(self):
        script = """import json,sys
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime.store import Store
r=json.loads(sys.stdin.read().split('Run context:'+chr(10),1)[1]);t=RunTools(Store(sys.argv[-1]),r['run_id'],r['token'])
i=t.call('read_task',{'task_id':'init'})
t.call('complete_task',{'task_id':'init','task_version':i['task_version'],'envelope':{
 'settings':{'objective':'Inspect failure'},'outputs':{'result':'committed'},'tasks':[
 {'id':'reason','node':'reason','inputs':{},'outputs':{'result':{'id':'reason.result'}}}]}})
# A final message neither writes this result nor proves that the Agent finished.
print(json.dumps({'outputs':{'result':'fabricated-final-result'}}))
"""
        self.implementations['init'] = {'kind': 'agent', 'command': [sys.executable, '-c', script, str(self.store.filename)], 'cwd': str(Path(__file__).resolve().parents[1])}
        self.create()
        self.until(lambda r: any(e['node'] == 'reason' and e['status'] == 'decision' for e in r['executions']))
        for _ in range(3):
            self.engine.tick(self.id)
        run = self.read()
        self.assertEqual('committed', run['records']['init.result'][-1]['value'])
        self.assertEqual('completed', run['tasks']['init']['status'])
        self.assertNotIn('reason.result', run['records'])
        self.assertEqual(2, agent_calls(run))
        self.assertTrue(task_list(run, self.engine.timeline_runtime)['has_tasks'])

    def test_scripts_and_events_complete_during_agent_operation(self):
        self.start()
        self.complete('init', settings={'objective': 'Continue'}, tasks=[task_spec('script', 'script'), task_spec('wait', 'wait'),
            task_spec('reason', 'reason')])
        token = self.tools.token
        self.until(lambda r: r['tasks']['script']['status'] == 'completed')
        self.engine.event(self.id, 'signal-1', 'signal', {'result': 'event-result'})
        self.engine.tick(self.id)
        run = self.read()
        self.assertEqual('event-result', run['records']['wait.result'][-1]['value'])
        self.assertEqual('script-result', run['records']['script.result'][-1]['value'])
        self.assertEqual(token, run['agent_sessions'][0]['token'])
        self.assertEqual(['task:reason'], [i['id'] for i in self.tools.call('next_tasks', {})['items']])
        self.complete('reason')
        self.assertEqual(1, agent_calls(self.read()))

    def test_finish_revokes_token_on_all_write_entry_points(self):
        self.start()
        self.complete('init', settings={'objective': 'Wait'}, tasks=[task_spec('wait', 'wait')])
        self.tools.call('finish', {})
        before = self.read()
        for operation in (lambda: self.tools.call('change_settings', {'revision': 1, 'change': {'guidance': 'stale'}}),
                          lambda: self.engine.change_settings(self.id, 1, {'guidance': 'stale'}, self.tools.token),
                          lambda: self.engine.command(self.id, 'pause', operator_token=self.tools.token)):
            with self.assertRaises(Conflict):
                operation()
            self.assertEqual(before, self.read())

    def test_user_request_waits_for_current_owner_and_is_resolved(self):
        from loop_anything.interfaces.agent_tasks import user_request
        self.start()
        with self.assertRaises(Conflict):
            user_request(self.store, self.id, 'Change the experiment')
        request = user_request(self.store, self.id, 'Change the experiment', operator_token=self.tools.token)
        self.assertTrue(any(t['id'] == request['id'] for t in self.tools.call('next_tasks', {})['items']))
        self.tools.call('resolve_request', {'task_id': request['id']})
        self.assertFalse(any(t['id'] == request['id'] for t in self.tools.call('next_tasks', {})['items']))

    def test_changed_inputs_reject_only_that_submission_not_further_reading(self):
        self.start()
        e = self.read()['executions'][0]
        before = self.read()
        with self.assertRaises(Invalid):
            self.engine.submit(self.id, e['id'], e['token'], {'outputs': {'result': 'bypass'}, 'settings': {'objective': 'bypass'}})
        self.assertEqual(before, self.read())
        self.complete('init', settings={'objective': 'Inspect'}, tasks=[task_spec('reason', 'reason')])
        task = self.tools.call('read_task', {'task_id': 'reason'})
        self.tools.call('change_task', {'task_id': 'reason', 'operation': 'update', 'parameters': {'new': True}, 'reason': 'Updated plan'})
        with self.assertRaises(Conflict):
            self.tools.call('complete_task', {'task_id': 'reason', 'task_version': task['task_version'], 'envelope': {'outputs': {'result': 'old'}}})
        self.complete('reason')
        self.assertEqual('completed', self.read()['tasks']['reason']['status'])

    def test_failed_command_cleanup_retains_operation_right(self):
        from unittest.mock import patch
        from loop_anything.runtime.host_runtime import CommandNotStopped
        self.implementations['init']['command'] = [sys.executable, '-c', 'pass']
        self.create()
        with patch('loop_anything.runtime.timeline_runtime.run_command', side_effect=CommandNotStopped('Process tree is still alive')):
            self.engine.tick(self.id)
            for future in list(self.engine.futures):
                future.result(timeout=5)
        self.assertTrue(self.read()['agent_sessions'][0]['recovery_required'])
        with self.assertRaises(Conflict):
            acquire(self.store, self.id)
        self.engine.tick(self.id)
        self.assertEqual(1, agent_calls(self.read()))

    def test_recovery_never_automatically_grants_a_second_agent_access(self):
        from loop_anything.interfaces.agent_tasks import recover_owner
        self.start()
        with self.store.edit(self.id) as run:
            run['executions'][0]['implementation']['command'] = ['old-harness-process']
        self.engine.recover()
        with self.assertRaises(Conflict):
            acquire(self.store, self.id)
        with self.assertRaises(Conflict):
            recover_owner(self.store, self.id, self.tools.token)
        recover_owner(self.store, self.id, self.tools.token, confirmed_stopped=True)
        new = acquire(self.store, self.id)
        with self.assertRaises(Conflict):
            self.tools.call('read_timeline', {})
        self.assertNotEqual(self.tools.token, new['token'])

    def test_agent_cannot_submit_a_script_or_approval_result(self):
        self.bp['nodes']['approve'] = copy.deepcopy(self.bp['nodes']['reason'])
        self.implementations['approve'] = {'kind': 'approval'}
        self.start()
        self.complete('init', settings={'objective': 'Inspect'}, tasks=[task_spec('script', 'script'), task_spec('approve', 'approve')])
        for id in ('script', 'approve'):
            info = self.tools.call('read_task', {'task_id': id})
            with self.assertRaises(Invalid):
                self.tools.call('complete_task', {'task_id': id, 'task_version': info['task_version'], 'envelope': {'outputs': {'result': 'fabricated'}}})
            self.assertNotIn(id + '.result', self.read()['records'])

    def test_paused_ready_tasks_are_waiting_not_immediate_agent_work(self):
        self.create()
        self.engine.command(self.id, 'pause')
        owner = acquire(self.store, self.id)
        tools = RunTools(self.store, self.id, owner['token'])
        self.assertFalse(tools.call('next_tasks', {})['has_tasks'])
        task = tools.call('read_task', {'task_id': 'init'})
        with self.assertRaises(Conflict):
            tools.call('complete_task', {'task_id': 'init', 'task_version': task['task_version'], 'envelope': {'settings': {'objective': 'Test'}, 'outputs': {'result': 'done'}}})
        tools.call('finish', {})
        self.engine.tick(self.id)
        self.assertEqual([], self.read()['executions'])


if __name__ == '__main__':
    unittest.main()
