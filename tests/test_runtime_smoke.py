"""Real subprocess startup and real lifecycle writes, without business services/models."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_packages import document
from loop_anything.packaging.packages import install, load_installed, make_archive
from loop_anything.packaging.runtime_smoke import runtime_smoke
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.lifecycle import template
from loop_anything.runtime.store import Store


class RuntimeSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
    def tearDown(self):
        self.tmp.cleanup()
    def installed(self, implementations, assets=None):
        doc = document();doc['implementations'] = implementations
        result = install(self.store, make_archive(doc, assets or {}))
        loaded, root = load_installed(self.store.filename, result['key'])
        return loaded, root, result['key']

    def test_installed_agent_and_fallback_use_exact_cwd_command_and_failure_is_visible(self):
        script = b'import pathlib,sys\nassert pathlib.Path("probe.py").exists()\nprint(sys.stdin.read().split("exactly: ")[-1])\n'
        doc = document()
        doc['loop_definition']['nodes']['finish']['inputs'] = {}
        doc['loop_definition']['fallback_node'] = 'finish'
        doc['implementations'] = {'initialize': {'kind': 'agent', 'command': [sys.executable, 'probe.py']},
                                 'finish': {'kind': 'agent', 'command': [sys.executable, '-c', 'import sys;sys.stderr.write("directory not trusted");sys.exit(7)']}}
        result = install(self.store, make_archive(doc, {'probe.py': (script, False)}))
        loaded, root = load_installed(self.store.filename, result['key'])
        before = copy.deepcopy(loaded)
        report = PlatformTools(self.store).call('smoke_runtime', {'key': result['key'], 'timeout': 3})
        rows = {r['node']: r for r in report['checks']}
        self.assertEqual(rows['initialize']['status'], 'pass')
        self.assertEqual(Path(rows['initialize']['cwd']), root)
        self.assertEqual(rows['finish']['status'], 'fail')
        self.assertIn('directory not trusted', rows['finish']['detail'])
        self.assertFalse(report['ready'])
        self.assertEqual(self.store.list(), [])
        self.assertEqual(before, load_installed(self.store.filename, result['key'])[0])
        cli = subprocess.run([sys.executable, '-m', 'loop_anything', '--db', self.store.filename,
                              'smoke-runtime', result['key'], '--node', 'initialize', '--timeout', '3'], capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertTrue(json.loads(cli.stdout)['verified'])

    def test_lifecycle_missing_events_retry_observation_and_conditional_cases(self):
        matrix = template('external')
        next(r for r in matrix['transitions'] if r['from'] == 'waiting' and r['event'] == 'failed')['to'] = 'retry'
        config = {'kind': 'external', 'command': [sys.executable, '-c', 'raise AssertionError("must not submit")'], 'observe': [sys.executable, '-c', 'raise AssertionError("must not observe")'], 'lifecycle': matrix}
        doc, root, _ = self.installed({'finish': config})
        report = runtime_smoke(doc, root)
        self.assertTrue(report['ready'], report)
        retry = next(r for r in report['checks'] if r.get('state') == 'waiting' and r.get('event') == 'failed')
        self.assertIn('attempt 2', retry['detail'])
        self.assertFalse(report['verified'])  # Actual external services remain untested.
        matrix['transitions'] = [r for r in matrix['transitions'] if r['event'] != 'check_error']
        doc, root, _ = self.installed({'finish': config})
        bad = runtime_smoke(doc, root)
        self.assertFalse(bad['ready'])
        self.assertTrue(any(r['status'] == 'fail' and r.get('event') == 'check_error' for r in bad['checks']))
        matrix['transitions'].append({'from': 'waiting', 'event': 'check_error', 'to': 'waiting'})
        retry_rule = next(r for r in matrix['transitions'] if r['from'] == 'waiting' and r['event'] == 'failed')
        retry_rule['when'] = {'op': 'le', 'args': [{'path': 'attempt'}, 2]}
        matrix['transitions'].append({'from': 'waiting', 'event': 'failed', 'to': 'agent',
                                     'when': {'op': 'ge', 'args': [{'path': 'attempt'}, 3]}})
        doc, root, _ = self.installed({'finish': config})
        cases = [{'node': 'finish', 'implementation': 'default', 'state': 'waiting', 'event': 'failed', 'attempt': n, 'expected': to}
                 for n, to in [(1, 'retry'), (3, 'agent')]]
        checked = runtime_smoke(doc, root, cases=cases)
        self.assertTrue(checked['ready'], checked)
        cases[-1]['expected'] = 'retry'
        self.assertFalse(runtime_smoke(doc, root, cases=cases)['ready'])
        self.assertFalse(self.store.list())

    def test_timeout_and_corrupt_asset_do_not_become_success(self):
        doc, root, _ = self.installed({'initialize': {'kind': 'agent', 'command': [sys.executable, '-c', 'import time;time.sleep(5)']}})
        report = runtime_smoke(doc, root, timeout=.05)
        self.assertFalse(report['ready'])
        doc, root, _ = self.installed({'initialize': {'kind': 'agent', 'command': [sys.executable, 'probe.py']}}, {'probe.py': (b'raise AssertionError("must not execute")', False)})
        (root / 'probe.py').write_text('changed')
        self.assertFalse(runtime_smoke(doc, root)['ready'])
