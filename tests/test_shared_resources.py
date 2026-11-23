import tempfile
import unittest
from pathlib import Path

from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.packaging.packages import make_archive, read_archive
from loop_anything.runtime.agent_prompt import receiver_context
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime.shared_resources import set_resource
from loop_anything.runtime.store import Store
from tests.runtime_fixture import runtime_run, seeded_draft


class SharedResourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'platform.sqlite3')
        self.tools = PlatformTools(self.store)

    def test_registration_saves_metadata_and_preserves_optional_preview(self):
        fields = {'resource_id': 'team-guide', 'revision': 0, 'name': 'Team guide',
                  'location': 'https://example.invalid/guides', 'skill': '/unmounted/team/SKILL.md'}
        preview = {'summary': 'A curated excerpt', 'facts': [{'label': 'Pages', 'value': '5'}]}
        created = set_resource(self.store, dict(fields, preview=preview))
        self.assertEqual(created['location_kind'], 'url')
        self.assertEqual(created['skill_kind'], 'path')
        self.assertNotIn('preview', self.tools.call('list_resources', {})['resources'][0])
        revision = set_resource(self.store, dict(fields, revision=1, name='New name'))
        self.assertEqual(revision['preview'], preview)
        self.assertEqual(revision['revision'], 2)
        with self.assertRaises(Conflict):
            set_resource(self.store, dict(fields, revision=1))
        with self.assertRaises(Invalid):
            set_resource(self.store, dict(fields, revision=2, location='javascript:alert(1)'))
        self.assertFalse(self.tools.respond('set_resource', dict(fields, revision=2))['ok'])
        self.assertEqual(self.tools.call('read_resource', {'resource_id': fields['resource_id']})['resource'], revision)

    def test_packages_carry_ids_and_tasks_resolve_on_the_current_platform(self):
        draft = seeded_draft(self.tools, {'name': 'Uses a shared resource'})
        draft = self.tools.call('set_loop', {'draft_id': draft['draft_id'], 'revision': draft['revision'],
                                            'handbook': 'Consult the registered resource when relevant.'})
        args = {'draft_id': draft['draft_id'], 'revision': draft['revision'], 'node_id': 'initialize'}
        duplicate = self.tools.respond('put_node', dict(args, resources=['inventory', 'inventory']))
        self.assertFalse(duplicate['ok'])
        edited = self.tools.call('put_node', dict(args, resources=['inventory', 'elsewhere']))
        item = self.tools.call('read_loop', {'draft_id': draft['draft_id']})['loop']
        manifest = read_archive(make_archive({key: item[key] for key in ('loop_definition', 'implementations')}))[0]
        self.assertIn('shared_resources', manifest['requires'])
        self.assertEqual(manifest['loop_definition']['nodes']['initialize']['resources'], ['inventory', 'elsewhere'])
        key = self.tools.call('publish_loop', {'draft_id': draft['draft_id'], 'revision': edited['revision']})['key']
        started = runtime_run(self.store, {'key': key, 'title': 'Resolve source references'})
        task_args = {'run_id': started['run_id'], 'token': started['token'], 'task_id': started['entry_task_id']}
        before = self.tools.call('read_task', task_args)['resources']
        self.assertEqual([entry['status'] for entry in before], ['missing', 'missing'])
        set_resource(self.store, {'resource_id': 'inventory', 'revision': 0, 'name': 'Inventory',
                     'location': '/source/team/inventory', 'skill': 'https://example.invalid/SKILL.md',
                     'preview': {'summary': 'Only present in the browser preview'}})
        resources = self.tools.call('read_task', task_args)['resources']
        self.assertEqual([entry['status'] for entry in resources], ['registered', 'missing'])
        self.assertNotIn('preview', resources[0])
        remote = receiver_context({'resources': resources}, '/source/team', '/receiver/team')
        self.assertEqual(remote['resources'][0]['location'], '/receiver/team/inventory')
        self.assertEqual(remote['resources'][0]['skill'], resources[0]['skill'])
        self.assertEqual(resources[0]['location'], '/source/team/inventory')
