import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Invalid, Conflict


class CommunicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engines = [Engine(Store(self.root / (n + '.db'))) for n in ('a', 'b', 'c')]
        self.a, self.b, self.c = [e.communication for e in self.engines]

    def tearDown(self):
        for engine in self.engines:
            engine.close()
        self.tmp.cleanup()

    def agent(self, comm, ident='papers', groups=(), local=True):
        comm.config('agent', agent_id=ident, task_confirmed=True, agent={'name':'论文助手','description':'查论文','capabilities':['papers'],
                    'local':local,'groups':list(groups),'implementation':{'kind':'agent','command':[sys.executable,'-c','pass']}})

    def groups(self):
        config = self.a.config('group', path=str(self.root/'nas'), create=True)['configuration']
        gid = next(iter(config['groups']))
        for comm in (self.b,self.c):comm.config('group',path=str(self.root/'nas'))
        return gid

    def test_delayed_claim_remains_valid_before_default_acceptance_deadline(self):
        gid=self.groups();self.agent(self.b,groups=[gid])
        created=self.a.request({'location':'group','group_id':gid,'agent_id':'papers','message':'help'})['request']
        self.assertAlmostEqual(created['deadline']-created['created_at'],300,places=2)
        self.assertEqual(created['next_action'],'await_assignment')
        with patch('loop_anything.runtime.communication.time.time',return_value=created['created_at']+29):
            self.a.tick()
            self.assertEqual(self.a.get(created['id'])['state'],'pending')
            self.a.receive({'id':'delayed-claim','kind':'claim','request_id':created['id'],
                'sender':self.b.settings()['instance_id'],'target':self.a.settings()['instance_id'],
                'group_id':gid,'assignment_id':None,'payload':{'agent_id':'papers'}})
        self.assertEqual(self.a.get(created['id'])['state'],'assigned')

    def test_cancelled_request_explains_late_claim_rejection_to_executor(self):
        gid=self.groups();self.agent(self.b,groups=[gid])
        created=self.a.request({'location':'group','group_id':gid,'agent_id':'papers','message':'help'})['request']
        with self.a.store.connection() as db:
            offer=next(json.loads(r[0]) for r in db.execute('SELECT document FROM communication_outbox') if json.loads(r[0])['kind']=='offer')
        self.b.receive(offer)
        cancelled=self.a.control(created['id'],'cancel',reason='User withdrew the task')['request']
        self.assertEqual(cancelled['cancellation']['previous_state'],'pending')
        with self.b.store.connection() as db:
            claim=next(json.loads(r[0]) for r in db.execute('SELECT document FROM communication_outbox') if json.loads(r[0])['kind']=='claim')
        self.a.receive(claim)
        with self.a.store.connection() as db:
            reply=next(json.loads(r[0]) for r in db.execute('SELECT document FROM communication_outbox') if json.loads(r[0])['kind']=='not_selected')
        self.b.receive(reply)
        decision=self.b.read(created['id'])['request']['selection_decision']
        self.assertEqual(decision['reason'],'cancelled')
        self.assertEqual(decision['source_state'],'cancelled')
        self.assertEqual(decision['cancellation']['reason'],'User withdrew the task')
        self.assertTrue(any(e['kind']=='claim_not_selected' for e in self.a.get(created['id'])['history']))

    def cycle(self, predicate, timeout=5):
        until = time.monotonic()+timeout
        while time.monotonic()<until:
            for comm in (self.a,self.b,self.c):
                comm.last_scan=0
                comm.tick()
            if predicate():return
            time.sleep(.02)
        self.fail('Communication did not reach expected state: '+str([[{k:r.get(k) for k in ('id','state','kind','error')} for r in c.requests()] for c in (self.a,self.b,self.c)]))

    def worker(self, command, prompt, *args, **kwargs):
        context=json.loads(prompt.split('\n',1)[1])
        for comm in (self.a,self.b,self.c):
            if comm.authorized(context,worker=True):
                comm.worker_call(context['request_id'],context['token'],'complete',{'result':{'papers':['one']}})
                return subprocess.CompletedProcess(command,0,'','')
        raise AssertionError('No worker identity')

    def test_local_without_group_or_run_and_no_automatic_registration(self):
        self.assertEqual(self.a.directory()['agents'],[])
        self.agent(self.a)
        result=self.a.request({'location':'local','agent_id':'papers','message':'查论文'})
        self.assertEqual(len(self.a.store.list()),1)
        self.assertIn('collaboration',self.a.store.list()[0])
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=self.worker):
            self.cycle(lambda:self.a.get(result['request']['id'])['state']=='completed')
        self.assertEqual(self.a.get(result['request']['id'])['result'],{'papers':['one']})
        with self.a.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM communication_outbox').fetchone()[0],0)
        self.assertTrue(self.a.authorized({'request_id':result['request']['id'],'token':result['request_token']}))
        self.assertFalse(self.a.authorized({'request_id':result['request']['id'],'token':'wrong'}))

    def test_assistance_context_task_accepts_business_json_without_blocking_launch(self):
        gid=self.groups();self.agent(self.a);self.agent(self.b,groups=[gid])
        contexts=[{}, {'task':'分析实验结果并查找相关论文'}, {'task':None}, {'task':['分析','检索']},
                  {'task':42}, {'task':{'skills':['paper-review'],'instructions':'Compare methods'}}]
        received=[]
        def worker(command,prompt,*args,**kwargs):
            received.append(json.loads(prompt.split('\n',1)[1]))
            return self.worker(command,prompt,*args,**kwargs)
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=worker):
            for location in ('local','group'):
                for context in contexts:
                    with self.subTest(location=location,context=context):
                        row=self.a.request({'location':location,'group_id':gid,'agent_id':'papers',
                                            'message':'process context','context':context})['request']
                        self.cycle(lambda:self.a.get(row['id'])['state'] in ('completed','failed'))
                        result=self.a.get(row['id'])
                        self.assertEqual(result['state'],'completed',result.get('error'))
                        supplied=next(c for c in received if c['request_id']==row['id'])
                        self.assertEqual(supplied['context'],context)
                        self.assertEqual(result['result'],{'papers':['one']})
                        if isinstance(context.get('task'),dict):
                            self.assertEqual(supplied['skills'],context['task']['skills'])
                            self.assertEqual(supplied['instructions'],context['task']['instructions'])

    def test_two_candidates_one_assignment_and_result_roundtrip(self):
        gid=self.groups()
        self.agent(self.b,groups=[gid]);self.agent(self.c,groups=[gid])
        row=self.a.request({'location':'group','group_id':gid,'capability':'papers','message':'查论文'})['request']
        calls=[]
        def worker(*args,**kw):calls.append(1);return self.worker(*args,**kw)
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=worker):
            self.cycle(lambda:self.a.get(row['id'])['state']=='completed')
            self.cycle(lambda:not self.b.live and not self.c.live)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.a.get(row['id'])['result'],{'papers':['one']})
        self.assertEqual(len(self.a.store.list()),1)
        self.assertIn('collaboration',self.a.store.list()[0])

    def test_missing_group_and_ambiguous_local_target_are_explicit(self):
        self.agent(self.a,'one');self.agent(self.a,'two')
        with self.assertRaises(Invalid):self.a.request({'location':'local','message':'help'})
        with self.assertRaises(Invalid):self.a.request({'location':'group','message':'help'})

    def test_same_agent_id_on_two_machines_requires_explicit_instance(self):
        gid=self.groups();self.agent(self.b,groups=[gid]);self.agent(self.c,groups=[gid])
        for comm in (self.b,self.c,self.a):comm.last_scan=0;comm.scan()
        args={'location':'group','group_id':gid,'agent_id':'papers','message':'help'}
        with self.assertRaises(Invalid):self.a.request(args)
        request=self.a.request(dict(args,instance_id=self.b.settings()['instance_id']))['request']
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=self.worker):
            self.cycle(lambda:self.a.get(request['id'])['state']=='completed')
        self.assertEqual(self.a.get(request['id'])['executor'],self.b.settings()['instance_id'])

    def test_exit_does_not_delete_history_or_silently_accept(self):
        gid=self.groups();self.agent(self.b,groups=[gid])
        self.b.config('leave',group_id=gid)
        self.assertFalse(self.b.eligible(self.b.settings()['agents']['papers'],{'location':'group','group_id':gid},self.b.settings()))
        self.assertTrue(self.b.eligible(self.b.settings()['agents']['papers'],{'location':'local'},self.b.settings()))

    def test_group_directory_advertises_only_explicitly_bound_loops(self):
        import test_timeline_runtime as fixture
        base=fixture.RuntimeTests();base.setUp()
        try:
            gid=self.groups()
            key=self.a.store.publish(base.bp,base.implementations)['key']
            base.bp['id']='not-shared'
            private=self.a.store.publish(base.bp,base.implementations)['key']
            self.a.config('bind_loop',loop_key=key,group_id=gid)
            self.a.scan();self.b.scan()
            refs=self.b.directory(gid)['loops']
            self.assertIn(key,[x['loop_key'] for x in refs])
            self.assertNotIn(private,[x['loop_key'] for x in refs])
        finally:base.tearDown()

    def test_recovery_does_not_start_unknown_process_again(self):
        self.agent(self.a)
        row=self.a.request({'location':'local','agent_id':'papers','message':'help'})['request']
        with self.a.transaction() as db:
            r=self.a.get(row['id'],db);r['state']='running';self.a.save(db,r)
        self.a.recover()
        self.assertEqual(self.a.get(row['id'])['state'],'unknown')
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=AssertionError('must not restart')):
            self.a.tick()
        self.assertEqual(self.a.get(row['id'])['state'],'unknown')

    def test_remote_node_uses_source_tools_and_never_creates_remote_run(self):
        import test_timeline_runtime as fixture
        base=fixture.RuntimeTests();base.setUp()
        try:
            gid=self.groups();self.agent(self.b,groups=[gid]);self.agent(self.b,'local-helper')
            base.implementations['init']={'kind':'agent','dispatch':{'location':'group','agent_id':'papers'}}
            from loop_anything.packaging.packages import make_archive,install
            base.bp['nodes']['init']['skills']=[{'name':'method','path':'skills/method/SKILL.md'}]
            content=b'# Method\n'+b'x'*1100000
            key=install(self.a.store,make_archive({'loop_definition':base.bp,'implementations':base.implementations},{'skills/method/SKILL.md':(content,False)}))['key']
            self.a.config('bind_loop',loop_key=key,group_id=gid)
            runid=self.a.store.create(key,'remote')['id']
            def remote(command,prompt,*args,**kw):
                context=json.loads(prompt.split('\n',1)[1])
                if context['kind']=='assistance':return self.worker(command,prompt,*args,**kw)
                self.assertEqual(Path(context['context']['task']['skills'][0]['resolved_path']).read_bytes(),content)
                comm=self.b if self.b.authorized(context,worker=True) else self.c
                def source(tool,arguments):
                    response=comm.worker_call(context['request_id'],context['token'],'source_call',{'tool':tool,'arguments':arguments})
                    ident=response['call']['id'];deadline=time.monotonic()+4
                    while time.monotonic()<deadline:
                        call=comm.get(context['request_id'])['rpc'][ident]
                        if call['state']=='failed':raise AssertionError(call['error'])
                        if call['state']=='completed':return call['result']
                        time.sleep(.01)
                    raise AssertionError('source call timeout')
                child=comm.worker_call(context['request_id'],context['token'],'request_assistance',{'location':'local','agent_id':'local-helper','message':'无需群组的本机帮助'})['request']
                until=time.monotonic()+5
                while comm.get(child['id'])['state'] not in ('completed','failed') and time.monotonic()<until:time.sleep(.01)
                self.assertEqual(comm.worker_call(context['request_id'],context['token'],'read_assistance',{'request_id':child['id']})['request']['result']['papers'],['one'])
                info=source('read_task',{'task_id':'init'})
                source('report_task',{'task_id':'init','task_version':info['task_version'],'event':'completed','report_id':'done',
                    'envelope':{'outputs':{'a':'A','b':'B'},'settings':{'objective':'remote'}}})
                source('finish',{})
                comm.worker_call(context['request_id'],context['token'],'complete',{'result':{}})
                return subprocess.CompletedProcess(command,0,'','')
            with patch('loop_anything.runtime.host_runtime.run_command',side_effect=remote):
                self.engines[0].tick(runid)
                self.cycle(lambda:any(r['kind']=='node_execution' and r['state']=='completed' for r in self.a.requests()),timeout=15)
            run=self.a.store.get(runid)
            self.assertEqual(run['records']['a'][0]['value'],'A')
            self.assertEqual(run['agent_sessions'],[])
            self.assertEqual(self.b.store.list(),[])
            self.assertEqual(self.c.store.list(),[])
        finally:base.tearDown()

    def test_assistance_wait_releases_owner_and_wakes_same_task_once(self):
        import test_timeline_runtime as fixture
        from loop_anything.interfaces.agent_tasks import RunTools
        base=fixture.RuntimeTests();base.setUp()
        try:
            key=self.a.store.publish(base.bp,base.implementations)['key']
            runid=self.a.store.create(key,'wait')['id'];self.engines[0].tick(runid)
            run=self.a.store.get(runid);token=run['agent_sessions'][0]['token']
            with self.a.store.edit(runid) as current:
                current['executions'][0]['implementation'].update(command=[sys.executable,'-c','pass'],resume_command=[sys.executable,'-c','pass','{{session_id}}','{{prompt}}'])
            RunTools(self.a.store,runid,token).call('register_agent_session',{'execution_id':run['executions'][0]['id'],'provider':'custom','session_id':'wait-original-session'})
            self.agent(self.a)
            req=self.a.request({'location':'local','agent_id':'papers','message':'查论文',
                'source':{'run_id':runid,'task_id':'init'},'token':token})['request']
            self.a.wait_assistance(runid,token,'init',[req['id']],seconds=30)
            RunTools(self.a.store,runid,token).call('finish',{})
            with patch('loop_anything.runtime.host_runtime.run_command',side_effect=self.worker):
                self.cycle(lambda:self.a.store.get(runid)['tasks']['init']['status']=='ready')
            self.a.wake_assistance();self.a.wake_assistance()
            run=self.a.store.get(runid)
            self.assertEqual(len(run['tasks']),1)
            self.assertEqual(run['tasks']['init']['assistance_results'][0]['result']['papers'],['one'])
            self.assertEqual(sum(h['kind']=='assistance_ready' for h in run['history']),1)
            self.assertEqual(run['records'],{})
        finally:base.tearDown()

    def test_run_group_snapshot_and_explicit_scope(self):
        import test_timeline_runtime as fixture
        base=fixture.RuntimeTests();base.setUp()
        try:
            gid=self.groups();key=self.a.store.publish(base.bp,base.implementations)['key']
            runid=self.a.store.create(key,'snapshot')['id']
            self.a.config('bind_loop',loop_key=key,group_id=gid)
            self.assertIsNone(self.a.run_group(self.a.store.get(runid)))
            self.engines[0].tick(runid);run=self.a.store.get(runid)
            with self.assertRaises(Conflict):
                self.a.request({'location':'group','group_id':gid,'agent_id':'papers','message':'help',
                    'source':{'run_id':runid,'task_id':'init'},'token':run['agent_sessions'][0]['token']})
        finally:base.tearDown()

    def test_wait_requires_original_session_and_legacy_wait_never_starts_fresh(self):
        import test_timeline_runtime as fixture
        from loop_anything.interfaces.agent_tasks import RunTools
        base=fixture.RuntimeTests();base.setUp()
        try:
            key=self.a.store.publish(base.bp,base.implementations)['key']
            rid=self.a.store.create(key,'missing session')['id'];self.engines[0].tick(rid)
            run=self.a.store.get(rid);token=run['agent_sessions'][0]['token']
            self.agent(self.a)
            request=self.a.request({'location':'local','agent_id':'papers','message':'help','source':{'run_id':rid,'task_id':'init'},'token':token})['request']
            with self.a.store.edit(rid) as current:current['executions'][0]['implementation'].update(command=[sys.executable,'-c','pass'])
            with self.assertRaisesRegex(Invalid,'native CLI session'):self.a.wait_assistance(rid,token,'init',[request['id']])
            self.assertEqual(self.a.store.get(rid)['tasks']['init']['status'],'decision')
            with self.a.store.edit(rid) as current:
                current['tasks']['init'].update(status='waiting_user',assistance_wait={'requests':[request['id']],'deadline':0,'execution_id':current['executions'][0]['id']})
                current['executions'][0]['status']='waiting_user'
            RunTools(self.a.store,rid,token).call('finish',{})
            self.a.wake_assistance();self.a.wake_assistance()
            current=self.a.store.get(rid)
            self.assertEqual(current['tasks']['init']['status'],'waiting_user')
            self.assertIn('native CLI session',current['tasks']['init']['assistance_resume_error'])
            self.assertEqual(sum(h['kind']=='assistance_resume_blocked' for h in current['history']),1)
            self.assertEqual(len(current['executions']),1)
            from loop_anything.interfaces.agent_tasks import acquire
            operator=acquire(self.a.store,rid)
            before_retry=self.a.store.get(rid)
            with self.assertRaisesRegex(Conflict,'original native CLI session'):
                RunTools(self.a.store,rid,operator['token']).call('change_task',{'task_id':'init','operation':'retry','reason':'Retry old waiting task'})
            after_retry=self.a.store.get(rid)
            self.assertEqual(after_retry['tasks'],before_retry['tasks'])
            self.assertEqual(after_retry['executions'],before_retry['executions'])
            self.assertEqual(after_retry['agent_sessions'],before_retry['agent_sessions'])
            with self.a.store.edit(rid) as current:
                current['tasks']['init']['assistance_resume']={'native_session':{'provider':'custom','id':'recovered-session'}}
            RunTools(self.a.store,rid,operator['token']).call('change_task',{'task_id':'init','operation':'cancel','reason':'User cancelled while waiting'})
            self.a.wake_assistance()
            self.assertEqual(self.a.store.get(rid)['tasks']['init']['status'],'cancelled')
        finally:base.tearDown()

    def test_cancel_before_launch_and_large_message_roundtrip(self):
        from loop_anything.runtime.communication import publish_message,read_message
        self.agent(self.a)
        row=self.a.request({'location':'local','agent_id':'papers','message':'help'})['request']
        self.a.control(row['id'],'cancel')
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=AssertionError('cancelled request launched')):
            self.a.tick()
        self.assertEqual(self.a.get(row['id'])['state'],'cancelled')
        file=self.root/'transport'/'message.json';message={'text':'large'*300000}
        publish_message(file,message)
        self.assertEqual(read_message(file),message)
        mtime=file.stat().st_mtime_ns
        publish_message(file,message)
        self.assertEqual(file.stat().st_mtime_ns,mtime)
        with self.assertRaises(Conflict):publish_message(file,{'text':'changed'})
        part=file.with_name('message-part-0.bin');part.write_bytes(b'corrupt')
        with self.assertRaises(Invalid):read_message(file)
        publish_message(file,message)
        self.assertEqual(read_message(file),message)

    def test_runtime_context_tracks_explicit_group_rebinding_and_unbinding(self):
        import test_timeline_runtime as fixture
        from loop_anything.runtime.agent_prompt import task_context
        base=fixture.RuntimeTests();base.setUp()
        try:
            gid=self.groups();key=self.a.store.publish(base.bp,base.implementations)['key']
            self.a.config('bind_loop',loop_key=key,group_id=gid)
            rid=self.a.store.create(key,'binding')['id'];self.engines[0].tick(rid)
            run=self.a.store.get(rid);execution=run['executions'][0]
            self.assertEqual(task_context(self.a.store,run,execution,None,None)['communication']['group_id'],gid)
            self.a.config('bind_loop',run_id=rid,group_id=None)
            self.assertIsNone(task_context(self.a.store,run,execution,None,None)['communication']['group_id'])
            self.a.config('bind_loop',run_id=rid,group_id=gid)
            self.assertEqual(task_context(self.a.store,run,execution,None,None)['communication']['group_id'],gid)
        finally:base.tearDown()

    def test_followup_preserves_group_and_can_read_fresh_loop_context(self):
        import test_timeline_runtime as fixture
        base=fixture.RuntimeTests();base.setUp()
        try:
            gid=self.groups();self.agent(self.a)
            key=self.a.store.publish(base.bp,base.implementations)['key']
            self.a.config('bind_loop',loop_key=key,group_id=gid)
            rid=self.a.store.create(key,'initial title')['id'];self.engines[0].tick(rid)
            token=self.a.store.get(rid)['agent_sessions'][0]['token']
            old=self.a.request({'location':'local','agent_id':'papers','message':'help','source':{'run_id':rid,'task_id':'init'},'token':token})['request']
            with self.a.transaction() as db:
                row=self.a.get(old['id'],db);row['state']='completed';self.a.save(db,row)
            with self.a.store.edit(rid) as run:run['title']='updated title'
            new=self.a.control(old['id'],'followup',message='continue',resume=False)['request']
            self.assertEqual(new['scope_group_id'],gid)
            with self.a.transaction() as db:
                row=self.a.get(new['id'],db);row.update(state='running',worker_token='followup-token');self.a.save(db,row)
            result=self.a.worker_call(new['id'],'followup-token','read_context',{})
            self.a.process_rpcs()
            answer=self.a.worker_call(new['id'],'followup-token','source_result',{'id':result['call']['id']})['call']
            self.assertEqual(answer['state'],'completed',answer)
            self.assertEqual(answer['result']['context']['run']['title'],'updated title')
            with self.assertRaises(Conflict):self.a.worker_call(new['id'],'followup-token','source_call',{'tool':'finish','arguments':{}})
        finally:base.tearDown()

    def test_copied_identity_cannot_execute_and_bad_peer_does_not_block(self):
        import shutil
        source=self.a.settings()['instance_id']
        with self.a.store.connection() as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        clone=self.root/'clone.db';shutil.copy2(self.a.store.filename,clone)
        other=Engine(Store(clone));self.engines.append(other)
        self.assertTrue(other.communication.identity_conflict)
        with self.assertRaises(Conflict):other.communication.request({'location':'local','message':'help'})
        other.communication.config('identity',name='Clone',regenerate=True)
        self.assertNotEqual(other.communication.settings()['instance_id'],source)
        gid=self.groups();members=self.root/'nas'/'members';members.mkdir(exist_ok=True)
        (members/'bad.json').write_text('{broken')
        self.a.scan();self.assertTrue((members/(self.a.settings()['instance_id']+'.json')).exists())

    def test_notifications_use_existing_outlet_and_retry_explicitly(self):
        self.agent(self.a)
        row=self.a.request({'location':'local','agent_id':'papers','message':'notify','notification_route':'missing','notification_level':'attention'})['request']
        with self.a.transaction() as db:
            current=self.a.get(row['id'],db);current.update(state='failed',error='test');self.a.save(db,current)
        self.a.deliver_notifications()
        for future in list(self.engines[0].futures):future.result(timeout=3)
        notice=self.a.get(row['id'])['notifications'][0]
        self.assertEqual(notice['status'],'waiting_configuration')
        self.a.store.notification_channels({'missing':{'command':[sys.executable,'-c','print(\'{"delivered":true}\')']}},revision=0)
        self.a.control(row['id'],'retry_notification',notification_id=notice['id'])
        self.a.deliver_notifications()
        for future in list(self.engines[0].futures):future.result(timeout=3)
        notes=self.a.get(row['id'])['notifications']
        self.assertEqual(len(notes),1)
        self.assertEqual((notes[0]['status'],notes[0]['attempt']),('delivered',2))
        self.a.deliver_notifications()
        self.assertEqual(len(self.a.get(row['id'])['notifications']),1)

    def test_unstartable_agent_pauses_admission_and_retains_request_error(self):
        self.a.config('agent',agent_id='broken',agent={'name':'broken','implementation':{'kind':'agent','command':['/definitely/missing/loop-agent']}})
        row=self.a.request({'location':'local','agent_id':'broken','message':'help'})['request']
        self.cycle(lambda:self.a.get(row['id'])['state']=='failed')
        self.assertFalse(self.a.settings()['agents']['broken']['enabled'])
        self.assertIn('broken',self.a.settings()['agent_errors'])
        next_request=self.a.request({'location':'local','agent_id':'broken','message':'help again'})['request']
        self.assertEqual(next_request['state'],'unavailable')

    def test_result_fields_named_token_are_not_removed(self):
        from loop_anything.runtime.communication import clean
        value=clean({'access_token':'private','result':{'token':'business-output'},'worker_token':'private'})
        self.assertEqual(value,{'result':{'token':'business-output'}})

    def test_execution_catalog_is_usable_for_assistance_and_full_node_tools(self):
        from loop_anything.interfaces.agent_tasks import RunTools
        self.agent(self.a)
        row=self.a.request({'location':'local','agent_id':'papers','message':'catalog'})['request']
        for kind in ('assistance','node_execution'):
            with self.a.transaction() as db:
                current=self.a.get(row['id'],db);current.update(worker_token='test-worker',kind=kind,state='running');self.a.save(db,current)
            catalog=self.a.scoped_definitions(row['id'],'test-worker')['tools']
            names=[d['name'] for d in catalog]
            self.assertEqual(len(names),len(set(names)))
            self.assertIn('read_capabilities',names)
            self.assertIn('read_context',names)
            if kind=='node_execution':
                self.assertTrue({d['name'] for d in RunTools(self.a.store,'').definitions()}<=set(names))
            else:self.assertNotIn('report_task',names)

    def test_local_helper_keeps_parent_group_scope_without_using_nas_for_local_request(self):
        gid=self.groups();self.agent(self.a,'parent',groups=[gid]);self.agent(self.a,'helper')
        parent=self.a.request({'location':'group','group_id':gid,'agent_id':'parent','message':'parent'})['request']
        with self.a.transaction() as db:
            row=self.a.get(parent['id'],db);row.update(state='running',worker_token='parent-token');self.a.save(db,row)
        child=self.a.worker_call(parent['id'],'parent-token','request_assistance',{'location':'local','agent_id':'helper','message':'help'})['request']
        self.assertIsNone(child['group_id'])
        with self.a.transaction() as db:
            row=self.a.get(child['id'],db);row.update(state='running',worker_token='helper-token');self.a.save(db,row)
        directory=self.a.worker_call(child['id'],'helper-token','communication_status',{})
        self.assertIn(gid,[g['id'] for g in directory['groups']])
        remote=self.a.worker_call(child['id'],'helper-token','request_assistance',{'location':'group','agent_id':'remote-helper','message':'ask remote'})['request']
        self.assertEqual(remote['group_id'],gid)
        with self.assertRaises(Conflict):
            self.a.worker_call(child['id'],'helper-token','request_assistance',{'location':'group','group_id':'another-group','agent_id':'remote-helper','message':'wrong scope'})
        with self.a.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM communication_outbox WHERE json_extract(document,'$.request_id')=?",(child['id'],)).fetchone()[0],0)

    def test_cancel_unknown_does_not_claim_stopped_and_confirmation_releases_session(self):
        from loop_anything.runtime.native_sessions import active_native
        self.agent(self.a)
        row=self.a.request({'location':'local','agent_id':'papers','message':'unknown'})['request']
        native={'provider':'custom','id':'unknown-session'}
        session=self.engines[0].terminals.create('',row['id'],'unknown-terminal',metadata={'native_session':native})
        session.doc['state']='interrupted';session.save()
        with self.a.transaction() as db:
            current=self.a.get(row['id'],db);current.update(state='unknown',native_session=native,terminal_id=session.doc['id']);self.a.save(db,current)
        self.a.control(row['id'],'cancel')
        self.assertEqual(self.a.get(row['id'])['state'],'unknown')
        with self.assertRaises(Conflict):self.a.control(row['id'],'followup',message='resume')
        self.a.control(row['id'],'confirm_stopped',confirmed_stopped=True)
        with self.a.store.connection() as db:self.assertIsNone(active_native(db,'custom','unknown-session',self.a.store))

    def test_remote_cancel_unknown_preserves_uncertainty_until_executor_confirmation(self):
        gid=self.groups();self.agent(self.b,groups=[gid])
        row=self.a.request({'location':'group','group_id':gid,'agent_id':'papers','message':'remote unknown'})['request']
        with self.a.transaction() as db:
            current=self.a.get(row['id'],db);self.a.assign(current,self.b.settings()['instance_id'],'papers');current['state']='unknown';self.a.save(db,current)
        with self.b.transaction() as db:self.b.save(db,dict(current))
        self.a.control(row['id'],'cancel')
        with self.a.store.connection() as db:
            message=json.loads(db.execute("SELECT document FROM communication_outbox WHERE json_extract(document,'$.kind')='cancel'").fetchone()[0])
        self.b.receive(message)
        self.assertEqual(self.b.get(row['id'])['state'],'unknown')
        self.a.control(row['id'],'confirm_stopped',confirmed_stopped=True)
        with self.a.store.connection() as db:
            message=json.loads(db.execute("SELECT document FROM communication_outbox WHERE json_extract(document,'$.kind')='confirm_stopped'").fetchone()[0])
        self.b.receive(message)
        self.assertEqual(self.b.get(row['id'])['state'],'failed')

    def test_session_identity_does_not_authorize_another_agent_or_parent_scope(self):
        self.agent(self.a,'one');self.agent(self.a,'two')
        old=self.a.request({'location':'local','agent_id':'one','message':'private'})['request']
        with self.a.transaction() as db:
            row=self.a.get(old['id'],db);row.update(state='completed',native_session={'provider':'custom','id':'private-session'},parent_request='another-parent');self.a.save(db,row)
        for agent in ('one','two'):
            request=self.a.request({'location':'local','agent_id':agent,'message':'resume someone else',
                'session':{'mode':'resume','request_id':old['id'],'instance_id':self.a.settings()['instance_id'],'native_id':'private-session'}})['request']
            with self.assertRaisesRegex(Conflict,'same request source'):
                self.a.launch(request['id'])

    def test_child_mirror_never_executes_and_preserves_source_notification_receipts(self):
        self.agent(self.a)
        parent=self.a.request({'location':'local','agent_id':'papers','message':'parent'})['request']
        parent.update(executor=self.b.settings()['instance_id'],notification_route='missing')
        child=dict(parent,id='child-view',origin=parent['executor'],parent_request=parent['id'],
                   executor=self.a.settings()['instance_id'],state='assigned',revision=1)
        with self.a.transaction() as db:self.a.import_children(db,parent,[child])
        with patch.object(self.a,'prepare_resources',side_effect=AssertionError('Mirror must not launch')):
            self.a.launch(child['id'])
        self.assertFalse(self.a.read(child['id'])['request']['can_control'])
        with self.assertRaises(Conflict):self.a.control(child['id'],'cancel')
        child.update(state='failed',revision=2,error='failed on executor')
        with self.a.transaction() as db:self.a.import_children(db,parent,[child])
        self.a.deliver_notifications()
        for future in list(self.engines[0].futures):future.result(timeout=3)
        receipt=self.a.get(child['id'])['notifications'][0]
        self.assertEqual(receipt['status'],'waiting_configuration')
        child.update(revision=3)
        with self.a.transaction() as db:self.a.import_children(db,parent,[child])
        self.a.deliver_notifications()
        self.assertEqual(self.a.get(child['id'])['notifications'],[receipt])
        self.a.control(child['id'],'retry_notification',notification_id=receipt['id'])
        # A returned mirror must not overwrite a request for which this machine is authoritative.
        with self.a.transaction() as db:
            real=self.a.get(child['id'],db);real.pop('mirror');real['result']={'authoritative':True};self.a.save(db,real)
            self.a.import_children(db,parent,[dict(child,revision=999,result={'forged':True})])
        self.assertEqual(self.a.get(child['id'])['result'],{'authoritative':True})

    def test_native_session_reservations_cover_communication_and_regular_terminals(self):
        from loop_anything.runtime.native_sessions import active_native
        self.agent(self.a)
        request=self.a.request({'location':'local','agent_id':'papers','message':'session'})['request']
        native={'provider':'custom','id':'session-1'}
        with self.a.transaction() as db:
            row=self.a.get(request['id'],db);row.update(state='starting',native_session=native);self.a.save(db,row)
            self.assertEqual(active_native(db,'custom','session-1',self.a.store)['communication_id'],row['id'])
            row['mirror']=True;self.a.save(db,row)
            self.assertIsNone(active_native(db,'custom','session-1',self.a.store))
        session=self.engines[0].terminals.create('', 'regular-execution','regular-terminal',metadata={'native_session':native})
        with self.a.store.connection() as db:
            self.assertEqual(active_native(db,'custom','session-1',self.a.store)['id'],session.doc['id'])

    def test_remote_node_can_release_session_while_local_child_finishes(self):
        self.remote_wait(False)

    def test_third_machine_helper_reads_source_context_after_parent_exit(self):
        self.remote_wait(True)

    def remote_wait(self, remote_child):
        import test_timeline_runtime as fixture
        base=fixture.RuntimeTests();base.setUp()
        try:
            gid=self.groups();self.agent(self.b,'research',groups=[gid]);self.agent(self.c if remote_child else self.b,'helper',groups=[gid] if remote_child else [])
            config=self.b.settings()['agents']['research']['implementation']
            self.b.config('agent',agent_id='research',agent={'implementation':dict(config,resume_command=[sys.executable,'-c','pass','{{session_id}}','{{prompt}}'])})
            base.implementations['init']={'kind':'agent','dispatch':{'location':'group','agent_id':'research'}}
            key=self.a.store.publish(base.bp,base.implementations)['key'];self.a.config('bind_loop',loop_key=key,group_id=gid)
            runid=self.a.store.create(key,'remote wait')['id']
            def worker(command,prompt,*args,**kw):
                c=json.loads(prompt.split('\n',1)[1])
                if c['kind']=='assistance':
                    time.sleep(.6)
                    helper=self.c if remote_child else self.b
                    reply=helper.worker_call(c['request_id'],c['token'],'read_context',{})
                    until=time.monotonic()+6
                    while reply['call']['state'] not in ('completed','failed') and time.monotonic()<until:
                        time.sleep(.01);reply=helper.worker_call(c['request_id'],c['token'],'source_result',{'id':reply['call']['id']})
                    self.assertEqual(reply['call']['state'],'completed',reply)
                    self.assertEqual(reply['call']['result']['context']['run']['id'],runid)
                    return self.worker(command,prompt,*args,**kw)
                self.b.worker_call(c['request_id'],c['token'],'native_session',{'provider':'custom','id':'remote-wait-session'})
                child=self.b.worker_call(c['request_id'],c['token'],'request_assistance',{'location':'group' if remote_child else 'local','group_id':gid,'agent_id':'helper','message':'查论文'})['request']
                for tool,arguments in [('wait_assistance',{'task_id':'init','request_ids':[child['id']],'seconds':10}),('finish',{})]:
                    ident=self.b.worker_call(c['request_id'],c['token'],'source_call',{'tool':tool,'arguments':arguments})['call']['id']
                    until=time.monotonic()+6
                    while time.monotonic()<until:
                        call=self.b.get(c['request_id'])['rpc'][ident]
                        if call['state']=='failed':raise AssertionError(call['error'])
                        if call['state']=='completed':break
                        time.sleep(.01)
                    else:raise AssertionError('source call did not finish')
                self.b.worker_call(c['request_id'],c['token'],'complete',{'result':{}})
                return subprocess.CompletedProcess(command,0,'','')
            with patch('loop_anything.runtime.host_runtime.run_command',side_effect=worker):
                self.engines[0].tick(runid)
                self.cycle(lambda:self.a.store.get(runid)['tasks']['init']['status']=='ready',timeout=12)
            run=self.a.store.get(runid)
            self.assertEqual(len(run['tasks']),1)
            self.assertEqual(run['records'],{})
            self.assertEqual(run['tasks']['init']['assistance_results'][0]['result']['papers'],['one'])
            self.assertEqual(self.b.store.list(),[])
            child=next(r for r in self.a.requests() if r.get('mirror'))
            self.assertEqual(child['notification_origin'],self.a.settings()['instance_id'])
            self.assertTrue(child.get('notifications'))
            self.assertFalse(self.b.get(child['id']).get('notifications'))
            if remote_child:self.assertFalse(self.c.get(child['id']).get('notifications'))
        finally:base.tearDown()


if __name__=='__main__':unittest.main()
