from loop_anything.runtime.implementations import selected, choose, options, default_id, check_selection
"""Scoped Agent operation rights and deterministic task inspection. No business decisions."""
import argparse
import copy
import json
import time
from types import SimpleNamespace
from loop_anything.runtime.model import Conflict, Invalid, digest, contract
from loop_anything.runtime.store import Store, uid
from loop_anything.runtime.task_scope import owner_for, require_scope, scope_available, scope_for, contains, attach_tasks

PENDING = {'planned', 'ready', 'blocked', 'held'}
ENDED = {'completed', 'cancelled', 'stale', 'skipped'}


def object_schema(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required,
            'additionalProperties': False}

def agent_calls(run):
    return sum(h['kind'] == 'agent_acquired' and h['detail']['kind'] == 'background' for h in run['history'])


def node_for(run, node_id):
    return run['loop_definition']['nodes'][node_id]


def require_owner(run, token):
    owner = owner_for(run, token)
    if not owner:
        raise Conflict('This Agent does not hold an operation right')
    return owner


def guard_write(run, token=None, task_id=None):
    """Protect the affected subtree; global settings require a global scope."""
    if token:
        owner = require_owner(run, token)
        require_scope(run, owner, task_id)
    if not scope_available(run, task_id, token):
        raise Conflict('Another Agent is operating this branch')


def acquire_in_run(run, kind, token=None, execution_id=None, task_id=None):
    if not run.get('operator_protocol'):
        raise Invalid('Historical Run has no operator protocol; start a new Run')
    if run['status'] in ('completed', 'terminated'):
        raise Conflict('Run ended')
    if execution_id:
        task_id = execution(run, execution_id)['task_id']
    if task_id is not None and task_id not in run['tasks']:
        raise Invalid('Unknown scope task')
    scope = scope_for(run, run['tasks'][task_id]) if kind == 'background' else task_id
    if not scope_available(run, scope):
        raise Conflict('Another Agent owns an overlapping branch')
    owner = dict(token=token or uid('operator'), kind=kind, execution_id=execution_id,
                 task_id=task_id or (run['loop_definition']['seed']['id'] if not run['initialized'] else None), scope_task=scope, acquired_at=time.time())
    run.setdefault('agent_sessions', []).append(owner)
    if scope is None:
        run.pop('attention_error', None)
    Store.log(run, 'agent_acquired', 'Agent operation right acquired', execution_id,
              {'kind': kind, 'scope_task': scope, 'task_id': task_id})
    return owner


def acquire(store, run_id, task_id=None, _db=None):
    with store.edit(run_id, _db=_db) as run:
        owner = copy.deepcopy(acquire_in_run(run, 'interactive', task_id=task_id))
    return owner


def recover_owner(store, run_id, token, confirmed_stopped=False):
    """Explicit local recovery only; never expire a possibly live Agent automatically."""
    with store.edit(run_id) as run:
        owner = require_owner(run, token)
        if confirmed_stopped is not True:
            raise Conflict('Verify the previous Agent stopped before releasing recovered ownership')
        release_in_run(run, token)
        if owner.get('recovery_required'):
            from loop_anything.runtime.timeline_runtime import agent_exited
            agent_exited(run, RunTools(store, run_id, token).runtime, 'Previous Agent confirmed stopped after interruption', owner.get('scope_task'))


def user_request(store, run_id, text, task_id=None, operator_token=None):
    if not isinstance(text, str) or not text.strip():
        raise Invalid('User request text is required')
    with store.edit(run_id) as run:
        guard_write(run, operator_token)
        if run['status'] in ('completed', 'terminated'):
            raise Conflict('Run ended')
        if task_id:
            run.get('task_dispositions', {}).pop(task_id, None)
        request = {'id': uid('request'), 'text': text, 'status': 'pending'}
        run.setdefault('user_requests', []).append(request)
        Store.log(run, 'user_request', text, detail={'request': request['id']})
    return request


def release_in_run(run, token):
    owner = require_owner(run, token)
    Store.log(run, 'agent_released', 'Run operation right released', owner.get('execution_id'))
    run['agent_sessions'].remove(owner)


