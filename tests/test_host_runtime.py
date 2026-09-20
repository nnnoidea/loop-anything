"""OS lifecycle checks. Mocked Windows/Linux checks are not native-host acceptance."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from loop_anything.runtime.host_runtime import KeepAwake, lock_database, run_command
from loop_anything.runtime.model import Invalid


class HostRuntimeTests(unittest.TestCase):
    def test_runtime_timeout_stops_the_configured_process(self):
        with tempfile.TemporaryDirectory() as folder:
            pid_file = Path(folder) / 'pid'
            script = 'import os,time;from pathlib import Path;Path(%r).write_text(str(os.getpid()));time.sleep(30)' % str(pid_file)
            with self.assertRaises(Invalid):
                run_command([sys.executable, '-c', script], '{}', .5)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)

    @unittest.skipIf(os.name == 'nt', 'POSIX process-group regression')
    def test_timeout_stops_children_even_when_parent_pipes_close(self):
        import signal
        import time
        with tempfile.TemporaryDirectory() as folder:
            beat = Path(folder) / 'beat'
            child = "import signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);p=Path(%r)\nwhile True:p.write_text(str(time.time()));time.sleep(.02)" % str(beat)
            parent = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',%r],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);time.sleep(30)" % child
            with self.assertRaises(Invalid):
                run_command([sys.executable, '-c', parent], '', .5)
            before = beat.read_text()
            time.sleep(.1)
            self.assertEqual(before, beat.read_text())

    def test_database_lock_excludes_second_engine_and_releases_on_close(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / 'runs.db')
            lock = lock_database(db)
            try:
                with self.assertRaises(Invalid):
                    lock_database(db)
            finally:
                lock.close()
            lock_database(db).close()

    def test_windows_protection_restores_prior_state_and_reports_failure(self):
        with patch('loop_anything.runtime.host_runtime.sys.platform', 'win32'), patch('loop_anything.runtime.host_runtime.windows_execution_state', return_value=0x80000000) as call:
            protection = KeepAwake()
            with self.assertRaises(RuntimeError):
                with protection:
                    self.assertTrue(protection.status()['active'])
                    protection.set_enabled(False)
                    self.assertFalse(protection.status()['active'])
                    self.assertFalse(protection.status()['requested'])
                    protection.set_enabled(True)
                    self.assertTrue(protection.status()['active'])
                    raise RuntimeError('server stopped')
            self.assertEqual([0x80000001, 0x80000000, 0x80000001, 0x80000000], [c.args[0] for c in call.call_args_list])
            self.assertFalse(protection.status()['active'])
        with patch('loop_anything.runtime.host_runtime.sys.platform', 'win32'), patch('loop_anything.runtime.host_runtime.windows_execution_state', side_effect=OSError('denied')):
            with KeepAwake() as protection:
                self.assertFalse(protection.status()['active'])
                self.assertEqual('denied', protection.status()['error'])

    def test_linux_helper_handshake_and_release(self):
        with tempfile.TemporaryDirectory() as folder:
            helper = Path(folder) / 'inhibit'
            helper.write_text('#!' + sys.executable + '\nimport sys\nprint("ready",flush=True)\nsys.stdin.read()\n')
            helper.chmod(0o700)
            with patch('loop_anything.runtime.host_runtime.sys.platform', 'linux'), patch('loop_anything.runtime.host_runtime.shutil.which', return_value=str(helper)):
                with KeepAwake() as protection:
                    self.assertTrue(protection.status()['active'])
                    process = protection.process
                self.assertIsNotNone(process.poll())
            with patch('loop_anything.runtime.host_runtime.sys.platform', 'linux'), patch('loop_anything.runtime.host_runtime.shutil.which', return_value=None):
                with KeepAwake() as protection:
                    self.assertFalse(protection.status()['active'])
                    self.assertTrue(protection.status()['error'])


if __name__ == '__main__':
    unittest.main()
