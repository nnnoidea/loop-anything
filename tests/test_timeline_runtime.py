"""Application-independent contracts: real Store/Engine, only handler replies supplied."""
import copy
import tempfile
import time
import unittest
from pathlib import Path
from loop_anything.runtime import engine
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime.store import Store
from loop_anything.runtime.model import Invalid, Conflict


def node(inputs=None, outputs=None, **extra):
    return dict(instructions='Read declared inputs; commit every declared record.',
                inputs=inputs or {}, outputs={k: {'record_type': v} for k, v in (outputs or {}).items()}, **extra)


def task_spec(id, node_id, inputs=None, outputs=None, **extra):
    return dict(id=id, node=node_id, inputs=inputs or {},
                outputs={k: {'id': v} for k, v in (outputs or {}).items()}, **extra)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
        self.engine = engine.Engine(self.store)
        self.bp = {'schema_version': 2, 'id': 'neutral', 'version': '1', 'entry': 'init',
                   'handbook': {'instructions': 'Initialize objective, plan tasks, commit typed records.'},
                   'records': {'text': {'type': 'string'}, 'flag': {'type': 'boolean'}},
                   'nodes': {'init': node(outputs={'a': 'text', 'b': 'text'}, initialize_timeline=True,
                                          plan_nodes=['join', 'produce', 'wait']),
                             'join': node({'a': {'type': 'string'}, 'b': {'type': 'string'}}, {'ok': 'flag'}),
                             'produce': node({'source': {'type': 'string'}}, {'text': 'text'}),
                             'wait': node(outputs={'text': 'text'})},
                   'seed': task_spec('init', 'init', outputs={'a': 'a', 'b': 'b'}), 'rules': []}
        self.implementations = {n: {'kind': 'agent'} for n in self.bp['nodes']}
        self.implementations['wait'] = {'kind': 'event', 'event': 'signal'}

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def start(self):
        key = self.store.publish(self.bp, self.implementations)['key']
        self.id = self.store.create(key, 'Neutral')['id']
        self.engine.tick(self.id)
        return self.read()['executions'][0]

    def read(self):
        return self.store.get(self.id)

    def task(self, task_id):
        run = self.read()
        tools = RunTools(self.store, self.id, run['agent_sessions'][0]['token'])
        info = tools.call('read_task', {'task_id': task_id})
        return dict(task_id=task_id, id=info['task'].get('execution_id'), token=tools.token,
                    inputs=info['inputs'], sources=info['sources'], settings_revision=run['settings']['revision'])

    def submit(self, e, envelope):
        if 'settings' in envelope:
            envelope['settings'].setdefault('completion_rule', {'op': 'and', 'args': [{'op': 'ge', 'args': [{'path': ['completed', 'join']}, 1]}, {'op': 'eq', 'args': [{'path': 'active_tasks'}, 0]}]})
        tools = RunTools(self.store, self.id, e['token'])
        info = tools.call('read_task', {'task_id': e['task_id']})
        tools.call('complete_task', {'task_id': e['task_id'], 'task_version': info['task_version'], 'envelope': envelope})
        if not tools.call('next_tasks', {})['has_tasks']:
            tools.call('finish', {})
        return self.read()

    def initialize(self, plans=None):
        e = self.start()
        self.submit(e, {'settings': {'objective': 'Complete bounded tasks'},
                        'outputs': {'a': 'A', 'b': 'B'}, 'tasks': plans or []})
        self.engine.tick(self.id)

    def join(self, **kw):
        return task_spec('join', 'join', {'a': {'record': 'a'}, 'b': {'record': 'b'}}, {'ok': 'done'}, **kw)

    def test_incomplete_result_is_rejected_and_complete_commit_is_atomic(self):
        e = self.start()
        with self.assertRaises(Invalid):
            self.submit(e, {'settings': {'objective': 'x'}, 'outputs': {'a': 'A'}})
        self.engine.tick(self.id)
        self.assertEqual({}, self.read()['records'])
        self.assertEqual(1, len(self.read()['tasks']))
        with self.assertRaises(Invalid):
            self.submit(e, {'settings': {'objective': 'x'}, 'outputs': {'b': 3}})
        self.assertFalse(self.read()['initialized'])
        self.submit(e, {'settings': {'objective': 'x'}, 'outputs': {'a': 'A', 'b': 'B'}, 'tasks': [self.join()]})
        self.engine.tick(self.id)
        join = self.task('join')
        self.assertEqual({'a': 'A', 'b': 'B'}, join['inputs'])
        self.assertEqual(e['id'], join['sources']['a']['execution'])
        self.submit(join, {'outputs': {'ok': True}})
        self.engine.tick(self.id)
        self.assertEqual('completed', self.read()['status'])
        with self.assertRaises(Conflict):
            self.submit(join, {'outputs': {'ok': True}})

    def test_cycle_write_rolls_back_and_missing_record_remains_visible(self):
        # Invalid batches never persist partial results or initialization changes.
        e = self.start()
        before = self.read()
        with self.assertRaises(Invalid):
            self.submit(e, {'settings': {'objective': 'Cycle'}, 'outputs': {'a': 'A', 'b': 'B'},
                'tasks': [task_spec('x', 'produce', {'source': {'record': 'y'}}, {'text': 'x'}),
                          task_spec('y', 'produce', {'source': {'record': 'x'}}, {'text': 'y'})]})
        self.assertEqual(before, self.read())
        self.initialize([task_spec('z', 'produce', {'source': {'record': 'absent'}}, {'text': 'z'})])
        self.assertIn('dependency_gap', {d['kind'] for d in self.read()['diagnostics']})

    def test_missing_version_distinguishes_gap_from_pending_producer(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                consumer = task_spec('consumer', 'produce', {'source': {'record': 'a', 'revision': 2}}, {'text': 'read-v2'})
                producer = task_spec('writer', 'wait', outputs={'text': 'a'})
                producer['outputs']['text']['expected_revision'] = 1
                self.initialize([consumer] + ([producer] if pending else []))
                gaps = [d for d in self.read()['diagnostics'] if d['kind'] == 'dependency_gap']
                self.assertEqual(not pending, bool(gaps))
                if gaps:
                    self.assertEqual(2, gaps[0]['revision'])

    def test_hook_is_gate_not_race_and_notification_is_deduplicated(self):
        self.initialize([self.join()])
        # Already dispatched tasks cannot be retroactively paused. Use a fresh fixture run.
        self.engine.command(self.id, 'terminate', operator_token=(self.read().get('agent_sessions') or [{}])[0].get('token'))
        self.id = self.store.create(self.read()['loop_key'], 'Gated')['id']
        hooks = [{'id': 'gate', 'action': 'pause', 'phase': 'before', 'frequency': 'once', 'target': {'node': 'join'}},
                 {'id': 'notice', 'action': 'notify', 'route': 'workspace', 'phase': 'before', 'frequency': 'always', 'target': {'node': 'join'}}]
        self.engine.change_settings(self.id, 1, {'hooks': hooks})
        self.engine.tick(self.id)
        self.submit(self.read()['executions'][0], {'settings': {'objective': 'x'}, 'outputs': {'a': 'A', 'b': 'B'}, 'tasks': [self.join()]})
        for _ in range(3):
            self.engine.tick(self.id)
        self.assertEqual('held', self.read()['tasks']['join']['status'])
        self.assertEqual(1, len(self.read()['executions']))
        self.engine.pool.submit(lambda: None).result()
        for f in self.engine.futures:
            f.result()
        self.assertEqual(1, len(self.read()['notifications']))
        self.assertEqual('delivered', self.read()['notifications'][0]['status'])
        self.engine.command(self.id, 'release_gate', hook_firing='gate:join')
        self.engine.tick(self.id)
        self.assertEqual('decision', self.read()['tasks']['join']['status'])

    def test_owner_can_read_and_use_updated_settings_without_becoming_stale(self):
        from loop_anything.interfaces.agent_tasks import RunTools
        self.initialize([self.join(policy='current')])
        e = self.task('join')
        with self.assertRaises(Conflict):
            self.engine.change_settings(self.id, 1, {'guidance': 'New instructions'})
        tools = RunTools(self.store, self.id, e['token'])
        tools.call('change_settings', {'revision': 1, 'change': {'guidance': 'New instructions'}})
        self.assertEqual(2, tools.call('read_timeline', {})['settings']['revision'])
        self.submit(e, {'outputs': {'ok': True}})
        self.assertTrue(self.read()['records']['done'][-1]['value'])

    def test_event_wait_is_not_gap_and_correlates_identity(self):
        self.initialize([task_spec('wait', 'wait', outputs={'text': 'signal'}, parameters={'event_key': 'wanted'}),
                         task_spec('consume', 'produce', {'source': {'record': 'signal'}}, {'text': 'copy'})])
        self.assertEqual([], self.read()['diagnostics'])
        self.engine.event(self.id, 'other', 'signal', {'text': 'wrong'}, key='other')
        self.engine.tick(self.id)
        self.assertNotIn('signal', self.read()['records'])
        self.engine.event(self.id, 'right', 'signal', {'text': 'right'}, key='wanted')
        self.engine.tick(self.id)
        self.engine.tick(self.id)
        self.assertEqual('right', self.read()['executions'][-1]['inputs']['source'])
        self.engine.event(self.id, 'right', 'signal', {'text': 'right'}, key='wanted')
        with self.assertRaises(Conflict):
            self.engine.event(self.id, 'right', 'signal', {'text': 'different'}, key='wanted')

    def test_restart_and_terminated_token_are_persistent(self):
        self.initialize([self.join()])
        e = self.read()['executions'][0]
        self.engine.close()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
        self.engine = engine.Engine(self.store)
        self.engine.recover()
        self.assertEqual(e['token'], self.read()['executions'][-1]['token'])
        self.engine.command(self.id, 'terminate', operator_token=e['token'])
        with self.assertRaises(Conflict):
            self.submit(e, {'outputs': {'ok': True}})

    def test_unauthorized_work_and_double_writer_roll_back(self):
        e = self.start()
        envelope = {'settings': {'objective': 'x'}, 'outputs': {'a': 'A', 'b': 'B'},
                    'tasks': [task_spec('bad', 'produce', {'source': {'literal': 'x'}}, {'text': 'a'})]}
        with self.assertRaises(Conflict):
            self.submit(e, envelope)
        self.assertEqual({}, self.read()['records'])
        self.assertFalse(self.read()['initialized'])
        envelope['tasks'] = [task_spec('bad', 'init', outputs={'a': 'x', 'b': 'y'})]
        with self.assertRaises(Invalid):
            self.submit(e, envelope)

    def test_hook_only_change_does_not_fire_semantic_replanning(self):
        self.initialize([task_spec('wait', 'wait', outputs={'text': 'signal'})])
        self.engine.change_settings(self.id, 1, {'max_parallel': 2})
        self.engine.tick(self.id)
        self.assertNotIn('join', self.read()['tasks'])
        self.engine.change_settings(self.id, 2, {'guidance': 'new meaning'})
        self.engine.tick(self.id)
        self.assertNotIn('join', self.read()['tasks'])

    def test_diagnostic_enters_default_attention_once(self):
        self.initialize([task_spec('consume', 'produce', {'source': {'record': 'missing'}}, {'text': 'copy'})])
        for _ in range(5):
            self.engine.tick(self.id)
        self.assertEqual(2, len(self.read()['tasks']))
        self.assertEqual(1, len(self.read()['executions']))
        self.assertTrue(RunTools(self.store, self.id, self.read()['agent_sessions'][0]['token']).call('next_tasks', {})['has_tasks'])
        self.assertEqual('dependency_gap', self.read()['diagnostics'][0]['kind'])

    def test_new_record_revision_preserves_pinned_old_source(self):
        planned = task_spec('update', 'produce', {'source': {'record': 'a'}}, {'text': 'a'})
        planned['outputs']['text']['expected_revision'] = 1
        pinned = self.join()
        pinned['inputs']['a']['revision'] = 1
        self.initialize([planned, pinned])
        update = self.task('update')
        self.submit(update, {'outputs': {'text': 'A2'}})
        self.engine.tick(self.id)
        versions = self.read()['records']['a']
        self.assertEqual(['A', 'A2'], [v['value'] for v in versions])
        join = self.task('join')
        self.assertEqual('A', join['inputs']['a'])
        self.assertEqual(1, join['sources']['a']['revision'])

    def test_notification_failure_does_not_complete_delivery_or_block_work(self):
        e = self.start()
        hooks = [{'id': 'failed', 'target': {'node': 'join'}, 'action': 'notify', 'phase': 'before', 'frequency': 'once', 'route': 'external'}]
        self.engine.change_settings(self.id, 1, {'hooks': hooks}, operator_token=e['token'])
        self.submit(e, {'settings': {'objective': 'x'}, 'outputs': {'a': 'A', 'b': 'B'}, 'tasks': [self.join()]})
        self.engine.tick(self.id)
        for future in self.engine.futures:
            future.result()
        self.assertEqual('fault', self.read()['notifications'][0]['status'])
        self.assertEqual('ready', self.read()['tasks']['join']['status'])
        self.engine.command(self.id, 'retry_notification', notification_id='failed:join', operator_token=self.read()['agent_sessions'][0]['token'])
        self.engine.tick(self.id)
        for future in self.engine.futures:
            future.result()
        self.assertEqual(2, self.read()['notifications'][0]['attempt'])

    def test_intent_change_does_not_recreate_initializer(self):
        self.bp['seed']['policy'] = 'current'
        old = self.start()
        self.engine.change_settings(self.id, 1, {'guidance': 'New initial instructions'}, operator_token=old['token'])
        self.engine.tick(self.id)
        current = self.read()['executions'][-1]
        self.assertEqual(old['id'], current['id'])
        self.assertEqual('decision', current['status'])
        self.assertEqual(1, len(self.read()['tasks']))
        self.assertFalse(self.read()['initialized'])


if __name__ == '__main__':
    unittest.main()
