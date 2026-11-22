"""Read the Run page and only the detail panels requested by its browser."""

import json
import re

from loop_anything.interfaces.agent_tasks import task_list
from loop_anything.interfaces.run_results import display_results
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.timeline_plan import task_dependencies
from loop_anything.runtime.timelines import public_status


HISTORY_PAGE_SIZE = 50
TABS = {'task-history', 'activity', 'hooks', 'tasks'}
ACTIVITY_KINDS = (
    'created', 'completed', 'pause', 'resume', 'terminate', 'method_updated',
    'settings', 'agent_action_change', 'monitor_retry', 'retry_applied',
    'waiting_user', 'agent_failure_pause', 'gate', 'release_gate', 'budget_exhausted',
)


def pick(doc, *keys):
    return {key: doc[key] for key in keys if key in doc}


def activity_page(db, run_id, offset):
    kinds = ','.join('?' for _ in ACTIVITY_KINDS)
    base = f"""FROM timeline_parts WHERE run_id=? AND section='history'
        AND (json_extract(document,'$.kind') IN ({kinds}) OR
        (json_extract(document,'$.kind')='transition' AND (
            json_extract(document,'$.detail.to') IN ('fault','unresolved') OR
            json_extract(document,'$.detail.event') IN ('external_rejected','failed_requires_agent','failed_retryable','process_error')
        )))"""
    total = db.execute('SELECT count(*) ' + base, (run_id, *ACTIVITY_KINDS)).fetchone()[0]
    rows = db.execute('SELECT document ' + base + ' ORDER BY position DESC LIMIT ? OFFSET ?',
                      (run_id, *ACTIVITY_KINDS, HISTORY_PAGE_SIZE, offset))
    return [json.loads(row[0]) for row in rows], total


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


def cancellation_reasons(db, run):
    pending = {task['id'] for task in run['tasks'].values() if task['status'] == 'cancelled'}
    if not pending:
        return {}
    executions = {e['id']: e['task_id'] for e in run['executions']}
    rows = db.execute("""SELECT coalesce(json_extract(document, '$.detail.tasks'),
                                         json_extract(document, '$.detail.task_id')),
                                json_extract(document, '$.execution'),
                                json_extract(document, '$.detail.operation'),
                                json_extract(document, '$.message')
                         FROM timeline_parts WHERE run_id=? AND section='history'
                         AND json_extract(document, '$.kind') IN ('agent_action_change', 'monitor_retry')
                         ORDER BY position DESC""", (run['id'],))
    reasons = {}
    for task_id, execution_id, operation, message in rows:
        task_id = task_id or executions.get(execution_id)
        if not isinstance(task_id, str) or task_id not in pending:
            continue
        # A later task change or monitor retry supersedes any earlier cancellation.
        pending.remove(task_id)
        note = message.strip() if operation == 'cancel' and isinstance(message, str) else ''
        if note and note not in ('取消任务', '取消等待'):
            reasons[task_id] = note if len(note) <= 600 else note[:599] + '…'
        if not pending:
            break
    return reasons


def failure_summary(attempt):
    if attempt.get('observation_error'):
        return '采集异常，外部任务状态待确认。'
    if attempt.get('failure_kind') == 'command_start':
        return '执行命令未能启动。'
    if attempt.get('failure_kind') == 'agent_command':
        return 'Agent 命令执行异常。'
    error = attempt.get('error')
    if not error:
        return ''
    # Error messages can embed complete command output. Only copy a filename
    # from a recognized error, and give unknown failures a readable summary.
    error = str(error)
    if 'Agent exited without sealing' in error or 'Agent exited without calling finish' in error:
        return 'Agent 在提交收尾结果前退出。'
    missing = re.search(r"""FileNotFoundError:.*No such file or directory:\s*['"]([^'"\n]+)['"]""", error)
    if missing:
        filename = missing[1].replace('\\', '/').rsplit('/', 1)[-1][:100]
        if filename:
            return f'找不到文件或目录 {filename}。'
    if 'TimeoutExpired' in error or 'timed out' in error:
        return '执行超时。'
    if 'PermissionError:' in error:
        return '执行所需的文件或资源不可访问。'
    return '本次执行失败。'