def gated(run, tasks):
    for hook in run['settings']['hooks']:
        if not hook.get('enabled', True) or hook['action'] != 'pause' or hook['phase'] != 'before':
            continue
        target = hook['target']
        if target.get('node', tasks['spec']['node']) != tasks['spec']['node'] or target.get('tasks', tasks['id']) != tasks['id']:
            continue
        firings = [f for f in run['hook_firings'] if f['hook'] == hook['id']]
        current = next((f for f in firings if f['tasks'] == tasks['id']), None)
        if current and current['status'] == 'released':
            continue
        if not current and hook['frequency'] == 'once' and firings:
            continue
        return True
    return False


def task_list(run, runtime, owner=None):
    """Read-only derivation used by CLI, tools and Engine's default transition."""
    if run['status'] in ('completed', 'terminated'):
        return {'run_id': run['id'], 'revision': run['revision'], 'authorization': run['settings'].get('authorization', ''),
                'items': [], 'waiting': [], 'has_tasks': False, 'state': run['status'],
                'owners': [{k: v for k, v in o.items() if k != 'token'} for o in run.get('agent_sessions', [])]}
    view = copy.deepcopy(run)
    for tasks in view['tasks'].values():
        if tasks['status'] in PENDING:
            _, _, missing = runtime.resolve_inputs(view, tasks)
            tasks['wait_reasons'] = missing
            tasks['status'] = 'blocked' if missing else 'held' if gated(view, tasks) else 'ready'
    runtime.diagnose(view)
    items, waiting = [], []
    dispositions = run.get('task_dispositions', {})
    def add(item):
        if owner and not contains(run, owner.get('scope_task'), item.get('task_id')):
            return
        active = run['tasks'].get(item.get('task_id'), {})
        current = next((e for e in run['executions'] if e['id'] == active.get('execution_id')), {})
        if item['kind'] == 'task' and current.get('token') and owner_for(run, current['token']) and (not owner or current['token'] != owner.get('token')):
            waiting.append(dict(item, kind='waiting', reason='Another Agent is executing this task'))
            return
        disposition = dispositions.get(item['id'])
        if disposition:
            waiting.append(dict(item, **disposition))
        else:
            items.append(item)
    for tasks in view['tasks'].values():
        implementation = selected(run, tasks)[1] or {}
        if tasks['status'] == 'fault':
            e = next((x for x in run['executions'] if x['id'] == tasks.get('execution_id')), {})
            add({'id': 'fault:' + tasks['id'] + ':' + str(tasks.get('attempts', 0)), 'kind': 'unexpected',
                 'task_id': tasks['id'], 'reason': e.get('error') or tasks.get('budget_error') or 'Task failed'})
        elif tasks['status'] not in PENDING | ENDED | {'executing', 'decision', 'waiting', 'approval', 'waiting_user'}:
            add({'id': 'state:' + tasks['id'] + ':' + tasks['status'], 'kind': 'unexpected', 'task_id': tasks['id'], 'reason': 'Unknown Task state'})
        elif implementation.get('kind') == 'agent' and (tasks['status'] in ('decision', 'executing') or (tasks['status'] == 'ready' and run['status'] == 'running')):
            add({'id': 'task:' + tasks['id'], 'kind': 'task', 'task_id': tasks['id'],
                 'node': tasks['spec']['node'], 'reason': node_for(run, tasks['spec']['node'])['instructions']})
        elif tasks['status'] not in ENDED:
            waiting.append({'id': 'task:' + tasks['id'], 'kind': 'waiting', 'task_id': tasks['id'], 'status': tasks['status'],
                            'reason': tasks.get('wait_reasons') or 'Script, event, approval or pause gate'})
    for diagnostic in view['diagnostics']:
        if diagnostic['kind'] == 'upstream_fault':
            continue
        item = {'id': 'issue:' + digest(diagnostic)[:20], 'kind': 'unexpected', 'reason': diagnostic}
        if diagnostic.get('tasks'):
            item['task_id'] = diagnostic['tasks']
        add(item)
    for event in run['events']:
        known = any(b.get('kind') == 'event' and b.get('event') == event['name'] for entry in run['implementations'].values() for b in options(entry).values())
        if event.get('consumed_by') == 'rejected' or (not known and not event.get('consumed_by')):
            add({'id': 'event:' + event['id'], 'kind': 'unexpected', 'reason': 'Unrecognized/rejected event', 'event': event})
    if run.get('attention_error'):
        add({'id': 'agent-exit:' + digest(run['attention_error'])[:20], 'kind': 'unexpected', 'reason': run['attention_error']})
    for request in run.get('user_requests', []):
        if request['status'] == 'pending':
            add({'id': request['id'], 'kind': 'request', 'reason': request['text']})
    for notification in run.get('notifications', []):
        if notification['status'] == 'fault':
            add({'id': 'notification:' + notification['id'] + ':' + str(notification['attempt']),
                 'kind': 'unexpected', 'notification_id': notification['id'], 'reason': notification.get('error', 'Notification delivery failed')})
    return {'run_id': run['id'], 'revision': run['revision'], 'authorization': run['settings'].get('authorization', ''),
            'items': items, 'waiting': [i for i in waiting if not owner or contains(run, owner.get('scope_task'), i.get('task_id'))], 'has_tasks': bool(items),
            'state': 'unexpected' if any(i['kind'] == 'unexpected' for i in items) else 'normal',
            'owners': [{k: v for k, v in o.items() if k != 'token'} for o in run.get('agent_sessions', [])]}


