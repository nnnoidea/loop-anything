"""Read versions for optimistic Agent edits. No locks across Agent computation."""
import copy
from contextlib import contextmanager
from types import SimpleNamespace

from loop_anything.runtime.model import Conflict, Invalid, digest
from loop_anything.runtime.task_scope import contains, owner_for

# Reports have their own Task/execution checks; only Agent reports use these reads.
EDIT_TOOLS = {'add_task', 'build_plan', 'change_task', 'edit_tasks', 'change_settings',
              'command', 'defer_task', 'resolve_request', 'report_task'}


def task_stamp(run, ident):
    task = run['tasks'].get(ident)
    if task is None:return None
    from loop_anything.runtime.timeline_runtime import TimelineRuntime
    from loop_anything.runtime.implementations import selected
    values, sources, missing = TimelineRuntime(SimpleNamespace(store=None)).resolve_inputs(run, task)
    attempt = next((e for e in run['executions'] if e['id'] == task.get('execution_id')), {})
    return digest([task['spec'], task.get('revision'), task['status'], task.get('execution_id'),
                   values, sources, missing, selected(run, task), task.get('assistance_results'),
                   {k: attempt.get(k) for k in ('lifecycle_state', 'observation_error', 'retry')}])


def collection_stamp(run, scope):
    # Include membership and execution state: "no next round / no active tasks" is a read too.
    return digest(sorted((ident, task.get('parent_id'), task_stamp(run, ident)) for ident, task in run['tasks'].items()
                         if contains(run, scope, ident)))


def basis(run, *, tasks=(), scope=False, settings=True, records=(), inbox=False):
    result = {'run_id': run['id'], 'status': run['status']}
    if settings:result['settings'] = digest(run['settings'])
    if tasks:result['tasks'] = {ident: task_stamp(run, ident) for ident in tasks}
    if scope is not False:result['task_sets'] = {scope or '': collection_stamp(run, scope)}
    if records:result['records'] = {ident: (run['records'].get(ident) or [{'revision': 0}])[-1]['revision'] for ident in records}
    if inbox:result['inbox'] = digest([run.get(k) for k in ('user_requests', 'events', 'task_dispositions', 'attention_error')])
    return result


def merge(run, left, right):
    result = copy.deepcopy(left or {})
    # Fresh collection reads supersede older Task reads in that collection.
    # Keep record evidence and observations outside this permission scope.
    for scope in right.get('task_sets', {}):
        for ident in list(result.get('tasks', {})):
            if contains(run, scope or None, ident):del result['tasks'][ident]
        for previous in list(result.get('task_sets', {})):
            if contains(run, scope or None, previous or None):del result['task_sets'][previous]
    if not result.get('tasks'):result.pop('tasks', None)
    for key, value in right.items():
        if key in ('tasks', 'task_sets', 'records'):result.setdefault(key, {}).update(value)
        else:result[key] = copy.deepcopy(value)
    return result


def read_basis(run, name, arguments, owner):
    scope = owner.get('scope_task') if owner else None
    if name == 'read_run':return basis(run, scope=None, records=run['records'], inbox=True)
    if name in ('read_timeline', 'next_tasks'):
        return basis(run, scope=scope, records=run['records'] if name == 'read_timeline' else (), inbox=scope is None)
    if name == 'read_task':return basis(run, tasks=[arguments['task_id']])
    if name == 'read_record':
        return basis(run, settings=False, records=[] if arguments.get('revision') else [arguments['id']])
    if name == 'resolve_refs':
        from loop_anything.runtime.task_refs import describe_references
        refs = describe_references([t['spec'] for t in run['tasks'].values()], arguments.get('refs'))
        return basis(run, tasks=[r['task_id'] for r in refs.values()])
    return basis(run, settings=False)


