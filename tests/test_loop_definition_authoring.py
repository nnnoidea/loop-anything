import tempfile
import unittest
from pathlib import Path
from loop_anything.runtime.model import Conflict, Invalid, validate
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine


def definition():
    return {'schema_version': 2, 'id': 'authored-loop', 'name': 'Authored in workspace', 'version': '1', 'entry': 'input',
            'handbook': {'instructions': 'Build Tasks and submit results.'}, 'records': {'text': {'type': 'string'}},
            'nodes': {'input': {'instructions': 'Initialize', 'initialize_timeline': True, 'plan_nodes': ['finish'], 'inputs': {}, 'outputs': {'result': {'record_type': 'text'}}},
                      'finish': {'instructions': 'Finish', 'inputs': {'message': {'type': 'string'}}, 'outputs': {'result': {'record_type': 'text'}}}},
            'seed': {'id': 'input', 'node': 'input', 'inputs': {}, 'outputs': {'result': {'id': 'source'}}}, 'plans': {},
            'layout': {'input': {'x': 30, 'y': 50}, 'finish': {'x': 290, 'y': 50}}}


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'db.sqlite')

    def tearDown(self):
        self.tmp.cleanup()

    def test_incomplete_draft_survives_restart_but_cannot_publish(self):
        bp = {'id': 'draft', 'version': '1', 'entry': '', 'nodes': {}, 'transitions': []}
        saved = self.store.save_draft(bp, {})
        restored = Store(self.store.filename).drafts()
        self.assertEqual(restored[0]['id'], saved['id'])
        self.assertEqual(restored[0]['loop_definition'], bp)
        with self.assertRaises(Invalid): self.store.publish(bp, {})
        self.assertEqual(self.store.catalog(), [])

    def test_stale_draft_save_rejected(self):
        saved = self.store.save_draft(definition(), {})
        updated = self.store.save_draft(definition(), {}, saved['id'], 1)
        self.assertEqual(updated['revision'], 2)
        with self.assertRaises(Conflict): self.store.save_draft(definition(), {}, saved['id'], 1)
        with self.assertRaises(Conflict): self.store.save_draft(definition(), {}, 'absent', 1)

    def test_publish_from_draft_then_run_and_new_version(self):
        bp = definition()
        implementations = {'input': {'kind': 'agent'}, 'finish': {'kind': 'agent'}}
        draft = self.store.save_draft(bp, implementations)
        key = self.store.publish(draft['loop_definition'], draft['implementations'])['key']
        run_id = self.store.create(key, 'Visual authoring run')['id']
        self.assertEqual(self.store.get(run_id)['executions'], [])  # publish does not execute
        engine = Engine(self.store)
        try:
            for result in ('hello', 'done'):
                engine.tick(run_id)
                current = self.store.get(run_id)
                from loop_anything.interfaces.agent_tasks import RunTools
                tools = RunTools(self.store, run_id, current['agent_sessions'][0]['token'])
                task_id = bp['seed']['id'] if result == 'hello' else 'finish'
                task = tools.call('read_task', {'task_id': task_id})
                envelope = {'outputs': {'result': result}}
                if result == 'hello':
                    envelope.update(settings={'objective': 'Finish', 'completion_rule': {'op': 'and', 'args': [{'op': 'ge', 'args': [{'path': ['completed', 'finish']}, 1]}, {'op': 'eq', 'args': [{'path': 'active_tasks'}, 0]}]}}, tasks=[{'id': 'finish', 'node': 'finish',
                        'inputs': {'message': {'record': 'source'}}, 'outputs': {'result': {'id': 'done'}}}])
                tools.call('complete_task', {'task_id': task_id, 'task_version': task['task_version'], 'envelope': envelope})
            tools.call('finish', {})
            engine.tick(run_id)
            self.assertEqual(self.store.get(run_id)['status'], 'completed')
            self.assertEqual(self.store.get(run_id)['executions'][1]['inputs']['message'], 'hello')
        finally:
            engine.close()
        bp['nodes']['input']['label'] = 'Changed label'
        changed = self.store.publish(bp, implementations)['key']
        self.assertNotEqual(key, changed)
        bp['version'] = '2'; self.store.publish(bp, implementations)
        self.assertNotIn('label', self.store.get(run_id)['loop_definition']['nodes']['input'])

    def test_bad_implementation_or_removed_output_cannot_publish(self):
        bp = definition()
        self.assertFalse(validate(bp, {'input': {'kind': 'command', 'command': 'python script.py'}})['valid'])
        implementations = {'input': {'kind': 'agent'}, 'finish': {'kind': 'agent'}}
        del bp['records']['text']
        self.assertFalse(validate(bp, implementations)['valid'])
        for bp, implementations in [(None, {}), ({'nodes': {'a': None}}, {}), (definition(), [])]:
            self.assertFalse(validate(bp, implementations)['valid'])


if __name__ == '__main__':
    unittest.main()
