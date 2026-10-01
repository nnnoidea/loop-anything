"""Results trigger author-defined plans atomically; no author-side task writer."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.store import Store


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'run.db')
        self.engine = Engine(self.store)
        self.platform = PlatformTools(self.store)
        self.draft = self.platform.call('create_loop', {'name': 'Event-driven work'})
        self.edit('set_loop', handbook='Submit experiment parameters; the platform arranges execution and analysis.')
        self.edit('put_node', node_id='initialize', outputs=[{'name':'requests','type':'array'}])
        self.edit('put_node', node_id='evaluate', instructions='Run agreed parameters', inputs=[],
                  outputs=[{'name':'score','type':'number'}])
        self.edit('set_implementation', node_id='evaluate', implementation_id='local', kind='command', default=True,
                  command=[sys.executable,'-c', 'import json,sys;r=json.load(sys.stdin);print(json.dumps({"outputs":{"score":r["parameters"]["batch"]*2}}))'],
                  parameter_schema={'type':'object','properties':{'batch':{'type':'integer'}},'required':['batch']})
        self.edit('put_node', node_id='review', instructions='Decide whether another round is needed',
                  inputs=[{'name':'scores','type':'array'}], outputs=[{'name':'decision','type':'object'}])
        self.edit('set_implementation', node_id='review', kind='agent')
        self.edit('put_step', plan='round', step='evaluate', node_id='evaluate', each='experiments',
                  parameters={'$':'item'}, inputs={})
        self.edit('put_step', plan='round', step='review', node_id='review', after=['evaluate'],
                  inputs={'scores':{'from':'evaluate','port':'score','collect':True}})
        self.route = {'id':'experiments','event':'completed','plan':'round','values':{'experiments':{'$':'outputs.requests'}}}
        self.edit('put_node', node_id='initialize', routes=[self.route])
        self.edit('put_node', node_id='review', routes=[{'id':'next_round','event':'completed','plan':'round',
                  'when':{'path':'outputs.decision.again'}, 'values':{'experiments':{'$':'outputs.decision.requests'}}}])

    def tearDown(self):
        self.engine.close();self.tmp.cleanup()

    def edit(self, tool, **values):
        self.draft = self.platform.call(tool, dict(draft_id=self.draft['draft_id'], revision=self.draft['revision'], **values))
        return self.draft

    def start(self):
        self.assertTrue(self.platform.call('validate_loop', {'draft_id':self.draft['draft_id']})['valid'])
        self.key = self.platform.call('publish_loop', {'draft_id':self.draft['draft_id'],'revision':self.draft['revision']})['key']
        started = self.platform.call('start_run', {'key':self.key,'title':'Parameters only','authorization':'Run the requested work'})
        self.id = started['run_id'];self.task_id=started['entry_task_id']
        self.tools = RunTools(self.store,self.id,started['token'])

    def initial_report(self, requests, **fields):
        info=self.tools.call('read_task',{'task_id':self.task_id})
        settings={'objective':'Two rounds', 'completion_rule':{'op':'and','args':[
            {'op':'ge','args':[{'path':['completed','review']},2]},
            {'op':'eq','args':[{'path':'active_tasks'},0]}]}}
        return dict(task_id=self.task_id,task_version=info['task_version'],report_id='initialize-result',event='completed',
                    envelope={'outputs':{'requests':requests},'settings':settings,**fields})

    def until_review(self):
        for _ in range(200):
            self.engine.tick(self.id)
            for f in list(self.engine.futures):f.result(timeout=5)
            run=self.store.get(self.id)
            self.assertFalse(any(t['status']=='fault' for t in run['tasks'].values()),run['history'][-3:])
            task=next((t for t in run['tasks'].values() if t['spec']['node']=='review' and t['status']=='decision'),None)
            if task:
                e=self.engine.execution(run,task['execution_id'])
                return task,RunTools(self.store,self.id,e['token'])
            time.sleep(.01)
        self.fail('No review task was automatically dispatched')

    def test_parameters_only_generate_two_rounds_with_aggregation_and_restart_dedup(self):
        self.start();args=self.initial_report([{'batch':2},{'batch':3}])
        receipt=self.tools.call('report_task',args)
        self.assertEqual(len(receipt['routes'][0]['batches'][0]['task_ids']),3)
        snapshot=self.store.get(self.id)
        self.assertEqual(len(snapshot['tasks']),4)
        self.assertEqual(self.tools.call('read_task',{'task_id':self.task_id})['routes'],[self.route])
        again=self.tools.call('report_task',args)
        self.assertTrue(again['duplicate']);self.assertEqual(again['routes'],receipt['routes'])
        self.assertEqual(len(self.store.get(self.id)['tasks']),4)
        self.tools.call('finish',{})
        self.engine.close();self.engine=Engine(self.store);self.engine.recover()
        task,tools=self.until_review()
        info=tools.call('read_task',{'task_id':task['id']})
        self.assertEqual(info['inputs']['scores'],[4,6])
        response=tools.call('report_task',{'task_id':task['id'],'task_version':info['task_version'],'event':'completed','report_id':'next',
                                        'envelope':{'outputs':{'decision':{'again':True,'requests':[{'batch':5}]}}}})
        self.assertTrue(response['accepted']);tools.call('finish',{})
        task2,tools2=self.until_review();info2=tools2.call('read_task',{'task_id':task2['id']})
        self.assertEqual(info2['inputs']['scores'],[10])
        tools2.call('report_task',{'task_id':task2['id'],'task_version':info2['task_version'],'event':'completed','report_id':'end',
                                 'envelope':{'outputs':{'decision':{'again':False}}}})
        tools2.call('finish',{});self.engine.tick(self.id)
        run=self.store.get(self.id)
        self.assertEqual(run['status'],'completed')
        self.assertEqual(sum(h['kind']=='route_fired' for h in run['history']),3)
        created=[t for t in run['tasks'].values() if t['origin'].get('route_id')]
        self.assertEqual(len(created),5)
        self.assertTrue(all(t['parent_id'] for t in created))
        self.assertFalse(any(h['kind']=='plan_built' for h in run['history']))

    def test_bad_second_item_and_combined_task_budget_roll_back_completion(self):
        self.edit('set_loop',limits={'max_tasks':4})
        self.start();before=self.store.get(self.id)
        with self.assertRaises(Invalid):self.tools.call('report_task',self.initial_report([{'batch':2},{}]))
        self.assertEqual(self.store.get(self.id),before)
        before=self.store.get(self.id)
        extra={'id':'explicit','node':'evaluate','inputs':{},'parameters':{'batch':1},'outputs':{'score':{'id':'explicit.score'}}}
        with self.assertRaises(Invalid):
            self.tools.call('report_task',self.initial_report([{'batch':2},{'batch':3}],tasks=[extra]))
        self.assertEqual(self.store.get(self.id),before)
        self.assertTrue(self.tools.call('report_task',self.initial_report([{'batch':2}]))['accepted'])

    def test_each_conditional_routes_and_candidate_overrides(self):
        route=dict(self.route,each='outputs.requests',when={'path':'item.enabled'},
                   values={'experiments':{'$':'item.experiments'}},steps={'evaluate':{'implementation':{'$':'item.implementation'}}},round='{item.name}')
        self.edit('put_node',node_id='initialize',routes=[route]);self.start()
        receipt=self.tools.call('report_task',self.initial_report([
            {'enabled':False}, {'enabled':True,'name':'one','experiments':[{'batch':2}],'implementation':'local'},
            {'enabled':True,'name':'two','experiments':[{'batch':4}],'implementation':'local'}]))
        self.assertEqual(receipt['routes'][0]['omitted_items'],[0]);self.assertEqual(len(receipt['routes'][0]['batches']),2)
        tasks=list(self.store.get(self.id)['tasks'].values())[1:]
        self.assertEqual({t['spec']['round'] for t in tasks},{'one','two'})
        self.assertTrue(all(t['spec'].get('implementation')=='local' for t in tasks if t['spec']['node']=='evaluate'))

    def test_custom_event_routes_use_detail_and_rejected_events_do_not_route(self):
        from loop_anything.runtime.lifecycle import template
        matrix=template('agent');matrix['transitions'].append({'from':'executing','event':'proposal','to':'executing'})
        self.edit('set_implementation',node_id='initialize',kind='agent',lifecycle=matrix)
        self.edit('put_node',node_id='initialize',routes=[dict(self.route,event='proposal',values={'experiments':{'$':'detail.requests'}}),
                                                      dict(self.route,id='not_accepted',event='unknown')])
        self.start();info=self.tools.call('read_task',{'task_id':self.task_id})
        args={'task_id':self.task_id,'task_version':info['task_version'],'report_id':'proposal','event':'proposal','detail':{'requests':[{'batch':2}]}}
        result=self.tools.call('report_task',args)
        self.assertTrue(result['accepted']);self.assertEqual(len(self.store.get(self.id)['tasks']),3)
        self.assertTrue(self.tools.call('report_task',args)['duplicate'])
        self.assertFalse(self.store.get(self.id)['records'])
        bad=self.tools.call('report_task',dict(args,report_id='bad',event='unknown'))
        self.assertFalse(bad['accepted']);self.assertEqual(len(self.store.get(self.id)['tasks']),3)

    def test_invalid_declarations_and_referenced_plan_removal(self):
        for routes in [[self.route,self.route],[dict(self.route,plan='missing')],[dict(self.route,values={'$':'token'})],
                       [dict(self.route,when={'path':'records.private'})]]:
            result=self.edit('put_node',node_id='initialize',routes=routes)
            self.assertFalse(result['validation']['valid'])
            self.assertEqual(result['validation']['issues'][0]['path'][:3],['nodes','initialize','routes'])
        self.edit('put_node',node_id='initialize',routes=[self.route])
        # Invalid drafts remain editable; restoration retains a valid author contract.
        self.assertTrue(self.platform.call('validate_loop',{'draft_id':self.draft['draft_id']})['valid'])
        self.edit('remove_step',plan='round',step='review')
        with self.assertRaisesRegex(Invalid,'route'):
            self.edit('remove_step',plan='round',step='evaluate')

    def test_script_timer_and_event_reports_share_routing_and_rejections_are_atomic(self):
        self.edit('put_node',node_id='wait',instructions='Wait for parameters',outputs=[{'name':'requests','type':'array'}])
        self.edit('set_implementation',node_id='wait',kind='event',event='experiment',wait={'key':'experiment'})
        self.edit('put_node',node_id='wait',routes=[self.route])
        self.edit('put_step',plan='listen',step='wait',node_id='wait',inputs={})
        self.edit('put_node',node_id='initialize',routes=[dict(self.route,plan='listen',values={})])
        self.start();self.tools.call('report_task',self.initial_report([]));self.tools.call('finish',{})
        self.engine.tick(self.id)
        wait=next(t for t in self.store.get(self.id)['tasks'].values() if t['spec']['node']=='wait')
        user=RunTools(self.store,self.id)
        user.call('send_event',{'event_id':'bad','name':'experiment','key':'experiment','payload':{'requests':[{'batch':2},{}]}})
        self.engine.tick(self.id)
        run=self.store.get(self.id)
        self.assertEqual(len(run['tasks']),2)
        self.assertFalse(any(k.startswith(wait['id']) for k in run['records']))
        self.assertEqual(run['tasks'][wait['id']]['status'],'waiting')
        user.call('send_event',{'event_id':'good','name':'experiment','key':'experiment','payload':{'requests':[{'batch':2}]}})
        self.engine.tick(self.id)
        run=self.store.get(self.id)
        self.assertEqual(run['tasks'][wait['id']]['status'],'completed');self.assertEqual(len(run['tasks']),4)
        self.assertEqual(sum(h['kind']=='route_fired' and h['detail']['task_id']==wait['id'] for h in run['history']),1)
        # A real command completion triggers a timer task through the same writer.
        # Use another isolated Run with the revised definition; the old Run stays pinned.
        self.edit('put_node',node_id='wait',routes=[],outputs=[])
        self.edit('set_implementation',node_id='wait',kind='timer',wait={'seconds':0},clear=['event','lifecycle'])
        self.edit('put_node',node_id='evaluate',routes=[{'id':'clock','event':'completed','plan':'listen','values':{}}])
        self.edit('put_node',node_id='wait',routes=[{'id':'after_clock','event':'completed','plan':'review_only',
                                                  'values':{'score':{'$':'parameters.score'}}}])
        self.edit('put_step',plan='listen',step='wait',node_id='wait',inputs={},parameters={'score':4})
        self.edit('put_step',plan='review_only',step='review',node_id='review',inputs={'scores':{'literal':[{'$':'values.score'}]}})
        self.edit('put_node',node_id='initialize',routes=[self.route]);self.start()
        self.tools.call('report_task',self.initial_report([{'batch':2}]));self.tools.call('finish',{})
        for _ in range(8):
            self.engine.tick(self.id)
            for f in list(self.engine.futures):f.result(timeout=5)
        run=self.store.get(self.id)
        self.assertTrue(any(t['status']=='completed' and t['spec']['node']=='wait' for t in run['tasks'].values()))
        self.assertEqual({h['detail']['route_id'] for h in run['history'] if h['kind']=='route_fired'}, {'experiments','clock','after_clock'})
        self.assertEqual(len(run['tasks']),5)

    def test_invalid_engine_error_route_becomes_visible_fault_and_stale_report_never_routes(self):
        self.edit('put_node',node_id='evaluate',routes=[dict(self.route,event='process_error',values={'experiments':{'$':'detail.missing'}})])
        self.edit('set_implementation',node_id='evaluate',implementation_id='local',command=[sys.executable,'-c','raise SystemExit(1)'])
        self.start();args=self.initial_report([{'batch':2}]);self.tools.call('report_task',args);self.tools.call('finish',{})
        for _ in range(4):
            self.engine.tick(self.id)
            for f in list(self.engine.futures):f.result(timeout=5)
        run=self.store.get(self.id)
        failed=next(e for e in run['executions'] if e['node']=='evaluate')
        self.assertEqual(failed['status'],'fault');self.assertIn('Route experiments',failed['error'])
        self.assertEqual(len(run['tasks']),3)
        # Stale reports are rejected before any event plan can be expanded.
        with self.assertRaises(Conflict), self.store.edit(self.id) as current:
            result=self.engine.timeline_runtime.report_in_run(current,self.engine.execution(current,failed['id']),
                {'event':'process_error','report_id':'stale','detail':{'missing':[{'batch':9}]}},'engine',stale=True)
        self.assertEqual(len(self.store.get(self.id)['tasks']),3)
        with self.store.edit(self.id) as current:
            receipt=self.engine.timeline_runtime.report_in_run(current,self.engine.execution(current,failed['id']),
                {'event':'process_error','report_id':'late-monitor','detail':{'missing':[{'batch':9}]}},'monitor',stale=True)
            self.assertFalse(receipt['accepted']);self.assertTrue(receipt['stale'])
        self.assertEqual(len(self.store.get(self.id)['tasks']),3)

    def test_later_route_failure_rolls_back_earlier_route_and_result(self):
        self.edit('put_node',node_id='initialize',routes=[self.route,dict(self.route,id='invalid',values={'experiments':[{}]})])
        self.start();before=self.store.get(self.id)
        with self.assertRaisesRegex(Invalid,'Route invalid'):
            self.tools.call('report_task',self.initial_report([{'batch':2}]))
        self.assertEqual(self.store.get(self.id),before)
