from tests.runtime_fixture import runtime_run
"""Conversation routing uses simulated machines/receipts; no real chat is contacted."""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_communication as fixtures
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.communication_conversations import resolve, from_source
from communication_helpers import notification_groups

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/loop-anything-platform/scripts'
sys.path.insert(0,str(SCRIPTS))
import cc_connect_context as bridge


class ConversationTests(unittest.TestCase):
    def setUp(self):
        fixtures.CommunicationTests.setUp(self)
        def sender(bot,destination=''):
            return {'command':[sys.executable,'-c','pass'],'channel':'cc-connect','identity':bot['project'],'destination':destination,'timeout':60}
        for name,value in [('sender',sender),('validate_bot',lambda bot:None)]:
            patched=patch('loop_anything.runtime.cc_connect.'+name,side_effect=value)
            patched.start();self.addCleanup(patched.stop)
    tearDown=fixtures.CommunicationTests.tearDown
    groups=notification_groups
    cycle=fixtures.CommunicationTests.cycle
    agent=fixtures.CommunicationTests.agent

    def entry(self, private=False):
        session='feishu:oc_chat:ou_user' if private else 'feishu:oc_chat:root:om_topic'
        context=dict(platform='feishu',chat_id='oc_chat',chat_type='p2p' if private else 'group',session_key=session,
                     thread_root=None if private else 'om_topic',entry_project='entrance')
        return from_source(self.a,context)['id']

    def bot(self,comm,gid=None):
        comm.store.notification_channels({'bot':dict(channel='cc-connect',identity='papers-bot',destination='unused',
            command=[sys.executable,'-c','pass'])},revision=0)
        self.agent(comm,groups=[gid] if gid else [])
        comm.config('agent',agent_id='papers',agent={'notification_bot':{'project':'papers-bot','platform':'feishu'}})
        for machine in (self.a,self.b,self.c):machine.last_scan=0;machine.scan()

    def completed(self, conversation, gid=None, **args):
        ident=self.a.request(dict(location='group' if gid else 'local',group_id=gid,agent_id='papers',instance_id=self.c.settings()['instance_id'] if gid else None,
                                  message='original body',conversation_id=conversation,**args))['request']['id']
        with self.a.transaction() as db:
            row=self.a.get(ident,db);row.update(state='completed',executor=(self.c if gid else self.a).settings()['instance_id'],result={'answer':42});self.a.save(db,row)
        return ident

    def receipt(self,command,text,*args):
        payload=json.loads(text);self.sent.append(payload)
        return subprocess.CompletedProcess(command,0,json.dumps({'delivered':True}),'')

    def test_private_uses_entry_bot_and_group_uses_agent_bot_in_exact_topic(self):
        gid=self.groups();self.bot(self.c,gid);self.sent=[]
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=self.receipt):
            private=self.completed(self.entry(True),gid)
            self.cycle(lambda:self.a.get(private).get('notifications',[{}])[-1].get('status')=='delivered')
            self.assertEqual(self.sent[-1]['outlet']['identity'],'entrance')
            group=self.completed(self.entry(),gid)
            self.cycle(lambda:self.a.get(group).get('notifications',[{}])[-1].get('status')=='delivered')
            self.assertEqual(self.sent[-1]['outlet']['identity'],'papers-bot')
            self.assertEqual(self.sent[-1]['conversation']['session_key'],'feishu:oc_chat:root:om_topic')
            self.assertEqual(self.sent[-1]['outlet']['destination'],'feishu:oc_chat:root:om_topic')
        shared=''.join(p.read_text() for p in (self.root/'nas').rglob('*.json'))
        self.assertNotIn('"command"',shared)
        self.assertNotIn('app_secret',shared)
        self.assertEqual(len(self.sent),2)

    def test_definite_presend_rejection_falls_back_but_unknown_send_does_not(self):
        gid=self.groups();self.bot(self.c,gid);self.sent=[]
        def send(command,text,*args):
            p=json.loads(text)
            if p['outlet']['identity']=='papers-bot':
                return subprocess.CompletedProcess(command,2,json.dumps({'delivered':False,'not_sent':True,'error':'not in chat'}),'')
            return self.receipt(command,text,*args)
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=send):
            ident=self.completed(self.entry(),gid)
            self.cycle(lambda:self.a.get(ident).get('notifications',[{}])[-1].get('status')=='delivered')
        notice=self.a.get(ident)['notifications'][0]
        self.assertEqual(notice['routing']['reason'],'entry_bot_fallback')
        self.assertEqual(len(notice['routing_attempts']),1)
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.sent[0]['outlet']['identity'],'entrance')
        def unknown(command,text,*args):
            self.sent.append(json.loads(text));raise TimeoutError('outcome unknown')
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=unknown):
            second=self.completed(self.entry(),gid)
            self.cycle(lambda:self.a.get(second).get('notifications',[{}])[-1].get('status')=='fault')
            for _ in range(3):self.a.tick();self.c.tick()
        self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sent[-1]['outlet']['identity'],'papers-bot')

    def test_local_named_bot_no_nas_and_explicit_route_override(self):
        self.bot(self.a);self.sent=[]
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=self.receipt):
            ident=self.completed(self.entry())
            self.cycle(lambda:self.a.get(ident).get('notifications',[{}])[-1].get('status')=='delivered')
        self.assertEqual(self.sent[0]['outlet']['identity'],'papers-bot')
        explicit=self.completed(self.entry(),notification_route='workspace')
        self.assertEqual(self.a.get(explicit)['notification_policy'],'explicit')
        self.assertNotIn('notification_conversation',self.a.get(explicit))
        continued=self.a.control(ident,'followup',message='continue',resume=False)['request']
        self.assertEqual(continued['notification_conversation'],self.a.get(ident)['notification_conversation'])

    def test_run_creation_captures_sender_and_node_assistance_inherits(self):
        import test_timeline_runtime as runtime
        from loop_anything.interfaces.platform_tools import PlatformTools
        case=runtime.RuntimeTests();case.setUp()
        try:
            key=self.a.store.publish(case.bp,case.implementations)['key']
            cid=self.entry()
            started=runtime_run(PlatformTools(self.a.store).store, dict(key=key,title='chat run',authorization='test',conversation_id=cid))
            run=self.a.store.get(started['run_id'])
            self.assertEqual(run['notification_conversation_id'],cid)
            self.assertEqual(run['settings']['notification_command'],[sys.executable,'-c','pass'])
            created=self.a.request(dict(location='local',agent_id='papers',message='node help',
                source={'run_id':run['id'],'task_id':started['entry_task_id']},token=started['token']))['request']
            self.assertEqual(created['notification_policy'],'conversation')
            self.assertEqual(created['notification_conversation']['id'],cid)
        finally:case.tearDown()

    def test_local_presend_rejection_uses_entry_without_duplicate_delivery(self):
        self.bot(self.a);self.sent=[]
        cli=self.root/'offline-cc-connect'
        cli.write_text('#!'+sys.executable+'\nimport sys\nprint("Error: cc-connect is not running (socket not found: /offline/run/api.sock)",file=sys.stderr)\nsys.exit(1)\n')
        cli.chmod(0o700)
        def send(command,text,*args):
            p=json.loads(text)
            if p['outlet']['identity']=='papers-bot':
                return subprocess.run([sys.executable,str(SCRIPTS/'notify_cc_connect.py'),'--executable',str(cli)],input=text,text=True,capture_output=True,timeout=10)
            return self.receipt(command,text,*args)
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=send):
            ident=self.completed(self.entry())
            self.cycle(lambda:self.a.get(ident).get('notifications',[{}])[-1].get('status')=='delivered')
            for _ in range(3):self.a.tick()
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.sent[0]['outlet']['identity'],'entrance')

    def test_nested_explicit_outlet_and_followup_survive_source_mirror(self):
        gid=self.groups();conversation=self.entry()
        parent_id=self.a.request(dict(location='group',group_id=gid,agent_id='papers',instance_id='notification-fixture',message='parent',conversation_id=conversation))['request']['id']
        with self.a.transaction() as db:
            parent=self.a.get(parent_id,db);parent.update(executor=self.b.settings()['instance_id'],state='running');self.a.save(db,parent)
        with self.b.transaction() as db:self.b.save(db,dict(parent,worker_token='worker'))
        args=dict(location='group',agent_id='papers',instance_id='notification-fixture',message='quiet child',notification_route='workspace',notification_level='attention')
        child=self.b.worker_call(parent_id,'worker','request_assistance',args)['request']
        self.assertEqual(child['notification_policy'],'explicit')
        self.assertNotIn('notification_conversation',child)
        self.assertEqual(child['notification_level'],'attention')
        with self.b.transaction() as db:
            current=self.b.get(child['id'],db);current.update(state='unavailable');self.b.save(db,current)
        followup=self.b.control(child['id'],'followup',message='quiet followup',resume=False)['request']
        self.assertEqual(followup['notification_policy'],'explicit')
        self.assertNotIn('notification_conversation',followup)
        with self.b.transaction() as db:views=self.b.child_views(parent_id,db)
        with self.a.transaction() as db:self.a.import_children(db,parent,views)
        for item in (child,followup):
            mirror=self.a.get(item['id'])
            self.assertEqual(mirror['notification_policy'],'explicit')
            self.assertEqual(mirror['notification_route'],'workspace')
            self.assertEqual(mirror['notification_level'],'attention')
            self.assertNotIn('notification_conversation',mirror)

    def test_captured_run_sender_keeps_delivery_timeout(self):
        from loop_anything.runtime.notifications import sender_for
        run={'settings':{'notification_command':['adapter']},'notification_conversation_id':self.entry()}
        _,sender=sender_for(self.a.store,run,'default')
        self.assertGreaterEqual(sender.get('timeout',30),60)

    def test_nested_remote_assistance_inherits_original_conversation(self):
        gid=self.groups();conversation=self.entry()
        parent_id=self.a.request(dict(location='group',group_id=gid,agent_id='papers',instance_id='notification-fixture',message='parent',conversation_id=conversation))['request']['id']
        with self.a.transaction() as db:
            parent=self.a.get(parent_id,db);parent.update(executor=self.b.settings()['instance_id'],state='running');self.a.save(db,parent)
        with self.b.transaction() as db:self.b.save(db,dict(parent,worker_token='worker'))
        child=self.b.worker_call(parent_id,'worker','request_assistance',dict(location='group',agent_id='papers',instance_id='notification-fixture',message='child',conversation_id='forged',chat_context={'platform':'feishu','entry_project':'forged','session_key':'feishu:oc_wrong:ou_wrong'}))['request']
        self.assertEqual(child['notification_conversation'],parent['notification_conversation'])
        with self.b.transaction() as db:views=self.b.child_views(parent_id,db)
        with self.a.transaction() as db:self.a.import_children(db,parent,views)
        mirror=self.a.get(child['id'])
        self.assertEqual(mirror['notification_conversation'],parent['notification_conversation'])
        self.assertEqual(mirror['notification_policy'],'conversation')
        with self.assertRaises(Invalid):resolve(self.b,conversation)

    def test_metadata_registration_reuses_binding_and_delivery_failure_does_not_fail_task(self):
        self.agent(self.a)
        context={'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:root:om_topic'}
        with patch.object(bridge,'read_config',side_effect=AssertionError('No channel preflight on request')), patch('loop_anything.runtime.cc_connect.sender',return_value={'configuration_error':'configure_cc_connect unavailable'}):
            binding=from_source(self.a,context);self.assertEqual(binding['id'],from_source(self.a,context)['id'])
            created=self.a.request(dict(location='local',agent_id='papers',message='work without cc-connect',chat_context=context))['request']
        with self.a.transaction() as db:
            row=self.a.get(created['id'],db);row.update(state='completed',result={'answer':42});self.a.save(db,row)
        def unavailable(command,text,*args):return subprocess.CompletedProcess(command,2,json.dumps({'delivered':False,'not_sent':True,'error':'cc-connect unavailable'}),'')
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=unavailable), patch('loop_anything.runtime.cc_connect.sender',return_value={'configuration_error':'configure_cc_connect unavailable'}):
            self.cycle(lambda:self.a.get(created['id']).get('notifications',[{}])[-1].get('status')=='waiting_configuration')
        current=self.a.get(created['id']);self.assertEqual(current['state'],'completed');self.assertEqual(current['result'],{'answer':42})
        self.assertIn('configure_cc_connect',current['notifications'][-1]['error'])
        self.assertEqual(current['notification_conversation']['conversation']['thread_root'],'om_topic')

    def test_untyped_private_context_learned_from_receipt_then_uses_entry_bot(self):
        context={'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:ou_user'}
        binding=from_source(self.a,context)
        self.bot(self.a)
        from loop_anything.runtime.communication_conversations import remember_context,select
        checked=dict(binding['conversation'],chat_type='p2p')
        with self.a.transaction() as db:remember_context(self.a,db,binding,{'conversation':dict(checked,app_secret='must not persist')})
        self.assertNotIn('app_secret',json.dumps(resolve(self.a,binding['id'])))
        request={'notification_conversation':dict(binding,conversation=dict(checked,chat_type='unknown')),'agent_id':'papers','executor':self.a.settings()['instance_id']}
        selected,_,fallback=select(self.a,request,'completed');self.assertEqual(selected['id'],binding['id']);self.assertIsNone(fallback)
        with self.a.transaction() as db:remember_context(self.a,db,binding,{'conversation':dict(checked,chat_id='another')})
        self.assertEqual(resolve(self.a,binding['id'])['conversation'],checked)

    def test_entry_uses_bridge_not_old_outlet_command(self):
        command=[sys.executable,'adapter.py','--config','/local/bridge.toml','--data-dir','/local/bridge']
        self.a.store.notification_channels({'entry':{'channel':'cc-connect','identity':'entrance','destination':'old destination','command':command,'cwd':'/local/working'}},revision=0)
        binding=from_source(self.a,{'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:root:om_topic'})
        saved=resolve(self.a,binding['id'],include_sender=True)
        self.assertEqual(saved['sender']['command'],[sys.executable,'-c','pass']);self.assertNotIn('cwd',saved['sender'])
        self.assertEqual(saved['sender']['destination'],'feishu:oc_chat:root:om_topic')
        self.assertNotIn('/local/',json.dumps(binding))

    def test_entry_does_not_merge_old_outlet_adapters(self):
        command=[sys.executable,'adapter.py','--data-dir','/configured/bridge']
        self.a.store.notification_channels({name:{'channel':'cc-connect','identity':'entrance','destination':name,'command':command,'timeout':timeout} for name,timeout in (('chat-a',60),('chat-b',90))},revision=0)
        binding=from_source(self.a,{'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:root:om_topic'})
        sender=resolve(self.a,binding['id'],include_sender=True)['sender']
        self.assertEqual(sender['command'],[sys.executable,'-c','pass']);self.assertEqual(sender['timeout'],60)
        self.assertEqual(sender['destination'],'feishu:oc_chat:root:om_topic')


    def test_run_metadata_reaches_timeline_notification_without_cli_probe(self):
        import test_timeline_runtime as runtime
        from loop_anything.interfaces.platform_tools import PlatformTools
        from loop_anything.runtime.notifications import enqueue
        case=runtime.RuntimeTests();case.setUp()
        try:
            key=self.a.store.publish(case.bp,case.implementations)['key']
            context={'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:root:om_topic'}
            tools=PlatformTools(self.a.store)
            with patch.object(bridge,'catalog',side_effect=AssertionError('No eager capture')):
                started=runtime_run(tools.store, dict(key=key,title='chat run',authorization='test',chat_context=context))
            run=self.a.store.get(started['run_id']);self.assertIn('notification_conversation_id',run)
            notice=enqueue(self.a.store,run,'test-notice',{'message':'result'})
            self.assertEqual(notice['conversation']['session_key'],context['session_key'])
            self.assertEqual(notice['status'],'pending')
            self.assertEqual(notice['sender']['command'],[sys.executable,'-c','pass'])
            explicit=runtime_run(tools.store, dict(key=key,title='explicit',authorization='test',chat_context=context,notification_route='workspace'))
            self.assertNotIn('notification_conversation_id',self.a.store.get(explicit['run_id']))
        finally:case.tearDown()


    def test_thread_metadata_survives_registration_and_delivery_receipt(self):
        from loop_anything.runtime.communication_conversations import remember_context
        source={'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:thread:omt_topic'}
        binding=from_source(self.a,source)
        self.assertEqual(binding['conversation']['thread_id'],'omt_topic')
        self.assertIsNone(binding['conversation']['thread_root'])
        context=dict(binding['conversation'],chat_type='group')
        registered=from_source(self.a,context)
        self.assertEqual(resolve(self.a,registered['id'])['conversation']['thread_id'],'omt_topic')
        with self.a.transaction() as db:
            remember_context(self.a,db,binding,{'conversation':context})
        updated=resolve(self.a,binding['id'])['conversation']
        self.assertEqual(updated['thread_id'],'omt_topic');self.assertIsNone(updated['thread_root'])

    def test_explicit_root_and_learned_root_persist_without_changing_session(self):
        from loop_anything.runtime.communication_conversations import remember_context
        source={'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:thread:omt_topic','thread_root':'om_real'}
        binding=from_source(self.a,source)
        self.assertEqual(binding['conversation']['thread_root'],'om_real')
        registered=from_source(self.a,binding['conversation'])
        self.assertEqual(registered['conversation']['thread_root'],'om_real')
        source.pop('thread_root');binding=from_source(self.a,source)
        self.bot(self.a)
        pending=self.completed(binding['id'])
        checked=dict(binding['conversation'],thread_root='om_real')
        with self.a.transaction() as db:remember_context(self.a,db,binding,{'conversation':checked})
        saved=from_source(self.a,source)['conversation']
        self.assertEqual(saved['thread_root'],'om_real')
        self.assertEqual(saved['session_key'],source['session_key'])
        self.sent=[]
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=self.receipt):
            self.cycle(lambda:self.a.get(pending)['notifications'][-1]['status']=='delivered')
        self.assertEqual(self.sent[-1]['outlet']['identity'],'papers-bot')
        self.assertEqual(self.sent[-1]['conversation']['thread_root'],'om_real')

    def test_timeline_delivery_saves_root_for_later_notices(self):
        import test_timeline_runtime as runtime
        from loop_anything.interfaces.platform_tools import PlatformTools
        from loop_anything.runtime.notifications import enqueue
        self.a.store.notification_channels({'entry':{'channel':'cc-connect','identity':'entrance','command':[sys.executable,'fake-sender']}},revision=0)
        case=runtime.RuntimeTests();case.setUp()
        try:
            key=self.a.store.publish(case.bp,case.implementations)['key']
            source={'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:thread:omt_topic'}
            started=runtime_run(PlatformTools(self.a.store).store, dict(key=key,title='topic',authorization='test',chat_context=source))
            with self.a.store.edit(started['run_id']) as run:
                notice=enqueue(self.a.store,run,'first',{'message':'result'})
                notice.update(status='sending',token='delivery-token')
            snapshot=self.a.store.get(started['run_id'])
            receipt={'delivered':True,'conversation':dict(notice['conversation'],thread_root='om_real')}
            with patch('loop_anything.runtime.timeline_runtime.run_command',return_value=subprocess.CompletedProcess([],0,json.dumps(receipt),'')):
                self.a.engine.timeline_runtime.deliver(started['run_id'],notice,snapshot)
            run=self.a.store.get(started['run_id'])
            later=enqueue(self.a.store,run,'second',{'message':'later'})
            self.assertEqual(later['conversation']['thread_root'],'om_real')
            self.assertEqual(later['conversation']['session_key'],source['session_key'])
        finally:case.tearDown()

    def test_receipts_cannot_erase_or_replace_saved_topic_identity(self):
        from loop_anything.runtime.communication_conversations import remember_context
        source={'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:thread:omt_topic'}
        stale=from_source(self.a,source)
        learned=dict(stale['conversation'],thread_root='om_real',chat_type='group')
        with self.a.transaction() as db:
            remember_context(self.a,db,dict(stale),{'conversation':learned})
            remember_context(self.a,db,dict(stale),{'conversation':stale['conversation']})
            remember_context(self.a,db,dict(stale),{'conversation':dict(learned,thread_root='om_wrong')})
            remember_context(self.a,db,dict(stale),{'conversation':dict(learned,thread_id='omt_wrong')})
        self.assertEqual(resolve(self.a,stale['id'])['conversation'],learned)


