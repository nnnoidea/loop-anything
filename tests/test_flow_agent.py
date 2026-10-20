"""A discovered flow recipe decides, hands off a durable wait, and returns on evidence."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.store import Store


class FlowAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        environment = patch.dict(os.environ, {'LOOP_ANYTHING_IDENTITY_DIR': str(Path(self.tmp.name) / 'identity')})
        environment.start(); self.addCleanup(environment.stop)
        self.store = Store(Path(self.tmp.name) / 'run.db')
        self.platform = PlatformTools(self.store)
        self.engine = Engine(self.store)
        self.draft = self.platform.call('create_loop', {'name': 'Skill to Loop'})
        recipe = self.platform.call('read_capabilities', {'capability': 'flow_agent'})['patterns']['flow_agent_decision']
        self.edit('put_node', **recipe['node'])
        self.edit('set_implementation', node_id='flow_agent', kind='agent')
        self.edit('set_loop', global_agent_node='flow_agent', handbook='Use the existing business Skill; wait for external facts before deciding.')
        for name, step in recipe['plan']['steps'].items():
            step = dict(step); step['node_id'] = step.pop('node')
            self.edit('put_step', plan='decide_next', step=name, **step)
        self.edit('put_node', node_id='initialize', outputs=[{'name': 'result', 'type': 'object'}], routes=recipe['source_routes'])
        self.edit('put_node', node_id='wait', instructions='Wait for external result', outputs=[{'name': 'result', 'type': 'object'}], routes=recipe['source_routes'])
        self.edit('set_implementation', node_id='wait', kind='event', event='result', wait={'key': 'work'})

    def tearDown(self):
        self.engine.close(); self.tmp.cleanup()

    def edit(self, name, **arguments):
        self.draft = self.platform.call(name, dict(draft_id=self.draft['draft_id'], revision=self.draft['revision'], **arguments))

    def start(self, completion=None):
        key = self.platform.call('publish_loop', {'draft_id': self.draft['draft_id'], 'revision': self.draft['revision']})['key']
        started = self.platform.call('start_run', {'key': key, 'title': 'Existing Skill', 'authorization': 'Isolated test'})
        self.run_id = started['run_id']
        tools = RunTools(self.store, self.run_id, started['token'])
        settings = {'objective': 'Wait for evidence then decide'}
        if completion: settings['completion_rule'] = completion
        self.complete(tools, started['entry_task_id'], {'result': {'stage': 'initial'}}, settings=settings)
        tools.call('finish', {})

    def complete(self, tools, task_id, outputs, **envelope):
        info = tools.call('read_task', {'task_id': task_id})
        args = dict(task_id=task_id, task_version=info['task_version'], report_id='complete:' + task_id,
                    event='completed', envelope=dict(outputs=outputs, **envelope))
        receipt = tools.call('report_task', args)
        self.assertTrue(receipt['accepted'])
        self.assertTrue(tools.call('report_task', args)['duplicate'])
        return receipt

    def decision(self):
        self.engine.tick(self.run_id)
        run = self.store.get(self.run_id)
        execution = next(e for e in reversed(run['executions']) if e['node'] == 'flow_agent' and e['status'] == 'decision')
        return execution['task_id'], RunTools(self.store, self.run_id, execution['token'])

    def test_decide_wait_wake_finish_and_trace_exact_evidence(self):
        self.start()
        task, agent = self.decision()
        info = agent.call('read_task', {'task_id': task})
        self.assertEqual(info['inputs']['result'], {'stage': 'initial'})
        self.assertEqual(info['inputs']['trigger']['transition']['to'], 'completed')
        timeline = agent.call('read_timeline', {})
        self.assertIsNone(timeline['scope_task'])
        self.assertEqual(timeline['handbook']['instructions'], self.store.get(self.run_id)['loop_definition']['handbook']['instructions'])
        self.assertFalse(info['skills'])
        planned = agent.call('add_task', {'key': 'external-work', 'node_id': 'wait', 'inputs': {}})
        self.assertEqual(planned, agent.call('add_task', {'key': 'external-work', 'node_id': 'wait', 'inputs': {}}))
        wait_id = planned['tasks'][0]['id']
        decision = {'action': 'wait for result', 'reason': 'Need the external measurement', 'evidence': info['sources']}
        self.complete(agent, task, {'decision': decision}); agent.call('finish', {})
        for _ in range(5): self.engine.tick(self.run_id)
        run = self.store.get(self.run_id)
        self.assertEqual(run['tasks'][wait_id]['status'], 'waiting')
        self.assertEqual(sum(e['node'] == 'flow_agent' for e in run['executions']), 1)
        self.assertFalse(run['agent_sessions'])
        self.assertEqual(run['tasks'][wait_id]['origin']['agent'], run['tasks'][task]['execution_id'])
        self.engine.close(); self.engine = Engine(self.store); self.engine.recover()
        event = {'run_id': self.run_id, 'name': 'result', 'key': 'work', 'event_id': 'measurement', 'payload': {'result': {'score': 42}}}
        self.platform.call('send_event', event); self.platform.call('send_event', event)
        task2, agent2 = self.decision()
        info2 = agent2.call('read_task', {'task_id': task2})
        self.assertEqual(info2['inputs']['result'], {'score': 42})
        self.assertEqual(info2['inputs']['trigger']['task_id'], wait_id)
        self.complete(agent2, task2, {'decision': {'action': 'stop', 'reason': 'Goal satisfied'}})
        agent2.call('change_settings', {'revision': agent2.call('read_timeline', {})['settings']['revision'], 'change': {'termination_signal': 'Goal satisfied'}})
        agent2.call('finish', {}); self.engine.tick(self.run_id)
        run = self.store.get(self.run_id)
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(sum(t['spec']['node'] == 'flow_agent' for t in run['tasks'].values()), 2)
        self.engine.close()
        before = self.store.get(self.run_id)
        saved = self.platform.call('read_run', {'run_id': self.run_id})['run']
        execution_id = saved['tasks'][task]['execution_id']
        committed = next(h for h in saved['history'] if h['kind'] == 'committed' and h['execution'] == execution_id)
        ref = committed['detail']['decision']
        value = self.platform.call('read_record', {'run_id': self.run_id, 'id': ref['record'], 'revision': ref['revision']})['record']['value']
        self.assertEqual(value, decision)
        execution = next(e for e in saved['executions'] if e['id'] == execution_id)
        self.assertEqual(execution['inputs'], info['inputs'])
        self.assertTrue(any(h['kind'] == 'route_fired' for h in saved['history']))
        self.assertTrue(any(h['kind'] == 'transition' and h['detail'].get('accepted') for h in saved['history']))
        self.assertEqual(self.store.get(self.run_id), before)

    def test_deterministic_path_never_calls_flow_agent(self):
        self.edit('put_node', node_id='wait', routes=[], outputs=[])
        self.edit('set_implementation', node_id='wait', kind='timer', wait={'seconds': 0}, clear=['event', 'lifecycle'])
        self.edit('put_step', plan='wait_only', step='wait', node_id='wait', inputs={})
        self.edit('put_node', node_id='initialize', routes=[{'id':'wait','event':'completed','plan':'wait_only','values':{}}])
        self.start({'op':'eq','args':[{'path':'active_tasks'},0]})
        for _ in range(4): self.engine.tick(self.run_id)
        run = self.store.get(self.run_id)
        self.assertEqual(run['status'], 'completed')
        self.assertFalse(any(e['node'] == 'flow_agent' for e in run['executions']))
        self.assertEqual({t['spec']['node'] for t in run['tasks'].values()}, {'initialize', 'wait'})

    def test_packaged_loop_handbook_reaches_wake_context_without_node_skill(self):
        from loop_anything.runtime.agent_prompt import task_context
        content = '# Existing business method\n' + 'Keep the full constraints and decision rules.\n' * 500
        self.edit('put_asset', path='guide/SKILL.md', content=content)
        self.edit('set_loop', handbook_path='guide/SKILL.md')
        self.start()
        task_id, agent = self.decision()
        run = self.store.get(self.run_id)
        execution = next(e for e in run['executions'] if e['task_id'] == task_id)
        context = task_context(self.store, run, execution, 'http://127.0.0.1:8767', None)
        handbook = agent.call('read_timeline', {})['handbook']
        self.assertEqual(context['handbook'], handbook)
        self.assertEqual(Path(handbook['resolved_path']).read_text(), content)
        self.assertFalse(context['skills'])
