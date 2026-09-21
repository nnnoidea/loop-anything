"""Transition contract through real task ownership/transactions; no business-specific rules."""
import json
import subprocess
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
        with self.assertRaises(Conflict):
            RunTools(self.store,self.base.id,old_token).call('report_task',dict(task_id='job',execution_id=e['id'],event='progress',report_id='stale'))
        with patch('loop_anything.runtime.timeline_runtime.run_command', side_effect=handler):
            self.engine.tick(self.base.id);self.settle()
        self.assertEqual(calls, ['submit', 'check', 'check'])
        self.assertEqual(self.base.read()['records']['out'][0]['value'], 'done')
        self.assertEqual(len([e for e in self.base.read()['executions'] if e['task_id']=='job']), 1)

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
client.report(context,'completed',report_id='init',envelope={'settings':{'objective':'HTTP report'},'outputs':{'a':'A','b':'B'}})
print('ordinary script logs')
""")
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
                    if run['tasks']['init']['status'] in ('completed','fault'):break
                    time.sleep(.05)
                self.assertEqual(run['tasks']['init']['status'],'completed',run['history'])
                self.assertEqual(run['records']['a'][0]['value'],'A')
                self.assertTrue(any(h['kind']=='transition' and h['detail']['event']=='completed' for h in run['history']))
            finally:
                server.terminate();server.wait(timeout=10)

    def test_matrix_cannot_bypass_completion_or_define_ambiguous_transition(self):
        incomplete = {'a': None, 'b': {'options': None}, 'c': {'options': {'draft': None}}}
        self.assertEqual(materialize(incomplete), incomplete)
        value=template('command')
        value['transitions'].append({'from':'executing','event':'done','to':'completed'})
        with self.assertRaises(Invalid):validate(value)
        value=template('external');value['transitions'].append(value['transitions'][0])
        with self.assertRaises(Invalid):validate(value)

if __name__=='__main__':unittest.main()
