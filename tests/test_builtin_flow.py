"""Built-in decisions share routing, durable waits and optimistic Task writes."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.flow_agent import NODE
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.store import Store


class BuiltinFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = patch.dict(os.environ, {'LOOP_ANYTHING_IDENTITY_DIR': self.tmp.name + '/identity'})
        env.start(); self.addCleanup(env.stop)
        self.store = Store(Path(self.tmp.name) / 'test.db')
        self.engine = Engine(self.store)
        self.platform = PlatformTools(self.store)
        self.draft = self.platform.call('create_loop', {'name': 'Built-in decisions'})
        recipe = self.platform.call('read_capabilities', {'capability': 'flow_agent'})['patterns']['flow_agent_decision']
        self.edit('set_loop', handbook='Use full evidence to decide the next work.', **recipe['loop'])
        self.route = recipe['source_routes'][0]
        self.edit('put_node', node_id='initialize', outputs=[{'name': 'result', 'type': 'object'}], routes=[self.route])
        self.edit('put_node', node_id='wait', instructions='Wait for the external fact', routes=[self.route], outputs=[{'name': 'result', 'type': 'object'}])
        self.edit('set_implementation', node_id='wait', kind='event', event='fact', wait={'key': 'test'})

    def tearDown(self):
        self.engine.close(); self.tmp.cleanup()

    def edit(self, tool, **values):
        self.draft = self.platform.call(tool, dict(draft_id=self.draft['draft_id'], revision=self.draft['revision'], **values))

    def start(self):
        self.key = self.platform.call('publish_loop', {'draft_id': self.draft['draft_id'], 'revision': self.draft['revision']})['key']
        start = self.platform.call('start_run', {'key': self.key, 'title': 'Flow test', 'authorization': 'Isolated test'})
        self.run_id = start['run_id']; self.entry = start['entry_task_id']
        self.tools = RunTools(self.store, self.run_id, start['token'])
        return self.tools

    def complete(self, tools, task, outputs, **envelope):
        info = tools.call('read_task', {'task_id': task})
        args = dict(task_id=task, task_version=info['task_version'], event='completed', report_id='complete:' + task,
                    envelope=dict(outputs=outputs, **envelope))
        result = tools.call('report_task', args)
        self.assertTrue(result['accepted'])
        self.assertTrue(tools.call('report_task', args)['duplicate'])
        return result

    def initialize(self):
        self.start()
        result = self.complete(self.tools, self.entry, {'result': {'stage': 'initial'}}, settings={'objective': 'Wait then decide'})
        self.tools.call('finish', {})
        return result

    def decision(self, claim=True):
        self.engine.tick(self.run_id)
        run = self.store.get(self.run_id)
        e = next(e for e in reversed(run['executions']) if e['node'] == NODE and e['status'] == 'decision')
        token = self.platform.call('acquire_run', {'run_id': self.run_id, 'task_id': e['task_id']})['token'] if claim else e['token']
        return e['task_id'], RunTools(self.store, self.run_id, token)

    def test_decision_wait_restart_return_and_complete_without_author_node(self):
        receipt = self.initialize()
        self.assertTrue(receipt['routes'][0]['flow_agent'])
        authored = self.platform.call('read_loop', {'key': self.key})['loop']['loop_definition']
        self.assertNotIn(NODE, authored['nodes'])
        self.assertNotIn('$flow_agent.decision', authored['records'])
        self.assertEqual(set(authored['nodes']), {'initialize', 'wait'})
        task, tools = self.decision()
        info = tools.call('read_task', {'task_id': task})
        self.assertFalse(info['skills'])
        self.assertEqual(info['inputs']['trigger']['task_id'], self.entry)
        self.assertIsNone(tools.call('read_timeline', {})['scope_task'])
        ref = info['inputs']['trigger']['records']['result']
        self.assertEqual(tools.call('read_record', {'id': ref['record'], 'revision': ref['revision']})['record']['value'], {'stage': 'initial'})
        source = tools.call('read_task', {'task_id': self.entry})
        self.assertEqual(source['flow_decisions'][0]['task_id'], task)
        self.assertTrue(source['route_receipts'][0]['flow_agent'])
        wait = tools.call('add_task', {'key': 'wait', 'node_id': 'wait', 'inputs': {}})['tasks'][0]['id']
        decision = {'next': wait, 'reason': 'Need the external fact', 'evidence': ref, 'full_answer': 'a' * 6000}
        self.complete(tools, task, {'decision': decision}); tools.call('finish', {})
        self.engine.tick(self.run_id)
        self.assertEqual(self.store.get(self.run_id)['tasks'][wait]['status'], 'waiting')
        self.engine.close(); self.engine = Engine(self.store); self.engine.recover()
        self.platform.call('send_event', {'run_id': self.run_id, 'name': 'fact', 'key': 'test', 'event_id': 'one', 'payload': {'result': {'score': 42}}})
        next_task, tools = self.decision()
        self.assertNotEqual(next_task, task)
        self.assertEqual(tools.call('read_task', {'task_id': next_task})['flow_trigger']['task_id'], wait)
        self.complete(tools, next_task, {'decision': 'Goal reached with full evidence.'})
        tools.call('change_settings', {'revision': tools.call('read_timeline', {})['settings']['revision'], 'change': {'termination_signal': 'done'}})
        tools.call('finish', {}); self.engine.tick(self.run_id)
        saved = self.store.get(self.run_id)
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(len([t for t in saved['tasks'].values() if t['spec']['node'] == NODE]), 2)
        self.assertEqual(saved['records'][task + '.decision'][-1]['value'], decision)

    def test_config_alone_and_false_condition_never_invoke_agent(self):
        for routes in ([], [dict(self.route, when={'op': 'eq', 'args': [1, 2]})]):
            self.edit('put_node', node_id='initialize', routes=routes)
            self.initialize()
            for _ in range(3): self.engine.tick(self.run_id)
            self.assertFalse(any(t['spec']['node'] == NODE for t in self.store.get(self.run_id)['tasks'].values()))

    def test_invalid_result_rolls_back_decision_and_pause_keeps_pending(self):
        self.start(); self.tools.call('read_task', {'task_id': self.entry}); before = self.store.get(self.run_id)
        with self.assertRaises(Invalid):
            self.complete(self.tools, self.entry, {'result': 'wrong type'}, settings={'objective': 'test'})
        self.assertEqual(self.store.get(self.run_id), before)
        self.complete(self.tools, self.entry, {'result': {}}, settings={'objective': 'test'})
        self.tools.call('finish', {})
        self.engine.command(self.run_id, 'pause'); self.engine.tick(self.run_id)
        self.assertFalse(any(e['node'] == NODE for e in self.store.get(self.run_id)['executions']))
        self.engine.close(); self.engine = Engine(self.store); self.engine.recover()
        self.engine.command(self.run_id, 'resume'); self.decision()
        self.assertEqual(sum(t['spec']['node'] == NODE for t in self.store.get(self.run_id)['tasks'].values()), 1)

    def test_rule_and_agent_routes_have_visible_receipts_and_no_implicit_fallback(self):
        self.edit('put_step', plan='work', step='wait', node_id='wait', inputs={})
        self.edit('put_node', node_id='initialize', routes=[{'id': 'rule', 'event': 'completed', 'plan': 'work', 'values': {}}, self.route])
        self.initialize(); task, tools = self.decision()
        receipts = tools.call('read_task', {'task_id': self.entry})['route_receipts']
        self.assertEqual({r['route_id'] for r in receipts}, {'rule', 'decide'})
        self.assertEqual(sum(t['spec']['node'] == 'wait' for t in self.store.get(self.run_id)['tasks'].values()), 1)
        with self.assertRaises(Invalid): tools.call('add_task', {'key': 'no-recursion', 'node_id': NODE, 'inputs': {'trigger': {'literal': {}}}})

    def test_missing_executor_config_and_mixed_route_contract(self):
        self.edit('set_loop', flow_agent=None)
        report = self.platform.call('validate_loop', {'draft_id': self.draft['draft_id']})
        self.assertFalse(report['valid'])
        self.edit('set_loop', flow_agent={'kind': 'agent'})
        with self.assertRaises(Invalid):
            self.edit('put_node', node_id='initialize', routes=[dict(self.route, plan='bogus', values={})])

    def test_concurrent_decisions_reconsider_stale_timeline_and_keep_task_claim(self):
        self.edit('put_node', node_id='initialize', routes=[self.route, dict(self.route, id='another')])
        self.initialize(); self.engine.tick(self.run_id)
        executions = [e for e in self.store.get(self.run_id)['executions'] if e['node'] == NODE]
        self.assertEqual(len(executions), 2)
        first, second = [RunTools(self.store, self.run_id, self.platform.call('acquire_run', {'run_id': self.run_id, 'task_id': e['task_id']})['token']) for e in executions]
        first.call('read_timeline', {}); second.call('read_timeline', {})
        first.call('add_task', {'key': 'one', 'node_id': 'wait', 'inputs': {}})
        with self.assertRaises(Conflict):second.call('add_task', {'key': 'two', 'node_id': 'wait', 'inputs': {}})
        from loop_anything.interfaces.agent_tasks import acquire
        with self.assertRaises(Conflict):acquire(self.store, self.run_id, executions[0]['task_id'])
        second.call('read_timeline', {})
        second.call('add_task', {'key': 'two', 'node_id': 'wait', 'inputs': {}})

    def test_real_cli_receives_trigger_commits_full_answer_and_keeps_native_session(self):
        code = """import json,sys
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
c=json.loads(sys.stdin.read().split('Run context:'+chr(10),1)[1])
assert c['flow_trigger']['event']=='completed'
t=RunTools(Store(sys.argv[1]),c['run_id'],c['token'])
print(json.dumps({'type':'thread.started','thread_id':'builtin-real-cli-session'}),flush=True)
i=t.call('read_task',{'task_id':c['task_id']})
r=i['inputs']['trigger']['records']['result']
v=t.call('read_record',{'id':r['record'],'revision':r['revision']})['record']['value']
t.call('report_task',{'task_id':c['task_id'],'task_version':i['task_version'],'event':'completed','report_id':'cli-result','envelope':{'outputs':{'decision':{'evidence':v,'answer':'complete answer'*500}}}})
t.call('finish',{})
"""
        self.edit('set_loop', flow_agent={'kind': 'agent', 'agent_cli': 'codex', 'cwd': str(Path(__file__).resolve().parents[1]),
                                        'command': [sys.executable, '-u', '-c', code, self.store.filename]})
        self.initialize(); self.engine.tick(self.run_id)
        for future in list(self.engine.futures):future.result(timeout=10)
        run = self.store.get(self.run_id)
        e = next(e for e in run['executions'] if e['node'] == NODE)
        self.assertEqual(e['status'], 'completed', e)
        self.assertEqual(e['native_session']['id'], 'builtin-real-cli-session')
        self.assertEqual(e['outputs']['decision']['evidence'], {'stage': 'initial'})
        self.assertEqual(e['outputs']['decision']['answer'], 'complete answer'*500)
        self.assertFalse(run['agent_sessions'])

    def test_read_task_observes_related_decision_changes_before_planning(self):
        self.initialize(); task, worker = self.decision()
        from loop_anything.interfaces.agent_tasks import acquire
        reader = RunTools(self.store, self.run_id, acquire(self.store, self.run_id)['token'])
        view = reader.call('read_task', {'task_id': self.entry})
        self.assertEqual(view['flow_decisions'][0]['status'], 'decision')
        self.complete(worker, task, {'decision': 'Decided elsewhere'})
        before = self.store.get(self.run_id)
        with self.assertRaises(Conflict):
            reader.call('add_task', {'key': 'stale-related-decision', 'node_id': 'wait', 'inputs': {}})
        self.assertEqual(self.store.get(self.run_id), before)
        reader.call('read_task', {'task_id': self.entry})
        reader.call('add_task', {'key': 'reconsidered', 'node_id': 'wait', 'inputs': {}})

    def test_manual_builtin_decision_can_be_claimed_once_without_a_running_cli(self):
        self.initialize(); task, previous = self.decision(claim=False)
        claimed = self.platform.call('acquire_run', {'run_id': self.run_id, 'task_id': task})
        manual = RunTools(self.store, self.run_id, claimed['token'])
        self.assertIsNone(manual.call('read_timeline', {})['scope_task'])
        with self.assertRaises(Conflict):
            self.platform.call('acquire_run', {'run_id': self.run_id, 'task_id': task})
        with self.assertRaises(Conflict):previous.call('add_task', {'key': 'stale-owner', 'node_id': 'wait', 'inputs': {}})
        self.complete(manual, task, {'decision': 'Handled in the current user Agent'})
        manual.call('finish', {})
        self.assertFalse(self.store.get(self.run_id)['agent_sessions'])
