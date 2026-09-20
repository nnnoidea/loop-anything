"""SQLite transtasks serialize run mutations across scheduler and UI."""
import json
import copy
import sqlite3
import time
import uuid
from contextlib import contextmanager, nullcontext
from loop_anything.runtime.task_scope import normalize_run
from pathlib import Path
from loop_anything.runtime.model import Conflict, Invalid, validate, current_definition


def uid(prefix):
    return prefix + '-' + uuid.uuid4().hex[:12]


class Store:
    def __init__(self, filename):
        self.filename = str(filename)
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='blueprints'").fetchone():
                raise Invalid('This database uses the pre-0.2 names. Convert a backup before opening it with Loop Anything; the original has not been changed.')
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS loop_definitions (key TEXT PRIMARY KEY, digest TEXT, document TEXT, implementations TEXT);
            CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS platform_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS timeline_parts (
              run_id TEXT NOT NULL, section TEXT NOT NULL, item TEXT NOT NULL,
              position INTEGER NOT NULL, document TEXT NOT NULL,
              PRIMARY KEY(run_id, section, item));
            CREATE TABLE IF NOT EXISTS loop_drafts (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, updated_at REAL NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS loop_packages (key TEXT PRIMARY KEY, digest TEXT NOT NULL, root TEXT NOT NULL, document TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.filename, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def keep_awake(self, value=None, default=True):
        with self.connection() as db:
            if value is not None:
                if type(value) is not bool:
                    raise Invalid('keep_awake must be a boolean')
                db.execute("INSERT INTO platform_settings VALUES ('keep_awake', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(value),))
                db.commit()
            row = db.execute("SELECT value FROM platform_settings WHERE key='keep_awake'").fetchone()
            return json.loads(row[0]) if row else default

    def publish(self, loop_definition, implementations):
        from loop_anything.packaging.packages import make_archive, install
        return install(self, make_archive({'loop_definition': loop_definition, 'implementations': implementations}))

    def catalog(self):
        with self.connection() as db:
            packages = {r[0] for r in db.execute('SELECT key FROM loop_packages')}
            return [dict(key=r['key'], loop_definition=current_definition(json.loads(r['document'])), implementations=json.loads(r['implementations']),
                         **({'package_key': r['key']} if r['key'] in packages else {}))
                    for r in db.execute('SELECT * FROM loop_definitions ORDER BY key')]

    def drafts(self):
        with self.connection() as db:
            return [dict(id=r['id'], revision=r['revision'], updated_at=r['updated_at'], **json.loads(r['document']))
                    for r in db.execute('SELECT * FROM loop_drafts ORDER BY updated_at DESC')]

    def save_draft(self, loop_definition, implementations, draft_id=None, revision=None, assets=None, checks=None):
        # Drafts may be incomplete. Strict graph validation belongs to publish.
        if not isinstance(loop_definition, dict) or not isinstance(loop_definition.get('nodes', {}), dict) or not isinstance(implementations, dict):
            raise Invalid('Draft loop_definition, nodes and implementations must be objects')
        extra = {}
        if assets is not None:
            from loop_anything.packaging.packages import decode_assets
            decode_assets(assets)
            extra['assets'] = assets
        if checks is not None:
            extra['checks'] = checks
        document = json.dumps({'loop_definition': loop_definition, 'implementations': implementations, **extra}, allow_nan=False)
        now = time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if draft_id:
                row = db.execute('SELECT revision FROM loop_drafts WHERE id=?', (draft_id,)).fetchone()
                if row is None or revision != row['revision']:
                    raise Conflict('Draft changed or no longer exists; reopen the saved draft')
                revision += 1
                db.execute('UPDATE loop_drafts SET revision=?, updated_at=?, document=? WHERE id=?',
                           (revision, now, document, draft_id))
            else:
                draft_id, revision = uid('draft'), 1
                db.execute('INSERT INTO loop_drafts VALUES (?,?,?,?)', (draft_id, revision, now, document))
            db.commit()
        return {'id': draft_id, 'revision': revision, 'updated_at': now, 'loop_definition': loop_definition, 'implementations': implementations, **extra}

    def create(self, key, title, inputs=None, settings=None, authorization='', acquire=False, bindings=None, fallback_node=None, global_agent_node=None, notification_command=None, _db=None):
        if type(acquire) is not bool:
            raise Invalid('acquire must be boolean')
        item = next((c for c in self.catalog() if c['key'] == key), None)
        if item is None:
            raise Invalid('Unknown loop_definition')
        if item.get('package_key'):
            from loop_anything.packaging.packages import load_installed, smoke
            document, root = load_installed(self.filename, key)
            readiness = smoke(document, root)
            if not readiness['startable']:
                failures = [c['target'] for c in readiness['checks'] if c['status'] == 'fail' and c['kind'] in ('manifest', 'asset')]
                raise Invalid('Package is installed but not ready; run smoke and resolve: ' + ', '.join(failures))
        loop_definition = item['loop_definition']
        if loop_definition.get('schema_version') != 2:
            raise Invalid('Legacy v1 loop_definitions are inspect-only; publish a Timeline-based Loop to execute')
        report = validate(loop_definition, item['implementations'])
        if not report['valid']:
            raise Invalid('Run requires complete valid implementations: ' + '; '.join(report['errors']))
        defaults = dict(loop_definition.get('defaults', {}))
        defaults.update(inputs or {})
        if settings:
            raise Invalid('Initialize semantics through the entry result and Timeline tools')
        run = {'id': uid('run'), 'title': title, 'loop_key': key, 'loop_definition': loop_definition,
               'implementations': item['implementations'], 'inputs': defaults,
               'status': 'running', 'revision': 1, 'created_at': time.time(),
               'executions': [], 'events': [], 'history': []}
        if loop_definition.get('schema_version') == 2:
            from loop_anything.runtime.timeline_runtime import initialize_run
            initialize_run(run)
            if not isinstance(authorization, str):
                raise Invalid('User authorization must be text')
            run['settings']['authorization'] = authorization
            if notification_command is not None:
                from loop_anything.runtime.timeline_model import validate_settings
                run['settings']['notification_command'] = copy.deepcopy(notification_command)
                validate_settings(run['settings'])
            from loop_anything.runtime.implementations import validate_bindings
            validate_bindings(loop_definition, run['implementations'], {} if bindings is None else bindings)
            run['settings']['bindings'] = copy.deepcopy({} if bindings is None else bindings)
            if fallback_node is not None:
                run['settings']['fallback_node'] = fallback_node or None
            from loop_anything.runtime.timeline_model import validate_fallback
            validate_fallback(loop_definition, run['implementations'], run['settings']['fallback_node'])
            if global_agent_node is not None:
                run['settings']['global_agent_node'] = global_agent_node or None
            from loop_anything.runtime.timeline_model import validate_global_agent
            validate_global_agent(loop_definition, run['implementations'], run['settings'].get('global_agent_node'))
        if acquire:
            from loop_anything.interfaces.agent_tasks import acquire_in_run
            acquire_in_run(run, 'interactive')
        self.log(run, 'created', 'Run created; entry Task is recorded before scheduling')
        if _db is not None:
            self._save(_db, run)
        else:
            with self.connection() as db:
                self._save(db, run)
                db.commit()
        return run

    @staticmethod
    def log(run, kind, message, execution=None, detail=None):
        run['history'].append({'id': uid('event'), 'at': time.time(), 'kind': kind,
                               'message': message, 'execution': execution, 'detail': detail})

    def list(self):
        with self.connection() as db:
            db.execute('BEGIN')
            return [self._load(db, row[0]) for row in db.execute('SELECT id FROM runs ORDER BY rowid DESC')]

    def get(self, run_id):
        with self.connection() as db:
            db.execute('BEGIN')
            return self._load(db, run_id)

    # Timeline partitions share one SQLite transaction; task attempts and history
    # remain separate from the current task arrangements.
    PARTS = {'tasks': 'tasks', 'executions': 'attempts', 'records': 'records',
             'history': 'history', 'events': 'events',
             'notifications': 'notifications', 'hook_firings': 'hook_firings'}

    def _load(self, db, run_id):
        row = db.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise Invalid('Unknown Run')
        run = json.loads(row[0])
        if run.pop('_storage', None) != 2:
            return normalize_run(run)  # Legacy snapshots are migrated transactionally on next edit.
        loop_definition = db.execute('SELECT document, implementations FROM loop_definitions WHERE key=?', (run['loop_key'],)).fetchone()
        run.update(loop_definition=current_definition(json.loads(loop_definition[0])), implementations=json.loads(loop_definition[1]))
        for field, section in self.PARTS.items():
            rows = [json.loads(r[0]) for r in db.execute(
                'SELECT document FROM timeline_parts WHERE run_id=? AND section=? ORDER BY position', (run_id, section))]
            if field == 'tasks':
                run[field] = {v['id']: v for v in rows}
            elif field == 'records':
                run[field] = {}
                for v in rows:
                    run[field].setdefault(v['id'], []).append(v)
            else:
                run[field] = rows
        return normalize_run(run)

    def _save(self, db, run):
        if run.get('schema_version') != 2:
            db.execute('INSERT OR REPLACE INTO runs VALUES (?,?)', (run['id'], json.dumps(run, allow_nan=False)))
            return
        header = {k: v for k, v in run.items() if k not in self.PARTS and k not in ('loop_definition', 'implementations')}
        header['_storage'] = 2
        for field, section in self.PARTS.items():
            values = run.get(field, [])
            if field == 'tasks':
                values = list(values.values())
            if field == 'records':
                values = [v for versions in values.values() for v in versions]
            old = {r[0]: (r[1], r[2]) for r in db.execute(
                'SELECT item, position, document FROM timeline_parts WHERE run_id=? AND section=?', (run['id'], section))}
            retained = set()
            for position, value in enumerate(values):
                key = value['id'] + ('@' + str(value['revision']) if field == 'records' else '')
                retained.add(key)
                document = json.dumps(value, ensure_ascii=False, allow_nan=False)
                if old.get(key) != (position, document):
                    db.execute('INSERT OR REPLACE INTO timeline_parts VALUES (?,?,?,?,?)',
                               (run['id'], section, key, position, document))
            for key in set(old) - retained:
                db.execute('DELETE FROM timeline_parts WHERE run_id=? AND section=? AND item=?', (run['id'], section, key))
        db.execute('INSERT INTO runs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                   (run['id'], json.dumps(header, ensure_ascii=False, allow_nan=False)))

    def scheduling_list(self):
        """No definition, record values or attempt archives needed for scheduling."""
        with self.connection() as db:
            db.execute('BEGIN')
            result = []
            for row in db.execute('SELECT document FROM runs'):
                run = json.loads(row[0])
                pending = any(n['status'] == 'pending' for n in run.get('notifications', []))
                if run.get('_storage') == 2:
                    pending = any(json.loads(r[0])['status'] == 'pending' for r in db.execute(
                        "SELECT document FROM timeline_parts WHERE run_id=? AND section='notifications'", (run['id'],)))
                if run['status'] == 'running' or pending or (run['status'] == 'paused' and run.get('settings', {}).get('termination_signal')):
                    result.append({'id': run['id'], 'status': run['status']})
            return result

    @contextmanager
    def edit(self, run_id, _db=None):
        with (self.connection() if _db is None else nullcontext(_db)) as db:
            if _db is None:
                db.execute('BEGIN IMMEDIATE')
            run = self._load(db, run_id)
            before = copy.deepcopy(run)
            yield run
            if run == before:
                if _db is None:
                    db.rollback()
                return
            if run.get('schema_version') == 2 and {k: (v['spec'], v.get('execution_id')) for k, v in run['tasks'].items()} != {k: (v['spec'], v.get('execution_id')) for k, v in before['tasks'].items()}:
                from loop_anything.runtime.timeline_plan import validate_task_dependencies
                validate_task_dependencies(run)
            run['revision'] += 1
            self._save(db, run)
            if _db is None:
                db.commit()
