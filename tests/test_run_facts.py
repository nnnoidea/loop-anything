"""Composable, paged Run facts through the platform tool boundary."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.store import Store


class RunFactsTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env=patch.dict('os.environ',{'LOOP_ANYTHING_IDENTITY_DIR':tmp.name+'/identity'})
        env.start()
        self.addCleanup(env.stop)
        self.store=Store(Path(tmp.name)/'runs.db')
        self.tools=PlatformTools(self.store)
        self.timeline=self.tools.call('create_timeline',{'objective':'Reduce evaluation failures'})['timeline']['id']

    def method(self,version):
        bp=dict(schema_version=2,id='evaluation',version=version,handbook={'instructions':'Evaluate inputs'},
                nodes={'score':dict(label='核对结果',instructions='Score',inputs={},outputs={})},records={})
        return self.store.publish(bp,{})['key']

    def measured_run(self,key,failures,base=0):
        run=self.store.create(key,'Measurement')
        with self.store.edit(run['id']) as r:
            for node in ('a','b'):
                r['tasks'][node]=dict(id=node,spec=dict(node='score',inputs={},outputs={}),status='completed',origin={})
            for i in range(failures):
                ident='failed-'+str(i)
                r['executions'].append(dict(id=ident,node='score',task_id='a',attempt=i+1,status='fault',
                    created_at=base+1,started_at=base+1,implementation={'kind':'command'},error="FileNotFoundError: [Errno 2] No such file or directory: '/tmp/score.json'"))
                self.store.log(r,'transition','failed',ident,{'event':'failed','accepted':True,'to':'retry'})
                r['history'][-1]['at']=base+2
            for task,start,end in [('a',10,20),('b',15,25)]:
                start,end=base+start,base+end
                r['executions'].append(dict(id=task,node='score',task_id=task,attempt=1+(failures if task=='a' else 0),
                    status='completed',created_at=start-1,started_at=start,completed_at=end,implementation={'kind':'external'}))
                self.store.log(r,'transition','submitted',task,{'event':'submitted','accepted':True,'to':'waiting'})
                r['history'][-1]['at']=start+1
                r['tasks'][task]['execution_id']=task
            r['status']='completed'
        return run['id']

    def facts(self,ids,source,**opts):
        return self.tools.call('query_run_facts',dict(run_ids=ids,source=source,**opts))

    def test_compare_versions_then_drill_down_without_loading_snapshots(self):
        old=self.measured_run(self.method('1'),2)
        new=self.measured_run(self.method('2'),0)
        ids=[old,new]
        with patch.object(Store,'_load',side_effect=AssertionError('Full Run read')):
            groups=self.facts(ids,'attempts',group_by=['version'],order_by='median_run_wall_seconds',descending=True)
            self.assertEqual(groups['items'][0]['version'],'1')
            by_version={r['version']:r for r in groups['items']}
            self.assertEqual((by_version['1']['count'],by_version['2']['count']),(4,2))
            self.assertEqual(by_version['1']['median_run_wall_seconds'],16)
            self.assertEqual(by_version['2']['median_run_wall_seconds'],15)
            self.assertEqual(by_version['1']['median_external_seconds'],9)
            result=self.facts(ids,'attempts',filters={'version':'1','status':'fault'},limit=1)
            self.assertEqual(result['next_offset'],1)
            row=result['items'][0]
            exact=self.tools.call('read_execution_attempt',dict(run_id=row['run_id'],execution_id=row['execution_id']))
            self.assertIn('score.json',exact['error'])
            self.assertEqual(self.facts(ids,'attempts',group_by=[],filters={'status':'fault'})['items'][0]['count'],2)
            self.assertEqual(self.facts([new,'deleted'],'runs')['missing_run_ids'],['deleted'])
        with self.assertRaises(Invalid):self.facts(ids,'history',group_by=['unrecognized'])
        with self.assertRaises(Invalid):self.facts(ids,'history',filters={'unknown':1})

    def test_repetition_pause_and_independent_timeline(self):
        rid=self.measured_run(self.method('1'),0)
        tools=self.tools
        def stamp():
            return tools.call('list_runs',{'view':'revisions','loop_id':'evaluation'})['runs'][0]
        before=stamp()
        with self.store.edit(rid) as r:
            for _ in range(3):
                self.store.log(r,'transition','check_error','a',{'event':'check_error','detail':{'message':'offline'}})
            r['status']='paused'
            self.store.log(r,'agent_failure_pause','Agent 连续失败三次，Loop 已暂停。',detail={'error':'offline'})
        repeated=self.facts([rid],'history',filters={'event':'check_error'},group_by=['reason'])
        self.assertEqual(repeated['items'],[{'reason':'offline','count':3,'run_count':1}])
        self.assertEqual(self.facts([rid],'runs')['items'][0]['status'],'paused')
        pause=self.facts([rid],'history',filters={'kind':'agent_failure_pause'})['items'][0]
        self.assertIn('暂停',pause['message'])
        self.assertGreater(stamp()['revision'],before['revision'])
        delta=lambda known: tools.call('list_runs',dict(loop_id='evaluation',known_revisions=known))
        self.assertEqual(delta([before])['runs'],[stamp()])
        self.assertEqual(delta([stamp()])['runs'],[])
        self.assertEqual(delta([dict(before,id='removed')])['removed_run_ids'],['removed'])
        after=stamp()
        args=dict(timeline_id=self.timeline,key='review-1',text='监控三次未取得结果；Run 已暂停。',refs=[dict(run_id=rid,fact_id=pause['fact_id'])])
        entry=tools.call('append_timeline',args)['entry']
        self.assertEqual(entry,tools.call('append_timeline',args)['entry'])
        self.assertEqual(entry['source_timeline_id'],self.timeline)
        self.assertEqual(stamp(),after)
        self.assertEqual(tools.call('read_work_timeline',{'timeline_id':self.timeline})['runs'],[])

    def test_period_longer_than_a_page_and_changed_runs(self):
        key=self.method('1')
        oldest=self.measured_run(key,1)
        for i in range(101):self.store.create(key,str(i))
        args=dict(loop_id='evaluation',view='revisions',created_from=0,created_to=4e9,sort='created_at',archived='include',limit=100)
        first=self.tools.call('list_runs',args)
        second=self.tools.call('list_runs',dict(args,offset=first['next_offset']))
        self.assertIsNone(second['next_offset'])
        ids=[r['id'] for r in first['runs']+second['runs']]
        self.assertEqual(len(ids),102)
        self.assertIn(oldest,[r['id'] for r in second['runs']])
        self.assertEqual(self.facts(ids,'runs',group_by=[])['items'][0]['count'],102)
        self.assertEqual(self.facts(ids,'attempts',filters={'status':'fault'})['items'][0]['run_id'],oldest)

    def test_retained_attempt_keeps_original_version(self):
        from loop_anything.runtime import run_methods
        rid=self.measured_run(self.method('1'),1)
        newkey=self.method('2')
        with self.store.edit(rid) as run:
            run['status']='running'
            run_methods.apply(self.store,run,newkey)
        groups=self.facts([rid],'attempts',group_by=['version','node'])['items']
        self.assertEqual([(r['version'],r['node'],r['count']) for r in groups],[('1','score',3)])