class BridgeDeliveryTests(unittest.TestCase):
    def test_client_only_carries_metadata_with_no_bridge_or_channel_access(self):
        import call as client
        from tests.runtime_fixture import client_work
        import os
        from io import StringIO
        for tool in ('request_assistance','start_run','submit_run_request'):
            for extra in ({},{'notification_route':'workspace'},{'source':{'run_id':'run-a'}}):
                with self.subTest(tool=tool,extra=extra):
                    calls=[]
                    def fetch(url,data=None,**kwargs):
                        if data is None:return {'workspace_id':'test-workspace'}
                        body=json.loads(data);calls.append(body);return {'ok':True}
                    argv=['call',tool,'--url','http://remote.example:1','--arguments',json.dumps(dict(message='help',**({'operation':'explain','run_id':'existing-run'} if tool=='submit_run_request' else {}),**extra))]
                    with client_work('http://remote.example:1',[('run','run-a'),('run','existing-run')]),patch.object(sys,'argv',argv),patch.object(sys,'stdout',new_callable=StringIO),patch.dict(os.environ,{'CC_PROJECT':'entrance','CC_SESSION_KEY':'feishu:oc_chat:ou_user','PATH':''}),patch.object(bridge,'catalog',side_effect=AssertionError('Client must not capture')),patch.object(client,'fetch',side_effect=fetch):
                        with self.assertRaises(SystemExit) as exit:client.main()
                        self.assertEqual(exit.exception.code,0)
                    self.assertEqual(len(calls),1);self.assertEqual(calls[0]['tool'],tool)
                    if not extra:self.assertEqual(calls[0]['arguments']['chat_context'],{'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:ou_user'})
                    else:self.assertNotIn('chat_context',calls[0]['arguments'])

    def test_generated_sender_preserves_custom_executable_and_data_directory(self):
        import notify_cc_connect as adapter
        import os
        with patch.dict(os.environ,{'CC_PROJECT':'entry','CC_SESSION_KEY':'feishu:oc_chat:root:om_root'}),patch.object(adapter.shutil,'which',side_effect=lambda p:p):
            argv=adapter.sender_command('/custom/cc-connect','/custom/data')
        self.assertEqual(argv[argv.index('--executable')+1],'/custom/cc-connect')
        self.assertEqual(argv[argv.index('--data-dir')+1],'/custom/data')
        self.assertNotIn('--config',argv)

    def test_adapter_subprocess_accepts_installed_cli_at_custom_path_without_cache(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cli=root/'custom cc-connect';config=root/'bridge.toml';log=root/'sent.json'
            cli.write_text('#!'+sys.executable+'\nimport sys,json\nfrom pathlib import Path\nPath('+repr(str(log))+').write_text(json.dumps({"argv":sys.argv[1:],"body":sys.stdin.read()}))\n')
            cli.chmod(0o700)
            config.write_text('[[projects]]\nname="entry"\n[[projects.platforms]]\ntype="feishu"\n[projects.platforms.options]\nthread_isolation=true\n')
            origin=dict(platform='feishu',entry_project='entry',chat_id='oc_chat',chat_type='group',session_key='feishu:oc_chat:thread:omt_topic',thread_id='omt_topic',thread_root='om_real')
            result=subprocess.run([sys.executable,str(SCRIPTS/'notify_cc_connect.py'),'--project','entry','--executable',str(cli),'--data-dir',str(root/'no-cache')],input=json.dumps({'id':'n','message':'result','conversation':origin}),text=True,capture_output=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            sent=json.loads(log.read_text());receipt=json.loads(result.stdout)
            self.assertEqual(sent['argv'][sent['argv'].index('--session')+1],'feishu:oc_chat:root:om_real')
            self.assertEqual(receipt['conversation'],origin)
            self.assertFalse((root/'no-cache').exists())
    def test_adapter_missing_executable_records_definite_unsent(self):
        import notify_cc_connect as adapter
        from io import StringIO
        payload={'id':'n','message':'result','outlet':{'identity':'entry','destination':'feishu:oc_chat:ou_user'}}
        with patch.object(sys,'argv',['adapter']),patch.object(sys,'stdin',StringIO(json.dumps(payload))),patch.object(sys,'stdout',new_callable=StringIO) as out,patch.object(adapter.subprocess,'run',side_effect=FileNotFoundError('missing executable')) as send:
            with self.assertRaises(SystemExit):adapter.main()
            self.assertTrue(json.loads(out.getvalue())['not_sent']);self.assertEqual(send.call_count,1)

    def test_all_bots_send_without_config_credentials_or_channel_probes(self):
        import notify_cc_connect as adapter
        from io import StringIO
        for session in ('feishu:chat:root:message','feishu:chat:thread:topic','opaque:future-format'):
            for project in ('entry','helper'):
                context={'platform':'feishu','entry_project':'entry','session_key':session,'chat_type':'unknown'}
                payload={'id':'n','message':'result','outlet':{'identity':project},'conversation':context,'alternate_bot':True}
                with patch.object(sys,'argv',['adapter']),patch.object(sys,'stdin',StringIO(json.dumps(payload))),patch.object(sys,'stdout',new_callable=StringIO) as out,patch.object(bridge,'read_config',side_effect=AssertionError('No per-send configuration read')),patch.object(adapter.shutil,'which',return_value='/fake/cc'),patch.object(adapter.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as send:
                    adapter.main()
                self.assertEqual(send.call_count,1)
                self.assertEqual(send.call_args.args[0][3],project)
                self.assertEqual(send.call_args.args[0][5],session)
                self.assertTrue(json.loads(out.getvalue())['delivered'])

    def test_failure_and_timeout_record_actual_delivery_failure_without_switching_bot(self):
        import notify_cc_connect as adapter
        from io import StringIO
        for outcome in (subprocess.CompletedProcess([],1,'','bridge permission denied'),subprocess.TimeoutExpired('send',25)):
            payload={'id':'n','message':'result','outlet':{'identity':'helper','destination':'feishu:chat:root:message'}}
            with patch.object(sys,'argv',['adapter']),patch.object(sys,'stdin',StringIO(json.dumps(payload))),patch.object(sys,'stdout',new_callable=StringIO) as out,patch.object(adapter.shutil,'which',return_value='/fake/cc'),patch.object(adapter.subprocess,'run') as send:
                if isinstance(outcome,Exception):send.side_effect=outcome
                else:send.return_value=outcome
                with self.assertRaises(SystemExit):adapter.main()
                receipt=json.loads(out.getvalue())
                self.assertFalse(receipt['delivered']);self.assertFalse(receipt['not_sent'])
                self.assertEqual(send.call_count,1)

    def test_socket_connection_failure_is_unsent_but_send_failure_is_unknown(self):
        import notify_cc_connect as adapter
        from io import StringIO
        from loop_anything.runtime.notifications import deliver_command, NotificationNotSent
        errors={
            'Error: cc-connect is not running (socket not found: /data/run/api.sock)':True,
            'Error: failed to connect: Post "http://unix/send": dial unix /data/run/api.sock: connect: connection refused':True,
            'Error: failed to connect: Post "http://unix/send": dial unix /data/run/api.sock: connect: no such file or directory':True,
            'Error: failed to connect: Post "http://unix/send": dial unix /data/run/api.sock: connect: permission denied':True,
            'Error: project "removed-bot" not found':True,
            'Error: feishu: reply failed code=230002 msg=Bot/User can NOT be out of the chat.':True,
            'Error: lark: send failed code=230002 msg=The bot can not be outside the group.':True,
            'Error: feishu: reply failed code=999999 msg=unknown failure':False,
            'Error: failed to connect: Post "http://unix/send": EOF':False,
            'Error: failed to connect: Post "http://unix/send": read unix /data/run/api.sock: connection reset by peer':False,
            'Error: feishu reply failed: connection refused':False,
        }
        payload={'id':'n','message':'result','outlet':{'identity':'helper','destination':'feishu:chat:root:message'}}
        for error,unsent in errors.items():
            with self.subTest(error=error),patch.object(sys,'argv',['adapter']),patch.object(sys,'stdin',StringIO(json.dumps(payload))),patch.object(sys,'stdout',new_callable=StringIO) as out,patch.object(adapter.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'',error)) as send:
                with self.assertRaises(SystemExit):adapter.main()
                self.assertEqual(json.loads(out.getvalue())['not_sent'],unsent)
                self.assertEqual(send.call_count,1)
                if unsent:
                    with self.assertRaises(NotificationNotSent):
                        deliver_command({'command':['adapter']},payload,lambda *args:subprocess.CompletedProcess([],2,out.getvalue(),''))


if __name__=='__main__':unittest.main()
