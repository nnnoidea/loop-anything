"""Real runtime acceptance. Example code only builds definitions / returns handler JSON."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
import tempfile
import unittest
from pathlib import Path
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.store import Store
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.interfaces.agent_tasks import acquire, RunTools
from loop_anything.examples.loops import research, trip


class PlatformLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
        self.engine = Engine(self.store)
        store = self.store
        class ToolsEndpoint(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def reply(self, result):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            def do_GET(self):
                self.reply(store.get(self.path.split('/')[3]))
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.reply(RunTools(store, self.path.split('/')[3], body['token']).respond(body['tool'], body['arguments']))
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), ToolsEndpoint)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.engine.platform_url = 'http://127.0.0.1:%s' % self.http.server_port

    def tearDown(self):
        self.engine.close()
        self.http.shutdown(); self.thread.join(); self.http.server_close()
        self.tmp.cleanup()

    def start(self, factory):
        bp, implementations = factory()
        key = self.store.publish(bp, implementations)['key']
        self.id = self.store.create(key, 'Acceptance', bp['defaults'])['id']

    def read(self):
        return self.store.get(self.id)

    def until(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.engine.tick(self.id)
            run = self.read()
            if any(e['status'] == 'fault' for e in run['executions']):
                self.fail(str([(e['node'], e.get('error')) for e in run['executions'] if e['status'] == 'fault']))
            if predicate(run):
                return run
            time.sleep(.025)
        self.fail('Timed out: ' + str([(w['id'], w['status'], w['wait_reasons']) for w in self.read()['tasks'].values()]))

    def pending(self, status):
        run = self.until(lambda r: any(e['status'] == status for e in r['executions']) and (status != 'approval' or not r.get('agent_sessions')))
        return next(e for e in run['executions'] if e['status'] == status)

    def approve(self, e, approved=True, **override):
        result = {'approved': approved, 'proposal_id': e['inputs']['proposal']['id'],
                  'proposal_record': e['parameters']['proposal_record'], **override}
        return self.engine.submit(self.id, e['id'], e['token'], envelope={'outputs': {'decision': result}})

    def event(self, e, status):
        payload = {'observation': {'status': status, 'detail': 'Simulated external event',
                   'booking_record': e['parameters']['event_key'], 'sequence': e['parameters']['sequence']}}
        self.engine.event(self.id, 'evt-' + e['id'], 'trip-status', payload, key=e['parameters']['event_key'])

    def test_research_independent_groups_append_work_and_finish(self):
        self.start(research)
        run = self.until(lambda r: any(e['node'] == 'reason' and e['inputs']['group'] == 'GA' and e['status'] == 'completed' for e in r['executions']))
        slow = next(e for e in run['executions'] if e['node'] == 'train' and e['inputs']['experiment']['id'] == 'B1')
        self.assertNotEqual('completed', slow['status'])
        self.assertTrue(any(w['spec']['node'] == 'train' and w['spec']['inputs']['experiment'].get('literal', {}).get('id') == 'C1' for w in run['tasks'].values()))
        ga = next(e for e in run['executions'] if e['node'] == 'reason' and e['inputs']['group'] == 'GA')
        self.assertEqual(['A1', 'A2'], [m['experiment'] for m in ga['inputs']['metrics']])
        # Restart without keeping any Agent session alive. External IDs remain in SQLite.
        self.engine.close()
        self.engine = Engine(Store(Path(self.tmp.name) / 'runs.db'))
        self.engine.platform_url = 'http://127.0.0.1:%s' % self.http.server_port
        self.engine.recover()
        run = self.until(lambda r: r['status'] == 'completed')
        self.assertEqual(4, sum(e['node'] in ('initialize', 'reason') for e in run['executions']))
        self.assertEqual([], run['diagnostics'])
        self.assertEqual(21, len(run['executions']))
        metrics = [v[-1]['value']['experiment'] for v in run['records'].values() if v[-1]['type'] == 'metric']
        self.assertEqual({'A1', 'A2', 'B1', 'C1'}, set(metrics))
        self.assertTrue(all(w['status'] == 'completed' for w in run['tasks'].values()))

    def test_trip_change_gate_notification_events_and_completion(self):
        self.start(trip)
        old = self.pending('approval')
        # A confirmation cannot smuggle a different record / plan into the graph.
        with self.assertRaises(Invalid):
            self.approve(old, proposal_record='forged')
        owner = acquire(self.store, self.id)
        tools = RunTools(self.store, self.id, owner['token'])
        tools.call('command', {'action': 'pause'})
        decision_record = self.read()['tasks'][old['task_id']]['spec']['outputs']['decision']['id']
        affected = [w['id'] for w in self.read()['tasks'].values() if w['id'] == old['task_id'] or
                    any(v.get('record') == decision_record for v in w['spec']['inputs'].values())]
        for task_id in affected:
            tools.call('change_task', {'task_id': task_id, 'operation': 'cancel', 'reason': 'User explicitly replaces the old approval and route'})
        tools.call('change_settings', {'revision': 1, 'change': {'constraints': {'destination': '北京', 'budget': 2200}}})
        with self.assertRaises(Conflict):
            self.approve(old)
        # Arrange the user-requested replacement before resuming deterministic advancement.
        tools.call('build_plan', {'name': 'replan', 'key': 'changed-requirements', 'values': {'reason': 'User changed requirements'}})
        tools.call('finish', {})
        self.engine.command(self.id, 'resume')
        current = self.pending('approval')
        self.assertNotEqual(old['id'], current['id'])
        self.assertEqual('北京', current['inputs']['proposal']['destination'])
        hooks = [{'id': 'before-book', 'action': 'pause', 'phase': 'before', 'frequency': 'once', 'target': {'node': 'book'}},
                 {'id': 'notify-book', 'action': 'notify', 'route': 'workspace', 'phase': 'after', 'frequency': 'always', 'target': {'node': 'book'}, 'message': '预订结果已写入'}]
        self.engine.change_settings(self.id, 2, {'hooks': hooks})
        self.approve(current)
        run = self.until(lambda r: any(w['status'] == 'held' for w in r['tasks'].values()))
        self.assertFalse(any(e['node'] == 'book' for e in run['executions']))
        self.engine.command(self.id, 'release_gate', hook_firing=run['hook_firings'][0]['id'])
        waiting = self.pending('waiting')
        self.assertEqual('monitor', waiting['node'])
        self.until(lambda r: len(r['notifications']) == 1 and r['notifications'][0]['status'] == 'delivered')
        # Events and run survive a full Engine/Store restart.
        self.engine.close()
        self.engine = Engine(Store(Path(self.tmp.name) / 'runs.db'))
        self.engine.platform_url = 'http://127.0.0.1:%s' % self.http.server_port
        self.engine.recover()
        self.event(waiting, 'cancelled')
        next_approval = self.pending('approval')
        self.assertNotEqual(current['inputs']['proposal']['id'], next_approval['inputs']['proposal']['id'])
        self.approve(next_approval)
        waiting = self.pending('waiting')
        self.event(waiting, 'arrived')
        run = self.until(lambda r: r['status'] == 'completed' and len(r['notifications']) == 3 and all(n['status'] == 'delivered' for n in r['notifications']))
        self.assertEqual(1, sum(n['id']=='completed:'+self.id for n in run['notifications']))
        self.assertEqual([], run['diagnostics'])
        self.assertEqual(2, sum(e['node'] == 'book' for e in run['executions']))
        self.assertEqual(1, sum(f['action'] == 'pause' for f in run['hook_firings']))

    def test_requirement_edit_does_not_revoke_accepted_approval(self):
        self.start(trip)
        old = self.pending('approval')
        self.approve(old)
        # Change occurs between formal approval commit and the next dispatch tick.
        self.engine.change_settings(self.id, 1, {'guidance': 'Change destination'})
        self.engine.tick(self.id)
        run = self.until(lambda r: any(e['node'] == 'book' for e in r['executions']))
        self.assertEqual('completed', next(e for e in run['executions'] if e['id'] == old['id'])['status'])

    def test_trip_unchanged_event_does_not_wake_agent(self):
        self.start(trip)
        self.approve(self.pending('approval'))
        waiting = self.pending('waiting')
        count = sum(e['implementation']['kind'] == 'agent' for e in self.read()['executions'])
        self.event(waiting, 'unchanged')
        run = self.until(lambda r: any(e['status'] == 'waiting' and e['id'] != waiting['id'] for e in r['executions']))
        self.assertEqual(count, sum(e['implementation']['kind'] == 'agent' for e in run['executions']))
        self.assertEqual(1, next(e for e in run['executions'] if e['status'] == 'waiting')['parameters']['sequence'])

    def test_definitions_do_not_create_or_run_work(self):
        before = self.store.list()
        research()
        trip()
        self.assertEqual(before, self.store.list())
        self.assertEqual([], self.store.catalog())


if __name__ == '__main__':
    unittest.main()
