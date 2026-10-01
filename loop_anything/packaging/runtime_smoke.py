"""Explicit Agent startup probes and isolated execution of external lifecycle reports."""
import copy
import math
import tempfile
from pathlib import Path

from loop_anything.packaging.packages import smoke, effective_implementations
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.host_runtime import run_command
from loop_anything.runtime.implementations import options, check_parameters
from loop_anything.runtime.lifecycle import definition, TERMINAL
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.store import Store, uid
from loop_anything.runtime.timeline_plan import add_task
from loop_anything.runtime.timeline_runtime import initialize_run


def probe_transition(engine, config, case):
    """Exercise the real report/retry writer, without running submit/observe commands."""
    node = {'instructions': 'Lifecycle probe', 'inputs': {}, 'outputs': {}}
    bp = {'schema_version': 2, 'nodes': {'init': dict(node, initialize_timeline=True), 'probe': node},
          'records': {}, 'entry': 'init', 'seed': {'id': 'init', 'node': 'init', 'inputs': {}, 'outputs': {}}}
    run = {'id': 'smoke', 'title': 'Isolated lifecycle probe', 'status': 'running', 'inputs': {},
           'loop_definition': bp, 'implementations': {'init': {'kind': 'agent'}, 'probe': config},
           'executions': [], 'history': [], 'events': []}
    initialize_run(run)
    run['initialized'] = True
    run['tasks']['init']['status'] = 'completed'
    run['settings'].update(case.get('settings', {}))
    run['settings'].update(notification_route='workspace', hooks=[], fallback_node=None)
    task = add_task(run, {'id': 'probe', 'node': 'probe', 'inputs': {}, 'outputs': {},
                         'parameters': case.get('parameters', {})}, {})
    task['attempts'] = case.get('attempt', 1) - 1
    runtime = engine.timeline_runtime
    execution = runtime.new_execution(run, task, config, case.get('inputs', {}), {})
    execution['lifecycle_state'] = case['state']
    if case['state'] != definition(config)['initial'] or case['event'] == 'check_error':
        execution['external_id'] = 'smoke-external'
        execution['status'] = task['status'] = 'waiting'
    report = {'event': case['event'], 'report_id': 'probe-event', 'detail': case.get('detail', {})}
    if case['event'] == 'submitted':
        report['external_id'] = 'smoke-external'
    if case['event'] == 'completed':
        report['envelope'] = {'outputs': {}}
    receipt = runtime.report_in_run(run, execution, report, 'monitor' if execution.get('external_id') else 'script')
    if not receipt['accepted']:
        raise Invalid(receipt['issue'])
    if case.get('expected') and receipt['state'] != case['expected']:
        raise Invalid('Expected ' + case['expected'] + ', got ' + receipt['state'])
    duplicate = runtime.report_in_run(run, execution, report, 'monitor')
    if not duplicate.get('duplicate'):
        raise Invalid('Repeated event was not deduplicated')
    detail = case['state'] + ' + ' + case['event'] + ' → ' + receipt['state'] + '; duplicate ignored'
    if receipt['state'] == 'retry':
        runtime.apply_retries(run)
        if execution['retry']['status'] != 'applied':
            raise Invalid('Retry could not be applied')
        if not any(r['from'] == definition(config)['initial'] and r['event'] == 'submitted' for r in definition(config)['transitions']):
            return detail + '; same Task retried; custom submission protocol needs an acceptance run'
        again = runtime.new_execution(run, task, config, execution['inputs'], {})
        runtime.report_in_run(run, again, {'event': 'submitted', 'report_id': 'resubmit', 'external_id': 'smoke-retry'}, 'script')
        checked = runtime.report_in_run(run, again, {'event': 'check_error', 'report_id': 'recheck'}, 'monitor')
        if not checked['accepted']:
            raise Invalid('Observation failure after retry: ' + checked['issue'])
        detail += '; same Task retried and check_error accepted on attempt ' + str(again['attempt'])
    return detail


