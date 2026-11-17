"""PATH registration remains idempotent, preserves shell config, and resolves in fresh shells."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from loop_anything.packaging.launcher import register, BEGIN


class LauncherTests(unittest.TestCase):
    def test_zsh_fresh_terminal_and_upgrade_with_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root)/'user';home.mkdir()
            profile=home/'.zshrc';profile.write_text('# personal settings\nexport CUSTOM_VALUE=keep\n')
            launcher=Path(root)/'程序 with spaces.command'
            launcher.write_text('#!/bin/sh\nprintf "%s\\n" "$1"\n');launcher.chmod(0o755)
            with patch('loop_anything.packaging.launcher.sys.platform','darwin'):
                result=register(launcher,home=home,environ={'SHELL':'/bin/zsh'})
                again=register(launcher,home=home,environ={'SHELL':'/bin/zsh'})
            self.assertEqual(result,again);self.assertEqual(profile.read_text().count(BEGIN),1)
            self.assertIn('CUSTOM_VALUE=keep',profile.read_text())
            env=dict(os.environ,ZDOTDIR=str(home),PATH='/usr/bin:/bin')
            shell=subprocess.run(['/bin/zsh','-d','-i','-c','command -v loop-anything; loop-anything "two words"; echo "$CUSTOM_VALUE"'],env=env,text=True,capture_output=True,check=True)
            self.assertEqual(shell.stdout.splitlines(),[result['command'],'two words','keep'])
            newer=Path(root)/'new.command';newer.write_text('#!/bin/sh\necho upgraded\n');newer.chmod(0o755)
            with patch('loop_anything.packaging.launcher.sys.platform','darwin'):
                register(newer,home=home,environ={'SHELL':'/bin/zsh'})
            self.assertEqual(subprocess.check_output([result['command']],text=True).strip(),'upgraded')
            self.assertEqual(profile.read_text().count(BEGIN),1)

    def test_bash_login_and_interactive_profiles_and_unrelated_command(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);(home/'.bash_profile').write_text('# existing login\n')
            source=home/'app';source.write_text('#!/bin/sh\necho ready\n');source.chmod(0o755)
            with patch('loop_anything.packaging.launcher.sys.platform','linux'):
                result=register(source,home=home,environ={'SHELL':'/bin/bash'})
            self.assertEqual(set(result['profiles']),{str(home/'.bashrc'),str(home/'.bash_profile')})
            self.assertIn('# existing login',(home/'.bash_profile').read_text())
            output=subprocess.check_output(['/bin/bash','--noprofile','--rcfile',str(home/'.bashrc'),'-ic','loop-anything'],env=dict(os.environ,PATH='/usr/bin:/bin'),text=True,stderr=subprocess.DEVNULL)
            self.assertEqual(output.strip(),'ready')
            target=Path(result['command']);target.write_text('Unrelated user command')
            with self.assertRaises(FileExistsError):register(source,home=home,environ={'SHELL':'/bin/bash'})
            self.assertEqual(target.read_text(),'Unrelated user command')

    def test_windows_registration_uses_user_path_and_preserves_cli_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);source=home/'Loop Anything.cmd';source.write_text('@echo off\n')
            with patch('loop_anything.packaging.launcher.sys.platform','win32'),patch('loop_anything.packaging.launcher._windows_path') as path:
                result=register(source,home=home,environ={})
                path.assert_called_once_with(home/'.local'/'bin')
            self.assertTrue(result['command'].endswith('loop-anything.cmd'))
            self.assertIn('%*',Path(result['command']).read_text())

    def test_register_cli_does_not_open_database_or_start_service(self):
        from loop_anything.__main__ import main
        with patch('sys.argv',['loop-anything','register']),patch('loop_anything.packaging.launcher.register',return_value={'command':'registered'}) as call,patch('loop_anything.runtime.store.Store',side_effect=AssertionError('No database for PATH registration')),patch('builtins.print'):
            main()
        call.assert_called_once_with(None)

    def test_profile_update_is_atomic_and_keeps_dotfile_symlinks(self):
        from loop_anything.packaging.launcher import _section
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);original=home/'dotfiles-zshrc';original.write_text('# keep personal settings\n')
            profile=home/'.zshrc';profile.symlink_to(original)
            with patch('loop_anything.packaging.launcher.os.replace',side_effect=OSError('simulated interruption')):
                with self.assertRaises(OSError):_section(profile,'export PATH=/test:"$PATH"')
            self.assertEqual(original.read_text(),'# keep personal settings\n');self.assertTrue(profile.is_symlink())
            _section(profile,'export PATH=/test:"$PATH"')
            self.assertTrue(profile.is_symlink());self.assertIn(BEGIN,original.read_text())
