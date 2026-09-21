"""Programmable Timeline v2: advance existing Tasks and accept their results.

The module contains no application names, simulated outcomes or domain policies.
"""
import copy
from loop_anything.runtime.agent_prompt import task_context, render_prompt, mask_prompt
import json
import time
import math
from loop_anything.paths import platform_skill_directory
from loop_anything.runtime.lifecycle import definition as lifecycle_definition
from loop_anything.runtime.model import digest
from loop_anything.runtime.timeline_model import (SEMANTIC_FIELDS, ENDING_FIELDS, check_task, settings_defaults,
                            validate_settings, validate_result, validate_fallback)
from loop_anything.runtime.model import Conflict, Invalid, contract, path
from loop_anything.runtime.store import Store, uid
from loop_anything.runtime.host_runtime import run_command, CommandNotStopped
from loop_anything.runtime.checks import check_assertions, evaluate
from loop_anything.runtime.implementations import selected, choose, validate_bindings
from loop_anything.runtime.timeline_plan import add_task
from loop_anything.runtime.task_scope import owner_for, scope_for, scope_available, require_scope, attach_tasks
from loop_anything.interfaces.agent_tasks import (node_for, acquire_in_run, require_owner,
                          guard_write, release_in_run, task_list, agent_calls)

PENDING = {'planned', 'ready', 'blocked', 'held'}
IN_FLIGHT = {'executing', 'decision', 'approval', 'waiting'}
END = {'completed', 'cancelled', 'stale', 'skipped'}


def initialize_run(run):
    run.update(schema_version=2, operator_protocol=1, agent_sessions=[], task_dispositions={}, user_requests=[], settings=settings_defaults(run['title']), records={}, tasks={},
               notifications=[], hook_firings=[], diagnostics=[], initialized=False, agent_failures=0)
    run['settings']['fallback_node'] = run['loop_definition'].get('fallback_node')
    run['settings']['global_agent_node'] = run['loop_definition'].get('global_agent_node')
    # Run creation is a Timeline write, not a scheduler responsibility.
    add_task(run, run['loop_definition']['seed'], {'entry': True})


def latest(run, record_id):
    versions = run['records'].get(record_id, [])
    return versions[-1] if versions else None


def record_version(run, record_id, revision=None):
    versions = run['records'].get(record_id, [])
    if not versions:
        return None
    if revision is None:
        return versions[-1]
    return next((v for v in versions if v['revision'] == revision), None)


def end_condition(run):
    """Two explicit Timeline paths to the terminal state; no inferred completion task."""
    signal = run['settings'].get('termination_signal', '').strip()
    if signal:
        return signal, None
    rule = run['settings'].get('completion_rule')
    if rule is None:
        return None, None
    context = {'settings': run['settings'], 'inputs': run['inputs'],
               'records': {key: versions[-1]['value'] for key, versions in run['records'].items() if versions},
               'completed': {node: sum(w['spec']['node'] == node and w['status'] == 'completed' for w in run['tasks'].values())
                             for node in run['loop_definition']['nodes']},
               'active_tasks': sum(w['status'] not in END for w in run['tasks'].values())}
    try:
        result = evaluate(rule, context)
        if type(result) is not bool:
            raise Invalid('Completion rule must evaluate to a boolean')
        return ('Timeline completion rule matched' if result else None), None
    except (KeyError, IndexError):
        return None, None  # A referenced result has not arrived yet.
    except (TypeError, ValueError) as exc:
        return None, str(exc)


def agent_exited(run, runtime, error=None, scope_task=None):
    """Count only confirmed exits in the same unresolved abnormal episode."""
    if run['status'] != 'running':
        return
    counter = run if scope_task is None else run['tasks'][scope_task]
    work = task_list(run, runtime, {'scope_task': scope_task})
    abnormal = work['state'] == 'unexpected' or (scope_task is None and bool(run.get('attention_error')))
    if not abnormal:
        counter['agent_failures'] = 0
        return
    if scope_task is None:
        # Global recovery continues the longest unresolved branch failure chain.
        counter['agent_failures'] = max([counter.get('agent_failures', 0)] + [
            run['tasks'].get(item.get('task_id'), {}).get('agent_failures', 0)
            for item in work['items'] if item['kind'] == 'unexpected'])
    error = error or 'Agent exited while the Loop remained abnormal'
    counter['agent_failures'] = counter.get('agent_failures', 0) + 1
    if counter['agent_failures'] >= 3:
        run['status'] = 'paused'
        message = 'Agent 连续失败三次，Loop 已暂停。请检查失败原因后恢复。'
        run['notifications'].append({'id': uid('agent-failure'), 'tasks': scope_task, 'status': 'pending',
            'message': message, 'route': 'user', 'attempt': 0, 'at': time.time(), 'reason': str(error)})
        Store.log(run, 'agent_failure_pause', message, detail={'failures': counter['agent_failures'], 'error': str(error)})
    else:
        Store.log(run, 'agent_retry', 'Agent exited; unresolved abnormal state will wake an Agent again',
                  detail={'failures': counter['agent_failures'], 'error': str(error)})