def runtime_smoke(document, root, *, timeout=30, node_id=None, implementation_id=None, cases=None):
    """Opt-in: may call configured Agents/models. Never submit external business jobs."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise Invalid('Probe timeout must be positive and finite')
    if implementation_id and not node_id:
        raise Invalid('implementation_id requires node_id')
    cases = [] if cases is None else cases
    if not isinstance(cases, list) or any(not isinstance(c, dict) for c in cases):
        raise Invalid('cases must be an array of lifecycle examples')
    candidates = [(node, ident, config) for node, entry in effective_implementations(document, root).items()
                  for ident, config in options(entry).items()
                  if (node_id is None or node == node_id) and (implementation_id is None or ident == implementation_id)]
    if not candidates:
        raise Invalid('No matching implementation')
    selected = {(n, i): c for n, i, c in candidates}
    allowed = {'node', 'implementation', 'state', 'event', 'attempt', 'parameters', 'inputs', 'settings', 'detail', 'expected'}
    for case in cases:
        config = selected.get((case.get('node'), case.get('implementation')))
        if set(case) - allowed or not config or config['kind'] != 'external':
            raise Invalid('Each case must select an external node/implementation and use supported context fields')
        if any(not isinstance(case.get(k), str) or not case[k] for k in ('state', 'event')):
            raise Invalid('Each case needs state and event')
        if type(case.get('attempt', 1)) is not int or case.get('attempt', 1) < 1:
            raise Invalid('Case attempt must be a positive integer')
        if any(k in case and not isinstance(case[k], dict) for k in ('parameters', 'inputs', 'settings', 'detail')):
            raise Invalid('Case context fields must be objects')
        if 'expected' in case and not isinstance(case['expected'], str):
            raise Invalid('Case expected state must be text')
    preflight = smoke(document, root)
    checks = [c for c in preflight['checks'] if c['status'] == 'fail' and
              (not c.get('node') or (c['node'], c.get('implementation')) in selected)]
    def add(node, ident, kind, status, detail, **fields):
        checks.append(dict(node=node, implementation=ident, kind=kind, status=status,
                           target=node + ' / ' + ident, detail=detail, **fields))
    if not preflight['startable']:
        return dict(mode='runtime', ready=False, verified=False, checks=preflight['checks'],
                    notice='Package integrity failed; no command was executed.')
    with tempfile.TemporaryDirectory(prefix='loop-runtime-smoke-') as temporary:
        engine = Engine(Store(Path(temporary) / 'smoke.sqlite3'))
        try:
            for node, ident, config in candidates:
                if config['kind'] == 'agent':
                    if not config.get('command'):
                        add(node, ident, 'agent_probe', 'unknown', 'Interactive Agent has no automatic command to probe.')
                        continue
                    marker = uid('loop-smoke-ok')
                    prompt = 'Startup check only. Do not use tools, read files, or perform any business task. Reply with exactly: ' + marker
                    try:
                        result = run_command(config['command'], prompt, min(timeout, config.get('timeout', timeout)), config.get('cwd'))
                        if result.returncode:
                            raise Invalid('Agent exited ' + str(result.returncode) + ': ' + result.stderr[-1500:])
                        if marker not in result.stdout:
                            raise Invalid('Agent exited without the requested probe response')
                        add(node, ident, 'agent_probe', 'pass', 'Configured command and cwd returned the probe response.', cwd=config.get('cwd'))
                    except Invalid as exc:
                        add(node, ident, 'agent_probe', 'fail', str(exc), cwd=config.get('cwd'), category='agent_configuration_or_access')
                elif config['kind'] == 'external':
                    matrix = definition(config)
                    states = {matrix['initial']} | {r['to'] for r in matrix['transitions'] if r['to'] not in TERMINAL}
                    pairs = {(r['from'], r['event']) for r in matrix['transitions']}
                    pairs |= {(s, 'process_error') for s in states}
                    pairs |= {(s, 'check_error') for s in states - {matrix['initial']}}
                    pairs |= {(r['to'], 'check_error') for r in matrix['transitions'] if r['event'] == 'submitted' and r['to'] not in TERMINAL}
                    examples = [c for c in cases if (c['node'], c['implementation']) == (node, ident)]
                    for state, event in sorted(pairs):
                        rows = [r for r in matrix['transitions'] if r['from'] == state and r['event'] == event]
                        if not rows:
                            add(node, ident, 'lifecycle_probe', 'fail', 'Uncovered platform event: ' + state + ' + ' + event,
                                state=state, event=event, category='loop_contract')
                            continue
                        supplied = [c for c in examples if (c['state'], c['event']) == (state, event)]
                        probes = supplied or [{'state': state, 'event': event}]
                        for case in probes:
                            if not supplied:
                                try:
                                    check_parameters(config, case.get('parameters', {}))
                                except Invalid as exc:
                                    add(node, ident, 'lifecycle_probe', 'unknown', str(exc), state=state, event=event, category='context_required')
                                    continue
                            try:
                                detail = probe_transition(engine, config, case)
                                add(node, ident, 'lifecycle_probe', 'pass', detail, state=state, event=event)
                            except Invalid as exc:
                                unknown = not supplied and any('when' in r for r in rows) and str(exc).startswith(('Invalid transition condition:', 'No matching transition:'))
                                add(node, ident, 'lifecycle_probe', 'unknown' if unknown else 'fail', str(exc), state=state, event=event,
                                    category='context_required' if unknown else 'loop_contract')
                        if any('when' in r for r in rows) and not supplied:
                            add(node, ident, 'lifecycle_probe', 'unknown', 'Provide cases for conditional branches, including retry limits.', state=state, event=event)
                    for case in examples:
                        if (case['state'], case['event']) not in pairs:
                            add(node, ident, 'lifecycle_probe', 'fail', 'Case names an uncovered state/event.', state=case['state'], event=case['event'], category='loop_contract')
                    add(node, ident, 'external_probe', 'unknown', 'Lifecycle reports were simulated; submit/observe commands and external services were not invoked.')
                else:
                    add(node, ident, 'runtime', 'unknown', 'This execution kind requires a business-specific acceptance run.')
        finally:
            engine.close()
    return dict(mode='runtime', ready=not any(c['status'] == 'fail' for c in checks),
                verified=bool(checks) and all(c['status'] == 'pass' for c in checks), checks=checks,
                notice='Agent startup uses installed commands and environment. Lifecycle probes use a temporary Timeline with empty output contracts; business behavior remains unverified.')
