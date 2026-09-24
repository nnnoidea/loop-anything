"""Shared Programmable Timeline v2 contract. No domain names or simulation policies."""
import copy
import math
import re
from loop_anything.runtime.model import Invalid, contract, check_schema, path, validate_guide
from loop_anything.runtime.checks import validate_expression

VERSION = 2
SEMANTIC_FIELDS = {'intent', 'objective', 'requirements', 'constraints', 'guidance', 'authorization'}
ENDING_FIELDS = {'completion_rule', 'termination_signal'}


def is_v2(run):
    return run.get('schema_version') == VERSION


def expand(value, context):
    """Explicit data substitution, never eval or natural-language interpretation."""
    def reference(key):
        try:
            return path(context, key)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise Invalid('Invalid value reference ' + str(key) + ': ' + str(exc)) from None
    if isinstance(value, dict):
        if set(value) == {'$'}:
            return copy.deepcopy(reference(value['$']))
        return {k: expand(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, context) for v in value]
    if isinstance(value, str):
        return re.sub(r'\{([\w.]+)\}', lambda m: str(reference(m[1])), value)
    return value


def unused_records(bp):
    if not isinstance(bp, dict) or not isinstance(bp.get('records', {}), dict) or not isinstance(bp.get('nodes'), dict):
        return []
    used = {s.get('record_type') for n in bp['nodes'].values() if isinstance(n, dict) and isinstance(n.get('outputs', {}), dict)
            for s in (n.get('outputs') or {}).values() if isinstance(s, dict) and isinstance(s.get('record_type'), str)}
    return sorted(set(bp.get('records', {})) - used)


def prune_removed_records(before, after):
    """Remove only generated types that lost their last output reference in this edit."""
    generated = {node + '.' + port for node, n in before.get('nodes', {}).items() if isinstance(n, dict) and isinstance(n.get('outputs', {}), dict)
                 for port, s in (n.get('outputs') or {}).items() if isinstance(s, dict) and s.get('record_type') == node + '.' + port}
    for name in generated.intersection(unused_records(after)):
        after['records'].pop(name, None)


