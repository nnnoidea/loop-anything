"""Task permissions and single-executor claims; scopes do not lock Timeline planning."""
import copy
from loop_anything.runtime.model import Conflict, Invalid


def contains(run, scope, task_id):
    if scope is None:
        return True
    seen = set()
    while task_id is not None and task_id not in seen:
        if task_id == scope:
            return True
        seen.add(task_id)
        task_id = run['tasks'].get(task_id, {}).get('parent_id')
    return False


def owner_for(run, token):
    owner = next((o for o in run.get('agent_sessions', []) if o['token'] == token), None)
    task = run.get('tasks', {}).get((owner or {}).get('task_id'), {})
    generation = task.get('origin', {}).get('steward')
    if generation and generation != run.get('steward', {}).get('generation'):
        return None
    return owner


def scope_for(run, task):
    node = task['spec']['node']
    from loop_anything.runtime.flow_agent import NODE as FLOW_AGENT
    if (node == FLOW_AGENT or run['loop_definition']['nodes'][node].get('initialize_timeline') or task['origin'].get('fallback') or
            node == (run['settings'].get('global_agent_node') or run['settings'].get('fallback_node'))):
        return None
    return task['id']


def scope_available(run, scope, token=None):
    if scope is None:return True
    if any(o['token'] != token and o.get('task_id') == scope for o in run.get('agent_sessions', [])):return False
    return not any((not token or e.get('token') != token) and (process_active(e) or owner_for(run, e.get('token')))
                   for e in run['executions'] if e['task_id'] == scope)


def process_active(execution):
    if execution.get('worker_active'):return True
    if execution.get('collaboration_caller_pid'):
        from loop_anything.runtime.collaboration import caller_active
        if caller_active(execution):return True
    if execution.get('communication_id'):
        from loop_anything.runtime.communication import END
        return execution.get('communication_state') not in END
    return False


def require_scope(run, owner, task_id=None):
    if not contains(run, owner.get('scope_task'), task_id):
        raise Conflict('Task is outside this Agent branch: ' + str(task_id))


def attach_tasks(run, specs, parent_id, owner=None):
    """Choose an immutable parent; a dependency never grants branch ownership."""
    specs = copy.deepcopy(specs)
    ids = {s['id'] for s in specs}
    for spec in specs:
        spec.setdefault('parent_id', parent_id)
        parent = spec['parent_id'] = spec['parent_id'] or None
        if parent == spec['id'] or (parent is not None and parent not in run['tasks'] and parent not in ids):
            raise Invalid('Task parent must name another task')
    parents = {s['id']: s['parent_id'] for s in specs}
    for spec in specs:
        seen, parent = {spec['id']}, spec['parent_id']
        while parent in parents:
            if parent in seen:
                raise Invalid('Task ownership cycle')
            seen.add(parent)
            parent = parents[parent]
        if owner:
            require_scope(run, owner, parent)
            if owner.get('scope_task') is not None:
                for destination in spec['outputs'].values():
                    previous = run.get('records', {}).get(destination['id'], [])
                    if previous:
                        require_scope(run, owner, previous[-1].get('tasks'))
                    for task in run['tasks'].values():
                        if any(d['id'] == destination['id'] for d in task['spec']['outputs'].values()):
                            require_scope(run, owner, task['id'])
    return specs
