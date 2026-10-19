"""The renderer ships with the Skill and saves through ordinary versioned assets."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from loop_anything.packaging.skill_bundle import bundle

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/loop-anything-platform/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('flow_renderer', SCRIPTS / 'render_flow.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
sys.path.remove(str(SCRIPTS))


class FlowDiagramTests(unittest.TestCase):
    def test_exported_skill_can_render_offline_and_revision_conflicts_stop_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with zipfile.ZipFile(io.BytesIO(bundle('http://localhost:8769'))) as archive:
                prefix = 'platform/loop-anything-platform/'
                for name in ('scripts/render_flow.py', 'scripts/vendor/answer-me-with-html/am.mjs',
                             'scripts/vendor/answer-me-with-html/LICENSE.txt', 'assets/flow.md',
                             'references/flow-diagram.md'):
                    self.assertIn(prefix + name, archive.namelist())
            source = SCRIPTS.parent / 'assets/flow.md'
            output = root / 'flow.html'
            renderer.render(source, output)
            self.assertIn('<svg', output.read_text())
            self.assertIn('制定方案', output.read_text())
            writes = []
            def accept(url, data):
                args = json.loads(data)['arguments']; writes.append(args)
                return {'ok': True, 'revision': args['revision'] + 1}
            with patch.object(renderer, 'fetch', side_effect=accept):
                self.assertEqual(renderer.upload(source, output, 'draft-a', 7, 'http://localhost:8769'), 9)
            self.assertEqual([(w['path'], w['revision']) for w in writes], [('docs/flow.md', 7), ('docs/flow.html', 8)])
            self.assertEqual(writes[1]['content'], output.read_text())
            with patch.object(renderer, 'fetch', return_value={'ok': False, 'error': 'conflict'}) as rejected:
                with self.assertRaisesRegex(ValueError, 'docs/flow.md'):
                    renderer.upload(source, output, 'draft-a', 7, 'http://localhost:8769')
                self.assertEqual(rejected.call_count, 1)
