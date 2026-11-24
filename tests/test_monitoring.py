import copy
import json
import sys
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
        overview=monitoring.workbench_runs(self.store)
        self.assertEqual(overview['active_total'],1)
        self.assertEqual(overview['attention'][0]['id'],receipt['run_id'])
        self.assertEqual(overview['attention'][0]['attention_count'],1)
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

    def test_finished_run_keeps_its_chart_when_timeline_is_continued(self):
        first=self.t.start()
        old_id=first['run_id']
        timeline_id=first['timeline_id']

        def save_chart(run_id, number):
            view={'at':number,'run_id':run_id,'view':{'series':[{'label':'F1','points':[[1,number]]}]}}
            with work.transaction(self.store) as db:
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?)',
                           (run_id,'Results',timeline_id,f'gen-{number}','{}',0,None))
                db.execute("""INSERT INTO observation_views VALUES(?,?,?,?)
                    ON CONFLICT(timeline_id,name) DO UPDATE SET job_id=excluded.job_id,document=excluded.document""",
                    (timeline_id,'Results',number,json.dumps(view)))

        def charts(group):
            return self.tools.call('read_monitor_dashboard',{'run_group':group,'charts_only':True,'limit':1})

        save_chart(old_id,1)
        expected=monitoring.charts_for_run(self.store,old_id)
        self.assertEqual(charts('active')['result_charts'],expected)
        self.t.engine.command(old_id,'pause')
        self.assertEqual(charts('active')['result_charts'],expected)
        self.t.engine.command(old_id,'terminate')
        unscored=self.store.create(self.t.key,'No chart')
        self.t.engine.command(unscored['id'],'terminate')
        self.assertEqual(charts('active')['total_runs'],0)
        self.assertEqual(charts('finished')['total_runs'],1)
        self.assertEqual(charts('finished')['result_charts'],expected)

        second=self.tools.call('start_run',{'key':self.t.key,'timeline_id':timeline_id,
                                             'title':'Continued work','request_id':'continued-with-chart'})
        save_chart(second['run_id'],2)
        self.assertEqual(charts('finished')['result_charts'],expected)
        self.assertEqual(monitoring.charts_for_run(self.store,old_id),expected)
        self.assertEqual(charts('active')['result_charts'][0]['series'][0]['points'],[[1,2]])
        self.assertEqual(self.tools.call('read_observations',{'timeline_id':timeline_id})['views'][0]['run_id'],
                         second['run_id'])

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

    def test_dashboard_only_lists_explicitly_displayed_instances(self):
        self.tools.call('register_monitor',{'script_id':'shared','revision':0,
            'script':{'command':[sys.executable,'-c','print(\'{"count":1}\')']}})
        self.tools.call('register_monitor',{'script_id':'unused','revision':0,'script':{'command':['unused']}})
        visible=self.tools.call('start_monitor',{'request_id':'visible','script_id':'shared','interval':60,
            'show_on_dashboard':True})['monitor']
        run=self.t.start()
        internal=self.tools.call('start_monitor',{'request_id':'internal','script_id':'shared','interval':60,
            'run_id':run['run_id']})['monitor']
        self.t.engine.work.tick()
        for future in list(self.t.engine.futures):future.result(timeout=5)
        wait=self.tools.call('wait_for',dict(self.t.session,timeline_id=run['timeline_id'],key='internal',
            sources={'m':{'kind':'monitor','id':internal['id']}},
            condition={'op':'eq','args':[{'path':'m.data.count'},1]}))['wait']
        self.assertEqual(wait['state'],'ready')
        public=self.tools.call('read_monitor_dashboard',{'dashboard_only':True})
        self.assertEqual([m['id'] for m in public['monitors']],[visible['id']])
        self.assertEqual([(s['id'],s['instances']) for s in public['scripts']],[('shared',1)])
        self.assertEqual(public['waits'],[])
        full=self.tools.call('read_monitor_dashboard',{})
        self.assertEqual({m['id'] for m in full['monitors']},{visible['id'],internal['id']})
        self.assertEqual({s['id']:s['instances'] for s in full['scripts']},{'shared':2,'unused':0})
        self.assertEqual([w['id'] for w in full['waits']],[wait['id']])
        before=self.tools.call('read_monitor',{'monitor_id':internal['id']})['monitor']
        after=self.tools.call('set_monitor_visibility',{'monitor_id':internal['id'],'show_on_dashboard':True})['monitor']
        self.assertEqual(after,dict(before,show_on_dashboard=True))
        public=self.tools.call('read_monitor_dashboard',{'dashboard_only':True})
        self.assertEqual({m['id'] for m in public['monitors']},{visible['id'],internal['id']})
        self.tools.call('set_monitor_visibility',{'monitor_id':internal['id'],'show_on_dashboard':False})
        self.assertEqual(self.tools.call('read_monitor',{'monitor_id':internal['id']})['monitor'],before)
        samples=self.tools.call('read_monitor_history',{'monitor_id':internal['id']})['samples']
        self.assertEqual([(s['call_id'],s['data']) for s in samples],[(before['sample']['call_id'],{'count':1})])
        self.assertEqual(self.tools.call('read_wait',{'wait_id':wait['id']})['wait']['state'],'ready')

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
        self.assertEqual(self.tools.call('read_monitor_dashboard',{'dashboard_only':True})['external'],[])
