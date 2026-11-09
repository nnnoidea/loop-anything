"""Shared kernel, NAS tool access, and headless execution without a second platform."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from loop_anything.runtime.local_tasks import TaskRegistry, LocalRuntime
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.tool_mailbox import ToolMailbox
from loop_anything.runtime.tool_client import module
from loop_anything.runtime.executor_client import Receiver
from loop_anything.runtime.executors import run as remote_run, RemotePending
from loop_anything.runtime.host_runtime import CommandNotStopped
from loop_anything.runtime.team_transport import core
import test_timeline_runtime as fixture
from test_timeline_runtime import task_spec


class TeamRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,LOOP_ANYTHING_IDENTITY_DIR=str(self.root/'identity'))
        self.env.start()

    def tearDown(self):self.env.stop();self.tmp.cleanup()

    def pump(self, fn, predicate, timeout=10):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            fn()
            if predicate():return
            time.sleep(.03)
        self.fail('Timed out')

    def settled(self, engine):
        return not engine.executors.waiting and not engine.executors.completing and all(f.done() for f in engine.futures)

    def test_personal_registry_never_autostarts_and_retains_completed_configuration(self):
        registry=TaskRegistry(self.root/'personal');target=self.root/'ran'
        definition={'name':'Backup','every':.05,'repeat':False,
            'command':[sys.executable,'-c','from pathlib import Path; Path('+repr(str(target))+').write_text("done")']}
        ident=registry.register(definition)['id']
        self.assertFalse(target.exists());self.assertEqual(registry.list()[0]['runtime']['status'],'registered')
        runtime=LocalRuntime(registry,[ident]);runtime.run()
        self.assertEqual(target.read_text(),'done')
        saved=registry.show(ident);self.assertEqual(saved['runtime']['status'],'completed')
        target.unlink();self.assertEqual(TaskRegistry(registry.root).list()[0]['definition'],definition)
        time.sleep(.1);self.assertFalse(target.exists())
        # No startup of another task just because this runtime starts.
        other=registry.register(dict(definition,name='Other'))['id']
        LocalRuntime(registry,[other]).run()
        self.assertEqual(registry.show(ident)['runtime'],saved['runtime'])

    def test_condition_wait_then_run_once_and_definition_edit_does_not_hold_execution_lock(self):
        registry=TaskRegistry(self.root/'personal');flag=self.root/'ready';done=self.root/'done'
        ident=registry.register({'name':'Watch','every':.05,
            'check':[sys.executable,'-c','import sys;from pathlib import Path;sys.exit(0 if Path('+repr(str(flag))+').exists() else 1)'],
            'command':[sys.executable,'-c','from pathlib import Path;Path('+repr(str(done))+').write_text("ok")']})['id']
        runtime=LocalRuntime(registry,[ident]);thread=threading.Thread(target=runtime.run);thread.start()
        try:
            time.sleep(.2);self.assertFalse(done.exists())
            updated=registry.show(ident)['definition'];updated['description']='Updated for next start'
            registry.register(updated,ident)
            with self.assertRaises(Exception):LocalRuntime(registry,[ident])
            flag.touch();thread.join(timeout=5);self.assertFalse(thread.is_alive())
            self.assertEqual(registry.show(ident)['runtime']['status'],'completed')
        finally:runtime.stop.set();thread.join(timeout=5)

    def setup_service(self):
        store=Store(self.root/'team/platform.sqlite3',journal_mode='DELETE');store.hosting_team=True
        engine=Engine(store);self.addCleanup(engine.close)
        box=ToolMailbox(store,self.root/'team',engine)
        engine.platform_url='nas://'+str(box.root);engine.executors.root=box.root
        return store,engine,box,module('platform_transport')

    def test_nas_tools_are_idempotent_and_use_existing_platform_contracts(self):
        store,engine,box,client=self.setup_service()
        pending=client.invoke(engine.platform_url,'create_loop',{'name':'Shared'},'api-once',wait=0)
        self.assertTrue(pending['pending']);box.tick()
        answer=client.result(engine.platform_url,'api-once');self.assertTrue(answer['ok'],answer)
        self.assertEqual(client.invoke(engine.platform_url,'create_loop',{'name':'Shared'},'api-once',0),answer)
        self.assertEqual(len(store.drafts()),1)
        with self.assertRaises(ValueError):client.invoke(engine.platform_url,'create_loop',{'name':'Changed'},'api-once',0)
        with store.connection() as db:self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'delete')
        with Store(store.filename).connection() as db:self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'delete')

    def test_report_client_loaded_by_path_submits_and_observes_over_nas(self):
        base=fixture.RuntimeTests();base.setUp();self.addCleanup(base.tearDown)
        engine=base.engine;box=ToolMailbox(base.store,self.root/'team',engine)
        engine.platform_url='nas://'+str(box.root)
        script=self.root/'handler.py';done=self.root/'reported'
        script.write_text('''import importlib.util,json,sys
from pathlib import Path
context=json.load(sys.stdin)
assert str(Path(context['report_client']).parent) not in sys.path
spec=importlib.util.spec_from_file_location('reporter',context['report_client'])
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
if not context['observing']:
    client.notify(context,'started','Starting',route='workspace')
    client.report(context,'submitted',report_id='submitted',external_id='nas-job',poll_after=.01)
else:
    fields={'report_id':'done','envelope':{'outputs':{'text':'NAS result'}}}
    assert client.report(context,'completed',**fields)['accepted']
    assert client.report(context,'completed',**fields)['duplicate']
    assert client.report(context,'progress',report_id='late')['stale']
    Path(sys.argv[1]).write_text('verified')
''')
        command=[sys.executable,'-I',str(script),str(done)]
        base.implementations['produce']={'kind':'external','command':command,'observe':command}
        base.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
        self.pump(lambda:(box.tick(),engine.tick(base.id)),
                  lambda:base.read()['tasks']['job']['status'] in ('completed','fault') and self.settled(engine),15)
        run=base.read()
        self.assertEqual(run['tasks']['job']['status'],'completed',run['history'])
        self.assertEqual(run['records']['out'][-1]['value'],'NAS result')
        self.assertEqual(done.read_text(),'verified')
        self.assertTrue(any(n['message']=='Starting' for n in run['notifications']))

    def test_interrupted_tool_is_unknown_without_repeating_effect(self):
        store,engine,box,client=self.setup_service()
        client.invoke(engine.platform_url,'create_loop',{'name':'One'},'api-crash',wait=0)
        original=box.dispatch
        def crash(packet):original(packet);raise KeyboardInterrupt()
        with patch.object(box,'dispatch',side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):box.tick()
        box=ToolMailbox(store,box.root,engine);box.tick()
        self.assertTrue(client.result(engine.platform_url,'api-crash')['outcome_unknown'])
        self.assertEqual(len(store.drafts()),1)

    def test_receiver_executes_without_http_and_replayed_packet_cannot_spawn_again(self):
        store,engine,box,client=self.setup_service()
        receiver=Receiver({'server':engine.platform_url,'name':'CPU'},self.root/'receiver')
        self.addCleanup(receiver.close);receiver.tick();engine.executors.sync()
        target=self.root/'effects';out=[]
        command=[sys.executable,'-c','from pathlib import Path;p=Path('+repr(str(target))+');p.write_text(p.read_text()+"x" if p.exists() else "x");print("complete")']
        call=lambda:remote_run(engine,{'kind':'command','executor':receiver.ident},command,'',10,None,engine.stopping,None,'call-once',{})
        with self.assertRaises(RemotePending):call()
        self.pump(lambda:(engine.executors.sync(),receiver.tick()),lambda:engine.executors.get('call-once')['state']=='completed')
        self.assertEqual(call().stdout.strip(),'complete');self.assertEqual(target.read_text(),'x')
        packet=engine.executors.packet(engine.executors.get('call-once'))
        self.pump(lambda:(engine.executors.sync(),receiver.tick()),lambda:not receiver.jobs)
        core.publish_message(box.root/'executors'/receiver.ident/'inbox/call-once.json',packet)
        receiver.tick();time.sleep(.1);self.assertEqual(target.read_text(),'x')

    def test_remote_command_advances_existing_timeline(self):
        base=fixture.RuntimeTests();base.setUp();self.addCleanup(base.tearDown)
        engine=base.engine;box=ToolMailbox(base.store,self.root/'team',engine)
        engine.platform_url='nas://'+str(box.root);engine.executors.root=box.root
        receiver=Receiver({'server':engine.platform_url},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync()
        base.implementations['produce']={'kind':'command','executor':receiver.ident,
            'command':[sys.executable,'-c','import json;print(json.dumps({"outputs":{"text":"remote-result"}}))']}
        base.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
        self.pump(lambda:(engine.executors.sync(),receiver.tick()),lambda:base.read()['tasks']['job']['status']=='completed')
        self.assertEqual(base.read()['records']['out'][-1]['value'],'remote-result')
        for future in list(engine.futures):future.result(timeout=5)

    def test_service_restart_reattaches_same_remote_process(self):
        base=fixture.RuntimeTests();base.setUp();self.addCleanup(base.tearDown)
        engine=base.engine;box=ToolMailbox(base.store,self.root/'team',engine)
        engine.platform_url='nas://'+str(box.root);engine.executors.root=box.root
        receiver=Receiver({'server':engine.platform_url},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync();began=self.root/'began';release=self.root/'release'
        code='import time,json;from pathlib import Path;p=Path('+repr(str(began))+');p.write_text(p.read_text()+"x" if p.exists() else "x")\nwhile not Path('+repr(str(release))+').exists():time.sleep(.02)\nprint(json.dumps({"outputs":{"text":"survived"}}))'
        base.implementations['produce']={'kind':'command','executor':receiver.ident,'command':[sys.executable,'-c',code]}
        base.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
        self.pump(lambda:(engine.executors.sync(),receiver.tick()),lambda:began.exists())
        engine.close()
        replacement=Engine(base.store);self.addCleanup(replacement.close)
        replacement.platform_url=engine.platform_url;replacement.executors.root=box.root;replacement.recover()
        release.touch()
        self.pump(lambda:(replacement.executors.sync(),receiver.tick()),lambda:base.read()['tasks']['job']['status']=='completed')
        self.assertEqual(began.read_text(),'x')
        self.assertEqual(base.read()['records']['out'][-1]['value'],'survived')

    def test_remote_agent_uses_nas_tools_and_records_native_session(self):
        base=fixture.RuntimeTests();base.setUp();self.addCleanup(base.tearDown)
        engine=base.engine;box=ToolMailbox(base.store,self.root/'team',engine)
        engine.platform_url='nas://'+str(box.root);engine.executors.root=box.root
        receiver=Receiver({'server':engine.platform_url},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync()
        code=r'''import json,sys
from pathlib import Path
c=json.loads(sys.stdin.read().rsplit('Run context:\n',1)[1])
sys.path.insert(0,str(Path(c['platform_client']).parent))
from call import fetch
def call(name,args):
 args.update(run_id=c['run_id'],token=c['token'])
 result=fetch(c['platform_url']+'/api/tools',json.dumps({'tool':name,'arguments':args}).encode())
 assert result.get('ok') and not result.get('pending'),result
 return result
call('register_agent_session',{'execution_id':c['execution_id'],'provider':'custom','session_id':'original-session'})
info=call('read_task',{'task_id':c['task_id']})
call('report_task',{'task_id':c['task_id'],'task_version':info['task_version'],'event':'completed','report_id':'complete-one','envelope':{'outputs':{'text':'from-agent'}}})
call('finish',{})
'''
        base.implementations['produce']={'kind':'agent','executor':receiver.ident,'command':[sys.executable,'-c',code],
            'resume_command':[sys.executable,'-c','pass','{{session_id}}','{{prompt}}']}
        base.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
        self.pump(lambda:(box.tick(),engine.executors.sync(),receiver.tick()),
            lambda:base.read()['tasks']['job']['status']=='completed' and self.settled(engine),timeout=20)
        self.assertEqual(base.read()['records']['out'][-1]['value'],'from-agent')
        execution=next(e for e in base.read()['executions'] if e['task_id']=='job')
        self.assertEqual(execution['native_session']['id'],'original-session')
        from loop_anything.interfaces.platform_tools import PlatformTools
        tools=PlatformTools(base.store);ids={'run_id':base.id,'execution_id':execution['id']}
        prepared=tools.respond('read_execution_session',dict(ids,prepare=True))
        self.assertEqual(prepared['native_session']['id'],'original-session')
        before=base.read()['records'];marker=self.root/'resumed'
        continuation="""import json,sys
