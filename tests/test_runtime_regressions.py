"""Counterexamples from the team-runtime semantic audit, using only disposable processes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import test_team_runtime as team
import test_timeline_runtime as fixture
from loop_anything.runtime.executor_client import Receiver
from loop_anything.runtime.executors import RemotePending,run as remote_run
from loop_anything.runtime.local_tasks import TaskRegistry,LocalRuntime
from loop_anything.runtime.host_runtime import CommandNotStopped
from loop_anything.runtime.lifecycle import template
from loop_anything.runtime.tool_mailbox import ToolMailbox
from loop_anything.runtime.team_transport import core


class RuntimeRegressionTests(unittest.TestCase):
    setUp=team.TeamRuntimeTests.setUp
    tearDown=team.TeamRuntimeTests.tearDown
    pump=team.TeamRuntimeTests.pump
    setup_service=team.TeamRuntimeTests.setup_service
    settled=team.TeamRuntimeTests.settled

    def test_received_cancellation_prevents_launch(self):
        store,engine,box,client=self.setup_service()
        receiver=Receiver({'server':engine.platform_url},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync();effect=self.root/'effect'
        call=lambda:remote_run(engine,{'kind':'command','executor':receiver.ident},
            [sys.executable,'-c','from pathlib import Path;Path('+repr(str(effect))+').touch()'],
            '',5,None,engine.stopping,None,'cancel-before-start',{})
        with self.assertRaises(RemotePending):call()
        engine.executors.control('cancel-before-start',reason='revoked');engine.executors.sync()
        # Let a submitted worker run to completion before the polling thread continues.
        submit=receiver.pool.submit
        def complete_first(*args,**kwargs):
            future=submit(*args,**kwargs);future.result(timeout=5);return future
        with patch.object(receiver.pool,'submit',side_effect=complete_first):receiver.tick()
        engine.executors.sync()
        self.assertFalse(effect.exists())
        self.assertEqual(engine.executors.get('cancel-before-start')['execution_state'],'not_started')
        self.assertEqual(call().returncode,0)

    def test_offline_calls_release_all_service_workers(self):
        store,engine,box,client=self.setup_service()
        engine.executors.register({'id':'offline','name':'Offline','owner':'one','heartbeat':0})
        futures=[engine.pool.submit(remote_run,engine,{'kind':'command','executor':'offline'},
            ['must-not-run'],'',None,None,engine.stopping,None,'pending-'+str(i),{}) for i in range(16)]
        for future in futures:
            with self.assertRaises(RemotePending):future.result(timeout=5)
        self.assertEqual(engine.pool.submit(lambda:'local work').result(timeout=2),'local work')
        self.assertEqual(len(engine.executors.calls()),16)
        self.assertTrue(all(j['state']=='queued' for j in engine.executors.calls()))

    def test_large_http_result_retries_delivery_without_reexecuting(self):
        base=fixture.RuntimeTests();base.setUp();self.addCleanup(base.tearDown)
        engine=base.engine;receiver=Receiver({'server':'http://unused'},self.root/'receiver');self.addCleanup(receiver.close)
        effect=self.root/'effects';lost=[False];crashed=[False]
        save=engine.executors.save
        def crash_before_database_commit(db,job):
            if job.get('result_file') and not crashed[0]:
                crashed[0]=True;raise OSError('Stopped after result rename, before database commit')
            return save(db,job)
        def request(url,name,arguments):
            if name=='executor_poll':return dict(ok=True,**engine.executors.poll(arguments['worker']))
            answer=engine.executors.report(arguments['id'],arguments['token'],arguments['update'])
            if arguments['update'].get('result_chunk') and not lost[0]:
                lost[0]=True;raise OSError('Lost chunk acknowledgement')
            return dict(ok=True,**answer)
        size=2100000
        with patch('loop_anything.runtime.executor_client.request',side_effect=request),patch.object(engine.executors,'save',side_effect=crash_before_database_commit):
            receiver.tick();matrix=template('command')
            for rule in matrix['transitions']:
                if rule['event']=='process_error':rule['to']='retry'
            code='import json;from pathlib import Path;p=Path('+repr(str(effect))+');p.write_text(p.read_text()+"x" if p.exists() else "x");print(json.dumps({"outputs":{"text":"x"*'+str(size)+'}}))'
            base.implementations['produce']={'kind':'command','executor':receiver.ident,'command':[sys.executable,'-c',code],'lifecycle':matrix}
            base.initialize([fixture.task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
            def tick():
                try:receiver.tick()
                except OSError:pass
                engine.tick(base.id)
            self.pump(tick,lambda:base.read()['tasks']['job']['status']=='completed' and self.settled(engine),15)
        self.assertTrue(lost[0]);self.assertTrue(crashed[0]);self.assertEqual(effect.read_text(),'x')
        self.assertEqual(base.read()['tasks']['job']['attempts'],1)
        self.assertEqual(base.read()['records']['out'][-1]['value'],'x'*size)

    def test_nas_result_larger_than_transport_limit_survives_receiver_restart(self):
        store,engine,box,client=self.setup_service()
        receiver=Receiver({'server':engine.platform_url},self.root/'receiver')
        self.addCleanup(receiver.close);receiver.tick();engine.executors.sync()
        size=33*1024*1024;effect=self.root/'effects'
        code='from pathlib import Path;p=Path('+repr(str(effect))+');p.write_text(p.read_text()+"x" if p.exists() else "x");print("z"*'+str(size)+',end="")'
        call=lambda:remote_run(engine,{'kind':'command','executor':receiver.ident},[sys.executable,'-c',code],
            '',10,None,engine.stopping,None,'large-nas',{})
        with self.assertRaises(RemotePending):call()
        engine.executors.sync();receiver.tick()
        self.pump(lambda:None,lambda:receiver.jobs['large-nas']['future'].done())
        self.assertEqual(receiver.jobs['large-nas']['update']['state'],'delivering')
        receiver.close()
        replacement=Receiver({'server':engine.platform_url},self.root/'receiver');self.addCleanup(replacement.close)
        engine.executors.sync()  # Observe the old receiver's offline heartbeat before takeover.
        self.pump(lambda:(replacement.tick(),engine.executors.sync()),lambda:engine.executors.get('large-nas')['state']=='completed',20)
        self.assertEqual(call().stdout,'z'*size);self.assertEqual(effect.read_text(),'x')

    def test_killed_scheduler_cannot_restart_its_surviving_action(self):
        registry=TaskRegistry(self.root/'personal');pids=self.root/'pids'
        code='import os,time;from pathlib import Path;p=Path('+repr(str(pids))+');p.open("a").write(str(os.getpid())+"\\n");time.sleep(30)'
        ident=registry.register({'name':'Controlled action','every':.01,'repeat':False,'command':[sys.executable,'-c',code]})['id']
        argv=[sys.executable,'-m','loop_anything','local','--root',str(registry.root),'start',ident]
        process=subprocess.Popen(argv,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            self.pump(lambda:None,lambda:pids.exists() and bool(pids.read_text().strip()))
            self.pump(lambda:None,lambda:bool(registry.show(ident)['execution'].get('pid')))
            process.kill();process.wait(5)
            pid=int(pids.read_text().strip());os.kill(pid,0)
            second=subprocess.run(argv,capture_output=True,text=True,timeout=5)
            self.assertNotEqual(second.returncode,0);self.assertIn('Previous action',second.stderr)
            self.assertEqual(len(pids.read_text().splitlines()),1)
            execution=registry.show(ident)['execution']
            self.assertEqual(execution['pid'],pid)
            with self.assertRaises(ValueError):registry.confirm_stopped(ident,'wrong-execution',True)
            with self.assertRaises(ValueError):registry.confirm_stopped(ident,execution['id'])
            os.killpg(pid,signal.SIGTERM)
            registry.confirm_stopped(ident,execution['id'],True)
            effect=self.root/'restarted'
            registry.register({'name':'Controlled action','every':.01,'repeat':False,
                'command':[sys.executable,'-c','from pathlib import Path;Path('+repr(str(effect))+').touch()']},ident)
            LocalRuntime(registry,[ident]).run();self.assertTrue(effect.exists())
        finally:
            if process.poll() is None:process.kill();process.wait(5)
            if pids.exists():
                for pid in map(int,pids.read_text().splitlines()):
                    try:os.killpg(pid,signal.SIGTERM)
                    except ProcessLookupError:pass

    def test_business_text_is_verbatim_across_client_and_receiver_mounts(self):
        from loop_anything.runtime.agent_prompt import process_prompt
        store,engine,box,client=self.setup_service();alias=self.root/'client';alias.symlink_to(box.root,target_is_directory=True)
        name=str(alias/'literal-name');url='nas://'+str(alias)
        client.invoke(url,'create_loop',{'name':name},'literal-name',0);box.tick()
        self.assertEqual(store.drafts()[0]['loop_definition']['name'],name)
        client.invoke(url,'arbitrary',{},'literal-result',0)
        payload={'result':{'cwd':str(box.root/'not-a-path-field'),'text':str(box.root/'literal-result')}}
        with patch.object(box,'dispatch',return_value=payload):box.tick()
        self.assertEqual(client.result(url,'literal-result'),payload)
        receiver=Receiver({'server':url},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync()
        text=str(box.root/'literal-business-text')
        context={'message':text,'inputs':{'cwd':text},'handbook':{'text':text,'resolved_path':str(box.root/'guide.md')},'platform_url':engine.platform_url}
        config={'kind':'command','executor':receiver.ident}
        prompt=process_prompt(config,context)
        command=[sys.executable,'-c','import sys,json;print(json.dumps({"context":json.load(sys.stdin),"argument":sys.argv[1]}))',text]
        call=lambda:remote_run(engine,config,command,prompt,5,None,engine.stopping,None,'literal-context',{})
        with self.assertRaises(RemotePending):call()
        self.pump(lambda:(engine.executors.sync(),receiver.tick()),lambda:engine.executors.get('literal-context')['state']=='completed')
        result=json.loads(call().stdout)
        self.assertEqual(result['argument'],text);self.assertEqual(result['context']['message'],text)
        self.assertEqual(result['context']['inputs'],context['inputs']);self.assertEqual(result['context']['handbook']['text'],text)
        self.assertEqual(result['context']['handbook']['resolved_path'],str(alias/'guide.md'))
        self.assertEqual(result['context']['platform_url'],url)

    def test_remote_external_submit_and_observe_keep_original_task_and_job(self):
        base=fixture.RuntimeTests();base.setUp();self.addCleanup(base.tearDown)
        engine=base.engine;box=ToolMailbox(base.store,self.root/'team',engine)
        engine.platform_url='nas://'+str(box.root);engine.executors.root=box.root
        receiver=Receiver({'server':engine.platform_url},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync()
        base.implementations['produce']={'kind':'external','executor':receiver.ident,
            'command':[sys.executable,'-c','print(\'{"status":"waiting","external_id":"training-job","poll_after":0.01}\')'],
            'observe':[sys.executable,'-c','import sys,json;c=json.load(sys.stdin);assert c["external_id"]=="training-job";print(\'{"outputs":{"text":"training-result"}}\')']}
        base.initialize([fixture.task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
        self.pump(lambda:(engine.executors.sync(),receiver.tick(),engine.tick(base.id)),
            lambda:base.read()['tasks']['job']['status']=='completed' and self.settled(engine),15)
        self.assertEqual(base.read()['records']['out'][-1]['value'],'training-result')
        self.assertEqual(base.read()['tasks']['job']['attempts'],1)
        calls=engine.executors.calls();self.assertEqual(len(calls),2)
        self.assertEqual(len({c['metadata']['execution_id'] for c in calls}),1)
        self.assertEqual({c['metadata']['observe'] for c in calls},{True,False})


if __name__=='__main__':unittest.main()
