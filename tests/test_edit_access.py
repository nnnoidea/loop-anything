"""Per-Loop portable edit protection, independent from ordinary execution."""
import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from loop_anything.runtime.store import Store
from loop_anything.interfaces.edit_access import EditAccess,EditLocked,LIFETIME,policy
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.packaging.packages import install,read_archive,make_archive,require_export,import_draft


class EditAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'a.db');self.tools=PlatformTools(self.store)
        self.a=self.tools.call('create_loop',{'name':'A'});self.b=self.tools.call('create_loop',{'name':'B'})
        self.ids=[next(d['loop_definition']['id'] for d in self.store.drafts() if d['id']==v['draft_id']) for v in (self.a,self.b)]
        self.a=self.tools.call('set_loop',dict(draft_id=self.a['draft_id'],revision=self.a['revision'],handbook='Use this Loop.'))
        self.key=self.tools.call('publish_loop',dict(draft_id=self.a['draft_id'],revision=self.a['revision']))['key']
        for value in (self.a,self.b):self.tools.call('set_loop_password',{'draft_id':value['draft_id'],'new_password':'protect'})
        self.access=EditAccess(self.store)
    def tearDown(self):self.tmp.cleanup()

    def test_cookie_scope_lifetime_restart_and_password_rotation(self):
        with patch('loop_anything.interfaces.edit_access.time.time',return_value=1000000):
            cookie=self.access.cookie(self.ids[0],True);status=self.access.status(self.ids[0],cookie)
            self.assertEqual(status['expires_at'],1000000+LIFETIME)
            self.assertFalse(self.access.status(self.ids[1],cookie)['unlocked'])
            self.assertEqual(status,EditAccess(self.store).status(self.ids[0],cookie))
            self.tools.call('set_loop_password',{'draft_id':self.a['draft_id'],'loop_password':'protect','new_password':'changed'})
            self.assertFalse(self.access.status(self.ids[0],cookie)['unlocked'])
        with patch('loop_anything.interfaces.edit_access.time.time',return_value=1000000+LIFETIME):
            self.assertFalse(self.access.status(self.ids[0],cookie)['unlocked'])
        for value in ('garbage','loop_edit=bad',self.access.cookie_name(self.ids[0])+'=999999999999.坏'):
            self.assertFalse(self.access.status(self.ids[0],value)['unlocked'])
        self.assertTrue(self.access.status()['unlocked'])

    def test_all_authoring_paths_guard_current_loop_identity(self):
        self.assertFalse(self.tools.respond('set_loop',dict(draft_id=self.a['draft_id'],revision=self.a['revision'],name='blocked'))['ok'])
        draft=next(d for d in self.store.drafts() if d['id']==self.a['draft_id'])
        forged=copy.deepcopy(draft['loop_definition']);forged['id']='different'
        with self.assertRaises(EditLocked):self.store.save_draft(forged,draft['implementations'],draft['id'],draft['revision'])
        with self.assertRaises(EditLocked):self.tools.call('copy_loop',{'key':self.key,'new_version':True})
        copied=self.tools.call('copy_loop',{'key':self.key})
        self.assertTrue(self.tools.respond('set_loop',dict(draft_id=copied['draft_id'],revision=copied['revision'],name='new identity'))['ok'])
        edited=self.tools.call('set_loop',dict(draft_id=self.a['draft_id'],revision=self.a['revision'],name='allowed',loop_password='protect'))
        self.assertEqual(edited['revision'],self.a['revision']+1)
        self.assertFalse(self.tools.respond('set_loop_password',{'draft_id':self.a['draft_id'],'new_password':''})['ok'])
        self.tools.call('set_loop_password',{'draft_id':self.a['draft_id'],'new_password':'','loop_password':'protect'})
        self.assertTrue(self.tools.respond('set_loop',dict(draft_id=self.a['draft_id'],revision=edited['revision'],name='cleared'))['ok'])

    def test_export_import_preserves_verifier_and_rejects_changed_protected_identity(self):
        raw=base64.b64decode(self.tools.call('export_loop',{'draft_id':self.a['draft_id']})['base64'])
        document,assets,_,_=read_archive(raw)
        self.assertIn('edit_protection',document)
        self.assertNotIn(b'"protect"',raw)
        draft_store=Store(Path(self.tmp.name)/'draft.db');imported=import_draft(draft_store,raw)
        self.assertEqual(policy(draft_store,self.ids[0]),policy(self.store,self.ids[0]))
        self.assertEqual(draft_store.catalog(),[])  # Loading a draft does not install or start it.
        self.assertFalse(PlatformTools(draft_store).respond('set_loop',dict(draft_id=imported['id'],revision=1,name='blocked'))['ok'])
        import_draft(draft_store,raw)  # Exact repeated import is read-like even while locked.
        altered=copy.deepcopy(document);altered['loop_definition']['name']='changed draft'
        with self.assertRaises(EditLocked):import_draft(draft_store,make_archive(altered,assets))
        other=Store(Path(self.tmp.name)/'b.db');result=install(other,raw)
        self.assertEqual(policy(other,self.ids[0]),policy(self.store,self.ids[0]))
        with self.assertRaises(EditLocked):PlatformTools(other).call('copy_loop',{'key':result['key'],'new_version':True})
        changed=copy.deepcopy(document);changed['loop_definition']['name']='tampered'
        with self.assertRaises(EditLocked):require_export(other,changed,assets)
        changed.pop('edit_protection')
        with self.assertRaises(EditLocked):install(other,make_archive(changed,assets))
        self.assertEqual(install(other,raw)['key'],result['key'])  # Identical reimport remains read-like.
        self.assertTrue(PlatformTools(other).respond('copy_loop',{'key':result['key'],'new_version':True,'loop_password':'protect'})['ok'])

    def test_protected_loop_can_run_and_accept_public_user_operations(self):
        started=self.tools.call('start_run',{'key':self.key,'title':'use protected','authorization':'test'})
        info=self.tools.call('read_task',{'run_id':started['run_id'],'task_id':started['entry_task_id']})
        completed=self.tools.call('complete_task',{'run_id':started['run_id'],'task_id':started['entry_task_id'],
            'task_version':info['task_version'],'envelope':{'settings':{'objective':'token handled by platform'},'outputs':{}}})
        self.assertTrue(completed['accepted'])
        self.tools.call('finish',{'run_id':started['run_id']})
        self.assertEqual(self.store.get(started['run_id'])['agent_sessions'],[])
        settings=self.tools.call('read_timeline',{'run_id':started['run_id']})['settings']
        self.tools.call('change_settings',{'run_id':started['run_id'],'revision':settings['revision'],'change':{'guidance':'public edit'}})
        self.assertEqual(self.store.get(started['run_id'])['agent_sessions'],[])
        with self.assertRaises(Exception):self.tools.call('change_settings',{'run_id':started['run_id'],'token':'wrong execution','revision':1,'change':{'guidance':'wrong'}})
        from loop_anything.interfaces.agent_tasks import acquire_in_run
        with self.store.edit(started['run_id']) as saved:acquire_in_run(saved,'background',task_id=started['entry_task_id'])
        from loop_anything.runtime.model import Conflict
        with self.assertRaises(Conflict):self.tools.call('change_settings',{'run_id':started['run_id'],'revision':1,'change':{'guidance':'must not steal worker scope'}})


if __name__=='__main__':unittest.main()
