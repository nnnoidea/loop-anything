"""Cases that exposed the semantic gaps, using actual runtime writes and scheduling."""
import copy
import sys
import unittest

import tests.test_steward as fixture
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.steward import expose_requests
from loop_anything.packaging.configuration import apply


class StewardRegressionTests(unittest.TestCase):
    def setUp(self):
        self.t = fixture.StewardTests();self.t.setUp();self.addCleanup(self.t.doCleanups)

    def test_takeover_revokes_completed_owner_but_preserves_evidence(self):
        t=self.t;request,old=t.initialized_start()
        t.complete(old,request['task_id'],{'decision':'Startup complete'})
        before=t.store.get(t.run_id)
        t.tools.call('assign_run_steward',{'run_id':t.run_id,'steward_id':'second','generation':1})
        with self.assertRaises(Conflict):old.call('read_timeline',{})
        saved=t.store.get(t.run_id)
        self.assertEqual(saved['tasks'][request['task_id']]['status'],'completed')
        self.assertEqual(saved['records'],before['records'])
        # The shared identity boundary also rejects a stale owner accidentally retained by a future caller.
        with t.store.edit(t.run_id) as run:run['agent_sessions'].extend(before['agent_sessions'])
        with self.assertRaises(Conflict):old.call('read_timeline',{})

    def test_business_created_successors_wait_but_manager_created_parallel_work_runs(self):
        t=self.t
        t.edit('set_implementation',node_id='work',kind='agent',clear=['lifecycle','event','wait'],command=[sys.executable,'-c','pass'])
        t.republish();request,manager=t.initialized_start()
        manager.call('read_timeline',{})
        source=manager.call('add_task',{'key':'source','node_id':'work','inputs':{}})['tasks'][0]['id']
        independent=manager.call('add_task',{'key':'independent','node_id':'fixed','inputs':{},'parent_id':source})['tasks'][0]['id']
        t.finish_start(request,manager);worker=t.worker(source)
        worker.call('read_timeline',{})
        early=worker.call('add_task',{'key':'early-child','node_id':'fixed','inputs':{}})['tasks'][0]['id']
        t.tick_without_cli()
        self.assertIsNone(t.store.get(t.run_id)['tasks'][early]['execution_id'])
        self.assertIsNotNone(t.store.get(t.run_id)['tasks'][independent]['execution_id'])
        worker.call('read_timeline',{})
        t.complete(worker,source,{'result':{}},tasks=[{'id':'reported-child','node':'fixed','inputs':{},'outputs':{}}])
        worker.call('finish',{});t.tick_without_cli()
        run=t.store.get(t.run_id)
        decision=next(r for r in run['steward_requests'].values() if r['operation']=='decide')
        for ident in (early,'reported-child'):
            self.assertIsNone(run['tasks'][ident]['execution_id'])
            self.assertEqual(run['tasks'][ident]['wait_reasons'][0]['reason'],'steward_decision')
        manager=t.worker(decision['task_id'])
        t.complete(manager,decision['task_id'],{'decision':'Reviewed both successors'});manager.call('finish',{})
        t.tick_without_cli()
        self.assertTrue(all(t.store.get(t.run_id)['tasks'][i]['execution_id'] for i in (early,'reported-child')))

    def test_explicit_rules_keep_script_arranged_work_automatic(self):
        t=self.t;t.edit('put_node',node_id='work',progression='rules')
        t.edit('set_implementation',node_id='work',kind='agent',clear=['lifecycle','event','wait'],command=[sys.executable,'-c','pass'])
        t.republish();request,manager=t.initialized_start();manager.call('read_timeline',{})
        source=manager.call('add_task',{'key':'source','node_id':'work','inputs':{}})['tasks'][0]['id']
        t.finish_start(request,manager);worker=t.worker(source)
        t.complete(worker,source,{'result':{}},tasks=[{'id':'fixed-child','node':'fixed','inputs':{},'outputs':{}}])
        worker.call('finish',{});t.tick_without_cli()
        self.assertIsNotNone(t.store.get(t.run_id)['tasks']['fixed-child']['execution_id'])
        self.assertFalse(any(r['operation']=='decide' for r in t.store.get(t.run_id)['steward_requests'].values()))

    def test_script_entry_arrangements_wait_for_startup_steward_review(self):
        t=self.t
        import json
        envelope={'settings':{'objective':'Script initialization'},'outputs':{},
                  'tasks':[{'id':'initial-child','node':'fixed','inputs':{},'outputs':{}}]}
        t.edit('put_node',node_id='initialize',plan_nodes=['fixed'])
        t.edit('set_implementation',node_id='initialize',kind='command',clear=['lifecycle'],
               command=[sys.executable,'-c','print('+repr(json.dumps({'event':'completed','envelope':envelope}))+')'])
        t.republish();request=t.start();t.engine.tick(t.run_id)
        for future in list(t.engine.futures):future.result(timeout=5)
        manager=t.worker(request['task_id'])
        self.assertIsNone(t.store.get(t.run_id)['tasks']['initial-child']['execution_id'])
        t.complete(manager,request['task_id'],{'decision':'Initial work reviewed'});manager.call('finish',{})
        t.tick_without_cli();self.assertIsNotNone(t.store.get(t.run_id)['tasks']['initial-child']['execution_id'])

    def test_withdrawn_decision_can_be_explicitly_reopened_with_original_evidence(self):
        t=self.t;request,manager=t.initialized_start();manager.call('read_timeline',{})
        source=manager.call('add_task',{'key':'source','node_id':'work','inputs':{}})['tasks'][0]['id']
        follow=manager.call('add_task',{'key':'follow','node_id':'fixed','inputs':{},'after':[source]})['tasks'][0]['id']
        t.finish_start(request,manager);t.tick_without_cli()
        from loop_anything.runtime.notifications import receive_event
        with t.store.edit(t.run_id) as run:receive_event(run,'ready','ready',{'result':{'score':3}},'evidence')
        t.tick_without_cli();run=t.store.get(t.run_id)
        decision=next(r for r in run['steward_requests'].values() if r['operation']=='decide')
        t.tools.call('reply_run_request',{'request_id':decision['id'],'reply_id':'withdraw','message':'Wait','cancel':True})
        t.tick_without_cli();self.assertIsNone(t.store.get(t.run_id)['tasks'][follow]['execution_id'])
        resumed=t.tools.call('reply_run_request',{'request_id':decision['id'],'reply_id':'resume','message':'Review and continue'})
        manager=t.worker(resumed['task_id']);info=manager.call('read_task',{'task_id':resumed['task_id']})
        self.assertEqual(info['flow_trigger']['event'],'completed')
        self.assertEqual(info['flow_trigger']['records'],decision['arguments']['records'])
        t.complete(manager,resumed['task_id'],{'decision':'Continue'});manager.call('finish',{})
        t.tick_without_cli();self.assertIsNotNone(t.store.get(t.run_id)['tasks'][follow]['execution_id'])

    def test_removed_configuration_and_call_surfaces_reject_explicitly(self):
        t=self.t
        with self.assertRaises(Invalid):t.edit('set_loop',flow_agent={'kind':'agent','command':['old']})
        doc=t.tools.call('read_loop',{'key':t.key})['loop']
        with self.assertRaises(Invalid):apply(doc,{'flow_agent':{}})
        names={d['name'] for d in t.tools.definitions()}
        self.assertFalse(names & {'acquire_run','update_run','delete_run','retry_notification'})

    def test_effective_status_is_shared_by_receipt_run_view_and_timeline(self):
        t=self.t;request=t.start();worker=t.worker(request['task_id'])
        response=t.tools.call('read_run_request',{'request_id':'startup'})
        self.assertEqual(response['status'],'processing')
        with t.store.edit(t.run_id) as run:
            run['tasks'][request['task_id']]['status']='fault'
            next(e for e in run['executions'] if e['task_id']==request['task_id'])['error']='Failed to run'
        effective=t.tools.call('read_run_request',{'request_id':'startup'})
        self.assertEqual(effective['status'],'failed')
        viewed=expose_requests(t.store.get(t.run_id))['steward_requests']['startup']
        self.assertEqual(viewed['status'],effective['status']);self.assertEqual(viewed['error'],effective['error'])
        self.assertEqual(t.tools.call('read_timeline',{'run_id':t.run_id})['requests'][0]['status'],'failed')

    def test_library_writes_have_durable_delete_receipts_and_no_read_snapshots(self):
        t=self.t;request,manager=t.initialized_start();t.finish_start(request,manager)
        def send(ident,op,args):return t.tools.call('submit_run_request',{'request_id':ident,'run_id':t.run_id,'operation':op,'arguments':args})
        updated=send('rename','update_run',{'metadata_revision':0,'title':'Renamed'})
        self.assertEqual(updated['result']['title'],'Renamed')
        before=copy.deepcopy(t.store.get(t.run_id)['steward_requests'])
        for _ in range(3):t.tools.call('read_run',{'run_id':t.run_id})
        self.assertEqual(before,t.store.get(t.run_id)['steward_requests'])
        with self.assertRaises(Invalid):send('read-copy','read_run',{})
        send('end','command',{'action':'terminate'})
        first=send('delete','delete_run',{'metadata_revision':1})
        self.assertTrue(first['result']['deleted'])
        self.assertEqual(send('delete','delete_run',{'metadata_revision':1}),first)
        self.assertEqual(t.tools.call('read_run_request',{'request_id':'delete'}),first)
        self.assertEqual(t.store.list(),[])
