"""Timeline construction. Called by writers, never by the scheduling tick."""
import copy
import time
from loop_anything.runtime.timeline_model import check_task, expand
from loop_anything.runtime.model import Conflict, Invalid, contract, digest, path


def add_task(run, spec, origin):
    """Install an explicit Task in the caller's Timeline transaction."""
    from loop_anything.runtime.store import Store
    spec = copy.deepcopy(spec)
    spec.pop('policy', None)
    parent_id = spec.pop('parent_id', None)
    check_task(run['loop_definition'], spec)
    from loop_anything.runtime.implementations import check_selection
    check_selection(run, spec)
    old = run['tasks'].get(spec['id'])
    if old:
        if old['spec'] != spec or old.get('parent_id') != parent_id:
            raise Conflict('Task id already names a different plan: ' + spec['id'])
        return old
    if len(run['tasks']) >= run['loop_definition'].get('limits', {}).get('max_tasks', float('inf')):
        raise Invalid('Timeline Task budget exhausted')
    for destination in spec['outputs'].values():
        for tasks in run['tasks'].values():
            if tasks['status'] in ('cancelled', 'stale', 'skipped'):
                continue
            if any(d['id'] == destination['id'] and d.get('expected_revision', 0) == destination.get('expected_revision', 0)
                   for d in tasks['spec']['outputs'].values()):
                raise Conflict('Two tasks items would write the same record version: ' + destination['id'])
    item = dict(id=spec['id'], spec=copy.deepcopy(spec), parent_id=parent_id, origin=origin, status='planned',
                settings_revision=run['settings']['revision'],
                created_at=time.time(), execution_id=None, wait_reasons=[])
    run['tasks'][item['id']] = item
    Store.log(run, 'planned', 'Timeline Task created: ' + item['id'], detail={'tasks': spec['id'], 'template': spec['node'], 'origin': origin, 'after': copy.deepcopy(spec)})
    return item


def validate_plans(bp):
    plans = bp.get('plans', {})
    if not isinstance(plans, dict):
        raise Invalid('plans must map names to batch templates')
    from loop_anything.runtime.model import check_schema
    for name, plan in plans.items():
        if not isinstance(name, str) or not name or not isinstance(plan, dict):
            raise Invalid('Invalid plan name or template')
        if set(plan) - {'parameters', 'steps', 'description'}:
            raise Invalid('Plan accepts parameters, steps and description only')
        check_schema(plan.get('parameters', {'type': 'object'}))
        steps = plan.get('steps')
        if not isinstance(steps, dict) or not steps:
            raise Invalid('Plan steps must be a nonempty object: ' + name)
        for key, step in steps.items():
            if not isinstance(key, str) or not key or not isinstance(step, dict) or step.get('node') not in bp['nodes']:
                raise Invalid('Plan step must name a declared node')
            if set(step) - {'node', 'inputs', 'parameters', 'after', 'each', 'implementation'}:
                raise Invalid('Unknown batch step field: ' + key)
            if 'implementation' in step and step['implementation'] is not None and not isinstance(step['implementation'], str):
                raise Invalid('Step implementation must be an ID or null')
            if bp['nodes'][step['node']].get('initialize_timeline'):
                raise Invalid('A batch cannot recreate the initializer')
            if not isinstance(step.get('inputs', {}), dict):
                raise Invalid('Step inputs must be an object')
            if set(step.get('inputs', {})) != set(bp['nodes'][step['node']]['inputs']):
                raise Invalid('Step inputs must match node ports: ' + key)
            if 'each' in step and (not isinstance(step['each'], str) or not step['each']):
                raise Invalid('each must be a path in plan values')
            after = step.get('after', [])
            if not isinstance(after, list) or any(x not in steps or x == key for x in after):
                raise Invalid('Step after must name other steps in this plan')
            for source in step.get('inputs', {}).values():
                if isinstance(source, dict) and 'from' in source:
                    upstream = steps.get(source['from'])
                    if not upstream or source.get('port') not in bp['nodes'][upstream['node']]['outputs']:
                        raise Invalid('Step input references an unknown step output')

        visiting, visited = set(), set()
        def visit(key):
            if key in visiting:
                raise Invalid('Plan contains a step dependency cycle: ' + name)
            if key in visited:
                return
            visiting.add(key)
            step = steps[key]
            for upstream in list(step.get('after', [])) + [s['from'] for s in step.get('inputs', {}).values() if isinstance(s, dict) and 'from' in s]:
                visit(upstream)
            visiting.remove(key)
            visited.add(key)
        for key in steps:
            visit(key)