def task_summary(task):
    result = pick(task, 'id', 'status', 'created_at', 'execution_id')
    result['spec'] = pick(task['spec'], 'node', 'round', 'ref')
    origin = task.get('origin') or {}
    result['origin'] = pick(origin, 'execution', 'agent', 'fallback')
    if isinstance(origin.get('flow_agent'), dict):
        result['origin']['flow_agent'] = pick(origin['flow_agent'], 'task_id')
    if origin.get('issues'):
        result['origin']['issues'] = [pick(issue, 'task_id') for issue in origin['issues'] if isinstance(issue, dict)]
    result['wait_reasons'] = [pick(reason, 'reason', 'action', 'input', 'record')
                              for reason in (task.get('wait_reasons') or [])]
    if task.get('budget_error'):
        result['failure_summary'] = '任务运行预算不足。'
    if task.get('assistance_wait'):
        result['assistance_wait'] = True
    return result


def attempt_summary(attempt, node, records, allow_approval=False, include_content=False):
    result = pick(attempt, 'id', 'node', 'task_id', 'attempt', 'status', 'created_at', 'started_at',
                  'completed_at', 'worker_active', 'activity_progress', 'child_run_id', 'child_status',
                  'communication_id')
    implementation = attempt['implementation']
    result['implementation'] = pick(implementation, 'kind', 'terminal', 'event')
    readings, content = display_results(node, records, attempt.get('outputs'))
    result['output_readout'] = readings
    if content:
        result['has_result_content'] = True
        if include_content:
            result['result_content'] = content
    if isinstance(attempt.get('wait'), dict):
        result['wait'] = pick(attempt['wait'], 'key', 'until', 'deadline')
    if attempt.get('observation_error'):
        result['observation_error'] = True
    summary = failure_summary(attempt)
    if summary:
        result['failure_summary'] = summary
    if allow_approval and attempt['status'] == 'approval' and implementation['kind'] == 'approval':
        result.update(pick(attempt, 'token'))
    return result


def output_schemas(loop, node):
    return {output['record_type']: loop['records'][output['record_type']]
            for output in node.get('outputs', {}).values()}


def attention_summary(run, runtime):
    items = task_list(run, runtime)
    result = {'items': [], 'waiting': []}
    for item in items['items']:
        summary = pick(item, 'id', 'task_id', 'kind', 'notification_id')
        reason = item.get('reason')
        if isinstance(reason, dict):
            summary['reason'] = pick(reason, 'kind')
        elif item['kind'] == 'request' and isinstance(reason, str):
            summary['reason'] = reason
        result['items'].append(summary)
    result['waiting'] = [pick(item, 'id', 'status', 'notification_id') for item in items['waiting']
                         if item.get('notification_id')]
    return result


def notification_view(view, run):
    settings = run['settings']
    view['settings']['bindings'] = settings.get('bindings', {})
    view['settings']['hooks'] = [pick(hook, 'enabled', 'action', 'phase', 'target', 'event', 'to', 'message', 'route')
                                 for hook in settings.get('hooks', []) if hook.get('action') == 'notify']
    implementations = {}
    for node, definition in run['implementations'].items():
        if not definition:
            continue
        entry = pick(definition, 'default')
        entry['options'] = {}
        for key, config in definition.get('options', {}).items():
            summary = pick(config, 'kind')
            if config.get('lifecycle'):
                summary['lifecycle'] = {'transitions': [
                    dict(pick(rule, 'from', 'to', 'event', 'when'), notify=[
                        pick(notice, 'message', 'route', 'reply') for notice in rule['notify']
                    ]) for rule in config['lifecycle']['transitions'] if rule.get('notify')
                ]}
            entry['options'][key] = summary
        implementations[node] = entry
    view['implementations'] = implementations
    for notice in run['notifications']:
        item = pick(notice, 'id', 'tasks', 'message', 'route', 'status', 'at', 'reply')
        if notice.get('sender'):
            item['sender'] = pick(notice['sender'], 'label')
        view['notifications'].append(item)
    view['events'] = [pick(event, 'name', 'key') for event in run['events']]
    view['hook_firings'] = [pick(firing, 'id', 'status', 'tasks') for firing in run['hook_firings']
                            if firing['status'] == 'held']


