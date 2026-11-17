"""Deliver declared package assets with process requests, using existing asset contracts."""
import base64
from pathlib import Path
import tempfile

from loop_anything.packaging.packages import (
    collect_assets, decode_assets, file_hash, installed_assets, json_bytes, load_installed,
)
from loop_anything.runtime.model import Invalid


def snapshot(store, metadata):
    if metadata.get('kind') in ('task', 'resume') and metadata.get('run_id'):
        from loop_anything.runtime.timelines import task_resources
        run=store.get(metadata['run_id'])
        execution=next(e for e in run['executions'] if e['id']==metadata['execution_id'])
        key,_=task_resources(run,execution['node'])
        document, root = load_installed(store.filename, key)
        assets = installed_assets(document, root)
        with store.connection() as db:
            original = db.execute('SELECT root FROM loop_packages WHERE key=?', (key,)).fetchone()[0]
        roots = list(dict.fromkeys([str(root), original]))
    elif metadata.get('kind') == 'communication':
        from loop_anything.runtime.communication import service
        row = service(store).get(metadata['request_id'])
        if not row.get('resource_root'):
            return None
        root = Path(row['resource_root'])
        assets = collect_assets(root, row.get('context', {}).get('asset_manifest', []))
        key, roots = metadata['request_id'], [str(root)]
    else:
        return None
    files = [{'path': name, 'base64': base64.b64encode(data).decode(), 'executable': executable}
             for name, (data, executable) in sorted(assets.items())]
    content = {'key': key, 'files': files}
    return dict(content, roots=roots, digest=file_hash(json_bytes(content)))


def materialize(bundle, cache):
    content = {k: bundle[k] for k in ('key', 'files')}
    fingerprint = file_hash(json_bytes(content))
    if fingerprint != bundle['digest']:
        raise Invalid('Execution resource checksum mismatch')
    assets = decode_assets(bundle['files'])
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    root = cache / fingerprint
    if root.exists() or root.is_symlink():
        if root.is_symlink() or not root.is_dir():
            raise Invalid('Invalid execution resource cache')
        for name, (data, _) in assets.items():
            path = root / name
            if path.is_symlink() or root.resolve() not in path.resolve().parents or not path.is_file() or path.read_bytes() != data:
                raise Invalid('Cached execution resource changed: ' + name)
        return root
    # The receiver serializes this short materialization; incomplete directories never become caches.
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        staging = Path(temporary) / 'resources'
        staging.mkdir()
        for name, (data, executable) in assets.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o700 if executable else 0o600)
        staging.rename(root)
    return root
