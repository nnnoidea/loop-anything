"""Recipient configuration affects execution, never the shared package or previous Runs."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.packaging.configuration import TEMPLATE, read, write, apply
from loop_anything.packaging.packages import make_archive, read_archive, install, load_installed, installed_assets, smoke
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.store import Store
from test_packages import document, assets


class LoopConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'LOOP_ANYTHING_IDENTITY_DIR': str(self.root / 'identity')})
        env.start(); self.addCleanup(env.stop)
        self.store = Store(self.root / 'one' / 'runs.db')
        self.doc = document()
        self.doc['loop_definition']['defaults'] = {'service_url': 'author.example', 'dataset': 'author/data', 'untouched': 4}
        self.raw = make_archive(self.doc, assets())
        self.key = install(self.store, self.raw)['key']

    def save(self, value):
        return write(self.store, self.key, value, read(self.store, self.key)['revision'])

    def test_shared_template_and_recipient_file_are_separate_and_immutable_runs_keep_snapshot(self):
        packaged, files, _, _ = read_archive(self.raw)
        self.assertIn(TEMPLATE, files)
        original = copy.deepcopy(self.doc)
        saved = read(self.store, self.key)
        self.assertTrue(saved['exists'])
        self.assertNotIn('packages', Path(saved['path']).parts[-2:])
        config = {'inputs': {'dataset': '/receiver/dataset', 'service_url': 'https://receiver.example'},
                  'implementations': {'initialize': {'default': {'cwd': str(self.root), 'command': [sys.executable, '-c', 'print("configured")']}}}}
        self.save(config)
        run = self.store.create(self.key, 'configured', inputs={'dataset': '/one-run/override'})
        self.assertEqual(run['inputs'], {'dataset': '/one-run/override', 'service_url': 'https://receiver.example', 'untouched': 4})
        self.assertEqual(run['implementations']['initialize']['cwd'], str(self.root))
        self.assertEqual(run['configuration']['config'], config)
        self.assertEqual(self.doc, original)
        self.save({'inputs': {'dataset': '/next'}})
        self.assertEqual(self.store.get(run['id'])['configuration']['config'], config)
        self.assertEqual(Store(self.store.filename).create(self.key, 'next')['inputs']['dataset'], '/next')
        doc, root = load_installed(self.store.filename, self.key)
        exported = make_archive(doc, installed_assets(doc, root))
        self.assertEqual(exported, self.raw)
        second = Store(self.root / 'two' / 'runs.db')
        install(second, exported)
        self.assertEqual(second.create(self.key, 'other')['inputs']['dataset'], 'author/data')
        install(self.store, self.raw)
        self.assertEqual(read(self.store, self.key)['config'], {'inputs': {'dataset': '/next'}})

    def test_local_candidates_fill_unbound_nodes_without_rewriting_definition_or_selecting_implicitly(self):
        doc = document(); doc['implementations'] = {}
        key = install(self.store, make_archive(doc))['key']
        config = {'implementations': {'initialize': {'codex_here': {'kind': 'agent', 'command': ['codex', 'exec', '-'], 'cwd': '/not-mounted-yet'}}},
                  'bindings': {'initialize': 'codex_here'}}
        info = read(self.store, key)
        write(self.store, key, config, info['revision'])
        run = self.store.create(key, 'new')
        self.assertEqual(run['settings']['bindings']['initialize'], 'codex_here')
        self.assertEqual(run['implementations']['initialize']['options']['codex_here']['kind'], 'agent')
        self.assertNotIn('default', run['implementations']['initialize'])
        self.assertEqual(load_installed(self.store.filename, key)[0]['implementations'], {})
        self.assertEqual(self.store.create(key, 'explicit bindings', bindings={})['settings']['bindings'], {})

    def test_existing_candidate_can_clear_execution_location_but_not_change_workflow_rules(self):
        doc = document(); doc['implementations']['initialize'] = {'kind': 'agent', 'dispatch': {'location': 'group', 'agent_id': 'remote'}}
        configured = apply(doc, {'implementations': {'initialize': {'default': {'clear': ['dispatch'], 'command': ['codex', 'exec', '-']}}}})
        self.assertNotIn('dispatch', configured['implementations']['initialize'])
        self.assertIn('dispatch', doc['implementations']['initialize'])
        for config in ({'nodes': {}}, {'implementations': {'missing': {}}}, {'bindings': {'finish': 'unknown'}},
                       {'implementations': {'initialize': {'default': {'lifecycle': {}}}}},
                       {'implementations': {'initialize': {'default': {'kind': 'command'}}}}):
            with self.assertRaises(Invalid): apply(doc, config)
        old = read(self.store, self.key)
        self.save({'inputs': {'dataset': 'changed'}})
        with self.assertRaises(Conflict): write(self.store, self.key, {}, old['revision'])

    def test_direct_start_and_read_only_smoke_use_the_same_execution_configuration(self):
        config = {'inputs': {'service_url': 'receiver'}, 'implementations': {'initialize': {'default': {'command': [sys.executable, '-c', 'print(1)'], 'cwd': str(self.root)}}}}
        self.save(config)
        started = self.store.create(self.key, 'configured start')
        self.assertEqual(started['inputs']['service_url'], 'receiver')
        self.assertEqual(started['implementations']['initialize']['cwd'], str(self.root))
        doc, root = load_installed(self.store.filename, self.key)
        report = smoke(doc, root, configuration=config)
        self.assertTrue(next(c for c in report['checks'] if c['kind'] == 'manifest')['status'] == 'pass')
        self.assertTrue(any(c['kind'] == 'cwd' and c['target'] == str(self.root) for c in report['checks']))
        tools = PlatformTools(self.store)
        names = {d['name'] for d in tools.definitions()}
        self.assertTrue({'read_loop_config', 'set_loop_config'} <= names)
        draft = tools.call('create_loop', {'name': 'Config template'})
        result = tools.call('read_loop_config', {'draft_id': draft['draft_id']})
        self.assertEqual(result['path'], TEMPLATE)
        self.assertFalse(result['exists'])
        self.assertEqual(result['config']['implementations'], {})

    def test_custom_template_and_old_archive_without_a_template_remain_usable(self):
        custom = dict(assets(), **{TEMPLATE: (json.dumps({'inputs': {'service_url': 'template.example'}}).encode(), False)})
        key = install(self.store, make_archive(self.doc, custom))['key']
        self.assertEqual(self.store.create(key, 'from template')['inputs']['service_url'], 'template.example')
        # A genuine old package has neither a configuration asset nor a recipient file.
        import io, zipfile
        doc, original, _, _ = read_archive(self.raw)
        doc['files'].pop(TEMPLATE); original.pop(TEMPLATE)
        from loop_anything.packaging.packages import json_bytes
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as archive:
            archive.writestr('loop.json', json_bytes(doc))
            for name, (raw, _) in original.items(): archive.writestr(name, raw)
        old = install(self.store, out.getvalue())
        Path(old['config_path']).unlink()
        self.assertEqual(self.store.create(old['key'], 'legacy')['inputs']['service_url'], 'author.example')

    def test_configured_script_actually_receives_mapped_inputs_and_json_errors_can_be_repaired(self):
        doc = document()
        doc['loop_definition']['defaults'] = {'service_url': 'original'}
        doc['loop_definition']['nodes']['initialize']['inputs'] = {'service': {'type': 'string'}}
        doc['loop_definition']['seed']['inputs'] = {'service': {'run': 'service_url'}}
        key = install(self.store, make_archive(doc, assets()))['key']
        saved = read(self.store, key)
        Path(saved['path']).write_text('{broken JSON')
        damaged = read(self.store, key)
        self.assertIn('error', damaged)
        command = [sys.executable, '-c', 'import sys,json; x=json.load(sys.stdin); print(json.dumps({"settings":{"objective":"config input"},"outputs":{"result":x["inputs"]["service"]}}))']
        config = {'inputs': {'service_url': 'receiver'}, 'implementations': {'initialize': {'default': {'command': command}}}}
        write(self.store, key, config, damaged['revision'])
        run = self.store.create(key, 'real script')
        write(self.store, key, {'inputs': {'service_url': 'next'}}, read(self.store, key)['revision'])
        engine = Engine(self.store); self.addCleanup(engine.close)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            engine.tick(run['id'])
            loaded = self.store.get(run['id'])
            if loaded['tasks']['first']['status'] in ('completed', 'fault'): break
            time.sleep(.02)
        self.assertEqual(loaded['tasks']['first']['status'], 'completed', str([(e.get('error'), e.get('result'), e.get('log')) for e in loaded['executions']]))
        self.assertEqual(loaded['records']['result'][-1]['value'], 'receiver')
        self.assertEqual(loaded['executions'][0]['implementation']['command'], command)

    def test_builtin_flow_agent_configuration_survives_loading_without_changing_the_package(self):
        doc = document()
        doc['loop_definition']['flow_agent'] = {'kind': 'agent', 'command': ['author-cli']}
        key = install(self.store, make_archive(doc, assets()))['key']
        saved = read(self.store, key)
        write(self.store, key, {'flow_agent': {'command': ['recipient-cli'], 'cwd': str(self.root)}}, saved['revision'])
        run = self.store.create(key, 'flow config')
        loaded = self.store.get(run['id'])
        self.assertEqual(loaded['implementations']['$flow_agent']['command'], ['recipient-cli'])
        self.assertEqual(loaded['implementations']['$flow_agent']['cwd'], str(self.root))
        self.assertEqual(load_installed(self.store.filename, key)[0]['loop_definition']['flow_agent']['command'], ['author-cli'])
