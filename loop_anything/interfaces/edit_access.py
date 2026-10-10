"""Optional per-Loop edit locks and local browser unlock cookies."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from http.cookies import SimpleCookie, CookieError
from loop_anything.runtime.model import Conflict, Invalid

LIFETIME = 24 * 60 * 60
ITERATIONS = 210000


class EditLocked(Conflict):
    def __init__(self, loop_id):
        self.loop_id = loop_id
        super().__init__('Unlock editing for this Loop: ' + loop_id)


def validate_policy(value):
    if value is None:return
    if not isinstance(value,dict) or set(value)!={'algorithm','iterations','salt','digest'} or value['algorithm']!='pbkdf2-sha256':
        raise Invalid('Invalid Loop edit protection')
    if type(value['iterations']) is not int or not 100000<=value['iterations']<=1000000:raise Invalid('Invalid password derivation cost')
    try:
        if len(bytes.fromhex(value['salt']))!=16 or len(bytes.fromhex(value['digest']))!=32:raise ValueError()
    except (TypeError,ValueError):raise Invalid('Invalid Loop password verifier') from None


def password_matches(policy,password):
    if not policy:return True
    if not isinstance(password,str) or not password or len(password)>1024:return False
    candidate=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(policy['salt']),policy['iterations']).hex()
    return hmac.compare_digest(candidate,policy['digest'])


def make_policy(password):
    if not isinstance(password,str) or len(password)>1024:raise Invalid('Loop password must be text up to 1024 characters')
    if not password:return None
    salt=secrets.token_bytes(16)
    return {'algorithm':'pbkdf2-sha256','iterations':ITERATIONS,'salt':salt.hex(),
            'digest':hashlib.pbkdf2_hmac('sha256',password.encode(),salt,ITERATIONS).hex()}


def policy(store,loop_id,db=None):
    if db is None:
        with store.connection() as db:return policy(store,loop_id,db)
    row=db.execute('SELECT document FROM loop_edit_protection WHERE loop_id=?',(loop_id,)).fetchone()
    return json.loads(row[0]) if row else None


def require_edit(store,loop_id,allowed=None,db=None):
    if policy(store,loop_id,db) and not (allowed and allowed(loop_id)):raise EditLocked(loop_id)


def set_password(store,loop_id,password,allowed=None):
    value=make_policy(password)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        require_edit(store,loop_id,allowed,db)
        db.execute('INSERT INTO loop_edit_protection VALUES (?,?) ON CONFLICT(loop_id) DO UPDATE SET document=excluded.document',(loop_id,json.dumps(value)))
        db.commit()
    return {'loop_id':loop_id,'protected':bool(value)}


class EditAccess:
    def __init__(self,store):
        self.store=store
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT OR IGNORE INTO platform_settings VALUES ('loop_edit_signing_key',?)",(json.dumps(secrets.token_hex(32)),))
            self.secret=json.loads(db.execute("SELECT value FROM platform_settings WHERE key='loop_edit_signing_key'").fetchone()[0]).encode()
            db.commit()

    @staticmethod
    def cookie_name(loop_id):return 'loop_edit_'+hashlib.sha256(loop_id.encode()).hexdigest()[:20]

    def matches(self,loop_id,password):return password_matches(policy(self.store,loop_id),password)

    def sign(self,loop_id,expires):
        value=str(expires)
        message=json.dumps([loop_id,policy(self.store,loop_id),expires],sort_keys=True).encode()
        return value+'.'+hmac.new(self.secret,message,hashlib.sha256).hexdigest()

    def status(self,loop_id=None,cookie=''):
        protected=bool(loop_id and policy(self.store,loop_id));expires=None
        if protected:
            try:
                jar=SimpleCookie();jar.load(cookie);value=jar[self.cookie_name(loop_id)].value;expiry=int(value.split('.')[0])
                if time.time()<expiry<=time.time()+LIFETIME and hmac.compare_digest(value,self.sign(loop_id,expiry)):expires=expiry
            except (CookieError,KeyError,ValueError,TypeError):pass
        return {'loop_id':loop_id,'protected':protected,'unlocked':not protected or expires is not None,'expires_at':expires}

    def permits(self,loop_id,cookie='',authorization='',password=None):
        if self.status(loop_id,cookie)['unlocked']:return True
        if password is not None and self.matches(loop_id,password):return True
        try:
            scheme,value=authorization.split(' ',1);credentials=base64.b64decode(value,validate=True).decode()
            return scheme.lower()=='basic' and ':' in credentials and self.matches(loop_id,credentials.split(':',1)[1])
        except (ValueError,UnicodeError):return False

    def cookie(self,loop_id,unlock):
        value=self.sign(loop_id,int(time.time())+LIFETIME) if unlock else ''
        return f'{self.cookie_name(loop_id)}={value}; Path=/; Max-Age={LIFETIME if unlock else 0}; HttpOnly; SameSite=Strict'