def validate_v2(bp, implementations):
    errors, warnings, issues, location = [], [], [], []
    try:
        if not isinstance(bp, dict) or not isinstance(implementations, dict):
            raise Invalid('LoopDefinition and implementations must be objects')
        location = ['guide']
        validate_guide(bp)
        location = ['schema_version']
        if bp.get('schema_version') != VERSION:
            raise Invalid('Expected Programmable Timeline schema_version=2')
        for key in ('id', 'version', 'entry'):
            location = [key]
            if not isinstance(bp.get(key), str) or not bp[key]:
                raise Invalid('Missing ' + key)
        location = ['nodes']
        nodes = bp['nodes']
        if not isinstance(nodes, dict) or bp['entry'] not in nodes:
            raise Invalid('Entry must reference a declared node')
        location = ['fallback_node']
        validate_fallback(bp, implementations, bp.get('fallback_node'))
        location = ['global_agent_node']
        validate_global_agent(bp, implementations, bp.get('global_agent_node'))
        location = ['implementations']
        if '$notifications' in implementations:
            raise Invalid('Loop notification senders are retired; configure local notification outlets and remove implementations.$notifications before sharing')
        if set(implementations) - set(nodes):
            raise Invalid('Implementation references an unknown node')
        location = ['limits']
        limits = bp.get('limits', {})
        if not isinstance(limits, dict) or set(limits) - {'max_tasks', 'max_attempts', 'max_agent_calls', 'attempts_by_node'}:
            raise Invalid('Unknown runtime limit')
        for key, limit in limits.items():
            values = limit.values() if key == 'attempts_by_node' and isinstance(limit, dict) else [limit]
            if any(type(v) is not int or v < 1 for v in values):
                raise Invalid('Runtime limits must be positive integers')
        if set(limits.get('attempts_by_node', {})) - set(nodes):
            raise Invalid('Attempt budget references unknown node')
        if not isinstance(nodes, dict) or bp['entry'] not in nodes:
            raise Invalid('Entry must reference a declared node')
        location = ['handbook']
        if not isinstance(bp.get('handbook'), dict) or not (bp['handbook'].get('instructions') or bp['handbook'].get('path')):
            raise Invalid('A Loop operation handbook with instructions or a Skill path is required')
        location = ['records']
        records = bp.get('records', {})
        if not isinstance(records, dict):
            raise Invalid('records must map record types to schemas')
        for record, schema in records.items():
            location = ['records', record]
            check_schema(schema)
        for name, node in nodes.items():
            location = ['nodes', name]
            if 'completion_checks' in node:
                raise Invalid('Use assertions with eq for node completion checks')
            if 'terminal' in node:
                raise Invalid('Node terminal flags are retired; write a completion_rule or termination_signal in Programmable Timeline')
            if 'allow_skip' in node:
                raise Invalid('allow_skip is obsolete; omit steps through build_plan')
            if 'agent_settings_schema' in node:
                location = ['nodes', name, 'agent_settings_schema']
                check_schema(node['agent_settings_schema'])
            if 'parameter_schema' in node:
                location = ['nodes', name, 'parameter_schema']
                check_schema(node['parameter_schema'])
            for index, check in enumerate(node.get('assertions', [])):
                location = ['nodes', name, 'assertions', index]
                if set(check) != {'message', 'test'} or not isinstance(check['message'], str):
                    raise Invalid('Assertions need message and test')
                validate_expression(check['test'])
            location = ['nodes', name]
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
                raise Invalid('Invalid node id')
            if not node.get('instructions'):
                raise Invalid('Node operation instructions required: ' + name)
            if not isinstance(node.get('inputs'), dict) or not isinstance(node.get('outputs'), dict):
                raise Invalid('Node inputs and outputs must be explicit objects: ' + name)
            if not isinstance(node.get('plan_nodes', []), list):
                raise Invalid('plan_nodes must be an array')
            for port, schema in node.get('inputs', {}).items():
                location = ['nodes', name, 'inputs', port]
                check_schema(schema)
            for output, spec in node.get('outputs', {}).items():
                location = ['nodes', name, 'outputs', output]
                if spec.get('record_type') not in records:
                    raise Invalid('Unknown output record type: ' + name + '.' + output)
            from loop_anything.runtime.implementations import validate_candidates
            if name in implementations:
                location = ['implementations', name]
                validate_candidates(implementations[name])
                from loop_anything.runtime.implementations import options
                for ident, config in options(implementations[name]).items():
                    for i, rule in enumerate(config.get('lifecycle',{}).get('transitions',[])):
                        for j, notice in enumerate(rule.get('notify',[])):
                            location=['implementations',name,ident,'lifecycle','transitions',i,'notify',j,'route']
                            if notice.get('route','default') not in ('default','workspace'):
                                raise Invalid('Loop notifications use default or workspace; choose personal outlets on the Run')
            location = ['nodes', name]
            if node.get('initialize_timeline') and name != bp['entry']:
                raise Invalid('Only entry may initialize user semantics')
            if any(target not in nodes for target in node.get('plan_nodes', [])):
                raise Invalid('plan_nodes must name declared capabilities')
        location = ['entry']
        if not nodes[bp['entry']].get('initialize_timeline'):
            raise Invalid('Entry must initialize structured Programmable Timeline')
        location = ['rules']
        if bp.get('rules'):
            raise Invalid('LoopDefinition rules are retired; use plans for tasks construction and Timeline completion_rule for terminal transitions')
        from loop_anything.runtime.timeline_plan import validate_plans
        location = ['plans']
        validate_plans(bp)
        location = ['seed']
        check_task(bp, bp['seed'])
        if bp['seed']['node'] != bp['entry']:
            raise Invalid('Seed must use entry node')
        warnings.append('Domain judgments and external side effects require handler acceptance; schema validation does not prove semantic correctness.')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        errors.append(str(exc))
        issues.append({'path': location + (getattr(exc, 'path', None) or []), 'message': str(exc)})
    from loop_anything.runtime.implementations import choose
    missing = sorted(n for n in bp.get('nodes', {}) if choose(implementations, n)[1] is None) if not errors and isinstance(bp, dict) and isinstance(bp.get('nodes'), dict) and isinstance(implementations, dict) else []
    return {'valid': not errors, 'errors': errors, 'warnings': warnings, 'unbound_nodes': missing, 'issues': issues, 'unused_records': unused_records(bp)}


def validate_fallback(bp, implementations, node_id):
    if node_id is None or node_id == '':
        return
    if not isinstance(node_id, str) or node_id not in bp['nodes'] or node_id == bp['entry']:
        raise Invalid('fallback_node must name a declared non-entry node, or be empty to disable')
    node = bp['nodes'][node_id]
    if node.get('inputs'):
        raise Invalid('Fallback reads current issues through Run tools; its input ports must be empty')
    if 'parameter_schema' in node:
        contract({}, node['parameter_schema'], 'Fallback parameters')
    from loop_anything.runtime.implementations import options, check_parameters
    for ident, config in options(implementations.get(node_id)).items():
        if config.get('kind') != 'agent':
            raise Invalid('Fallback node implementations must be Agents')
        check_parameters(config, {}, 'Fallback ' + ident + ' parameters')


