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
from loop_anything.runtime.communication_conversations import register, resolve, from_source

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/loop-anything-platform/scripts'
sys.path.insert(0,str(SCRIPTS))
import cc_connect_context as bridge


class ConversationTests(unittest.TestCase):
    setUp=fixtures.CommunicationTests.setUp
    tearDown=fixtures.CommunicationTests.tearDown
    groups=fixtures.CommunicationTests.groups
    cycle=fixtures.CommunicationTests.cycle
    agent=fixtures.CommunicationTests.agent

    def entry(self, private=False):
        session='feishu:oc_chat:ou_user' if private else 'feishu:oc_chat:root:om_topic'
        context=dict(platform='feishu',chat_id='oc_chat',chat_type='p2p' if private else 'group',session_key=session,
                     thread_root=None if private else 'om_topic',entry_project='entrance')
        return register(self.a,dict(conversation=context,notification_command=[sys.executable,'-c','pass']))['conversation_id']

    def bot(self,comm,gid=None):
        comm.store.notification_channels({'bot':dict(channel='cc-connect',identity='papers-bot',destination='unused',
            command=[sys.executable,'-c','pass'])},revision=0)
        self.agent(comm,groups=[gid] if gid else [])
        comm.config('agent',agent_id='papers',agent={'notification_route':'bot'})
        for machine in (self.a,self.b,self.c):machine.last_scan=0;machine.scan()

    def completed(self, conversation, gid=None, **args):
        ident=self.a.request(dict(location='group' if gid else 'local',group_id=gid,agent_id='papers',
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

    def test_definite_preflight_rejection_falls_back_but_unknown_send_does_not(self):
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
            started=PlatformTools(self.a.store).call('start_run',dict(key=key,title='chat run',authorization='test',conversation_id=cid))
            run=self.a.store.get(started['run_id'])
            self.assertEqual(run['notification_conversation_id'],cid)
            self.assertEqual(run['settings']['notification_command'],[sys.executable,'-c','pass'])
            created=self.a.request(dict(location='local',agent_id='papers',message='node help',
                source={'run_id':run['id'],'task_id':started['entry_task_id']},token=started['token']))['request']
            self.assertEqual(created['notification_policy'],'conversation')
            self.assertEqual(created['notification_conversation']['id'],cid)
        finally:case.tearDown()

    def test_local_preflight_rejection_uses_entry_without_duplicate_delivery(self):
        self.bot(self.a);self.sent=[]
        def send(command,text,*args):
            p=json.loads(text)
            if p['outlet']['identity']=='papers-bot':
                return subprocess.CompletedProcess(command,2,json.dumps({'delivered':False,'not_sent':True}),'')
            return self.receipt(command,text,*args)
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=send):
            ident=self.completed(self.entry())
            self.cycle(lambda:self.a.get(ident).get('notifications',[{}])[-1].get('status')=='delivered')
            for _ in range(3):self.a.tick()
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.sent[0]['outlet']['identity'],'entrance')

    def test_nested_explicit_outlet_and_followup_survive_source_mirror(self):
        gid=self.groups();conversation=self.entry()
        parent_id=self.a.request(dict(location='group',group_id=gid,agent_id='papers',message='parent',conversation_id=conversation))['request']['id']
        with self.a.transaction() as db:
            parent=self.a.get(parent_id,db);parent.update(executor=self.b.settings()['instance_id'],state='running');self.a.save(db,parent)
        with self.b.transaction() as db:self.b.save(db,dict(parent,worker_token='worker'))
        args=dict(location='group',agent_id='papers',message='quiet child',notification_route='workspace',notification_level='attention')
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

    def test_captured_run_sender_keeps_preflight_delivery_timeout(self):
        from loop_anything.runtime.notifications import sender_for
        run={'settings':{'notification_command':['adapter']},'notification_conversation_id':self.entry()}
        _,sender=sender_for(self.a.store,run,'default')
        self.assertGreaterEqual(sender.get('timeout',30),60)

    def test_nested_remote_assistance_inherits_original_conversation(self):
        gid=self.groups();conversation=self.entry()
        parent_id=self.a.request(dict(location='group',group_id=gid,agent_id='papers',message='parent',conversation_id=conversation))['request']['id']
        with self.a.transaction() as db:
            parent=self.a.get(parent_id,db);parent.update(executor=self.b.settings()['instance_id'],state='running');self.a.save(db,parent)
        with self.b.transaction() as db:self.b.save(db,dict(parent,worker_token='worker'))
        child=self.b.worker_call(parent_id,'worker','request_assistance',dict(location='group',agent_id='papers',message='child',conversation_id='forged',chat_context={'platform':'feishu','entry_project':'forged','session_key':'feishu:oc_wrong:ou_wrong'}))['request']
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
        with patch.object(bridge,'inspect_compatible',side_effect=AssertionError('No channel preflight on request')):
            binding=from_source(self.a,context);self.assertEqual(binding['id'],from_source(self.a,context)['id'])
            created=self.a.request(dict(location='local',agent_id='papers',message='work without cc-connect',chat_context=context))['request']
        with self.a.transaction() as db:
            row=self.a.get(created['id'],db);row.update(state='completed',result={'answer':42});self.a.save(db,row)
        def unavailable(command,text,*args):return subprocess.CompletedProcess(command,2,json.dumps({'delivered':False,'not_sent':True,'error':'cc-connect unavailable'}),'')
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=unavailable):
            self.cycle(lambda:self.a.get(created['id']).get('notifications',[{}])[-1].get('status')=='fault')
        current=self.a.get(created['id']);self.assertEqual(current['state'],'completed');self.assertEqual(current['result'],{'answer':42})
        self.assertIn('cc-connect unavailable',current['notifications'][-1]['error'])
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

    def test_platform_selects_configured_entry_adapter_with_local_paths(self):
        command=[sys.executable,'adapter.py','--config','/local/bridge.toml','--data-dir','/local/bridge']
        self.a.store.notification_channels({'entry':{'channel':'cc-connect','identity':'entrance','destination':'old destination','command':command,'cwd':'/local/working'}},revision=0)
        binding=from_source(self.a,{'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:root:om_topic'})
        saved=resolve(self.a,binding['id'],include_sender=True)
        self.assertEqual(saved['sender']['command'],command);self.assertEqual(saved['sender']['cwd'],'/local/working')
        self.assertEqual(saved['sender']['destination'],'feishu:oc_chat:root:om_topic')
        self.assertNotIn('/local/',json.dumps(binding))

    def test_same_bot_multiple_destinations_preserve_identical_adapter(self):
        command=[sys.executable,'adapter.py','--data-dir','/configured/bridge']
        self.a.store.notification_channels({name:{'channel':'cc-connect','identity':'entrance','destination':name,'command':command,'timeout':timeout} for name,timeout in (('chat-a',60),('chat-b',90))},revision=0)
        binding=from_source(self.a,{'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:root:om_topic'})
        sender=resolve(self.a,binding['id'],include_sender=True)['sender']
        self.assertEqual(sender['command'],command);self.assertEqual(sender['timeout'],90)
        self.assertEqual(sender['destination'],'feishu:oc_chat:root:om_topic')

    def test_conflicting_entry_adapters_record_configuration_error_without_blocking_work(self):
        self.a.store.notification_channels({name:{'channel':'cc-connect','identity':'entrance','destination':name,'command':[sys.executable,name+'.py']} for name in ('a','b')},revision=0)
        context={'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:root:om_topic'}
        self.agent(self.a)
        created=self.a.request(dict(location='local',agent_id='papers',message='keep working',chat_context=context))['request']
        with self.a.transaction() as db:
            row=self.a.get(created['id'],db);row.update(state='completed',result={'answer':42});self.a.save(db,row)
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=AssertionError('Ambiguous sender must not execute')):
            self.cycle(lambda:self.a.get(created['id']).get('notifications',[{}])[-1].get('status')=='waiting_configuration')
        self.assertEqual(self.a.get(created['id'])['state'],'completed')
        import test_timeline_runtime as runtime
        from loop_anything.interfaces.platform_tools import PlatformTools
        from loop_anything.runtime.notifications import enqueue
        case=runtime.RuntimeTests();case.setUp()
        try:
            key=self.a.store.publish(case.bp,case.implementations)['key']
            started=PlatformTools(self.a.store).call('start_run',dict(key=key,title='ambiguous adapter',authorization='test',chat_context=context))
            run=self.a.store.get(started['run_id']);notice=enqueue(self.a.store,run,'notice',{'message':'result'})
            self.assertEqual(notice['status'],'waiting_configuration');self.assertIn('Multiple adapters',notice['error'])
            self.a.store.notification_channels({'a':{'channel':'cc-connect','identity':'entrance','destination':'unused','command':[sys.executable,'a.py']}},revision=1)
            with self.a.store.edit(run['id']) as saved:
                retried=enqueue(self.a.store,saved,'fixed-notice',{'message':'result'})
                self.assertEqual(retried['sender']['command'],[sys.executable,'a.py'])
            self.sent=[]
            notice_id=self.a.get(created['id'])['notifications'][-1]['id']
            self.a.control(created['id'],'retry_notification',notification_id=notice_id)
            with patch('loop_anything.runtime.host_runtime.run_command',side_effect=self.receipt):
                self.cycle(lambda:self.a.get(created['id'])['notifications'][-1]['status']=='delivered')
            self.assertEqual(self.sent[-1]['conversation']['thread_root'],'om_topic')
            chosen=resolve(self.a,self.a.get(created['id'])['notification_conversation']['id'],include_sender=True)['sender']['command']
            self.a.store.notification_channels({'a':{'channel':'cc-connect','identity':'entrance','command':[sys.executable,'different.py']}},revision=2)
            refreshed=resolve(self.a,self.a.get(created['id'])['notification_conversation']['id'],include_sender=True,refresh_sender=True)
            self.assertEqual(refreshed['sender']['command'],chosen)
        finally:case.tearDown()

    def test_run_metadata_reaches_timeline_notification_without_cli_probe(self):
        import test_timeline_runtime as runtime
        from loop_anything.interfaces.platform_tools import PlatformTools
        from loop_anything.runtime.notifications import enqueue
        case=runtime.RuntimeTests();case.setUp()
        try:
            key=self.a.store.publish(case.bp,case.implementations)['key']
            context={'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:root:om_topic'}
            tools=PlatformTools(self.a.store)
            with patch.object(bridge,'capture_arguments',side_effect=AssertionError('No eager capture')):
                started=tools.call('start_run',dict(key=key,title='chat run',authorization='test',chat_context=context))
            run=self.a.store.get(started['run_id']);self.assertIn('notification_conversation_id',run)
            notice=enqueue(self.a.store,run,'test-notice',{'message':'result'})
            self.assertEqual(notice['conversation']['session_key'],context['session_key'])
            self.assertEqual(notice['sender']['identity'],'entrance')
            explicit=tools.call('start_run',dict(key=key,title='explicit',authorization='test',chat_context=context,notification_route='workspace'))
            self.assertNotIn('notification_conversation_id',self.a.store.get(explicit['run_id']))
        finally:case.tearDown()


