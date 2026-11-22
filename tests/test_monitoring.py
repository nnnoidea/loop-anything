import copy
import json
import time
import unittest
import test_work_context as fixture
from loop_anything.runtime import work,monitoring
from loop_anything.runtime.model import Invalid


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.t=fixture.WorkContextTests();self.t.setUp();self.addCleanup(self.t.doCleanups)
        self.tools=self.t.tools;self.store=self.t.store

    def test_empty_dashboard_is_read_only_and_installs_no_scripts(self):
        first=self.tools.call('read_monitor_dashboard',{})
        second=self.tools.call('read_monitor_dashboard',{})
        for field in ('runs','monitors','result_charts','waits','scripts'):
            self.assertEqual(first[field],[])
            self.assertEqual(first[field],second[field])
        self.assertEqual(self.store.list(),[])

    def test_run_summary_uses_current_states_and_no_execution_payloads(self):
        receipt=self.t.start();self.t.initialize(receipt);self.t.engine.tick(receipt['run_id'])
        with self.store.edit(receipt['run_id']) as run:
            next(iter(run['tasks'].values()))['status']='fault'
        before=self.store.get(receipt['run_id'])
        data=self.tools.call('read_monitor_dashboard',{})
        self.assertEqual(data['counts']['running'],1)
        self.assertEqual(data['runs'][0]['attention_count'],1)
        self.assertEqual(data['runs'][0]['status'],'running')
        payload=json.dumps(data)
        self.assertNotIn(before['executions'][0]['token'],payload)
        self.assertNotIn('implementation',payload)
        self.assertEqual(before,self.store.get(receipt['run_id']))
        self.t.engine.command(receipt['run_id'],'pause')
        self.assertEqual(self.tools.call('read_monitor_dashboard',{})['counts']['paused'],1)

    def test_dashboard_projects_saved_series_from_their_own_run(self):
        run=self.store.create(self.t.key,'Scored work')
        run_id, timeline_id=run['id'],run['timeline_id']
        series=[{'label':'F1','points':[[1,0.24],[2,0.42]]}]
        with work.transaction(self.store) as db:
            for number,(name,owner,view) in enumerate([
                ('Results', run_id, {'summary':'Two scores','series':series,'image_png':'not part of dashboard'}),
                ('Text only', run_id, {'summary':'no chart'}),
                ('Previous Run', 'continued-from', {'series':series}),
                ('Disabled', run_id, {'series':series}),
            ],1):
                if name!='Disabled':
                    db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?)',
                               (run_id,name,timeline_id,f'gen-{number}','{}',0,None))
                db.execute('INSERT INTO observation_views VALUES(?,?,?,?)',
                           (timeline_id,name,number,json.dumps({'run_id':owner,'at':100,'view':view})))
        charts=self.tools.call('read_monitor_dashboard',{})['result_charts']
        self.assertEqual(charts,[{'run_id':run_id,'run_title':'Scored work','timeline_id':timeline_id,
                                  'name':'Results','summary':'Two scores','at':100,'series':series}])

    def test_history_retains_gaps_and_bounds_each_instance(self):
        m=self.tools.call('start_monitor',{'request_id':'history','interval':30,
            'script':{'command':['unused-test-command']}})['monitor']
        with work.transaction(self.store) as db:
            for i in range(245):monitoring.record_sample(db,m['id'],str(i),{'count':i},None)
            monitoring.record_sample(db,m['id'],'error',None,'timeout')
            monitoring.record_sample(db,m['id'],'error',None,'timeout')
        rows=self.tools.call('read_monitor_history',{'monitor_id':m['id'],'limit':240})['samples']
        self.assertEqual(len(rows),240)
        self.assertEqual(rows[0]['data']['count'],6)
        self.assertIsNone(rows[-1]['data'])
        self.assertEqual(rows[-1]['error'],'timeout')
        self.assertEqual(rows[-1]['call_id'],'error')
        projected=self.tools.call('read_monitor_history',{'monitor_id':m['id'],'metric':'count','limit':2})
        self.assertEqual(projected['points'],[{'at':rows[-2]['at'],'value':244},{'at':rows[-1]['at'],'value':None}])

    def test_sampling_health_does_not_claim_external_business_failure(self):
        m=self.tools.call('start_monitor',{'request_id':'health','interval':10,
            'script':{'command':['unused'],'display':'bars','metrics':[{'key':'gpu.available','label':'可用 GPU','unit':'张'}]}})['monitor']
        with work.transaction(self.store) as db:
            m.update(sample={'at':time.time()-1000,'data':{'status':'running','gpu':{'available':0}}},error=None)
            work.put(db,'monitor',m)
        row=self.tools.call('read_monitor_dashboard',{})['monitors'][0]
        self.assertEqual(row['data_state'],'stale')
        self.assertEqual(row['sample']['data']['status'],'running')
        with work.transaction(self.store) as db:
            m['error']='timeout';work.put(db,'monitor',m)
        row=self.tools.call('read_monitor_dashboard',{})['monitors'][0]
        self.assertEqual(row['data_state'],'error')
        self.assertEqual(row['status'],'running')
        self.assertEqual(row['metrics'][0]['unit'],'张')
        self.assertEqual(row['display'],'bars')

    def test_metrics_are_optional_and_invalid_definitions_rejected(self):
        with self.assertRaises(Invalid):
            self.tools.call('register_monitor',{'script_id':'bad','revision':0,
                'script':{'command':['unused'],'metrics':[{'key':'count'},{'key':'count'}]}})
        self.assertEqual(self.tools.call('list_monitor_scripts',{})['scripts'],[])

    def test_script_can_declare_more_than_twelve_metrics(self):
        metrics = [{'key': 'metric' + str(i)} for i in range(20)]
        self.tools.call('register_monitor', {'script_id': 'many', 'revision': 0,
                        'script': {'command': ['unused'], 'metrics': metrics}})
        scripts = self.tools.call('list_monitor_scripts', {})['scripts']
        self.assertEqual(scripts[0]['script']['metrics'], metrics)

    def test_run_pagination_and_archives(self):
        for i in range(3):
            r=self.store.create(self.t.key,'run '+str(i))
            if i==0:
                with self.store.edit(r['id']) as current:current['archived_at']=time.time()
        first=self.tools.call('read_monitor_dashboard',{'limit':1})
        second=self.tools.call('read_monitor_dashboard',{'limit':1,'offset':1})
        self.assertEqual(first['total_runs'],2)
        self.assertNotEqual(first['runs'][0]['id'],second['runs'][0]['id'])
        beyond=self.tools.call('read_monitor_dashboard',{'limit':1,'offset':2})
        self.assertEqual(beyond['offset'],1)
        self.assertEqual(beyond['runs'],second['runs'])

    def test_loop_owned_external_observer_links_existing_run(self):
        run=self.store.create(self.t.key,'Existing external work')
        with self.store.edit(run['id']) as current:
            from loop_anything.runtime.timeline_plan import add_task
            task=add_task(current,{'id':'observed','node':'work','inputs':{},'outputs':{'value':{'id':'observed.value'}}},{'test':True})
            task['execution_id']='external-current'
            current['executions'].append({'id':'external-current','task_id':task['id'],'node':task['spec']['node'],'external_id':'batch-A',
                'implementation':{'kind':'external','command':['private-submit'],'observe':['private-check']},
                'status':'waiting','token':'private-token','observation_error':'timeout','activity_progress_at':10,'activity_progress':{'external_status':'RUNNING','progress':0,'metrics':{'loss':0.25}}})
        overview=self.tools.call('read_monitor_dashboard',{})
        self.assertEqual(len(overview['external']),1)
        self.assertEqual(overview['external'][0]['run_id'],run['id'])
        reading=overview['external'][0]
        self.assertEqual(reading['business_status'],'RUNNING')
        self.assertEqual((reading['external_id'],reading['progress'],reading['sampled_at']),('batch-A',0,10))
        self.assertEqual(reading['metrics'],{'loss':0.25})
        self.assertNotIn('private-',json.dumps(overview))
