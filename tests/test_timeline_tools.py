"""Typed Timeline mutations, atomic partition storage, hard checks."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from loop_anything.interfaces.agent_tasks import RunTools, agent_calls
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Invalid, Conflict, contract
from loop_anything.runtime.store import Store


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'run.db')
        self.engine = Engine(self.store)
        text = {'type': 'string'}
        self.bp = {'schema_version': 2, 'id': 'tools', 'version': '1', 'entry': 'init',
            'handbook': {'instructions': 'Write intent and results with tools. Handle tasks then finish.'},
            'records': {'text': text}, 'nodes': {
                'init': {'instructions': 'Initialize', 'inputs': {}, 'outputs': {'result': {'record_type': 'text'}},
                         'initialize_timeline': True, 'plan_nodes': ['finish']},
                'finish': {'instructions': 'Finish', 'inputs': {'value': text}, 'outputs': {'result': {'record_type': 'text'}}}},
            'seed': {'id': 'initial', 'node': 'init', 'inputs': {}, 'outputs': {'result': {'id': 'initial-result'}}}, 'rules': []}
        self.implementations = {k: {'kind': 'agent'} for k in self.bp['nodes']}

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def start(self):
        key = self.store.publish(self.bp, self.implementations)['key']
        self.run_id = self.store.create(key, 'Typed')['id']
        self.engine.tick(self.run_id)
        self.e = self.store.get(self.run_id)['executions'][0]
        self.tools = RunTools(self.store, self.run_id, self.e['token'])

    def complete(self, task_id='initial', **envelope):
        info = self.tools.call('read_task', {'task_id': task_id})
        return self.tools.respond('complete_task', {'task_id': task_id, 'task_version': info['task_version'], 'envelope': envelope})

    def test_invalid_result_rolls_back_all_writes_then_valid_result_commits_immediately(self):
        self.start()
        before = self.store.get(self.run_id)
        self.assertFalse(self.complete(settings={'objective': 'Task'}, outputs={'result': 3})['ok'])
        self.assertEqual(before, self.store.get(self.run_id))
        self.assertTrue(self.complete(settings={'objective': 'Task'}, outputs={'result': 'source'})['ok'])
        run = self.store.get(self.run_id)
        self.assertEqual('source', run['records']['initial-result'][-1]['value'])
        self.assertTrue(run['initialized'])
        self.assertEqual(self.e['token'], run['agent_sessions'][0]['token'])
        self.assertFalse(self.complete(outputs={'result': 'duplicate'})['ok'])
        self.assertEqual(run, self.store.get(self.run_id))

    def test_assertions_apply_to_actual_submission_and_cannot_be_bypassed(self):
        self.bp['nodes']['init']['assertions'] = [{'message': 'Must use evidence', 'test': {'op': 'eq', 'args': [{'path': 'outputs.result'}, 'evidence']}}]
        self.start()
        before = self.store.get(self.run_id)
        self.assertFalse(self.complete(settings={'objective': 'Task'}, outputs={'result': 'guess'})['ok'])
        self.assertEqual(before, self.store.get(self.run_id))
        self.assertTrue(self.complete(settings={'objective': 'Task'}, outputs={'result': 'evidence'})['ok'])

    def test_initialization_links_batch_outputs_before_submitting_result(self):
        from loop_anything.examples.loops import obj, array, node, value, ref, TEXT, NUMBER
        candidate = obj(id=TEXT, x=NUMBER, dropout=NUMBER)
        plan = obj(experiments=array(candidate), metric_ids=array(TEXT))
        self.bp['records'].update(plan=plan, metric=TEXT)
        self.bp['nodes']['init']['outputs'] = {'plan': {'record_type': 'plan'}}
        self.bp['nodes']['init']['plan_nodes'] = ['evaluate', 'reason']
        self.bp['seed']['outputs'] = {'plan': {'id': 'plan.initial'}}
        self.bp['nodes']['evaluate'] = node('Evaluate', {'experiment': candidate}, {'metric': 'metric'}, 'Produce a metric.')
        self.bp['nodes']['reason'] = node('Review', {'plan': plan, 'metrics': array(TEXT)}, {'plan': 'plan'}, 'Read this batch results.')
        self.bp['plans'] = {'round': {'parameters': obj(experiments=array(candidate), plan_record=TEXT), 'steps': {
            'evaluate': {'node': 'evaluate', 'each': 'experiments', 'inputs': {'experiment': {'literal': value('item')}}},
            'reason': {'node': 'reason', 'inputs': {'plan': ref(value('values.plan_record')),
                'metrics': {'from': 'evaluate', 'port': 'metric', 'collect': True}}}}}}
        self.implementations = {k: {'kind': 'agent'} for k in self.bp['nodes']}
        self.start()
        task = self.tools.call('read_task', {'task_id': self.e['task_id']})
        candidates = [{'id': 'a', 'x': .3, 'dropout': .1}, {'id': 'b', 'x': .6, 'dropout': .1}]
        batch = self.tools.call('build_plan', {'name': 'round', 'key': 'one', 'values': {
            'experiments': candidates, 'plan_record': task['task']['spec']['outputs']['plan']['id']}})['tasks']
        self.assertEqual(4, len(self.store.get(self.run_id)['tasks']))
        metric_ids = [w['outputs']['metric']['id'] for w in batch if w['node'] == 'evaluate']
        self.tools.call('complete_task', {'task_id': self.e['task_id'], 'task_version': task['task_version'], 'envelope': {
            'settings': {'objective': 'Compare candidates'},
            'outputs': {'plan': {'experiments': candidates, 'metric_ids': metric_ids}}}})
        run = self.store.get(self.run_id)
        self.assertEqual(4, len(run['tasks']))
        self.assertEqual(metric_ids, run['records'][task['task']['spec']['outputs']['plan']['id']][-1]['value']['metric_ids'])
        self.assertEqual(2, len(self.tools.call('next_tasks', {})['items']))


    def test_noop_tick_does_not_rewrite_settings(self):
        self.start()
        before = self.store.get(self.run_id)
        self.engine.tick(self.run_id)
        self.assertEqual(before, self.store.get(self.run_id))


    def test_bounds_are_engine_contracts_not_provider_only(self):
        for value, schema in [(True, {'type': 'integer'}), (float('nan'), {'type': 'number'}),
                (3, {'type': 'number', 'maximum': 2}), ([1, 2, 3], {'type': 'array', 'maxItems': 2}),
                ({'extra': 1}, {'type': 'object', 'additionalProperties': False})]:
            with self.assertRaises(Invalid):
                contract(value, schema)




    def test_partitioned_storage_roundtrip_rollback_and_legacy_migration(self):
        self.start()
        self.assertTrue(self.complete(settings={'objective': 'Store'}, outputs={'result': 'source'})['ok'])
        run = self.store.get(self.run_id)
        with self.store.connection() as db:
            header = json.loads(db.execute('SELECT document FROM runs').fetchone()[0])
            self.assertEqual(2, header['_storage'])
            for key in ('tasks', 'executions', 'records', 'history', 'loop_definition'):
                self.assertNotIn(key, header)
            self.assertGreater(db.execute("SELECT count(*) FROM timeline_parts WHERE section='tasks'").fetchone()[0], 0)
        with self.assertRaises(RuntimeError):
            with self.store.edit(self.run_id) as edited:
                edited['records']['bad'] = []
                edited['settings']['objective'] = 'partial'
                raise RuntimeError('rollback')
        self.assertEqual(run, self.store.get(self.run_id))
        # Simulate an old unpartitioned row. A normal edit migrates it losslessly.
        with self.store.connection() as db:
            db.execute('UPDATE runs SET document=? WHERE id=?', (json.dumps(run), self.run_id))
            db.commit()
        with self.store.edit(self.run_id) as edited:
            edited['title'] = 'Migrated'
        after = self.store.get(self.run_id)
        self.assertEqual(run['executions'], after['executions'])
        self.assertEqual(run['history'], after['history'])
        self.assertEqual([self.run_id], [r['id'] for r in self.store.scheduling_list()])


    def test_visual_and_agent_task_edits_share_conflicts_cycles_and_history(self):
        from loop_anything.interfaces.agent_tasks import edit_tasks
        self.start()
        self.assertTrue(self.complete(settings={'objective': 'Review'}, outputs={'result': 'original'})['ok'])
        a = self.tools.call('add_task', {'key': 'a', 'node_id': 'finish', 'inputs': {'value': {'record': 'initial-result'}}})['tasks'][0]
        b = self.tools.call('add_task', {'key': 'b', 'node_id': 'finish', 'inputs': {'value': {'record': a['outputs']['result']['id']}}})['tasks'][0]
        before = self.store.get(self.run_id)
        change = {'tool': 'change_task', 'arguments': {'task_id': a['id'], 'operation': 'update', 'after': [b['id']], 'reason': 'cycle'}}
        with self.assertRaises(Conflict):
            edit_tasks(self.store, self.run_id, [change], before['revision'])
        with self.assertRaises(Conflict):
            edit_tasks(self.store, self.run_id, [change], before['revision'] - 1, self.e['token'])
        with self.assertRaises(Invalid):
            edit_tasks(self.store, self.run_id, [change], before['revision'], self.e['token'])
        self.assertEqual(before, self.store.get(self.run_id))
        change['arguments'].update(after=[], parameters={'threshold': 0.5})
        preview = edit_tasks(self.store, self.run_id, [change], before['revision'], self.e['token'], preview=True)
        self.assertEqual(before, self.store.get(self.run_id))
        self.assertEqual(0.5, preview['changes'][0]['after']['spec']['parameters']['threshold'])
        updated = edit_tasks(self.store, self.run_id, [change], before['revision'], self.e['token'])
        self.assertEqual(before['executions'], updated['executions'])
        self.assertEqual(before['records'], updated['records'])
        self.assertEqual(0.5, updated['history'][-1]['detail']['after']['parameters']['threshold'])
        self.assertTrue(self.complete(task_id=a['id'], outputs={'result': 'A'})['ok'])
        finished = self.store.get(self.run_id)
        with self.assertRaises(Conflict):
            edit_tasks(self.store, self.run_id, [change], finished['revision'], self.e['token'])
        self.assertEqual(finished, self.store.get(self.run_id))
        with self.store.edit(self.run_id) as historical:
            historical.pop('operator_protocol', None)
            historical['agent_sessions'] = []
        historical = self.store.get(self.run_id)
        with self.assertRaises(Conflict):
            edit_tasks(self.store, self.run_id, [change], historical['revision'])
        self.assertEqual(historical, self.store.get(self.run_id))


if __name__ == '__main__':
    unittest.main()
