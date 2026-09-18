"""One portable package format; unbound nodes are not damaged packages.

Pack/install never execute handlers. Smoke is a read-only, conservative preflight,
not an environment repairer. Only an explicit Run creates tasks for the Engine.
"""
import base64
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile

from loop_anything.runtime.timeline_model import validate_v2
from loop_anything.runtime.model import Invalid, Conflict, current_definition
from loop_anything.runtime.implementations import options, default_id

FORMAT = 'loop-anything-package/1'
MANIFEST = 'loop.json'
MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 256
PRIVATE_PARTS = {'.git', '.loop-anything', '.state-loop', '.codex', '.ssh', '__pycache__', '.venv'}


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def file_hash(content):
    return hashlib.sha256(content).hexdigest()


def member_path(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise Invalid('Invalid package path: ' + str(name))
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')):
        raise Invalid('Package path must be relative without dot segments: ' + name)
    if any(p.casefold() in PRIVATE_PARTS or p.casefold() == '.env' or p.casefold().startswith('.env.') for p in path.parts):
        raise Invalid('Private/runtime files cannot be packaged: ' + name)
    return name


def validate_skill_files(bp, files=None):
    skills = [bp.get('handbook', {})]
    for node in bp['nodes'].values():
        skills.extend(node.get('skills', []))
    for skill in skills:
        if 'path' in skill:
            path = member_path(skill['path'])
            if files is not None and path not in files:
                raise Invalid('Skill entry is missing from package assets: ' + path)


def resolve_skill(database, key, skill):
    """Return a local entry path without rewriting the portable Skill binding."""
    result = copy.deepcopy(skill)
    if 'path' in result:
        document, root = load_installed(database, key)
        relative = member_path(result['path'])
        path = (root / relative).resolve()
        if relative not in document['files'] or root.resolve() not in path.parents or not path.is_file():
            raise Invalid('Installed Skill entry is unavailable: ' + relative)
        result['resolved_path'] = str(path)
    return result


def validate_document(document):
    if not isinstance(document, dict) or set(document) - {'format', 'loop_definition', 'implementations', 'checks', 'files'}:
        raise Invalid('Package document accepts loop_definition, optional implementations/checks and package metadata only')
    if document.get('format', FORMAT) != FORMAT:
        raise Invalid('Unsupported Loop package format')
    bp, implementations = document.get('loop_definition'), document.get('implementations', {})
    report = validate_v2(current_definition(bp) if isinstance(bp, dict) else bp, implementations)
    if not report['valid']:
        raise Invalid('; '.join(report['errors']))
    validate_skill_files(bp)
    notifications = implementations.get('$notifications')
    if '$notifications' in implementations:
        if not isinstance(notifications, dict) or not isinstance(notifications.get('command'), list) or not notifications['command'] or not all(isinstance(x, str) and x and '\x00' not in x for x in notifications['command']):
            raise Invalid('$notifications requires command argv')
        if 'cwd' in notifications and (not isinstance(notifications['cwd'], str) or not notifications['cwd'] or '\x00' in notifications['cwd']):
            raise Invalid('$notifications cwd must be a nonempty string')
        timeout = notifications.get('timeout', 30)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise Invalid('$notifications timeout must be positive and finite')
    checks = document.get('checks', {})
    if not isinstance(checks, dict) or set(checks) - {'paths', 'env', 'programs'}:
        raise Invalid('checks supports paths, env and programs only')
    for name, items in checks.items():
        if not isinstance(items, list) or not all(isinstance(x, str) and x and '\x00' not in x for x in items):
            raise Invalid('checks.' + name + ' must be a nonempty-string array')
        if name == 'env' and any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', x) for x in items):
            raise Invalid('Invalid required environment variable name')
    if not isinstance(document.get('files', {}), dict):
        raise Invalid('files must be a manifest object')
    return report


def make_archive(document, assets=None):
    """assets maps explicit relative names to (bytes, executable). No filesystem scan."""
    validate_document(document)
    assets = assets or {}
    if set(document.get('files', {})) - set(assets):
        raise Invalid('Existing manifest declares assets that were not supplied; explicitly include them instead of silently dropping files')
    if len(assets) >= MAX_FILES:
        raise Invalid('Too many package files')
    manifest = copy.deepcopy(document)
    manifest.update(format=FORMAT, implementations=copy.deepcopy(document.get('implementations', {})), files={})
    total, seen = 0, set()
    for name, (data, executable) in assets.items():
        member_path(name)
        if name.casefold() == MANIFEST or name.casefold() in seen:
            raise Invalid('Reserved or duplicate package path: ' + name)
        seen.add(name.casefold())
        if not isinstance(data, bytes) or type(executable) is not bool:
            raise Invalid('Invalid asset data')
        total += len(data)
        if total > MAX_BYTES:
            raise Invalid('Package exceeds 20 MiB uncompressed limit')
        manifest['files'][name] = {'sha256': file_hash(data), 'executable': executable}
    encoded = json_bytes(manifest)
    if total + len(encoded) > MAX_BYTES:
        raise Invalid('Package exceeds 20 MiB uncompressed limit')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data, executable in [(MANIFEST, encoded, False)] + [(n, assets[n][0], assets[n][1]) for n in sorted(assets)]:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
            archive.writestr(info, data)
    data = out.getvalue()
    read_archive(data)  # Validate exact file list and path collisions before handing it out.
    return data


def read_archive(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise Invalid('Loop package must be a ZIP of at most 20 MiB')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
                raise Invalid('Package exceeds file count or expanded size limit')
            seen, contents = set(), {}
            for info in infos:
                name = member_path(info.filename)
                kind = stat.S_IFMT(info.external_attr >> 16)
                if kind not in (0, stat.S_IFREG) or info.is_dir() or info.flag_bits & 1:
                    raise Invalid('Only regular unencrypted files are allowed: ' + name)
                folded = name.casefold()
                if folded in seen:
                    raise Invalid('Duplicate package path: ' + name)
                seen.add(folded)
                contents[name] = archive.read(info)
            for name in seen:
                if any(str(parent) in seen for parent in PurePosixPath(name).parents if str(parent) != '.'):
                    raise Invalid('File/directory path collision: ' + name)
        if MANIFEST not in contents:
            raise Invalid('Package is missing loop.json')
        document = json.loads(contents.pop(MANIFEST))
        validate_document(document)
        if document.get('format') != FORMAT or set(contents) != set(document.get('files', {})):
            raise Invalid('Manifest must declare the exact package file list')
        assets = {}
        for name, metadata in document['files'].items():
            if not isinstance(metadata, dict) or set(metadata) != {'sha256', 'executable'} or type(metadata['executable']) is not bool:
                raise Invalid('Invalid file metadata: ' + name)
            if metadata['sha256'] != file_hash(contents[name]):
                raise Invalid('File checksum mismatch: ' + name)
            assets[name] = (contents[name], metadata['executable'])
        validate_skill_files(document['loop_definition'], assets)
        fingerprint = file_hash(json_bytes(document))
        return document, assets, 'pkg-' + fingerprint, fingerprint
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, RuntimeError, NotImplementedError) as exc:
        raise Invalid('Invalid Loop archive: ' + str(exc)) from exc


def collect_assets(root, includes):
    """Only explicit --include files/directories; reject symlinks, never follow them."""
    root = Path(root).resolve()
    assets = {}
    for include in includes:
        member_path(include)
        source = root / include
        for part in [source] + list(source.parents):
            if part == root:
                break
            if part.is_symlink():
                raise Invalid('Cannot package symlink: ' + include)
        paths = sorted(source.rglob('*')) if source.is_dir() else [source]
        for file in paths:
            relative = file.relative_to(root).as_posix()
            member_path(relative)
            if file.is_symlink():
                raise Invalid('Cannot package symlink: ' + relative)
            if file.is_dir():
                continue
            if not file.is_file():
                raise Invalid('Missing/nonregular package file: ' + relative)
            if file.stat().st_size > MAX_BYTES:
                raise Invalid('Asset exceeds package size limit')
            assets[relative] = (file.read_bytes(), bool(file.stat().st_mode & 0o111))
            if len(assets) >= MAX_FILES or sum(len(a[0]) for a in assets.values()) > MAX_BYTES:
                raise Invalid('Package exceeds file count or expanded size limit')
    return assets


def effective_implementations(document, root):
    """Resolve ONLY the package-defined cwd base. Never rewrite command arguments."""
    implementations = copy.deepcopy(document.get('implementations', {}))
    for implementation in (v for node, entry in implementations.items() for v in ([entry] if node == '$notifications' else options(entry).values())):
        if 'command' in implementation or 'observe' in implementation:
            directory = Path(implementation.get('cwd', '.'))
            implementation['cwd'] = str(directory if directory.is_absolute() else Path(root) / directory)
    return implementations


def smoke(document, root):
    """No subprocess, imports, network, writes, dependency installation or repairs."""
    report = validate_document(document)
    root = Path(root)
    checks = []
    def add(kind, target, passed, detail, node=None, implementation=None):
        checks.append({'kind': kind, 'target': target, 'status': 'pass' if passed else 'fail', 'detail': detail, 'node': node, 'implementation': implementation})
    def same_file(file, expected):
        try:
            return file.is_file() and file.stat().st_size <= MAX_BYTES and file_hash(file.read_bytes()) == expected
        except OSError:
            return False
    def executable_exists(command, directory):
        if '/' in command or '\\' in command:
            target = Path(command) if Path(command).is_absolute() else directory / command
            return bool(shutil.which(str(target))) if os.name == 'nt' else target.is_file() and os.access(target, os.X_OK)
        # Relative PATH entries are evaluated in the handler's declared cwd.
        search_path = os.pathsep.join(p if Path(p).is_absolute() else str(directory / p)
                                      for p in os.get_exec_path())
        return bool(shutil.which(command, path=search_path))
    manifest_file = root / MANIFEST
    add('manifest', MANIFEST, not root.is_symlink() and not manifest_file.is_symlink() and
        same_file(manifest_file, file_hash(json_bytes(document))), 'Installed manifest must match the registered definition.')
    for name in report['unbound_nodes']:
        add('implementation', name, False, 'Node has no implementation implementation; package remains valid and shareable.', name)
    for name, metadata in document.get('files', {}).items():
        file = root / name
        safe = not root.is_symlink() and not any((root / Path(*PurePosixPath(name).parts[:i])).is_symlink()
                                                for i in range(1, len(PurePosixPath(name).parts) + 1))
        valid = safe and same_file(file, metadata['sha256'])
        add('asset', name, valid, 'Installed asset matches manifest.' if valid else 'Asset missing, changed or symlinked.')
    candidates = [(node, ident, config) for node, entry in effective_implementations(document, root).items() for ident, config in ([('default', entry)] if node == '$notifications' else options(entry).items())]
    for name, ident, implementation in candidates:
        directory = Path(implementation.get('cwd', str(root)))
        if 'command' in implementation or 'observe' in implementation:
            add('cwd', str(directory), directory.is_dir(), 'Declared working directory; never created by smoke.', name, ident)
        for field in ('command', 'observe'):
            argv = implementation.get(field)
            if not argv:
                continue
            command = argv[0]
            found = executable_exists(command, directory)
            add('executable', command, found, 'Executable lookup only; command is not invoked.', name, ident)
            # Explicit script entrypoints only. Arbitrary CLI flag semantics are not guessed.
            if len(argv) > 1 and not argv[1].startswith('-') and Path(argv[1]).suffix in ('.py', '.sh', '.js', '.mjs'):
                script = Path(argv[1]) if Path(argv[1]).is_absolute() else directory / argv[1]
                add('script', str(script), script.is_file() and os.access(script, os.R_OK), 'Script existence/readability only.', name, ident)
        if implementation.get('kind') in ('event', 'approval') or implementation.get('kind') == 'agent' and not implementation.get('command'):
            checks.append({'kind': 'manual_or_event', 'target': name, 'status': 'unknown',
                           'detail': 'Explicit implementation waits for external input; no automatic executor is configured.'})
    for path in document.get('checks', {}).get('paths', []):
        target = Path(path) if Path(path).is_absolute() else root / path
        add('path', path, target.exists(), 'Author-declared path; not rewritten.')
    for name in document.get('checks', {}).get('programs', []):
        add('program', name, executable_exists(name, root), 'Author-declared executable; not invoked.')
    for name in document.get('checks', {}).get('env', []):
        add('env', name, bool(os.environ.get(name)), 'Presence only; value is never included in the report.')
    checks.append({'kind': 'runtime', 'status': 'unknown', 'target': 'external behavior',
                   'detail': 'Imports, arbitrary command arguments, model access, external services and business results are not tested.'})
    return {'package_valid': True, 'startable': not any(c['status'] == 'fail' and c['kind'] in ('manifest', 'asset') for c in checks), 'ready': not any(c['status'] == 'fail' for c in checks),
            'unbound_nodes': report['unbound_nodes'], 'checks': checks,
            'notice': 'Read-only preflight, not a guarantee of successful execution. No configuration or files were repaired.'}


def load_installed(database, key):
    """Read-only even when smoke is the first CLI command in an empty directory."""
    uri = Path(database).resolve().as_uri() + '?mode=ro'
    try:
        with sqlite3.connect(uri, uri=True) as db:
            row = db.execute('SELECT document, root FROM loop_packages WHERE key=?', (key,)).fetchone()
    except sqlite3.Error as exc:
        raise Invalid('No installed package database: ' + str(exc)) from exc
    if row is None:
        raise Invalid('Unknown installed package')
    return json.loads(row[0]), Path(row[1])


def install(store, data):
    document, assets, key, fingerprint = read_archive(data)
    parent = Path(store.filename).resolve().parent / 'packages'
    if parent.is_symlink():
        raise Invalid('Package installation root must not be a symlink')
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / fingerprint
    # A single transaction serializes installation across platform processes.
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if root.exists() or root.is_symlink():
            if root.is_symlink() or (root / MANIFEST).is_symlink() or not (root / MANIFEST).is_file():
                raise Conflict('Existing package directory is not a valid installation')
            if (root / MANIFEST).read_bytes() != json_bytes(document):
                raise Conflict('Installed package manifest changed; do not overwrite')
            if any(c['kind'] == 'asset' and c['status'] == 'fail' for c in smoke(document, root)['checks']):
                raise Conflict('Installed assets changed; do not overwrite or repair')
        else:
            with tempfile.TemporaryDirectory(prefix='.install-', dir=str(parent)) as temporary:
                staging = Path(temporary) / 'package'
                staging.mkdir()
                (staging / MANIFEST).write_bytes(json_bytes(document))
                for name, (content, executable) in assets.items():
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    target.chmod(0o755 if executable else 0o644)
                staging.rename(root)
        # Keep the author's document untouched; cwd resolution is installation metadata.
        bound = effective_implementations(document, root)
        existing = db.execute('SELECT document, root FROM loop_packages WHERE key=?', (key,)).fetchone()
        if existing and (json.loads(existing[0]) != document or existing[1] != str(root)):
            raise Conflict('Package identity already installed with different content/location')
        db.execute('INSERT OR IGNORE INTO loop_packages VALUES (?,?,?,?)', (key, fingerprint, str(root), json.dumps(document)))
        db.execute('INSERT OR IGNORE INTO loop_definitions VALUES (?,?,?,?)',
                   (key, fingerprint, json.dumps(current_definition(document['loop_definition'])), json.dumps(bound)))
        db.commit()
    return {'key': key, 'loop_definition_id': document['loop_definition']['id'], 'version': document['loop_definition']['version'],
            'root': str(root), 'unbound_nodes': validate_document(document)['unbound_nodes'],
            'installed': True, 'started': False}


def decode_assets(items):
    if not isinstance(items, list) or len(items) >= MAX_FILES:
        raise Invalid('Invalid asset list')
    assets = {}
    for item in items:
        name = member_path(item['path'])
        if name in assets:
            raise Invalid('Duplicate asset: ' + name)
        try:
            data = base64.b64decode(item['base64'], validate=True)
        except (ValueError, TypeError) as exc:
            raise Invalid('Invalid asset encoding') from exc
        assets[name] = (data, item.get('executable', False))
        if name == MANIFEST or sum(len(v[0]) for v in assets.values()) > MAX_BYTES:
            raise Invalid('Reserved asset path or package size limit exceeded')
    return assets


def installed_assets(document, root):
    report = smoke(document, root)
    if any(c['kind'] in ('asset', 'manifest') and c['status'] == 'fail' for c in report['checks']):
        raise Invalid('Installed assets no longer match the package; cannot export changed files silently')
    return {name: ((root / name).read_bytes(), spec['executable']) for name, spec in document['files'].items()}