from pathlib import Path
assert sys.argv[1]=='original-session'
c=json.loads(Path(sys.argv[2]).read_text().rsplit('Run context:'+chr(10),1)[1])
sys.path.insert(0,str(Path(c['platform_client']).parent))
from call import fetch
Path(sys.argv[3]).write_text(sys.argv[1])
r=fetch(c['platform_url']+'/api/tools',json.dumps({'tool':'finish','arguments':{'run_id':c['run_id'],'token':c['token']}}).encode())
assert r.get('ok'),r
"""
        restored=tools.respond('control_execution_session',dict(ids,action='resume',continuation={
            'provider':'custom','native_session_id':'original-session','message':'Explain the previous result',
            'command':[sys.executable,'-c',continuation,'{{session_id}}','{{prompt_file}}',str(marker)]}))
        self.assertTrue(restored['ok'],restored)
        self.pump(lambda:(box.tick(),engine.executors.sync(),receiver.tick()),lambda:self.settled(engine),20)
        self.assertTrue(marker.exists(),engine.terminals.read(base.id,execution['id']))
        self.assertEqual(marker.read_text(),'original-session');self.assertEqual(base.read()['records'],before)


    def test_headless_service_cli_and_portable_nas_client(self):
        root=self.root/'cli-team'
        process=subprocess.Popen([sys.executable,'-m','loop_anything','serve','--team-dir',str(root),'--no-web','--allow-sleep'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.pump(lambda:None,lambda:(root/'team.json').exists())
            duplicate=subprocess.run([sys.executable,'-m','loop_anything','serve','--team-dir',str(root),'--no-web','--allow-sleep'],capture_output=True,text=True,timeout=5)
            self.assertNotEqual(duplicate.returncode,0)
            self.assertIn('already owns',duplicate.stderr)
            script=Path(__file__).resolve().parents[1]/'skills/loop-anything-platform/scripts/call.py'
            result=subprocess.run([sys.executable,str(script),'create_loop','--url','nas://'+str(root),
                '--arguments','{"name":"Terminal only"}'],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertTrue(json.loads(result.stdout)['ok'])
        finally:
            process.terminate();out,err=process.communicate(timeout=10)
        self.assertEqual(process.returncode,0,out+err)
        with Store(root/'platform.sqlite3').connection() as db:self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'delete')

    def test_bad_mailbox_entry_does_not_block_valid_work(self):
        store,engine,box,client=self.setup_service()
        (box.root/'api/requests/aaa-bad.json').write_text('{')
        client.invoke(engine.platform_url,'create_loop',{'name':'Valid'},'api-valid',0)
        box.tick()
        self.assertFalse(client.result(engine.platform_url,'aaa-bad')['ok'])
        self.assertTrue(client.result(engine.platform_url,'api-valid')['ok'])

    def test_receiver_retries_outage_and_stop_closes_it_while_other_tasks_continue(self):
        registry=TaskRegistry(self.root/'personal')
        ident=registry.register({'name':'Receiver','every':.01,'receiver':{'server':'http://127.0.0.1:1'}})['id']
        other=registry.register({'name':'Later','every':100,'command':['unused']})['id']
        runtime=LocalRuntime(registry,[ident,other]);self.addCleanup(runtime.close)
        with patch.object(Receiver,'tick',side_effect=OSError('temporarily offline')):
            runtime.move(runtime.items[ident],'due');runtime.execute(ident)
        self.assertEqual(registry.show(ident)['runtime']['status'],'waiting')
        with patch.object(Receiver,'tick'):
            runtime.move(runtime.items[ident],'due');runtime.execute(ident)
        self.assertNotIn('error',registry.show(ident)['runtime'])
        registry.stop(ident);runtime.last_control=0;runtime.tick()
        self.assertTrue(runtime.items[ident]['receiver'].closed)
        self.assertFalse(runtime.stop.is_set())

    def test_http_receiver_and_remote_terminal_input_use_existing_session(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from loop_anything.interfaces.platform_tools import PlatformTools
        store,engine,box,client=self.setup_service();platform=PlatformTools(store)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                body=json.dumps(platform.respond(data['tool'],data['arguments'])).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        serving=threading.Thread(target=server.serve_forever);serving.start()
        self.addCleanup(lambda:(server.shutdown(),serving.join(),server.server_close()))
        receiver=Receiver({'server':'http://127.0.0.1:'+str(server.server_port)},self.root/'receiver')
        self.addCleanup(receiver.close);receiver.tick()
        session=engine.terminals.create('run','attempt','terminal-remote',True)
        command=[sys.executable,'-u','-c',"import os;print('ready');print('received:'+input());print(os.get_terminal_size())",'{{prompt}}']
        call=lambda:remote_run(engine,{'kind':'agent','terminal':True,'executor':receiver.ident},command,'hello',10,None,engine.stopping,session,'terminal-remote',{})
        with self.assertRaises(RemotePending):call()
        self.pump(receiver.tick,lambda:'ready' in str(engine.terminals.read('run','attempt')['output']) and session.writable())
        engine.terminals.control('run','attempt','terminal-remote',cols=121,rows=39,data='from-user\n')
        self.pump(receiver.tick,lambda:engine.executors.get('terminal-remote')['state']=='completed')
        self.assertEqual(call().returncode,0)
        output=str(engine.terminals.read('run','attempt')['output'])
        self.assertIn('received:from-user',output);self.assertIn('columns=121',output)

    def test_public_authoring_can_select_executor(self):
        from loop_anything.interfaces.platform_tools import PlatformTools
        from loop_anything.capabilities import required_capabilities
        store,engine,box,client=self.setup_service();tools=PlatformTools(store)
        created=tools.respond('create_loop',{'name':'Shared'})
        result=tools.respond('set_implementation',{k:created[k] for k in ('draft_id','revision')}|
            {'node_id':'initialize','kind':'agent','executor':'executor-test','command':['my-cli']})
        self.assertTrue(result['ok'],result)
        saved=tools.call('read_loop',{'draft_id':created['draft_id']})['loop']
        self.assertIn('headless_execution',required_capabilities(saved['loop_definition'],saved['implementations']))

    def test_remote_agent_assistance_resumes_exact_session_over_nas(self):
        from test_assistance_resume import NODE_CLI,HELPER_CLI
        from loop_anything.paths import platform_skill_directory
        base=fixture.RuntimeTests();base.setUp();self.addCleanup(base.tearDown)
        engine=base.engine;box=ToolMailbox(base.store,self.root/'team',engine)
        engine.platform_url='nas://'+str(box.root);engine.executors.root=box.root
        receiver=Receiver({'server':engine.platform_url,'capacity':2},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync()
        prefix='import sys\nsys.path.insert(0,'+repr(str(platform_skill_directory()/'scripts'))+')\nfrom call import fetch\n'
        node=NODE_CLI.replace(" r=Request(c['platform_url']+'/api/tools',data=json.dumps({'tool':name,'arguments':args}).encode(),headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})\n with urlopen(r,timeout=30) as f:v=json.load(f)",
            " v=fetch(c['platform_url']+'/api/tools',json.dumps({'tool':name,'arguments':args}).encode())")
        helper=HELPER_CLI.replace("with urlopen(r,timeout=10) as f:assert json.load(f)['ok']","assert fetch(c['platform_url']+'/api/tools',r.data)['ok']")
        script=self.root/'node.py';script.write_text(prefix+node)
        state=self.root/'session.json'
        from loop_anything.interfaces.platform_tools import PlatformTools
        PlatformTools(base.store).call('communication_config',{'operation':'agent','agent_id':'helper','agent':{'name':'helper','description':'Find paper','local':True,
            'implementation':{'kind':'agent','executor':receiver.ident,'command':[sys.executable,'-c',prefix+helper],'prompt':'{{context}}'}}})
        base.implementations['init']={'kind':'agent','executor':receiver.ident,'terminal':True,'agent_cli':'custom','prompt':'{{context}}',
            'command':[sys.executable,str(script),str(state),'new','{{session_id}}','{{prompt}}'],
            'resume_command':[sys.executable,str(script),str(state),'resume','{{session_id}}','{{prompt}}']}
        key=base.store.publish(base.bp,base.implementations)['key'];rid=base.store.create(key,'wait remotely')['id']
        def tick():
            box.tick();engine.executors.sync();receiver.tick();engine.communication.tick();engine.tick(rid)
        self.pump(tick,lambda:base.store.get(rid)['tasks']['init']['status'] in ('completed','fault') and self.settled(engine),30)
        run=base.store.get(rid)
        self.assertEqual(run['tasks']['init']['status'],'completed',run['history'])
        memory=json.loads(state.read_text());self.assertEqual(memory['calls'],['new','resume'])
        self.assertEqual([e['native_session']['id'] for e in run['executions']],[memory['session']]*2)
        self.assertEqual(run['records']['a'][0]['value'],'reasoning-before-assistance')
        self.assertEqual(run['records']['b'][0]['value'],'paper-found')

    def test_interrupted_receiver_receipt_is_unknown_and_not_reexecuted(self):
        store,engine,box,client=self.setup_service()
        receiver=Receiver({'server':engine.platform_url},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync();effect=self.root/'must-not-run'
        command=[sys.executable,'-c','from pathlib import Path;Path('+repr(str(effect))+').touch()']
        call=lambda:remote_run(engine,{'kind':'command','executor':receiver.ident},command,'',10,None,engine.stopping,None,'call-interrupted',{})
        with self.assertRaises(RemotePending):call()
        self.pump(engine.executors.sync,lambda:(box.root/'executors'/receiver.ident/'inbox/call-interrupted.json').exists())
        packet=engine.executors.packet(engine.executors.get('call-interrupted'))
        core.atomic_json(receiver.file('call-interrupted'),{'packet':packet,'update':{'state':'starting','sequence':1,'control_cursor':0}})
        self.pump(lambda:(receiver.tick(),engine.executors.sync()),lambda:engine.executors.get('call-interrupted')['state']=='unknown')
        with self.assertRaises(CommandNotStopped):call()
        self.assertFalse(effect.exists())
        self.assertTrue(engine.executors.confirm_stopped('call-interrupted')['confirmed'])

    def test_reconnect_terminal_preserves_output_cursor_and_cli_queries(self):
        from loop_anything.runtime.process_session import ProcessSession
        from loop_anything.runtime.host_runtime import run_command
        store,engine,box,client=self.setup_service()
        original=engine.terminals.create('run','attempt','one')
        original.append('stdout','before\n')
        restored=engine.terminals.attach('one');restored.append('stdout','after\n')
        self.assertEqual(len(engine.terminals.read('run','attempt')['output']),2)
        session=ProcessSession('local-pty',{'terminal':True})
        code="import os,tty;tty.setraw(0);os.write(1,b'abc\\x1b[6n');assert os.read(0,64)==b'\\x1b[1;4R';print('query-ok')"
        result=run_command([sys.executable,'-c',code],'',3,session=session)
        self.assertEqual(result.returncode,0);self.assertIn('query-ok',result.stdout)

    def test_team_paths_follow_client_mount_and_service_move(self):
        from loop_anything.interfaces.platform_tools import PlatformTools
        from loop_anything.packaging.packages import load_installed
        store,engine,box,client=self.setup_service()
        tools=PlatformTools(store);draft=tools.call('create_loop',{'name':'Portable'})
        draft=tools.call('set_loop',{k:draft[k] for k in ('draft_id','revision')}|{'handbook':'Portable team workflow.'})
        saved=tools.call('set_implementation',{k:draft[k] for k in ('draft_id','revision')}|
            {'node_id':'initialize','kind':'agent','command':['unused']})
        key=tools.call('publish_loop',{'draft_id':draft['draft_id'],'revision':saved['revision']})['key']
        old=str(box.root);alias=self.root/'client-mount';alias.symlink_to(box.root,target_is_directory=True)
        client.invoke('nas://'+str(alias),'_platform',request_id='client-path',wait=0);box.tick()
        self.assertEqual(client.result('nas://'+str(alias),'client-path')['database'],str(alias/'platform.sqlite3'))
        changed=client.mount_path(old+'/file',[old],old+'/new')
        self.assertEqual(client.mount_path(changed,[old,old+'/new'],old+'/new'),changed)
        workspace=engine.communication.settings()['instance_id']
        engine.close();moved=self.root/'new-service-mount';box.root.rename(moved)
        with patch.dict(os.environ,LOOP_ANYTHING_IDENTITY_DIR=str(self.root/'other-machine')):
            replacement_store=Store(moved/'platform.sqlite3');replacement_store.hosting_team=True
            replacement=Engine(replacement_store);self.addCleanup(replacement.close)
            ToolMailbox(replacement_store,moved,replacement)
            self.assertFalse(replacement.communication.identity_conflict)
            self.assertEqual(replacement.communication.settings()['instance_id'],workspace)
            document,package=load_installed(replacement_store.filename,key)
            self.assertTrue(package.is_dir());self.assertIn(str(moved),str(package))
            self.assertEqual(replacement.mounted_path(old+'/file'),str(moved.resolve()/'file'))

    def test_unknown_remote_script_claim_survives_service_restart_until_confirmed(self):
        from loop_anything.interfaces.platform_tools import PlatformTools
        from loop_anything.runtime.model import Conflict
        base=fixture.RuntimeTests();base.setUp();self.addCleanup(base.tearDown)
        engine=base.engine;box=ToolMailbox(base.store,self.root/'team',engine)
        engine.platform_url='nas://'+str(box.root);engine.executors.root=box.root
        receiver=Receiver({'server':engine.platform_url},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync()
        base.implementations['produce']={'kind':'command','executor':receiver.ident,'command':['must-not-run']}
        base.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
        self.pump(lambda:None,lambda:bool(engine.executors.calls()))
        job=engine.executors.calls()[0]
        engine.executors.report(job['id'],job['token'],{'state':'unknown','sequence':1,'error':'Receiver interrupted'})
        self.pump(lambda:None,lambda:all(f.done() for f in engine.futures))
        engine.close();replacement=Engine(base.store);self.addCleanup(replacement.close);replacement.recover()
        attempt=next(e for e in base.read()['executions'] if e['task_id']=='job')
        self.assertEqual(attempt['worker_active'],job['id'])
        with self.assertRaises(Conflict):replacement.command(base.id,'retry',attempt['id'])
        tools=PlatformTools(base.store)
        self.assertFalse(tools.respond('confirm_executor_stopped',{'id':job['id'],'confirmed_stopped':False})['ok'])
        replacement.executors.report(job['id'],job['token'],{'state':'completed','sequence':2,'result':{'returncode':0,'stdout':'late result','stderr':''}})
        self.assertTrue(tools.respond('confirm_executor_stopped',{'id':job['id'],'confirmed_stopped':True})['ok'])
        self.assertEqual(replacement.executors.get(job['id'])['result']['stdout'],'late result')
        replacement.command(base.id,'retry',attempt['id'])
        self.assertNotIn('worker_active',next(e for e in base.read()['executions'] if e['id']==attempt['id']))

    def test_service_reconnect_after_agent_finish_uses_existing_process_prompt(self):
        from loop_anything.interfaces.agent_tasks import RunTools
        base=fixture.RuntimeTests();base.setUp();self.addCleanup(base.tearDown)
        engine=base.engine;box=ToolMailbox(base.store,self.root/'team',engine)
        engine.platform_url='nas://'+str(box.root);engine.executors.root=box.root
        receiver=Receiver({'server':engine.platform_url},self.root/'receiver');self.addCleanup(receiver.close)
        receiver.tick();engine.executors.sync()
        base.implementations['produce']={'kind':'agent','executor':receiver.ident,'command':['must-not-start-again']}
        base.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
        self.pump(lambda:None,lambda:bool(engine.executors.calls()))
        job=engine.executors.calls()[0];attempt=next(e for e in base.read()['executions'] if e['task_id']=='job')
        agent=RunTools(base.store,base.id,attempt['token']);info=agent.call('read_task',{'task_id':'job'})
        agent.call('report_task',{'task_id':'job','task_version':info['task_version'],'event':'completed','report_id':'committed',
            'envelope':{'outputs':{'text':'saved-before-restart'}}});agent.call('finish',{})
        engine.close()
        replacement=Engine(base.store);self.addCleanup(replacement.close)
        replacement.platform_url=engine.platform_url
        replacement.executors.report(job['id'],job['token'],{'state':'completed','sequence':1,
            'session':{'state':'exited','returncode':0},'result':{'returncode':0,'stdout':'','stderr':''}})
        replacement.recover()
        for future in list(replacement.futures):future.result(timeout=5)
        self.assertEqual(base.read()['records']['out'][-1]['value'],'saved-before-restart')
        self.assertFalse(any(h['kind']=='agent_exit_error' for h in base.read()['history']))
        self.assertTrue(replacement.executors.get(job['id'])['applied'])


if __name__=='__main__':unittest.main()
