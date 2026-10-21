from communication_helpers import legacy_offer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.communication import Communication, service
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime.store import Store
from loop_anything.runtime.agent_prompt import author_context


class MachineIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'LOOP_ANYTHING_IDENTITY_DIR': str(self.root / 'identity')})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def comm(self, name):
        return service(Store(self.root / (name + '.db')))

    def test_registration_discovery_across_workspaces_is_local_and_allows_duplicate_names(self):
        first=self.comm('first');second=self.comm('second')
        profile={'name':'Research','description':'Read papers','enabled':False,
                 'implementation':{'kind':'agent','command':['codex','--secret','DO-NOT-EXPOSE'],'cwd':str(self.root)}}
        first.config('agent',agent_id='research',agent=profile)
        second.config('agent',agent_id='research',agent=profile)
        second.config('agent',agent=profile)
        tools=PlatformTools(second.store)
        with patch.object(second,'directory',side_effect=AssertionError('No team transport during registration discovery')):
            result=tools.call('communication_workspace',{'registered_agents':True})
        agents=result['registered_agents']
        self.assertEqual(len(agents),3)
        self.assertEqual(sum(a['current_workspace'] for a in agents),2)
        self.assertEqual(len({(a['workspace_id'],a['agent_id']) for a in agents}),3)
        self.assertTrue(all(a['name']=='Research' and not a['enabled'] for a in agents))
        self.assertTrue(all(a['executable']=='codex' and a['cwd']==str(self.root) for a in agents))
        self.assertNotIn('DO-NOT-EXPOSE',json.dumps(result))
        self.assertNotIn('implementation',json.dumps(result))
        self.assertEqual(first.settings()['agents']['research']['name'],'Research')
        # Explicitly targeting one record updates it without changing the other workspace.
        second.config('agent',agent_id='research',agent={'name':'Research updated'})
        self.assertEqual(first.settings()['agents']['research']['name'],'Research')

    def test_registration_discovery_reports_missing_or_replaced_workspaces(self):
        first=self.comm('first');second=self.comm('second');missing=self.comm('missing')
        with first.transaction() as db:
            config=first.settings(db);config['machine_id']='another-machine'
            db.execute('UPDATE communication_settings SET document=?',(json.dumps(config),))
        Path(missing.store.filename).unlink()
        result=second.machine_identity.agent_registrations(second.settings()['instance_id'])
        self.assertEqual(len(result['unavailable_workspaces']),2)
        self.assertFalse(Path(missing.store.filename).exists())
        self.assertEqual(result['registered_agents'],[])

    @staticmethod
    def copy_database(source, destination):
        a = sqlite3.connect(source)
        b = sqlite3.connect(destination)
        try:a.backup(b)
        finally:a.close();b.close()

    def test_lazy_concurrent_creation_and_shared_machine_with_distinct_workspaces(self):
        path = self.root / 'identity' / 'identity.sqlite3'
        self.assertFalse(path.exists())
        code = 'import json;from loop_anything.runtime.machine_identity import MachineIdentity;print(json.dumps(MachineIdentity().read()))'
        processes = [subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
        identities = []
        for process in processes:
            out, err = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, err)
            identities.append(json.loads(out))
        self.assertTrue(all(value == identities[0] for value in identities))
        self.assertRegex(identities[0]['machine_id'], r'^machine-[0-9a-f]{32}$')
        a, b = self.comm('a'), self.comm('b')
        first = PlatformTools(a.store).call('communication_status', {})
        second = PlatformTools(b.store).call('communication_status', {})
        self.assertEqual(first['self']['machine_id'], second['self']['machine_id'])
        self.assertNotEqual(first['self']['workspace_id'], second['self']['workspace_id'])
        self.assertEqual(first['instance_id'], first['self']['workspace_id'])
        self.assertEqual(author_context(a.store, None, {})['self'], first['self'])
        self.assertEqual(a.store.list(), [])

    def test_rename_restart_and_database_move_preserve_identity(self):
        a = self.comm('a')
        original = a.self_info()
        a.config('identity', name='Research host')
        a = Communication(Store(a.store.filename))
        self.assertEqual(a.self_info()['machine_name'], 'Research host')
        moved = self.root / 'moved.db'
        Path(a.store.filename).rename(moved)
        with patch('socket.gethostname', return_value='renamed-os-host'):
            moved_comm = Communication(Store(moved))
        self.assertFalse(moved_comm.identity_conflict)
        self.assertEqual(moved_comm.self_info()['machine_id'], original['machine_id'])
        self.assertEqual(moved_comm.self_info()['workspace_id'], original['workspace_id'])

    def test_legacy_upgrade_preserves_routing_identity_and_name_changes_do_not_rebind(self):
        a = self.comm('legacy')
        with a.transaction() as db:
            config = a.settings(db)
            config['instance_id'] = 'machine-123456abcdef'
            config.pop('machine_id')
            config['identity_location'] = {'host': socket.gethostname(), 'database': a.store.filename}
            db.execute('UPDATE communication_settings SET document=? WHERE id=1', (json.dumps(config),))
        upgraded = Communication(Store(a.store.filename))
        self.assertFalse(upgraded.identity_conflict)
        self.assertEqual(upgraded.self_info()['workspace_id'], 'machine-123456abcdef')
        self.assertNotIn('identity_location', upgraded.settings())
        before = upgraded.self_info()
        with patch('socket.gethostname', return_value='renamed-host'):
            again = Communication(Store(a.store.filename))
        self.assertEqual(again.self_info(), before)
        self.assertFalse(again.identity_conflict)

    def test_copies_keep_original_execution_history_read_only_after_explicit_fork(self):
        a = self.comm('a')
        tools = PlatformTools(a.store)
        draft = tools.call('create_loop', {'name': 'Original'})
        draft = tools.call('set_loop', {'draft_id':draft['draft_id'], 'revision':draft['revision'], 'handbook':'Initialize the requested work.'})
        key = tools.call('publish_loop', {'draft_id': draft['draft_id'], 'revision': draft['revision']})['key']
        started = tools.call('start_run', {'key': key, 'title': 'Original work', 'authorization':'Initialize only'})
        original = a.store.get(started['run_id'])
        path = self.root / 'copy.db'
        self.copy_database(a.store.filename, path)
        with patch.dict(os.environ, {'LOOP_ANYTHING_IDENTITY_DIR': str(self.root / 'other-machine')}):
            engine = Engine(Store(path))
        try:
            b = engine.communication
            self.assertTrue(b.identity_conflict)
            self.assertNotEqual(b.self_info()['machine_id'], a.self_info()['machine_id'])
            engine.recover()  # Conflict must not take over copied sessions.
            self.assertEqual(engine.store.get(original['id']), original)
            b.config('identity', name='Second host', regenerate=True)
            self.assertFalse(b.identity_conflict)
            self.assertNotEqual(b.self_info()['workspace_id'], a.self_info()['workspace_id'])
            copy = engine.store.get(original['id'])
            self.assertTrue(copy['identity_read_only'])
            for field in ('executions', 'records', 'tasks', 'history'):
                self.assertEqual(copy[field], original[field])
            with patch.object(engine.timeline_runtime, 'tick', side_effect=AssertionError('No takeover')):
                engine.tick(original['id'])
            self.assertEqual(engine.store.scheduling_list(), [])
            with self.assertRaises(Conflict), engine.store.edit(original['id']):pass
            with self.assertRaises(Conflict):
                b.request({'location':'local', 'message':'Do not continue old work', 'token':started['token'],
                           'source':{'run_id':original['id'],'task_id':started['entry_task_id']}})
            new = PlatformTools(engine.store).call('start_run', {'key': key, 'title': 'New work', 'authorization':'Initialize only'})
            self.assertNotEqual(new['run_id'], original['id'])
            self.assertNotIn('identity_read_only', engine.store.get(new['run_id']))
            self.assertEqual(a.store.get(original['id']), original)
        finally:engine.close()

    def test_same_machine_copy_conflicts_but_does_not_change_machine_id(self):
        a = self.comm('a')
        group = a.config('group', path=str(self.root / 'nas'), create=True)['configuration']
        gid = next(iter(group['groups']))
        request = legacy_offer(a,location='group',group_id=gid,agent_id='missing',message='Pending work')
        a.scan()
        publication = next((self.root / 'nas' / 'messages' / 'broadcast').glob('*.json'))
        a.control(request['request']['id'], 'cancel')  # Archive is journaled but not yet applied.
        path = self.root / 'copy.db'
        self.copy_database(a.store.filename, path)
        b = Communication(Store(path))
        self.assertTrue(b.identity_conflict)
        self.assertEqual(b.self_info()['machine_id'], a.self_info()['machine_id'])
        with self.assertRaises(Conflict):b.request({'location': 'local', 'message': 'help'})
        with self.assertRaises(Conflict):b.control(request['request']['id'],'cancel')
        self.assertFalse(b.read(request['request']['id'])['request']['can_control'])
        before = b.settings()
        with self.assertRaises(Invalid):b.config('identity', name='', regenerate=True)
        self.assertTrue(b.identity_conflict, 'A rolled-back identity change must remain blocked')
        self.assertEqual(b.settings(), before)
        b.config('identity', name=a.self_info()['machine_name'], regenerate=True)
        self.assertEqual(b.self_info()['machine_id'], a.self_info()['machine_id'])
        self.assertNotEqual(b.self_info()['workspace_id'], a.self_info()['workspace_id'])
        with self.assertRaises(Conflict):b.control(request['request']['id'],'retry_notification',notification_id='old')
        self.assertFalse(b.read(request['request']['id'])['request']['can_retry_notification'])
        b.scan()
        self.assertTrue(publication.exists(), 'A copy must not apply the source archive journal')
        self.assertFalse(b.authorized({'request_id':request['request']['id'],'token':request['request_token']}))
        a.last_scan = 0;a.scan()
        self.assertFalse(publication.exists())

    def test_public_members_include_machine_and_workspace_without_identity_path(self):
        a, b = self.comm('a'), self.comm('b')
        config = a.config('group', path=str(self.root / 'nas'), create=True)['configuration']
        gid = next(iter(config['groups']))
        b.config('group', path=str(self.root / 'nas'))
        b.config('agent', agent_id='helper', task_confirmed=True, agent={
            'name': 'Helper', 'description': 'Test help', 'groups': [gid],
            'implementation': {'kind': 'agent', 'command': [sys.executable, '-c', 'pass']}})
        b.scan();a.scan()
        member = next(m for m in a.directory(gid)['agents'] if m['id'] == 'helper')
        self.assertEqual(member['machine_id'], b.self_info()['machine_id'])
        self.assertEqual(member['workspace_id'], b.self_info()['workspace_id'])
        self.assertEqual(member['instance_id'], member['workspace_id'])
        self.assertNotIn(str(self.root / 'identity'), json.dumps(a.directory()))


if __name__ == '__main__':unittest.main()