def validate(run, expected):
    if not isinstance(expected, dict) or expected.get('run_id') != run['id'] or 'status' not in expected:
        raise Invalid('Use basis returned by a read tool for this Run')
    if set(expected) - {'run_id', 'status', 'settings', 'tasks', 'task_sets', 'records', 'inbox'}:
        raise Invalid('Unknown basis fields')
    current = basis(run, settings='settings' in expected, tasks=expected.get('tasks', {}),
                    records=expected.get('records', {}), inbox='inbox' in expected)
    if 'task_sets' in expected:
        if not isinstance(expected['task_sets'], dict):raise Invalid('basis.task_sets must be an object')
        current['task_sets'] = {key: collection_stamp(run, key or None) for key in expected['task_sets']}
    conflicts = []
    for key, value in expected.items():
        actual = current.get(key)
        if value != actual:
            if isinstance(value, dict) and isinstance(actual, dict):
                conflicts.extend({'field': key + '.' + str(k), 'expected': v, 'actual': actual.get(k)}
                                 for k, v in value.items() if actual.get(k) != v)
            else:conflicts.append({'field': key, 'expected': value, 'actual': actual})
    if conflicts:
        error = Conflict('Decision basis changed; read the changed state and reconsider before submitting')
        error.conflicts = conflicts
        raise error


def refresh(run, expected):
    """Advance only versions already observed, after this caller's successful write."""
    result = basis(run, settings='settings' in expected, tasks=expected.get('tasks', {}),
                   records=expected.get('records', {}), inbox='inbox' in expected)
    if 'task_sets' in expected:
        result['task_sets'] = {key: collection_stamp(run, key or None) for key in expected['task_sets']}
    return result


@contextmanager
def writing(run, token, name, arguments):
    owner = owner_for(run, token)
    supplied = arguments.pop('basis', None)
    expected = supplied if supplied is not None else (owner or {}).get('observed')
    check = (owner is not None or supplied is not None) and name in EDIT_TOOLS
    duplicate = False
    if check:
        if owner and owner.get('execution_id') and not owner.get('resume_session'):
            primary = run['tasks'].get(owner.get('task_id'), {})
            claimed = next((e for e in run['executions'] if e['id'] == owner['execution_id']), {})
            if primary.get('execution_id') != owner['execution_id'] or claimed.get('token') != token:
                raise Conflict('This execution identity was superseded; use the current Task execution')
        # Idempotent report retries must return the original receipt even after state changes.
        task = run['tasks'].get(arguments.get('task_id'), {})
        attempt = next((e for e in run['executions'] if e['id'] == task.get('execution_id')), {})
        duplicate = name == 'report_task' and arguments.get('report_id') in attempt.get('reports', {})
        if not duplicate:
            if expected is None:raise Conflict('Read current state before editing Timeline')
            targets = [arguments['task_id']] if name == 'change_task' else [
                c.get('arguments', {}).get('task_id') for c in arguments.get('changes', []) if c.get('tool') == 'change_task']
            for target in targets:
                covered = target in expected.get('tasks', {}) or any(contains(run, scope or None, target) for scope in expected.get('task_sets', {}))
                legacy_revision = name == 'edit_tasks' and supplied is None and arguments.get('revision') is not None
                if target in run['tasks'] and not covered and not legacy_revision:
                    raise Conflict('Read the affected Task or task collection before changing it: ' + str(target))
            if name == 'change_settings' and 'settings' not in expected:
                raise Conflict('Read Timeline settings before changing them')
            try:
                validate(run, expected)
            except Conflict:
                if name not in ('add_task', 'build_plan'):raise
                from loop_anything.interfaces.agent_tasks import apply_task_edit
                probe = copy.deepcopy(run)
                probe_owner = owner_for(probe, token)
                apply_task_edit(probe, name, arguments, {'agent': (owner or {}).get('execution_id') or 'interactive'}, probe_owner)
                if probe != run:raise
                duplicate = True
    yield
    if check and not duplicate and expected is not None and owner is not None and owner_for(run, token) is owner:
        owner['observed'] = refresh(run, expected)
