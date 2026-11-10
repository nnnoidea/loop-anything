"""Verify explicit web controls use the CLI registry and execution guards."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from loop_anything.runtime.local_tasks import LocalRuntime, TaskRegistry


class WebSchedulesTests(unittest.TestCase):
    def test_stop_accepted_between_control_polls_prevents_due_job_from_launching(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = TaskRegistry(folder)
            ident = registry.register({'name': 'Waiting job', 'every': 60, 'command': [sys.executable, '-c', 'print("ran")']})['id']
            runtime = LocalRuntime(registry, [ident])
            try:
                runtime.tick()
                self.assertTrue(registry.stop(ident)['stop_requested'])
                runtime.items[ident]['state']['next_at'] = time.time() - 1
                runtime.last_control = time.monotonic()
                runtime.tick()
                job = registry.show(ident)
                self.assertEqual(job['runtime']['status'], 'stopped')
                self.assertIsNone(job['execution'])
            finally:
                runtime.close()

    def test_stop_during_condition_check_prevents_the_following_command(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'ran'
            registry = TaskRegistry(folder)
            check = [sys.executable, '-m', 'loop_anything', 'client', 'local', '--root', folder, 'stop', 'conditional']
            command = [sys.executable, '-c', 'from pathlib import Path; Path(%r).touch()' % str(marker)]
            registry.register({'name': 'Conditional job', 'every': 60, 'check': check, 'command': command}, 'conditional')
            runtime = LocalRuntime(registry, ['conditional'])
            try:
                runtime.tick()
                runtime.items['conditional']['future'].result(timeout=5)
                self.assertFalse(marker.exists())
                self.assertEqual(registry.show('conditional')['runtime']['status'], 'stopped')
            finally:
                runtime.close()

    def until(self, read):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            value = read()
            if value:
                return value
            time.sleep(.05)
        self.fail('Timed out waiting for the test scheduler')

    def test_registered_tasks_require_explicit_start_and_current_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / 'workspace.sqlite3'
            registry = TaskRegistry(str(database) + '.schedules')
            marker = root / 'ran'
            command = [sys.executable, '-c', 'from pathlib import Path; Path(%r).touch(); print("done")' % str(marker)]
            job = registry.register({'name': 'One shot', 'every': .1, 'repeat': False, 'command': command}, 'once')
            registry.register({'name': 'Waiting job', 'every': 60, 'command': command}, 'waiting')
            registry.register({'name': 'Receiver', 'every': 1, 'receiver': {'server': 'nas:///unused'}}, 'receiver')
            log = root / 'server.log'
            with log.open('w') as output:
                process = subprocess.Popen([sys.executable, '-m', 'loop_anything', '--db', str(database),
                                            'serve', '--port', '0', '--allow-sleep'], stdout=output, stderr=output,
                                           env=dict(os.environ, LOOP_ANYTHING_IDENTITY_DIR=str(root / 'identity')))
                try:
                    def startup():
                        output = log.read_text()
                        self.assertIsNone(process.poll(), output)
                        return re.search(r'Loop Anything workspace: (http://127\.0\.0\.1:\d+)', output)

                    match = self.until(startup)
                    base = match.group(1) + '/api/schedules'

                    def api(path='', body=None):
                        data = None if body is None else json.dumps(body).encode()
                        request = Request(base + path, data, headers={'X-Loop-Anything': 'workspace'})
                        with urlopen(request, timeout=5) as response:
                            return json.load(response)

                    def task(ident):
                        return next(item for item in api()['tasks'] if item['id'] == ident)

                    listed = api()
                    self.assertEqual(Path(listed['directory']), registry.root)
                    self.assertEqual([item['id'] for item in listed['tasks']], ['once', 'waiting'])
                    self.assertNotIn('command', task('once')['definition'])
                    self.assertEqual(task('once')['runtime']['status'], 'registered')
                    self.assertFalse(marker.exists())

                    initial = {'revision': job['revision'], 'owner': None}
                    self.assertTrue(api('/once/start', initial)['started'])
                    with self.assertRaises(HTTPError) as duplicate:
                        api('/once/start', initial)
                    self.assertEqual(duplicate.exception.code, 409)
                    self.until(lambda: task('once')['runtime']['status'] == 'completed')
                    self.assertTrue(marker.exists())
                    self.assertEqual(task('once')['runtime']['last_result']['stdout'].strip(), 'done')

                    api('/waiting/start', {'revision': 1, 'owner': None})
                    before = task('waiting')
                    owner = before['runtime']['owner']
                    registry.register({'name': 'Updated waiting job', 'every': 3600, 'command': command}, 'waiting')
                    updated = task('waiting')
                    self.assertEqual((updated['revision'], updated['definition']['every']), (2, 3600))
                    self.assertEqual((updated['runtime']['definition_revision'], updated['runtime']['schedule']['every']), (1, 60))
                    self.assertEqual(updated['runtime']['next_at'], before['runtime']['next_at'])
                    self.assertNotIn('command', updated['runtime']['schedule'])
                    with self.assertRaises(HTTPError) as stale:
                        api('/waiting/stop', {'owner': 'earlier-execution'})
                    self.assertEqual(stale.exception.code, 409)
                    self.assertTrue(api('/waiting/stop', {'owner': owner})['stop_requested'])
                    self.until(lambda: task('waiting')['runtime']['status'] == 'stopped')
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
