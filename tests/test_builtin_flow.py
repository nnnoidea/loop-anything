"""Explicit decision routes use the Run steward and retain native execution evidence."""
import sys
import unittest
from pathlib import Path

import tests.test_steward as fixture
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.notifications import receive_event


class BuiltinFlowTests(unittest.TestCase):
    def setUp(self):
        self.t=fixture.StewardTests();self.t.setUp();self.addCleanup(self.t.doCleanups)
        self.t.edit('put_node',node_id='work',progression='rules',routes=[{'id':'review','event':'completed','flow_agent':True}])
        self.t.republish()

    def prepare(self):
        t=self.t;request,worker=t.initialized_start();worker.call('read_timeline',{})
        source=worker.call('add_task',{'key':'source','node_id':'work','inputs':{}})['tasks'][0]['id']
        t.finish_start(request,worker);t.tick_without_cli()
        return source

    def signal(self):
        with self.t.store.edit(self.t.run_id) as run:
            receive_event(run,'result','ready',{'result':{'score':42}},'evidence')

    def test_declared_decision_has_exact_evidence_and_full_results_without_business_node(self):
        t=self.t;source=self.prepare();self.signal();t.tick_without_cli()
        run=t.store.get(t.run_id)
        request=next(r for r in run['steward_requests'].values() if r['operation']=='decide')
        worker=t.worker(request['task_id']);info=worker.call('read_task',{'task_id':request['task_id']})
        ref=info['flow_trigger']['records']['result']
        self.assertEqual(worker.call('read_record',{'id':ref['record'],'revision':ref['revision']})['record']['value'],{'score':42})
        answer={'full_answer':'Evidence and reasoning. '*500}
        t.complete(worker,request['task_id'],{'decision':answer});worker.call('finish',{})
        t.tick_without_cli()
        self.assertEqual(t.tools.call('read_run_request',{'request_id':request['id']})['result'],answer)
        self.assertEqual(len([r for r in t.store.get(t.run_id)['steward_requests'].values() if r['operation']=='decide']),1)
        authored=t.tools.call('read_loop',{'key':t.key})['loop']['loop_definition']
        self.assertNotIn('$flow_agent',authored['nodes']);self.assertNotIn('flow_agent',authored)
        self.assertEqual(info['flow_trigger']['task_id'],source)

    def test_false_explicit_condition_does_not_fall_back_to_default_decision(self):
        t=self.t;t.edit('put_node',node_id='work',progression='rules',routes=[{'id':'review','event':'completed','flow_agent':True,'when':{'op':'eq','args':[1,2]}}])
        t.republish();self.prepare();self.signal();t.tick_without_cli()
        self.assertFalse(any(r['operation']=='decide' for r in t.store.get(t.run_id)['steward_requests'].values()))

    def test_invalid_report_is_atomic_and_rule_agent_mixing_is_validated(self):
        t=self.t
        with self.assertRaises(Invalid):t.edit('put_node',node_id='work',routes=[{'id':'bad','event':'completed','flow_agent':True,'plan':'extra','values':{}}])
        request,worker=t.initialized_start()
        before=t.store.get(t.run_id)
        with self.assertRaises(Invalid):t.complete(worker,request['task_id'],{'not_decision':'bad'})
        after=t.store.get(t.run_id)
        for field in ('tasks','executions','records','steward_requests'):
            self.assertEqual(after[field],before[field])

    def test_real_cli_receives_trigger_and_preserves_full_result_and_native_session(self):
        t=self.t
        code='''import json,sys
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime.store import Store
c=json.loads(sys.stdin.read().split('Run context:'+chr(10),1)[1])
assert c['flow_trigger']['event']=='completed'
t=RunTools(Store(sys.argv[1]),c['run_id'],c['token'])
print(json.dumps({'type':'thread.started','thread_id':'builtin-real-cli-session'}),flush=True)
i=t.call('read_task',{'task_id':c['task_id']});r=i['inputs']['trigger']['records']['result']
v=t.call('read_record',{'id':r['record'],'revision':r['revision']})['record']['value']
t.call('report_task',{'task_id':c['task_id'],'event':'completed','report_id':'cli-result','envelope':{'outputs':{'decision':{'evidence':v,'answer':'complete answer'*500}}}})
t.call('finish',{})
'''
        t.tools.call('communication_config',{'operation':'agent','agent_id':'first','agent':{'implementation':{
            'kind':'agent','agent_cli':'codex','cwd':str(Path(__file__).resolve().parents[1]),
            'command':[sys.executable,'-u','-c',code,t.store.filename]}}})
        source=self.prepare();self.signal();t.engine.tick(t.run_id)
        for future in list(t.engine.futures):future.result(timeout=10)
        run=t.store.get(t.run_id)
        task=next(x for x in run['tasks'].values() if x['origin'].get('flow_agent',{}).get('task_id')==source)
        execution=next(e for e in run['executions'] if e['id']==task['execution_id'])
        self.assertEqual(execution['status'],'completed',execution.get('error'))
        self.assertEqual(execution['native_session']['id'],'builtin-real-cli-session')
        self.assertEqual(execution['outputs']['decision'],{'evidence':{'score':42},'answer':'complete answer'*500})
