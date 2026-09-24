"""Notifications and waits use real Timeline transactions, with isolated delivery commands."""
import json
import subprocess
import unittest
from unittest.mock import patch
import test_timeline_runtime as fixture
from test_timeline_runtime import task_spec
from loop_anything.interfaces.agent_tasks import RunTools, change_task_in_run
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.lifecycle import template
from loop_anything.runtime.model import Conflict, Invalid


class NotificationWaitTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.RuntimeTests();self.base.setUp();self.store=self.base.store;self.engine=self.base.engine
    def tearDown(self):self.base.tearDown()
    def settle(self):
        for f in list(self.engine.futures):f.result(timeout=5)
    def owner(self):
        return RunTools(self.store,self.base.id,self.base.read()['agent_sessions'][0]['token'])

    def test_outlet_snapshot_dedup_and_transition_notification(self):
        self.store.notification_channels({'chat':{'command':['sender-a'],'identity':'bot-a','destination':'room-a'}},0)
        with self.assertRaises(Conflict):self.store.notification_channels({},0)
        e=self.base.start();tools=self.owner()
        tools.call('change_settings',{'revision':1,'change':{'notification_route':'chat'}})
        args={'key':'progress','message':'one update'}
        first=tools.call('notify',args);self.assertEqual(first,tools.call('notify',args))
        with self.assertRaises(Conflict):tools.call('notify',dict(args,message='different'))
        self.store.notification_channels({'chat':{'command':['sender-b'],'identity':'bot-b','destination':'room-b'}},1)
        seen=[]
        def send(command,request,*args,**kwargs):seen.append((command,json.loads(request)));return subprocess.CompletedProcess(command,0,'{"delivered":true}', '')
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=send):self.engine.tick(self.base.id);self.settle()
        self.assertEqual(seen[0][0],['sender-a']);self.assertEqual(seen[0][1]['outlet']['destination'],'room-a')
        self.assertEqual(len(self.base.read()['notifications']),1)
        self.assertNotIn('notification_channels',self.store.catalog()[0]['loop_definition'])
        tools.call('change_settings',{'revision':2,'change':{'notification_route':'missing'}})
        tools.call('notify',{'key':'missing','message':'keep original target'})
        tools.call('change_settings',{'revision':3,'change':{'notification_route':'chat'}})
        self.assertEqual(self.base.read()['notifications'][-1]['route'],'missing')
        self.store.notification_channels({'missing':{'command':['fixed-sender']}},2)
        self.engine.command(self.base.id,'retry_notification',notification_id='notice:missing',operator_token=tools.token)
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=send):self.engine.tick(self.base.id);self.settle()
        self.assertEqual(seen[-1][0],['fixed-sender'])

    def test_question_event_reply_and_timeout_are_persistent(self):
        self.base.implementations['produce']={'kind':'event','event':'reply','wait':{'key':'{parameters.question}','timeout':60}}
        self.base.initialize([task_spec('answer','produce',{'source':{'record':'a'}},{'text':'answer'},parameters={'question':'budget'})])
        # External replies do not need to acquire an Agent session.
        user=RunTools(self.store,self.base.id)
        question=user.call('notify',{'key':'budget','message':'Approve budget?','reply':{'event':'reply','key':'budget','schema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}})
        reply={'event_id':'budget-reply','name':'reply','key':'budget','notification_id':question['notification_id'],'payload':{'text':'approved'}}
        with self.assertRaises(Invalid):user.call('send_event',dict(reply,payload={'text':12}))
        self.assertEqual(user.call('send_event',reply),user.call('send_event',reply))
        self.engine.close();self.base.engine=self.engine=Engine(self.store);self.engine.recover();self.engine.tick(self.base.id);self.settle()
        run=self.base.read();self.assertEqual(run['records']['answer'][0]['value'],'approved');self.assertEqual(len(run['events']),1)
        user.call('send_event',dict(reply,event_id='late-reply'));self.engine.tick(self.base.id);self.settle()
        self.assertEqual(len(self.base.read()['records']['answer']),1)

    def test_timer_restart_and_event_timeout_do_not_call_commands(self):
        self.base.bp['nodes']['wait']['outputs']={}
        self.base.implementations['wait']={'kind':'timer','wait':{'seconds':'{parameters.delay}'}}
        matrix=template('event');next(r for r in matrix['transitions'] if r['event']=='timeout')['notify']=[{'message':'Timed out','route':'workspace'}]
        self.base.implementations['produce']={'kind':'event','event':'answer','wait':{'timeout':5},'lifecycle':matrix}
        self.base.initialize([task_spec('clock','wait',parameters={'delay':10}),task_spec('cancel-clock','wait',parameters={'delay':10}),task_spec('answer','produce',{'source':{'record':'a'}},{'text':'answer'})])
        run=self.base.read();clock=next(e for e in run['executions'] if e['task_id']=='clock');deadline=clock['wait']['until']
        with self.store.edit(self.base.id) as run:change_task_in_run(run,{'task_id':'cancel-clock','operation':'cancel','reason':'No longer needed'})
        self.engine.close();self.base.engine=self.engine=Engine(self.store);self.engine.recover()
        self.assertEqual(next(e for e in self.base.read()['executions'] if e['task_id']=='clock')['wait']['until'],deadline)
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=AssertionError('Wait must not run commands')),patch('time.time',return_value=deadline+1):
            self.engine.tick(self.base.id);self.settle();self.engine.tick(self.base.id);self.settle()
        run=self.base.read();self.assertEqual(run['tasks']['cancel-clock']['status'],'cancelled');self.assertEqual(run['tasks']['clock']['status'],'completed');self.assertEqual(run['tasks']['answer']['status'],'fault')
        self.assertEqual(len(run['notifications']),1);self.assertEqual(run['notifications'][0]['status'],'delivered')
        self.assertFalse(any(h['kind']=='observation' for h in run['history']))

    def test_transition_and_script_notify_keep_scope_and_idempotency(self):
        matrix=template('command');next(r for r in matrix['transitions'] if r['event']=='completed')['notify']=[{'message':'Result {outputs.text}','route':'workspace'}]
        self.base.implementations['produce']={'kind':'command','command':['script'],'lifecycle':matrix}
        def script(command,request,*args,**kwargs):
            c=json.loads(request);tool=RunTools(self.store,self.base.id,c['token'])
            args={'task_id':c['task_id'],'execution_id':c['execution_id'],'key':'script-progress','message':'progress'}
            tool.call('notify',args);tool.call('notify',args)
            with self.assertRaises(Conflict):tool.call('notify',dict(args,task_id='init',key='wrong'))
            report={'task_id':c['task_id'],'execution_id':c['execution_id'],'event':'completed','report_id':'done','envelope':{'outputs':{'text':'ok'}}}
            tool.call('report_task',report);tool.call('report_task',report)
            return subprocess.CompletedProcess(command,0,'','')
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=script):
            self.base.initialize([task_spec('work','produce',{'source':{'record':'a'}},{'text':'result'})]);self.settle()
        run=self.base.read();self.assertEqual(len(run['notifications']),2);self.assertEqual(run['notifications'][1]['message'],'Result ok')
        self.assertEqual(len(run['records']['result']),1)

    def test_automatic_notifications_share_the_default_outlet(self):
        from loop_anything.runtime.timeline_runtime import agent_exited
        self.base.initialize()
        with self.store.edit(self.base.id) as run:
            run['attention_error']='isolated failure'
            for _ in range(3):agent_exited(run,self.engine.timeline_runtime,'isolated failure')
        self.engine.tick(self.base.id);self.settle()
        notice=self.base.read()['notifications'][0]
        self.assertEqual((notice['route'],notice['status']),('workspace','delivered'))
        with self.store.edit(self.base.id) as run:
            run['settings']['termination_signal']='finished'
        self.engine.tick(self.base.id);self.settle();self.engine.tick(self.base.id);self.settle()
        notices=self.base.read()['notifications']
        self.assertEqual(len(notices),2)
        self.assertEqual(notices[-1]['receipt']['channel'],'workspace')

    def test_invalid_wait_reference_is_a_visible_fault_without_stalling_other_tasks(self):
        self.base.bp['nodes']['wait']['outputs']={}
        self.base.implementations['wait']={'kind':'timer','wait':{'seconds':{'$':['parameters','delays',3]}}}
        self.base.initialize([task_spec('bad','wait',parameters={'delays':[0]}),task_spec('good','wait',parameters={'delays':[0,0,0,0]})])
        self.engine.tick(self.base.id);self.settle()
        run=self.base.read()
        self.assertEqual(run['tasks']['bad']['status'],'fault')
        self.assertEqual(run['tasks']['good']['status'],'completed')
        self.assertEqual(len([e for e in run['executions'] if e['task_id']=='bad']),1)
        self.assertTrue(any(h['kind']=='transition' and h['detail']['event']=='process_error' for h in run['history']))

    def test_notification_templates_cannot_stall_dispatch_and_before_reads_inputs(self):
        self.base.bp['nodes']['wait']['outputs']={}
        self.base.implementations['wait']={'kind':'timer','wait':{'seconds':0}}
        self.base.implementations['produce']={'kind':'timer','wait':{'seconds':0,'outputs':{'text':'done'}}}
        e=self.base.start()
        hooks=[{'id':'bounds','action':'notify','phase':'before','frequency':'once','target':{'node':'wait'},'message':'{parameters.items.5}','route':'workspace'},
               {'id':'empty','action':'notify','phase':'after','frequency':'once','target':{'node':'wait'},'message':'{parameters.blank}','route':'workspace'},
               {'id':'inputs','action':'notify','phase':'before','frequency':'once','target':{'node':'produce'},'message':'Starting {inputs.source}','route':'workspace'}]
        self.engine.change_settings(self.base.id,1,{'hooks':hooks},operator_token=e['token'])
        self.base.submit(e,{'settings':{'objective':'audit'},'outputs':{'a':'A','b':'B'},'tasks':[
            task_spec('clock','wait',parameters={'items':[],'blank':''}),task_spec('work','produce',{'source':{'record':'a'}},{'text':'out'})]})
        for _ in range(3):self.engine.tick(self.base.id);self.settle()
        run=self.base.read()
        self.assertEqual(run['tasks']['clock']['status'],'completed')
        self.assertEqual(run['tasks']['work']['status'],'completed')
        self.assertEqual(run['records']['out'][0]['value'],'done')
        self.assertEqual(sum(n['status']=='fault' for n in run['notifications']),2)
        self.assertEqual([(n['message'],n['status']) for n in run['notifications'] if n['status']!='fault'],[('Starting A','delivered')])
