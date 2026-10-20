import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loop_anything.runtime.model import Invalid
from loop_anything.paths import default_database
from loop_anything.packaging.skill_bundle import bundle, install_skills
from loop_anything.runtime.store import Store


class InstallationTests(unittest.TestCase):
    def test_default_database_is_absolute_and_independent_of_working_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch('loop_anything.paths.Path.home', return_value=Path(folder)):
            for system in ('darwin', 'win32', 'linux'):
                with patch('loop_anything.paths.sys.platform', system), patch.dict(os.environ, {'LOCALAPPDATA': folder, 'XDG_DATA_HOME': 'relative-is-ignored'}):
                    first = default_database()
                    previous = Path.cwd()
                    try:
                        os.chdir(folder)
                        self.assertEqual(first, default_database())
                        self.assertTrue(first.is_absolute())
                    finally:
                        os.chdir(previous)

    def test_skill_install_conflict_is_explicit_and_update_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'runs.db')
            directory = Path(folder) / 'skills'
            install_skills(bundle('http://127.0.0.1:8767'), directory)
            extra = directory / 'loop-anything-platform' / 'personal.txt'
            extra.write_text('keep')
            updated = bundle('http://127.0.0.1:9876')
            with self.assertRaises(Invalid):
                install_skills(updated, directory)
            connection = directory / 'loop-anything-platform' / 'connection.json'
            self.assertEqual('http://127.0.0.1:8767', json.loads(connection.read_text())['url'])
            install_skills(updated, directory, replace=True)
            self.assertEqual('http://127.0.0.1:9876', json.loads(connection.read_text())['url'])
            self.assertEqual('keep', extra.read_text())

    def test_service_configuration_keeps_workspace_and_rejects_a_busy_port(self):
        import plistlib
        import socket
        from loop_anything.runtime.service import definition, available, option
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'existing workspace.db'
            store = Store(database)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); listener.listen()
                port = listener.getsockname()[1]
                config = definition('/application with spaces/venv/bin/python', database, port, '127.0.0.1')
                config['EnvironmentVariables']['CUSTOM_PLATFORM_ENV'] = 'shared'
                config = plistlib.loads(plistlib.dumps(config))
                with patch.dict(os.environ, {}, clear=True):
                    upgraded = definition('/application with spaces/venv/bin/python', previous=config)
                self.assertEqual(str(database.resolve()), option(upgraded, '--db', None))
                self.assertEqual(str(port), option(upgraded, '--port', None))
                self.assertEqual('shared', upgraded['EnvironmentVariables']['CUSTOM_PLATFORM_ENV'])
                before = database.read_bytes()
                with self.assertRaises(Invalid):
                    available(upgraded)
                self.assertEqual(before, database.read_bytes())
            available(upgraded)

    def test_upgrade_preserves_existing_interpreter_when_installer_uses_another_python(self):
        import install as installer
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            prefix=Path(folder)/'app';environment=prefix/'venv';(environment/'bin').mkdir(parents=True)
            config=environment/'pyvenv.cfg';config.write_text('home = /another/python\nversion = 3.10.20\n')
            executable=environment/'bin/python';executable.write_bytes(b'original interpreter')
            wheel=Path(folder)/'local.whl';wheel.write_bytes(b'local package supplied by test')
            calls=[]
            def run(argv,**kwargs):calls.append(argv);return subprocess.CompletedProcess(argv,0)
            with patch.object(installer.sys,'argv',['install.py','--prefix',str(prefix),'--package',str(wheel),'--no-service']), \
                 patch.object(installer.subprocess,'run',side_effect=run), \
                 patch.object(installer.venv.EnvBuilder,'create',side_effect=AssertionError('Must preserve existing venv')), \
                 patch('builtins.print'):
                installer.main()
            self.assertEqual(executable.read_bytes(),b'original interpreter')
            self.assertIn('/another/python',config.read_text())
            self.assertTrue(all(Path(argv[0]).resolve()==executable.resolve() for argv in calls))
            self.assertTrue(any('pip' in argv and str(wheel.resolve()) in argv for argv in calls))
