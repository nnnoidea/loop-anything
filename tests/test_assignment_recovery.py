"""User-visible waits, interrupted work and reports from independent callers."""
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tests import test_work_context as fixture
from loop_anything.runtime import web_assignments as web, work
from loop_anything.runtime.local_tasks import TaskRegistry
from loop_anything.runtime.model import Conflict
from loop_anything.runtime.tool_client import module


class AssignmentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.c=fixture.WorkContextTests()
        self.c.setUp()
        self.addCleanup(self.c.doCleanups)
        self.store=self.c.store
        self.call=self.c.tools.call

    def plan(self):
        plan=web.start(self.store,dict(kind='plan',text='等待 GPU 后继续',request_id='plan'))
        with self.store.connection() as db:
            return plan,work.get(db,'session',plan['id'])

    def test_monitor_failure_and_recovery_reach_waiting_plan(self):
        plan,s=self.plan()
        tid=plan['timeline_id']
        monitor=self.call('start_monitor',dict(request_id='watch',interval=60,
            script={'command':[sys.executable,'-c','raise SystemExit("采集失败")']}))['monitor']
        def sample(command):
            with work.transaction(self.store) as db:
                m=work.get(db,'monitor',monitor['id'])
                m['call_id']='sample-'+str(time.time_ns())
                m['script']['script']['command']=[sys.executable,'-c',command]
                work.put(db,'monitor',m)
            self.c.engine.work.monitor(m)
        wait=self.call('wait_for',dict(timeline_id=tid,session_id=s['id'],session_token=s['token'],key='capacity',
            sources={'gpu':{'kind':'monitor','id':monitor['id']}},condition={'op':'ge','args':[{'path':'gpu.data.free'},8]},
            message='等待 8 张 GPU'))['wait']
        self.call('append_timeline',dict(timeline_id=tid,key='steps',kind='progress',text='等待 8 张 GPU',
            refs=[dict(steps=[dict(title='等资源',status='waiting')])]))
        with work.transaction(self.store) as db:
            s['state'],s['error']=web.finished(db,s)
            work.put(db,'session',s)
        def card():return web.overview(self.store,'plan')['items'][0]
        self.assertEqual(card()['state'],'idle')
        self.assertFalse(card()['wait_errors'])
        sample('raise SystemExit("采集失败")')
        work.poll_wait(self.store,wait['id'])
        self.assertIn('采集失败',card()['wait_errors'][0]['error'])
        sample('print(\'{"free":4}\')')
        self.assertEqual(work.poll_wait(self.store,wait['id'])['state'],'waiting')
        self.assertFalse(card()['wait_errors'])
        sample('print(\'{"free":8}\')')
        self.assertEqual(work.poll_wait(self.store,wait['id'])['state'],'ready')

    def test_restart_requires_confirmation_and_dead_process_then_requeues_original(self):
        plan,s=self.plan()
        native={'provider':'codex','id':'previous-native-session','cwd':str(self.c.root)}
        with work.transaction(self.store) as db:
            s.update(state='running',wake='original',process_id=os.getpid(),native_session=native)
            work.put(db,'session',s)
        work.WorkRuntime(self.c.engine)
        def card():return web.overview(self.store,'plan')['items'][0]
        self.assertEqual(card()['state'],'unknown')
        self.assertFalse(card()['can_recover'])
        with self.assertRaises(Conflict):web.follow_up(self.store,s['id'],dict(text='',confirmed_stopped=True))
        child=subprocess.Popen([sys.executable,'-c','pass']);child.wait()
        with work.transaction(self.store) as db:
            updated=work.get(db,'session',s['id'])
            updated['process_id']=child.pid;work.put(db,'session',updated)
        self.assertTrue(card()['can_recover'])
        with self.assertRaises(Conflict):web.follow_up(self.store,s['id'],dict(text='继续'))
        web.follow_up(self.store,s['id'],dict(text='',confirmed_stopped=True))
        self.assertEqual((card()['state'],card()['timeline_id']),('queued',plan['timeline_id']))
        with self.store.connection() as db:
            resumed=work.get(db,'session',s['id'])
        command,_=web.launch(resumed,{})
        self.assertIn('resume',command['command'])
        self.assertIn(native['id'],command['command'])
        with self.assertRaises(Conflict):web.follow_up(self.store,s['id'],dict(text='继续',confirmed_stopped=True))

    def test_wait_uses_the_schedule_registry_where_the_plan_started(self):
        first=self.c.root/'original'
        second=self.c.root/'new'
        with patch.dict(os.environ,{'LOOP_ANYTHING_SPACES':str(self.c.root/'spaces.json')}):
            spaces=module('spaces')
            spaces.configure({'local_registry':str(first)},0)
            plan,s=self.plan()
            job=TaskRegistry(first).register(dict(name='取样',every=30,command=['echo','42']))
            spaces.configure({'local_registry':str(second)},1)
            wait=self.call('wait_for',dict(timeline_id=plan['timeline_id'],session_id=s['id'],session_token=s['token'],
                key='job',sources={'job':{'kind':'schedule','id':job['id']}},
                condition={'op':'eq','args':[{'path':'job.status'},'registered']}))['wait']
            self.assertEqual(work.poll_wait(self.store,wait['id'])['state'],'ready')

    def test_external_reports_use_the_same_loop_and_timeline_as_web(self):
        run=self.c.start()
        loop=self.store.get(run['run_id'])['loop_definition']['id']
        tid=self.call('create_timeline',{'title':'持续优化'})['timeline']['id']
        meta=dict(loop_id=loop,run_count=1)
        def publish(key,text):
            return self.call('append_timeline',dict(key=key,text=text,kind='progress',review=meta,timeline_id=tid))
        a=publish('manual','手动报告')
        self.assertEqual(a,publish('manual','手动报告'))
        new=web.start(self.store,dict(kind='review',request_id='web',loop_key=self.c.key,created_to=time.time()+1))
        self.assertEqual(new['timeline_id'],tid)
        publish(new['id']+':report','网页报告')
        publish('scheduled','定时回顾发现新问题')
        self.call('append_timeline',dict(timeline_id=tid,key='discussion',kind='progress',text='讨论一个改进'))
        items=web.overview(self.store,'review')['items']
        self.assertEqual(items[0]['summary'],'定时回顾发现新问题')
        self.assertEqual(items[0]['count'],1)
        self.assertEqual({i['timeline_id'] for i in items},{tid})
