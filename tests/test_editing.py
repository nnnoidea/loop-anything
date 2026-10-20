"""Retired edit metadata never blocks work; normal version and scope checks remain."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from loop_anything.capabilities import discover, require_supported
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.packaging.packages import make_archive, read_archive, import_draft, install, load_installed, smoke
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime.store import Store
from test_run_agent import definition


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'workspace.db')
        self.tools = PlatformTools(self.store)
        self.bp, self.impl = definition()

    def legacy_package(self):
        raw = make_archive({'loop_definition': self.bp, 'implementations': self.impl},
                           {'notes.txt': (b'original instructions', False)})
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(output, 'w') as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == 'loop.json':
                    doc = json.loads(data)
                    doc['format'] = 'loop-anything-package/2'
                    doc['edit_protection'] = {'algorithm': 'pbkdf2-sha256', 'iterations': 210000,
                                              'salt': '01' * 16, 'digest': '02' * 32}
                    doc['requires'] = sorted(set(doc.get('requires', [])) | {'loop_edit_protection'})
                    doc['loop_definition']['requires'] = ['loop_edit_protection']
                    data = json.dumps(doc).encode()
                target.writestr(info, data)
        return output.getvalue()

    def test_old_database_passwords_are_inert_and_stale_revisions_still_conflict(self):
        # An existing workspace may retain the old table. The new Store never reads it.
        with self.store.connection() as db:
            db.execute('CREATE TABLE loop_edit_protection (loop_id TEXT PRIMARY KEY, document TEXT NOT NULL)')
            db.execute('INSERT INTO loop_edit_protection VALUES (?,?)', (self.bp['id'], json.dumps({'digest': 'old'})))
        draft = self.store.save_draft(self.bp, self.impl)
        change = {'draft_id': draft['id'], 'revision': draft['revision'], 'name': 'Edited directly'}
        self.assertTrue(self.tools.respond('set_loop', change)['ok'])
        with self.assertRaises(Conflict):self.tools.call('set_loop', change)
        self.assertNotIn('set_loop_password', {d['name'] for d in self.tools.definitions()})
        self.assertNotIn('loop_edit_protection', discover()['capabilities'])
        self.assertTrue(all('loop_password' not in d['inputSchema']['properties'] for d in self.tools.definitions()))
        self.assertNotIn('edit_protected', self.tools.call('read_loop', {'draft_id': draft['id']})['loop'])
        with self.assertRaises(Invalid):require_supported(['unknown_capability'])

    def test_legacy_package_can_install_copy_edit_and_reexport_without_protection(self):
        raw = self.legacy_package()
        installed = install(self.store, raw)
        self.assertEqual(install(self.store, raw)['key'], installed['key'])
        original, root = load_installed(self.store.filename, installed['key'])
        self.assertTrue(smoke(original, root)['package_valid'])
        self.assertIn('edit_protection', original)  # Immutable package history remains exact.
        draft = import_draft(self.store, raw)
        edited = self.tools.call('put_asset', {'draft_id': draft['id'], 'revision': draft['revision'],
                                             'path': 'notes.txt', 'content': 'updated instructions'})
        copied = self.tools.call('copy_loop', {'key': installed['key'], 'new_version': True})
        self.assertNotEqual(copied['revision'], 0)
        import base64
        exported = self.tools.call('export_loop', {'draft_id': edited['draft_id']})
        doc, assets, _, _ = read_archive(base64.b64decode(exported['base64']))
        self.assertNotIn('edit_protection', doc)
        self.assertNotIn('loop_edit_protection', doc.get('requires', []))
        self.assertNotIn('loop_edit_protection', doc['loop_definition'].get('requires', []))
        self.assertEqual(assets['notes.txt'][0], b'updated instructions')