class BridgePreflightTests(unittest.TestCase):
    def inspect(self, expected=None, root='om_root', options=None, chat=None, member=True):
        defaults={'app_id':'local-id','app_secret':'secret','thread_isolation':True,'reply_to_trigger':True}
        defaults.update(options or {})
        def api(base,path,token=None,data=None):
            if path.endswith('/internal'):return {'tenant_access_token':'private-token'}
            if path.endswith('/is_in_chat'):return {'data':{'is_in_chat':member}}
            if '/messages/' in path:return {'data':{'items':[{'message_id':'om_root','chat_id':'oc_chat'}]}}
            return {'data':chat or {'chat_mode':'group','group_message_type':'thread','moderation_permission':'all_members'}}
        session='feishu:oc_chat:root:'+root if root else 'feishu:oc_chat:ou_user'
        with patch.object(bridge,'config_options',return_value=defaults),patch.object(bridge,'bridge_ready'),patch.object(bridge,'api',side_effect=api):
            return bridge.inspect('papers-bot',session,'unused','unused',expected)

    def test_preflight_checks_membership_thread_config_and_root(self):
        self.assertEqual(self.inspect()['thread_root'],'om_root')
        for args in ({'root':None},{'member':False},{'options':{'thread_isolation':False}},
                     {'options':{'reply_to_trigger':False}},{'root':'om_wrong'}):
            with self.subTest(args=args),self.assertRaises(ValueError):self.inspect(**args)
        context=self.inspect();context['entry_project']='entrance'
        with self.assertRaises(ValueError):self.inspect(expected=context,chat={'chat_mode':'group','moderation_permission':'only_owner'})
        context.update(chat_type='p2p',session_key='feishu:oc_chat:ou_user',thread_root=None)
        with self.assertRaises(ValueError):self.inspect(expected=context,root=None,chat={'chat_mode':'p2p'})

    def test_adapter_preflight_failure_never_calls_send(self):
        import notify_cc_connect as adapter
        payload={'id':'n','message':'result','conversation':{'session_key':'feishu:oc_chat:root:om_root'}}
        from io import StringIO
        with patch.object(sys,'argv',['adapter','--project','papers','--session','unused','--conversation']),patch.object(sys,'stdin',StringIO(json.dumps(payload))),patch.object(sys,'stdout',new_callable=StringIO) as out,patch.object(bridge,'inspect_compatible',side_effect=ValueError('not in chat')),patch.object(adapter.shutil,'which',return_value='/fake/cc-connect'),patch.object(adapter.subprocess,'run') as send:
            with self.assertRaises(SystemExit):adapter.main()
            self.assertTrue(json.loads(out.getvalue())['not_sent']);send.assert_not_called()


    def test_cli_started_timeout_never_claims_not_sent(self):
        import notify_cc_connect as adapter
        from io import StringIO
        payload={'id':'n','message':'result','outlet':{'identity':'bot','destination':''},'conversation':{'session_key':'feishu:oc_chat:root:om_root','entry_project':'bot'}}
        with patch.object(sys,'argv',['adapter']),patch.object(sys,'stdin',StringIO(json.dumps(payload))),patch.object(sys,'stdout',new_callable=StringIO) as out,patch.object(bridge,'inspect_compatible',return_value={}),patch.object(adapter.shutil,'which',return_value='/fake/cc-connect'),patch.object(adapter.subprocess,'run',side_effect=subprocess.TimeoutExpired('send',25)):
            with self.assertRaises(SystemExit):adapter.main()
            self.assertFalse(json.loads(out.getvalue())['not_sent'])

    def test_client_only_carries_metadata_with_no_bridge_or_channel_access(self):
        import call as client
        import os
        from io import StringIO
        for tool in ('request_assistance','start_run'):
            for extra in ({},{'notification_route':'workspace'},{'conversation_id':'existing'},{'source':{'run_id':'run-a'}}):
                with self.subTest(tool=tool,extra=extra):
                    calls=[]
                    def fetch(url,data=None):
                        body=json.loads(data);calls.append(body);return {'ok':True}
                    argv=['call',tool,'--url','http://remote.example:1','--arguments',json.dumps(dict(message='help',**extra))]
                    with patch.object(sys,'argv',argv),patch.object(sys,'stdout',new_callable=StringIO),patch.dict(os.environ,{'CC_PROJECT':'entrance','CC_SESSION_KEY':'feishu:oc_chat:ou_user','PATH':''}),patch.object(bridge,'capture_arguments',side_effect=AssertionError('Client must not capture')),patch.object(client,'fetch',side_effect=fetch):
                        with self.assertRaises(SystemExit) as exit:client.main()
                        self.assertEqual(exit.exception.code,0)
                    self.assertEqual(len(calls),1);self.assertEqual(calls[0]['tool'],tool)
                    if not extra:self.assertEqual(calls[0]['arguments']['chat_context'],{'platform':'feishu','entry_project':'entrance','session_key':'feishu:oc_chat:ou_user'})
                    else:self.assertNotIn('chat_context',calls[0]['arguments'])

    def test_unknown_chat_type_is_resolved_and_private_chat_cannot_use_another_bot(self):
        context=self.inspect(expected={'platform':'feishu','chat_id':'oc_chat','chat_type':'unknown','session_key':'feishu:oc_chat:ou_user','thread_root':None,'entry_project':'papers-bot'},root=None,chat={'chat_mode':'p2p'})
        self.assertEqual(context['chat_type'],'p2p')
        with self.assertRaises(ValueError):self.inspect(expected=dict(context,chat_type='unknown',entry_project='entrance'),root=None,chat={'chat_mode':'p2p'})

    def test_sending_adapter_resolves_and_sends_to_original_topic(self):
        import notify_cc_connect as adapter
        from io import StringIO
        origin={'platform':'feishu','chat_id':'oc_chat','chat_type':'group','session_key':'feishu:oc_chat:root:om_root','thread_root':'om_root','entry_project':'entrance'}
        payload={'id':'n','message':'result','outlet':{'identity':'papers-bot','destination':'wrong old destination'},'conversation':origin}
        checked=dict(origin,entry_project='papers-bot')
        with patch.object(sys,'argv',['adapter']),patch.object(sys,'stdin',StringIO(json.dumps(payload))),patch.object(sys,'stdout',new_callable=StringIO) as out,patch.object(bridge,'inspect_compatible',return_value=checked) as inspect,patch.object(adapter.shutil,'which',return_value='/fake/cc-connect'),patch.object(adapter.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as send:
            adapter.main()
        self.assertEqual(inspect.call_args.args[:2],('papers-bot',origin['session_key']))
        self.assertEqual(send.call_args.args[0][:5],['/fake/cc-connect','send','--project','papers-bot','--session'])
        self.assertEqual(send.call_args.args[0][5],origin['session_key'])
        receipt=json.loads(out.getvalue());self.assertTrue(receipt['delivered']);self.assertEqual(receipt['conversation']['entry_project'],'entrance')

    def test_adapter_missing_executable_records_definite_unsent(self):
        import notify_cc_connect as adapter
        from io import StringIO
        payload={'id':'n','message':'result','outlet':{'identity':'entry','destination':'feishu:oc_chat:ou_user'}}
        with patch.object(sys,'argv',['adapter']),patch.object(sys,'stdin',StringIO(json.dumps(payload))),patch.object(sys,'stdout',new_callable=StringIO) as out,patch.object(adapter.shutil,'which',return_value=None),patch.object(adapter.subprocess,'run') as send:
            with self.assertRaises(SystemExit):adapter.main()
            self.assertTrue(json.loads(out.getvalue())['not_sent']);send.assert_not_called()


if __name__=='__main__':unittest.main()
