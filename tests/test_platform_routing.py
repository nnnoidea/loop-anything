"""Origin affinity across independent client processes, default changes and retries."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from loop_anything.runtime.tool_client import module

ROOT=Path(__file__).resolve().parents[1]
CLIENT=ROOT/'skills/loop-anything-platform/scripts/call.py'

class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.env=dict(LOOP_ANYTHING_SPACES=str(self.root/'spaces.json'),LOOP_ANYTHING_IDENTITY_DIR=str(self.root/'identity'),LOOP_ANYTHING_WORK='')
        env=patch.dict(os.environ,self.env);env.start();self.addCleanup(env.stop)
        self.spaces=module('spaces');self.routing=module('routing');self.ledger=self.routing.Ledger();self.addCleanup(self.ledger.close)
        self.spaces.configure({'local_url':'http://127.0.0.1:1111','team_url':'http://127.0.0.1:2222','default_space':'local'})
    def test_unknown_conflicting_and_ambiguous_origins_fail_closed(self):
        local=self.ledger.choose('create_timeline',{},request_id='first')
        self.ledger.finish(local['id'],'create_timeline',{}, {'ok':True,'timeline':{'id':'timeline-one'}})
        self.spaces.configure({'default_space':'team'})
        self.assertEqual(self.ledger.choose('read_work_timeline',{'timeline_id':'timeline-one'})['url'],local['url'])
        with self.assertRaisesRegex(ValueError,'cannot override'):self.ledger.choose('read_work_timeline',{'timeline_id':'timeline-one'},space='team')
        with self.assertRaisesRegex(ValueError,'Unknown original'):self.ledger.choose('read_executor_call',{'id':'unknown'},url=local['url'])
        team=self.ledger.choose('create_timeline',{})
        self.ledger.finish(team['id'],'create_timeline',{}, {'ok':True,'timeline':{'id':'timeline-one'}})
        with self.assertRaisesRegex(ValueError,'Ambiguous'):self.ledger.choose('read_work_timeline',{'timeline_id':'timeline-one'},space='local')
        self.assertEqual(self.ledger.choose('read_work_timeline',{'timeline_id':'timeline-one'},work=local['id'])['url'],local['url'])
        self.ledger.remember(team['id'],[('session','team-session')]);self.ledger.db.commit()
        with self.assertRaisesRegex(ValueError,'another work'):self.ledger.choose('wait_for',{'timeline_id':'timeline-one','session_id':'team-session'},work=local['id'])
        with self.assertRaisesRegex(ValueError,'Ambiguous'):self.ledger.choose('wait_for',{'timeline_id':'timeline-one','session_id':'team-session'})
        with self.assertRaisesRegex(ValueError,'Unknown routing contract'):self.ledger.choose('future_tool',{},space='team')
    def test_read_original_task_from_a_new_clients_continuation_snapshot(self):
        local = self.ledger.choose('list_runs', {})
        self.ledger.verify(local['id'], 'local-workspace')
        self.spaces.configure({'default_space': 'team'})
        ref = {'run_id': 'original', 'task_id': 'training'}
        with patch.dict(os.environ, LOOP_ANYTHING_WORK=local['id']):
            self.assertEqual(self.ledger.choose('read_task', ref)['url'], local['url'])
            with self.assertRaisesRegex(ValueError, 'Unknown original'):
                self.ledger.choose('change_task', ref)
        self.ledger.finish(local['id'], 'read_run', {'run_id': 'current'}, {
            'ok': True, 'tasks': [{'continuation_source': ref}]})
        self.assertEqual(self.ledger.choose('read_task', ref)['url'], local['url'])
        team = self.ledger.choose('list_runs', {})
        self.ledger.verify(team['id'], 'team-workspace')
        with self.assertRaisesRegex(ValueError, 'another work platform'):
            self.ledger.choose('read_task', ref, work=team['id'])

    def test_bound_reads_can_query_resources_before_discovery(self):
        local=self.ledger.choose('list_runs',{})
        self.ledger.verify(local['id'],'original-platform')
        self.spaces.configure({'default_space':'team'})
        for tool, args in [('read_monitor',{'monitor_id':'m'}),('read_work_result',{'timeline_id':'t','id':'score'}),
                           ('list_timelines',{'loop_id':'research'}),('next_tasks',{'run_id':'r'})]:
            with self.subTest(tool=tool):
                self.assertEqual(self.ledger.choose(tool,args,work=local['id'])['url'],local['url'])
                with self.assertRaisesRegex(ValueError,'Unknown original'):
                    self.ledger.choose(tool,args)
        with self.assertRaisesRegex(ValueError,'Unknown original'):
            self.ledger.choose('stop_monitor',{'monitor_id':'m'},work=local['id'])

    def test_unique_common_verified_platform_is_sufficient(self):
        local=self.ledger.choose('list_loops',{})
        team=self.ledger.choose('list_loops',{},space='team')
        for work,identity in ((local,'local-id'),(team,'team-id')):
            self.ledger.verify(work['id'],identity)
            with self.ledger.db:self.ledger.remember(work['id'],[('loop','shared-key')])
        with self.ledger.db:self.ledger.remember(local['id'],[('timeline','t'),('session','s')])
        self.spaces.configure({'default_space':'team'})
        self.assertEqual(self.ledger.choose('start_run',{'key':'shared-key','timeline_id':'t','session_id':'s'})['url'],local['url'])
        with self.assertRaisesRegex(ValueError,'Ambiguous'):
            self.ledger.choose('read_loop',{'key':'shared-key'})

    def test_request_reserved_before_send_and_http_unknown_is_not_replayed(self):
        first=self.ledger.choose('create_timeline',{'title':'one'},request_id='retry')
        self.spaces.configure({'default_space':'team','local_url':'http://127.0.0.1:3333'})
        self.assertEqual(self.ledger.choose('create_timeline',{'title':'one'},request_id='retry')['url'],first['url'])
        with self.assertRaisesRegex(ValueError,'different arguments'):self.ledger.choose('create_timeline',{'title':'two'},request_id='retry')
        self.assertIsNone(self.ledger.begin('retry'))
        self.assertTrue(self.ledger.begin('retry')['outcome_unknown'])
        self.ledger.finish(first['id'],'create_timeline',{'title':'one'},{'ok':True,'timeline':{'id':'saved'}},'retry')
        self.assertEqual(self.ledger.begin('retry')['timeline']['id'],'saved')
        self.assertEqual(self.ledger.choose('result',{},request_id='retry')['id'],first['id'])
        self.ledger.verify(first['id'],'workspace-one')
        with self.assertRaisesRegex(ValueError,'different platform'):self.ledger.verify(first['id'],'workspace-two')
    def test_readonly_http_retry_remains_bound_after_lost_response(self):
        first=self.ledger.choose('create_timeline',{},request_id='created')
        self.ledger.verify(first['id'],'platform')
        self.ledger.finish(first['id'],'create_timeline',{}, {'ok':True,'timeline':{'id':'tl'}},'created')
        args={'timeline_id':'tl'}
        route=self.ledger.choose('export_timeline',args,request_id='download')
        self.assertIsNone(self.ledger.begin('download'))
        self.ledger.finish(route['id'],'export_timeline',args,{'ok':False,'transport_error':True},'download')
        self.spaces.configure({'default_space':'team'})
        self.assertEqual(self.ledger.choose('export_timeline',args,request_id='download')['url'],first['url'])
        self.assertIsNone(self.ledger.begin('download'))

    def test_run_id_list_uses_the_original_platform(self):
        local=self.ledger.choose('list_runs',{},space='local')
        team=self.ledger.choose('list_runs',{},space='team')
        for work, identity, ids in [(local,'local-id',['run-a','run-b']), (team,'team-id',['run-c'])]:
            self.ledger.verify(work['id'],identity)
            with self.ledger.db:
                self.ledger.remember(work['id'],[('run',ident) for ident in ids])
        self.spaces.configure({'default_space':'team'})
        self.assertEqual(self.ledger.choose('list_runs',{'run_ids':['run-a','run-b']})['url'],local['url'])
        with self.assertRaisesRegex(ValueError,'conflict|platform'):
            self.ledger.choose('list_runs',{'run_ids':['run-a','run-c']})

    def test_all_platform_tools_have_an_explicit_routing_contract(self):
        from loop_anything.interfaces.platform_tools import PlatformTools
        self.assertEqual(self.routing.READ_ONLY,{d['name'] for d in PlatformTools(None).definitions() if d['annotations']['readOnlyHint']})
        for definition in PlatformTools(None).definitions():
            self.assertIn(definition['name'],self.routing.KNOWN_TOOLS)
            local={'node_id','implementation_id','execution_id','task_id','parent_id','report_id','external_id','event_id','reply_id','notification_id','conversation_id','instance_id','process_id'}
            handled=set(self.routing.FIELDS)|set(self.routing.LIST_FIELDS)|{'session_id','request_id'}|local
            for field in definition['inputSchema']['properties']:
                if field.endswith('_id') or field.endswith('_ids'):
                    self.assertIn(field,handled,definition['name']+': new selector needs a routing decision')
        self.assertEqual(self.routing.references('list_runs',{'run_ids':['run-x']}),[('run','run-x')])
        observed=self.routing.resources('communication_workspace',{'directory':{'loops':[{'key':'remote-loop'}],'agents':[{'id':'agent'}]}})
        self.assertNotIn(('loop','remote-loop'),observed)
        self.assertIn(('agent','agent'),observed)


    def test_cached_receipt_needs_no_live_platform(self):
        import io
        work=self.ledger.choose('create_timeline',{},request_id='offline-receipt')
        self.ledger.finish(work['id'],'create_timeline',{}, {'ok':True,'timeline':{'id':'cached'}},'offline-receipt')
        client=module('call')
        with patch.object(sys,'argv',['call','result','--request-id','offline-receipt']),patch.object(client,'fetch',side_effect=AssertionError('Cached receipt must not contact a platform')),patch('sys.stdout',new_callable=io.StringIO) as out,patch('sys.stderr',new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as done:client.main()
            self.assertEqual(done.exception.code,0)
            self.assertEqual(json.loads(out.getvalue())['timeline']['id'],'cached')

    def test_concurrent_reservations_have_one_origin(self):
        from concurrent.futures import ThreadPoolExecutor
        def reserve(space):
            ledger=self.routing.Ledger()
            try:
                try:return ledger.choose('create_timeline',{},space=space,request_id='race')['url']
                except ValueError:return None
            finally:ledger.close()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,['local','team']))
        self.assertEqual(len([r for r in results if r]),1)
    def test_wake_context_binds_wait_sources_and_assistance(self):
        work=self.routing.bind_context({'platform_url':'http://127.0.0.1:1111','session_id':'session',
            'waits':[{'id':'wait','timeline_id':'timeline','sources':{'a':{'kind':'run','id':'prior-run'},'b':{'kind':'monitor','id':'monitor'}}}],
            'assistance_results':[{'id':'assistance'}]})
        self.spaces.configure({'default_space':'team'})
        for tool,args in [('read_run',{'run_id':'prior-run'}),('read_monitor',{'monitor_id':'monitor'}),('read_assistance',{'request_id':'assistance'})]:
            self.assertEqual(self.ledger.choose(tool,args,work=work)['url'],'http://127.0.0.1:1111')

    def test_nested_cross_platform_references_cannot_escape_work(self):
        a=self.ledger.choose('list',{},space='local');b=self.ledger.choose('list',{},space='team')
        self.ledger.remember(a['id'],[('draft','draft'),('session','session'),('timeline','timeline')])
        self.ledger.remember(b['id'],[('loop','remote-loop'),('run','remote-run')]);self.ledger.db.commit()
        for tool,args in [('set_implementation',{'draft_id':'draft','loop':{'key':'remote-loop'}}),('wait_for',{'session_id':'session','timeline_id':'timeline','sources':{'x':{'kind':'task','id':'remote-run','task_id':'x'}}})]:
            with self.subTest(tool=tool),self.assertRaises(ValueError):self.ledger.choose(tool,args,work=a['id'])

class RoutingHTTPTests(unittest.TestCase):
    def test_clients_runtime_export_and_retries_stay_on_original_platform(self):
        from loop_anything.runtime.store import Store
        from test_packages import document
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);processes=[]
            env=dict(os.environ,LOOP_ANYTHING_SPACES=str(root/'spaces.json'),LOOP_ANYTHING_IDENTITY_DIR=str(root/'identity'),LOOP_ANYTHING_WORK='')
            store=Store(root/'local.db');doc=document();key=store.publish(doc['loop_definition'],doc['implementations'])['key'];run=store.create(key,'existing')
            with store.edit(run['id']) as current:current['status']='paused'
            def start(kind):
                stream=(root/(kind+'.log')).open('w');mail=root/(kind+'-nas')
                p=subprocess.Popen([sys.executable,'-m','loop_anything','--db',str(root/(kind+'.db')),'serve','--port','0','--space',kind,'--allow-sleep','--team-dir',str(mail)],env=env,cwd=ROOT,stdout=stream,stderr=stream);processes.append((p,stream))
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    match=re.search(r'Health check: (http://127.0.0.1:\d+)/api/health',(root/(kind+'.log')).read_text())
                    if match:return match.group(1),mail.as_uri().replace('file:','nas:')
                    self.assertIsNone(p.poll(),(root/(kind+'.log')).read_text());time.sleep(.05)
                self.fail('startup timeout')
            def invoke(tool,args=None,flags=(),client=CLIENT,ok=True):
                cmd=[sys.executable,str(client),tool,'--arguments',json.dumps(args or {}),*flags]
                response=subprocess.run(cmd,env=env,cwd=ROOT,text=True,capture_output=True)
                if ok:self.assertEqual(response.returncode,0,response.stderr+'\n'+response.stdout)
                else:self.assertNotEqual(response.returncode,0,response.stdout)
                return json.loads(response.stdout) if response.stdout else response.stderr
            def configure(**change):
                with patch.dict(os.environ,env):return module('spaces').configure(change)
            try:
                local,local_nas=start('local');team,team_nas=start('team')
                configure(local_url=local,team_url=team,default_space='local')
                t=invoke('create_timeline',{'title':'local'})
                script={'command':[sys.executable,'-c','print("{}")'],'description':'original'}
                monitor=invoke('register_monitor',{'script_id':'same-name','revision':0,'script':script})
                draft=invoke('create_loop',{'name':'local draft'})
                configure(default_space='team')
                changed=invoke('update_timeline',{'timeline_id':t['timeline']['id'],'revision':t['timeline']['revision'],'change':{'objective':'kept local'}})
                self.assertEqual(changed['platform_url'],local)
                script['description']='local edit'
                self.assertEqual(invoke('register_monitor',{'script_id':'same-name','revision':1,'script':script})['platform_url'],local)
                self.assertEqual(invoke('set_loop',{'draft_id':draft['draft_id'],'revision':draft['revision'],'description':'kept local'})['platform_url'],local)
                invoke('read_work_timeline',{'timeline_id':t['timeline']['id']},['--space','team'],ok=False)
                invoke('read_executor_call',{'id':'never-seen'},['--url',team],ok=False)
                invoke('register_monitor',{'script_id':'same-name','revision':0,'script':script},['--space','team'])
                invoke('register_monitor',{'script_id':'same-name','revision':2,'script':script},ok=False)
                self.assertEqual(invoke('register_monitor',{'script_id':'same-name','revision':2,'script':script},['--work',monitor['work_id']])['platform_url'],local)
                # CLI and exported Skills share durable origin knowledge.
                from loop_anything.packaging.skill_bundle import install_skills,bundle
                install_skills(bundle(team),root/'skills')
                exported=root/'skills/loop-anything-platform/scripts/call.py'
                self.assertEqual(invoke('read_work_timeline',{'timeline_id':t['timeline']['id']},client=exported)['platform_url'],local)
                # A managed Agent needs neither --url nor --work.
                from loop_anything.runtime.host_runtime import run_command
                with patch.dict(os.environ,env):
                    from loop_anything.runtime.process_session import ProcessSession
                    for session in (None,ProcessSession('routing-probe',{'kind':'agent'})):
                        process=run_command([sys.executable,str(CLIENT),'read_run','--arguments',json.dumps({'run_id':run['id']})],'',10,session=session,context={'platform_url':local,'run_id':run['id'],'loop_key':key})
                        self.assertEqual(process.returncode,0,process.stderr)
                        self.assertEqual(json.loads(process.stdout)['platform_url'],local)
                    self.assertEqual(os.environ['LOOP_ANYTHING_WORK'],'')
                    missing=run_command([sys.executable,str(CLIENT),'create_timeline','--arguments','{"title":"must not leak"}'],'',10,context={'run_id':'unroutable'})
                    self.assertNotEqual(missing.returncode,0)
                    self.assertIn('Unknown work reference',missing.stderr)

                # HTTP duplicate ID returns original receipt, even after defaults/addresses change.
                first=invoke('create_timeline',{'title':'http once'},['--space','local','--request-id','http-once'])
                configure(local_url='http://127.0.0.1:1')
                again=invoke('create_timeline',{'title':'http once'},['--request-id','http-once'])
                self.assertEqual(again['timeline']['id'],first['timeline']['id']);self.assertEqual(again['platform_url'],local)
                invoke('create_timeline',{'title':'http once'},['--request-id','http-once','--space','team'],ok=False)
                # Actual NAS service, not a simulated receipt: retry and result use original mailbox.
                configure(team_url=local_nas)
                first=invoke('create_timeline',{'title':'nas once'},['--request-id','nas-once','--wait','0'])
                configure(team_url=team_nas)
                again=invoke('create_timeline',{'title':'nas once'},['--request-id','nas-once','--wait','5'])
                receipt=invoke('retry',flags=['--request-id','nas-once'])
                invoke('retry',flags=['--request-id','unknown-retry'],ok=False)
                self.assertEqual(again['timeline']['id'],receipt['timeline']['id']);self.assertEqual(again['platform_url'],local_nas)
                self.assertFalse((root/'team-nas/api/requests/nas-once.json').exists());self.assertFalse((root/'team-nas/api/history/nas-once.json').exists())
                # A real commit followed by a lost HTTP response must not be replayed.
                import io
                client=module('call');real_fetch=client.fetch
                def lose_response(url,data=None,**kwargs):
                    result=real_fetch(url,data,**kwargs)
                    return {'ok':False,'transport_error':True,'error':'simulated lost response after commit'} if data else result
                argv=['call','create_timeline','--work',t['work_id'],'--request-id','lost-response','--arguments','{"title":"committed-once"}']
                with patch.dict(os.environ,env),patch.object(sys,'argv',argv),patch.object(client,'fetch',side_effect=lose_response),patch('sys.stdout',new_callable=io.StringIO),patch('sys.stderr',new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as lost:client.main()
                    self.assertEqual(lost.exception.code,2)
                response=invoke('retry',flags=['--request-id','lost-response'],ok=False)
                self.assertTrue(response['outcome_unknown'])
                listed=invoke('list_timelines',flags=['--work',t['work_id']])
                self.assertEqual(sum(v['title']=='committed-once' for v in listed['timelines']),1)

                # A server-committed Timeline import is idempotent on its original platform.
                exported = invoke('export_timeline', {'timeline_id': t['timeline']['id']})
                args = {'request_id': 'same-import', 'document': exported['document']}
                before = listed['total']
                argv = ['call', 'import_timeline', '--work', t['work_id'], '--request-id', 'lost-import',
                        '--arguments', json.dumps(args)]
                with patch.dict(os.environ, env), patch.object(sys, 'argv', argv), patch.object(client, 'fetch', side_effect=lose_response), patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as lost:
                        client.main()
                    self.assertEqual(lost.exception.code, 2)
                retried = invoke('retry', flags=['--request-id', 'lost-import'])
                self.assertTrue(retried['duplicate'])
                self.assertEqual(retried['platform_url'], local)
                self.assertEqual(invoke('list_timelines', flags=['--work', t['work_id']])['total'], before + 1)

            finally:
                for p,stream in processes:
                    p.terminate()
                    try:p.wait(timeout=10)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
                    stream.close()
