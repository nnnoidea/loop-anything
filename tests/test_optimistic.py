"""Agents may think concurrently; commits use relevant read versions and exact Task claims."""
import copy
import tempfile
import unittest
from pathlib import Path

from loop_anything.interfaces.agent_tasks import RunTools, acquire, release_in_run
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Conflict
from loop_anything.runtime.store import Store
from test_run_agent import definition, task_spec


class OptimisticTests(unittest.TestCase):
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
        root.call('complete_task', {'task_id': 'init', 'task_version': info['task_version'], 'envelope': {
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
        return agent.call('report_task', {'task_id': ident, 'task_version': view['task_version'],
            'report_id': report, 'event': 'completed', 'envelope': {'outputs': {'result': ident}}})

    def test_global_and_parent_decisions_do_not_block_other_tasks_or_duplicate_task(self):
        global_agent = self.global_agent()
        ancestor = acquire(self.store, self.ident, 'init')
        with self.assertRaises(Conflict):acquire(self.store, self.ident, 'a')
        self.complete(self.a, 'a')
        self.engine.tick(self.ident)  # a has not finished; its successor can start anyway.
        self.assertEqual(self.store.get(self.ident)['tasks']['pending']['status'], 'decision')
        self.assertTrue(any(o['token'] == global_agent.token for o in self.store.get(self.ident)['agent_sessions']))
        with self.assertRaises(Conflict):acquire(self.store, self.ident, 'pending')

    def test_targeted_edit_ignores_sibling_completion_and_logs_but_rejects_changed_target(self):
        first, second = self.global_agent(), self.global_agent()
        first.call('read_task', {'task_id': 'pending'})
        self.complete(self.b, 'b')
        with self.store.edit(self.ident) as run:Store.log(run, 'progress', 'unrelated information')
        self.assertTrue(first.call('change_task', {'task_id': 'pending', 'operation': 'update',
            'parameters': {'value': 1}, 'reason': 'target unchanged'})['updated'])
        second.call('read_task', {'task_id': 'pending'})
        first.call('change_task', {'task_id': 'pending', 'operation': 'update',
            'parameters': {'value': 2}, 'reason': 'first edit'})
        before = self.store.get(self.ident)
        result = second.respond('change_task', {'task_id': 'pending', 'operation': 'update',
            'parameters': {'value': 3}, 'reason': 'stale decision'})
        self.assertFalse(result['ok']);self.assertTrue(result['error']['conflicts'])
        self.assertEqual(self.store.get(self.ident), before)
        second.call('read_task', {'task_id': 'pending'})
        self.assertTrue(second.call('change_task', {'task_id': 'pending', 'operation': 'update',
            'parameters': {'value': 3}, 'reason': 'reconsidered'})['updated'])

    def test_collection_absence_and_settings_changes_reject_stale_planning(self):
        one, two = self.global_agent(), self.global_agent()
        one.call('read_timeline', {})
        two.call('add_task', {'key': 'next-round', 'node_id': 'reason', 'inputs': {}})
        before = self.store.get(self.ident)
        with self.assertRaises(Conflict):one.call('add_task', {'key': 'another-round', 'node_id': 'reason', 'inputs': {}})
        self.assertEqual(self.store.get(self.ident), before)
        one.call('read_timeline', {})
        two.call('change_settings', {'revision': before['settings']['revision'], 'change': {'objective': 'New objective'}})
        with self.assertRaises(Conflict):one.call('add_task', {'key': 'old-objective', 'node_id': 'reason', 'inputs': {}})

    def test_atomic_edits_and_network_retry_receipts(self):
        caller = self.global_agent()
        view = caller.call('read_task', {'task_id': 'pending'})
        before = self.store.get(self.ident)
        with self.assertRaises(Conflict):caller.call('edit_tasks', {'basis': view['basis'], 'changes': [
            {'tool': 'change_task', 'arguments': {'task_id': 'pending', 'operation': 'update', 'parameters': {'v': 1}, 'reason': 'valid'}},
            {'tool': 'change_task', 'arguments': {'task_id': 'a', 'operation': 'update', 'reason': 'already executing'}}]})
        self.assertEqual(self.store.get(self.ident), before)
        task = self.a.call('read_task', {'task_id': 'a'})
        report = {'task_id': 'a', 'task_version': task['task_version'], 'report_id': 'stable',
                  'event': 'completed', 'envelope': {'outputs': {'result': 'a'}}}
        self.assertTrue(self.a.call('report_task', report)['accepted'])
        caller.call('read_task', {'task_id': 'pending'})
        caller.call('change_settings', {'revision': before['settings']['revision'], 'change': {'objective': 'Changed'}})
        self.assertTrue(self.a.call('report_task', report)['duplicate'])

    def test_stateless_caller_supplies_basis_without_taking_another_agents_identity(self):
        read = self.platform.call('read_task', {'run_id': self.ident, 'task_id': 'pending'})
        before = self.store.get(self.ident)
        with self.assertRaises(Conflict):self.platform.call('change_task', {'run_id': self.ident,
            'task_id': 'pending', 'operation': 'cancel', 'reason': 'missing basis'})
        self.assertEqual(self.store.get(self.ident), before)
        self.platform.call('change_task', {'run_id': self.ident, 'basis': read['basis'],
            'task_id': 'pending', 'operation': 'cancel', 'reason': 'user adjustment'})
        self.assertEqual([o['token'] for o in self.store.get(self.ident)['agent_sessions']],
                         [o['token'] for o in before['agent_sessions']])

    def test_concurrent_updates_choose_one_commit_and_keep_the_losers_basis(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        agents = [self.global_agent(), self.global_agent()]
        for agent in agents:agent.call('read_task', {'task_id': 'pending'})
        barrier = Barrier(2)
        def submit(index):
            barrier.wait()
            return agents[index].respond('change_task', {'task_id': 'pending', 'operation': 'update',
                'parameters': {'winner': index}, 'reason': 'Concurrent decision'})
        with ThreadPoolExecutor(max_workers=2) as pool:receipts = list(pool.map(submit, [0, 1]))
        self.assertEqual(1, sum(r['ok'] for r in receipts))
        loser = next(r for r in receipts if not r['ok'])
        self.assertEqual('conflict', loser['error']['code']);self.assertTrue(loser['error']['conflicts'])
        winner = next(i for i, r in enumerate(receipts) if r['ok'])
        self.assertEqual(winner, self.store.get(self.ident)['tasks']['pending']['spec']['parameters']['winner'])

    def test_record_evidence_and_pinned_history_have_different_versions(self):
        latest, pinned = self.global_agent(), self.global_agent()
        latest.call('read_record', {'id': 'init.result'})
        pinned.call('read_record', {'id': 'init.result', 'revision': 1})
        with self.store.edit(self.ident) as run:
            changed = copy.deepcopy(run['records']['init.result'][-1]);changed.update(revision=2, value='new evidence')
            run['records']['init.result'].append(changed)
        with self.assertRaises(Conflict):latest.call('add_task', {'key': 'outdated', 'node_id': 'reason', 'inputs': {}})
        self.assertTrue(pinned.call('add_task', {'key': 'historical', 'node_id': 'reason', 'inputs': {}})['tasks'])

    def test_stateless_identical_append_retry_is_not_a_new_decision(self):
        read = self.platform.call('read_timeline', {'run_id': self.ident})
        args = {'run_id': self.ident, 'basis': read['basis'], 'key': 'stable-append', 'node_id': 'reason', 'inputs': {}}
        first = self.platform.call('add_task', args)
        self.assertEqual(first, self.platform.call('add_task', args))
        self.assertEqual(1, sum(t['id'] == first['tasks'][0]['id'] for t in self.store.get(self.ident)['tasks'].values()))

    def test_read_bookkeeping_preserves_business_revision_and_expired_execution_cannot_write(self):
        before = self.store.get(self.ident)
        task = self.a.call('read_task', {'task_id': 'a'})
        self.assertEqual(before['revision'], self.store.get(self.ident)['revision'])
        with self.store.edit(self.ident) as run:
            run['tasks']['a']['execution_id'] = None  # A recovered/replaced attempt invalidates this identity.
        result = self.a.respond('report_task', {'task_id': 'a', 'task_version': task['task_version'],
            'report_id': 'old-execution', 'event': 'completed', 'envelope': {'outputs': {'result': 'old'}}})
        self.assertFalse(result['ok']);self.assertIn('superseded', result['error']['message'])
        self.assertNotIn('a.result', self.store.get(self.ident)['records'])

    def test_settings_content_and_latest_record_listing_are_decision_inputs(self):
        caller = self.global_agent()
        caller.call('read_timeline', {})
        with self.store.edit(self.ident) as run:
            run['settings']['objective'] = 'Changed without a revision bump, as during initialization'
        result = caller.respond('add_task', {'key': 'stale-initialization', 'node_id': 'reason', 'inputs': {}})
        self.assertFalse(result['ok']);self.assertIn('settings', [c['field'] for c in result['error']['conflicts']])
        caller.call('read_timeline', {})
        with self.store.edit(self.ident) as run:
            changed = copy.deepcopy(run['records']['init.result'][-1]);changed.update(revision=2, value='new')
            run['records']['init.result'].append(changed)
        result = caller.respond('add_task', {'key': 'stale-result-list', 'node_id': 'reason', 'inputs': {}})
        self.assertFalse(result['ok']);self.assertIn('records.init.result', [c['field'] for c in result['error']['conflicts']])

    def test_fresh_collection_replaces_old_task_snapshot_but_keeps_other_evidence(self):
        caller = self.global_agent()
        caller.call('read_task', {'task_id': 'b'})
        self.complete(self.b, 'b')
        caller.call('next_tasks', {})
        self.assertTrue(caller.call('add_task', {'key': 'after-fresh-list', 'node_id': 'reason', 'inputs': {}})['tasks'])
        caller.call('read_record', {'id': 'init.result'})
        with self.store.edit(self.ident) as run:
            changed = copy.deepcopy(run['records']['init.result'][-1]);changed.update(revision=2, value='changed')
            run['records']['init.result'].append(changed)
        caller.call('next_tasks', {})  # The work list does not reread record values or their directory.
        with self.assertRaises(Conflict):caller.call('add_task', {'key': 'still-stale-evidence', 'node_id': 'reason', 'inputs': {}})

    def test_batch_requires_affected_task_reads_for_preview_and_commit(self):
        caller = self.global_agent()
        edits = [{'tool': 'change_task', 'arguments': {'task_id': 'pending', 'operation': 'update',
                  'parameters': {'v': 1}, 'reason': 'Batch correction'}}]
        before = self.store.get(self.ident)
        for preview in (True, False):
            with self.assertRaises(Conflict):caller.call('edit_tasks', {'changes': edits, 'preview': preview})
            self.assertEqual(before, self.store.get(self.ident))
        caller.call('read_task', {'task_id': 'pending'})
        caller.call('edit_tasks', {'changes': edits})
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
