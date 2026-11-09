"""Installed Loops compose through real Runs, without wrapper scripts or waiting workers."""
import copy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

import test_timeline_runtime as fixture
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Invalid,digest


class LoopCallTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.RuntimeTests();self.base.setUp()
        self.store=self.base.store;self.engine=self.base.engine
        self.effect=Path(self.base.tmp.name)/'effects'
        self.child_bp={'schema_version':2,'id':'child','version':'1','entry':'init',
            'handbook':{'instructions':'Return the given request and finish.'},'records':{'text':{'type':'string'}},
            'nodes':{'init':fixture.node({'request':{'type':'string'}},{'answer':'text'},initialize_timeline=True)},
            'seed':fixture.task_spec('init','init',{'request':{'run':'request'}},{'answer':'answer'}),'rules':[]}
        code='import json,sys;from pathlib import Path;c=json.load(sys.stdin);p=Path('+repr(str(self.effect))+');p.write_text(p.read_text()+"x" if p.exists() else "x");print(json.dumps({"settings":{"objective":"Child work","termination_signal":"Child finished"},"outputs":{"answer":c["inputs"]["request"]+"!"}}))'
        self.child_impl={'init':{'kind':'command','command':[sys.executable,'-c',code]}}
        self.key=self.store.publish(self.child_bp,self.child_impl)['key']

    def tearDown(self):self.base.tearDown()

    def config(self):
        return {'kind':'loop','loop':{'key':self.key,'inputs':{'request':{'$':'inputs.source'}},
            'result':{'outputs':{'text':{'$':'records.answer'}}}}}

    def start(self, config=None, two=False):
        self.base.implementations['produce']=config or self.config()
        tasks=[fixture.task_spec('call','produce',{'source':{'record':'a'}},{'text':'result'})]
        if two:tasks.append(fixture.task_spec('second','produce',{'source':{'record':'b'}},{'text':'other'}))
        self.base.initialize(tasks)
        return self.base.id

    def tick(self):
        for item in self.store.scheduling_list():self.engine.tick(item['id'])

    def until(self, predicate):
        end=time.monotonic()+8
        while time.monotonic()<end:
            self.tick()
            if predicate():return
            time.sleep(.02)
        self.fail('Timed out: '+json.dumps(self.base.read()['history'][-5:]))

    def child(self, task='call'):
        return self.store.get(self.base.read()['tasks'][task]['child_call']['run_id'])

    def test_input_output_mapping_and_one_child_per_task(self):
        self.start(two=True)
        with self.store.edit(self.base.id) as parent:parent['created_by']='tdh'
        self.until(lambda:all(self.base.read()['tasks'][t]['status']=='completed' for t in ('call','second')))
        run=self.base.read();self.assertEqual(run['records']['result'][-1]['value'],'A!')
        self.assertEqual(run['records']['other'][-1]['value'],'B!')
        self.assertNotEqual(self.child()['id'],self.child('second')['id'])
        self.assertEqual(self.child()['parent_call']['run_id'],self.base.id)
        self.assertEqual(self.child()['created_by'],'tdh')
        self.assertEqual(self.child()['settings']['authorization'],run['settings']['authorization'])
        for _ in range(4):self.tick()
        self.assertEqual(self.effect.read_text(),'xx');self.assertEqual(len(self.store.list()),3)
        task=RunTools(self.store,self.base.id).call('read_task',{'task_id':'call'})
        self.assertEqual(task['execution_state']['child_run_id'],self.child()['id'])
        self.assertEqual(task['execution_state']['child_status'],'completed')
        self.assertFalse(task['execution_state'].get('worker_active'))

    def test_recovery_keeps_call_and_runs_child_own_entry(self):
        self.start();self.engine.tick(self.base.id);ident=self.child()['id']
        self.assertFalse(self.effect.exists());self.assertFalse(self.child()['agent_sessions'])
        self.engine.close();self.engine=Engine(self.store);self.base.engine=self.engine;self.engine.recover()
        self.until(lambda:self.base.read()['tasks']['call']['status']=='completed')
        self.assertEqual(self.child()['id'],ident);self.assertEqual(self.effect.read_text(),'x')

    def test_crash_between_child_save_and_parent_save_rolls_back_both(self):
        self.start();save=self.store._save
        def crash(db,run):
            if run['id']==self.base.id and run['tasks']['call'].get('child_call'):raise KeyboardInterrupt()
            return save(db,run)
        with patch.object(self.store,'_save',side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):self.engine.tick(self.base.id)
        self.assertEqual(len(self.store.list()),1)
        self.assertNotIn('child_call',self.base.read()['tasks']['call'])
        self.until(lambda:self.base.read()['tasks']['call']['status']=='completed')
        self.assertEqual(len(self.store.list()),2);self.assertEqual(self.effect.read_text(),'x')

    def test_mapping_error_and_retry_reuse_child_without_repeating_work(self):
        config=self.config();config['loop']['result']={'outputs':{'text':{'$':'records.absent'}}}
        self.start({'default':'bad','options':{'bad':config,'corrected':self.config()}})
        self.until(lambda:self.base.read()['tasks']['call']['status']=='fault')
        ident=self.child()['id'];attempt=self.base.read()['tasks']['call']['execution_id']
        self.engine.command(self.base.id,'retry',attempt)
        self.until(lambda:self.base.read()['tasks']['call']['status']=='fault')
        self.assertEqual(self.child()['id'],ident);self.assertEqual(self.effect.read_text(),'x')
        self.assertEqual(len(self.store.list()),2)
        tools=PlatformTools(self.store);basis=tools.call('read_task',{'run_id':self.base.id,'task_id':'call'})['basis']
        tools.call('change_task',{'run_id':self.base.id,'task_id':'call','operation':'retry','implementation':'corrected',
            'reason':'Use corrected result mapping','basis':basis})
        self.until(lambda:self.base.read()['tasks']['call']['status']=='completed')
        self.assertEqual(self.base.read()['records']['result'][-1]['value'],'A!')
        self.assertEqual(self.child()['id'],ident);self.assertEqual(self.effect.read_text(),'x')

    def test_settings_edits_do_not_change_an_in_flight_call(self):
        config=self.config();config['loop']['inputs']={'request':{'$':'settings.objective'}}
        self.start(config);self.engine.tick(self.base.id)
        original=self.child()['inputs']['request']
        with self.store.edit(self.base.id) as run:run['settings']['objective']='Updated while waiting'
        self.until(lambda:self.base.read()['tasks']['call']['status']=='completed')
        self.assertEqual(self.base.read()['records']['result'][-1]['value'],original+'!')

    def test_invalid_result_index_faults_instead_of_stalling_scheduler(self):
        config=self.config();config['loop']['inputs']['items']=[]
        config['loop']['result']={'outputs':{'text':{'$':'inputs.items.0'}}}
        self.start(config);self.until(lambda:self.base.read()['tasks']['call']['status']=='fault')
        self.assertEqual(self.child()['status'],'completed');self.assertEqual(self.effect.read_text(),'x')

    def test_parent_pause_and_cancel_leave_child_independent(self):
        self.start();self.engine.tick(self.base.id);ident=self.child()['id']
        self.engine.command(self.base.id,'pause')
        self.until(lambda:self.child()['status']=='completed')
        self.assertEqual(self.base.read()['tasks']['call']['status'],'waiting')
        self.engine.command(self.base.id,'resume')
        self.until(lambda:self.base.read()['tasks']['call']['status']=='completed')
        self.assertEqual(self.effect.read_text(),'x')
        # Another call can be cancelled after creation without terminating the called Run.
        self.base.engine=self.engine
        self.start();self.engine.tick(self.base.id);other=self.child()['id']
        self.engine.command(self.base.id,'terminate')
        self.until(lambda:self.store.get(other)['status']=='completed')
        self.assertEqual(self.base.read()['status'],'terminated')
        self.assertNotEqual(ident,other)

    def test_terminated_child_reports_failure_without_starting_a_replacement(self):
        self.start();self.engine.tick(self.base.id);ident=self.child()['id']
        self.engine.command(ident,'terminate');self.engine.tick(self.base.id)
        self.assertEqual(self.base.read()['tasks']['call']['status'],'fault')
        self.assertFalse(self.effect.exists())
        self.engine.command(self.base.id,'retry',self.base.read()['tasks']['call']['execution_id'])
        self.engine.tick(self.base.id);self.engine.tick(self.base.id)
        self.assertEqual(self.child()['id'],ident);self.assertEqual(len(self.store.list()),2)

    def test_tool_discovery_schema_validation_and_no_wrapper_configuration(self):
        tools=PlatformTools(self.store)
        draft=tools.call('create_loop',{'name':'Calls'})
        tools.call('set_implementation',{'draft_id':draft['draft_id'],'revision':draft['revision'],
            'node_id':'initialize','clear':['lifecycle'],**self.config()})
        config=tools.call('read_loop',{'draft_id':draft['draft_id']})['loop']['implementations']['initialize']
        from loop_anything.runtime.implementations import options,validate_implementation
        self.assertEqual(next(iter(options(config).values()))['loop']['key'],self.key)
        capability=tools.call('read_capabilities',{'capability':'loop_calls'})
        self.assertIn('set_implementation',capability['guide']['loop_calls']['tools'])
        from loop_anything.capabilities import required_capabilities
        self.assertIn('loop_calls',required_capabilities(self.base.bp,{'produce':self.config()}))
        for bad in ({'kind':'loop'},{'kind':'loop','loop':{'key':self.key,'unknown':1}},dict(self.config(),command=['unused'])):
            with self.assertRaises(Invalid):validate_implementation(bad)

    def test_child_agent_entry_uses_its_own_registered_implementation(self):
        self.child_impl['init']={'kind':'agent','command':[sys.executable,'-c',r'''import json,sys
from pathlib import Path
c=json.loads(sys.stdin.read().rsplit('Run context:\n',1)[1]);sys.path.insert(0,str(Path(c['platform_client']).parent))
from call import fetch
def call(name,args):
 args.update(run_id=c['run_id'],token=c['token']);r=fetch(c['platform_url']+'/api/tools',json.dumps({'tool':name,'arguments':args}).encode());assert r.get('ok'),r;return r
i=call('read_task',{'task_id':c['task_id']})
call('report_task',{'task_id':c['task_id'],'task_version':i['task_version'],'event':'completed','report_id':'child','envelope':{'settings':{'objective':'Child','termination_signal':'done'},'outputs':{'answer':i['inputs']['request']+'!'}}})
call('finish',{})
''']}
        self.key=self.store.publish(self.child_bp,self.child_impl)['key']
        from loop_anything.runtime.tool_mailbox import ToolMailbox
        box=ToolMailbox(self.store,Path(self.base.tmp.name)/'team',self.engine);self.engine.platform_url='nas://'+str(box.root)
        self.start();tick=self.tick
        self.tick=lambda:(box.tick(),tick())
        self.until(lambda:self.base.read()['tasks']['call']['status']=='completed')
        self.assertEqual(self.base.read()['records']['result'][-1]['value'],'A!')
        self.assertEqual(self.child()['executions'][0]['implementation']['kind'],'agent')

    def test_recursive_call_fails_without_creating_another_run(self):
        bp=copy.deepcopy(self.child_bp)
        implementation={'init':{'kind':'loop','loop':{'key':'recursive'}}}
        with self.store.connection() as db:
            db.execute('INSERT INTO loop_definitions VALUES (?,?,?,?)',('recursive',digest(bp),json.dumps(bp),json.dumps(implementation)));db.commit()
        run=self.store.create('recursive','Recursive',{'request':'test'})
        self.engine.tick(run['id']);self.engine.tick(run['id'])
        self.assertEqual(len(self.store.list()),1)
        self.assertEqual(self.store.get(run['id'])['tasks']['init']['status'],'fault')

    def test_loop_call_can_initialize_parent_and_scenarios_do_not_launch_children(self):
        bp=copy.deepcopy(self.child_bp);bp['id']='parent'
        config={'kind':'loop','loop':{'key':self.key,'result':{'settings':{'objective':'Parent','termination_signal':'Finished'},
            'outputs':{'answer':{'$':'records.answer'}}}}}
        key=self.store.publish(bp,{'init':config})['key']
        run=self.store.create(key,'Parent',{'request':'Input'})
        end=time.monotonic()+5
        while time.monotonic()<end and self.store.get(run['id'])['status']!='completed':self.tick();time.sleep(.02)
        parent=self.store.get(run['id'])
        self.assertEqual(parent['status'],'completed');self.assertEqual(parent['records']['answer'][-1]['value'],'Input!')
        from loop_anything.packaging.scenarios import run_scenarios
        before=self.store.list()
        result=run_scenarios({'loop_definition':bp,'implementations':{'init':config}},[{
            'name':'Called result','inputs':{'request':'Input'},'steps':[{'task_id':'init','report':{'event':'completed',
                'envelope':{'settings':{'objective':'Scenario','termination_signal':'Done'},'outputs':{'answer':'Sample'}}}}],
            'assertions':[{'message':'Parent finished with simulated child result','test':{'op':'eq','args':[{'path':'status'},'completed']}}]}])
        self.assertTrue(result['passed'],result);self.assertEqual(self.store.list(),before)

    def test_concurrent_ticks_create_one_child_and_cancel_before_creation_creates_none(self):
        from concurrent.futures import ThreadPoolExecutor
        self.start()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(self.engine.tick,self.base.id) for _ in range(2)]
            for job in jobs:job.result(timeout=5)
        self.assertEqual(len(self.store.list()),2)
        self.start()
        tools=PlatformTools(self.store);basis=tools.call('read_task',{'run_id':self.base.id,'task_id':'call'})['basis']
        tools.call('change_task',{'run_id':self.base.id,'task_id':'call','operation':'cancel','reason':'Cancel before dispatch','basis':basis})
        self.engine.tick(self.base.id)
        self.assertNotIn('child_call',self.base.read()['tasks']['call'])
        self.assertEqual(len(self.store.list()),3)

    def test_parent_completion_signal_prevents_new_child(self):
        self.start()
        with self.store.edit(self.base.id) as run:run['settings']['termination_signal']='No further work'
        self.engine.tick(self.base.id)
        self.assertEqual(self.base.read()['status'],'completed')
        self.assertNotIn('child_call',self.base.read()['tasks']['call'])
        self.assertEqual(len(self.store.list()),1)


if __name__=='__main__':unittest.main()
