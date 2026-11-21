"""Public Run startup and explicit, evidence-bearing routing decisions."""
import sys
import unittest
from pathlib import Path
from tests import test_work_context as fixture
from loop_anything.runtime.model import Invalid


class BuiltinFlowTests(unittest.TestCase):
    def setUp(self):
        c=fixture.WorkContextTests()
        c.setUp()
        self.addCleanup(c.doCleanups)
        self.c=c
        self.draft=c.tools.call('copy_loop',{'key':c.key,'new_version':True})

    def edit(self,tool,**args):
        self.draft=self.c.tools.call(tool,dict(draft_id=self.draft['draft_id'],revision=self.draft['revision'],**args))

    def run_route(self,implementation,when=None):
        c=self.c
        self.edit('set_loop',flow_agent=implementation)
        route={'id':'review','event':'completed','flow_agent':True}
        if when:route['when']=when
        self.edit('put_node',node_id='work',routes=[route])
        key=c.tools.call('publish_loop',{'draft_id':self.draft['draft_id'],'revision':self.draft['revision']})['key']
        start=c.tools.call('start_run',{'key':key,'title':'Route evidence','request_id':'start'})
        self.assertNotIn('starter_session_id',c.store.get(start['run_id']))
        c.initialize(start)
        c.engine.tick(start['run_id'])
        c.engine.event(start['run_id'],'fact','result',{'value':'scored'})
        c.engine.tick(start['run_id'])
        for job in list(c.engine.futures):job.result(timeout=15)
        return c.store.get(start['run_id'])

    def test_unmatched_route_creates_no_decision(self):
        run=self.run_route({'kind':'agent'},when={'op':'eq','args':[1,2]})
        self.assertEqual(len(run['tasks']),1)
        self.assertFalse(any(h['kind']=='route_fired' for h in run['history']))
        skipped = next(h for h in run['history'] if h['kind']=='route_skipped')
        view = self.c.tools.call('read_task',{'run_id':run['id'],'task_id':skipped['detail']['task_id']})
        self.assertEqual(view['route_receipts'][0]['status'],'skipped')
        self.assertEqual(view['flow_decisions'],[])

    def test_invalid_route_requires_configured_agent(self):
        self.edit('put_node',node_id='work',routes=[{'id':'review','event':'completed','flow_agent':True}])
        with self.assertRaises(Invalid):
            self.c.tools.call('publish_loop',dict(draft_id=self.draft['draft_id'],revision=self.draft['revision']))

    def test_hot_update_preserves_route_on_inflight_task(self):
        c=self.c
        self.edit('set_loop',flow_agent={'kind':'agent'})
        self.edit('put_node',node_id='work',routes=[{'id':'review','event':'completed','flow_agent':True}])
        key=c.tools.call('publish_loop',dict(draft_id=self.draft['draft_id'],revision=self.draft['revision']))['key']
        start=c.tools.call('start_run',dict(key=key,title='Pending decision',request_id='v1'))
        c.initialize(start)
        rid=start['run_id']
        c.engine.tick(rid)
        self.draft=c.tools.call('copy_loop',dict(key=key,new_version=True))
        self.edit('put_node',node_id='work',routes=[])
        self.edit('set_loop',flow_agent=None)
        new=c.tools.call('publish_loop',dict(draft_id=self.draft['draft_id'],revision=self.draft['revision']))['key']
        owner=c.tools.call('acquire_run',dict(run_id=rid))
        c.tools.call('update_run_method',dict(run_id=rid,key=new,token=owner['token']))
        from loop_anything.interfaces.agent_tasks import RunTools
        RunTools(c.store,rid,owner['token']).call('finish',{})
        c.engine.event(rid,'score','result',{'value':'ready'})
        c.engine.tick(rid)
        run=c.store.get(rid)
        decision=next(t for t in run['tasks'].values() if t['origin'].get('flow_agent'))
        self.assertEqual(decision['status'],'decision')
        scope=c.tools.call('acquire_run',dict(run_id=rid,task_id=decision['id']))
        self.assertIsNone(scope['scope_task'])

    def test_real_cli_receives_evidence_and_finishes(self):
        code='''import json,sys
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime.store import Store
c=json.loads(sys.stdin.read().split('Run context:'+chr(10),1)[1])
assert c['flow_trigger']['event']=='completed'
t=RunTools(Store(sys.argv[1]),c['run_id'],c['token'])
print(json.dumps({'type':'thread.started','thread_id':'builtin-real-cli-session'}),flush=True)
i=t.call('read_task',{'task_id':c['task_id']});r=i['inputs']['trigger']['records']['value']
v=t.call('read_record',{'id':r['record'],'revision':r['revision']})['record']['value']
t.call('report_task',{'task_id':c['task_id'],'event':'completed','report_id':'cli-result','envelope':{'outputs':{'decision':{'evidence':v,'answer':'complete answer'*500}}}})
t.call('finish',{})
'''
        run=self.run_route({'kind':'agent','command':[sys.executable,'-c',code,self.c.store.filename],
                            'agent_cli':'codex','cwd':str(Path(__file__).resolve().parents[1])})
        decisions=[e for e in run['executions'] if e['node']=='$flow_agent']
        self.assertEqual(len(decisions),1)
        events = [h for h in run['history'] if h['kind']=='route_fired']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['detail']['status'],'fired')
        self.assertEqual(events[0]['detail']['batches'][0]['task_ids'],[decisions[0]['task_id']])
        decision=decisions[0]
        self.assertEqual(decision['status'],'completed',decision.get('error'))
        self.assertEqual(decision['outputs']['decision']['evidence'],'scored')
        self.assertEqual(decision['native_session']['id'],'builtin-real-cli-session')
