from tests.runtime_fixture import update_work
"""Execution ownership, atomic edits and idempotent retries without read bookkeeping."""
import copy
import tempfile
import unittest
from pathlib import Path

from loop_anything.interfaces.agent_tasks import RunTools, acquire, release_in_run
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime.store import Store
from test_run_agent import definition, task_spec


class ExecutionGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'run.db');self.engine = Engine(self.store)
        self.addCleanup(self.engine.close)
        bp, impl = definition();bp['global_agent_node'] = 'finish'
        key = self.store.publish(bp, impl)['key']
        run = self.store.create(key, 'Concurrent decisions', acquire=True);self.ident = run['id']
        self.platform = PlatformTools(self.store)
        root = RunTools(self.store, self.ident, run['agent_sessions'][0]['token'])
        info = root.call('read_task', {'task_id': 'init'})
        root.call('report_task', {'event':'completed','report_id':'complete','task_id': 'init', 'envelope': {
            'settings': {'objective': 'Concurrent decisions'}, 'outputs': {'result': 'start'},
            'tasks': [task_spec('a', 'reason'), task_spec('b', 'reason'), task_spec('pending', 'reason', after=['a'])]}})
        root.call('finish', {});self.engine.tick(self.ident)
        self.a = self.agent('a');self.b = self.agent('b')

    def agent(self, ident):
        return RunTools(self.store, self.ident, next(o['token'] for o in self.store.get(self.ident)['agent_sessions'] if o.get('task_id') == ident))

    def global_agent(self):
        return RunTools(self.store, self.ident, acquire(self.store, self.ident)['token'])

    def complete(self, agent, ident, report='done'):
        view = agent.call('read_task', {'task_id': ident})
        return agent.call('report_task', {'task_id': ident, 'report_id': report, 'event': 'completed', 'envelope': {'outputs': {'result': ident}}})

    def test_global_and_parent_decisions_do_not_block_other_tasks_or_duplicate_task(self):
        global_agent = self.global_agent()
        ancestor = acquire(self.store, self.ident, 'init')
        with self.assertRaises(Conflict):acquire(self.store, self.ident, 'a')
        self.complete(self.a, 'a')
        self.engine.tick(self.ident)  # a has not finished; its successor can start anyway.
        self.assertEqual(self.store.get(self.ident)['tasks']['pending']['status'], 'decision')
        self.assertTrue(any(o['token'] == global_agent.token for o in self.store.get(self.ident)['agent_sessions']))
        with self.assertRaises(Conflict):acquire(self.store, self.ident, 'pending')



    def test_atomic_edits_and_network_retry_receipts(self):
        caller = self.global_agent()
        view = caller.call('read_task', {'task_id': 'pending'})
        before = self.store.get(self.ident)
        with self.assertRaises(Conflict):caller.call('edit_tasks', {'changes': [
            {'tool': 'change_task', 'arguments': {'task_id': 'pending', 'operation': 'update', 'parameters': {'v': 1}, 'reason': 'valid'}},
            {'tool': 'change_task', 'arguments': {'task_id': 'a', 'operation': 'update', 'reason': 'already executing'}}]})
        self.assertEqual(self.store.get(self.ident), before)
        task = self.a.call('read_task', {'task_id': 'a'})
        report = {'task_id': 'a', 'report_id': 'stable',
                  'event': 'completed', 'envelope': {'outputs': {'result': 'a'}}}
        self.assertTrue(self.a.call('report_task', report)['accepted'])
        caller.call('read_task', {'task_id': 'pending'})
        update_work(self.store,self.ident,{'objective':'Changed'})
        self.assertTrue(self.a.call('report_task', report)['duplicate'])

    def test_client_reads_do_not_grant_runtime_write_identity(self):
        read = self.platform.call('read_task', {'run_id': self.ident, 'task_id': 'pending'})
        before = self.store.get(self.ident)
        with self.assertRaises(Invalid):self.platform.call('change_task', {'run_id': self.ident,
            'task_id': 'pending', 'operation': 'cancel', 'reason': 'missing execution identity'})
        self.assertEqual(self.store.get(self.ident), before)
        with self.assertRaises(Invalid):
            self.platform.call('change_task', {'run_id': self.ident, 'task_id': 'pending', 'operation': 'cancel', 'reason': 'user adjustment'})
        self.assertEqual(self.store.get(self.ident), before)
        self.assertEqual([o['token'] for o in self.store.get(self.ident)['agent_sessions']],
                         [o['token'] for o in before['agent_sessions']])



    def test_identical_append_retry_is_not_a_new_task(self):
        read = self.platform.call('read_timeline', {'run_id': self.ident})
        caller = self.global_agent()
        args = {'run_id': self.ident, 'token': caller.token, 'key': 'stable-append', 'node_id': 'reason', 'inputs': {}}
        first = self.platform.call('add_task', args)
        self.assertEqual(first, self.platform.call('add_task', args))
        self.assertEqual(1, sum(t['id'] == first['tasks'][0]['id'] for t in self.store.get(self.ident)['tasks'].values()))

    def test_read_bookkeeping_preserves_business_revision_and_expired_execution_cannot_write(self):
        before = self.store.get(self.ident)
        task = self.a.call('read_task', {'task_id': 'a'})
        self.assertEqual(before['revision'], self.store.get(self.ident)['revision'])
        with self.store.edit(self.ident) as run:
            run['tasks']['a']['execution_id'] = None  # A recovered/replaced attempt invalidates this identity.
        result = self.a.respond('report_task', {'task_id': 'a', 'report_id': 'old-execution', 'event': 'completed', 'envelope': {'outputs': {'result': 'old'}}})
        self.assertFalse(result['ok']);self.assertIn('superseded', result['error']['message'])
        self.assertNotIn('a.result', self.store.get(self.ident)['records'])



    def test_reads_are_pure_and_edits_need_no_prior_read(self):
        caller = self.global_agent()
        before = self.store.get(self.ident)
        for name,args in [('read_task',{'task_id':'pending'}),('read_run',{}),('read_timeline',{}),('next_tasks',{}),('read_record',{'id':'init.result'})]:
            view=caller.call(name,args)
            self.assertNotIn('basis',view)
            self.assertNotIn('task_version',view)
        self.assertEqual(before,self.store.get(self.ident))
        self.assertTrue(all('observed' not in o for o in before['agent_sessions']))
        edits = [{'tool': 'change_task', 'arguments': {'task_id': 'pending', 'operation': 'update',
                  'parameters': {'v': 1}, 'reason': 'Batch correction'}}]
        caller.call('edit_tasks', {'changes': edits, 'preview': True})
        self.assertEqual(before,self.store.get(self.ident))
        caller.call('edit_tasks', {'changes': edits})
        caller.call('add_task',{'key':'after-own-write','node_id':'reason','inputs':{}})
        self.assertEqual({'v': 1}, self.store.get(self.ident)['tasks']['pending']['spec']['parameters'])

    def test_remote_finish_does_not_release_the_task_before_process_completion(self):
        with self.store.edit(self.ident) as run:
            attempt = next(e for e in run['executions'] if e['task_id'] == 'a')
            attempt.update(communication_id='remote-worker', communication_state='unknown', status='fault')
            run['tasks']['a']['status'] = 'fault'
            release_in_run(run, self.a.token)
        caller = self.global_agent();caller.call('read_task', {'task_id': 'a'})
        with self.assertRaises(Conflict):acquire(self.store, self.ident, 'a')
        with self.assertRaises(Conflict):caller.call('change_task', {'task_id': 'a', 'operation': 'retry', 'reason': 'Too early'})
        self.assertTrue(caller.call('add_task', {'key': 'unrelated', 'node_id': 'reason', 'inputs': {}})['tasks'])
        with self.store.edit(self.ident) as run:
            next(e for e in run['executions'] if e['task_id'] == 'a')['communication_state'] = 'completed'
        caller.call('read_task', {'task_id': 'a'})
        caller.call('change_task', {'task_id': 'a', 'operation': 'retry', 'reason': 'Remote process exited'})

    def test_interrupted_historical_process_claim_survives_restart_until_confirmed(self):
        from loop_anything.runtime.native_sessions import confirm_stopped
        with self.store.edit(self.ident) as run:
            attempt = next(e for e in run['executions'] if e['task_id'] == 'a')
            ident = attempt['id'];attempt.update(worker_active='old-terminal', token=None)
            release_in_run(run, self.a.token)
            # A historical attempt must still protect its Task after the current pointer moves.
            run['tasks']['a']['execution_id'] = None
        self.engine.terminals.create(self.ident, ident, 'old-terminal')
        self.engine.recover()
        with self.assertRaises(Conflict):acquire(self.store, self.ident, 'a')
        self.assertTrue(acquire(self.store, self.ident)['token'])  # No global Timeline exclusion.
        confirm_stopped(self.engine, self.ident, ident, 'old-terminal')
        self.assertTrue(acquire(self.store, self.ident, 'a')['token'])

    def test_adopted_external_caller_cannot_be_bypassed_with_manual_retry(self):
        import os
        with self.store.edit(self.ident) as run:
            attempt = next(e for e in run['executions'] if e['task_id'] == 'a')
            attempt.update(collaboration_caller_pid=os.getpid(), status='fault', token=None)
            run['tasks']['a']['status'] = 'fault'
            release_in_run(run, self.a.token)
        caller = self.global_agent();caller.call('read_task', {'task_id': 'a'})
        with self.assertRaises(Conflict):acquire(self.store, self.ident, 'a')
        with self.assertRaises(Conflict):caller.call('change_task', {'task_id': 'a', 'operation': 'retry', 'reason': 'Caller still running'})
        with self.store.edit(self.ident) as run:
            next(e for e in run['executions'] if e['task_id'] == 'a').pop('collaboration_caller_pid')
        caller.call('read_task', {'task_id': 'a'})
        caller.call('change_task', {'task_id': 'a', 'operation': 'retry', 'reason': 'Caller exited'})
