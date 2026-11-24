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
from loop_anything.runtime.model import Conflict, Invalid
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

    def test_plan_completion_times_follow_platform_reports(self):
        plan,_=self.plan()
        tid=plan['timeline_id']
        def report(key, at, steps):
            with patch('loop_anything.runtime.timelines.time.time',return_value=at):
                self.call('append_timeline',dict(timeline_id=tid,key=key,kind='progress',
                    text=key,refs=[{'steps':steps}]))
        first={'title':'第一步','status':'done','completed_at':42}
        second={'title':'第二步','status':'done'}
        report('first',100,[first,dict(second,status='waiting')])
        report('second',200,[second,first])
        report('note',300,[dict(second,note='已复核'),first])
        card=web.overview(self.store,'plan')['items'][0]
        self.assertEqual([s['completed_at'] for s in card['steps']],[200,100])
        report('reopen',400,[dict(second,status='active',completed_at=200),first])
        card=web.overview(self.store,'plan')['items'][0]
        self.assertNotIn('completed_at',card['steps'][0])
        report('done-again',500,[second,first,{'title':'跳过','status':'skipped'}])
        card=web.overview(self.store,'plan')['items'][0]
        self.assertEqual([s.get('completed_at') for s in card['steps']],[500,100,None])

    def test_plan_agent_state_is_separate_from_plan_state(self):
        _,s=self.plan()
        def state():
            return web.overview(self.store,'plan')['items'][0]['agent_state']
        def update(**changes):
            with work.transaction(self.store) as db:
                s.update(changes)
                work.put(db,'session',s)
        self.assertEqual(state(),'starting')
        update(state='running')
        self.assertEqual(state(),'starting')
        update(process_id=os.getpid(),process={'state':'running'})
        self.assertEqual(state(),'running')
        update(process={'state':'exited'})
        self.assertEqual(state(),'idle')
        update(state='idle',process_id=None)
        self.assertEqual(state(),'idle')
        update(state='unknown')
        self.assertEqual(state(),'unknown')
        update(process_id=os.getpid())
        self.assertEqual(state(),'running')

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
        self.assertEqual(card()['wait_messages'],['等待 8 张 GPU'])
        self.assertFalse(card()['wait_errors'])
        sample('raise SystemExit("采集失败")')
        work.poll_wait(self.store,wait['id'])
        self.assertIn('采集失败',card()['wait_errors'][0]['error'])
        sample('print(\'{"free":4}\')')
        self.assertEqual(work.poll_wait(self.store,wait['id'])['state'],'waiting')
        self.assertFalse(card()['wait_errors'])
        sample('print(\'{"free":8}\')')
        self.assertEqual(work.poll_wait(self.store,wait['id'])['state'],'ready')
        self.assertFalse(card()['wait_messages'])

    def test_stop_plan_cancels_waits_and_follow_up_keeps_native_session(self):
        plan,s=self.plan()
        tid=plan['timeline_id']
        native={'provider':'codex','id':'original-plan-session','cwd':str(self.c.root)}
        auth={'session_id':s['id'],'session_token':s['token']}
        run=self.c.start()
        wait=self.call('wait_for',dict(auth,timeline_id=tid,key='ready',
            sources={'run':{'kind':'run','id':run['run_id']}},
            condition={'op':'eq','args':[{'path':'run.status'},'running']},message='等待运行'))['wait']
        self.assertEqual(work.poll_wait(self.store,wait['id'])['state'],'ready')
        other=self.call('wait_for',dict(auth,timeline_id=tid,key='waiting',
            sources=wait['sources'],condition={'op':'eq','args':[{'path':'run.status'},'paused']}))['wait']
        self.call('append_timeline',dict(timeline_id=tid,key='original',kind='progress',text='旧进度',
            refs=[dict(steps=[dict(title='原规划',status='done')])]))
        with work.transaction(self.store) as db:
            s.update(state='idle',native_session=native)
            work.put(db,'session',s)
        self.assertTrue(web.overview(self.store,'plan')['items'][0]['can_stop'])
        self.assertEqual(web.stop_plan(self.store,s['id']),{'id':s['id'],'state':'stopped'})
        self.assertEqual(web.stop_plan(self.store,s['id'])['state'],'stopped')
        self.c.engine.work.wake(s['id'],queued=True)
        read=self.call('read_work_session',auth)
        self.assertEqual(read['session']['state'],'stopped')
        self.assertEqual({(w['id'],w['state']) for w in read['waits']},
                         {(wait['id'],'cancelled'),(other['id'],'cancelled')})
        self.assertEqual(self.store.get(run['run_id'])['status'],'running')
        card=web.overview(self.store,'plan')['items'][0]
        self.assertTrue(card['can_follow_up'])
        self.assertFalse(card['can_stop'])
        with self.assertRaises(Conflict):web.follow_up(self.store,s['id'],dict(text='旧入口未扩权'))
        web.follow_up(self.store,s['id'],dict(text='补充新指令'),instruction=True)
        with self.assertRaises(Conflict):web.follow_up(self.store,s['id'],dict(text='重复提交'),instruction=True)
        with self.store.connection() as db:
            resumed=work.get(db,'session',s['id'])
            self.assertEqual(resumed['native_session'],native)
            self.assertEqual(resumed['assignment']['timeline_id'],tid)
            self.assertEqual(web.finished(db,resumed)[0],'failed')
        config,_=web.launch(resumed,{})
        self.assertIn('resume',config['command'])
        self.assertIn(native['id'],config['command'])
        self.call('append_timeline',dict(timeline_id=tid,key='reply-result',kind='progress',text='新指令已处理',
            refs=[dict(steps=[dict(title='新安排',status='done')])]))
        with self.store.connection() as db:
            self.assertEqual(web.finished(db,resumed)[0],'completed')

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
        html='<!DOCTYPE html><html lang="zh-CN"><title>回顾报告</title><p>面向用户的图文版</p></html>'
        def publish(key,text,**args):
            return self.call('append_timeline',dict(key=key,text=text,kind='progress',review=meta,timeline_id=tid,**args))
        a=publish('manual','手动报告')
        self.assertEqual(a,publish('manual','手动报告'))
        new=web.start(self.store,dict(kind='review',request_id='web',loop_key=self.c.key,created_to=time.time()+1))
        self.assertEqual(new['timeline_id'],tid)
        with self.assertRaises(Invalid):
            publish('invalid','导出失败',review_html='incorrect')
        publish(new['id']+':report','网页报告')
        with self.store.connection() as db:
            session=work.get(db,'session',new['id'])
            self.assertEqual(web.finished(db,session)[0],'failed')
        publish(new['id']+':report','网页报告',review_html=html)
        with self.store.connection() as db:
            self.assertEqual(web.finished(db,session),('completed',None))
        scheduled=publish('scheduled/最新','定时回顾发现新问题',review_html=html)
        self.assertEqual(scheduled,publish('scheduled/最新','定时回顾发现新问题',review_html=html))
        with self.assertRaises(Conflict):
            publish('scheduled/最新','定时回顾发现新问题',review_html=html.replace('图文版','更新版'))
        self.call('append_timeline',dict(timeline_id=tid,key='discussion',kind='progress',text='讨论一个改进'))
        items=web.overview(self.store,'review')['items']
        self.assertEqual(items[0]['report_url'],scheduled['report_url'])
        self.assertEqual(items[0]['count'],1)
        self.assertEqual({i['timeline_id'] for i in items},{tid})
        self.assertNotIn('定时回顾发现新问题',str(items))
        self.assertEqual(web.read_report_html(self.store,tid,'scheduled/最新'),html.encode())
        entries=self.call('read_work_timeline',dict(timeline_id=tid))['entries']
        self.assertNotIn('invalid',{e['key'] for e in entries})
        entry=next(e for e in entries if e['key']=='scheduled/最新')
        self.assertEqual(entry['text'],'定时回顾发现新问题')
        self.assertNotIn('review_html',entry)
