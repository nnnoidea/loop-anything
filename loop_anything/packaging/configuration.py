"""Recipient-owned run configuration, outside immutable/shareable Loop packages."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.implementations import options, validate_implementation, validate_bindings

TEMPLATE = 'config.example.json'
FIELDS = {'command', 'observe', 'cwd', 'timeout', 'executor', 'dispatch', 'agent_cli', 'resume_command', 'terminal'}


def template(document):
    return {
        '$comment': '接收方运行配置：inputs 填写此 Loop 使用的路径、外部服务地址等启动参数；bindings 选择已有候选；implementations 按 节点ID/候选ID 覆盖命令、工作目录或执行位置。空对象沿用包配置。只影响新 Run；凭据使用执行环境，不写入分享模板。',
        'inputs': {}, 'bindings': {},
        'implementations': {},
        **({'flow_agent': {}} if document['loop_definition'].get('flow_agent') else {})}


def decode(raw):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Invalid('运行配置不是有效 JSON: ' + str(exc)) from exc
    if not isinstance(value, dict):
        raise Invalid('运行配置必须是 JSON 对象')
    return value


def path_for(database, key):
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', key):
        raise Invalid('Invalid Loop key for configuration')
    return Path(database).resolve().parent / 'loop-configs' / (key + '.json')


def read_file(document, root, filename):
    fallback = template(document)
    if root is not None and TEMPLATE in document.get('files', {}):
        fallback = decode((Path(root) / TEMPLATE).read_bytes())
    try:
        raw = filename.read_bytes()
    except FileNotFoundError:
        raw = None
    except OSError as exc:
        raise Invalid('Cannot read Loop configuration: ' + str(exc)) from exc
    result = {'path': str(filename), 'exists': raw is not None,
              'revision': hashlib.sha256(raw).hexdigest() if raw is not None else 'missing', 'template': fallback}
    try:
        result['config'] = decode(raw) if raw is not None else fallback
    except Invalid as exc:
        result.update(config=None, error=str(exc), raw=raw.decode('utf-8', errors='replace'))
    return result


def installed(database, key):
    from loop_anything.packaging.packages import load_installed
    document, root = load_installed(database, key)
    return document, root, read_file(document, root, path_for(database, key))


def patch(target, changes, label):
    if not isinstance(changes, dict) or set(changes) - FIELDS - {'clear', 'kind'}:
        raise Invalid(label + ': only execution settings and clear may be changed; keep workflow rules in the Loop')
    if 'kind' in changes and target and changes['kind'] != target['kind']:
        raise Invalid(label + ': choose another candidate instead of changing its execution kind')
    if not target and changes.get('kind') not in ('agent', 'command', 'external'):
        raise Invalid(label + ': a new execution candidate needs kind=agent, command or external')
    clear = changes.get('clear', [])
    if not isinstance(clear, list) or any(not isinstance(k, str) or k not in FIELDS for k in clear):
        raise Invalid(label + ': clear must name execution settings')
    if set(clear) & set(changes):
        raise Invalid(label + ': cannot clear and set the same field')
    result = copy.deepcopy(target)
    for name in clear:
        result.pop(name, None)
    result.update({k: copy.deepcopy(v) for k, v in changes.items() if k != 'clear'})
    validate_implementation(result)
    return result


def apply(document, config):
    """Compose a Run snapshot. No mutation, online probes, shell expansion or inferred mapping."""
    if not isinstance(config, dict) or set(config) - {'$comment', 'inputs', 'bindings', 'implementations', 'flow_agent'}:
        raise Invalid('运行配置仅支持 inputs、bindings、implementations、flow_agent 和 $comment')
    for field in ('inputs', 'bindings', 'implementations', 'flow_agent'):
        if field in config and not isinstance(config[field], dict):
            raise Invalid('运行配置 ' + field + ' 必须是对象')
    result = copy.deepcopy(document)
    bp = result['loop_definition']
    bp['defaults'] = dict(bp.get('defaults', {}), **config.get('inputs', {}))
    candidates = result.setdefault('implementations', {})
    for node, changes in config.get('implementations', {}).items():
        if node not in bp['nodes'] or not isinstance(changes, dict):
            raise Invalid('Unknown node or invalid configuration: ' + node)
        available = options(candidates.get(node))
        for ident, fields in changes.items():
            if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', ident):
                raise Invalid('Invalid configuration candidate ID')
            updated = patch(available.get(ident, {}), fields, node + '/' + ident)
            if node not in candidates:
                candidates[node] = {'options': {}}
            if 'kind' in candidates[node] and ident == 'default':
                candidates[node] = updated
            else:
                if 'kind' in candidates[node]:
                    candidates[node] = {'options': {'default': candidates[node]}, 'default': 'default'}
                candidates[node].setdefault('options', {})[ident] = updated
    if config.get('flow_agent'):
        if not bp.get('flow_agent'):
            raise Invalid('This Loop has no built-in flow_agent to configure')
        bp['flow_agent'] = patch(bp['flow_agent'], config['flow_agent'], 'flow_agent')
    validate_bindings(bp, candidates, config.get('bindings', {}))
    return result


def effective(document, root, config):
    from loop_anything.packaging.packages import effective_implementations, effective_definition
    result = apply(document, config)
    return {'loop_definition': effective_definition(result),
            'implementations': effective_implementations(result, root),
            'bindings': copy.deepcopy(config.get('bindings', {}))}


def read(store, key):
    document, root, saved = installed(store.filename, key)
    # Raw author configuration is useful when filling the recipient file; do not guess values.
    saved['targets'] = {'inputs': document['loop_definition'].get('defaults', {}),
                        'implementations': {n: {i: {k: v for k, v in c.items() if k in FIELDS}
                                               for i, c in options(entry).items()}
                                            for n, entry in ((n, document.get('implementations', {}).get(n)) for n in document['loop_definition']['nodes'])}}
    if document['loop_definition'].get('flow_agent'):
        saved['targets']['flow_agent'] = {k: v for k, v in document['loop_definition']['flow_agent'].items() if k in FIELDS}
    return saved


def write(store, key, config, revision):
    document, root, _ = installed(store.filename, key)
    apply(document, config)  # Shape/target checks only; no filesystem or service readiness checks.
    encoded = (json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    filename = path_for(store.filename, key)
    # Reuse the workspace transaction to serialize tool writes; atomic replace keeps readers whole.
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        saved = read_file(document, root, filename)
        if saved['revision'] != revision:
            raise Conflict('运行配置已变化，请重新 read_loop_config 后再修改')
        filename.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=filename.parent, prefix='.config-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
            os.replace(temporary, filename)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        db.commit()
    return read_file(document, root, filename)


def initialize_file(database, key, document, root):
    """First install only; repeat installs never overwrite the recipient's choices."""
    filename = path_for(database, key)
    if filename.exists():
        return str(filename)
    config = read_file(document, root, filename)['config']
    filename.parent.mkdir(parents=True, exist_ok=True)
    try:
        with filename.open('x', encoding='utf-8') as out:
            json.dump(config, out, ensure_ascii=False, indent=2, allow_nan=False)
            out.write('\n')
    except FileExistsError:
        pass
    return str(filename)
