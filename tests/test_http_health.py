"""The fixed health URL is a small, unauthenticated HTTP liveness response."""
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen

from loop_anything.capabilities import VERSION


class HTTPHealthTests(unittest.TestCase):
    def test_plain_http_health_without_credentials_or_business_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / 'workspace.sqlite3'
            log = root / 'server.log'
            with log.open('w') as output:
                process = subprocess.Popen(
                    [sys.executable, '-m', 'loop_anything', '--db', str(database),
                     'serve', '--port', '0', '--allow-sleep'],
                    stdout=output, stderr=output,
                    env=dict(os.environ, LOOP_ANYTHING_IDENTITY_DIR=str(root / 'identity')))
                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        startup = log.read_text()
                        match = re.search(r'Health check: (http://127\.0\.0\.1:\d+/api/health)', startup)
                        if match:
                            break
                        self.assertIsNone(process.poll(), startup)
                        time.sleep(.05)
                    else:
                        self.fail('Health URL not printed: ' + log.read_text())
                    url = match.group(1)
                    # No TLS, credentials, or platform-specific headers are supplied.
                    with urlopen(url, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.geturl(), url)
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                        self.assertEqual(response.headers.get_content_type(), 'application/json')
                        self.assertEqual(json.load(response),
                                         {'ok': True, 'service': 'loop-anything', 'version': VERSION})
                    # Full discovery remains a separate existing endpoint.
                    with urlopen(url.replace('/health', '/platform'), timeout=5) as response:
                        self.assertIn('keep_awake', json.load(response))
                    with sqlite3.connect(database) as connection:
                        self.assertEqual(connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
