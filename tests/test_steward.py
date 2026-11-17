from tests.runtime_fixture import seeded_draft
"""Steward delegation survives client exit and transfers pending work safely."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from loop_anything.interfaces.agent_tasks import RunTools
from tests.runtime_fixture import RuntimeStewardTools as PlatformTools
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime.store import Store


class StewardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {'LOOP_ANYTHING_IDENTITY_DIR': str(self.root / 'identity')})
        env.start()
        self.addCleanup(env.stop)
        self.store = Store(self.root / 'service.db')
        self.engine = Engine(self.store)
        self.addCleanup(self.engine.close)
        self.tools = PlatformTools(self.store)
        for ident in ('first', 'second'):
            self.tools.call('communication_config', {'operation': 'agent', 'agent_id': ident, 'agent': {
                'name': ident, 'description': 'Manage isolated test Runs', 'local': True,
                'implementation': {'kind': 'agent', 'cwd': str(Path(__file__).resolve().parents[1]),
                                   'command': [sys.executable, '-c', 'print("managed")']}}})
        self.draft = seeded_draft(self.tools,{'name': 'Steward test'})
        self.edit('set_loop', handbook='Initialize, wait for evidence, then decide with full records.')
        self.edit('put_node', node_id='work', instructions='Wait for evidence', outputs=[{'name': 'result', 'type': 'object'}])
        self.edit('set_implementation', node_id='work', kind='event', event='ready', wait={'key': 'evidence'})
        self.edit('put_node', node_id='fixed', instructions='Fixed end', progression='rules', outputs=[])
        self.edit('set_implementation', node_id='fixed', kind='timer', wait={'seconds': 0, 'outputs': {}})
        self.key = self.tools.call('publish_loop', {'draft_id': self.draft['draft_id'], 'revision': self.draft['revision']})['key']

    def edit(self, name, **values):
        self.draft = self.tools.call(name, dict(draft_id=self.draft['draft_id'], revision=self.draft['revision'], **values))

    def start(self):
        self.start_args = {'key': self.key, 'title': 'Research', 'authorization': 'Test only',
                           'request_id': 'startup', 'steward_id': 'first', 'message': 'Begin the experiment'}
        receipt = self.tools.call('start_run', self.start_args)
        self.run_id = receipt['run_id']
        return receipt

    def worker(self, task_id):
        current=self.store.get(self.run_id)
        if current.get('steward',{}).get('session_id'):
            from loop_anything.runtime import work
            with self.store.connection() as db:session=work.get(db,'session',current['steward']['session_id'])
            with self.store.edit(self.run_id) as run:claim=work.claim_in_run(self.store,run,session)
            return RunTools(self.store,self.run_id,claim['token'])
        with patch.object(self.engine.timeline_runtime, 'execute'):
            self.engine.tick(self.run_id)
            for future in list(self.engine.futures):
                future.result(timeout=5)
        run = self.store.get(self.run_id)
        task = run['tasks'][task_id]
        execution = next(e for e in run['executions'] if e['id'] == task['execution_id'])
        return RunTools(self.store, self.run_id, execution['token'])

    def complete(self, worker, task_id, outputs, **envelope):
        info = worker.call('read_task', {'task_id': task_id})
        return worker.call('report_task', {'task_id': task_id, 'event': 'completed', 'report_id': 'complete-' + task_id, 'envelope': dict(outputs=outputs, **envelope)})

    def initialize(self, worker):
        self.complete(worker, 'initialize', {}, settings={'objective': 'Test durable startup'})

    def republish(self):
        published = self.tools.call('publish_loop', {'draft_id': self.draft['draft_id'],
            'revision': self.draft['revision'], 'auto_version': True})
        self.key = published['key']
        self.draft['revision'] = published['revision']

    def tick_without_cli(self):
        with patch.object(self.engine.timeline_runtime, 'execute'):
            self.engine.tick(self.run_id)
            for future in list(self.engine.futures):
                future.result(timeout=5)

    def initialized_start(self):
        request = self.start()
        worker = self.worker(request['task_id'])
        self.initialize(worker)
        return request, worker

    def finish_start(self, request, worker):
        self.complete(worker, request['task_id'], {'decision': 'Initial work arranged'})
        worker.call('finish', {})

    def test_public_start_has_no_caller_owned_compatibility_path(self):
        names = {d['name'] for d in self.tools.definitions()}
        self.assertNotIn('acquire_run', names)
        with self.assertRaises(Invalid):
            self.tools.call('start_run', {'key': self.key, 'title': 'Old caller', 'authorization': 'test'})
        self.assertEqual(self.store.list(), [])
        request = self.start()
        self.assertNotIn('token', request)
        with self.assertRaises(Invalid):
            self.tools.call('change_settings', {'run_id': self.run_id, 'revision': 1, 'change': {'guidance': 'bypass'}})

    def test_cli_start_requires_steward_and_retries_same_request(self):
        import subprocess
        command = [sys.executable, '-m', 'loop_anything', '--db', self.store.filename, 'create', self.key,
                   '--title', 'CLI start', '--authorization', 'test']
        missing = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(self.store.list(), [])
        session=self.tools.call('register_work_session', {
            'native_session':{'provider':'custom','id':'cli-original'},
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass'],
                'resume_command':[sys.executable,'-c','pass','{{session_id}}','{{prompt}}']},
            'process_id':os.getpid()})
        command += ['--request-id','cli-start','--session-id',session['session_id'],'--session-token',session['session_token']]
        receipts=[json.loads(subprocess.run(command,capture_output=True,text=True,check=True).stdout) for _ in range(2)]
        self.assertEqual(receipts[0],receipts[1])
        self.assertEqual(receipts[0]['status'],'accepted')
        self.assertIn('token',receipts[0])
        self.assertEqual(len(self.store.list()),1)

    def test_explicit_decision_route_uses_selected_steward_without_loop_executor(self):
        self.edit('put_node', node_id='work', progression='rules',
                  routes=[{'id': 'review', 'event': 'completed', 'flow_agent': True}])
        self.republish()
        request, worker = self.initialized_start()
        worker.call('read_timeline', {})
        worker.call('add_task', {'key': 'route-test', 'node_id': 'work', 'inputs': {}})
        self.finish_start(request, worker)
        self.tick_without_cli()
        from loop_anything.runtime.notifications import receive_event
        with self.store.edit(self.run_id) as run:
            receive_event(run, 'result', 'ready', {'result': {}}, 'evidence')
        self.tick_without_cli()
        run = self.store.get(self.run_id)
        decisions = [r for r in run['steward_requests'].values() if r['operation'] == 'decide']
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['arguments']['route_id'], 'review')
        self.assertEqual(run['tasks'][decisions[0]['task_id']]['status'], 'executing')

    def test_called_loop_inherits_steward_and_durable_startup(self):
        child_key = self.key
        self.edit('put_node', node_id='child', instructions='Delegate another Loop', outputs=[])
        self.edit('set_implementation', node_id='child', kind='loop', loop={'key': child_key})
        self.republish()
        request, worker = self.initialized_start()
        worker.call('read_timeline', {})
        child_task = worker.call('add_task', {'key': 'child', 'node_id': 'child', 'inputs': {}})['tasks'][0]['id']
        self.finish_start(request, worker)
        self.tick_without_cli()
        self.tick_without_cli()
        parent = self.store.get(self.run_id)
        child = self.store.get(parent['tasks'][child_task]['child_call']['run_id'])
        self.assertEqual(child['steward']['agent_id'], 'first')
        self.assertEqual(child['steward']['generation'], 1)
        startup = next(iter(child['steward_requests'].values()))
        self.assertEqual(startup['operation'], 'start')
        self.assertEqual(self.tools.call('read_run_request', {'request_id': startup['id']})['run_id'], child['id'])
        with patch.object(self.engine.timeline_runtime, 'execute'):
            self.engine.tick(child['id'])
        child = self.store.get(child['id'])
        self.assertIsNone(child['tasks']['initialize']['execution_id'])
        self.assertEqual(child['tasks'][startup['task_id']]['status'], 'executing')

    def test_progression_waits_for_current_steward_after_takeover(self):
        self.edit('put_node', node_id='work', progression='steward')
        self.republish()
        request, worker = self.initialized_start()
        worker.call('read_timeline', {})
        source = worker.call('add_task', {'key': 'source', 'node_id': 'work', 'inputs': {}})['tasks'][0]['id']
        follow = worker.call('add_task', {'key': 'follow', 'node_id': 'fixed', 'inputs': {}, 'after': [source]})['tasks'][0]['id']
        self.finish_start(request, worker)
        self.tick_without_cli()
        from loop_anything.runtime.notifications import receive_event
        with self.store.edit(self.run_id) as run:
            receive_event(run, 'ready-one', 'ready', {'result': {}}, 'evidence')
        self.tick_without_cli()
        run = self.store.get(self.run_id)
        decision = next(r for r in run['steward_requests'].values() if r['operation'] == 'decide')
        self.assertEqual(run['tasks'][follow]['status'], 'blocked')
        self.assertEqual(run['tasks'][follow]['wait_reasons'][0]['reason'], 'steward_decision')
        self.assertIsNone(run['tasks'][follow]['execution_id'])
        self.tools.call('assign_run_steward', {'run_id': self.run_id, 'steward_id': 'second', 'generation': 1})
        current = self.tools.call('read_run_request', {'request_id': decision['id']})
        self.assertNotEqual(current['task_id'], decision['task_id'])
        manager = self.worker(current['task_id'])
        self.assertIsNone(self.store.get(self.run_id)['tasks'][follow]['execution_id'])
        self.complete(manager, current['task_id'], {'decision': 'Reviewed; continue the existing successor'})
        manager.call('finish', {})
        self.tick_without_cli()
        self.assertIsNotNone(self.store.get(self.run_id)['tasks'][follow]['execution_id'])

    def test_script_entry_failure_can_be_repaired_without_waiting_for_entry(self):
        self.edit('set_implementation', node_id='initialize', kind='command', clear=['lifecycle'],
                  command=[sys.executable, '-c', 'import sys;sys.exit(1)'])
        self.republish()
        self.start()
        self.engine.tick(self.run_id)
        for future in list(self.engine.futures):
            future.result(timeout=5)
        self.tick_without_cli()
        self.tick_without_cli()
        run = self.store.get(self.run_id)
        self.assertEqual(run['tasks']['initialize']['status'], 'fault')
        repair = next(r for r in run['steward_requests'].values() if r['operation'] == 'repair')
        self.assertEqual(run['tasks'][repair['task_id']]['status'], 'executing')
        self.assertFalse(run['tasks'][repair['task_id']]['spec'].get('after'))
        self.assertEqual(self.tools.call('read_run_request', {'request_id': 'startup'})['status'], 'failed')

    def test_full_business_capacity_still_admits_one_management_turn(self):
        self.edit('set_implementation', node_id='work', kind='agent', clear=['lifecycle', 'event', 'wait'],
                  command=[sys.executable, '-c', 'print("business")'])
        self.republish()
        request, worker = self.initialized_start()
        settings = worker.call('read_run', {'view':'snapshot'})['settings']
        worker.call('change_settings', {'revision': settings['revision'], 'change': {'max_parallel': 1}})
        work = worker.call('add_task', {'key': 'long', 'node_id': 'work', 'inputs': {}})['tasks'][0]['id']
        self.finish_start(request, worker)
        self.tick_without_cli()
        requests = [self.tools.call('submit_run_request', {'request_id': str(i), 'operation': 'modify',
                    'run_id': self.run_id, 'message': 'Inspect current work'}) for i in range(2)]
        self.tick_without_cli()
        run = self.store.get(self.run_id)
        self.assertEqual(run['tasks'][work]['status'], 'executing')
        self.assertEqual([run['tasks'][r['task_id']]['status'] for r in requests], ['executing', 'ready'])
        # Ordinary completed task sessions retain the original resume path.
        execution = next(e for e in run['executions'] if e['id'] == run['tasks'][work]['execution_id'])
        business = RunTools(self.store, self.run_id, execution['token'])
        self.complete(business, work, {'result': {}})
        business.call('finish', {})
        from loop_anything.runtime.native_sessions import resume
        restored = resume(self.engine, self.run_id, execution['id'], {'message': 'Explain this result',
            'provider': 'codex', 'native_session_id': 'test-business-session',
            'command': [sys.executable, '-c', 'pass', '{{session_id}}', '{{prompt}}']})
        self.assertTrue(restored['session_id'])
        from loop_anything.interfaces.agent_tasks import acquire_in_run
        with self.store.edit(self.run_id) as run:
            manager_task = run['tasks'][requests[0]['task_id']]
            with self.assertRaises(Conflict):
                acquire_in_run(run, 'interactive', execution_id=manager_task['execution_id'])

    def test_reads_are_pure_and_queued_requests_do_not_block_current_work(self):
        request, worker = self.initialized_start()
        worker.call('read_timeline', {})
        from loop_anything.runtime.run_library import list_runs
        before = list_runs(self.store)['runs'][0]['last_activity_at']
        self.tools.call('read_timeline', {'run_id': self.run_id})
        self.assertEqual(before, list_runs(self.store)['runs'][0]['last_activity_at'])
        worker.call('add_task', {'key': 'after-query', 'node_id': 'work', 'inputs': {}})
        worker.call('read_timeline', {})
        self.tools.call('submit_run_request', {'request_id': 'real-change', 'operation': 'modify', 'run_id': self.run_id})
        self.assertTrue(worker.call('add_task', {'key': 'after-change', 'node_id': 'work', 'inputs': {}})['tasks'])

    def test_steward_can_apply_only_the_authorization_explicitly_supplied_by_user(self):
        request, worker = self.initialized_start()
        settings = worker.call('read_run', {'view':'snapshot'})['settings']
        with self.assertRaises(Invalid):
            worker.call('change_settings', {'revision': settings['revision'], 'change': {'authorization': 'Invented permission'}})
        self.finish_start(request, worker)
        update = self.tools.call('submit_run_request', {'request_id': 'permission', 'operation': 'modify',
            'run_id': self.run_id, 'message': 'Allow the next experiment'})
        manager = self.worker(update['task_id'])
        settings = manager.call('read_run', {'view':'snapshot'})['settings']
        from tests.runtime_fixture import update_work
        result=update_work(self.store,self.run_id,{'constraints':'Run experiment B'})
        self.assertIn('告诉用户',result['notice'])
        self.assertEqual(self.store.get(self.run_id)['settings']['constraints'], 'Run experiment B')

    def test_request_reply_keeps_its_requester_and_outlet_through_retry(self):
        request, worker = self.initialized_start()
        self.finish_start(request, worker)
        answer = self.tools.call('submit_run_request', {'request_id': 'user-b', 'operation': 'explain',
            'run_id': self.run_id, 'created_by': 'User B', 'notification_route': 'b-inbox'})
        manager = self.worker(answer['task_id'])
        self.complete(manager, answer['task_id'], {'decision': 'Full answer for User B'})
        manager.call('finish', {})
        run = self.store.get(self.run_id)
        self.assertEqual(run['steward_requests']['user-b']['context']['created_by'], 'User B')
        notice = next(n for n in run['notifications'] if n['message'] == 'Full answer for User B')
        self.assertEqual(notice['route'], 'b-inbox')
        self.assertEqual(notice['status'], 'waiting_configuration')
        self.tools.call('set_notification_channels', {'revision': 0, 'channels': {
            'b-inbox': {'command': [sys.executable, '-c', 'print(\'{"delivered":true}\')']}}})
        self.tools.call('submit_run_request', {'request_id': 'retry-delivery', 'operation': 'command',
            'run_id': self.run_id, 'arguments': {'action': 'retry_notification', 'notification_id': notice['id']}})
        self.engine.tick(self.run_id)
        for future in list(self.engine.futures):
            future.result(timeout=5)
        delivered = next(n for n in self.store.get(self.run_id)['notifications'] if n['id'] == notice['id'])
        self.assertEqual(delivered['route'], 'b-inbox')
        self.assertEqual(delivered['status'], 'delivered')

    def test_atomic_start_identity_default_return_and_explicit_rule_mode(self):
        request = self.start()
        self.assertNotIn('token', request)
        self.assertEqual(self.tools.call('start_run', self.start_args)['run_id'], self.run_id)
        with self.assertRaises(Conflict):
            self.tools.call('start_run', dict(self.start_args, title='different'))
        worker = self.worker(request['task_id'])
        self.initialize(worker)
        worker.call('read_timeline', {})
        work = worker.call('add_task', {'key': 'first-experiment', 'node_id': 'work', 'inputs': {}})['tasks'][0]['id']
        worker.call('add_task', {'key': 'fixed-step', 'node_id': 'fixed', 'inputs': {}})
        self.complete(worker, request['task_id'], {'decision': {'answer': 'Started', 'task': work}})
        worker.call('finish', {})
        self.assertEqual(self.tools.call('read_run_request', {'request_id': 'startup'})['status'], 'completed')
        with self.assertRaises(Invalid):
            self.tools.call('change_settings', {'run_id': self.run_id, 'revision': 1, 'change': {'guidance': 'bypass'}})
        self.engine.tick(self.run_id)
        self.engine.tick(self.run_id)
        self.tools.call('read_timeline', {'run_id': self.run_id})
        with self.store.edit(self.run_id) as run:
            from loop_anything.runtime.notifications import receive_event
            receive_event(run, 'evidence', 'ready', {'result': {'metric': 12}}, 'evidence')
        with patch.object(self.engine.timeline_runtime, 'execute'):
            self.engine.tick(self.run_id)
        run = self.store.get(self.run_id)
        decisions = [t for t in run['tasks'].values() if t['origin'].get('flow_agent', {}).get('task_id') == work]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['origin']['steward'], 1)
        self.assertEqual(len([t for t in run['tasks'].values() if t['spec']['node'] == '$flow_agent']), 2)

    def test_takeover_fences_old_manager_and_preserves_pending_request(self):
        request = self.start()
        old = self.worker(request['task_id'])
        self.initialize(old)
        self.tools.call('assign_run_steward', {'run_id': self.run_id, 'steward_id': 'second', 'generation': 1})
        with self.assertRaises(Conflict):
            old.call('read_task', {'task_id': request['task_id']})
        new_request = self.tools.call('read_run_request', {'request_id': 'startup'})
        self.assertNotEqual(new_request['task_id'], request['task_id'])
        new = self.worker(new_request['task_id'])
        self.assertEqual(self.store.get(self.run_id)['settings']['objective'],'Test durable startup')
        self.complete(new, new_request['task_id'], {'decision': 'Recovered startup from persisted initialization'})
        new.call('finish', {})
        self.assertEqual(self.tools.call('read_run_request', {'request_id': 'startup'})['steward']['agent_id'], 'second')

    def test_questions_replies_and_paused_run_management(self):
        request = self.start()
        worker = self.worker(request['task_id'])
        answer = self.tools.call('answer_run_request', {'run_id': self.run_id, 'token': worker.token,
            'request_id': 'startup', 'status': 'waiting_user', 'result': 'Which dataset?'})
        self.assertEqual(answer['status'], 'waiting_user')
        worker.call('finish', {})
        reply = {'request_id': 'startup', 'reply_id': 'data', 'message': 'Use dataset A'}
        receipt = self.tools.call('reply_run_request', reply)
        self.assertEqual(self.tools.call('reply_run_request', reply)['task_id'], receipt['task_id'])
        self.tools.call('submit_run_request', {'request_id': 'pause', 'operation': 'command',
            'run_id': self.run_id, 'arguments': {'action': 'pause'}})
        current = self.worker(receipt['task_id'])
        self.assertEqual(self.store.get(self.run_id)['status'], 'paused')
        self.assertEqual(self.tools.call('read_run_request', {'request_id': 'startup'})['replies'][0]['message'], 'Use dataset A')

    def test_real_server_agent_completes_start_after_caller_disconnects(self):
        code = '''import json,sys
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
c=json.loads(sys.stdin.read().split('Run context:\\n',1)[1])
t=RunTools(Store(sys.argv[1]),c['run_id'],c['token'])
def complete(task, outputs, **envelope):
 i=t.call('read_task',{'task_id':task})
 t.call('report_task',{'task_id':task,'event':'completed','report_id':task,'envelope':dict(outputs=outputs,**envelope)})
complete('initialize',{},settings={'objective':'Persisted user intent'})
t.call('read_timeline',{})
t.call('add_task',{'key':'experiment','node_id':'work','inputs':{}})
complete(c['task_id'],{'decision':{'answer':'Ready','request_id':c['steward_request']['id']}})
t.call('finish',{})
'''
        self.tools.call('communication_config', {'operation': 'agent', 'agent_id': 'first', 'agent': {
            'implementation': {'kind': 'agent', 'cwd': str(Path(__file__).resolve().parents[1]),
                               'command': [sys.executable, '-c', code, self.store.filename]}}})
        self.start()
        self.engine.tick(self.run_id)
        for future in list(self.engine.futures):
            future.result(timeout=10)
        result = self.tools.call('read_run_request', {'request_id': 'startup'})
        self.assertEqual(result['status'], 'completed', self.store.get(self.run_id)['executions'])
        self.assertEqual(result['result']['answer'], 'Ready')
        self.assertFalse(self.store.get(self.run_id)['agent_sessions'])

    def test_nas_replayed_start_reuses_run_and_terminal_run_accepts_explanation(self):
        from loop_anything.runtime.tool_mailbox import ToolMailbox
        from loop_anything.runtime.tool_client import module
        mailbox = ToolMailbox(self.store, self.root / 'team', self.engine)
        transport = module('platform_transport')
        url = 'nas://' + str(mailbox.root)
        session=self.tools.call('register_work_session', {
            'native_session':{'provider':'custom','id':'nas-original'},
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass'],
                'resume_command':[sys.executable,'-c','pass','{{session_id}}','{{prompt}}']},
            'process_id':os.getpid()})
        args = dict(session,key=self.key,title='NAS start',request_id='nas-startup',constraints='test',objective='Test durable startup')
        for api_id in ('request-one', 'request-retry'):
            waiting = transport.invoke(url, 'start_run', args, request_id=api_id, wait=0)
            self.assertTrue(waiting['pending'])
            mailbox.tick()
            result = transport.result(url, api_id)
            self.assertTrue(result['ok'], result)
        self.assertEqual(len(self.store.list()), 1)
        self.run_id = result['run_id']
        worker = self.worker(result['task_id'])
        self.initialize(worker)
        self.complete(worker, result['task_id'], {'decision': 'Initialized'})
        worker.call('finish', {})
        self.tools.call('submit_run_request', {'request_id': 'stop', 'operation': 'command',
            'run_id': self.run_id, 'arguments': {'action': 'terminate'}})
        explanation = self.tools.call('submit_run_request', {'request_id': 'explain', 'operation': 'explain',
            'run_id': self.run_id, 'message': 'Explain the result'})
        worker = self.worker(explanation['task_id'])
        self.complete(worker, explanation['task_id'], {'decision': 'The user ended this Run.'})
        worker.call('finish', {})
        self.assertEqual(self.tools.call('read_run_request', {'request_id': 'explain'})['status'], 'completed')