def execution(run, execution_id):
    return next(e for e in run['executions'] if e['id'] == execution_id)


def change_task_in_run(run, arguments):
    tasks = run['tasks'].get(arguments['task_id'])
    if not tasks:
        raise Invalid('Unknown business Task')
    before = copy.deepcopy(tasks['spec'])
    op = arguments['operation']
    if not arguments['reason'].strip():
        raise Invalid('A reason is required')
    active_script = tasks['status'] in ('executing', 'waiting', 'decision')
    if active_script or (tasks['status'] == 'approval' and op != 'cancel') or tasks['status'] == 'completed':
        raise Conflict('Cannot change dispatched side effects or completed tasks')
    if op == 'update':
        if tasks['status'] not in PENDING or tasks.get('execution_id'):
            raise Conflict('Only unstarted Tasks can be updated')
        from loop_anything.runtime.timeline_model import check_task
        spec = dict(tasks['spec'])
        spec.pop('policy', None)
        for field in ('inputs', 'parameters', 'implementation', 'after'):
            if field in arguments:
                spec[field] = (None if field == 'implementation' and arguments[field] == '' else copy.deepcopy(arguments[field]))
        check_task(run['loop_definition'], spec)
        check_selection(run, spec)
        tasks.update(spec=spec, status='planned')
    elif op == 'retry':
        if tasks['status'] not in ('fault', 'stale', 'waiting_user', 'cancelled') or tasks.get('budget_error'):
            raise Conflict('Only failed/stale tasks can retry; budgets remain enforced')
        if tasks.get('execution_id'):
            execution(run, tasks['execution_id'])['token'] = None
        from loop_anything.runtime.timeline_model import check_task
        for field in ('inputs', 'parameters', 'implementation', 'after'):
            if field in arguments:
                tasks['spec'][field] = (None if field == 'implementation' and arguments[field] == '' else copy.deepcopy(arguments[field]))
        tasks['spec'].pop('policy', None)
        check_task(run['loop_definition'], tasks['spec'])
        check_selection(run, tasks['spec'])
        tasks.update(status='planned', execution_id=None, settings_revision=run['settings']['revision'])
    else:
        tasks['status'] = 'cancelled'
        if tasks.get('execution_id'):
            execution(run, tasks['execution_id']).update(status='cancelled', token=None)
    run.get('task_dispositions', {}).pop('task:' + tasks['id'], None)
    Store.log(run, 'agent_action_change', arguments['reason'], detail={'tasks': tasks['id'], 'operation': op, 'before': before, 'after': copy.deepcopy(tasks['spec'])})


