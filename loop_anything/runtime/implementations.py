"""Candidate implementations and explicit selection; no execution or routing."""
import copy
import math
import re
from loop_anything.runtime.model import Invalid


def options(entry):
    # The existing single implementation is the compact form of one default option.
    if not entry:
        return {}
    return {'default': entry} if 'kind' in entry else entry.get('options', {})


def default_id(entry):
    return 'default' if entry and 'kind' in entry else (entry or {}).get('default')


def validate_implementation(implementation):
    if not isinstance(implementation, dict) or implementation.get('kind') not in ('agent', 'command', 'external', 'event', 'approval'):
        raise Invalid('Invalid execution implementation', path=['kind'])
    if 'prompt' in implementation and (implementation['kind'] != 'agent' or not isinstance(implementation['prompt'], str)):
        raise Invalid('prompt is a string for Agent implementations only', path=['prompt'])
    for cmd in ('command', 'observe'):
        if cmd in implementation and (not isinstance(implementation[cmd], list) or not implementation[cmd] or not all(isinstance(x, str) and x and '\x00' not in x for x in implementation[cmd])):
            raise Invalid(cmd + ' must be nonempty argv', path=[cmd])
    if implementation['kind'] in ('command', 'external') and not implementation.get('command'):
        raise Invalid('Command implementation needs command', path=['command'])
    if implementation['kind'] == 'external' and not implementation.get('observe'):
        raise Invalid('External implementation needs observe', path=['observe'])
    if 'lifecycle' in implementation:
        from loop_anything.runtime.lifecycle import validate
        try:
            validate(implementation['lifecycle'])
        except Invalid as exc:
            raise Invalid(str(exc), path=['lifecycle'] + (exc.path or [])) from None
    timeout = implementation.get('timeout')
    if 'timeout' in implementation and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
        raise Invalid('Timeout must be positive', path=['timeout'])
    if 'cwd' in implementation and (not isinstance(implementation['cwd'], str) or not implementation['cwd'] or '\x00' in implementation['cwd']):
        raise Invalid('cwd must be a nonempty path', path=['cwd'])
    if implementation['kind'] == 'event' and not implementation.get('event'):
        raise Invalid('Event implementation needs event name', path=['event'])


def validate_candidates(entry):
    if not isinstance(entry, dict):
        raise Invalid('Node implementations must be an object')
    if 'kind' not in entry:
        if set(entry) - {'default', 'options'} or not isinstance(entry.get('options', {}), dict):
            raise Invalid('Node implementations accept options and optional default only')
        if entry.get('default') is not None and entry['default'] not in entry.get('options', {}):
            raise Invalid('Default must name an existing implementation')
    for ident, implementation in options(entry).items():
        if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', ident):
            raise Invalid('Implementation IDs use letters, digits, underscores and hyphens')
        try:
            validate_implementation(implementation)
        except Invalid as exc:
            raise Invalid(str(exc), path=([] if 'kind' in entry else ['options', ident]) + (exc.path or [])) from None


def validate_bindings(bp, catalog, bindings):
    if not isinstance(bindings, dict) or set(bindings) - set(bp['nodes']):
        raise Invalid('Bindings must map declared node IDs to implementation IDs or null')
    for node, ident in bindings.items():
        if ident is not None and (not isinstance(ident, str) or ident not in options(catalog.get(node))):
            raise Invalid('Unknown implementation for ' + node + ': ' + str(ident))


def choose(catalog, node, bindings=None, explicit=None):
    entry = catalog.get(node)
    ident = explicit if explicit is not None else (bindings[node] if bindings and node in bindings else default_id(entry))
    return ident, options(entry).get(ident)


def selected(run, task):
    """Dispatched attempts keep their snapshot, including after a default changes."""
    if task.get('execution_id'):
        execution = next((e for e in run['executions'] if e['id'] == task['execution_id']), None)
        if execution:
            return execution.get('implementation_id'), execution['implementation']
    spec = task['spec']
    return choose(run['implementations'], spec['node'], run['settings'].get('bindings'), spec.get('implementation'))


def check_selection(run, spec):
    ident = spec.get('implementation')
    if ident is not None:
        validate_bindings(run['loop_definition'], run['implementations'], {spec['node']: ident})


def catalog_copy(entry):
    return {'options': copy.deepcopy(options(entry)), 'default': default_id(entry)}
