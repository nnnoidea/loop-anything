"""A workspace catalog of resource references and explicitly published previews."""
import json
import time
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

from loop_anything.runtime.model import Conflict, Invalid, contract


RESOURCE_ID = {'type': 'string', 'maxLength': 80, 'pattern': '^[a-z0-9][a-z0-9_-]*$(?!\\n)'}
REFERENCES = {'type': 'array', 'items': RESOURCE_ID, 'uniqueItems': True, 'maxItems': 32}


def text(max_length, min_length=1):
    return {'type': 'string', 'minLength': min_length, 'maxLength': max_length}


def object_fields(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


PREVIEW = object_fields({
    'summary': text(1600, 0),
    'facts': {'type': 'array', 'maxItems': 8,
              'items': object_fields({'label': text(60), 'value': text(100)}, ('label', 'value'))},
    'sections': {'type': 'array', 'maxItems': 4, 'items': object_fields({
        'title': text(100),
        'items': {'type': 'array', 'maxItems': 8, 'items': object_fields({
            'title': text(240), 'text': text(900), 'details': text(1200),
        }, ('title', 'text'))},
    }, ('title', 'items'))},
})


REGISTRATION = object_fields({
    'resource_id': RESOURCE_ID,
    'revision': {'type': 'integer', 'minimum': 0},
    'name': text(160),
    'location': text(2000),
    'skill': text(2000),
    'description': text(1400, 0),
    'preview': PREVIEW,
}, ('resource_id', 'revision', 'name', 'location', 'skill'))


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS shared_resources (
        id TEXT PRIMARY KEY, revision INTEGER NOT NULL, updated_at REAL NOT NULL, document TEXT NOT NULL
    )''')


def locator_kind(value, label):
    if value != value.strip() or any(ord(char) < 32 for char in value):
        raise Invalid(label + ' contains space padding or control characters')
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        return 'path'
    try:
        parsed = urlsplit(value)
        if (parsed.scheme in ('http', 'https') and parsed.hostname and parsed.username is None
                and '\\' not in value and not any(char.isspace() for char in value)):
            _ = parsed.port
            return 'url'
    except ValueError:
        pass
    raise Invalid(label + ' must be an absolute path or an HTTP(S) URL without embedded credentials')


def _entry(row, include_preview):
    doc = json.loads(row['document'])
    if not include_preview:
        doc.pop('preview', None)
    return dict(doc, id=row['id'], revision=row['revision'], updated_at=row['updated_at'])


def list_resources(store):
    with store.connection() as db:
        return [_entry(row, False) for row in db.execute('SELECT * FROM shared_resources ORDER BY id')]


def read_resource(store, resource_id):
    with store.connection() as db:
        row = db.execute('SELECT * FROM shared_resources WHERE id=?', (resource_id,)).fetchone()
    if row is None:
        raise Invalid('Shared resource is not registered: ' + resource_id)
    return _entry(row, True)


def set_resource(store, arguments):
    contract(arguments, REGISTRATION, 'Resource registration')
    resource_id, revision = arguments['resource_id'], arguments['revision']
    name, location, skill = arguments['name'], arguments['location'], arguments['skill']
    description, preview = arguments.get('description', ''), arguments.get('preview')
    if not name.strip():
        raise Invalid('Resource name is required')
    location_kind = locator_kind(location, 'Resource location')
    skill_kind = locator_kind(skill, 'Skill entry')
    doc = dict(name=name, description=description, location=location, location_kind=location_kind,
               skill=skill, skill_kind=skill_kind)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT * FROM shared_resources WHERE id=?', (resource_id,)).fetchone()
        if revision != (current['revision'] if current else 0):
            raise Conflict('Shared resource changed; reload the entry before saving')
        if preview is not None:
            doc['preview'] = preview
        elif current:
            doc['preview'] = json.loads(current['document']).get('preview', {})
        now = time.time()
        db.execute('''INSERT INTO shared_resources VALUES (?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, updated_at=excluded.updated_at, document=excluded.document''',
                   (resource_id, revision + 1, now, json.dumps(doc, ensure_ascii=False)))
        db.commit()
    return dict(doc, id=resource_id, revision=revision + 1, updated_at=now)


def resolve(store, node):
    ids = node.get('resources', [])
    if not ids:
        return []
    with store.connection() as db:
        rows = db.execute('SELECT * FROM shared_resources WHERE id IN (%s)' % ','.join('?' for _ in ids), ids)
        resources = {row['id']: dict(_entry(row, False), status='registered') for row in rows}
    return [resources.get(resource_id, {'id': resource_id, 'status': 'missing',
                                         'message': 'Shared resource is not registered on the source platform'})
            for resource_id in ids]
