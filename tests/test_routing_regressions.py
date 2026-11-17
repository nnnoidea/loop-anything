"""Regression cases from the second origin-routing audit."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from loop_anything.runtime.tool_client import module
from loop_anything.runtime.store import Store
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.communication import Communication,service
ROOT=Path(__file__).resolve().parents[1]
CLIENT=ROOT/'skills/loop-anything-platform/scripts/call.py'

class RoutingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        env=patch.dict(os.environ,LOOP_ANYTHING_SPACES=str(self.root/'spaces.json'),LOOP_ANYTHING_IDENTITY_DIR=str(self.root/'identity'),LOOP_ANYTHING_WORK='')
        env.start();self.addCleanup(env.stop)
        self.spaces=module('spaces');self.routing=module('routing');self.ledger=self.routing.Ledger();self.addCleanup(self.ledger.close)
        self.spaces.configure({'local_url':'http://127.0.0.1:1111','team_url':'http://127.0.0.1:2222','default_space':'local'})
    def test_resource_keeps_actual_verified_work_and_rejects_same_url_other_workspace(self):
        empty=self.ledger.choose('check',{})
        original=self.ledger.choose('list_monitor_scripts',{})
        self.ledger.verify(original['id'],'workspace-a')
        self.ledger.finish(original['id'],'list_monitor_scripts',{}, {'ok':True,'scripts':[{'id':'script'}]})
        chosen=self.ledger.choose('register_monitor',{'script_id':'script','revision':1})
        self.assertEqual(chosen['id'],original['id'])
        self.assertIsNone(self.ledger.get(empty['id'])['workspace'])
        replacement=self.ledger.choose('check',{})
        self.ledger.verify(replacement['id'],'workspace-b')
        with self.assertRaises(ValueError):self.ledger.choose('register_monitor',{'script_id':'script','revision':1},work=replacement['id'])
        with self.assertRaises(ValueError):self.ledger.verify(chosen['id'],'workspace-b')
        # Another work on the same confirmed origin is valid, not an alias to another workspace.
        same=self.ledger.choose('check',{});self.ledger.verify(same['id'],'workspace-a')
        self.assertEqual(self.ledger.choose('register_monitor',{'script_id':'script','revision':1},work=same['id'])['id'],same['id'])
    def test_business_id_reuses_first_transport_receipt_and_origin(self):
        stores={url:Store(self.root/(name+'.db')) for url,name in [('http://127.0.0.1:1111','a'),('http://127.0.0.1:2222','b')]}
        client=module('call')
        def fetch(url,data=None,**kwargs):
            base=url.rsplit('/api/',1)[0]
            if data is None:return {'workspace_id':'workspace-'+('a' if base.endswith('1111') else 'b')}
            packet=json.loads(data);return PlatformTools(stores[base]).respond(packet['tool'],packet['arguments'])
        def invoke(args,flags=(),ok=True):
            argv=['call','start_monitor','--arguments',json.dumps(args),*flags]
            with patch.object(sys,'argv',argv),patch.object(client,'fetch',side_effect=fetch),patch('sys.stdout',new_callable=io.StringIO) as out,patch('sys.stderr',new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as done:client.main()
            self.assertEqual(done.exception.code==0,ok,out.getvalue())
            return json.loads(out.getvalue()) if out.getvalue() else None
        args={'request_id':'business-once','script':{'command':[sys.executable,'-c','print("{}")']},'interval':3600}
        first=invoke(args,['--request-id','explicit-first'])
        self.spaces.configure({'default_space':'team'})
        again=invoke(args)
        changed_transport=invoke(args,['--request-id','another-transport'])
        for result in (again,changed_transport):
            self.assertEqual(result['routing_request_id'],'explicit-first')
            self.assertEqual(result['monitor']['id'],first['monitor']['id'])
            self.assertEqual(result['platform_url'],first['platform_url'])
        invoke(args,['--space','team'],ok=False)
        invoke(dict(args,interval=7200),ok=False)
        self.assertEqual(len(PlatformTools(stores['http://127.0.0.1:1111']).respond('list_monitors',{})['monitors']),1)
        self.assertEqual(PlatformTools(stores['http://127.0.0.1:2222']).respond('list_monitors',{})['monitors'],[])
    def test_business_origin_is_reserved_before_a_response_and_with_concurrent_transports(self):
        from concurrent.futures import ThreadPoolExecutor
        args={'request_id':'pending-business','script':{},'interval':1}
        def choose(transport):
            ledger=self.routing.Ledger()
            try:return ledger.choose('start_monitor',args,request_id=transport)
            finally:ledger.close()
        with ThreadPoolExecutor(max_workers=2) as pool:works=list(pool.map(choose,['transport-a','transport-b']))
        self.assertEqual(works[0]['id'],works[1]['id'])
        self.assertEqual(works[0]['request_id'],works[1]['request_id'])
        self.spaces.configure({'default_space':'team'})
        later=choose('transport-c')
        self.assertEqual(later['id'],works[0]['id'])
        self.assertEqual(self.ledger.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],1)
    def test_nas_pending_business_retry_keeps_first_mailbox_and_transport_id(self):
        from loop_anything.runtime.engine import Engine
        from loop_anything.runtime.tool_mailbox import ToolMailbox
        stores=[Store(self.root/('nas-'+name+'.db')) for name in ('a','b')]
        engines=[Engine(store) for store in stores]
        for engine in engines:self.addCleanup(engine.close)
        boxes=[ToolMailbox(store,self.root/('mailbox-'+name),engine) for store,engine,name in zip(stores,engines,('a','b'))]
        urls=[box.root.as_uri().replace('file:','nas:') for box in boxes]
        self.spaces.configure({'team_url':urls[0],'default_space':'team'})
        args={'request_id':'pending-monitor','script':{'command':['unused-test-script']},'interval':3600}
        def invoke(flags):
            p=subprocess.run([sys.executable,str(CLIENT),'start_monitor','--arguments',json.dumps(args),'--wait','0',*flags],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            return json.loads(p.stdout)
        first=invoke(['--request-id','first-nas-attempt']);self.assertTrue(first['pending'])
        self.spaces.configure({'team_url':urls[1]})
        pending=invoke([]);self.assertTrue(pending['pending'])
        self.assertEqual(pending['routing_request_id'],'first-nas-attempt')
        self.assertEqual(pending['platform_url'],urls[0])
        self.assertEqual(len(list((boxes[0].root/'api/requests').glob('*.json'))),1)
        self.assertEqual(list((boxes[1].root/'api/requests').glob('*.json')),[])
        boxes[0].tick();boxes[1].tick()
        done=invoke(['--request-id','another-nas-attempt'])
        self.assertEqual(done['routing_request_id'],first['routing_request_id'])
        self.assertEqual(len(PlatformTools(stores[0]).respond('list_monitors',{})['monitors']),1)
        self.assertEqual(PlatformTools(stores[1]).respond('list_monitors',{})['monitors'],[])

    def test_scoped_tool_catalog_is_covered_including_read_asset(self):
        work=self.ledger.choose('list',{})
        for kind in ('node_execution','assistance'):
            scope=SimpleNamespace(authorized=lambda _:True,get=lambda _: {'kind':kind},store=None)
            definitions=Communication.scoped_definitions(scope,'request','token')['tools']
            for definition in definitions:self.assertIn(definition['name'],self.routing.KNOWN_TOOLS)
        self.assertEqual(self.ledger.choose('read_asset',{'path':'handbook.md'},work=work['id'])['id'],work['id'])
    def test_discover_then_join_a_group_uses_the_discovered_origin(self):
        a=service(Store(self.root/'a.db'));b=service(Store(self.root/'b.db'));nas=self.root/'nas';nas.mkdir()
        sid=a.config('space',path=str(nas),name='Research')['space_id']
        groups=a.config('group',space_id=sid,name='Papers',create=True)['configuration']['groups'];group=next(iter(groups.values()))
        b.config('space',path=str(nas),name='Research')
        work=self.ledger.choose('communication_workspace',{'discover':True});self.ledger.verify(work['id'],'b')
        result=PlatformTools(b.store).respond('communication_workspace',{'discover':True})
        self.ledger.finish(work['id'],'communication_workspace',{'discover':True},result)
        self.spaces.configure({'default_space':'team'})
        args={'operation':'group','space_id':sid,'relative_path':group['relative_path'],'group_id':group['id']}
        self.assertEqual(self.ledger.choose('communication_config',args)['id'],work['id'])
        self.assertTrue(PlatformTools(b.store).respond('communication_config',args)['ok'])
    def test_injected_work_cannot_be_overridden_by_another_platform(self):
        a=self.ledger.choose('check',{});b=self.ledger.choose('check',{},space='team')
        with patch.dict(os.environ,LOOP_ANYTHING_WORK=a['id']),self.assertRaises(ValueError):
            self.ledger.choose('create_timeline',{},work=b['id'])

class WorkspaceReplacementHTTPTests(unittest.TestCase):
    def test_failed_initial_check_cannot_later_redirect_an_existing_resource(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);processes=[]
            env=dict(os.environ,LOOP_ANYTHING_SPACES=str(root/'spaces.json'),LOOP_ANYTHING_IDENTITY_DIR=str(root/'identity'),LOOP_ANYTHING_WORK='')
            def cli(tool,args=None):
                p=subprocess.run([sys.executable,str(CLIENT),tool,'--arguments',json.dumps(args or {})],cwd=ROOT,env=env,text=True,capture_output=True)
                return p.returncode,p.stdout,p.stderr
            def start(name,port):
                log=root/(name+'.log');stream=log.open('w')
                p=subprocess.Popen([sys.executable,'-m','loop_anything','--db',str(root/(name+'.db')),'serve','--space','local','--port',str(port)],cwd=ROOT,env=env,stdout=stream,stderr=stream);processes.append((p,stream))
                until=time.monotonic()+15
                while time.monotonic()<until:
                    if 'Health check:' in log.read_text():return p
                    self.assertIsNone(p.poll(),log.read_text());time.sleep(.03)
                self.fail(log.read_text())
            try:
                with patch.dict(os.environ,env):
                    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                    module('spaces').configure({'local_url':'http://127.0.0.1:'+str(port)})
                    self.assertNotEqual(cli('check')[0],0)
                    stores={name:Store(root/(name+'.db')) for name in ('a','b')}
                    script={'command':[sys.executable,'-c','print("{}")'],'description':'original'}
                    for store in stores.values():self.assertTrue(PlatformTools(store).respond('register_monitor',{'script_id':'shared','revision':0,'script':script})['ok'])
                    a=start('a',port);self.assertEqual(cli('list_monitor_scripts')[0],0)
                    a.terminate();a.wait(timeout=10)
                    start('b',port)
                    code,_,error=cli('register_monitor',{'script_id':'shared','revision':1,'script':dict(script,description='wrong')})
                    self.assertNotEqual(code,0);self.assertIn('different platform',error)
                    for store in stores.values():self.assertEqual(PlatformTools(store).respond('list_monitor_scripts',{})['scripts'][0]['script']['description'],'original')
            finally:
                for p,stream in processes:
                    if p.poll() is None:
                        p.terminate()
                        try:p.wait(timeout=10)
                        except subprocess.TimeoutExpired:p.kill();p.wait()
                    stream.close()
