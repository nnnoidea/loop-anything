import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Conflict,Invalid
from loop_anything.runtime import work


class WorkContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        env=patch.dict(os.environ,{'LOOP_ANYTHING_IDENTITY_DIR':str(self.root/'identity')})
        env.start();self.addCleanup(env.stop)
        self.store=Store(self.root/'test.db')
        self.engine=Engine(self.store);self.addCleanup(self.engine.close)
        self.tools=PlatformTools(self.store)
        self.session=self.tools.call('register_work_session',{
            'native_session':{'provider':'custom','id':'test-native','cwd':str(self.root)},
            'implementation':{'kind':'agent','command':[sys.executable,'-c','print("unused")'],
                'resume_command':[sys.executable,'-c','print("resumed")','{{session_id}}','{{prompt}}']},
            'process_id':os.getpid()})
        draft=self.tools.call('create_loop',{'name':'Continue work'})
        for name,args in [('set_loop',{'handbook':'Continue objective using existing evidence.'}),
                          ('put_node',{'node_id':'work','instructions':'Wait','outputs':[{'name':'value','type':'string'}]}),
                          ('set_implementation',{'node_id':'work','kind':'event','event':'result'})]:
            draft=self.tools.call(name,dict(draft_id=draft['draft_id'],revision=draft['revision'],**args))
        self.key=self.tools.call('publish_loop',{'draft_id':draft['draft_id'],'revision':draft['revision']})['key']

    def start(self,**kwargs):
        args=dict(self.session,key=self.key,title='work',request_id='start',objective='Finish the work',constraints='Local only',**kwargs)
        return self.tools.call('start_run',args)

    def initialize(self,receipt):
        runtime=RunTools(self.store,receipt['run_id'],receipt['token'])
        run=self.store.get(receipt['run_id'])
        seed=run['loop_definition']['seed']['id']
        info=runtime.call('read_task',{'task_id':seed})
        runtime.call('report_task',{'task_id':seed,'event':'completed','report_id':'init',
                     'envelope':{'settings':{'objective':run['settings']['objective']},'outputs':{}}})
        runtime.call('add_task',{'key':'work','node_id':'work','inputs':{}})
        info=runtime.call('read_task',{'task_id':receipt['task_id']})
        runtime.call('report_task',{'task_id':receipt['task_id'],'event':'completed','report_id':'managed',
                     'envelope':{'outputs':{'decision':'Started'}}})
        runtime.call('finish',{})
        return runtime

    def test_timeline_without_run_and_edit_does_not_schedule_or_pause(self):
        t=self.tools.call('create_timeline',{'objective':'old','constraints':'limit'})['timeline']
        self.tools.call('append_timeline',{'timeline_id':t['id'],'key':'progress-1','text':'recorded progress','kind':'progress'})
        r=self.start(timeline_id=t['id'])
        before=self.store.get(r['run_id'])
        result=self.tools.call('update_timeline',{'timeline_id':t['id'],'revision':t['revision'],'change':{'objective':'new'}})
        self.assertIn('告诉用户',result['notice'])
        after=self.store.get(r['run_id'])
        self.assertEqual(before['status'],after['status'])
        self.assertEqual(before['tasks'],after['tasks'])
        self.assertEqual(after['settings']['objective'],'new')
        self.assertNotIn('authorization',after['settings'])
        with self.assertRaises(Conflict):
            self.tools.call('update_timeline',{'timeline_id':t['id'],'revision':t['revision'],'change':{'constraints':'other'}})
        read=self.tools.call('read_work_timeline',{'timeline_id':t['id']})
        self.assertEqual(read['entries'][0]['text'],'recorded progress')

    def test_start_binds_current_session_and_deduplicates(self):
        r=self.start()
        self.assertEqual(r,self.start())
        run=self.store.get(r['run_id'])
        self.assertEqual(run['steward']['session_id'],self.session['session_id'])
        self.assertEqual(run['executions'][0]['native_session']['id'],'test-native')
        self.engine.tick(run['id'])
        self.assertEqual(len(self.store.get(run['id'])['executions']),1)
        self.initialize(r)
        self.engine.tick(r['run_id'])

    def test_wait_completed_source_and_cancel_are_independent(self):
        r=self.start()
        with self.store.edit(r['run_id']) as run:run['status']='completed'
        a=dict(self.session,timeline_id=r['timeline_id'],key='done',
               sources={'job':{'kind':'run','id':r['run_id']}},
               condition={'op':'eq','args':[{'path':'job.status'},'completed']})
        first=self.tools.call('wait_for',a)['wait']
        second=self.tools.call('wait_for',dict(a,key='also-done'))['wait']
        self.assertEqual(first['state'],'ready')
        self.assertEqual(second['state'],'ready')
        self.tools.call('cancel_wait',dict(self.session,wait_id=first['id']))
        self.assertEqual(self.tools.call('read_wait',{'wait_id':second['id']})['wait']['state'],'ready')
        self.assertEqual(self.store.get(r['run_id'])['status'],'completed')

    def test_monitor_registry_and_inline_instances_real_process(self):
        script={'command':[sys.executable,'-c',
            'import sys,json; p=json.load(sys.stdin); print(json.dumps({"gpu":p["parameters"]["gpu"]}))']}
        self.tools.call('register_monitor',{'script_id':'gpu','revision':0,'script':script})
        self.assertEqual(self.tools.call('list_monitors',{})['monitors'],[])
        first=self.tools.call('start_monitor',{'request_id':'first','script_id':'gpu','parameters':{'gpu':8},'interval':60})['monitor']
        second=self.tools.call('start_monitor',{'request_id':'second','script':script,'parameters':{'gpu':4},'interval':60})['monitor']
        self.engine.work.tick()
        for f in list(self.engine.futures):f.result(timeout=5)
        self.assertEqual(self.tools.call('read_monitor',{'monitor_id':first['id']})['monitor']['sample']['data']['gpu'],8)
        self.assertEqual(self.tools.call('read_monitor',{'monitor_id':second['id']})['monitor']['sample']['data']['gpu'],4)
        t=self.tools.call('create_timeline',{})['timeline']
        wait=self.tools.call('wait_for',dict(self.session,timeline_id=t['id'],key='gpu',
            sources={'gpu':{'kind':'monitor','id':first['id']}},
            condition={'op':'ge','args':[{'path':'gpu.data.gpu'},8]}))['wait']
        self.assertEqual(wait['state'],'ready')
        self.tools.call('stop_monitor',{'monitor_id':first['id']})
        self.assertEqual(self.tools.call('read_monitor',{'monitor_id':second['id']})['monitor']['status'],'running')

    def test_unknown_monitor_never_matches_false_branch(self):
        t=self.tools.call('create_timeline',{})['timeline']
        wait=self.tools.call('wait_for',dict(self.session,timeline_id=t['id'],key='missing',
            sources={'gpu':{'kind':'monitor','id':'missing'}},
            condition={'op':'eq','args':[{'op':'eq','args':[{'path':'gpu.data.gpu'},8]},False]}))['wait']
        self.assertEqual(wait['state'],'waiting')
        self.assertTrue(wait['error'])

    def test_recovery_keeps_external_identity_and_results(self):
        r=self.start();self.initialize(r);self.engine.tick(r['run_id'])
        old=self.store.get(r['run_id'])
        task=next(t for t in old['tasks'].values() if t['spec']['node']=='work')
        # Simulate a stopped original Agent; the event observer is still waiting.
        with self.store.edit(old['id']) as run:
            for e in run['executions']:e.pop('collaboration_caller_pid',None)
        recovered=self.tools.call('start_run',dict(self.session,key=self.key,title='continued',request_id='recover',
                                                continue_run_id=old['id']))
        new=self.store.get(recovered['run_id'])
        self.assertEqual(new['timeline_id'],old['timeline_id'])
        self.assertEqual(new['tasks'][task['id']]['continuation_source']['run_id'],old['id'])
        self.engine.event(old['id'],'event','result',{'value':'original result'})
        self.engine.tick(old['id']);self.engine.tick(new['id'])
        updated=self.store.get(new['id'])
        self.assertEqual(updated['tasks'][task['id']]['status'],'completed')
        self.assertEqual(updated['records'][task['spec']['outputs']['value']['id']][-1]['value'],'original result')
        self.assertTrue(all(e['implementation']['kind']=='event' for e in updated['executions'] if e['node']=='work'))
        self.assertTrue(any(t.get('origin',{}).get('flow_agent',{}).get('task_id')==task['id'] for t in updated['tasks'].values()))

    def test_real_session_wake_waits_for_original_process_and_uses_exact_id(self):
        import subprocess
        sleeper=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        self.addCleanup(lambda: sleeper.poll() is None and sleeper.kill())
        target=self.root/'wake.json'
        code='import sys,pathlib,json;pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))'
        registered=self.tools.call('register_work_session', {
            'native_session':{'provider':'custom','id':'exact-original','cwd':str(self.root)},
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass'],
                'resume_command':[sys.executable,'-c',code,str(target),'{{session_id}}','{{prompt}}']},
            'process_id':sleeper.pid})
        t=self.tools.call('create_timeline',{})['timeline']
        monitor=self.tools.call('start_monitor',{'request_id':'wake-monitor','interval':60,
            'script':{'command':[sys.executable,'-c','print("{}")']}})['monitor']
        with work.transaction(self.store) as db:
            m=work.get(db,'monitor',monitor['id']);m['sample']={'at':time.time(),'data':{'ready':True}}
            m['next_at']=time.time()+60;work.put(db,'monitor',m)
        wait=self.tools.call('wait_for',dict(registered,timeline_id=t['id'],key='wake',
            sources={'m':{'kind':'monitor','id':monitor['id']}},
            condition={'op':'eq','args':[{'path':'m.data.ready'},True]}))['wait']
        self.engine.work.tick();self.assertFalse(target.exists())
        sleeper.terminate();sleeper.wait(timeout=5)
        self.engine.work.tick()
        for f in list(self.engine.futures):f.result(timeout=10)
        argv=json.loads(target.read_text())
        self.assertEqual(argv[0],'exact-original')
        self.assertIn(wait['id'],argv[1])
        self.tools.call('acknowledge_wait',dict(registered,wait_id=wait['id']))
        self.assertEqual(self.tools.call('read_wait',{'wait_id':wait['id']})['wait']['state'],'handled')

    def test_resumed_starter_claims_default_progression_and_completes_work(self):
        import subprocess
        sleeper=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        self.addCleanup(lambda: sleeper.poll() is None and sleeper.kill())
        script=self.root/'continue_agent.py'
        script.write_text("import sys\nsys.path.insert(0,"+repr(str(Path(__file__).resolve().parents[1]))+")\n"+"""
import json,sys
from loop_anything.runtime.store import Store
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.interfaces.agent_tasks import RunTools
context=json.loads(sys.argv[-1].split('\\n',1)[1])
store=Store(sys.argv[1]);tools=PlatformTools(store)
for request in context['run_requests']:
    claim=tools.call('claim_run',dict(run_id=request['run_id'],session_id=context['session_id'],session_token=context['session_token']))
    rt=RunTools(store,claim['run_id'],claim['token'])
    info=rt.call('read_task',{'task_id':claim['task_id']})
    rt.call('report_task',{'task_id':claim['task_id'],'report_id':'resumed-decision','event':'completed','envelope':{'outputs':{'decision':'All work is done'}}})
    state=rt.call('read_timeline',{})
    rt.call('change_settings',{'revision':state['settings']['revision'],'change':{'termination_signal':'Timeline task completed'}})
    rt.call('finish',{})
""")
        registered=self.tools.call('register_work_session',{
            'native_session':{'provider':'custom','id':'progression-owner','cwd':str(Path.cwd())},
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass'],
                'resume_command':[sys.executable,str(script),self.store.filename,'{{session_id}}','{{prompt}}']},
            'process_id':sleeper.pid})
        receipt=self.tools.call('start_run',dict(registered,key=self.key,title='progression',request_id='progression-start',
                                               objective='Finish the work',constraints='Local only'))
        self.initialize(receipt);self.engine.tick(receipt['run_id'])
        self.engine.event(receipt['run_id'],'complete-work','result',{'value':'done'})
        self.engine.tick(receipt['run_id'])
        sleeper.terminate();sleeper.wait(timeout=5)
        self.engine.work.tick()
        for f in list(self.engine.futures):f.result(timeout=10)
        self.engine.tick(receipt['run_id'])
        run=self.store.get(receipt['run_id'])
        self.assertEqual(run['status'],'completed',self.tools.call('read_work_session',registered))
        self.assertTrue(any(r['operation']=='decide' and r['status']=='completed' for r in run['steward_requests'].values()))
        self.assertEqual(self.tools.call('read_run_request',{'request_id':'progression-start'})['status'],'completed')

    def test_missing_timeline_is_checked_when_loading_that_run(self):
        import json
        receipt=self.start()
        with self.store.connection() as db:
            db.execute("UPDATE runs SET document=json_remove(document,'$.timeline_id') WHERE id=?",(receipt['run_id'],));db.commit()
            before=db.execute('SELECT document FROM runs WHERE id=?',(receipt['run_id'],)).fetchone()[0]
        with self.assertRaises(Invalid):Store(self.store.filename).get(receipt['run_id'])
        with self.store.connection() as db:
            self.assertEqual(before,db.execute('SELECT document FROM runs WHERE id=?',(receipt['run_id'],)).fetchone()[0])


    def test_timeline_rebind_after_finished_run_blocks_parallel_start(self):
        first=self.start();self.initialize(first)
        with self.store.edit(first['run_id']) as run:run['status']='completed'
        second=self.tools.call('start_run',dict(self.session,key=self.key,title='next',request_id='next',
                                               timeline_id=first['timeline_id']))
        with self.assertRaises(Conflict):
            self.tools.call('start_run',dict(self.session,key=self.key,title='parallel',request_id='parallel',
                                            timeline_id=first['timeline_id']))
        timeline=self.tools.call('read_work_timeline',{'timeline_id':first['timeline_id']})['timeline']
        self.assertEqual(timeline['active_run_id'],second['run_id'])

    def test_recovery_transfers_wait_recipient_without_changing_condition(self):
        first=self.start();self.initialize(first);self.engine.tick(first['run_id'])
        wait=self.tools.call('wait_for',dict(self.session,timeline_id=first['timeline_id'],key='external-wait',
            sources={'original':{'kind':'run','id':first['run_id']}},
            condition={'op':'eq','args':[{'path':'original.status'},'completed']}))['wait']
        next_session=self.tools.call('register_work_session',{
            'native_session':{'provider':'custom','id':'replacement'},
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass'],
                              'resume_command':[sys.executable,'-c','pass','{{session_id}}','{{prompt}}']},
            'process_id':os.getpid()})
        with self.store.edit(first['run_id']) as run:
            for e in run['executions']:e.pop('collaboration_caller_pid',None)
        self.tools.call('start_run',dict(next_session,key=self.key,title='recover',request_id='handoff-recovery',
                                        continue_run_id=first['run_id']))
        moved=self.tools.call('read_wait',{'wait_id':wait['id']})['wait']
        self.assertEqual(moved['sources'],wait['sources'])
        self.assertEqual(moved['condition'],wait['condition'])
        self.assertEqual(moved['session_id'],next_session['session_id'])
        self.tools.call('cancel_wait',dict(next_session,wait_id=wait['id']))

    def test_explicit_takeover_transfers_run_and_waits_in_one_transaction(self):
        first=self.start();self.initialize(first)
        wait=self.tools.call('wait_for',dict(self.session,timeline_id=first['timeline_id'],key='takeover-wait',
            sources={'run':{'kind':'run','id':first['run_id']}},
            condition={'op':'eq','args':[{'path':'run.status'},'completed']}))['wait']
        second=self.tools.call('register_work_session',{
            'native_session':{'provider':'custom','id':'takeover-owner'},
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass'],
                              'resume_command':[sys.executable,'-c','pass','{{session_id}}','{{prompt}}']},
            'process_id':os.getpid()})
        with self.store.edit(first['run_id']) as run:
            for e in run['executions']:e.pop('collaboration_caller_pid',None)
        with self.assertRaises(Conflict):
            self.tools.call('take_over_run',dict(second,run_id=first['run_id'],generation=0))
        self.assertEqual(self.tools.call('read_wait',{'wait_id':wait['id']})['wait']['session_id'],self.session['session_id'])
        claim=self.tools.call('take_over_run',dict(second,run_id=first['run_id'],generation=1))
        self.assertIn('token',claim)
        self.assertEqual(self.store.get(first['run_id'])['steward']['session_id'],second['session_id'])
        self.assertEqual(self.tools.call('read_wait',{'wait_id':wait['id']})['wait']['session_id'],second['session_id'])
