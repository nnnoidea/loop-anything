"""The visible execution contract: one initial state and explicit event transitions."""
import copy
import re
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.checks import validate_expression

KINDS = ('command', 'external', 'agent', 'event', 'approval')
TERMINAL = {'completed', 'fault'}


def template(kind):
    initial = {'external': 'submitting', 'event': 'waiting', 'approval': 'approval'}.get(kind, 'executing')
    states = [initial] + (['waiting'] if kind == 'external' else [])
    rows = []
    for state in states:
        rows.extend({'from': state, 'event': event, 'to': target} for event, target in
                    [('progress', state), ('completed', 'completed'), ('failed', 'fault'), ('process_error', 'fault')])
    if kind == 'external':
        rows += [{'from': 'submitting', 'event': 'submitted', 'to': 'waiting'},
                 {'from': 'waiting', 'event': 'check_error', 'to': 'waiting'}]
    return {'initial': initial, 'transitions': rows}


def definition(implementation):
    return copy.deepcopy(implementation.get('lifecycle', template(implementation['kind'])))


def materialize(catalog):
    from loop_anything.runtime.implementations import options
    result = copy.deepcopy(catalog)
    for node, entry in result.items():
        if node == '$notifications' or not isinstance(entry, dict):
            continue
        candidates = options(entry)
        if not isinstance(candidates, dict):
            continue
        for config in candidates.values():
            if isinstance(config, dict) and config.get('kind') in KINDS:
                config.setdefault('lifecycle', template(config['kind']))
    return result


def validate(value):
    if not isinstance(value, dict) or set(value) != {'initial', 'transitions'}:
        raise Invalid('lifecycle needs initial and transitions')
    def name(v):
        return isinstance(v, str) and bool(re.fullmatch(r'[a-zA-Z0-9_-]+', v))
    if not name(value['initial']) or value['initial'] in TERMINAL:
        raise Invalid('Lifecycle initial must be a nonterminal state ID')
    rows = value['transitions']
    if not isinstance(rows, list) or not rows:
        raise Invalid('Lifecycle transitions must be a nonempty array')
    pairs = set()
    for row in rows:
        if not isinstance(row, dict) or not {'from', 'event', 'to'} <= set(row) or set(row) - {'from', 'event', 'to', 'when'}:
            raise Invalid('Each transition needs from, event, to and optional when')
        if not all(name(row[k]) for k in ('from', 'event', 'to')) or row['from'] in TERMINAL:
            raise Invalid('Transition IDs must be valid; terminal states have no outgoing transitions')
        pair = (row['from'], row['event'])
        if pair in pairs:
            raise Invalid('Each state/event pair must have one transition')
        pairs.add(pair)
        if row['event'] == 'completed' and row['to'] != 'completed' or row['to'] == 'completed' and row['event'] != 'completed':
            raise Invalid('Only a validated completed report enters completed')
        if row['event'] == 'process_error' and row['to'] != 'fault':
            raise Invalid('A stopped process cannot continue executing; process_error must enter fault')
        if row['event'] == 'check_error' and row['to'] in TERMINAL:
            raise Invalid('A failed check cannot determine the external task outcome')
        if 'when' in row:
            validate_expression(row['when'])
    reachable = {value['initial']}
    while True:
        expanded = reachable | {r['to'] for r in rows if r['from'] in reachable}
        if expanded == reachable:
            break
        reachable = expanded
    if any(r['from'] not in reachable for r in rows):
        raise Invalid('Transition source is unreachable from initial')
