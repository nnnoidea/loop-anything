import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from loop_anything.runtime.store import Store
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime.run_library import list_runs, update_run, delete_run, manage_loop
from loop_anything.interfaces.platform_tools import PlatformTools


class RunLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,LOOP_ANYTHING_IDENTITY_DIR=self.tmp.name+'/identity');self.env.start();self.addCleanup(self.env.stop)
        self.store=Store(Path(self.tmp.name)/'runs.db');self.tools=PlatformTools(self.store)
        self.draft=self.tools.call('create_loop',{'name':'Research'})
        self.draft=self.tools.call('set_loop',{'draft_id':self.draft['draft_id'],'revision':self.draft['revision'],'handbook':'Run the agreed task.'})
        self.key=self.tools.call('publish_loop',{'draft_id':self.draft['draft_id'],'revision':self.draft['revision']})['key']

    def create(self, name='tdh', title='Run', created=10, active=20):
        run=self.store.create(self.key,title,created_by=name)
        with self.store.edit(run['id']) as current:
            current['created_at']=created;current['last_activity_at']=active
        return run['id']

    def end(self, ident):
        with self.store.edit(ident) as run:run['status']='terminated'

    def test_summary_query_paginates_without_loading_timelines(self):
        ids=[self.create('tdh' if i%2 else 'alice','Trial '+str(i),i,100-i) for i in range(8)]
        with patch.object(self.store,'_load',side_effect=AssertionError('Loaded a Timeline')):
            first=list_runs(self.store,limit=3)
            second=list_runs(self.store,limit=3,offset=first['next_offset'])
            self.assertEqual(first['total'],8);self.assertEqual([r['id'] for r in first['runs']],ids[:3])
            self.assertFalse(set(r['id'] for r in first['runs'])&set(r['id'] for r in second['runs']))
            self.assertEqual({g['created_by']:g['count'] for g in first['groups']},{'tdh':4,'alice':4})
            self.assertNotIn('executions',first['runs'][0]);self.assertNotIn('records',first['runs'][0])
            subset=list_runs(self.store,created_by='tdh',created_from=2,created_to=7,active_from=95,active_to=99,sort='created_at',order='asc')
            self.assertEqual([r['id'] for r in subset['runs']],[ids[3],ids[5]])
            self.assertEqual(list_runs(self.store,query='alice')['total'],4)

    def test_metadata_conflicts_are_independent_of_execution_revision_and_work_after_end(self):
        ident=self.create()
        with self.store.edit(ident) as run:Store.log(run,'dispatched','Work started')
        self.end(ident)
        result=update_run(self.store,ident,0,title='Renamed',created_by=' tao ',archived=True)
        self.assertEqual(result['created_by'],'tao');self.assertEqual(result['metadata_revision'],1)
        self.assertEqual(list_runs(self.store)['total'],0)
        self.assertEqual(list_runs(self.store,archived='only')['runs'][0]['title'],'Renamed')
        with self.assertRaises(Conflict):update_run(self.store,ident,0,title='Stale')
        update_run(self.store,ident,1,archived=False)
        self.assertEqual(list_runs(self.store)['total'],1)

    def test_polling_and_reads_do_not_count_as_activity_but_progress_changes_do(self):
        ident=self.create(active=20)
        with self.store.edit(ident) as run:
            run['executions'].append({'id':'fake','task_id':'initialize','status':'waiting','implementation':{'kind':'external'}})
            with patch('time.time',return_value=30):Store.log(run,'observation','Checking')
            self.assertEqual(run['last_activity_at'],20)
            detail={'from':'waiting','to':'waiting','event':'progress','detail':{'progress':10,'observed_at':30}}
            with patch('time.time',return_value=40):Store.log(run,'transition','progress','fake',detail)
            self.assertEqual(run['last_activity_at'],40)
            detail['detail']['observed_at']=50
            with patch('time.time',return_value=50):Store.log(run,'transition','progress','fake',detail)
            self.assertEqual(run['last_activity_at'],40)
            detail['detail']['progress']=20
            with patch('time.time',return_value=60):Store.log(run,'transition','progress','fake',detail)
        for _ in range(2):list_runs(self.store);self.store.get(ident)
        self.assertEqual(self.store.get(ident)['last_activity_at'],60)

    def test_delete_checks_run_worker_child_and_loop_references(self):
        parent=self.create();child=self.create()
        with self.store.edit(child) as run:run['parent_call']={'run_id':parent,'task_id':'call','execution_id':'call-1'}
        self.assertEqual(list_runs(self.store,root_only=True)['total'],1)
        self.assertEqual(list_runs(self.store,parent_run_id=parent)['runs'][0]['id'],child)
        with self.assertRaises(Conflict):delete_run(self.store,parent,0)
        self.end(child)
        with self.assertRaises(Conflict):delete_run(self.store,child,0)
        self.end(parent)
        with self.assertRaises(Conflict):delete_run(self.store,parent,0)
        with self.store.edit(child) as run:run['executions'].append({'id':'live','task_id':'initialize','worker_active':'worker','implementation':{'kind':'agent'}})
        with self.assertRaises(Conflict):delete_run(self.store,child,0)
        with self.store.edit(child) as run:run['executions'][0].pop('worker_active')
        with self.assertRaises(Conflict):manage_loop(self.store,key=self.key,delete=True)
        manage_loop(self.store,key=self.key,archived=True)
        self.assertEqual(self.tools.call('list_loops',{})['loops'],[])
        self.assertEqual(self.tools.call('read_loop',{'key':self.key})['loop']['key'],self.key)
        self.assertEqual(self.store.get(child)['loop_key'],self.key)
        delete_run(self.store,child,0);delete_run(self.store,parent,0)
        manage_loop(self.store,key=self.key,delete=True)
        self.assertEqual(self.store.catalog(),[])
        with self.assertRaises(Invalid):self.store.get(parent)

    def test_deleted_collaboration_keeps_result_but_is_no_longer_reconciled(self):
        ident=self.create();self.end(ident)
        with self.store.connection() as db:
            db.execute('CREATE TABLE communication_requests (id TEXT PRIMARY KEY,document TEXT)')
            request={'id':'request-one','state':'running','collaboration':{'run_id':ident,'task_id':'collect'},'result':{'answer':'full answer'}}
            db.execute('INSERT INTO communication_requests VALUES (?,?)',('request-one',json.dumps(request)));db.commit()
        with self.assertRaises(Conflict):delete_run(self.store,ident,0)
        with self.store.connection() as db:
            request['state']='completed';db.execute('UPDATE communication_requests SET document=?',(json.dumps(request),))
            db.execute('CREATE TABLE executor_calls (id TEXT PRIMARY KEY,document TEXT NOT NULL)')
            job={'state':'completed','applied':False,'metadata':{'kind':'communication','request_id':'request-one'}}
            db.execute('INSERT INTO executor_calls VALUES (?,?)',('remote-assistance',json.dumps(job)));db.commit()
        with self.assertRaises(Conflict):delete_run(self.store,ident,0)
        with self.store.connection() as db:
            retained=json.loads(db.execute('SELECT document FROM communication_requests').fetchone()[0])
            self.assertNotIn('deleted',retained['collaboration'])
            job['applied']=True;db.execute('UPDATE executor_calls SET document=?',(json.dumps(job),));db.commit()
        delete_run(self.store,ident,0)
        with self.store.connection() as db:retained=json.loads(db.execute('SELECT document FROM communication_requests').fetchone()[0])
        self.assertTrue(retained['collaboration']['deleted']);self.assertEqual(retained['result'],request['result'])
        from types import SimpleNamespace
        from loop_anything.runtime.collaboration import reconcile
        stale=dict(request,origin='local')
        comm=SimpleNamespace(store=self.store,requests=lambda:[stale],settings=lambda:{'instance_id':'local'},get=lambda ident:retained)
        reconcile(comm)  # An already fetched request must not crash the next reconciliation after deletion.

    def test_legacy_header_is_backfilled_and_draft_management_uses_its_revision(self):
        ident=self.create(name='')
        with self.store.connection() as db:
            db.execute("UPDATE runs SET document=json_remove(document,'$.last_activity_at','$.created_by') WHERE id=?",(ident,));db.commit()
        store=Store(self.store.filename)
        summary=list_runs(store,created_by='')['runs'][0]
        self.assertIsNotNone(summary['last_activity_at']);self.assertEqual(summary['created_by'],'')
        manage_loop(store,draft_id=self.draft['draft_id'],revision=self.draft['revision'],archived=True)
        self.assertEqual(store.drafts(False),[])
        with self.assertRaises(Conflict):manage_loop(store,draft_id=self.draft['draft_id'],revision=999,delete=True)
        manage_loop(store,draft_id=self.draft['draft_id'],revision=self.draft['revision'],delete=True)
        self.assertEqual(store.drafts(),[])

    def test_loop_deletion_keeps_untracked_runtime_files_and_remains_reinstallable(self):
        from loop_anything.packaging.packages import load_installed, make_archive, installed_assets, install
        document,root=load_installed(self.store.filename,self.key)
        raw=make_archive(document,installed_assets(document,root))
        output=root/'artifacts'/'model.bin'
        output.parent.mkdir();output.write_bytes(b'valuable runtime artifact')
        result=manage_loop(self.store,key=self.key,delete=True)
        self.assertEqual(output.read_bytes(),b'valuable runtime artifact')
        self.assertTrue(result['package_files_retained'])
        self.assertEqual(Path(result['retained_package_path']),root)
        self.assertEqual(install(self.store,raw)['key'],self.key)

    def test_loop_deletion_checks_actual_calls_not_parameter_examples(self):
        draft=self.tools.call('create_loop',{'name':'Caller'})
        draft=self.tools.call('set_implementation',{'draft_id':draft['draft_id'],'revision':draft['revision'],
            'node_id':'initialize','kind':'command','command':['unused'],'clear':['lifecycle'],
            'parameter_schema':{'type':'object','properties':{'example':{'type':'object',
                'default':{'kind':'loop','loop':'ordinary business data'}}}}})
        manage_loop(self.store,key=self.key,delete=True)
        # Real references remain protected, both in drafts and published candidates.
        self.key=self.tools.call('publish_loop',{'draft_id':self.draft['draft_id'],'revision':self.draft['revision']})['key']
        draft=self.tools.call('set_implementation',{'draft_id':draft['draft_id'],'revision':draft['revision'],
            'node_id':'initialize','kind':'loop','loop':{'key':self.key},'clear':['command','lifecycle']})
        with self.assertRaises(Conflict):manage_loop(self.store,key=self.key,delete=True)
        draft=self.tools.call('set_loop',{'draft_id':draft['draft_id'],'revision':draft['revision'],'handbook':'Call the child Loop.'})
        caller=self.tools.call('publish_loop',{'draft_id':draft['draft_id'],'revision':draft['revision']})['key']
        manage_loop(self.store,draft_id=draft['draft_id'],revision=draft['revision'],delete=True)
        with self.assertRaises(Conflict):manage_loop(self.store,key=self.key,delete=True)
        manage_loop(self.store,key=caller,delete=True)
        manage_loop(self.store,key=self.key,delete=True)

    def test_delete_waits_for_remote_receipt_application_even_after_worker_flag_clears(self):
        ident=self.create();self.end(ident)
        with self.store.connection() as db:
            db.execute('CREATE TABLE executor_calls (id TEXT PRIMARY KEY,document TEXT NOT NULL)')
            job={'state':'completed','metadata':{'kind':'task','run_id':ident},'applied':False}
            db.execute('INSERT INTO executor_calls VALUES (?,?)',('remote-one',json.dumps(job)));db.commit()
        with self.assertRaises(Conflict):delete_run(self.store,ident,0)
        with self.store.connection() as db:
            job['applied']=True;db.execute('UPDATE executor_calls SET document=?',(json.dumps(job),));db.commit()
        delete_run(self.store,ident,0)

    def test_unpartitioned_history_preserves_activity_and_execution_count(self):
        ident=self.create();old=self.store.get(ident)
        old.pop('last_activity_at',None)
        old['executions']=[{'id':'historic-attempt'}]
        old['history']=[{'id':'done','kind':'committed','at':500},
                        {'id':'poll','kind':'observation','at':900},
                        {'id':'progress','kind':'transition','at':950,'detail':{'from':'waiting','to':'waiting','event':'progress'}}]
        with self.store.connection() as db:
            db.execute('UPDATE runs SET document=? WHERE id=?',(json.dumps(old),ident))
            db.execute('DELETE FROM timeline_parts WHERE run_id=?',(ident,));db.commit()
        migrated=Store(self.store.filename)
        row=list_runs(migrated,active_from=450)['runs'][0]
        self.assertEqual(row['last_activity_at'],500)
        self.assertEqual(row['execution_count'],1)
        # Repair an earlier library version which filled legacy activity with creation time.
        with self.store.connection() as db:
            db.execute("UPDATE runs SET document=json_set(document,'$.last_activity_at',json_extract(document,'$.created_at')) WHERE id=?",(ident,));db.commit()
        self.assertEqual(list_runs(Store(self.store.filename))['runs'][0]['last_activity_at'],500)

    def test_delete_preserves_unconfirmed_native_sessions(self):
        ident=self.create();self.end(ident)
        with self.store.connection() as db:
            db.execute('CREATE TABLE execution_sessions (id TEXT PRIMARY KEY,run_id TEXT,document TEXT NOT NULL)')
            db.execute('INSERT INTO execution_sessions VALUES (?,?,?)',('session-one',ident,json.dumps({'state':'interrupted'})));db.commit()
        with self.assertRaises(Conflict):delete_run(self.store,ident,0)
        with self.store.connection() as db:
            db.execute('UPDATE execution_sessions SET document=?',(json.dumps({'state':'released','native_session':{'id':'retained-native'}}),));db.commit()
        delete_run(self.store,ident,0)
        with self.store.connection() as db:self.assertIn('retained-native',db.execute('SELECT document FROM execution_sessions').fetchone()[0])

    def test_builtin_collaboration_can_be_recreated_after_unused_version_deletion(self):
        from loop_anything.runtime.collaboration import ensure_loop
        key=ensure_loop(self.store)
        manage_loop(self.store,key=key,delete=True)
        self.assertEqual(ensure_loop(self.store),key)
        self.assertTrue(any(row['key']==key for row in self.store.catalog()))

    def test_broken_optional_name_profile_does_not_block_platform_calls(self):
        spec=importlib.util.spec_from_file_location('broken_profile_client','skills/loop-anything-platform/scripts/call.py')
        client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
        profile=Path(self.tmp.name)/'broken-profile.json';profile.write_text('{broken')
        with patch.dict(os.environ,LOOP_ANYTHING_PROFILE=str(profile)),patch('sys.stdout',new_callable=io.StringIO),patch('sys.stderr',new_callable=io.StringIO):
            for tool in ('read_run','start_run'):
                with patch.object(client,'fetch',return_value={'ok':True}) as fetch,patch.object(sys,'argv',['call.py',tool,'--url','http://example.invalid','--arguments','{}']):
                    with self.assertRaises(SystemExit) as done:client.main()
                    self.assertEqual(done.exception.code,0)
                    self.assertNotIn('created_by',json.loads(fetch.call_args.kwargs['data'])['arguments'])

    def test_local_profile_does_not_need_connection_and_new_runs_inherit_it(self):
        path=Path('skills/loop-anything-platform/scripts/call.py')
        spec=importlib.util.spec_from_file_location('run_profile_client',path);client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
        profile=str(Path(self.tmp.name)/'profile.json')
        with patch.dict(os.environ,LOOP_ANYTHING_PROFILE=profile),patch('sys.stdout',new_callable=io.StringIO):
            with patch.object(sys,'argv',['call.py','profile','--name','tdh']):client.main()
            self.assertEqual(json.loads(Path(profile).read_text())['user_name'],'tdh')
            with patch.object(client,'fetch',return_value={'ok':True}) as fetch,patch.object(sys,'argv',['call.py','start_run','--url','http://example.invalid','--arguments','{"key":"test","title":"Run","authorization":"test"}']):
                with self.assertRaises(SystemExit) as done:client.main()
                self.assertEqual(done.exception.code,0)
                payload=json.loads(fetch.call_args.kwargs['data'])
                self.assertEqual(payload['arguments']['created_by'],'tdh')


if __name__=='__main__':unittest.main()
