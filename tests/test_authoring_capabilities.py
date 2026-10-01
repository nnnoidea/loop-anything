import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime.store import Store
from loop_anything.runtime.model import Invalid, contract, check_schema
from loop_anything.packaging.packages import make_archive, read_archive
from loop_anything.capabilities import discover


def equal(path,value):return {'op':'eq','args':[{'path':path},value]}


class AuthoringCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'run.db');self.tools=PlatformTools(self.store)
        self.draft=self.tools.call('create_loop',{'name':'Selective batch review'})
        self.edit('set_loop',handbook='Submit parameters, let declared routes arrange tasks.')
        self.edit('put_node',node_id='initialize',outputs=[{'name':'jobs','type':'array'},{'name':'groups','type':'array'}])
        self.edit('put_node',node_id='work',instructions='Execute chosen parameters',inputs=[],outputs=[{'name':'result','type':'number'}])
        self.schema={'type':'object','properties':{'value':{'type':'integer'},'mode':{'enum':['a','b']},'source':{'type':'string'},'template':{'type':'string'}},
                     'required':['value','mode'],'if':{'properties':{'mode':{'const':'a'}},'required':['mode']},'then':{'required':['source']},
                     'else':{'required':['template']},'additionalProperties':False}
        self.edit('set_implementation',node_id='work',kind='command',command=['must-never-run-scenario'],parameter_schema=self.schema)
        self.edit('put_node',node_id='review',instructions='Review selected work',inputs=[{'name':'results','type':'array'}],outputs=[{'name':'done','type':'boolean'}])
        self.edit('set_implementation',node_id='review',kind='agent')
        self.edit('put_step',plan='work',step='work',node_id='work',inputs={},each='jobs',parameters={'$':'item.params'},ref='work:{item.id}')
        self.edit('put_step',plan='review',step='review',node_id='review',inputs={'results':{'task_refs':{'$':'values.members'},'port':'result'}},
                  after_refs={'$':'values.members'},ref='review:{values.id}')
        self.routes=[{'id':'work','event':'completed','plan':'work','values':{'jobs':{'$':'outputs.jobs'}}},
                     {'id':'review','event':'completed','plan':'review','each':'outputs.groups','values':{'$':'item'}}]
        self.edit('put_node',node_id='initialize',routes=self.routes)

    def tearDown(self):self.tmp.cleanup()
    def edit(self,name,**args):
        self.draft=self.tools.call(name,dict(draft_id=self.draft['draft_id'],revision=self.draft['revision'],**args));return self.draft
    def target(self,**args):return dict(draft_id=self.draft['draft_id'],**args)
    def report(self):
        return {'event':'completed','report_id':'initial','envelope':{'settings':{'objective':'Review A and C',
             'completion_rule':{'op':'and','args':[equal('active_tasks',0),equal(['completed','review'],1)]}},
             'outputs':{'jobs':[{'id':v,'params':{'value':i,'mode':'a','source':'input'}} for i,v in enumerate(['A','B','C'])],
                        'groups':[{'id':'chosen','members':['work:A','work:C']}]}}}
    def scenario(self):
        return {'name':'selected group','steps':[
            {'node':'initialize','report':self.report(),'duplicate':True},
            *[{'ref':'work:'+v,'report':{'event':'completed','envelope':{'outputs':{'result':i}}}} for i,v in enumerate(['A','B','C'])],
            {'ref':'review:chosen','report':{'event':'completed','envelope':{'outputs':{'done':True}}}}],
            'assertions':[{'message':'Run ended','test':equal('status','completed')},
                          {'message':'Exactly one initializer, three work and one review','test':equal('task_count',5)},
                          {'message':'Selected results preserve order','test':equal(['by_ref','review:chosen','resolved_inputs','results'],[0,2])}]}

    def test_agent_discovery_to_saved_scenario_to_real_refs_without_side_effects(self):
        guide=self.tools.call('read_capabilities',{'capability':'scenarios'})
        self.assertIn('test_loop',guide['guide']['scenarios']['tools'])
        self.edit('set_loop',scenarios=[self.scenario()])
        before=self.store.drafts();runs=self.store.list()
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=AssertionError('No external command in scenario')):
            result=self.tools.call('test_loop',self.target())
        self.assertTrue(result['passed'],result);self.assertTrue(result['simulated'])
        self.assertEqual(self.store.drafts(),before);self.assertEqual(self.store.list(),runs)
        state=result['scenarios'][0]['state'];review=state['by_ref']['review:chosen']
        self.assertEqual(review['after'],[state['by_ref']['work:A']['id'],state['by_ref']['work:C']['id']])
        self.assertNotIn('token',json.dumps(result));self.assertNotIn('must-never-run',json.dumps(result))
        key=self.tools.call('publish_loop',self.target(revision=self.draft['revision']))['key']
        started=self.tools.call('start_run',{'key':key,'title':'Verify refs','authorization':'Only create tasks'})
        owner=RunTools(self.store,started['run_id'],started['token']);info=owner.call('read_task',{'task_id':started['entry_task_id']})
        owner.call('report_task',dict(self.report(),task_id=started['entry_task_id'],task_version=info['task_version']))
        refs=owner.call('resolve_refs',{'refs':['work:A','review:chosen']})['references']
        self.assertEqual(refs['work:A']['node'],'work')
        preview=owner.call('edit_tasks',{'revision':self.store.get(started['run_id'])['revision'],'preview':True,'changes':[
            {'tool':'add_task','arguments':{'key':'later','node_id':'review','ref':'review:later','after_refs':['work:A'],
                                          'inputs':{'results':{'task_refs':['work:A'],'port':'result'}}}}]})
        self.assertEqual(preview['changes'][0]['after']['spec']['after'],[refs['work:A']['task_id']])

    def test_schema_conditions_composition_unknown_keywords_and_preview(self):
        result=self.tools.call('validate_parameters',self.target(node_id='work',parameters={'value':3,'mode':'a'}))
        self.assertFalse(result['valid']);self.assertIn('source',result['errors'][0])
        good={'value':3,'mode':'b','template':'T'}
        self.assertTrue(self.tools.call('validate_parameters',self.target(node_id='work',parameters=good))['valid'])
        original=copy.deepcopy(good);contract(good,self.schema);self.assertEqual(good,original)
        for bad in ({'value':False,'mode':'b','template':'T'},dict(good,extra=True),{'value':3,'mode':'b'}):
            with self.assertRaises(Invalid):contract(bad,self.schema)
        union={'type':['array','string'],'oneOf':[{'type':'string','minLength':2},{'type':'array','items':{'type':'integer'}}]}
        check_schema(union);contract('ok',union);contract([1,2],union)
        with self.assertRaises(Invalid):contract([True],union)
        for bad in ({'type':'object','requred':['x']},{'type':'object','if':{'properties':{'x':{'wat':1}}}},{'type':'string','pattern':'['}):
            with self.assertRaises(Invalid):check_schema(bad)
        condition={'type':'object','oneOf':[{'required':['preset']},{'required':['template']}],'dependentRequired':{'path':['format']}}
        check_schema(condition);contract({'preset':'p'},condition)
        for value in ({},{'preset':'p','template':'t'},{'preset':'p','path':'x'}):
            with self.assertRaises(Invalid):contract(value,condition)
        with self.assertRaises(Invalid):contract({'flag':True},{'properties':{'flag':{'const':1}}})
        with self.assertRaises(Invalid):contract({'v':'bad'},{'additionalProperties':{'type':'integer'}})
        before=self.store.list()
        p=self.tools.call('preview_plan',self.target(name='work',batch_key='demo',values={'jobs':[{'id':'A','params':good}]}))
        self.assertEqual(p['tasks'][0]['parameters'],good);self.assertIn('work:A',p['references']);self.assertEqual(self.store.list(),before)
        with self.assertRaises(Invalid):self.tools.call('preview_plan',self.target(name='work',batch_key='bad',values={'jobs':[{'id':'A','params':{'value':1,'mode':'a'}}]}))

    def test_missing_duplicate_and_forward_refs_and_failed_assertions(self):
        case=self.scenario();case['steps'][0]['report']['envelope']['outputs']['groups'][0]['members']=['work:missing']
        result=self.tools.call('test_loop',self.target(scenarios=[case]))
        self.assertFalse(result['passed']);self.assertIn('Unknown Task ref',result['scenarios'][0]['error']);self.assertEqual(result['scenarios'][0]['state']['task_count'],1)
        case=self.scenario();case['steps'][0]['report']['envelope']['outputs']['jobs'][1]['id']='A'
        result=self.tools.call('test_loop',self.target(scenarios=[case]));self.assertFalse(result['passed']);self.assertIn('Duplicate Task ref',result['scenarios'][0]['error'])
        self.edit('put_node',node_id='initialize',routes=list(reversed(self.routes)))
        self.assertTrue(self.tools.call('test_loop',self.target(scenarios=[self.scenario()]))['passed'])
        case=self.scenario();case['assertions'][0]['test']=equal('status','paused')
        result=self.tools.call('test_loop',self.target(scenarios=[case]));self.assertFalse(result['passed']);self.assertFalse(result['scenarios'][0]['assertions'][0]['passed'])

    def test_package_requirements_and_unknown_service_capability(self):
        document=self.tools.call('read_loop',self.target())['loop']
        archive=make_archive({k:document[k] for k in ('loop_definition','implementations')})
        manifest=read_archive(archive)[0]
        self.assertEqual(manifest['format'],'loop-anything-package/2')
        self.assertTrue({'event_routes','task_refs','conditional_contracts'} <= set(manifest['requires']))
        # Unknown requirements fail import before installation, even with intact asset hashes.
        manifest['requires'].append('future-capability')
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('loop.json',json.dumps(manifest))
        with self.assertRaisesRegex(Invalid,'future-capability'):read_archive(buf.getvalue())
        self.edit('set_loop',requires=['future-capability'])
        self.assertFalse(self.tools.call('validate_loop',self.target())['valid'])
        self.assertIn('future-capability',str(self.draft['validation']))

    def test_external_monitor_reports_retry_original_task_and_keep_other_results(self):
        from loop_anything.runtime.lifecycle import template
        matrix=template('external')
        for rule in matrix['transitions']:
            if rule['event']=='failed':rule['to']='retry'
        self.edit('set_implementation',node_id='work',kind='external',command=['no-submit'],observe=['no-observe'],lifecycle=matrix)
        case=self.scenario();steps=[case['steps'][0]]
        for i,key in enumerate(['A','B','C']):
            steps.append({'ref':'work:'+key,'report':{'event':'submitted','external_id':'external-'+key}})
            if key=='A':
                steps.append({'ref':'work:A','report':{'event':'failed','detail':{'message':'temporary'}}})
                steps.append({'ref':'work:A','report':{'event':'submitted','external_id':'replacement-A'},'attempt':2})
            steps.append({'ref':'work:'+key,'report':{'event':'completed','envelope':{'outputs':{'result':i}}},'duplicate':True})
        case['steps']=steps+[case['steps'][-1]]
        case['assertions'].append({'message':'Retry used original Task','test':equal(['by_ref','work:A','attempt'],2)})
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=AssertionError('No external command')):
            result=self.tools.call('test_loop',self.target(scenarios=[case]))
        self.assertTrue(result['passed'],[(r['error'],r['failed_step']) for r in result['scenarios']])

    def test_all_capability_tools_are_callable_and_run_discovery_needs_no_scope(self):
        defs={d['name']:d for d in self.tools.definitions()}
        for value in discover()['guide'].values():
            for name in value['tools']:self.assertIn(name,defs)
        mapped={name for value in discover()['guide'].values() for name in value['tools']}
        self.assertFalse(set(defs)-mapped,set(defs)-mapped)
        self.assertEqual(len(defs),len(self.tools.definitions()))
        for definition in defs.values():check_schema(definition['inputSchema'])
        self.assertIn('task_refs',RunTools(self.store,'not-a-run').call('read_capabilities',{})['capabilities'])

    def test_scenario_omission_creates_no_placeholder_and_finishes(self):
        self.edit('put_step',plan='work',step='work',node_id='work',when={'path':'values.enabled'})
        route=dict(self.routes[0],values={'jobs':{'$':'outputs.jobs'},'enabled':False})
        self.edit('put_node',node_id='initialize',routes=[route])
        report=self.report();report['envelope']['settings']['completion_rule']=equal('active_tasks',0)
        case={'name':'omitted','steps':[{'node':'initialize','report':report,'duplicate':True}],
              'assertions':[{'message':'Only initializer','test':equal('task_count',1)},
                            {'message':'No work placeholder','test':equal(['counts','work','total'],0)},
                            {'message':'Explicit completion applied','test':equal('status','completed')}]}
        result=self.tools.call('test_loop',self.target(scenarios=[case]))
        self.assertTrue(result['passed'],result)
        self.assertEqual(result['scenarios'][0]['receipts'][0]['routes'][0]['batches'][0]['omitted'][0]['reason'],'condition_false')
