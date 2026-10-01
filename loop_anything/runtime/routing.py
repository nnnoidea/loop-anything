"""Author-declared event routes reuse plan expansion inside the report transaction."""
import copy
import re

from loop_anything.runtime.checks import evaluate, validate_expression
from loop_anything.runtime.model import Invalid, path, digest
from loop_anything.runtime.timeline_model import expand
from loop_anything.runtime.timeline_plan import add_task, build_plan, validate_task_dependencies
from loop_anything.runtime.task_scope import attach_tasks, owner_for


CONTEXT_FIELDS = {'inputs', 'outputs', 'parameters', 'settings', 'detail', 'attempt', 'task_revision',
                  'task', 'transition', 'item', 'index'}


def validate_routes(bp):
    for node_id, node in bp['nodes'].items():
        routes = node.get('routes', [])
        location = ['nodes', node_id, 'routes']
        if not isinstance(routes, list):
            raise Invalid('routes must be an array', path=location)
        ids = set()
        for index, route in enumerate(routes):
            here = location + [index]
            if not isinstance(route, dict) or not {'id', 'event', 'plan', 'values'} <= set(route) or set(route) - {'id', 'event', 'plan', 'values', 'each', 'when', 'steps', 'round'}:
                raise Invalid('Route needs id, event, plan, values and optional each/when/steps/round', path=here)
            for field in ('id', 'event'):
                if not isinstance(route[field], str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', route[field]):
                    raise Invalid('Route ' + field + ' must be a nonempty identifier', path=here + [field])
            if route['id'] in ids:
                raise Invalid('Route IDs must be unique within the node', path=here + ['id'])
            ids.add(route['id'])
            if not isinstance(route['plan'], str) or route['plan'] not in bp.get('plans', {}):
                raise Invalid('Route must name an existing plan', path=here + ['plan'])
            if any(bp['nodes'][s['node']].get('initialize_timeline') for s in bp['plans'][route['plan']]['steps'].values()):
                raise Invalid('Routes cannot create initialization tasks', path=here + ['plan'])
            for field in ('values', 'steps'):
                if field in route and not isinstance(route[field], dict):
                    raise Invalid('Route ' + field + ' must be an object template', path=here + [field])
            for field in ('each', 'round'):
                if field in route and (not isinstance(route[field], str) or not route[field].strip()):
                    raise Invalid('Route ' + field + ' must be nonempty text', path=here + [field])
            if 'when' in route:
                if not isinstance(route['when'], dict) or not route['when']:
                    raise Invalid('Route when must be a deterministic expression', path=here + ['when'])
                try:
                    validate_expression(route['when'])
                except Invalid as exc:
                    raise Invalid(str(exc), path=here + ['when']) from None
            # Only explicit report context is available, never credentials or arbitrary Run state.
            def references(value, expression=False):
                if isinstance(value, dict):
                    if set(value) == {'$'} or expression and set(value) == {'path'}:
                        key = next(iter(value.values()))
                        if not isinstance(key, (str, list)) or not key:
                            raise Invalid('Route reference needs a context path', path=here)
                        first = key.split('.')[0] if isinstance(key, str) else key[0]
                        if first not in CONTEXT_FIELDS:
                            raise Invalid('Unknown route context: ' + str(first), path=here)
                    for child in value.values():references(child, expression)
                elif isinstance(value, list):
                    for child in value:references(child, expression)
            for field in ('values', 'steps'):
                references(route.get(field, {}))
            references(route.get('when', {}), True)
            if 'each' in route and route['each'].split('.')[0] not in CONTEXT_FIELDS - {'item', 'index'}:
                raise Invalid('Route each must read a report context array', path=here + ['each'])


def prepare_routes(run, execution, report, context):
    """Validate all generated tasks on a copy before any result/state is committed.

    This also protects timer/event callers which catch errors within Store.edit.
    """
    node = run['loop_definition']['nodes'][execution['node']]
    routes = [r for r in node.get('routes', []) if r['event'] == report['event']]
    if not routes:
        return [], []
    shadow = copy.deepcopy(run)
    actor = owner_for(run, execution['token']) if execution['implementation']['kind'] == 'agent' else None
    for spec in attach_tasks(shadow, report.get('envelope', {}).get('tasks', []), execution['task_id'], actor):
        add_task(shadow, spec, {'execution': execution['id']})
    context = dict(context, task={'id': execution['task_id'], 'node': execution['node'],
                                'outputs': run['tasks'][execution['task_id']]['spec']['outputs']})
    from loop_anything.runtime.task_refs import resolve_task_references, describe_references
    prepared, firings = [], []
    for route in routes:
        try:
            items = path(context, route['each']) if 'each' in route else [None]
            if not isinstance(items, list):raise Invalid('each must resolve to an array')
            firing = {'route_id': route['id'], 'plan': route['plan'], 'batches': [], 'omitted_items': []}
            for index, item in enumerate(items):
                current = dict(context, item=item, index=index)
                if 'when' in route:
                    included = evaluate(route['when'], current)
                    if type(included) is not bool:raise Invalid('when must return a boolean')
                    if not included:
                        firing['omitted_items'].append(index)
                        continue
                values, steps = expand(route['values'], current), expand(route.get('steps', {}), current)
                if not isinstance(values, dict) or not isinstance(steps, dict):
                    raise Invalid('values and steps must resolve to objects')
                summary = {}
                # The report identity is already authenticated and deduplicated by the writer.
                key = ['route', execution['id'], report['report_id'], route['id'], index]
                specs = build_plan(run['loop_definition'], route['plan'], digest(key), values, steps,
                                   expand(route['round'], current) if 'round' in route else None, summary, defer_references=True, resolved_overrides=True)
                origin = {'execution': execution['id'], 'route_id': route['id'], 'report_id': report['report_id'],
                          'plan': route['plan'], 'batch_id': summary['batch_id'], 'item_index': index}
                for spec in attach_tasks(shadow, specs, execution['task_id'], actor):
                    prepared.append((spec, origin))
                firing['batches'].append(dict(summary, task_ids=[s['id'] for s in specs]))
            firings.append(firing)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise Invalid('Route ' + route['id'] + ': ' + str(exc), path=['nodes', execution['node'], 'routes', route['id']]) from None
    resolved = resolve_task_references([spec for spec, _ in prepared], [t['spec'] for t in shadow['tasks'].values()])
    prepared = [(spec, original[1]) for spec, original in zip(resolved, prepared)]
    for spec, origin in prepared:
        try:add_task(shadow, spec, origin)
        except Invalid as exc:raise Invalid('Route ' + origin['route_id'] + ': ' + str(exc)) from None
    for firing in firings:
        for batch in firing['batches']:
            batch['references'] = describe_references([s for s in resolved if s['id'] in batch['task_ids']])
    validate_task_dependencies(shadow)
    return prepared, firings
