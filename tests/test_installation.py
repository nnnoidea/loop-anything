import json
import os
import subprocess
import plistlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loop_anything.runtime.model import Invalid
from loop_anything.paths import default_database
from loop_anything.packaging.skill_bundle import bundle, install_skills
from loop_anything.runtime.store import Store


class InstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.personal = Path(temporary.name) / 'spaces.json'
        env = patch.dict(os.environ, LOOP_ANYTHING_SPACES=str(self.personal))
        env.start()
        self.addCleanup(env.stop)

    def test_client_rejects_database_option_without_opening_a_store(self):
        from loop_anything.__main__ import main
        with patch('sys.argv',['loop-anything','--db','unused.sqlite3','client']), \
             patch('loop_anything.runtime.store.Store',side_effect=AssertionError('Client must not open a Store')), \
             patch('sys.stderr'), self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code,2)

    def test_installer_rejects_removed_installation_modes(self):
        import install as installer
        for flags in (['--role','client'],['--role','server'],['--space','team'],['--no-service'],['--host','0.0.0.0']):
            with self.subTest(flags=flags), patch.object(installer.sys,'argv',['install.py',*flags]),patch.object(installer.subprocess,'run') as run,patch('sys.stderr'):
                with self.assertRaises(SystemExit) as error:installer.main()
                self.assertEqual(error.exception.code,2);run.assert_not_called()

    def test_foreground_installers_always_create_the_full_local_launcher(self):
        import install as installer
        for system in ('linux','win32'):
            with self.subTest(system=system),tempfile.TemporaryDirectory() as folder:
                prefix=Path(folder).resolve()/'app';environment=prefix/'venv';environment.mkdir(parents=True)
                (environment/'pyvenv.cfg').write_text('version = 3.9\n')
                wheel=Path(folder)/'local.whl';wheel.write_bytes(b'test package')
                with patch.object(installer.sys,'argv',['install.py','--prefix',str(prefix),'--package',str(wheel)]),patch.object(installer.sys,'platform',system),patch.object(installer.subprocess,'run') as run,patch('loop_anything.runtime.service.configuration',side_effect=AssertionError('Foreground installation does not read macOS service configuration')),patch.object(installer,'register',return_value={'command':'test-bin/loop-anything','current_terminal':'test activation'}),patch('builtins.print'):
                    installer.main()
                launcher=prefix/('Loop Anything.cmd' if system=='win32' else 'loop-anything')
                text=launcher.read_text();self.assertIn('serve',text);self.assertIn('--space local',text);self.assertNotIn('client --help',text)
                calls=[call.args[0] for call in run.call_args_list]
                self.assertEqual(json.loads(self.personal.read_text())['local_url'], 'http://127.0.0.1:8767')
                self.assertFalse(any('service' in args for args in calls))

    def test_upgrade_keeps_saved_workspace_port_and_hosting_mode(self):
        import install as installer
        from loop_anything.runtime.service import definition
        for mode,host in (('local','127.0.0.1'),('team','0.0.0.0')):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                prefix=Path(folder).resolve()/'app';environment=prefix/'venv';(environment/'bin').mkdir(parents=True)
                (environment/'pyvenv.cfg').write_text('version = 3.9\n')
                wheel=Path(folder)/'local.whl';wheel.write_bytes(b'test')
                previous=definition(environment/'bin/python',Path(folder)/'existing.db',9876,host,space=mode)
                plist = Path(folder) / 'service.plist'; plist.write_bytes(plistlib.dumps(previous))
                self.personal.unlink(missing_ok=True)
                with patch('loop_anything.runtime.service.service_file',return_value=plist),patch('loop_anything.runtime.service.launchctl',return_value=subprocess.CompletedProcess([],0)),patch.object(installer.sys,'argv',['install.py','--prefix',str(prefix),'--package',str(wheel)]),patch.object(installer.sys,'platform','darwin'),patch.object(installer.subprocess,'run') as run,patch('loop_anything.runtime.service.configuration',return_value=previous),patch('loop_anything.runtime.service.manage') as manage,patch('loop_anything.runtime.service.available') as available,patch.object(installer,'register',return_value={'command':'test','current_terminal':'test'}),patch('builtins.print'):
                    installer.main()
                manage.assert_called_once_with('stop')
                self.assertEqual(available.call_args.args[0]['ProgramArguments'],previous['ProgramArguments'])
                calls=[call.args[0] for call in run.call_args_list]
                service=next(args for args in calls if 'service' in args)
                self.assertEqual(service[-4:],['service','install','--port','9876'])
                if mode=='local':
                    saved=json.loads(self.personal.read_text())
                    self.assertEqual(saved['local_url'],'http://127.0.0.1:9876')
                    self.assertEqual(saved['local_registry'],str((Path(folder)/'existing.db').resolve())+'.schedules')
                else:self.assertFalse(self.personal.exists())

    def test_local_skill_export_needs_no_platform_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            result=install_skills(bundle('unused',only='local'),folder)
            self.assertEqual(result['skills'],['loop-anything-local'])
            self.assertFalse((Path(folder)/'loop-anything-platform').exists())
            self.assertEqual(result['check'][-2:],['local','--help'])

    def test_build_identity_includes_portable_runtime_code(self):
        from loop_anything.capabilities import _source_build
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);scripts=root/'loop-anything-dispatch/scripts';scripts.mkdir(parents=True)
            source=scripts/'team_transport.py';source.write_text('VERSION=1')
            with patch('loop_anything.paths.platform_skill_directory',return_value=root/'loop-anything-platform'):
                before=_source_build()
                source.write_text('VERSION=2')
                self.assertNotEqual(before,_source_build())

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
            connection = directory / 'loop-anything-platform' / 'platform-source.json'
            self.assertEqual('http://127.0.0.1:8767', json.loads(connection.read_text())['platform_url'])
            install_skills(updated, directory, replace=True)
            self.assertEqual('http://127.0.0.1:9876', json.loads(connection.read_text())['platform_url'])
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
            prefix=Path(folder).resolve()/'app';environment=prefix/'venv';(environment/'bin').mkdir(parents=True)
            config=environment/'pyvenv.cfg';config.write_text('home = /another/python\nversion = 3.10.20\n')
            executable=environment/'bin/python';executable.write_bytes(b'original interpreter')
            wheel=Path(folder)/'local.whl';wheel.write_bytes(b'local package supplied by test')
            calls=[]
            def run(argv,**kwargs):calls.append(argv);return subprocess.CompletedProcess(argv,0)
            with patch.object(installer.sys,'argv',['install.py','--prefix',str(prefix),'--package',str(wheel)]), \
                 patch.object(installer.sys,'platform','linux'),patch.object(installer.subprocess,'run',side_effect=run), \
                 patch.object(installer.venv.EnvBuilder,'create',side_effect=AssertionError('Must preserve existing venv')), \
                 patch.object(installer,'register',return_value={'command':'test-bin/loop-anything','current_terminal':'test activation'}), \
                 patch('builtins.print'):
                installer.main()
            self.assertEqual(executable.read_bytes(),b'original interpreter')
            self.assertIn('/another/python',config.read_text())
            self.assertTrue(all(Path(argv[0]).resolve()==executable.resolve() for argv in calls))
            self.assertTrue(any('pip' in argv and str(wheel.resolve()) in argv for argv in calls))

    def test_reinstall_preserves_personal_tasks_and_foreground_workspace(self):
        import install as installer
        from loop_anything.runtime.tool_client import module
        from loop_anything.runtime.local_tasks import TaskRegistry
        spaces=module('spaces')
        for system in ('linux','win32'):
            with self.subTest(system=system),tempfile.TemporaryDirectory() as folder:
                prefix=Path(folder).resolve();env=prefix/'venv';env.mkdir();(env/'pyvenv.cfg').write_text('version=3.9')
                wheel=prefix/'package.whl';wheel.write_bytes(b'mocked')
                registry=prefix/'personal-tasks';TaskRegistry(registry).register({'name':'Existing','every':3600,'command':['unused']},'existing')
                spaces.configure({'local_url':'http://127.0.0.1:9876','local_registry':str(registry),'team_url':'https://team.example','default_space':'local'})
                before=spaces.read()
                launcher=prefix/('Loop Anything.cmd' if system=='win32' else 'loop-anything')
                # Its saved database need not be inferred from the independent registry.
                command='custom-python --db "original workspace.db" serve --port 9876 --space local\n'
                launcher.write_text(command)
                with patch.object(installer.sys,'argv',['install.py','--prefix',str(prefix),'--package',str(wheel)]),patch.object(installer.sys,'platform',system),patch.object(installer.subprocess,'run'),patch.object(installer,'register',return_value={'command':'test','current_terminal':'test'}),patch('builtins.print'):
                    installer.main()
                self.assertEqual(spaces.read(),before)
                self.assertEqual(launcher.read_text(),command)
                self.assertEqual([row['id'] for row in TaskRegistry(spaces.read()['local_registry']).list()],['existing'])
                self.assertEqual(TaskRegistry(registry).show('existing')['runtime']['status'],'registered')

    def test_optional_team_settings_and_port_preserve_existing_workspace(self):
        import install as installer
        from loop_anything.runtime.tool_client import module
        for system in ('linux','win32'):
            with self.subTest(system=system),tempfile.TemporaryDirectory() as folder:
                prefix=Path(folder).resolve();env=prefix/'venv';env.mkdir();(env/'pyvenv.cfg').write_text('version=3.9')
                wheel=prefix/'package.whl';wheel.write_bytes(b'mocked')
                launcher=prefix/('Loop Anything.cmd' if system=='win32' else 'loop-anything')
                launcher.write_text('python --db "original workspace.db" serve --port 9876 --space local\n')
                with patch.object(installer.sys,'argv',['install.py','--prefix',str(prefix),'--package',str(wheel),'--team-url','nas:///mounted/team','--team-web-url','https://team.example','--default-space','team','--port','9877']),patch.object(installer.sys,'platform',system),patch.object(installer.subprocess,'run'),patch.object(installer,'register',return_value={'command':'test','current_terminal':'test'}),patch('builtins.print'):
                    installer.main()
                config=module('spaces').read()
                self.assertEqual(config['team_url'],'nas:///mounted/team');self.assertEqual(config['team_web_url'],'https://team.example')
                self.assertEqual(config['default_space'],'team');self.assertEqual(config['local_url'],'http://127.0.0.1:9877')
                self.assertIn('--db "original workspace.db" serve --port 9877',launcher.read_text())

    def test_mac_failures_restore_program_plist_and_previous_running_state(self):
        import install as installer
        from loop_anything.runtime.service import definition
        for failure in ('availability','pip','startup'):
            for loaded in (True,False):
                with self.subTest(failure=failure,loaded=loaded),tempfile.TemporaryDirectory() as folder:
                    prefix=Path(folder).resolve();environment=prefix/'venv';environment.mkdir();(environment/'pyvenv.cfg').write_text('version=3.9')
                    package=environment/'program.py';package.write_text('known good')
                    wheel=prefix/'package.whl';wheel.write_bytes(b'mocked')
                    previous=definition(environment/'bin/python',prefix/'original.db',9876,'127.0.0.1')
                    plist=prefix/'service.plist';saved=plistlib.dumps(previous);plist.write_bytes(saved)
                    launcher=prefix/'Loop Anything.command';launcher.write_text('original launcher')
                    state={'running':loaded};events=[]
                    def manage(action):
                        events.append(action)
                        if action=='start':
                            self.assertEqual(package.read_text(),'known good');self.assertEqual(plist.read_bytes(),saved)
                            self.assertEqual(launcher.read_text(),'original launcher')
                        state['running']=action=='start'
                    def available(config):
                        if failure=='availability':raise Invalid('occupied')
                    def run(argv,**kwargs):
                        if 'pip' in argv:
                            package.write_text('partly installed')
                            if failure=='pip':raise subprocess.CalledProcessError(1,argv)
                        if 'service' in argv:
                            plist.write_bytes(b'new config');state['running']=True
                            raise subprocess.CalledProcessError(1,argv)
                        return subprocess.CompletedProcess(argv,0)
                    with patch.object(installer.sys,'argv',['install.py','--prefix',str(prefix),'--package',str(wheel)]),patch.object(installer.sys,'platform','darwin'),patch.object(installer.subprocess,'run',side_effect=run),patch('loop_anything.runtime.service.service_file',return_value=plist),patch('loop_anything.runtime.service.configuration',return_value=previous),patch('loop_anything.runtime.service.launchctl',return_value=subprocess.CompletedProcess([],0 if loaded else 1)),patch('loop_anything.runtime.service.manage',side_effect=manage),patch('loop_anything.runtime.service.available',side_effect=available),patch.object(installer,'register',return_value={'command':'test','current_terminal':'test'}),patch('builtins.print'):
                        with self.assertRaises((Invalid,subprocess.CalledProcessError)):installer.main()
                    self.assertEqual(state['running'],loaded)
                    self.assertEqual(package.read_text(),'known good');self.assertEqual(plist.read_bytes(),saved)
                    self.assertEqual(launcher.read_text(),'original launcher')
                    self.assertEqual(events,['stop','stop']+(['start'] if loaded else []))

    def test_invalid_personal_settings_do_not_stop_or_install(self):
        import install as installer
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(installer.sys,'argv',['install.py','--prefix',folder,'--default-space','team']),patch.object(installer.sys,'platform','darwin'),patch('loop_anything.runtime.service.configuration',return_value=None),patch.object(installer.subprocess,'run') as run,patch('loop_anything.runtime.service.manage') as manage:
                with self.assertRaises(ValueError):installer.main()
            run.assert_not_called();manage.assert_not_called()

    def test_recovery_failure_keeps_known_good_files_and_reports_location(self):
        import install as installer
        with tempfile.TemporaryDirectory() as folder:
            prefix=Path(folder);environment=prefix/'venv';environment.mkdir();(environment/'program.py').write_text('known good')
            plist=prefix/'service.plist';plist.write_bytes(b'original plist')
            def manage(action):
                if action=='start':raise Invalid('simulated restart failure')
            with patch('loop_anything.runtime.service.service_file',return_value=plist),patch('loop_anything.runtime.service.launchctl',return_value=subprocess.CompletedProcess([],0)),patch('loop_anything.runtime.service.manage',side_effect=manage):
                with self.assertRaisesRegex(RuntimeError,'Original environment saved at') as error:
                    with installer.recover_service(environment,{'installed':True}):
                        (environment/'program.py').write_text('broken');raise ValueError('install failure')
            backup=next(prefix.glob('recovery-*'))
            self.assertIn(str(backup),str(error.exception))
            self.assertEqual((backup/'venv/program.py').read_text(),'known good')
            self.assertEqual((backup/'service.plist').read_bytes(),b'original plist')

    def test_first_mac_install_can_choose_an_available_port(self):
        import install as installer
        from loop_anything.runtime.service import option
        with tempfile.TemporaryDirectory() as folder:
            prefix=Path(folder).resolve();env=prefix/'venv';env.mkdir();(env/'pyvenv.cfg').write_text('version=3.9')
            wheel=prefix/'package.whl';wheel.write_bytes(b'mocked')
            def available(config):
                self.assertEqual(option(config,'--port',None),'8876')
            with patch.object(installer.sys,'argv',['install.py','--prefix',str(prefix),'--package',str(wheel),'--port','8876']),patch.object(installer.sys,'platform','darwin'),patch.object(installer.subprocess,'run') as run,patch('loop_anything.runtime.service.configuration',return_value=None),patch('loop_anything.runtime.service.available',side_effect=available),patch.object(installer,'register',return_value={'command':'test','current_terminal':'test'}),patch('builtins.print'):
                installer.main()
            command=next(call.args[0] for call in run.call_args_list if 'service' in call.args[0])
            self.assertEqual(command[-2:],['--port','8876'])
            self.assertEqual(json.loads(self.personal.read_text())['local_url'],'http://127.0.0.1:8876')
