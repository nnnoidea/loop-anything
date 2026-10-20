import json
import sys
import tempfile
import unittest
from pathlib import Path

from loop_anything.runtime.store import Store
from loop_anything.runtime.communication import service
from loop_anything.runtime.communication_spaces import discover, join_instructions, MANIFEST
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.interfaces.communication_tools import call, definitions


class SharedSpaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.a=service(Store(self.root/'a.db'));self.b=service(Store(self.root/'b.db'))
        self.nas=self.root/'nas';self.nas.mkdir()

    def tearDown(self):self.tmp.cleanup()

    def create(self):
        sid=self.a.config('space',path=str(self.nas),name='Research')['space_id']
        c=self.a.config('group',space_id=sid,name='Papers',description='Paper assistance',create=True)['configuration']
        return sid,next(iter(c['groups'].values()))

    def test_discover_join_then_explicitly_expose_command_mapping(self):
        sid,g=self.create()
        alias=self.root/'b-mount';alias.symlink_to(self.nas,target_is_directory=True)
        self.b.config('space',path=str(alias),name='Ignored local rename')
        rows=call(self.b.store,'communication_workspace',{'discover':True})['shared_spaces']
        self.assertEqual(rows[0]['id'],sid)
        self.assertFalse(rows[0]['groups'][0]['joined'])
        self.assertEqual(self.b.settings()['groups'],{})
        self.assertEqual(self.b.directory()['agents'],[])
        self.b.config('group',space_id=sid,relative_path=g['relative_path'],group_id=g['id'])
        self.assertEqual(self.b.settings()['agents'],{})
        implementation={'kind':'agent','command':[sys.executable,'-c','print("local-secret-command")']}
        self.b.config('agent',agent_id='papers',agent={'name':'Paper Agent','description':'Find research papers','groups':[],'implementation':implementation})
        self.b.scan();self.a.scan()
        self.assertEqual(self.a.directory()['agents'],[])
        self.b.config('agent',agent_id='papers',agent={'groups':[g['id']], 'description':'Find research papers'},task_confirmed=True)
        self.b.last_scan=0
        # Force heartbeat refresh, without starting any CLI.
        member=Path(g['path'])/'members'/(self.b.settings()['instance_id']+'.json');member.unlink()
        self.b.scan();self.a.last_scan=0;self.a.scan()
        agent=self.a.directory()['agents'][0]
        self.assertEqual(agent['id'],'papers')
        self.assertEqual(agent['instance_id'],self.b.settings()['instance_id'])
        self.assertNotIn('implementation',agent)
        self.assertNotIn('local-secret-command',member.read_text())
        self.assertEqual(self.b.settings()['agents']['papers']['implementation'],implementation)
        self.assertEqual(self.a.requests(),[])

    def test_missing_mount_and_replaced_space_never_create_group(self):
        with self.assertRaisesRegex(Invalid,'Mount'):
            self.a.config('space',path=str(self.root/'missing'))
        self.assertFalse((self.root/'missing').exists())
        sid,g=self.create()
        info=json.loads((self.nas/MANIFEST).read_text());info['id']='different-space'
        (self.nas/MANIFEST).write_text(json.dumps(info))
        with self.assertRaises(Conflict):self.a.config('group',space_id=sid,name='Wrong mount',create=True)
        self.assertIn('identity changed',discover(self.a)[0]['error'])
        self.assertEqual(len(list((self.nas/'groups').iterdir())),1)

    def test_join_checks_selected_identity_and_rejects_path_escape(self):
        sid,g=self.create();self.b.config('space',path=str(self.nas))
        for relative in ('../outside','/tmp/group','nested/group'):
            with self.assertRaises(Invalid):self.b.config('group',space_id=sid,relative_path=relative,group_id=g['id'])
        with self.assertRaises(Conflict):self.b.config('group',space_id=sid,relative_path=g['relative_path'],group_id='stale-id')
        outside=self.root/'outside';outside.mkdir()
        (self.nas/'groups'/'symlink').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(Invalid):self.b.config('group',space_id=sid,relative_path='symlink',group_id=g['id'])
        self.assertEqual(self.b.settings()['groups'],{})

    def test_bad_group_does_not_hide_good_group_and_instructions_are_portable(self):
        sid,g=self.create();bad=self.nas/'groups'/'bad';bad.mkdir();(bad/'group.json').write_text('broken')
        rows=discover(self.a)
        self.assertEqual(len(rows[0]['groups']),1);self.assertEqual(len(rows[0]['errors']),1)
        text=join_instructions(self.a,g['id'])['instructions']
        self.assertIn(sid,text);self.assertIn(g['id'],text);self.assertIn('groups/'+g['relative_path'],text)
        self.assertNotIn(str(self.root),text)
        self.assertNotIn('implementation',text)
        self.a.config('leave',group_id=g['id'])
        self.assertFalse(discover(self.a)[0]['groups'][0]['joined'])
        self.a.config('group',space_id=sid,relative_path=g['relative_path'],group_id=g['id'])
        self.assertTrue(discover(self.a)[0]['groups'][0]['joined'])

    def test_remount_same_space_keeps_membership_and_checks_groups(self):
        sid,g=self.create();renamed=self.root/'remount';self.nas.rename(renamed)
        self.assertIn('error',discover(self.a)[0])
        self.a.config('space',space_id=sid,path=str(renamed))
        group=self.a.settings()['groups'][g['id']]
        self.assertEqual(group['path'],str((renamed/'groups'/g['relative_path']).resolve()))
        self.assertTrue(group['enabled'])
        self.assertEqual(len(self.a.settings()['spaces']),1)
        self.assertTrue(discover(self.a)[0]['groups'][0]['joined'])

    def test_tools_expose_setup_without_changing_runtime_status(self):
        schemas={t['name']:t['inputSchema']['properties'] for t in definitions()}
        self.assertIn('space_id',schemas['communication_config'])
        self.assertIn('relative_path',schemas['communication_config'])
        self.assertIn('discover',schemas['communication_workspace'])
        self.create()
        self.assertNotIn('shared_spaces',call(self.a.store,'communication_workspace',{}))
        self.assertNotIn('spaces',call(self.a.store,'communication_status',{}))
        self.assertEqual(self.a.store.list(),[])