def build_plan(bp, name, key, values=None, steps=None, round_name=None):
    """Expand one loop_definition batch, omitting skipped steps without placeholders.

    `each` expands a step over a values array. `from` binds the matching item;
    `collect: true` binds all outputs of that step in this batch only.
    """
    if not isinstance(key, str) or not key:
        raise Invalid('Plan key must be nonempty')
    if round_name is not None and (not isinstance(round_name, str) or not round_name.strip()):
        raise Invalid('round must be a nonempty display label')
    plan = bp.get('plans', {}).get(name)
    if plan is None:
        raise Invalid('Unknown loop_definition plan: ' + str(name))
    values, overrides = values if values is not None else {}, steps if steps is not None else {}
    contract(values, plan.get('parameters', {'type': 'object'}), 'Plan values')
    if not isinstance(overrides, dict) or set(overrides) - set(plan['steps']):
        raise Invalid('Overrides must name steps in this plan')
    for override in overrides.values():
        if not isinstance(override, dict) or set(override) - {'skip', 'inputs', 'parameters', 'implementation'}:
            raise Invalid('Step override accepts only skip, inputs and parameters')
        if 'implementation' in override and override['implementation'] is not None and not isinstance(override['implementation'], str):
            raise Invalid('Step implementation override must be an ID or null')
        if type(override.get('skip', False)) is not bool:
            raise Invalid('Step skip must be boolean')
        if any(not isinstance(override[k], dict) for k in ('inputs', 'parameters') if k in override):
            raise Invalid('Step inputs/parameters overrides must be objects')
    prefix = 'batch-' + digest([name, key])[:16]
    groups, contexts = {}, {}
    for step_key, step in plan['steps'].items():
        groups[step_key] = []
        if overrides.get(step_key, {}).get('skip'):
            continue
        items = path(values, step['each']) if 'each' in step else [None]
        if not isinstance(items, list):
            raise Invalid('Step each must resolve to an array: ' + step_key)
        for index, item in enumerate(items):
            explicit = overrides.get(step_key, {}).get('implementation', step.get('implementation')) or None
            task_id = prefix + '.' + step_key + '.' + str(index)
            spec = dict(id=task_id, node=step['node'], inputs={},
                        outputs={p: {'id': task_id + '.' + p} for p in bp['nodes'][step['node']]['outputs']})
            if explicit is not None:
                spec['implementation'] = explicit
            if round_name is not None:
                spec['round'] = round_name
            groups[step_key].append(spec)
            contexts[task_id] = {'values': values, 'item': item, 'index': index}
    for step_key, group in groups.items():
        step = plan['steps'][step_key]
        override = overrides.get(step_key, {})
        for index, spec in enumerate(group):
            context = contexts[spec['id']]
            spec['parameters'] = expand(dict(step.get('parameters', {}), **override.get('parameters', {})), context)
            for port, raw in dict(step.get('inputs', {}), **override.get('inputs', {})).items():
                source = expand(raw, context)
                if isinstance(source, dict) and 'from' in source:
                    if set(source) - {'from', 'port', 'collect'} or type(source.get('collect', False)) is not bool:
                        raise Invalid('Step output source accepts from, port and boolean collect only')
                    upstream = groups.get(source['from'])
                    if not upstream:
                        raise Invalid('Input ' + step_key + '.' + port + ' needs omitted/empty step ' + source['from'] + '; bind an existing record explicitly')
                    output = source.get('port')
                    if any(output not in w['outputs'] for w in upstream):
                        raise Invalid('Unknown upstream output port')
                    if source.get('collect'):
                        source = {'records': [w['outputs'][output]['id'] for w in upstream]}
                    else:
                        upstream_step = plan['steps'][source['from']]
                        if len(upstream) == 1:
                            selected = upstream[0]
                        elif step.get('each') and step.get('each') == upstream_step.get('each'):
                            selected = upstream[index]
                        else:
                            raise Invalid('Multiple upstream Tasks require collect or the same each array')
                        source = {'record': selected['outputs'][output]['id']}
                spec['inputs'][port] = source
            spec['after'] = [w['id'] for predecessor in step.get('after', []) for w in groups[predecessor]]
            check_task(bp, spec)
    tasks = [spec for group in groups.values() for spec in group]
    # Catch ordering/data cycles before publishing the batch.
    producers = {d['id']: w['id'] for w in tasks for d in w['outputs'].values()}
    deps = {w['id']: list(w['after']) + [producers[rid] for source in w['inputs'].values()
            for rid in source.get('records', [source.get('record')]) if rid in producers] for w in tasks}
    visited, visiting = set(), set()
    def visit(task_id):
        if task_id in visiting:
            raise Invalid('Batch contains an Task dependency cycle')
        if task_id in visited:
            return
        visiting.add(task_id)
        for predecessor in deps[task_id]:
            visit(predecessor)
        visiting.remove(task_id)
        visited.add(task_id)
    for task_id in deps:
        visit(task_id)
    return tasks