def apply_task_edit(run, tool, arguments, origin, owner=None):
    from loop_anything.runtime.timeline_plan import add_task, build_plan
    if not run.get('operator_protocol'):
        raise Conflict('Historical Run is inspect-only')
    if run['status'] in ('completed', 'terminated'):
        raise Conflict('Run ended')
    if tool == 'change_task':
        guard_write(run, owner['token'] if owner else None, arguments['task_id'])
        change_task_in_run(run, arguments)
        return {'updated': True}
    if tool == 'build_plan':
        specs = build_plan(run['loop_definition'], arguments['name'], 'operator:' + ((owner['scope_task'] + ':') if owner and owner.get('scope_task') else '') + arguments['key'],
                           arguments['values'], arguments.get('steps'), arguments.get('round'))
    elif tool == 'add_task':
        node = run['loop_definition']['nodes'].get(arguments['node_id'])
        if not node or node.get('initialize_timeline'):
            raise Invalid('Choose a declared non-entry node')
        if not arguments['key'].strip():
            raise Invalid('Task key must be nonempty')
        ident = 'task-' + digest([owner['scope_task'], arguments['key']] if owner and owner.get('scope_task') else arguments['key'])[:16]
        spec = {k: copy.deepcopy(arguments[k]) for k in ('inputs', 'parameters', 'after', 'implementation', 'round') if k in arguments}
        if not spec.get('implementation'):
            spec.pop('implementation', None)
        spec.update(id=ident, node=arguments['node_id'], outputs={p: {'id': ident + '.' + p} for p in node['outputs']})
        specs = [spec]
    else:
        raise Invalid('Unknown task edit')
    parent = arguments.get('parent_id', (owner.get('scope_task') or owner.get('task_id')) if owner else None)
    specs = attach_tasks(run, specs, parent, owner)
    for spec in specs:
        guard_write(run, owner['token'] if owner else None, spec['parent_id'])
        add_task(run, spec, origin)
    return {'tasks': specs}


def edit_tasks(store, run_id, changes, revision, token=None, preview=False):
    """UI edits/preview use the same contracts as Agent task tools."""
    definitions = {d['name']: d['inputSchema'] for d in RunTools(store, run_id, token).definitions()}
    if not isinstance(changes, list) or not changes:
        raise Invalid('Supply task changes')
    if type(preview) is not bool:
        raise Invalid('preview must be boolean')

    def apply(run):
        owner = require_owner(run, token) if token else None
        if type(revision) is not int or revision != run['revision']:
            raise Conflict('Run changed; reload the plan before applying edits')
        for change in changes:
            tool = change.get('tool')
            if tool not in ('add_task', 'change_task', 'build_plan'):
                raise Invalid('Unknown task edit')
            contract(change.get('arguments'), definitions[tool], 'arguments')
            apply_task_edit(run, tool, change['arguments'], {'user': True}, owner)

    if preview:
        from loop_anything.runtime.timeline_plan import validate_task_dependencies
        run = store.get(run_id)
        before = copy.deepcopy(run['tasks'])
        apply(run)
        validate_task_dependencies(run)
        return {'changes': [{'task_id': k, 'before': before.get(k), 'after': v}
                            for k, v in run['tasks'].items() if v != before.get(k)]}
    with store.edit(run_id) as run:
        apply(run)
    return store.get(run_id)


