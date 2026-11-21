"""Timeline-owned state, atomic decisions, and Loop changes with real Store/Engine."""
import copy
import unittest
from unittest.mock import patch

import test_timeline_runtime as fixture
from test_timeline_runtime import task_spec
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime import business_state, timelines


class BusinessStateTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.RuntimeTests();self.base.setUp();self.addCleanup(self.base.tearDown)
        self.store=self.base.store;self.engine=self.base.engine
        self.base.bp['state']={'id':'research','types':{
            'question':{'mode':'current','schema':{'type':'object','properties':{'text':{'type':'string'},'status':{'type':'string'}},'required':['text','status'],'additionalProperties':False},'summary':['text','status']},
            'judgment':{'mode':'append','schema':{'type':'string'}}}}
        self.base.bp['plans']={'experiment':{'parameters':{'type':'object'},'steps':{'observe':{'node':'wait','inputs':{}}}}}

    def question(self,revision=0,status='open'):
        return {'type':'question','id':'q1','value':{'text':'Does A improve recall?','status':status}}

    def first(self,waiting=False):
        e=self.base.start()
        self.base.submit(e,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'},
                           'state':[self.question()], 'tasks':[task_spec('experiment','wait',outputs={'text':'result'})] if waiting else []})
        self.engine.tick(self.base.id)
        return self.store.get(self.base.id)

    def second(self,old):
        bp=copy.deepcopy(self.base.bp);bp['version']='2';bp['id']='optimized-research'
        bp['nodes']['reason']=bp['nodes'].pop('init');bp['entry']='reason';bp['seed']['node']='reason';bp['seed']['id']='reason'
        implementations=copy.deepcopy(self.base.implementations);implementations['reason']=implementations.pop('init')
        key=self.store.publish(bp,implementations)['key']
        run=self.store.create(key,'same research',timeline_id=old['timeline_id'],continue_run_id=old['id'])
        self.base.id=run['id'];self.engine.tick(run['id'])
        return self.store.get(run['id'])

    def test_current_state_and_results_survive_new_loop_without_copying(self):
        old=self.first();new=self.second(old)
        self.assertEqual(new['timeline']['objective'],'Compare methods')
        self.assertEqual(new['business_state']['records'][0]['intent_revision'],old['timeline']['revision'])
        self.assertEqual(new['business_state']['records'][0]['value']['status'],'open')
        self.assertEqual(new['records']['a'][0]['source_run_id'],old['id'])
        e=next(e for e in new['executions'] if e['node']=='reason')
        self.base.submit(e,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'},
                           'state':[self.question(1,'resolved'),{'type':'judgment','id':'j1','value':'A wins on the fixed evaluation','refs':[{'record':'a','revision':1}]}]})
        current=business_state.read(self.store,old['timeline_id'])
        self.assertEqual(next(r for r in current['records'] if r['type']=='question')['revision'],2)
        self.assertEqual(business_state.read(self.store,old['timeline_id'],type='question',id='q1',revision=1)['records'][0]['value']['status'],'open')
        self.assertEqual(self.store.get(old['id'])['business_state']['records'],current['records'])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM work_results WHERE id=? AND revision=1',('a',)).fetchone()[0],1)

    def test_inflight_result_stays_one_execution_after_loop_change(self):
        old=self.first(waiting=True);old_execution=next(e for e in old['executions'] if e['node']=='wait')
        new=self.second(old)
        self.assertEqual(new['tasks']['experiment']['continuation_source'],{'run_id':old['id'],'task_id':'experiment'})
        self.assertFalse(any(e['node'].endswith(':wait') for e in new['executions']))
        self.engine.event(old['id'],'external-finished','signal',{'text':'result from original experiment'})
        self.engine.tick(old['id']);self.engine.tick(new['id'])
        result=self.store.get(new['id'])
        self.assertEqual(result['tasks']['experiment']['status'],'completed')
        self.assertEqual(result['records']['result'][0]['producer'],old_execution['id'])
        self.assertEqual(len(result['records']['result']),1)
        self.assertEqual(len([e for e in self.store.get(old['id'])['executions'] if e['node']=='wait']),1)

    def test_bad_reference_rolls_back_state_output_and_scheduled_work(self):
        e=self.base.start();tools=RunTools(self.store,self.base.id,e['token']);info=tools.call('read_task',{'task_id':e['task_id']})
        envelope={'settings':{'objective':'Compare'},'outputs':{'a':'A','b':'B'},
                  'state':[dict(self.question(),refs=[{'record':'missing','revision':1}])],
                  'operations':[{'tool':'build_plan','arguments':{'name':'experiment','key':'one','work_key':'experiment:one','values':{}}}]}
        with self.assertRaises(Invalid):
            tools.call('report_task',{'task_id':e['task_id'],'report_id':'bad','event':'completed','envelope':envelope})
        run=self.store.get(self.base.id)
        self.assertEqual(run['business_state']['records'],[]);self.assertEqual(run['records'],{})
        self.assertEqual(len(run['tasks']),1);self.assertEqual(run['arrangements'],{})

    def submit_experiment(self):
        e=self.base.start();tools=RunTools(self.store,self.base.id,e['token']);info=tools.call('read_task',{'task_id':e['task_id']})
        args={'task_id':e['task_id'],'report_id':'decision','event':'completed',
              'envelope':{'settings':{'objective':'Compare'},'outputs':{'a':'A','b':'B'},'state':[self.question()],
                          'operations':[{'tool':'build_plan','arguments':{'name':'experiment','key':'one','work_key':'experiment:one','values':{}}}]}}
        self.assertTrue(tools.call('report_task',copy.deepcopy(args))['accepted'])
        return tools, args

    def test_duplicate_decision_keeps_state_and_work_once(self):
        tools, args = self.submit_experiment()
        self.assertTrue(tools.call('report_task',copy.deepcopy(args))['duplicate'])
        run=self.store.get(self.base.id);self.assertEqual(run['business_state']['records'][0]['revision'],1);self.assertEqual(len(run['arrangements']),1)
        self.assertEqual(len(run['tasks']),2)

    def test_delete_ended_run_keeps_its_timeline_progress(self):
        from loop_anything.runtime.run_library import delete_run
        self.submit_experiment()
        run = self.store.get(self.base.id)
        tools = PlatformTools(self.store)
        args = {'timeline_id': run['timeline_id']}
        before = tools.call('export_timeline', args)['document']
        self.engine.command(run['id'], 'terminate')
        delete_run(self.store, run['id'], run.get('metadata_revision', 0))
        after = tools.call('export_timeline', args)['document']
        self.assertEqual(after['results'], before['results'])
        self.assertEqual(after['state'], before['state'])
        self.assertEqual(tools.call('read_work_timeline', args)['runs'], [])
        new = self.store.create(run['loop_key'], 'Continue', **args)
        self.assertEqual(new['business_state']['records'][0]['value'], self.question()['value'])
        self.assertEqual(new['arrangements'], {})

    def test_loop_business_schema_changes_do_not_block_continuation(self):
        old=self.first()
        bp=copy.deepcopy(self.base.bp);bp['version']='different';bp['state']['types']['question']['schema']['properties']['text']={'type':'number'}
        key=self.store.publish(bp,self.base.implementations)['key']
        new=self.store.create(key,'updated',timeline_id=old['timeline_id'],continue_run_id=old['id'])
        self.assertEqual(new['business_state']['records'],old['business_state']['records'])
        self.assertEqual(self.store.get(old['id'])['superseded_by'],new['id'])

    def test_summary_exposes_state_and_original_detail_and_rejects_transcripts(self):
        run=self.first();tools=PlatformTools(self.store)
        summary=tools.call('read_work_timeline',{'timeline_id':run['timeline_id']})
        self.assertEqual(summary['business_state']['records'][0]['summary']['status'],'open')
        detail=tools.call('read_business_state',{'timeline_id':run['timeline_id'],'type':'question','id':'q1'})
        self.assertEqual(detail['records'][0]['run_id'],run['id'])
        with self.assertRaises(Invalid):tools.call('append_timeline',{'timeline_id':run['timeline_id'],'key':'chat','text':'raw chat','kind':'user'})

    def test_shared_work_key_deduplicates_after_loop_change_and_keeps_dependencies(self):
        e=self.base.start();tools=RunTools(self.store,self.base.id,e['token']);info=tools.call('read_task',{'task_id':e['task_id']})
        operation={'tool':'build_plan','arguments':{'name':'experiment','key':'one','work_key':'experiment:one','values':{}}}
        tools.call('report_task',{'task_id':e['task_id'],'report_id':'plan','event':'completed',
            'envelope':{'settings':{'objective':'Compare'},'outputs':{'a':'A','b':'B'},'state':[self.question()],'operations':[operation]}})
        tools.call('finish',{})
        old=self.store.get(self.base.id);new=self.second(old)
        owner=next(x for x in new['executions'] if x['node']=='reason')
        current=RunTools(self.store,new['id'],owner['token']);current.call('read_timeline',{})
        reused=current.call('build_plan',operation['arguments'])
        original=old['arrangements']['experiment:one']['result']
        self.assertEqual(reused,original)
        current.call('read_timeline',{})
        scheduled=current.call('add_task',{'node_id':'join','key':'judge','inputs':{'a':{'record':'a'},'b':{'record':'b'}},
                                          'after_work':[{'key':'experiment:one','step':'observe'}]})
        self.assertEqual(scheduled['tasks'][0]['after'],original['steps']['observe'])
        self.assertEqual(len([t for t in self.store.get(new['id'])['tasks'] if t.startswith(original['tasks'][0]['id'])]),1)

    def test_state_updates_preserve_history_and_old_unretained_writer_cannot_update(self):
        old=self.first();new=self.second(old)
        e=next(e for e in new['executions'] if e['node']=='reason')
        self.base.submit(e,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'},
                           'state':[{'type':'judgment','id':'j1','value':'bounded conclusion'}]})
        with self.store.edit(new['id']) as run:
            attempt=next(x for x in run['executions'] if x['node']=='reason')
            business_state.apply(run,attempt,[{'type':'judgment','id':'j1','value':'revised conclusion'}])
        with self.assertRaises(Conflict):
            with self.store.edit(old['id']) as run:
                business_state.apply(run,run['executions'][0],[self.question(1,'resolved')])
        self.assertEqual(business_state.read(self.store,old['timeline_id'],type='judgment',id='j1',revision=1)['records'][0]['value'],'bounded conclusion')

        self.assertEqual(business_state.read(self.store,old['timeline_id'],type='judgment',id='j1')['records'][0]['value'],'revised conclusion')

    def test_filtered_page_reads_only_returned_bodies_and_pins_revisions(self):
        import json
        run=self.first()
        tid=run['timeline_id']
        with self.store.edit(run['id']) as current:
            business_state.apply(current,current['executions'][0],
                [{'type':'metric','id':str(i),'value':'probe-body-'+str(i)} for i in range(5)])
        with self.store.connection() as db:
            cutoff=db.execute('SELECT max(rowid) FROM work_state').fetchone()[0]
        with self.store.edit(run['id']) as current:
            business_state.apply(current,current['executions'][0],[{'type':'metric','id':'2','value':'updated'}])
        real_loads=json.loads
        with patch.object(business_state.json,'loads',wraps=real_loads) as decode:
            page=business_state.read(self.store,tid,type='metric',offset=2,limit=1,as_of=cutoff)
            loaded=[c.args[0] for c in decode.call_args_list if 'probe-body-' in c.args[0]]
        self.assertEqual((page['records'][0]['value'],page['total'],page['next_offset']),('probe-body-2',5,3))
        self.assertEqual(len(loaded),1)
        self.assertEqual(business_state.read(self.store,tid,type='metric',id='2')['records'][0]['value'],'updated')
        empty=business_state.read(self.store,tid,type='metric',offset=11)
        self.assertEqual((empty['records'],empty['total'],empty['next_offset']),([],5,None))