def task_dependencies(run):
    """Actual consumed versions for attempts; currently resolved sources for plans."""
    tasks = run.get('tasks', {})
    executions = {e['id']: e for e in run.get('executions', [])}
    producers = {(d['id'], d.get('expected_revision', 0) + 1): t['id']
                 for t in tasks.values() if t['status'] not in ('cancelled', 'stale')
                 for d in t['spec']['outputs'].values()}
    deps = {}
    for ident, task in tasks.items():
        links = set(task['spec'].get('after', []))
        attempt = executions.get(task.get('execution_id'))
        if attempt:
            for source in attempt.get('sources', {}).values():
                for ref in source if isinstance(source, list) else [source]:
                    producer = executions.get(ref.get('execution'), {}).get('task_id')
                    if producer and producer != ident:
                        links.add(producer)
        else:
            for source in task['spec']['inputs'].values():
                for rid in source.get('records', [source.get('record')]):
                    if not rid:
                        continue
                    versions = run.get('records', {}).get(rid, [])
                    record = next((v for v in reversed(versions) if not source.get('revision') or v['revision'] == source['revision']), None)
                    producer = (record.get('tasks') or executions.get(record.get('producer'), {}).get('task_id')) if record else producers.get((rid, source.get('revision', 1)))
                    if producer:
                        links.add(producer)
        deps[ident] = sorted(links)
    return deps


def validate_task_dependencies(run):
    # Kahn's algorithm also handles long research histories without recursion limits.
    deps = {k: set(v) & run['tasks'].keys() for k, v in task_dependencies(run).items()}
    followers = {k: [] for k in deps}
    for task, sources in deps.items():
        for source in sources:
            followers[source].append(task)
    ready = [k for k, sources in deps.items() if not sources]
    count = 0
    while ready:
        source = ready.pop()
        count += 1
        for task in followers[source]:
            deps[task].remove(source)
            if not deps[task]:
                ready.append(task)
    if count != len(deps):
        raise Invalid('Task dependency cycle: ' + ', '.join(k for k, sources in deps.items() if sources))
