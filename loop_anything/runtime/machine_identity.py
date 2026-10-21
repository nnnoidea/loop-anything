"""Local platform identity, independent of any business workspace database."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import sqlite3
import uuid

from loop_anything.paths import data_directory
from loop_anything.runtime.model import Invalid


def workspace_id():
    return 'workspace-' + uuid.uuid4().hex


class MachineIdentity:
    def __init__(self):
        root = Path(os.environ.get('LOOP_ANYTHING_IDENTITY_DIR') or data_directory()).expanduser()
        if not root.is_absolute():raise Invalid('LOOP_ANYTHING_IDENTITY_DIR must be an absolute local directory')
        root.mkdir(parents=True, exist_ok=True)
        self.filename = root / 'identity.sqlite3'
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS machine (singleton INTEGER PRIMARY KEY, id TEXT NOT NULL, name TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, path TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO machine VALUES (1,?,?)', ('machine-' + uuid.uuid4().hex, socket.gethostname()))

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.filename, timeout=15)
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    def read(self):
        db = sqlite3.connect(self.filename, timeout=15)
        try:
            ident, name = db.execute('SELECT id,name FROM machine WHERE singleton=1').fetchone()
        finally:db.close()
        return {'machine_id': ident, 'machine_name': name}

    def rename(self, name):
        if not isinstance(name, str) or not name.strip():raise Invalid('Machine name must be nonempty text')
        with self.transaction() as db:
            db.execute('UPDATE machine SET name=? WHERE singleton=1', (name,))

    def agent_registrations(self, current_workspace):
        """Inspect known local registrations on demand; never open a Store or start workers."""
        with self.transaction() as db:
            machine=db.execute('SELECT id FROM machine WHERE singleton=1').fetchone()[0]
            workspaces=db.execute('SELECT id,path FROM workspaces ORDER BY id').fetchall()
        agents=[];unavailable=[]
        for workspace,path in workspaces:
            try:
                # Only known databases, read-only, including stopped workspaces.
                db=sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True,timeout=2)
                try:row=db.execute('SELECT document FROM communication_settings WHERE id=1').fetchone()
                finally:db.close()
                config=json.loads(row[0]) if row else {}
                if config.get('machine_id')!=machine or config.get('instance_id')!=workspace:
                    raise ValueError('Workspace identity no longer matches its local registration')
                for ident,agent in config.get('agents',{}).items():
                    launch=agent.get('implementation',{})
                    groups=config.get('groups',{})
                    agents.append({'agent_id':ident,'name':agent.get('name',''),
                        'description':agent.get('description',''),'enabled':agent.get('enabled',True),
                        'workspace_id':workspace,'database':path,'current_workspace':workspace==current_workspace,
                        'cwd':launch.get('cwd'),'executable':(launch.get('command') or [None])[0],
                        'teams':[{'id':gid,'name':groups.get(gid,{}).get('name',''),
                                  'enabled':groups.get(gid,{}).get('enabled',False)} for gid in agent.get('groups',[])]})
            except (OSError,sqlite3.Error,ValueError,TypeError,KeyError) as exc:
                unavailable.append({'workspace_id':workspace,'database':path,'error':str(exc)})
        return {'machine_id':machine,'registered_agents':agents,'unavailable_workspaces':unavailable}

    def claim(self, ident, database, owner=None, legacy=None):
        """Serialize first use and moves; a live second copy cannot reuse an address."""
        path = Path(database).resolve()
        with self.transaction() as db:
            machine = db.execute('SELECT id FROM machine WHERE singleton=1').fetchone()[0]
            if owner and owner != machine:
                return 'This workspace belongs to another machine; create a new workspace identity for this copy'
            row = db.execute('SELECT path FROM workspaces WHERE id=?', (ident,)).fetchone()
            previous = row[0] if row else (legacy or {}).get('database')
            if previous and Path(previous).exists() and not Path(previous).samefile(path):
                return 'Another local database already uses this workspace identity; create a new identity for the copy'
            if not owner and legacy and legacy.get('host') != socket.gethostname():
                return 'Legacy workspace has no machine identity and its original host differs; explicitly identify this copy before execution'
            db.execute('INSERT INTO workspaces VALUES (?,?) ON CONFLICT(id) DO UPDATE SET path=excluded.path', (ident, str(path)))
        return None
