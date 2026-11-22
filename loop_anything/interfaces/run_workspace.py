"""Read the Run page and only the detail panels requested by its browser."""

import json

from loop_anything.interfaces.agent_tasks import task_list
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.timeline_plan import task_dependencies
from loop_anything.runtime.timeline_runtime import result_readings
from loop_anything.runtime.timelines import public_status


HISTORY_PAGE_SIZE = 50
TABS = {'task-history', 'history', 'activity', 'decisions', 'records', 'hooks', 'tasks'}
ACTIVITY_KINDS = (
    'created', 'completed', 'pause', 'resume', 'terminate', 'method_updated',
    'settings', 'agent_action_change', 'monitor_retry', 'retry_applied',
    'waiting_user', 'agent_failure_pause', 'gate', 'release_gate', 'budget_exhausted',
)


def pick(doc, *keys):
    return {key: doc[key] for key in keys if key in doc}


def history_for_panel(db, run_id, tab, task_id, task_attempts, audit, offset):
    base = "FROM timeline_parts WHERE run_id=? AND section='history'"
    if tab == 'activity':
        kinds = ','.join('?' for _ in ACTIVITY_KINDS)
        base += f""" AND (json_extract(document,'$.kind') IN ({kinds}) OR
            (json_extract(document,'$.kind')='transition' AND (
                json_extract(document,'$.detail.to') IN ('fault','unresolved') OR
                json_extract(document,'$.detail.event') IN ('external_rejected','failed_requires_agent','failed_retryable','process_error')
            )))"""
        total = db.execute('SELECT count(*) ' + base, (run_id, *ACTIVITY_KINDS)).fetchone()[0]
        rows = db.execute('SELECT document ' + base + ' ORDER BY position DESC LIMIT ? OFFSET ?',
                          (run_id, *ACTIVITY_KINDS, HISTORY_PAGE_SIZE, offset))
        return [json.loads(row[0]) for row in rows], total
    if tab == 'history':
        total = db.execute('SELECT count(*) ' + base, (run_id,)).fetchone()[0]
        rows = db.execute('SELECT document ' + base + ' ORDER BY position DESC LIMIT ? OFFSET ?',
                          (run_id, HISTORY_PAGE_SIZE, offset))
        return [json.loads(row[0]) for row in rows][::-1], total

    conditions, args = [], [run_id]
    if task_id:
        conditions.append("json_extract(document,'$.detail.tasks')=? OR "
                          "json_extract(document,'$.execution') IN (SELECT value FROM json_each(?))")
        args.extend((task_id, json.dumps(task_attempts)))
    if audit:
        conditions.append("json_extract(document,'$.kind') IN ('route_fired','route_skipped') OR "
                          "(json_extract(document,'$.kind')='plan_built' AND json_array_length(document,'$.detail.omitted')>0)")
    if not conditions:
        return [], 0
    query = 'SELECT document ' + base + ' AND (' + ' OR '.join(conditions) + ') ORDER BY position'
    return [json.loads(row[0]) for row in db.execute(query, args)], 0


def activity_summary(history, run):
    executions = {e['id']: e['task_id'] for e in run['executions']}
    summaries = []
    for entry in history:
        kind = entry['kind']
        detail = entry['detail'] if isinstance(entry.get('detail'), dict) else {}
        task_id = detail.get('tasks') or detail.get('task_id') or detail.get('task') or executions.get(entry.get('execution'))
        if kind == 'budget_exhausted':
            task_id = entry.get('message')
        item = pick(entry, 'id', 'at', 'kind')
        if isinstance(task_id, str) and task_id in run['tasks']:
            item['task_id'] = task_id
        if kind == 'agent_action_change':
            item['operation'] = detail.get('operation')
        if kind == 'transition':
            item['event'] = detail.get('event')
        if kind in ('agent_action_change', 'monitor_retry', 'waiting_user'):
            message = (entry.get('message') or '').strip()
            if message and message != 'User requested retry after checking side effects':
                item['note'] = message[:600]
        summaries.append(item)
    return summaries


