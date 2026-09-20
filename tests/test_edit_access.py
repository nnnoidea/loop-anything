"""Fixed browser lifetime without a session database."""
import unittest
import base64
from unittest.mock import patch
from loop_anything.interfaces.edit_access import EditAccess, LIFETIME


class EditAccessTests(unittest.TestCase):
    def test_fixed_lifetime_restart_lock_and_password_change(self):
        access = EditAccess('共享口令', '/workspace')
        with patch('loop_anything.interfaces.edit_access.time.time', return_value=1000000):
            cookie = access.cookie(True)
            first = access.status(cookie)
            self.assertEqual(1000000 + 24 * 3600, first['expires_at'])
        with patch('loop_anything.interfaces.edit_access.time.time', return_value=1000000 + LIFETIME - 1):
            self.assertEqual(first, EditAccess('共享口令', '/workspace').status(cookie))
            self.assertFalse(access.status(access.cookie(False))['unlocked'])
            self.assertFalse(EditAccess('changed', '/workspace').status(cookie)['unlocked'])
            self.assertFalse(EditAccess('共享口令', '/other-workspace').status(cookie)['unlocked'])
        with patch('loop_anything.interfaces.edit_access.time.time', return_value=1000000 + LIFETIME):
            self.assertFalse(access.status(cookie)['unlocked'])
        for cookie in ('loop_edit=garbage', 'loop_edit=999999999999.bad', 'loop_edit=1000001.中文'):
            self.assertFalse(access.status(cookie)['unlocked'])
        self.assertTrue(access.permits_header('Basic ' + base64.b64encode(':共享口令'.encode()).decode()))
        self.assertFalse(access.permits_header('Basic invalid'))
        self.assertTrue(EditAccess(None, '/workspace').status()['unlocked'])