class RunTools:
    """Read current Run state; mutate only with an acquired operation scope."""
    def __init__(self, store, run_id, token=None):
        from loop_anything.runtime.timeline_runtime import TimelineRuntime
        self.store, self.run_id, self.token = store, run_id, token
        self.runtime = TimelineRuntime(SimpleNamespace(store=store, execution=execution))

    def definitions(self):
        text, obj = {'type': 'string'}, {'type': 'object'}
        defs = [
            ('next_tasks', 'Read current work and waiting reasons without acquiring rights. With a token, restrict the work view to that operation scope. Other active Agents are waiting, not tasks to take over.', {}, [], True),
            ('read_timeline', 'Read the latest shared Timeline without acquiring rights. read_only=true grants no write permission; scope_task=null means global rights only when read_only=false. Read before acquiring and re-read before editing.', {}, [], True),
            ('read_record', 'Read a committed record on demand.', {'id': text, 'revision': {'type': 'integer'}}, ['id'], True),
            ('read_task', 'Read this Task input sources, live values, output contract and node Skill before completing it.', {'task_id': text}, ['task_id'], True),
            ('read_plans', 'Read loop_definition batch templates and values schemas.', {}, [], True),
            ('build_plan', 'Write a batch directly to Timeline. Omit steps with steps.<key>.skip=true; explicitly bind reused inputs. Stable key deduplicates. Optional round is a display label only; it never serializes execution.', {'name': text, 'key': text, 'values': obj, 'steps': obj, 'round': text, 'parent_id': text}, ['name', 'key', 'values'], False),
            ('add_task', 'Add one task from a declared non-entry node. Stable key deduplicates; outputs get record identities automatically. after names predecessor tasks. No execution starts inside this tool.', {'key': text, 'node_id': text, 'inputs': obj, 'parameters': obj, 'after': {'type': 'array', 'items': text}, 'implementation': text, 'round': text, 'parent_id': text}, ['key', 'node_id', 'inputs'], False),
            ('complete_task', 'Submit every declared output for an Agent Task using task_version from read_task. Supply settings only for initialization. Success commits immediately; failure commits nothing. Creating future tasks is not a substitute for this result. Call next_tasks again afterward.', {'task_id': text, 'task_version': text, 'envelope': obj}, ['task_id', 'task_version', 'envelope'], False),
            ('change_settings', 'Write authorized Timeline changes, including bindings (node ID to candidate ID or null, replaces the Run selection map), completion_rule (deterministic expression) or termination_signal (reason text). Engine applies terminal transitions; finish only releases Agent ownership. Changing requirements does not invalidate tasks or results. fallback_node selects a declared fallback node; empty/null disables it. notification_command sets this Run sender argv (empty inherits the Loop sender); only a global operator may change it. Already attempted notifications keep their original sender on retry. Only the interactive user Agent may change authorization.', {'revision': {'type': 'integer'}, 'change': obj}, ['revision', 'change'], False),
            ('command', 'Use existing Run controls only within user authorization. Pausing does not cancel external side effects.', {'action': {'type': 'string', 'enum': ['pause', 'resume', 'terminate', 'release_gate', 'retry_notification']}, 'hook_firing': text, 'notification_id': text}, ['action'], False),
            ('change_task', 'Choose a candidate with implementation (empty string inherits the Run default). Correct unstarted Task inputs/parameters, cancel tasks, or retry a failed Task only after checking side effects. Cannot alter an executing script.', {'task_id': text, 'operation': {'type': 'string', 'enum': ['update', 'cancel', 'retry']}, 'inputs': obj, 'parameters': obj, 'implementation': text, 'after': {'type': 'array', 'items': text}, 'reason': text}, ['task_id', 'operation', 'reason'], False),
            ('defer_task', 'Record why an item must wait for user authorization/input. This is not successful execution and must not hide tasks you can do.', {'task_id': text, 'reason': text}, ['task_id', 'reason'], False),
            ('resolve_request', 'Mark a user request fulfilled only after its changes are applied.', {'task_id': text}, ['task_id'], False),
            ('finish', 'Finish after your wake-up task is completed/deferred and in-scope issues are handled. Ready descendant tasks may remain for Engine dispatch. Releases only this token and scope.', {}, [], False)]
        return [{'name': n, 'description': d, 'inputSchema': object_schema(p, required),
                 'annotations': {'readOnlyHint': readonly}} for n, d, p, required, readonly in defs]

    def respond(self, name, arguments):
        try:
            return dict(ok=True, **self.call(name, arguments))
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            return {'ok': False, 'error': {'code': 'conflict' if isinstance(exc, Conflict) else 'invalid_request', 'message': str(exc)}}

    def call(self, name, arguments):
        definitions = {d['name']: d for d in self.definitions()}
        if name not in definitions:
            raise Invalid('Unknown Run tool')
        contract(arguments, definitions[name]['inputSchema'], 'arguments')
        if definitions[name]['annotations']['readOnlyHint']:
            run = self.store.get(self.run_id)
            owner = require_owner(run, self.token) if self.token is not None else None
            return self._read(run, name, arguments, owner)
        with self.store.edit(self.run_id) as run:
            owner = require_owner(run, self.token)
            if name in ('complete_task', 'change_task'):
                tasks = run['tasks'].get(arguments['task_id'])
                if not tasks:
                    raise Invalid('Unknown business Task')
            if run['status'] in ('terminated', 'completed') and name != 'finish':
                raise Conflict('Run ended')
            if name in ('build_plan', 'add_task', 'change_task'):
                return apply_task_edit(run, name, arguments, {'agent': owner.get('execution_id') or 'interactive'}, owner)
            if name == 'complete_task':
                require_scope(run, owner, tasks['id'])
                current = execution(run, tasks['execution_id']) if tasks.get('execution_id') else None
                if current and current.get('token') != self.token and owner_for(run, current.get('token')):
                    raise Conflict('Another Agent owns this execution')
                implementation = selected(run, tasks)[1] or {}
                if implementation.get('kind') != 'agent':
                    raise Invalid('Agent cannot fabricate script/event/approval results')
                if tasks['status'] in ENDED or tasks['status'] == 'fault':
                    raise Conflict('Task must be pending or owned; inspect/retry failures first')
                values, sources, missing = self.runtime.resolve_inputs(run, tasks)
                if missing or gated(run, tasks):
                    raise Conflict('Task inputs or gate are not ready')
                if arguments['task_version'] != digest([tasks['spec'], values, sources, selected(run, tasks)]):
                    raise Conflict('Task inputs changed; read_task again and reconsider this result')
                self.runtime.apply_hooks(run, tasks, 'before')
                if tasks.get('execution_id'):
                    e = execution(run, tasks['execution_id'])
                    e.update(inputs=values, sources=sources, token=self.token)
                else:
                    if run['status'] != 'running':
                        raise Conflict('Run is paused; edit its plan without starting another Task')
                    self.runtime.check_budget(run, tasks)
                    e = self.runtime.new_execution(run, tasks, implementation, values, sources)
                    e['token'] = self.token
                    e.update(status='decision')
                    tasks['status'] = 'decision'
                if e.get('started_at') is None:
                    e['started_at'] = time.time()
                self.runtime.commit_in_run(run, e, arguments['envelope'])
                return {'completed': tasks['id'], 'next': 'next_tasks'}
            if name == 'change_settings':
                # Use the same transaction through the runtime's pure update helper.
                self.runtime.change_settings_in_run(run, arguments['revision'], arguments['change'], self.token)
            elif name == 'command':
                self.runtime.command_in_run(run, arguments['action'], hook_firing=arguments.get('hook_firing'),
                                            notification_id=arguments.get('notification_id'), operator_token=self.token)
            elif name == 'defer_task':
                tasks = task_list(run, self.runtime, owner)
                if not any(t['id'] == arguments['task_id'] for t in tasks['items']) or not arguments['reason'].strip():
                    raise Invalid('Choose a current task and explain the required user input')
                run.setdefault('task_dispositions', {})[arguments['task_id']] = {'status': 'waiting_user', 'reason': arguments['reason']}
                if arguments['task_id'].startswith('task:'):
                    tasks = run['tasks'][arguments['task_id'].split(':', 1)[1]]
                    tasks['status'] = 'waiting_user'
                    if tasks.get('execution_id'):
                        execution(run, tasks['execution_id'])['status'] = 'waiting_user'
                Store.log(run, 'waiting_user', arguments['reason'], detail={'task': arguments['task_id']})
            elif name == 'resolve_request':
                require_scope(run, owner)
                request = next((r for r in run.get('user_requests', []) if r['id'] == arguments['task_id']), None)
                if not request:
                    raise Invalid('Unknown user request')
                request['status'] = 'completed'
            elif name == 'finish':
                tasks = task_list(run, self.runtime, owner)
                unresolved = [i for i in tasks['items'] if i['kind'] != 'task' or i.get('task_id') == owner.get('task_id')]
                if unresolved and not run['settings'].get('termination_signal', '').strip():
                    raise Conflict('Run still has actionable tasks: ' + ', '.join(t['id'] for t in tasks['items']))
                release_in_run(run, self.token)
                return {'finished': True}
            return {'updated': True, 'next': 'next_tasks'}

    def _read(self, run, name, arguments, owner):
        from loop_anything.packaging.packages import resolve_skill
        if name == 'next_tasks':
            return task_list(run, self.runtime, owner)
        if name == 'read_timeline':
            return {'settings': run['settings'], 'handbook': resolve_skill(self.store.filename, run['loop_key'], run['loop_definition'].get('handbook', {})),
                    'records': [{'id': rid, 'type': rows[-1]['type'], 'revision': rows[-1]['revision']} for rid, rows in run['records'].items() if rows], 'implementations': {n: {'default': default_id(entry), 'options': list(options(entry))} for n, entry in run['implementations'].items()}, 'status': run['status'], 'tasks': task_list(run, self.runtime, owner), 'run_id': run['id'], 'revision': run['revision'], 'read_only': owner is None, 'scope_task': owner.get('scope_task') if owner else None}
        if name == 'read_plans':
            return {'plans': run['loop_definition'].get('plans', {})}
        if name == 'read_record':
            from loop_anything.runtime.timeline_runtime import record_version
            record = record_version(run, arguments['id'], arguments.get('revision'))
            if record is None:
                raise Invalid('Record not found')
            return {'record': record}
        if name == 'read_task':
            tasks = run['tasks'].get(arguments['task_id'])
            if not tasks:
                raise Invalid('Unknown business Task')
            node = node_for(run, tasks['spec']['node'])
            values, sources, missing = self.runtime.resolve_inputs(run, tasks)
            return {'task': tasks, 'inputs': values, 'sources': sources, 'missing': missing,
                    'task_version': digest([tasks['spec'], values, sources, selected(run, tasks)]),
                    'implementation_id': selected(run, tasks)[0], 'implementation': selected(run, tasks)[1],
                    'implementation_options': options(run['implementations'].get(tasks['spec']['node'])),
                    'instructions': node['instructions'], 'skills': [resolve_skill(self.store.filename, run['loop_key'], skill) for skill in node.get('skills', [])],
                    'initialize_timeline': bool(node.get('initialize_timeline')),
                    'settings_schema': node.get('agent_settings_schema') if node.get('initialize_timeline') else None,
                    'assertions': node.get('assertions', []),
                    'outputs': {p: run['loop_definition']['records'][s['record_type']] for p, s in node['outputs'].items()},
                    'authorization': run['settings'].get('authorization', '')}


def main():
    parser = argparse.ArgumentParser(description='Inspect Run tasks or use explicit Agent operation rights')
    parser.add_argument('--db', required=True)
    parser.add_argument('run_id')
    parser.add_argument('--acquire', action='store_true')
    parser.add_argument('--token')
    parser.add_argument('--release-stopped', action='store_true', help='Recovery only: confirm the previous Agent process has stopped')
    parser.add_argument('--tool', default='next_tasks')
    parser.add_argument('--arguments', default='{}')
    args = parser.parse_args()
    store = Store(args.db)
    if args.acquire:
        result = acquire(store, args.run_id)
    elif args.release_stopped:
        recover_owner(store, args.run_id, args.token, confirmed_stopped=True)
        result = {'released': True}
    else:
        tools = RunTools(store, args.run_id, args.token)
        if args.tool == 'list':
            if args.token is not None:
                require_owner(store.get(args.run_id), args.token)
            result = tools.definitions()
        else:
            result = tools.respond(args.tool, json.loads(args.arguments))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