class TimelineRuntime:
    def __init__(self, engine):
        self.engine, self.store = engine, engine.store

    def resolve_inputs(self, run, tasks):
        values, sources, missing = {}, {}, []
        for task_id in tasks['spec'].get('after', []):
            before = run['tasks'].get(task_id)
            if not before or before['status'] not in ('completed', 'skipped'):
                missing.append({'action': task_id, 'reason': 'order_dependency', 'status': before['status'] if before else 'missing'})
        node = node_for(run, tasks['spec']['node'])
        for name, source in tasks['spec']['inputs'].items():
            try:
                if 'record' in source or 'records' in source:
                    ids = source['records'] if 'records' in source else [source['record']]
                    records = [record_version(run, rid, source.get('revision')) for rid in ids]
                    absent = [rid for rid, rec in zip(ids, records) if rec is None]
                    if absent:
                        missing.extend({'input': name, 'record': rid, 'revision': source.get('revision') or 1, 'reason': 'missing_record'} for rid in absent)
                        continue
                    value = [path(rec['value'], source.get('path', '')) for rec in records]
                    provenance = [{'record': rec['id'], 'revision': rec['revision'], 'execution': rec['producer']} for rec in records]
                    if 'record' in source:
                        value, provenance = value[0], provenance[0]
                elif 'run' in source:
                    value, provenance = path(run['inputs'], source['run']), {'run_input': source['run']}
                elif 'settings' in source:
                    value = path(run['settings'], source['settings'])
                    provenance = {'settings': source['settings'], 'revision': run['settings']['revision']}
                else:
                    value, provenance = copy.deepcopy(source['literal']), {'literal': True}
                contract(value, node['inputs'][name], name)
                values[name], sources[name] = copy.deepcopy(value), provenance
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                missing.append({'input': name, 'reason': 'invalid_input', 'detail': str(exc)})
        if not missing and selected(run, tasks)[1] is None:
            missing.append({'reason': 'missing_implementation', 'node': tasks['spec']['node']})
        return values, sources, missing

    def apply_hooks(self, run, tasks, phase):
        held = False
        for hook in run['settings']['hooks']:
            if not hook.get('enabled', True) or hook['phase'] != phase:
                continue
            target = hook['target']
            if target.get('node') and target['node'] != tasks['spec']['node']:
                continue
            if target.get('tasks') and target['tasks'] != tasks['id']:
                continue
            key = hook['id'] + ':' + tasks['id']
            firing = next((f for f in run['hook_firings'] if f['id'] == key), None)
            if firing:
                held |= firing['action'] == 'pause' and firing['status'] == 'held'
                continue
            if hook['frequency'] == 'once' and any(f['hook'] == hook['id'] for f in run['hook_firings']):
                continue
            firing = {'id': key, 'hook': hook['id'], 'tasks': tasks['id'], 'action': hook['action'],
                      'status': 'held' if hook['action'] == 'pause' else 'queued', 'at': time.time()}
            run['hook_firings'].append(firing)
            if hook['action'] == 'pause':
                held = True
                Store.log(run, 'gate', 'Paused before ' + tasks['id'], detail=firing)
            else:
                run['notifications'].append({'id': key, 'tasks': tasks['id'], 'status': 'pending',
                    'message': hook.get('message') or (tasks['id'] + ': ' + phase),
                    'route': hook.get('route', 'user'), 'attempt': 0, 'at': time.time()})
                Store.log(run, 'notification', 'Notification queued for ' + tasks['id'])
        return held

    def diagnose(self, run):
        diagnostics = [{'kind': 'budget_exhausted', 'tasks': w['id'], 'detail': w['budget_error']}
                       for w in run['tasks'].values() if w.get('budget_error')]
        diagnostics.extend({'kind': 'observation_error', 'tasks': e['task_id'], 'detail': e['observation_error']}
                           for e in run['executions'] if e.get('observation_error') and run['tasks'][e['task_id']].get('execution_id') == e['id'] and e['status'] not in END)
        producers = {}
        for tasks in run['tasks'].values():
            if tasks['status'] in ('stale', 'cancelled'):
                continue
            for output in tasks['spec']['outputs'].values():
                producers[(output['id'], output.get('expected_revision', 0) + 1)] = tasks['id']
        deps = {}
        for tasks in run['tasks'].values():
            if tasks['status'] != 'blocked':
                continue
            deps[tasks['id']] = []
            for item in tasks['wait_reasons']:
                if item.get('reason') == 'missing_implementation':
                    diagnostics.append({'kind': 'missing_implementation', 'tasks': tasks['id'], **item})
                    continue
                if item.get('action'):
                    deps[tasks['id']].append(item['action'])
                    before = run['tasks'].get(item['action'])
                    if not before or before['status'] in ('fault', 'cancelled', 'stale'):
                        diagnostics.append({'kind': 'order_dependency_gap', 'tasks': tasks['id'], **item})
                    continue
                producer = producers.get((item.get('record'), item.get('revision', 1)))
                if producer:
                    deps[tasks['id']].append(producer)
                    status = run['tasks'][producer]['status']
                    if status == 'fault':
                        diagnostics.append({'kind': 'upstream_fault', 'tasks': tasks['id'], 'producer': producer})
                    elif status == 'completed':
                        diagnostics.append({'kind': 'dependency_gap', 'tasks': tasks['id'], 'producer': producer, **item})
                    elif status == 'skipped':
                        diagnostics.append({'kind': 'skipped_dependency', 'tasks': tasks['id'], 'producer': producer, 'record': item.get('record')})
                elif item.get('record'):
                    diagnostics.append({'kind': 'dependency_gap', 'tasks': tasks['id'], **item})
                else:
                    diagnostics.append({'kind': 'invalid_input', 'tasks': tasks['id'], **item})
        def cyclic(start, node, visited):
            return any(n == start or (n not in visited and cyclic(start, n, visited | {n})) for n in deps.get(node, []))
        for task_id in deps:
            if cyclic(task_id, task_id, {task_id}):
                diagnostics.append({'kind': 'dependency_cycle', 'tasks': task_id})
        active = any(w['status'] not in END for w in run['tasks'].values())
        _, rule_error = end_condition(run)
        if rule_error:
            diagnostics.append({'kind': 'invalid_completion_rule', 'detail': rule_error})
        if not run['initialized'] and not active:
            diagnostics.append({'kind': 'initialization_incomplete', 'detail': 'No active initializer and no committed initial Timeline'})
        if diagnostics != run['diagnostics']:
            run['diagnostics'] = diagnostics
            if diagnostics:
                Store.log(run, 'diagnostics', 'Run readiness needs inspection', detail=diagnostics)

    def tick(self, run_id):
        jobs, deliveries = [], []
        with self.store.edit(run_id) as run:
            if not run.get('operator_protocol'):
                return  # No autonomous exception migration of historical Runs.
            if run['loop_definition'].get('rules'):
                raise Invalid('This Run uses retired Engine rules. Publish a plans-based Loop; existing data is not migrated automatically.')
            if run['status'] == 'running' or (run['status'] == 'paused' and run['settings'].get('termination_signal')):
                reason, _ = end_condition(run)
                if reason:
                    self.end_run(run, reason)
            if run['status'] == 'running':
                # Observe/consume existing tasks before admitting new tasks.
                for e in run['executions']:
                    tasks = run['tasks'][e['task_id']]
                    if e['status'] != 'waiting' or e.get('worker_active') or e.get('observation_error'):
                        continue
                    implementation = e['implementation']
                    if implementation['kind'] == 'event':
                        event = next((v for v in run['events'] if not v.get('consumed_by') and
                            v['name'] == implementation['event'] and v.get('key') == tasks['spec'].get('parameters', {}).get('event_key')), None)
                        if event:
                            try:
                                self.report_in_run(run, e, {'event': 'completed', 'report_id': 'event:' + event['id'], 'envelope': {'outputs': event['payload']}}, 'event')
                                event['consumed_by'] = e['id']
                            except Invalid as exc:
                                event['consumed_by'] = 'rejected'
                                Store.log(run, 'event_rejected', str(exc))
                    elif e['wake_at'] <= time.time():
                        e['status'] = tasks['status'] = 'executing'
                        jobs.append((copy.deepcopy(e), copy.deepcopy(run), True))
                active = sum(w['status'] in {'executing', 'decision'} or (w['status'] == 'waiting' and
                    (selected(run, w)[1] or {}).get('kind') == 'external') for w in run['tasks'].values())
                global_waiting = False
                candidates = sorted(run['tasks'].values(), key=lambda task: scope_for(run, task) is not None)
                for tasks in candidates:
                    if tasks['status'] not in PENDING:
                        continue
                    values, sources, missing = self.resolve_inputs(run, tasks)
                    tasks['wait_reasons'] = missing
                    if missing:
                        tasks['status'] = 'blocked'
                        continue
                    tasks['status'] = 'ready'
                    if self.apply_hooks(run, tasks, 'before'):
                        tasks['status'] = 'held'
                        continue
                    implementation = selected(run, tasks)[1]
                    if implementation['kind'] == 'agent':
                        scope = scope_for(run, tasks)
                        if 'task:' + tasks['id'] in run.get('task_dispositions', {}):
                            continue
                        if not scope_available(run, scope):
                            global_waiting = global_waiting or scope is None
                            continue
                        if global_waiting and scope is not None:
                            continue
                    try:
                        self.check_budget(run, tasks)
                        if implementation['kind'] == 'agent' and agent_calls(run) >= run['loop_definition'].get('limits', {}).get('max_agent_calls', float('inf')):
                            raise Invalid('Declared Agent-call budget prevents dispatch')
                    except Invalid as exc:
                        tasks.update(status='fault', budget_error=str(exc))
                        Store.log(run, 'budget_exhausted', tasks['id'])
                        continue
                    if implementation['kind'] not in ('event', 'approval') and active >= run['settings']['max_parallel']:
                        continue
                    e = self.new_execution(run, tasks, implementation, values, sources)
                    if implementation['kind'] == 'agent':
                        acquire_in_run(run, 'background', e['token'], e['id'])
                    if implementation['kind'] == 'event':
                        e['status'] = 'waiting'
                    elif implementation['kind'] == 'approval':
                        e['status'] = 'approval'
                    elif implementation['kind'] == 'agent' and not implementation.get('command'):
                        e['status'] = 'decision'
                    else:
                        jobs.append((copy.deepcopy(e), copy.deepcopy(run), False))
                    if e['status'] in ('decision', 'approval', 'waiting'):
                        e['started_at'] = time.time()
                    tasks['status'] = e['status']
                    if e['status'] in ('executing', 'decision'):
                        active += 1
                    Store.log(run, 'dispatched', tasks['id'] + ' → ' + e['node'], e['id'], {'sources': sources, 'origin': tasks['origin']})
                self.diagnose(run)
                tasks = task_list(run, self)
                run['attention_state'] = 'unexpected' if run.get('attention_error') else tasks['state']
                if tasks['state'] != 'unexpected' and not run.get('attention_error') and not run.get('agent_sessions'):
                    run['agent_failures'] = 0
                    for task in run['tasks'].values():
                        task.pop('agent_failures', None)
                if run.get('attention_error') or any(t['kind'] in ('unexpected', 'request') for t in tasks['items']):
                    fallback = run['settings'].get('fallback_node')
                    pending = any(w['origin'].get('fallback') and w['status'] in PENDING | IN_FLIGHT for w in run['tasks'].values())
                    if fallback and not pending:
                        node = node_for(run, fallback)
                        previous = next((w for w in reversed(list(run['tasks'].values()))
                                         if w['origin'].get('fallback') and w['spec']['node'] == fallback and w['status'] == 'fault'), None)
                        try:
                            self.check_budget(run, {'spec': {'node': fallback}})
                            if agent_calls(run) >= run['loop_definition'].get('limits', {}).get('max_agent_calls', float('inf')):
                                raise Invalid('Declared Agent-call budget prevents fallback')
                            if previous and run.get('agent_failures', 0):
                                from loop_anything.interfaces.agent_tasks import change_task_in_run
                                change_task_in_run(run, {'task_id': previous['id'], 'operation': 'retry',
                                                        'reason': 'Retry configured fallback after confirmed Agent failure'})
                            else:
                                ident = uid('fallback')
                                spec = {'id': ident, 'node': fallback, 'inputs': {},
                                        'outputs': {p: {'id': ident + '.' + p} for p in node['outputs']}}
                                add_task(run, spec, {'fallback': True, 'issues': copy.deepcopy(tasks['items'])})
                        except Invalid as exc:
                            run['attention_error'] = str(exc)
                reason, _ = end_condition(run)
                if reason:
                    self.end_run(run, reason)
            # Notifications may finish delivery while business tasks is paused/complete.
            for notification in run['notifications']:
                if notification['status'] != 'pending':
                    continue
                if notification['route'] != 'workspace' and 'sender' not in notification:
                    command = run['settings'].get('notification_command')
                    sender = {'command': command} if command else run['implementations'].get('$notifications', {})
                    if sender.get('command'):
                        notification['sender'] = copy.deepcopy(sender)
                notification.update(status='sending', token=uid('delivery'), attempt=notification['attempt'] + 1)
                deliveries.append((copy.deepcopy(notification), copy.deepcopy(run)))
            jobs = [(e, copy.deepcopy(run), observe) for e, _, observe in jobs]
        for e, snapshot, observe in jobs:
            self.engine.futures.add(self.engine.pool.submit(self.execute, run_id, e, snapshot, observe))
        for notification, snapshot in deliveries:
            self.engine.futures.add(self.engine.pool.submit(self.deliver, run_id, notification, snapshot))
        self.engine.futures = {f for f in self.engine.futures if not f.done()}

    def end_run(self, run, reason):
        run['status'] = 'completed'
        run['completion'] = {'reason': reason, 'at': time.time(), 'settings_revision': run['settings']['revision']}
        for tasks in run['tasks'].values():
            if tasks['status'] not in END:
                tasks['status'] = 'cancelled'
                if tasks.get('execution_id'):
                    self.engine.execution(run, tasks['execution_id']).update(status='cancelled', token=None)
        Store.log(run, 'completed', 'Engine entered terminal state: ' + reason)
        if run['settings'].get('notification_command') or run['implementations'].get('$notifications', {}).get('command'):
            run['notifications'].append({'id': 'completed:' + run['id'], 'tasks': None, 'status': 'pending',
                'message': '运行已完成', 'reason': reason, 'route': 'user', 'attempt': 0, 'at': time.time()})

    def check_budget(self, run, tasks):
        limits = run['loop_definition'].get('limits', {})
        attempts = run['executions']
        if (len(attempts) >= limits.get('max_attempts', float('inf')) or
            sum(e['node'] == tasks['spec']['node'] for e in attempts) >= limits.get('attempts_by_node', {}).get(tasks['spec']['node'], float('inf'))):
            raise Invalid('Declared attempt budget prevents dispatch')

    def new_execution(self, run, tasks, implementation, values, sources):
        e = dict(id=uid('exec'), task_id=tasks['id'], node=tasks['spec']['node'], inputs=values, sources=sources,
                 parameters=copy.deepcopy(tasks['spec'].get('parameters', {})), status='executing', token=uid('attempt'),
                 settings_revision=run['settings']['revision'],
                 implementation_id=selected(run, tasks)[0], implementation=copy.deepcopy(implementation), created_at=time.time(), started_at=None, attempt=tasks.get('attempts', 0) + 1)
        tasks['execution_id'], tasks['attempts'] = e['id'], e['attempt']
        e['implementation']['lifecycle'] = lifecycle_definition(implementation)
        e['lifecycle_state'] = e['implementation']['lifecycle']['initial']
        run['executions'].append(e)
        Store.log(run, 'transition', 'Execution entered initial state', e['id'],
                  {'from': None, 'event': 'start', 'to': e['lifecycle_state'], 'source': 'engine', 'accepted': True})
        return e

    def check_owner(self, run, e, token):
        if run['status'] in ('completed', 'terminated') or e['status'] not in IN_FLIGHT or e['token'] != token:
            raise Conflict('Execution no longer owns this tasks')
        tasks = run['tasks'][e['task_id']]
        if e['implementation']['kind'] == 'agent':
            require_scope(run, require_owner(run, token), e['task_id'])
        # Results retain dispatched inputs. Explicit cancellation/retry revokes tokens;
        # Agent submissions separately validate live task_version in complete_task.

    def commit_in_run(self, run, e, envelope):
        if not isinstance(envelope, dict) or not isinstance(envelope.get('outputs', {}), dict) or not isinstance(envelope.get('tasks', []), list):
            raise Invalid('Completion envelope requires object outputs and array tasks')
        node = node_for(run, e['node'])
        tasks = run['tasks'][e['task_id']]
        outputs = envelope.get('outputs', {})
        validate_result(run['loop_definition'], e['node'], outputs)
        context = {'outputs': outputs, 'inputs': e['inputs'], 'parameters': e['parameters'],
                   'settings': dict(run['settings'], **envelope.get('settings', {})),
                   'completed': {name: sum(x['node'] == name and x['status'] == 'completed' for x in run['executions'])
                                 for name in run['loop_definition']['nodes']}}
        check_assertions(node, context)
        if set(envelope) - {'outputs', 'tasks', 'settings'}:
            raise Invalid('Unknown completion envelope field')
        if envelope.get('settings') is not None:
            if not node.get('initialize_timeline') or run['initialized']:
                raise Invalid('Only initial semantic parsing may initialize settings')
            if 'authorization' in envelope['settings'] and envelope['settings']['authorization'] != run['settings'].get('authorization', ''):
                raise Invalid('Agent cannot grant itself user authorization')
            if set(envelope['settings']) - SEMANTIC_FIELDS - ENDING_FIELDS:
                raise Invalid('Initializer cannot change Engine runtime fields')
            candidate = dict(run['settings'], **envelope['settings'])
            validate_settings(candidate)
            if node.get('agent_settings_schema'):
                contract(envelope['settings'], node['agent_settings_schema'], 'settings')
            if not candidate['objective']:
                raise Invalid('Initializer must provide objective')
        elif node.get('initialize_timeline') and not run['initialized']:
            raise Invalid('Initializer must submit structured user semantics')
        for planned in envelope.get('tasks', []):
            allowed = list(run['loop_definition']['nodes']) if e['implementation']['kind'] == 'agent' else node.get('plan_nodes', [])
            if planned.get('node') not in allowed or run['loop_definition']['nodes'].get(planned.get('node'), {}).get('initialize_timeline'):
                raise Invalid('This node cannot propose tasks for ' + str(planned.get('node')))
            check_task(run['loop_definition'], planned)
        # Validate every destination before applying any shared-state write.
        for name, value in outputs.items():
            destination = tasks['spec']['outputs'][name]
            previous = latest(run, destination['id'])
            expected = destination.get('expected_revision', 0)
            if (previous['revision'] if previous else 0) != expected:
                raise Conflict('Output record revision conflict: ' + destination['id'])
            if previous and previous['type'] != node['outputs'][name]['record_type']:
                raise Invalid('Cannot replace a record with a different type')
        if envelope.get('settings') is not None:
            run['settings'].update(copy.deepcopy(envelope['settings']))
            run['initialized'] = True
            Store.log(run, 'initialized', 'User meaning parsed into Programmable Timeline', e['id'], {'settings': run['settings']})
        actor = require_owner(run, e['token']) if e['implementation']['kind'] == 'agent' else None
        for planned in attach_tasks(run, envelope.get('tasks', []), e['task_id'], actor):
            add_task(run, planned, {'execution': e['id']})
        refs = {}
        for name, value in outputs.items():
            destination = tasks['spec']['outputs'][name]
            rec = {'id': destination['id'], 'revision': destination.get('expected_revision', 0) + 1,
                   'type': node['outputs'][name]['record_type'], 'value': copy.deepcopy(value),
                   'producer': e['id'], 'tasks': tasks['id'], 'at': time.time(), 'sources': copy.deepcopy(e['sources'])}
            run['records'].setdefault(rec['id'], []).append(rec)
            refs[name] = {'record': rec['id'], 'revision': rec['revision']}
        e.update(status='completed', completed_at=time.time(), record_refs=refs, outputs=copy.deepcopy(outputs))
        tasks['status'] = 'completed'
        Store.log(run, 'committed', tasks['id'] + ': shared records committed', e['id'], refs)
        self.apply_hooks(run, tasks, 'after')

    def report_in_run(self, run, e, report, source):
        """Ownership is checked by the caller; validate before changing shared records."""
        if not isinstance(report, dict) or set(report) - {'event', 'report_id', 'envelope', 'detail', 'external_id', 'poll_after'}:
            raise Invalid('Unsupported report fields')
        if not all(isinstance(report.get(k), str) and report[k].strip() for k in ('event', 'report_id')):
            raise Invalid('Report needs event and stable report_id')
        if 'detail' in report and not isinstance(report['detail'], dict):
            raise Invalid('Report detail must be an object')
        if 'envelope' in report and not isinstance(report['envelope'], dict):
            raise Invalid('Completion envelope must be an object')
        reports = e.setdefault('reports', {})
        previous = reports.get(report['report_id'])
        fingerprint = digest(report)
        if previous:
            if previous['fingerprint'] != fingerprint:
                raise Conflict('report_id already used for different contents')
            if e.get('worker_active'):
                e['call_reported'] = True
            return dict(previous['receipt'], duplicate=True)
        if run['status'] in ('completed', 'terminated') or e['status'] in END or e['status'] == 'fault':
            raise Conflict('Execution has ended; cannot report another transition')
        kind = e['implementation']['kind']
        external_id = report.get('external_id', e.get('external_id'))
        delay = report.get('poll_after', 10)
        if type(delay) not in (int, float) or not math.isfinite(delay) or delay <= 0:
            raise Invalid('poll_after must be positive and finite')
        if 'external_id' in report and (kind != 'external' or not isinstance(external_id, str) or not external_id):
            raise Invalid('external_id requires an external implementation and a nonempty ID')
        if e.get('external_id') and external_id != e['external_id']:
            raise Conflict('A monitor cannot replace the external task identity')
        event = report['event']
        if event == 'check_error' and (kind != 'external' or not external_id):
            raise Invalid('check_error requires an external task already submitted')
        if event == 'submitted' and (kind != 'external' or not external_id):
            raise Invalid('submitted needs the external task ID')
        if 'envelope' in report and event != 'completed':
            raise Invalid('Only completed reports may commit outputs or arrange tasks')
        state = e.get('lifecycle_state', lifecycle_definition(e['implementation'])['initial'])
        rules = lifecycle_definition(e['implementation'])['transitions']
        rule = next((r for r in rules if r['from'] == state and r['event'] == event), None)
        context = {'inputs': e['inputs'], 'parameters': e['parameters'], 'settings': run['settings'],
                   'detail': report.get('detail', {}), 'outputs': report.get('envelope', {}).get('outputs', {})}
        matched = rule is not None
        if rule and 'when' in rule:
            try:
                matched = evaluate(rule['when'], context) is True
            except (KeyError, IndexError, TypeError, ValueError):
                matched = False
        task = run['tasks'][e['task_id']]
        if event == 'check_error':
            e['observation_error'] = str(report.get('detail', {}).get('message') or 'Observation failed; external state is unknown')
        if matched:
            if event != 'check_error':
                e.pop('observation_error', None)
            target = rule['to']
            if target == 'completed':
                self.commit_in_run(run, e, report.get('envelope', {}))
            elif target == 'fault':
                e.update(status='fault', error=str(report.get('detail', {}).get('message') or event))
                task['status'] = 'fault'
            else:
                if kind == 'external' and external_id:
                    e.update(external_id=external_id, poll_after=delay, wake_at=time.time() + delay)
                    e['status'] = task['status'] = 'waiting'
            e['lifecycle_state'] = target
        else:
            target = state
            e.update(status='fault', error=('Transition condition not met: ' if rule else 'Uncovered transition: ') + state + ' + ' + event)
            task['status'] = 'fault'
        detail = {'from': state, 'event': event, 'to': target, 'source': source, 'accepted': matched,
                  'report_id': report['report_id'], 'detail': copy.deepcopy(report.get('detail', {})),
                  'rule': copy.deepcopy(rule)}
        if external_id:
            detail['external_id'] = external_id
        Store.log(run, 'transition', event if matched else e['error'], e['id'], detail)
        receipt = {'accepted': matched, 'task_id': task['id'], 'execution_id': e['id'], 'state': target,
                   'report_id': report['report_id']}
        if target == 'completed' and matched:
            receipt['completed'] = task['id']
        if not matched:
            receipt['issue'] = e['error']
        reports[report['report_id']] = {'fingerprint': fingerprint, 'receipt': receipt}
        if e.get('worker_active'):
            e['call_reported'] = True
        return receipt

    def submit(self, run_id, execution_id, token, envelope):
        with self.store.edit(run_id) as run:
            e = self.engine.execution(run, execution_id)
            if e['implementation']['kind'] == 'agent':
                raise Invalid('Agent results must use read_task and report_task')
            self.check_owner(run, e, token)
            self.report_in_run(run, e, {'event': 'completed', 'report_id': 'submit:' + digest(envelope), 'envelope': envelope}, 'submission')

    def execute(self, run_id, e, snapshot, observe=False):
        implementation = e['implementation']
        exit_error = None
        invocation = uid('call')
        try:
            if implementation['kind'] == 'agent':
                context = task_context(self.store, snapshot, e, getattr(self.engine, 'platform_url', None),
                                       owner_for(snapshot, e['token']).get('scope_task'))
                request_text = render_prompt(implementation, 'task', context)
            else:
                node = node_for(snapshot, e['node'])
                request = {'run_id': run_id, 'execution_id': e['id'], 'task_id': e['task_id'], 'token': e['token'],
                           'inputs': e['inputs'], 'parameters': e['parameters'], 'external_id': e.get('external_id'),
                           'timeline': snapshot, 'handbook': snapshot['loop_definition']['handbook'],
                           'node_instructions': node['instructions'], 'output_contract': node['outputs'],
                           'platform_url': getattr(self.engine, 'platform_url', None),
                           'report_client': str(platform_skill_directory() / 'scripts/report.py'),
                           'lifecycle': lifecycle_definition(implementation), 'state': e.get('lifecycle_state'),
                           'invocation_id': invocation, 'observing': observe}
                request_text = json.dumps(request)
            # A queued worker must recheck its ownership before launching a command.
            with self.store.edit(run_id) as current_run:
                current = self.engine.execution(current_run, e['id'])
                self.check_owner(current_run, current, e['token'])
                current['worker_active'] = True
                current['call_reported'] = False
                if observe:
                    Store.log(current_run, 'observation', 'Checking external task', e['id'], {'external_id': current.get('external_id'), 'invocation_id': invocation})
                if current.get('started_at') is None:
                    current['started_at'] = time.time()
                if implementation['kind'] == 'agent':
                    current['prompt_text'] = mask_prompt(request_text, e['token'])
            result = run_command(implementation['observe'] if observe else implementation['command'], request_text,
                                 implementation.get('timeout', None if implementation['kind'] == 'agent' else 60), implementation.get('cwd'),
                                 stop=self.engine.stopping if implementation['kind'] == 'agent' else None)
            if result.returncode:
                raise Invalid('Handler failed: ' + result.stderr[-1500:])
            envelope = None
            with self.store.edit(run_id) as run:
                current = self.engine.execution(run, e['id'])
                if implementation['kind'] == 'agent':
                    if owner_for(run, e['token']):
                        raise Invalid('Agent exited without calling finish')
                    return  # Tool writes already committed; stdout is not a business result.
                # Direct tool reporting is authoritative; stdout is a compact adapter for old scripts.
                if current.get('token') != e['token'] or current['status'] in END | {'fault'}:
                    return
                self.check_owner(run, current, e['token'])
                reported = current.get('call_reported', False)
                if not reported and result.stdout.strip():
                    envelope = json.loads(result.stdout)
                if envelope is not None:
                    if not isinstance(envelope, dict):
                        raise Invalid('Script response must be an object')
                    if envelope.get('status') == 'waiting':
                        report = {'event': 'progress' if current.get('external_id') else 'submitted',
                                  'report_id': invocation, 'external_id': envelope.get('external_id'),
                                  'poll_after': envelope.get('poll_after', 10), 'detail': envelope.get('detail', {})}
                    elif 'event' in envelope:
                        report = dict(envelope, report_id=envelope.get('report_id', invocation))
                    else:
                        report = {'event': 'completed', 'report_id': invocation, 'envelope': envelope}
                    self.report_in_run(run, current, report, 'monitor' if observe else 'script')
                elif not reported:
                    raise Invalid('Program exited without reporting a result')
                if observe and current['status'] == 'executing' and reported:
                    # A replay acknowledges a prior report; checking is over but its business state stays unchanged.
                    current.update(status='waiting', wake_at=time.time() + current.get('poll_after', 10))
                    run['tasks'][e['task_id']]['status'] = 'waiting'
                if implementation['kind'] == 'command' and current['status'] not in END | {'fault'}:
                    raise Invalid('Program exited before completing its task')
                if implementation['kind'] == 'external' and not current.get('external_id') and current['status'] not in END | {'fault'}:
                    raise Invalid('Submitter exited without an external task ID or result')
        except Exception as exc:
            exit_error = exc
            with self.store.edit(run_id) as run:
                if implementation['kind'] == 'agent' and not owner_for(run, e['token']):
                    Store.log(run, 'agent_exit_error', str(exc), e['id'])
                    return
                current = self.engine.execution(run, e['id'])
                if current.get('token') == e['token'] and current['status'] not in ('cancelled', 'stale'):
                    if current['status'] not in ('completed', 'fault') and not (current.get('external_id') and not observe):
                        self.report_in_run(run, current, {'event': 'check_error' if observe else 'process_error',
                            'report_id': invocation + ':error', 'detail': {'message': str(exc)}}, 'engine')
                    Store.log(run, 'process_error', str(exc), e['id'], {'observing': observe, 'result_preserved': current['status'] == 'completed'})
                    if implementation['kind'] == 'agent':
                        if isinstance(exc, CommandNotStopped):
                            owner_for(run, e['token'])['recovery_required'] = True
                        if owner_for(run, e['token']).get('scope_task') is None:
                            run['attention_error'] = str(exc)
        finally:
            with self.store.edit(run_id) as run:
                current = self.engine.execution(run, e['id'])
                current.pop('worker_active', None)
                current.pop('call_reported', None)
            if e['implementation']['kind'] == 'agent':
                with self.store.edit(run_id) as run:
                    owner = owner_for(run, e['token'])
                    if owner and not owner.get('recovery_required'):
                        release_in_run(run, e['token'])
                    if not owner_for(run, e['token']):
                        previous = owner_for(snapshot, e['token'])
                        if previous and not self.engine.stopping.is_set():
                            agent_exited(run, self, exit_error, previous.get('scope_task'))

    def deliver(self, run_id, notification, snapshot):
        try:
            if notification['route'] == 'workspace':
                receipt = {'delivered': True, 'channel': 'workspace', 'reference': notification['id']}
            else:
                adapter = notification.get('sender', {})
                if not adapter.get('command'):
                    raise Invalid('No notification transport configured')
                task = snapshot['tasks'].get(notification.get('tasks'), {})
                payload = {k: v for k, v in notification.items() if k not in ('sender', 'token')}
                payload.update(run_id=run_id, title=snapshot['title'], run_status=snapshot['status'],
                               task_label=snapshot['loop_definition']['nodes'].get(task.get('spec', {}).get('node'), {}).get('label', ''),
                               task_status=task.get('status', ''))
                result = run_command(adapter['command'], json.dumps(payload), adapter.get('timeout', 30), adapter.get('cwd'))
                if result.returncode:
                    try:
                        detail = json.loads(result.stdout).get('error')
                    except (ValueError, AttributeError):
                        detail = None
                    raise Invalid('Notification transport failed: ' + str(detail or result.stderr or result.returncode)[-1500:])
                receipt = json.loads(result.stdout)
                if receipt.get('delivered') is not True:
                    raise Invalid('Transport did not confirm delivery')
            error = None
        except Exception as exc:
            receipt, error = None, str(exc)
        with self.store.edit(run_id) as run:
            row = next(n for n in run['notifications'] if n['id'] == notification['id'])
            if row.get('token') != notification['token'] or row['status'] != 'sending':
                return
            row.update(status='fault' if error else 'delivered', receipt=receipt, error=error)
            Store.log(run, 'notification_' + row['status'], row['message'], detail={'id': row['id'], 'route': row['route'], 'receipt': receipt, 'error': error})

    def change_settings(self, run_id, revision, change, operator_token=None):
        with self.store.edit(run_id) as run:
            self.change_settings_in_run(run, revision, change, operator_token)
        return self.store.get(run_id)

    def change_settings_in_run(self, run, revision, change, operator_token=None):
        if not run.get('operator_protocol'):
            raise Invalid('Historical Run is inspect-only under the new operator protocol')
        guard_write(run, operator_token)
        if 'authorization' in change and (owner_for(run, operator_token) or {}).get('kind') == 'background':
            raise Invalid('Only the user may change user authorization')
        allowed = SEMANTIC_FIELDS | ENDING_FIELDS | {'max_parallel', 'hooks', 'bindings', 'fallback_node', 'global_agent_node', 'notification_command'}
        if set(change) - allowed:
            raise Invalid('Unknown Programmable Timeline field')
        if run['status'] in ('completed', 'terminated'):
            raise Conflict('Run ended')
        if revision != run['settings']['revision']:
            raise Conflict('Programmable Timeline revision changed')
        before = copy.deepcopy(run['settings'])
        candidate = dict(before, **copy.deepcopy(change))
        validate_settings(candidate)
        validate_bindings(run['loop_definition'], run['implementations'], candidate.get('bindings', {}))
        candidate['fallback_node'] = candidate.get('fallback_node') or None
        validate_fallback(run['loop_definition'], run['implementations'], candidate['fallback_node'])
        from loop_anything.runtime.timeline_model import validate_global_agent
        validate_global_agent(run['loop_definition'], run['implementations'], candidate.get('global_agent_node'))
        seen = set()
        for hook in candidate['hooks']:
            if not hook.get('id') or hook['id'] in seen:
                raise Invalid('Hook IDs must be unique')
            seen.add(hook['id'])
            if hook.get('action') not in ('pause', 'notify') or hook.get('phase') not in ('before', 'after') or hook.get('frequency') not in ('once', 'always'):
                raise Invalid('Invalid hook action/phase/frequency')
            if hook['action'] == 'pause' and hook['phase'] != 'before':
                raise Invalid('Pause gates run before dispatch; choose the downstream node')
            if not isinstance(hook.get('target'), dict) or set(hook['target']) - {'node', 'tasks'} or not hook['target']:
                raise Invalid('Hook needs node or tasks target')
            if not all(isinstance(v, str) and v for v in hook['target'].values()):
                raise Invalid('Hook target IDs must be nonempty strings')
            if hook['target'].get('node') and hook['target']['node'] not in run['loop_definition']['nodes']:
                raise Invalid('Unknown hook node')
            old = next((h for h in before['hooks'] if h['id'] == hook['id']), None)
            if old and {k: v for k, v in old.items() if k != 'enabled'} != {k: v for k, v in hook.items() if k != 'enabled'}:
                raise Invalid('Use a new hook id to change a hook definition')
        candidate['revision'] += 1
        run['settings'] = candidate
        if before.get('fallback_node') != candidate['fallback_node']:
            for task in run['tasks'].values():
                if task['origin'].get('fallback') and task['status'] in PENDING and not task.get('execution_id'):
                    task['status'] = 'cancelled'
        Store.log(run, 'settings', 'Programmable Timeline changed', detail={'before': before, 'after': candidate})

    def command(self, run_id, action, execution_id=None, hook_firing=None, notification_id=None,
                operator_token=None):
        with self.store.edit(run_id) as run:
            self.command_in_run(run, action, execution_id, hook_firing, notification_id, operator_token)
        return self.store.get(run_id)

    def command_in_run(self, run, action, execution_id=None, hook_firing=None, notification_id=None, operator_token=None):
        guard_write(run, operator_token)
        if action == 'retry_notification':
            row = next(n for n in run['notifications'] if n['id'] == notification_id)
            if row['status'] != 'fault':
                raise Conflict('Notification is not failed')
            row['status'] = 'pending'
            return
        if run['status'] in ('completed', 'terminated'):
            raise Conflict('Run ended')
        if action in ('pause', 'resume', 'terminate'):
            run['status'] = {'pause': 'paused', 'resume': 'running', 'terminate': 'terminated'}[action]
            if action == 'resume':
                run['agent_failures'] = 0
                for task in run['tasks'].values():
                    task.pop('agent_failures', None)
            if action == 'terminate':
                for tasks in run['tasks'].values():
                    if tasks['status'] not in END:
                        tasks['status'] = 'cancelled'
                        if tasks['execution_id']:
                            self.engine.execution(run, tasks['execution_id']).update(status='cancelled', token=None)
        elif action == 'release_gate':
            firing = next(f for f in run['hook_firings'] if f['id'] == hook_firing)
            if firing['status'] != 'held':
                raise Conflict('Gate is not held')
            firing['status'] = 'released'
        elif action == 'retry':
            e = self.engine.execution(run, execution_id)
            if run['tasks'][e['task_id']].get('execution_id') != execution_id:
                raise Conflict('Only the current execution can be retried')
            from loop_anything.interfaces.agent_tasks import change_task_in_run
            change_task_in_run(run, {'task_id': e['task_id'], 'operation': 'retry', 'reason': 'User requested retry after checking side effects'})
        else:
            raise Invalid('Unknown command')
        Store.log(run, action, 'Timeline command: ' + action, execution_id, {'gate': hook_firing})

    def recover(self, run):
        if not run.get('operator_protocol'):
            return
        for attempt in run['executions']:
            attempt.pop('worker_active', None)
            attempt.pop('call_reported', None)
        for owner in run.get('agent_sessions', []):
            if owner.get('execution_id'):
                primary = self.engine.execution(run, owner['execution_id'])
                if primary['implementation'].get('command'):
                    owner['recovery_required'] = True
        for e in run['executions']:
            if e['status'] in IN_FLIGHT and 'lifecycle' not in e['implementation']:
                # Adopt the explicit contract for active pre-lifecycle attempts, without rewriting history.
                e['implementation']['lifecycle'] = lifecycle_definition(e['implementation'])
                e.setdefault('lifecycle_state', 'waiting' if e['implementation']['kind'] == 'external' and e.get('external_id') else e['implementation']['lifecycle']['initial'])
            if e['status'] == 'executing':
                if e['implementation']['kind'] == 'external' and e.get('external_id'):
                    e.update(status='waiting', wake_at=0)
                    run['tasks'][e['task_id']]['status'] = 'waiting'
                else:
                    self.report_in_run(run, e, {'event': 'process_error', 'report_id': uid('recovery'),
                        'detail': {'message': 'Engine interrupted; inspect external effects before retry'}}, 'engine')
                    e['token'] = None
                Store.log(run, 'recovery', 'Recovered ' + e['task_id'], e['id'])
        for notification in run['notifications']:
            if notification['status'] == 'sending':
                notification.update(status='fault', error='Interrupted delivery: outcome unknown; retry with the same notification id')
