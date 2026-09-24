"""Transition contract through real task ownership/transactions; no business-specific rules."""
import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import test_timeline_runtime as fixture
from test_timeline_runtime import task_spec, node
from loop_anything.interfaces.agent_tasks import RunTools, change_task_in_run
from loop_anything.runtime.lifecycle import template, validate, materialize
from loop_anything.runtime.model import Conflict, Invalid


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.RuntimeTests()
        self.base.setUp()
        self.store, self.engine = self.base.store, self.base.engine

    def tearDown(self):
        self.base.tearDown()

    def settle(self):
        for future in list(self.engine.futures):
            future.result(timeout=5)

    def call(self, context, event, report_id, **fields):
        return RunTools(self.store, self.base.id, context['token']).call('report_task',
            dict(task_id=context['task_id'], execution_id=context['execution_id'], event=event, report_id=report_id, **fields))

    def external(self, handler):
        self.base.implementations['produce'] = {'kind': 'external', 'command': ['submit'], 'observe': ['check']}
        with patch('loop_anything.runtime.timeline_runtime.run_command', side_effect=handler):
            self.base.initialize([task_spec('job', 'produce', {'source': {'record': 'a'}}, {'text': 'out'})])
            self.settle()
        return next(e for e in self.base.read()['executions'] if e['task_id'] == 'job')

    def test_agent_reports_are_atomic_idempotent_and_do_not_release_scope(self):
        e = self.base.start()
        tools = RunTools(self.store, self.base.id, e['token'])
        info = tools.call('read_task', {'task_id': 'init'})
        args = dict(task_id='init', task_version=info['task_version'], event='completed', report_id='final',
                    envelope={'outputs': {'a': 'A', 'b': 'B'}, 'settings': {'objective': 'Test reporting'}})
        bad = dict(args, envelope={'outputs': {'a': 'A'}})
        with self.assertRaises(Invalid):
            tools.call('report_task', bad)
        self.assertFalse(self.base.read()['records'])
        result = tools.call('report_task', args)
        self.assertTrue(result['accepted'])
        self.assertTrue(tools.call('report_task', args)['duplicate'])
        self.assertEqual(len(self.base.read()['records']['a']), 1)
        self.assertTrue(self.base.read()['agent_sessions'])
        with self.assertRaises(Conflict):
            tools.call('report_task', dict(args, event='progress'))
        tools.call('finish', {})
        self.assertFalse(self.base.read()['agent_sessions'])
        with self.assertRaises(Conflict):
            tools.call('report_task', args)

    def test_concurrent_duplicate_reports_commit_once_and_self_loops_remain_legal(self):
        from concurrent.futures import ThreadPoolExecutor
        e=self.base.start();tools=RunTools(self.store,self.base.id,e['token'])
        info=tools.call('read_task',{'task_id':'init'})
        progress={'task_id':'init','task_version':info['task_version'],'report_id':'progress-1','event':'progress'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:tools.call('report_task',progress),range(2)))
        self.assertEqual(sum(r.get('duplicate',False) for r in results),1)
        tools.call('report_task',dict(progress,report_id='progress-2'))
        run=self.base.read()
        self.assertEqual(len([h for h in run['history'] if h['kind']=='transition' and h['detail']['event']=='progress']),2)
        tools.call('change_settings',{'revision':run['settings']['revision'],'change':{'hooks':[
            {'id':'notify','action':'notify','phase':'after','target':{'tasks':'init'},'route':'workspace','frequency':'always'}]}})
        info=tools.call('read_task',{'task_id':'init'})
        completed=dict(progress,event='completed',report_id='final',task_version=info['task_version'],
            envelope={'outputs':{'a':'A','b':'B'},'settings':{'objective':'One commit'}})
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _:tools.call('report_task',completed),range(2)))
        run=self.base.read()
        self.assertEqual(len(run['records']['a']),1)
        self.assertEqual(len(run['notifications']),1)
        self.assertEqual(run['tasks']['init']['status'],'completed')

    def test_direct_script_result_survives_exit_error_and_rejects_late_report(self):
        captured = {}
        self.base.implementations['produce'] = {'kind': 'command', 'command': ['script']}
        def handler(command, request, *args, **kw):
            context = json.loads(request);captured.update(context)
            self.call(context, 'completed', 'final', envelope={'outputs': {'text': 'done'}})
            return subprocess.CompletedProcess(command, 1, 'ordinary logs', 'cleanup failed')
        with patch('loop_anything.runtime.timeline_runtime.run_command', side_effect=handler):
            self.base.initialize([task_spec('job', 'produce', {'source': {'record': 'a'}}, {'text': 'out'})])
            self.settle()
        run = self.base.read()
        self.assertEqual(run['tasks']['job']['status'], 'completed')
        self.assertEqual(run['records']['out'][0]['value'], 'done')
        self.assertTrue(any(h['kind']=='process_error' and h['detail']['result_preserved'] for h in run['history']))
        with self.assertRaises(Conflict):
            self.call(captured, 'progress', 'late', detail={'percent': 10})

    def test_monitor_failure_keeps_external_identity_and_retry_only_checks(self):
        calls = []
        def handler(command, request, *args, **kw):
            context = json.loads(request);calls.append(command[0])
            if command[0] == 'submit':
                self.call(context, 'submitted', 'submit', external_id='remote-42', poll_after=.1)
            elif len(calls) == 2:
                raise Invalid('Network unavailable')
            else:
                self.assertEqual(context['external_id'], 'remote-42')
                self.call(context, 'completed', 'result', envelope={'outputs': {'text': 'done'}})
            return subprocess.CompletedProcess(command, 0, 'ordinary logs', '')
        attempt = self.external(handler)
        # Upgrade an already submitted job from the previous on-disk execution format.
        for malformed in (None, [], 'not-an-envelope'):
            with self.assertRaises(Invalid):
                self.engine.timeline_runtime.submit(self.base.id, attempt['id'], attempt['token'], malformed)
        with self.store.edit(self.base.id) as run:
            e = next(e for e in run['executions'] if e['id'] == attempt['id'])
            e.pop('lifecycle_state')
            e['implementation'].pop('lifecycle')
            self.engine.timeline_runtime.recover(run)
            self.assertEqual(e['lifecycle_state'], 'waiting')
            self.assertEqual(e['implementation']['lifecycle'], template('external'))
        time.sleep(.12)
        with patch('loop_anything.runtime.timeline_runtime.run_command', side_effect=handler):
            self.engine.tick(self.base.id);self.settle()
        run = self.base.read();e = next(e for e in run['executions'] if e['id']==attempt['id'])
        self.assertEqual(e['lifecycle_state'], 'waiting')
        self.assertEqual(run['tasks']['job']['status'], 'waiting')
        self.assertIn('Network unavailable', e['observation_error'])
        self.assertEqual(RunTools(self.store,self.base.id).call('next_tasks',{})['state'], 'unexpected')
        old_token = e['token']
        with self.store.edit(self.base.id) as run:
            change_task_in_run(run, {'task_id': 'job', 'operation': 'retry', 'reason': 'Connection restored'})
        stale = RunTools(self.store,self.base.id,old_token).call('report_task',dict(task_id='job',execution_id=e['id'],event='progress',report_id='stale'))
        self.assertTrue(stale['stale']);self.assertFalse(stale['accepted'])
        self.assertEqual(self.base.read()['tasks']['job']['status'], 'waiting')
        with patch('loop_anything.runtime.timeline_runtime.run_command', side_effect=handler):
            self.engine.tick(self.base.id);self.settle()
        self.assertEqual(calls, ['submit', 'check', 'check'])
        self.assertEqual(self.base.read()['records']['out'][0]['value'], 'done')
        self.assertEqual(len([e for e in self.base.read()['executions'] if e['task_id']=='job']), 1)
        self.assertEqual(self.base.read()['tasks']['job']['revision'],1)
        self.assertEqual(next(e for e in self.base.read()['executions'] if e['task_id']=='job')['task_revision'],1)

    def test_monitor_terminal_reports_are_evidence_only_and_never_launch_again(self):
        from loop_anything.runtime.lifecycle import revoke_execution_token
        captured = {}
        def submit(command, request, *args, **kwargs):
            captured.update(json.loads(request))
            return subprocess.CompletedProcess(command, 0, json.dumps({'status':'waiting','external_id':'remote-1','poll_after':100}), '')
        attempt = self.external(submit)
        for state in ('agent', 'fault', 'completed', 'retry'):
            with self.subTest(state=state):
                with self.store.edit(self.base.id) as run:
                    e = next(e for e in run['executions'] if e['id'] == attempt['id'])
                    e.update(status='completed' if state=='completed' else 'fault', lifecycle_state=state)
                    run['tasks']['job']['status'] = 'completed' if state=='completed' else 'fault'
                    snapshot = json.loads(json.dumps(run))
                args = dict(event='progress', report_id='late-'+state, detail={'percent':99})
                result = self.call(captured, **args)
                self.assertTrue(result['stale']);self.assertFalse(result['accepted'])
                self.assertTrue(self.call(captured, **args)['duplicate'])
                self.assertEqual(self.base.read()['tasks'], snapshot['tasks'])
                self.assertEqual(self.base.read()['agent_failures'], snapshot['agent_failures'])
                with patch('loop_anything.runtime.timeline_runtime.run_command') as command:
                    self.engine.timeline_runtime.execute(self.base.id, attempt, snapshot, True)
                    command.assert_not_called()
        with self.store.edit(self.base.id) as run:
            e = next(e for e in run['executions'] if e['id'] == attempt['id']);revoke_execution_token(e)
            run['tasks']['job'].update(status='planned',execution_id=None)
        self.assertTrue(self.call(captured,'completed','old-attempt',envelope={'outputs':{'text':'must not commit'}})['stale'])
        self.assertNotIn('out',self.base.read()['records'])
        with self.assertRaises(Conflict):
            self.call(dict(captured,token='wrong'), 'progress', 'wrong')
        with self.assertRaises(Conflict):
            RunTools(self.store,self.base.id,captured['token']).call('change_settings',{'revision':1,'change':{'objective':'forbidden'}})

    def test_monitor_handoff_stops_polling_and_resumes_prior_state(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        self.base.bp['nodes']['recover']=node();self.base.bp['fallback_node']='recover'
        self.base.implementations['recover']={'kind':'agent'}
        matrix=template('external');next(r for r in matrix['transitions'] if r['event']=='check_error')['to']='agent';validate(matrix)
        for target in ('fault','retry','completed'):
            bad=json.loads(json.dumps(matrix));next(r for r in bad['transitions'] if r['event']=='check_error')['to']=target
            with self.assertRaises(Invalid):validate(bad)
        self.base.implementations['produce']={'kind':'external','command':['submit'],'observe':['check'],'lifecycle':matrix}
        def submit(command,request,*args,**kwargs):return subprocess.CompletedProcess(command,0,json.dumps({'status':'waiting','external_id':'remote-1','poll_after':100}), '')
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=submit):
            self.base.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})]);self.settle()
        original=self.base.read();attempt=next(e for e in original['executions'] if e['task_id']=='job')
        entered,release=threading.Event(),threading.Event();captured={}
        def monitor(command,request,*args,**kwargs):
            captured.update(json.loads(request));entered.set();release.wait(3)
            return subprocess.CompletedProcess(command,1,'','late network failure')
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=monitor),ThreadPoolExecutor() as pool:
            future=pool.submit(self.engine.timeline_runtime.execute,self.base.id,attempt,original,True)
            self.assertTrue(entered.wait(2))
            self.assertTrue(self.call(captured,'check_error','handoff',detail={'message':'observer unhealthy'})['accepted'])
            release.set();future.result(timeout=5)
        run=self.base.read();e=next(e for e in run['executions'] if e['task_id']=='job')
        self.assertEqual(e['lifecycle_state'],'agent');self.assertEqual(e['external_id'],'remote-1')
        self.assertFalse(any(h['kind']=='process_error' and h.get('execution')==e['id'] for h in run['history']))
        self.assertTrue(any(h['kind']=='stale_monitor_report' for h in run['history']))
        for owner in run['agent_sessions']:RunTools(self.store,self.base.id,owner['token']).call('finish',{})
        for _ in range(3):self.engine.tick(self.base.id)
        run=self.base.read();self.assertEqual(len([e for e in run['executions'] if e['node']=='recover']),1)
        with self.store.edit(self.base.id) as run:
            change_task_in_run(run,{'task_id':'job','operation':'retry','reason':'Connection restored'})
        run=self.base.read();e=next(e for e in run['executions'] if e['task_id']=='job')
        self.assertEqual((e['lifecycle_state'],e['status'],e['external_id']),('waiting','waiting','remote-1'))
        self.assertTrue(self.call(captured,'progress','retired-checker')['stale'])
        self.assertEqual(len([e for e in run['executions'] if e['task_id']=='job']),1)

    def test_agent_missing_cwd_is_classified_as_start_configuration_error(self):
        self.base.implementations['produce']={'kind':'agent','command':[sys.executable,'-c','pass'],'cwd':str(self.store.filename)+'.missing'}
        self.base.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
        run=self.base.read();owner=run['agent_sessions'][0];RunTools(self.store,self.base.id,owner['token']).call('finish',{})
        self.engine.tick(self.base.id);self.settle()
        run=self.base.read();attempt=next(e for e in run['executions'] if e['task_id']=='job')
        self.assertEqual(attempt['failure_kind'],'command_start')
        self.assertTrue(any(h['kind']=='command_start' and h.get('execution')==attempt['id'] for h in run['history']))

    def test_custom_matrix_uncovered_event_enters_only_configured_fallback(self):
        self.base.bp['nodes']['recover'] = node()
        self.base.bp['fallback_node'] = 'recover'
        self.base.implementations['recover'] = {'kind': 'agent'}
        matrix = {'initial': 'loading', 'transitions': [
            {'from': 'loading', 'event': 'loaded', 'to': 'processing'},
            {'from': 'processing', 'event': 'completed', 'to': 'completed'}]}
        validate(matrix)
        self.base.implementations['produce'] = {'kind': 'command', 'command': ['script'], 'lifecycle': matrix}
        def handler(command, request, *args, **kw):
            context=json.loads(request)
            self.assertTrue(self.call(context,'loaded','1')['accepted'])
            self.assertFalse(self.call(context,'unknown','2')['accepted'])
            return subprocess.CompletedProcess(command,0,'','')
        with patch('loop_anything.runtime.timeline_runtime.run_command', side_effect=handler):
            self.base.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})]);self.settle()
        self.engine.tick(self.base.id)
        run=self.base.read()
        self.assertEqual(run['tasks']['job']['status'],'fault')
        self.assertTrue(any(t['origin'].get('fallback') for t in run['tasks'].values()))
        event=next(h for h in run['history'] if h['kind']=='transition' and h['detail']['event']=='unknown')
        self.assertEqual((event['detail']['from'],event['detail']['to']),('processing','processing'))
        self.assertFalse(event['detail']['accepted'])

    def test_report_client_uses_execution_token_over_real_http(self):
        import os
        import socket
        import sys
        from pathlib import Path
        script = Path(self.base.tmp.name) / 'handler.py'
        script.write_text("""import json,sys,importlib.util
context=json.load(sys.stdin)
spec=importlib.util.spec_from_file_location('reporter',context['report_client'])
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
client.notify(context,context['task_id']+':started','Starting',route='workspace')
client.report(context,'completed',report_id='init',envelope={'settings':{'objective':'HTTP report'},'outputs':{'a':'A','b':'B'},'tasks':[{'id':'job','node':'produce','inputs':{'source':{'record':'a'}},'outputs':{'text':{'id':'out'}}}]})
print('ordinary script logs')
""")
        monitor = Path(self.base.tmp.name) / 'monitor.py'
        monitor.write_text('''import json,sys,importlib.util
context=json.load(sys.stdin)
spec=importlib.util.spec_from_file_location('reporter',context['report_client'])
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
client.report(context,'completed',report_id='done',envelope={'outputs':{'text':'done'}})
assert client.report(context,'progress',report_id='late')['stale']
''')
        self.base.implementations['produce']={'kind':'external','command':[sys.executable,'-c','print(\'{"status":"waiting","external_id":"remote-http","poll_after":0.02}\')'],'observe':[sys.executable,str(monitor)]}
        self.base.implementations['init']={'kind':'command','command':[sys.executable,str(script)]}
        key=self.store.publish(self.base.bp,self.base.implementations)['key']
        ident=self.store.create(key,'HTTP')['id']
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with open(Path(self.base.tmp.name)/'server.log','w+') as log:
            server=subprocess.Popen([sys.executable,'-m','loop_anything','--db',str(self.store.filename),'serve','--port',str(port),'--allow-sleep'],
                env=dict(os.environ,LOOP_ANYTHING_EDIT_PASSWORD='test-password'),stdout=log,stderr=log)
            try:
                for _ in range(100):
                    run=self.store.get(ident)
                    if run['tasks'].get('job',{}).get('status') in ('completed','fault'):break
                    time.sleep(.05)
                self.assertEqual(run['tasks']['init']['status'],'completed',run['history'])
                self.assertEqual(run['records']['a'][0]['value'],'A')
                self.assertEqual(run['tasks']['job']['status'],'completed',run['history'])
                self.assertEqual(run['records']['out'][0]['value'],'done')
                from loop_anything.runtime.lifecycle import revoke_execution_token
                from urllib.request import Request, urlopen
                from urllib.error import HTTPError
                attempt=next(e for e in run['executions'] if e['task_id']=='job')
                with self.store.edit(ident) as saved:
                    revoke_execution_token(next(e for e in saved['executions'] if e['id']==attempt['id']))
                body={'tool':'report_task','arguments':{'run_id':ident,'task_id':'job','execution_id':attempt['id'],'token':attempt['token'],'event':'progress','report_id':'revoked-late'}}
                def post():return urlopen(Request('http://127.0.0.1:'+str(port)+'/api/tools',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'}))
                with post() as response:self.assertTrue(json.load(response)['stale'])
                body['arguments']['token']='wrong'
                with self.assertRaises(HTTPError) as rejected:post()
                self.assertEqual(rejected.exception.code,403)

                self.assertTrue(any(h['kind']=='transition' and h['detail']['event']=='completed' for h in run['history']))
            finally:
                server.terminate();server.wait(timeout=10)

    def retry_matrix(self, kind, event='failed', parameters=None):
        matrix=template(kind);state='waiting' if kind=='external' else 'executing'
        matrix['transitions']=[r for r in matrix['transitions'] if (r['from'],r['event'])!=(state,event)]
        matrix['transitions'] += [
            {'from':state,'event':event,'when':{'op':'le','args':[{'path':'attempt'},2]},'to':'retry',**({'parameters':parameters} if parameters is not None else {})},
            {'from':state,'event':event,'when':{'op':'ge','args':[{'path':'attempt'},3]},'to':'agent'}]
        return matrix

    def advance(self, predicate):
        for _ in range(100):
            self.engine.tick(self.base.id);self.settle();run=self.base.read()
            if predicate(run):return run
            time.sleep(.01)
        self.fail(str(run['history'][-8:]))

    def test_real_command_retries_same_task_once_per_report_across_restart(self):
        from loop_anything.runtime.engine import Engine
        matrix=self.retry_matrix('command')
        matrix['transitions'][-2]['when']={'op':'eq','args':[{'path':'attempt'},1]}
        matrix['transitions'].append({'from':'executing','event':'failed','to':'retry',
            'when':{'op':'eq','args':[{'path':'attempt'},2]},'parameters':{'batch':8}})
        script="import json,sys;c=json.load(sys.stdin);print(json.dumps({'event':'failed','report_id':'failed','detail':{'message':'retryable'}} if c['attempt']<3 else {'outputs':{'text':str(c['parameters'])}}))"
        self.base.implementations['produce']={'kind':'command','command':[sys.executable,'-c',script],'lifecycle':matrix}
        self.base.initialize([task_spec('work','produce',{'source':{'record':'a'}},{'text':'out'},parameters={'batch':16,'keep':42}),
            task_spec('downstream','join',{'a':{'record':'out'},'b':{'record':'b'}},{'ok':'done'},after=['work'])]);self.settle()
        run=self.base.read();first=next(e for e in run['executions'] if e['task_id']=='work')
        downstream=run['tasks']['downstream']['spec']
        tools=RunTools(self.store,self.base.id,first['token'])
        replay=tools.call('report_task',{'task_id':'work','execution_id':first['id'],'event':'failed','report_id':'failed','detail':{'message':'retryable'}})
        self.assertTrue(replay['duplicate']);self.assertEqual(run['tasks']['work']['status'],'retrying')
        self.engine.close();self.base.engine=self.engine=Engine(self.store)
        self.engine.recover();self.engine.recover()
        run=self.advance(lambda r:r['tasks']['work']['status']=='completed')
        attempts=[e for e in run['executions'] if e['task_id']=='work']
        self.assertEqual([(e['attempt'],e['task_revision']) for e in attempts],[(1,1),(2,1),(3,2)])
        self.assertEqual(attempts[-1]['parameters'],{'batch':8,'keep':42})
        self.assertEqual(run['tasks']['downstream']['spec'],downstream)
        self.assertEqual(set(run['tasks']),{'init','work','downstream'})
        self.assertEqual(len([h for h in run['history'] if h['kind']=='retry_applied']),2)
        self.engine.recover();self.engine.tick(self.base.id)
        self.assertEqual(len([e for e in self.base.read()['executions'] if e['task_id']=='work']),3)

    def test_external_failures_retry_then_agent_repairs_original_task(self):
        self.base.bp['nodes']['recover']=node();self.base.bp['fallback_node']='recover';self.base.implementations['recover']={'kind':'agent'}
        submit="import json,sys;c=json.load(sys.stdin);print(json.dumps({'status':'waiting','external_id':'job-'+str(c['attempt']),'poll_after':.001}))"
        observe="import json,sys;c=json.load(sys.stdin);print(json.dumps({'event':'failed','report_id':'failed'} if not c['parameters'].get('fixed') else {'outputs':{'text':'repaired'}}))"
        self.base.implementations['produce']={'kind':'external','command':[sys.executable,'-c',submit],'observe':[sys.executable,'-c',observe],'lifecycle':self.retry_matrix('external')}
        self.base.initialize([task_spec('work','produce',{'source':{'record':'a'}},{'text':'out'})])
        run=self.advance(lambda r:any(e['node']=='recover' for e in r['executions']))
        attempts=[e for e in run['executions'] if e['task_id']=='work']
        self.assertEqual([e['external_id'] for e in attempts],['job-1','job-2','job-3'])
        self.assertEqual(attempts[-1]['lifecycle_state'],'agent')
        fallback=next(e for e in run['executions'] if e['node']=='recover');tools=RunTools(self.store,self.base.id,fallback['token'])
        tools.call('change_task',{'task_id':'work','operation':'retry','parameters':{'fixed':True},'reason':'Repair original task'})
        info=tools.call('read_task',{'task_id':fallback['task_id']})
        tools.call('complete_task',{'task_id':fallback['task_id'],'task_version':info['task_version'],'envelope':{'outputs':{}}});tools.call('finish',{})
        run=self.advance(lambda r:r['tasks']['work']['status']=='completed')
        self.assertEqual(run['tasks']['work']['revision'],2)
        self.assertEqual(len([t for t in run['tasks'].values() if t['spec']['node']=='produce']),1)
        self.assertEqual(run['records']['out'][0]['value'],'repaired')

    def test_overlapping_conditions_and_bad_retry_parameters_are_visible_failures(self):
        for bad_parameters in (False,True):
            with self.subTest(bad_parameters=bad_parameters):
                matrix=self.retry_matrix('external',parameters={'batch':0} if bad_parameters else None)
                if not bad_parameters:matrix['transitions'][-1]['when']={'op':'ge','args':[{'path':'attempt'},1]}
                validate(matrix)
                self.base.implementations['produce']={'kind':'external','command':['submit'],'observe':['observe'],'lifecycle':matrix,
                    'parameter_schema':{'type':'object','properties':{'batch':{'type':'integer','minimum':1}}}}
                self.base.bp['version']=str(bad_parameters)
                with patch('loop_anything.runtime.timeline_runtime.run_command',return_value=subprocess.CompletedProcess([],0,json.dumps({'status':'waiting','external_id':'job','poll_after':10}),'')):
                    self.base.initialize([task_spec('work','produce',{'source':{'record':'a'}},{'text':'out'},parameters={'batch':16})]);self.settle()
                run=self.base.read();e=next(e for e in run['executions'] if e['task_id']=='work')
                result=RunTools(self.store,self.base.id,e['token']).call('report_task',{'task_id':'work','execution_id':e['id'],'event':'failed','report_id':'failed'})
                self.assertFalse(result['accepted']);self.assertIn('Invalid retry parameters' if bad_parameters else 'Ambiguous',result['issue'])
                run=self.base.read();self.assertEqual(run['tasks']['work']['spec']['parameters'],{'batch':16});self.assertEqual(run['tasks']['work']['revision'],1)
                self.assertNotIn('retry',next(x for x in run['executions'] if x['id']==e['id']))

    def test_pending_retry_waits_for_scope_and_unconfirmed_exit_blocks_restart(self):
        matrix=self.retry_matrix('command')
        self.base.implementations['produce']={'kind':'command','command':['work'],'lifecycle':matrix}
        with patch('loop_anything.runtime.timeline_runtime.run_command',return_value=subprocess.CompletedProcess([],0,json.dumps({'event':'failed','report_id':'failed'}),'')):
            self.base.initialize([task_spec('work','produce',{'source':{'record':'a'}},{'text':'out'})]);self.settle()
        from loop_anything.interfaces.agent_tasks import acquire
        owner=acquire(self.store,self.base.id)
        self.engine.tick(self.base.id);self.assertEqual(self.base.read()['tasks']['work']['attempts'],1)
        RunTools(self.store,self.base.id,owner['token']).call('finish',{})
        # Simulate restart with an invocation that had not durably confirmed exit.
        with self.store.edit(self.base.id) as run:
            e=next(e for e in run['executions'] if e['task_id']=='work');e['worker_active']=True
        self.engine.recover();self.engine.tick(self.base.id)
        run=self.base.read();e=next(e for e in run['executions'] if e['task_id']=='work')
        self.assertEqual(e['retry']['status'],'blocked');self.assertEqual(run['tasks']['work']['attempts'],1)
        self.assertIn('verify stopped',e['retry']['error'])

    def test_pending_fallback_retry_does_not_create_another_fallback_task(self):
        self.base.bp['nodes']['recover']=node();self.base.bp['fallback_node']='recover'
        matrix=template('agent')
        next(r for r in matrix['transitions'] if r['event']=='failed')['to']='retry'
        self.base.implementations['recover']={'kind':'agent','lifecycle':matrix}
        self.base.implementations['produce']={'kind':'command','command':[sys.executable,'-c','raise SystemExit(1)']}
        self.base.initialize([task_spec('work','produce',{'source':{'record':'a'}},{'text':'out'})])
        run=self.advance(lambda r:any(e['node']=='recover' for e in r['executions']))
        fallback=next(e for e in run['executions'] if e['node']=='recover')
        tools=RunTools(self.store,self.base.id,fallback['token'])
        info=tools.call('read_task',{'task_id':fallback['task_id']})
        tools.call('report_task',{'task_id':fallback['task_id'],'task_version':info['task_version'],'event':'failed','report_id':'retry'})
        for _ in range(3):self.engine.tick(self.base.id)
        run=self.base.read()
        self.assertEqual(run['tasks'][fallback['task_id']]['status'],'retrying')
        self.assertEqual([t['id'] for t in run['tasks'].values() if t['origin'].get('fallback')],[fallback['task_id']])

    def test_agent_process_retry_does_not_bypass_three_failure_pause(self):
        matrix=template('agent')
        next(r for r in matrix['transitions'] if r['event']=='process_error')['to']='retry'
        self.base.implementations['produce']={'kind':'agent','command':[sys.executable,'-c','raise SystemExit(1)'],'lifecycle':matrix}
        self.base.initialize([task_spec('work','produce',{'source':{'record':'a'}},{'text':'out'})])
        owner=self.base.read()['agent_sessions'][0]
        RunTools(self.store,self.base.id,owner['token']).call('finish',{})
        run=self.advance(lambda r:r['status']=='paused')
        self.assertEqual(run['tasks']['work']['attempts'],3)
        self.engine.tick(self.base.id);self.assertEqual(self.base.read()['tasks']['work']['attempts'],3)

    def test_finish_does_not_allow_retry_when_the_process_cannot_be_stopped(self):
        from loop_anything.runtime.host_runtime import CommandNotStopped
        matrix=template('agent')
        for row in matrix['transitions']:
            if row['event'] in ('failed','process_error'):row['to']='retry'
        self.base.implementations['produce']={'kind':'agent','command':['agent'],'lifecycle':matrix}
        ids=('with_finish','without_finish')
        self.base.initialize([task_spec(id,'produce',{'source':{'record':'a'}},{'text':id}) for id in ids])
        owner=self.base.read()['agent_sessions'][0];RunTools(self.store,self.base.id,owner['token']).call('finish',{})
        def handler(command,request,*args,**kwargs):
            context=json.loads(request.split('Run context:\n',1)[1]);tools=RunTools(self.store,self.base.id,context['token'])
            if context['task_id']=='with_finish':
                info=tools.call('read_task',{'task_id':context['task_id']})
                tools.call('report_task',{'task_id':context['task_id'],'task_version':info['task_version'],'event':'failed','report_id':'failed'})
                tools.call('finish',{})
            raise CommandNotStopped('Test: process still exists')
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=handler):
            self.engine.tick(self.base.id);self.settle()
        self.engine.tick(self.base.id);run=self.base.read()
        for id in ids:
            e=next(e for e in run['executions'] if e['task_id']==id)
            self.assertEqual(e['retry']['status'],'blocked');self.assertEqual(run['tasks'][id]['attempts'],1)

    def test_agent_can_release_its_scope_after_explicit_handoff(self):
        self.base.bp['nodes']['recover']=node();self.base.bp['fallback_node']='recover';self.base.implementations['recover']={'kind':'agent'}
        matrix=template('agent');next(r for r in matrix['transitions'] if r['event']=='failed')['to']='agent'
        self.base.implementations['produce']={'kind':'agent','lifecycle':matrix}
        self.base.initialize([task_spec('work','produce',{'source':{'record':'a'}},{'text':'out'})])
        owner=self.base.read()['agent_sessions'][0];RunTools(self.store,self.base.id,owner['token']).call('finish',{})
        self.engine.tick(self.base.id);run=self.base.read();e=next(e for e in run['executions'] if e['task_id']=='work')
        tools=RunTools(self.store,self.base.id,e['token']);info=tools.call('read_task',{'task_id':'work'})
        tools.call('report_task',{'task_id':'work','task_version':info['task_version'],'event':'failed','report_id':'handoff'})
        self.assertTrue(tools.call('finish',{})['finished'])
        run=self.advance(lambda r:any(e['node']=='recover' for e in r['executions']))
        self.assertEqual(run['tasks']['work']['status'],'fault')
        self.assertEqual(len([t for t in run['tasks'].values() if t['spec']['node']=='produce']),1)

    def test_matrix_cannot_bypass_completion_or_define_ambiguous_transition(self):
        incomplete = {'a': None, 'b': {'options': None}, 'c': {'options': {'draft': None}}}
        self.assertEqual(materialize(incomplete), incomplete)
        value=template('command')
        value['transitions'].append({'from':'executing','event':'done','to':'completed'})
        with self.assertRaises(Invalid):validate(value)
        value=template('external');value['transitions'].append(value['transitions'][0])
        with self.assertRaises(Invalid):validate(value)

if __name__=='__main__':unittest.main()
