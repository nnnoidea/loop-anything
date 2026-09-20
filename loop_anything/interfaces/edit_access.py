"""One shared edit password and a signed, fixed-lifetime browser cookie."""
import base64
import hashlib
import hmac
import time
from http.cookies import SimpleCookie, CookieError

LIFETIME = 24 * 60 * 60
COOKIE = 'loop_edit'


class EditAccess:
    def __init__(self, password, workspace):
        self.password = password or ''
        self.key = (self.password + '\0' + workspace).encode()

    def matches(self, password):
        return isinstance(password, str) and hmac.compare_digest(self.password.encode(), password.encode())

    def permits_header(self, authorization):
        try:
            scheme, value = authorization.split(' ', 1)
            credentials = base64.b64decode(value, validate=True).decode('utf-8')
            return scheme.lower() == 'basic' and ':' in credentials and self.matches(credentials.split(':', 1)[1])
        except (ValueError, UnicodeError):
            return False

    def sign(self, expires):
        value = str(expires)
        return value + '.' + hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def status(self, cookie=''):
        expires = None
        try:
            jar = SimpleCookie(); jar.load(cookie)
            value = jar[COOKIE].value
            expiry = int(value.split('.')[0])
            if time.time() < expiry <= time.time() + LIFETIME and hmac.compare_digest(value.encode(), self.sign(expiry).encode()):
                expires = expiry
        except (CookieError, KeyError, ValueError):
            pass
        return {'protected': bool(self.password), 'unlocked': not self.password or expires is not None,
                'expires_at': expires}

    def cookie(self, unlock):
        value = self.sign(int(time.time()) + LIFETIME) if unlock else ''
        return f'{COOKIE}={value}; Path=/; Max-Age={LIFETIME if unlock else 0}; HttpOnly; SameSite=Strict'
