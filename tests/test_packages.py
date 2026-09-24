"""Portable Loop handoff without real Agent/model calls or environment repair."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from loop_anything.runtime.timeline_model import validate_v2
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.packaging.packages import (FORMAT, make_archive, read_archive, collect_assets,
                                 install, load_installed, smoke, installed_assets, json_bytes)
from loop_anything.runtime.store import Store


HANDLER = b'''import json,sys
request=json.load(sys.stdin)
if sys.argv[1]=='initialize':
    print(json.dumps({'settings':{'objective':'Portable loop','completion_rule':{'op': 'and', 'args': [{'op': 'ge', 'args': [{'path': ['completed', 'finish']}, 1]}, {'op': 'eq', 'args': [{'path': 'active_tasks'}, 0]}]}},'outputs':{'result':'portable'},'tasks':[{'id':'last','node':'finish','inputs':{'value':{'record':'result'}},'outputs':{'done':{'id':'done'}}}]}))
else:
    print(json.dumps({'outputs':{'done':request['inputs']['value']=='portable'}}))
'''


def document():
    bp = {'schema_version': 2, 'id': 'portable', 'version': '1', 'name': 'Portable loop', 'entry': 'initialize',
          'handbook': {'instructions': 'Initialize intent, write result, finish after result.'},
          'records': {'text': {'type': 'string'}, 'flag': {'type': 'boolean'}},
          'nodes': {'initialize': {'instructions': 'Initialize', 'initialize_timeline': True, 'plan_nodes': ['finish'],
                       'inputs': {}, 'outputs': {'result': {'record_type': 'text'}}},
                    'finish': {'instructions': 'Finish',
                       'inputs': {'value': {'type': 'string'}}, 'outputs': {'done': {'record_type': 'flag'}}}},
          'seed': {'id': 'first', 'node': 'initialize', 'inputs': {}, 'outputs': {'result': {'id': 'result'}}},
          'plans': {}}
    return {'loop_definition': bp, 'implementations': {n: {'kind': 'command', 'command': ['python3', 'scripts/handler.py', n]} for n in bp['nodes']}}


def assets():
    return {'scripts/handler.py': (HANDLER, False)}


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.store = Store(self.root / 'target machine' / 'runs.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_format_supports_zero_partial_and_complete_implementations(self):
        keys = []
        for count in (0, 1, 2):
            doc = document()
            doc['implementations'] = dict(list(doc['implementations'].items())[:count])
            before = copy.deepcopy(doc)
            data = make_archive(doc, assets() if count else {})
            unpacked, _, key, _ = read_archive(data)
            self.assertEqual(FORMAT, unpacked['format'])
            self.assertEqual(doc['implementations'], unpacked['implementations'])
            result = install(self.store, data)
            self.assertEqual(2 - count, len(result['unbound_nodes']))
            self.assertFalse(result['started'])
            self.assertEqual(before, doc)
            loaded, root = load_installed(self.store.filename, key)
            self.assertEqual(count == 2, smoke(loaded, root)['ready'])
            self.assertTrue(smoke(loaded, root)['startable'])
            run = self.store.create(key, 'Optional implementations')
            self.assertEqual('running', run['status'])
            keys.append(key)
        self.assertEqual(3, len(set(keys)))  # Implementation variants do not overwrite a loop_definition version.
        self.assertEqual(3, len(self.store.catalog()))

    def test_definition_missing_implementations_is_valid_but_malformed_implementation_is_not(self):
        doc = document()
        self.assertTrue(validate_v2(doc['loop_definition'], {})['valid'])
        self.assertTrue(validate_v2(doc['loop_definition'], {})['valid'])
        from loop_anything.runtime.lifecycle import template
        personal=document();matrix=template('agent');matrix['transitions'][1]['notify']=[{'message':'done','route':'my-private-chat'}]
        personal['implementations']['initialize']['lifecycle']=matrix
        with self.assertRaises(Invalid):make_archive(personal,assets())
        matrix['transitions'][1]['notify'][0]['route']='default'
        self.assertTrue(make_archive(personal,assets()))
        for implementation in (None, {'options': []}, {'kind': 'command', 'command': 'wrong'}):
            self.assertFalse(validate_v2(doc['loop_definition'], {'finish': implementation})['valid'])
        doc.pop('implementations')
        self.assertEqual({}, read_archive(make_archive(doc))[0]['implementations'])

    def test_complete_package_runs_in_new_directory_without_source_project(self):
        source = self.root / 'author project'
        (source / 'scripts').mkdir(parents=True)
        script = source / 'scripts/handler.py'
        script.write_bytes(HANDLER)
        data = make_archive(document(), collect_assets(source, ['scripts']))
        script.unlink()  # Remove generated fixture source: only installed assets remain.
        installed = install(self.store, data)
        run_id = self.store.create(installed['key'], 'Transferred')['id']
        runtime = Engine(self.store)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                runtime.tick(run_id)
                run = self.store.get(run_id)
                if any(e['status'] == 'fault' for e in run['executions']):
                    self.fail(str(run['executions']))
                if run['status'] == 'completed':
                    break
                time.sleep(.02)
            self.assertEqual('completed', run['status'])
            self.assertTrue(run['records']['done'][-1]['value'])
            self.assertEqual(2, len(run['executions']))
            self.assertEqual(['python3', 'scripts/handler.py', 'initialize'], run['implementations']['initialize']['command'])
        finally:
            runtime.close()

    def test_smoke_is_read_only_does_not_execute_or_repair(self):
        doc = document()
        doc['implementations']['initialize']['command'] = ['/missing/original/python', '/missing/original/handler.py']
        doc['implementations']['finish']['cwd'] = '/missing/original/workdir'
        doc['checks'] = {'paths': ['/missing/original/data'], 'env': ['STATELOOP_TEST_REQUIRED'], 'programs': ['missing-loop-program']}
        result = install(self.store, make_archive(doc, assets()))
        loaded, root = load_installed(self.store.filename, result['key'])
        before = snapshot(root)
        original = copy.deepcopy(loaded)
        with patch('subprocess.run', side_effect=AssertionError('smoke must never execute')), patch.dict(os.environ, {'STATELOOP_TEST_REQUIRED': 'private-test-value'}):
            report = smoke(loaded, root)
        self.assertFalse(report['ready'])
        self.assertNotIn('private-test-value', json.dumps(report))
        self.assertEqual(before, snapshot(root))
        self.assertEqual(original, loaded)
        self.assertEqual(doc['implementations'], loaded['implementations'])
        self.assertEqual([], self.store.list())

    def test_pack_and_smoke_do_not_create_a_database_or_missing_directories(self):
        source = self.root / 'definition.json'
        source.write_text(json.dumps({'loop_definition': document()['loop_definition']}))
        package = self.root / 'pure.loop.zip'
        db = self.root / 'must-not-exist' / 'state.sqlite3'
        command = [sys.executable, '-m', 'loop_anything', '--db', str(db)]
        result = subprocess.run(command + ['pack', str(source), '--output', str(package)], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(db.parent.exists())
        result = subprocess.run(command + ['smoke', 'unknown'], capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(db.parent.exists())

    def test_install_idempotent_and_original_implementations_survive_reexport(self):
        data = make_archive(document(), assets())
        first = install(self.store, data)
        self.assertEqual(first, install(self.store, data))
        loaded, root = load_installed(self.store.filename, first['key'])
        self.assertEqual(document()['implementations'], loaded['implementations'])
        self.assertEqual(data, make_archive(loaded, installed_assets(loaded, root)))
        self.assertEqual(1, len(self.store.catalog()))

    def test_repack_does_not_silently_drop_declared_assets(self):
        manifest = read_archive(make_archive(document(), assets()))[0]
        with self.assertRaises(Invalid):
            make_archive(manifest)

    def test_changed_installed_files_block_run_and_reinstall_does_not_repair(self):
        data = make_archive(document(), assets())
        info = install(self.store, data)
        script = Path(info['root']) / 'scripts/handler.py'
        script.write_text('changed by fixture')
        with self.assertRaises(Invalid):
            self.store.create(info['key'], 'Must refuse')
        with self.assertRaises(Conflict):
            install(self.store, data)
        self.assertEqual('changed by fixture', script.read_text())
        self.assertEqual([], self.store.list())

    def test_bad_paths_symlinks_and_private_paths_are_rejected(self):
        for name in ('../escape', '/absolute', 'a/../b', 'C:/bad', 'a\\b', '.env', '.codex/auth.json', 'loop.json'):
            with self.subTest(name=name), self.assertRaises(Invalid):
                make_archive(document(), {name: (b'x', False)})
        source = self.root / 'source'
        source.mkdir()
        (source / 'target').write_text('fixture')
        (source / 'alias').symlink_to(source / 'target')
        with self.assertRaises(Invalid):
            collect_assets(source, ['alias'])

    def test_file_directory_and_case_collisions_rejected(self):
        for contents in ({'a': (b'x', False), 'a/b': (b'y', False)}, {'A': (b'x', False), 'a': (b'y', False)}):
            with self.assertRaises(Invalid):
                make_archive(document(), contents)

    def test_zip_traversal_symlink_undeclared_member_and_checksum_rejected(self):
        manifest = read_archive(make_archive(document(), assets()))[0]
        for kind in ('traversal', 'symlink', 'undeclared', 'checksum'):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr('loop.json', json_bytes(manifest))
                archive.writestr('scripts/handler.py', b'tampered' if kind == 'checksum' else HANDLER)
                if kind == 'traversal':
                    archive.writestr('../outside', b'bad')
                if kind == 'undeclared':
                    archive.writestr('extra', b'bad')
                if kind == 'symlink':
                    info = zipfile.ZipInfo('link')
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, '../outside')
            with self.subTest(kind=kind), self.assertRaises(Invalid):
                install(self.store, stream.getvalue())
        self.assertEqual([], self.store.catalog())
        self.assertFalse((self.root / 'target machine/packages').exists())

    def test_draft_roundtrip_retains_selected_assets_and_smoke_declarations(self):
        doc = document()
        selected = [{'path': 'scripts/handler.py', 'base64': base64.b64encode(HANDLER).decode(), 'executable': False}]
        result = self.store.save_draft(doc['loop_definition'], {}, assets=selected, checks={'env': ['TOKEN_NAME']})
        restored = self.store.drafts()[0]
        self.assertEqual(selected, restored['assets'])
        self.assertEqual(result['checks'], restored['checks'])
        self.assertEqual({}, restored['implementations'])

    def test_cli_install_and_smoke_partial_package(self):
        doc = document()
        doc['implementations'].pop('finish')
        file = self.root / 'partial.loop.zip'
        file.write_bytes(make_archive(doc, assets()))
        command = [sys.executable, '-m', 'loop_anything', '--db', self.store.filename]
        installed = subprocess.run(command + ['install', str(file)], capture_output=True, text=True)
        self.assertEqual(0, installed.returncode, installed.stderr)
        result = json.loads(installed.stdout)
        checked = subprocess.run(command + ['smoke', result['key']], capture_output=True, text=True)
        self.assertEqual(2, checked.returncode, checked.stderr)
        self.assertEqual(['finish'], json.loads(checked.stdout)['unbound_nodes'])
        self.assertFalse(result['started'])

    def test_changed_manifest_blocks_run_without_repair(self):
        result = install(self.store, make_archive(document(), assets()))
        file = Path(result['root']) / 'loop.json'
        file.write_text('{"changed":true}')
        doc, root = load_installed(self.store.filename, result['key'])
        self.assertFalse(smoke(doc, root)['ready'])
        with self.assertRaises(Invalid):
            self.store.create(result['key'], 'Blocked')
        self.assertEqual('{"changed":true}', file.read_text())

    def test_dangling_install_symlink_is_not_overwritten(self):
        data = make_archive(document(), assets())
        _, _, _, fingerprint = read_archive(data)
        parent = Path(self.store.filename).parent / 'packages'
        parent.mkdir()
        root = parent / fingerprint
        root.symlink_to(self.root / 'absent-target', target_is_directory=True)
        with self.assertRaises(Conflict):
            install(self.store, data)
        self.assertTrue(root.is_symlink())
        self.assertFalse((self.root / 'absent-target').exists())

    def test_smoke_resolves_relative_path_lookup_in_declared_cwd(self):
        doc = document()
        doc['implementations']['initialize'] = {'kind': 'command', 'command': ['local-handler']}
        content = assets()
        content['bin/local-handler'] = (b'#!/bin/sh\nexit 0\n', True)
        result = install(self.store, make_archive(doc, content))
        loaded, root = load_installed(self.store.filename, result['key'])
        with patch.dict(os.environ, {'PATH': 'bin'}):
            report = smoke(loaded, root)
        local = next(c for c in report['checks'] if c['kind'] == 'executable' and c['node'] == 'initialize')
        self.assertEqual('pass', local['status'])

    def test_nonfinite_implementation_timeout_rejected_at_pack(self):
        doc = document()
        doc['implementations']['initialize']['timeout'] = float('nan')
        with self.assertRaises(Invalid):
            make_archive(doc, assets())
        from loop_anything.runtime.lifecycle import template
        personal=document();matrix=template('agent');matrix['transitions'][1]['notify']=[{'message':'done','route':'my-private-chat'}]
        personal['implementations']['initialize']['lifecycle']=matrix
        with self.assertRaises(Invalid):make_archive(personal,assets())
        matrix['transitions'][1]['notify'][0]['route']='default'
        self.assertTrue(make_archive(personal,assets()))
        for implementation in (None, {'command': ['bad\x00command']}, {'kind':'command','command':['sender','private-recipient']}):
            bad = document()
            bad['implementations']['$notifications'] = implementation
            with self.assertRaises(Invalid):
                make_archive(bad, assets())


if __name__ == '__main__':
    unittest.main()