def read_workspace(store, runtime, run_id, query):
    tab = query.get('tab', 'task-history')
    if tab not in TABS:
        raise Invalid('Unknown Run view')
    task_id = query.get('task', '') if tab == 'task-history' else ''
    try:
        offset = int(query.get('offset', '0')) if tab == 'activity' else 0
    except ValueError as exc:
        raise Invalid('Invalid history offset') from exc
    if not 0 <= offset <= 2**31 - 1:
        raise Invalid('Invalid history offset')
    with store.connection() as db:
        db.execute('BEGIN')
        run = store._load(db, run_id, include_history=False, include_arrangements=False)
        reasons = cancellation_reasons(db, run) if tab == 'task-history' else {}
        history, total = activity_page(db, run_id, offset) if tab == 'activity' else ([], 0)
        changed = [row[0] for row in db.execute("""SELECT DISTINCT json_extract(document, '$.detail.tasks')
                      FROM timeline_parts WHERE run_id=? AND section='history'
                      AND json_type(document, '$.detail.tasks')='text'
                      AND json_type(document, '$.detail.before') NOT IN ('null', 'false')""", (run_id,))] if tab == 'task-history' else []

    view = pick(run, 'id', 'title', 'revision', 'status', 'timeline_id', 'loop_key', 'created_by',
                'archived_at', 'last_activity_at', 'superseded_by', 'identity_read_only', 'follow_loop_updates')
    view['timeline'] = pick(run.get('timeline') or {}, 'active_run_id', 'title', 'objective')
    settings = run['settings']
    view['settings'] = dict(pick(settings, 'revision', 'objective', 'constraints', 'notification_route'),
                            completion_rule=True if settings.get('completion_rule') is not None else None,
                            termination_signal=bool(settings.get('termination_signal')),
                            has_notification_command=bool(settings.get('notification_command')))
    view.update(status=public_status(run), task_dependencies=task_dependencies(run),
                workspace_view={'tab': tab, 'task': '', 'offset': offset},
                changed_tasks=changed, history=activity_summary(history, run) if history else [], history_total=total,
                agent_tasks=attention_summary(run, runtime), has_diagnostics=bool(run['diagnostics']),
                controls_available=bool(run['notifications'] or any(f['status']=='held' for f in run['hook_firings'])),
                agent_sessions=[pick(o, 'recovery_required', 'resume_execution') for o in run['agent_sessions']],
                simulation=any(b.get('kind') == 'mock' or b.get('simulation') for entry in run['implementations'].values()
                               for b in (entry or {}).get('options', {}).values()))
    view['task_dispositions'] = {ident: pick(disposition, 'reason') for ident, disposition in run.get('task_dispositions', {}).items()
                                 if run['tasks'].get(ident, {}).get('status') == 'waiting_user'}
    loop = run['loop_definition']
    nodes = loop['nodes']
    selected_execution = run['tasks'].get(task_id, {}).get('execution_id')
    waiting = next((e for e in run['executions'] if e['id'] == selected_execution and
                    e['implementation']['kind'] in ('approval', 'event') and e['status'] in ('approval', 'waiting')), None)
    view['loop_definition'] = dict(pick(loop, 'id', 'name', 'version'),
                                   nodes={key: pick(node, 'label', 'readout', 'outputs') for key, node in nodes.items()},
                                   records=output_schemas(loop, nodes[waiting['node']]) if waiting else {})
    view['tasks'] = {ident: task_summary(task) for ident, task in run['tasks'].items()}
    for ident, reason in reasons.items():
        view['tasks'][ident]['cancellation_reason'] = reason
    view['executions'] = [attempt_summary(e, nodes.get(e['node'], {}), loop['records'],
                                          allow_approval=e['id'] == selected_execution, include_content=e['task_id'] == task_id)
                          for e in run['executions']]
    if waiting or any(e.get('result_content') for e in view['executions']):
        view['workspace_view']['task'] = task_id
    view.update(notifications=[], events=[], hook_firings=[])
    if tab == 'hooks':
        notification_view(view, run)
    return view