def attempt_summary(attempt, node):
    result = pick(attempt, 'id', 'node', 'task_id', 'attempt', 'task_revision', 'status', 'created_at', 'started_at',
                  'completed_at', 'worker_active', 'activity_progress', 'child_run_id', 'child_status', 'communication_id')
    result['implementation'] = pick(attempt['implementation'], 'kind', 'terminal', 'event')
    result['output_readout'] = list(result_readings(node, attempt.get('outputs')))
    if attempt.get('observation_error'):
        result['observation_error'] = True
    if attempt.get('error'):
        result['error'] = str(attempt['error']).rstrip().rsplit('\n', 1)[-1][:512]
    return result


def read_workspace(store, runtime, run_id, query):
    tab = query.get('tab', 'task-history')
    if tab not in TABS:
        raise Invalid('Unknown Run view')
    task_id = query.get('task', '') if tab == 'task-history' else ''
    audit = tab == 'task-history' and query.get('audit') == 'true'
    try:
        offset = int(query.get('offset', '0')) if tab in ('history', 'activity') else 0
    except ValueError as exc:
        raise Invalid('Invalid history offset') from exc
    if not 0 <= offset <= 2**31 - 1:
        raise Invalid('Invalid history offset')
    with store.connection() as db:
        db.execute('BEGIN')
        run = store._load(db, run_id, include_history=False, include_arrangements=False)
        task_attempts = [e['id'] for e in run['executions'] if e['task_id'] == task_id]
        history, total = history_for_panel(db, run_id, tab, task_id, task_attempts, audit, offset)
        changed = [row[0] for row in db.execute("""SELECT DISTINCT json_extract(document, '$.detail.tasks')
                      FROM timeline_parts WHERE run_id=? AND section='history'
                      AND json_type(document, '$.detail.tasks')='text'
                      AND json_type(document, '$.detail.before') NOT IN ('null', 'false')""", (run_id,))] if tab == 'task-history' else []

    view = pick(run, 'id', 'title', 'revision', 'status', 'timeline_id', 'timeline', 'loop_key', 'created_by',
                'archived_at', 'last_activity_at', 'settings', 'superseded_by', 'identity_read_only', 'follow_loop_updates',
                'diagnostics', 'task_dispositions')
    if tab == 'activity':
        history = activity_summary(history, run)
    view.update(status=public_status(run), task_dependencies=task_dependencies(run),
                workspace_view={'tab': tab, 'task': task_id, 'audit': audit, 'offset': offset},
                changed_tasks=changed, history=history, history_total=total, agent_tasks=task_list(run, runtime),
                controls_available=bool(run['notifications'] or any(f['status']=='held' for f in run['hook_firings'])),
                agent_sessions=[pick(o, 'recovery_required', 'resume_execution') for o in run['agent_sessions']],
                simulation=any(b.get('kind') == 'mock' or b.get('simulation') for entry in run['implementations'].values()
                               for b in (entry or {}).get('options', {}).values()))

    loop = run['loop_definition']
    nodes = loop['nodes']
    if tab == 'hooks':
        view['loop_definition'] = loop
        view['implementations'] = run['implementations']
    else:
        view['loop_definition'] = dict(pick(loop, 'id', 'name', 'version'),
                                       nodes={key: pick(node, 'label', 'description', 'readout', 'inputs', 'outputs')
                                              for key, node in nodes.items()}, records=loop['records'] if task_id or tab == 'decisions' else {})
        if audit:
            view['loop_definition']['plans'] = loop.get('plans', {})

    view['tasks'] = {ident: task if ident == task_id else
                     dict(pick(task, 'id', 'status', 'revision', 'created_at', 'execution_id', 'origin', 'wait_reasons', 'budget_error'),
                          spec=pick(task['spec'], 'node', 'round', 'ref')) for ident, task in run['tasks'].items()}
    view['executions'] = [e if e['task_id'] == task_id or (tab == 'decisions' and e['status'] in ('approval','decision','unresolved','waiting'))
                          else attempt_summary(e, nodes.get(e['node'], {})) for e in run['executions']]
    view['records'] = run['records'] if tab == 'records' else {}
    for section in ('notifications', 'events', 'hook_firings'):
        view[section] = run[section] if tab == 'hooks' else []
    return view
