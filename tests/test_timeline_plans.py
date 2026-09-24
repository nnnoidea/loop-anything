"""Batch construction and real scheduling; no model calls or fake completion."""
import copy
import sys
import tempfile
import time
import unittest
from pathlib import Path
from loop_anything.runtime.timeline_plan import build_plan
from loop_anything.interfaces.agent_tasks import RunTools, edit_tasks
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.store import Store


def definition():
    text = {'type': 'string'}
    def node(inputs, outputs, **extra):
        return dict(instructions='Process declared inputs.', inputs=inputs,
                    outputs={p: {'record_type': 'text'} for p in outputs}, **extra)
    bp = dict(schema_version=2, id='batch-test', version='1', entry='init',
        handbook={'instructions': 'Build a round, reuse data if present.'}, records={'text': text},
        nodes={'init': node({}, ['data'], initialize_timeline=True, plan_nodes=['prepare', 'train', 'judge']),
               'prepare': node({}, ['data']), 'train': node({'data': text, 'experiment': text}, ['result']),
               'judge': node({'results': {'type': 'array', 'items': text}}, ['summary'])},
        seed={'id': 'init', 'node': 'init', 'inputs': {}, 'outputs': {'data': {'id': 'cached'}}},
        plans={'round': {'parameters': {'type': 'object', 'required': ['experiments'],
                    'properties': {'experiments': {'type': 'array', 'items': text}}},
                'steps': {'prepare': {'node': 'prepare', 'inputs': {}},
                          'train': {'node': 'train', 'each': 'experiments', 'after': ['prepare'],
                              'inputs': {'data': {'from': 'prepare', 'port': 'data'},
                                         'experiment': {'literal': {'$': 'item'}}}},
                          'judge': {'node': 'judge', 'inputs': {'results': {'from': 'train', 'port': 'result', 'collect': True}}}}}})
    script = "import json,sys; r=json.load(sys.stdin); print(json.dumps({'outputs': {'data': 'fresh'}} if r['timeline']['tasks'][r['task_id']]['spec']['node']=='prepare' else {'outputs': {'result': r['inputs']['data']+':'+r['inputs']['experiment']}}))"
    implementations = {n: {'kind': 'agent'} for n in bp['nodes']}
    for n in ('prepare', 'train'):
        implementations[n] = {'kind': 'command', 'command': [sys.executable, '-c', script]}
    return bp, implementations


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'test.db')
        self.engine = Engine(self.store)
        self.bp, self.implementations = definition()

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def start(self):
        key = self.store.publish(self.bp, self.implementations)['key']
        self.run_id = self.store.create(key, 'Test')['id']
        self.assertEqual(['init'], list(self.store.get(self.run_id)['tasks']))
        self.engine.tick(self.run_id)
        self.e = self.store.get(self.run_id)['executions'][0]
        self.tools = RunTools(self.store, self.run_id, self.e['token'])

    def complete(self, task_id, outputs, settings=None):
        task = self.tools.call('read_task', {'task_id': task_id})
        envelope = {'outputs': outputs}
        if settings is not None:
            envelope['settings'] = dict(settings, completion_rule={'op': 'and', 'args': [{'op': 'ge', 'args': [{'path': ['completed', 'judge']}, 1]}, {'op': 'eq', 'args': [{'path': 'active_tasks'}, 0]}]})
        return self.tools.call('complete_task', {'task_id': task_id, 'task_version': task['task_version'], 'envelope': envelope})

    def commit(self):
        self.complete('init', {'data': 'cached-data'}, {'objective': 'Test'})

    def until_judge(self):
        for _ in range(150):
            self.engine.tick(self.run_id)
            r = self.store.get(self.run_id)
            self.assertFalse(any(w['status'] == 'fault' for w in r['tasks'].values()), r['executions'])
            found = [w for w in r['tasks'].values() if w['spec']['node'] == 'judge' and w['status'] == 'ready']
            if found:
                return r, [self.tools.call('read_task', {'task_id': w['id']}) for w in found]
            time.sleep(.02)
        self.fail('Judge did not become ready')

    def test_skip_means_no_action_and_aggregate_only_this_batch(self):
        self.start()
        args = {'name': 'round', 'key': 'first', 'values': {'experiments': ['a', 'b', 'c']},
                'steps': {'prepare': {'skip': True}, 'train': {'inputs': {'data': {'record': 'cached', 'revision': 1}}}}}
        self.tools.call('build_plan', args)
        self.tools.call('build_plan', args)  # Idempotent; no duplicate batch.
        self.assertEqual(5, len(self.store.get(self.run_id)['tasks']))
        self.commit()
        before = self.store.get(self.run_id)
        self.assertEqual(5, len(before['tasks']))
        self.assertFalse(any(w['spec']['node'] == 'prepare' for w in before['tasks'].values()))
        run, judges = self.until_judge()
        self.assertEqual(['cached-data:a', 'cached-data:b', 'cached-data:c'], judges[0]['inputs']['results'])
        self.assertEqual(set(before['tasks']), set(run['tasks']))  # Tick never constructs tasks.
        self.complete(judges[0]['task']['id'], {'summary': 'done'})
        self.tools.call('finish', {})
        self.engine.tick(self.run_id)
        self.assertEqual('completed', self.store.get(self.run_id)['status'])

    def test_conditional_omission_is_atomic_visible_and_requires_explicit_reuse(self):
        self.bp['plans']['round']['steps']['prepare']['when'] = {'path': 'values.enabled'}
        self.start()
        args = {'name': 'round', 'key': 'conditional', 'values': {'experiments': ['a', 'b'], 'enabled': False}}
        before = self.store.get(self.run_id)
        self.assertFalse(self.tools.respond('build_plan', args)['ok'])
        self.assertEqual(self.store.get(self.run_id)['tasks'], before['tasks'])
        args['steps'] = {'train': {'inputs': {'data': {'record': 'cached'}}}}
        preview = edit_tasks(self.store, self.run_id, [{'tool': 'build_plan', 'arguments': args}], before['revision'], self.e['token'], preview=True)
        self.assertEqual(preview['omitted'][0]['reason'], 'condition_false')
        self.assertEqual(self.store.get(self.run_id), before)
        result = self.tools.call('build_plan', args)
        self.assertEqual(result['omitted'][0]['step'], 'prepare')
        self.assertEqual(sorted(x['node'] for x in result['tasks']), ['judge', 'train', 'train'])
        self.tools.call('build_plan', args)
        run = self.store.get(self.run_id)
        self.assertEqual(sum(h['kind'] == 'plan_built' for h in run['history']), 1)
        self.assertFalse(any(t['status'] == 'skipped' for t in run['tasks'].values()))
        for value in [None, 'false', 0, [], {}]:
            bad = dict(args, key='invalid', values={'experiments': ['a'], 'enabled': value})
            self.assertFalse(self.tools.respond('build_plan', bad)['ok'])
        self.assertFalse(self.tools.respond('build_plan', dict(args, key='missing', values={'experiments': ['a']}))['ok'])
        self.assertEqual(self.store.get(self.run_id)['tasks'], run['tasks'])
        allowed = self.tools.call('build_plan', dict(args, key='included', values={'experiments': ['a'], 'enabled': True}))
        self.assertEqual(allowed['omitted'], [])
        self.assertIn('prepare', [t['node'] for t in allowed['tasks']])

    def test_empty_conditional_batch_has_no_placeholders_and_stable_key(self):
        for step in self.bp['plans']['round']['steps'].values():
            step['when'] = {'path': 'values.enabled'}
        self.start()
        args = {'name': 'round', 'key': 'empty', 'values': {'experiments': ['a'], 'enabled': False}}
        before = self.store.get(self.run_id)
        with self.assertRaises(Conflict):
            edit_tasks(self.store, self.run_id, [{'tool': 'build_plan', 'arguments': dict(args, parent_id='')}], before['revision'], preview=True)
        self.assertEqual(self.store.get(self.run_id), before)
        result = self.tools.call('build_plan', args)
        self.assertEqual(result['tasks'], [])
        self.assertEqual(len(result['omitted']), 3)
        self.assertEqual(list(self.store.get(self.run_id)['tasks']), ['init'])
        self.tools.call('build_plan', args)
        changed = dict(args, values={'experiments': ['a'], 'enabled': True})
        self.assertFalse(self.tools.respond('build_plan', changed)['ok'])
        self.assertEqual(list(self.store.get(self.run_id)['tasks']), ['init'])
        self.assertEqual(sum(h['kind'] == 'plan_built' for h in self.store.get(self.run_id)['history']), 1)

    def test_bad_plan_references_are_structured_errors_without_partial_tasks(self):
        self.bp['plans']['round']['steps']['train']['parameters']={'bad':{'$':['values','experiments',5]}}
        self.start()
        before=self.store.get(self.run_id)
        result=self.tools.respond('build_plan',{'name':'round','key':'invalid','values':{'experiments':['x']}})
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'invalid_request')
        self.assertIn('experiments',result['error']['message'])
        self.assertEqual(self.store.get(self.run_id),before)
        self.bp['plans']['round']['steps']['train'].pop('parameters')
        self.bp['plans']['round']['steps']['train']['each']='experiments.9'
        with self.assertRaises(Invalid):build_plan(self.bp,'round','bad-each',{'experiments':['x']})

    def test_defaults_construct_all_steps_and_execute_prepare(self):
        self.start()
        self.tools.call('build_plan', {'name': 'round', 'key': 'default', 'values': {'experiments': ['a', 'b']}})
        self.commit()
        run, judges = self.until_judge()
        self.assertEqual(['fresh:a', 'fresh:b'], judges[0]['inputs']['results'])
        self.assertEqual(1, sum(e['node'] == 'prepare' for e in run['executions']))

    def test_omitted_input_source_requires_explicit_reuse(self):
        self.start()
        response = self.tools.respond('build_plan', {'name': 'round', 'key': 'missing', 'values': {'experiments': ['a']}, 'steps': {'prepare': {'skip': True}}})
        self.assertFalse(response['ok'])
        self.assertIn('bind an existing record', response['error']['message'])
        self.assertEqual(['init'], list(self.store.get(self.run_id)['tasks']))

    def test_wrong_reused_type_or_missing_record_never_dispatches_train(self):
        for source in ({'literal': 123}, {'record': 'missing'}):
            with self.subTest(source=source):
                args = {'name': 'round', 'key': 'bad', 'values': {'experiments': ['a']},
                        'steps': {'prepare': {'skip': True}, 'train': {'inputs': {'data': source}}}}
                self.start()
                response = self.tools.respond('build_plan', args)
                if 'literal' in source:
                    self.assertFalse(response['ok'])
                else:
                    self.assertTrue(response['ok'])
                    self.commit()
                    for _ in range(3):
                        self.engine.tick(self.run_id)
                    self.assertFalse(any(e['node'] == 'train' for e in self.store.get(self.run_id)['executions']))

    def test_separate_batches_never_share_aggregate_inputs(self):
        first = build_plan(self.bp, 'round', 'one', {'experiments': ['a', 'b']})
        second = build_plan(self.bp, 'round', 'two', {'experiments': ['c']})
        self.assertEqual(2, len(first[-1]['inputs']['results']['records']))
        self.assertEqual(1, len(second[-1]['inputs']['results']['records']))
        self.assertFalse(set(first[-1]['inputs']['results']['records']) & set(second[-1]['inputs']['results']['records']))

    def test_empty_aggregation_and_dependency_cycle_rejected(self):
        with self.assertRaises(Invalid):
            build_plan(self.bp, 'round', 'empty', {'experiments': []})
        self.bp['plans']['round']['steps']['prepare']['after'] = ['judge']
        with self.assertRaises(Invalid):
            build_plan(self.bp, 'round', 'cycle', {'experiments': ['a']})

    def test_no_remaining_action_does_not_infer_completion_or_a_new_task(self):
        self.start()
        self.commit()
        self.tools.call('finish', {})
        self.engine.tick(self.run_id)
        current = self.store.get(self.run_id)
        self.assertEqual('running', current['status'])
        self.assertEqual([], current['diagnostics'])
        self.assertEqual(['init'], list(current['tasks']))

    def test_rules_and_skip_placeholders_no_longer_accepted(self):
        self.bp['rules'] = [{'id': 'old'}]
        with self.assertRaises(Invalid):
            self.store.publish(self.bp, self.implementations)
        del self.bp['rules']
        self.start()
        names = [x['name'] for x in self.tools.definitions()]
        self.assertNotIn('skip_action', names)
        self.assertNotIn('remove_skip', names)

    def test_aggregate_waits_for_last_committed_result(self):
        self.implementations['train'] = {'kind': 'agent'}
        self.start()
        self.tools.call('build_plan', {'name': 'round', 'key': 'join', 'values': {'experiments': ['a', 'b']},
            'steps': {'prepare': {'skip': True}, 'train': {'inputs': {'data': {'record': 'cached'}}}}})
        self.commit()
        self.engine.tick(self.run_id)
        run = self.store.get(self.run_id)
        train_ids = [w['id'] for w in run['tasks'].values() if w['spec']['node'] == 'train']
        judge_id = next(w['id'] for w in run['tasks'].values() if w['spec']['node'] == 'judge')
        self.assertTrue(self.tools.call('read_task', {'task_id': judge_id})['missing'])
        for index, task_id in enumerate(train_ids):
            self.complete(task_id, {'result': str(index)})
            info = self.tools.call('read_task', {'task_id': judge_id})
            self.assertEqual(index == 0, bool(info['missing']))
        self.assertEqual(['0', '1'], info['inputs']['results'])

    def test_changed_batch_key_is_rejected_without_partial_writes(self):
        self.start()
        args = {'name': 'round', 'key': 'replace', 'values': {'experiments': ['a', 'b']}}
        self.tools.call('build_plan', args)
        before = self.store.get(self.run_id)
        args['values'] = {'experiments': ['c']}
        self.assertFalse(self.tools.respond('build_plan', args)['ok'])
        self.assertEqual(before, self.store.get(self.run_id))

    def test_plan_tools_are_not_restricted_to_wakeup_node_plan_list(self):
        self.bp['nodes']['init']['plan_nodes'] = []
        self.start()
        self.tools.call('build_plan', {'name': 'round', 'key': 'allowed', 'values': {'experiments': ['a']}})
        self.assertEqual(4, len(self.store.get(self.run_id)['tasks']))

    def test_public_writer_requires_revision_and_rolls_back_budget_failure(self):
        self.bp['limits'] = {'max_tasks': 2}
        self.start()
        run = self.store.get(self.run_id)
        changes = [{'tool': 'build_plan', 'arguments': {'name': 'round', 'key': 'user', 'values': {'experiments': ['a']}}}]
        with self.assertRaises(Conflict):
            edit_tasks(self.store, self.run_id, changes, 0)
        with self.assertRaises(Invalid):
            edit_tasks(self.store, self.run_id, changes, run['revision'], self.e['token'])
        self.assertEqual(run, self.store.get(self.run_id))

    def test_requirement_change_preserves_records_and_scheduled_work(self):
        self.bp['seed']['policy'] = 'current'
        self.start()
        self.tools.call('build_plan', {'name': 'round', 'key': 'reuse', 'values': {'experiments': ['a']},
            'steps': {'prepare': {'skip': True}, 'train': {'inputs': {'data': {'record': 'cached'}}}}})
        self.commit()
        self.engine.change_settings(self.run_id, 1, {'guidance': 'New intent'}, self.e['token'])
        self.engine.tick(self.run_id)
        run = self.store.get(self.run_id)
        self.assertTrue(any(e['node'] == 'train' for e in run['executions']))
        train = next(w for w in run['tasks'].values() if w['spec']['node'] == 'train')
        self.assertEqual([], train['wait_reasons'])
        self.assertTrue(run['records']['cached'])

    def test_unknown_override_and_source_fields_are_not_silently_ignored(self):
        for overrides in ({'train': {'when': 'maybe'}}, {'train': {'inputs': {'data': {'from': 'prepare', 'port': 'data', 'path': 'hidden'}}}}):
            with self.assertRaises(Invalid):
                build_plan(self.bp, 'round', 'bad', {'experiments': ['a']}, overrides)

    def test_production_engine_rejects_legacy_run_without_writing_it(self):
        import json
        run = {'id': 'historical', 'title': 'Historical snapshot', 'status': 'paused', 'history': []}
        with self.store.connection() as db:
            db.execute('INSERT INTO runs VALUES (?,?)', (run['id'], json.dumps(run)))
            db.commit()
        with self.assertRaises(Invalid):
            self.engine.tick(run['id'])
        self.assertEqual(run, self.store.get(run['id']))


if __name__ == '__main__':
    unittest.main()