def check_task(bp, tasks):
    if not isinstance(tasks.get('id'), str) or not tasks['id']:
        raise Invalid('Task needs a stable id')
    if 'implementation' in tasks and tasks['implementation'] is not None and (not isinstance(tasks['implementation'], str) or not tasks['implementation']):
        raise Invalid('Task implementation must be an ID or null to inherit')
    if 'round' in tasks and (not isinstance(tasks['round'], str) or not tasks['round'].strip()):
        raise Invalid('Task round must be a nonempty display label')
    node = bp['nodes'].get(tasks.get('node'))
    if node is None:
        raise Invalid('Task must target a declared node')
    after = tasks.get('after', [])
    if not isinstance(after, list) or any(not isinstance(x, str) or not x or x == tasks['id'] for x in after) or len(set(after)) != len(after):
        raise Invalid('after must list unique other Task IDs')
    if 'skip' in tasks or tasks.get('status') == 'skipped':
        raise Invalid('Do not create skipped Tasks; omit the step in build_plan')
    if set(tasks.get('inputs', {})) != set(node.get('inputs', {})):
        raise Invalid('Task inputs must match node declarations: ' + tasks['id'])
    if set(tasks.get('inputs', {})) - set(node.get('inputs', {})):
        raise Invalid('Unknown Task input')
    if set(tasks.get('outputs', {})) != set(node.get('outputs', {})):
        raise Invalid('Task outputs must match node declarations: ' + tasks['id'])
    if 'parameter_schema' in node:
        contract(tasks.get('parameters', {}), node['parameter_schema'], 'Task parameters')
    for name, source in tasks.get('inputs', {}).items():
        if not isinstance(source, dict) or len(set(source) & {'record', 'records', 'run', 'settings', 'literal'}) != 1:
            raise Invalid('Input needs one explicit source: ' + name)
        if 'record' in source and (not isinstance(source['record'], str) or not source['record']):
            raise Invalid('record source must be an id')
        if 'records' in source and (not isinstance(source['records'], list) or not all(isinstance(x, str) and x for x in source['records'])):
            raise Invalid('records source must list record IDs')
        if 'literal' in source:
            contract(source['literal'], node['inputs'][name], 'Task input ' + name)
    for destination in tasks.get('outputs', {}).values():
        if not isinstance(destination, dict) or not isinstance(destination.get('id'), str) or not destination['id']:
            raise Invalid('Output must identify the record to commit')
        if type(destination.get('expected_revision', 0)) is not int or destination.get('expected_revision', 0) < 0:
            raise Invalid('expected_revision must be nonnegative')


def settings_defaults(title):
    return {'revision': 1, 'intent': title, 'objective': '', 'authorization': '', 'requirements': [], 'constraints': {},
            'guidance': '', 'max_parallel': 4, 'hooks': [], 'fallback_node': None, 'bindings': {}, 'completion_rule': None, 'termination_signal': ''}


def validate_settings(settings):
    if not isinstance(settings.get('notification_route','user'),str) or not settings.get('notification_route','user'):raise Invalid('notification_route must be nonempty')
    command = settings.get('notification_command', [])
    if not isinstance(command, list):
        raise Invalid('notification_command must be an argv array')
    if command:
        from loop_anything.runtime.implementations import validate_implementation
        validate_implementation({'kind': 'command', 'command': command})
    if settings.get('completion_rule') is not None:
        validate_expression(settings['completion_rule'])
    if not isinstance(settings.get('termination_signal', ''), str):
        raise Invalid('termination_signal must be text explaining why the Run should end')
    if not isinstance(settings.get('authorization', ''), str):
        raise Invalid('User authorization must be natural-language text')
    if not isinstance(settings['intent'], str) or not isinstance(settings['objective'], str) or not isinstance(settings['guidance'], str):
        raise Invalid('Intent, objective and guidance must be strings')
    if not isinstance(settings['requirements'], list) or not all(isinstance(x, str) for x in settings['requirements']):
        raise Invalid('Requirements must be a string array')
    if not isinstance(settings['constraints'], dict):
        raise Invalid('Constraints must be an object')
    if type(settings['max_parallel']) is not int or not 1 <= settings['max_parallel'] <= 8:
        raise Invalid('Parallelism must be between 1 and 8')


def validate_result(bp, node_id, outputs):
    node = bp['nodes'][node_id]
    if not isinstance(outputs, dict) or set(outputs) != set(node['outputs']):
        raise Invalid('All declared outputs must be submitted together to finish')
    for name, spec in node['outputs'].items():
        contract(outputs[name], bp['records'][spec['record_type']], name)


def validate_global_agent(bp, implementations, node_id):
    if node_id is None or node_id == '':
        return
    from loop_anything.runtime.implementations import options
    if node_id not in bp['nodes'] or any(c.get('kind') != 'agent' for c in options(implementations.get(node_id)).values()):
        raise Invalid('global_agent_node must name a declared Agent node')
