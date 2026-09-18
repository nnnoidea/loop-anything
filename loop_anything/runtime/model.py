"""Small, deliberately non-executable loop_definition language."""
import copy
import hashlib
import json
import math


class Invalid(ValueError):
    pass


class Conflict(Invalid):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def path(value, key):
    if not key:
        return value
    for part in key.split('.') if isinstance(key, str) else key:
        if isinstance(value, list):
            value = value[int(part)]
        else:
            value = value[part]
    return value


def contract(value, schema, label='output'):
    types = {'object': dict, 'array': list, 'string': str, 'number': (int, float), 'integer': int, 'boolean': bool}
    kind = schema.get('type')
    if kind not in types or not isinstance(value, types[kind]) or (kind in ('number', 'integer') and isinstance(value, bool)):
        raise Invalid('%s must be %s' % (label, kind))
    if schema.get('nonempty') and not value:
        raise Invalid('%s must not be empty' % label)
    if 'enum' in schema and value not in schema['enum']:
        raise Invalid('%s must be one of the declared enum values' % label)
    if kind in ('number', 'integer'):
        if not math.isfinite(value):
            raise Invalid(label + ' must be finite')
        for key, valid in [('minimum', lambda x: value >= x), ('maximum', lambda x: value <= x)]:
            if key in schema and not valid(schema[key]):
                raise Invalid(label + ' violates ' + key)
    if kind == 'array':
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', float('inf')):
            raise Invalid(label + ' violates array length bounds')
        if schema.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise Invalid(label + ' requires unique items')
    if kind == 'object':
        if schema.get('additionalProperties') is False and set(value) - set(schema.get('properties', {})):
            raise Invalid(label + ' has undeclared fields')
        for field in schema.get('required', []):
            if field not in value:
                raise Invalid('%s missing %s' % (label, field))
        for field, child in schema.get('properties', {}).items():
            if field in value:
                contract(value[field], child, label + '.' + field)
    if kind == 'array' and 'items' in schema:
        for i, item in enumerate(value):
            contract(item, schema['items'], '%s[%s]' % (label, i))


def check_schema(schema):
    if not isinstance(schema, dict) or schema.get('type') not in ('object', 'array', 'string', 'number', 'integer', 'boolean'):
        raise Invalid('Every output needs a supported type')
    if 'enum' in schema and (not isinstance(schema['enum'], list) or not schema['enum']):
        raise Invalid('enum must be a nonempty array')
    for key in ('minimum', 'maximum'):
        if key in schema and (type(schema[key]) not in (int, float) or not math.isfinite(schema[key])):
            raise Invalid(key + ' must be finite numeric bound')
    for key in ('minItems', 'maxItems'):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            raise Invalid(key + ' must be nonnegative integer')
    for child in schema.get('properties', {}).values():
        check_schema(child)
    if 'items' in schema:
        check_schema(schema['items'])


def validate_guide(loop_definition):
    """Optional author-facing explanation, never interpreted by the scheduler."""
    if 'guide' not in loop_definition:
        return
    guide = loop_definition['guide']
    fields = {'purpose', 'suitable_for', 'not_for', 'preparation', 'results', 'lifecycle', 'participation', 'effects', 'parameters'}
    if not isinstance(guide, dict) or set(guide) - fields:
        raise Invalid('guide contains unsupported fields')
    for key, value in guide.items():
        if key != 'parameters' and not isinstance(value, str):
            raise Invalid('guide.' + key + ' must be text')
    params = guide.get('parameters', {})
    if not isinstance(params, dict):
        raise Invalid('guide.parameters must be an object')
    for name, spec in params.items():
        if not name or not isinstance(spec, dict) or set(spec) - {'label', 'description'} or not all(isinstance(v, str) for v in spec.values()):
            raise Invalid('guide.parameters entries accept label and description text only')


def current_definition(definition):
    """Read old package checks through the one current assertion contract."""
    result = copy.deepcopy(definition)
    result.pop('attention_node', None)  # Old implicit recovery is not an opt-in.
    result.get('seed', {}).pop('policy', None)
    for plan in result.get('plans', {}).values():
        for step in plan.get('steps', {}).values():
            step.pop('policy', None)
    for node in result.get('nodes', {}).values():
        for check in node.pop('completion_checks', []):
            if set(check) != {'left', 'right'} or not all(isinstance(v, str) for v in check.values()):
                raise Invalid('Legacy completion check requires left/right field paths')
            node.setdefault('assertions', []).append({
                'message': check['left'] + ' must equal ' + check['right'],
                'test': {'op': 'eq', 'args': [{'path': check['left']}, {'path': check['right']}]}})
        node.pop('context_record_types', None)
    return result


def validate(loop_definition, implementations):
    if not isinstance(loop_definition, dict) or loop_definition.get('schema_version') != 2:
        return {'valid': False, 'errors': ['Historical loop_definitions are read-only; author a Timeline-based Loop'], 'warnings': []}
    from loop_anything.runtime.timeline_model import validate_v2
    return validate_v2(loop_definition, implementations)
