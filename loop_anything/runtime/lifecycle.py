"""The visible execution contract: one initial state and explicit event transitions."""
import copy
import re
from loop_anything.runtime.model import Invalid, digest
from loop_anything.runtime.checks import validate_expression

KINDS = ('command', 'external', 'agent', 'event', 'approval', 'timer')
TERMINAL = {'completed', 'fault', 'retry', 'agent'}


def template(kind):
    initial = {'external': 'submitting', 'event': 'waiting', 'timer': 'waiting', 'approval': 'approval'}.get(kind, 'executing')
    states = [initial] + (['waiting'] if kind == 'external' else [])
    rows = []
    for state in states:
        rows.extend({'from': state, 'event': event, 'to': target} for event, target in
                    [('progress', state), ('completed', 'completed'), ('failed', 'fault'), ('process_error', 'fault')])
    if kind == 'event':
        rows.append({'from': initial, 'event': 'timeout', 'to': 'fault'})
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
        if not isinstance(entry, dict):
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
    pairs = {}
    for row in rows:
        if not isinstance(row, dict) or not {'from', 'event', 'to'} <= set(row) or set(row) - {'from', 'event', 'to', 'when', 'parameters', 'notify'}:
            raise Invalid('Each transition needs from, event, to and optional when/parameters')
        if not all(name(row[k]) for k in ('from', 'event', 'to')) or row['from'] in TERMINAL:
            raise Invalid('Transition IDs must be valid; terminal states have no outgoing transitions')
        pair = (row['from'], row['event'])
        previous = pairs.setdefault(pair, [])
        if previous and ('when' not in row or any('when' not in old or old['when'] == row['when'] for old in previous)):
            raise Invalid('Branches for one state/event need distinct explicit conditions')
        previous.append(row)
        if 'parameters' in row and (row['to'] != 'retry' or not isinstance(row['parameters'], dict)):
            raise Invalid('Only retry transitions may declare parameter changes as an object')
        if row['event'] == 'completed' and row['to'] != 'completed' or row['to'] == 'completed' and row['event'] != 'completed':
            raise Invalid('Only a validated completed report enters completed')
        if row['event'] == 'process_error' and row['to'] not in {'fault', 'retry', 'agent'}:
            raise Invalid('A stopped process cannot continue executing; process_error must enter fault, retry or agent')
        if row['event'] == 'check_error' and row['to'] in TERMINAL - {'agent'}:
            raise Invalid('A failed check cannot determine the external task outcome')
        if 'notify' in row:
            from loop_anything.runtime.notifications import validate_notice
            if not isinstance(row['notify'],list):raise Invalid('notify must be a list')
            for notice in row['notify']:validate_notice(notice)
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


def revoke_execution_token(execution):
    # Retired monitor credentials only authenticate evidence; they never regain write access.
    if execution['implementation']['kind'] == 'external' and execution.get('external_id') and execution.get('token'):
        execution.setdefault('retired_monitor_tokens', []).append(digest(execution['token']))
    execution['token'] = None


def monitor_token_matches(execution, token):
    return bool(token and execution['implementation']['kind'] == 'external' and execution.get('external_id') and
                (execution.get('token') == token or digest(token) in execution.get('retired_monitor_tokens', [])))


def monitor_ended(run, execution):
    return (run['status'] in ('completed', 'terminated') or execution['status'] in {'completed', 'fault', 'cancelled', 'stale', 'skipped'} or
            execution.get('lifecycle_state') in TERMINAL or run['tasks'][execution['task_id']].get('execution_id') != execution['id'])


def wait_values(implementation, context):
    from datetime import datetime
    from loop_anything.runtime.timeline_model import expand
    import math, time
    try:
        value = expand(implementation.get('wait', {}), context)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise Invalid('Invalid wait reference: ' + str(exc)) from None
    def number(v):
        if isinstance(v,str):
            try:v=float(v)
            except ValueError:raise Invalid('Wait seconds must be numeric') from None
        if type(v) not in (int,float) or not math.isfinite(v) or v < 0:raise Invalid('Wait seconds must be finite and nonnegative')
        return v
    def timestamp(v):
        try:
            date=datetime.fromisoformat(v.replace('Z','+00:00'))
            if date.tzinfo is None:raise ValueError('timezone required')
            return date.timestamp()
        except (AttributeError,TypeError,ValueError):raise Invalid('Wait until requires an ISO date with timezone') from None
    now=time.time();result={}
    if 'seconds' in value:result['until']=now+number(value['seconds'])
    if 'until' in value:result['until']=timestamp(value['until'])
    if 'timeout' in value:result['deadline']=now+number(value['timeout'])
    result['key']=value.get('key',context['parameters'].get('event_key'))
    if result['key'] is not None and not isinstance(result['key'],str):raise Invalid('Event key must be text')
    result['outputs']=value.get('outputs',{})
    if not isinstance(result['outputs'],dict):raise Invalid('Timer outputs must be an object')
    return result
