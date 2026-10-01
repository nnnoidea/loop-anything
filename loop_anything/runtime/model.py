"""Small, deliberately non-executable loop_definition language."""
import copy
import hashlib
import json
import math


class Invalid(ValueError):
    def __init__(self, message, path=None):
        super().__init__(message)
        self.path = path


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


def record_refs(source):
    """Canonical record identities, including a separate pinned revision per item."""
    ids = source.get('records', [source.get('record')])
    revisions = source.get('revisions')
    if revisions is not None:
        if 'records' not in source or 'revision' in source or not isinstance(revisions, list) or len(revisions) != len(ids):
            raise Invalid('revisions requires records of equal length and cannot combine with revision')
        if any(type(v) is not int or v < 1 for v in revisions):
            raise Invalid('Record revisions must be positive integers')
    else:
        revision = source.get('revision')
        if revision is not None and (type(revision) is not int or revision < 1):
            raise Invalid('Record revision must be a positive integer')
        revisions = [revision] * len(ids)
    return list(zip(ids, revisions))


SCHEMA_TYPES = {'object': dict, 'array': list, 'string': str, 'number': (int, float),
                'integer': int, 'boolean': bool, 'null': type(None)}
SCHEMA_KEYWORDS = {'type', 'title', 'description', 'default', 'examples', 'format', 'nonempty',
                   'enum', 'const', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
                   'minLength', 'maxLength', 'pattern', 'minItems', 'maxItems', 'uniqueItems',
                   'properties', 'required', 'additionalProperties', 'items', 'minProperties', 'maxProperties',
                   'oneOf', 'anyOf', 'allOf', 'not', 'if', 'then', 'else', 'dependentRequired'}


def _equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def contract(value, schema, label='output'):
    """Validate the documented JSON Schema subset; no coercion or default injection."""
    if schema is True:
        return
    if schema is False:
        raise Invalid(label + ' is forbidden by schema')
    def matches(branch):
        try:
            contract(value, branch, label)
            return True
        except Invalid:
            return False
    kind = schema.get('type')
    kinds = kind if isinstance(kind, list) else [kind] if kind else []
    def has_type(k):
        return isinstance(value, SCHEMA_TYPES[k]) and not (k in ('number', 'integer') and isinstance(value, bool))
    if kinds and not any(has_type(k) for k in kinds):
        raise Invalid(label + ' must be ' + ' or '.join(kinds))
    if schema.get('nonempty') and not value:
        raise Invalid(label + ' must not be empty')
    if 'const' in schema and not _equal(value, schema['const']):
        raise Invalid(label + ' must equal the declared const')
    if 'enum' in schema and not any(_equal(value, item) for item in schema['enum']):
        raise Invalid(label + ' must be one of the declared enum values')
    for key in ('allOf', 'anyOf', 'oneOf'):
        if key not in schema:
            continue
        results = [matches(branch) for branch in schema[key]]
        if not (all(results) if key == 'allOf' else any(results) if key == 'anyOf' else sum(results) == 1):
            failures = []
            for index, branch in enumerate(schema[key]):
                try:contract(value, branch, label)
                except Invalid as exc:failures.append(str(index) + ': ' + str(exc))
            raise Invalid(label + ' violates ' + key + ' (' + '; '.join(failures or ['multiple branches matched']) + ')')
    if 'not' in schema and matches(schema['not']):
        raise Invalid(label + ' matches a forbidden schema')
    if 'if' in schema:
        contract(value, schema.get('then' if matches(schema['if']) else 'else', True), label)
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise Invalid(label + ' must be finite')
        for key, valid in [('minimum', lambda x: value >= x), ('maximum', lambda x: value <= x),
                           ('exclusiveMinimum', lambda x: value > x), ('exclusiveMaximum', lambda x: value < x)]:
            if key in schema and not valid(schema[key]):
                raise Invalid(label + ' violates ' + key)
    if isinstance(value, str):
        import re
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', float('inf')):
            raise Invalid(label + ' violates string length bounds')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise Invalid(label + ' does not match pattern ' + schema['pattern'])
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', float('inf')):
            raise Invalid(label + ' violates array length bounds')
        if schema.get('uniqueItems') and any(_equal(item, old) for i, item in enumerate(value) for old in value[:i]):
            raise Invalid(label + ' requires unique items')
        for i, item in enumerate(value):
            contract(item, schema.get('items', True), '%s[%s]' % (label, i))
    if isinstance(value, dict):
        if len(value) < schema.get('minProperties', 0) or len(value) > schema.get('maxProperties', float('inf')):
            raise Invalid(label + ' violates property count bounds')
        for field in schema.get('required', []):
            if field not in value:
                raise Invalid(label + ' missing ' + field)
        for field, required in schema.get('dependentRequired', {}).items():
            if field in value:
                for other in required:
                    if other not in value:raise Invalid(label + '.' + field + ' requires ' + other)
        for field, item in value.items():
            child = schema.get('properties', {}).get(field, schema.get('additionalProperties', True))
            if child is False:raise Invalid(label + ' has undeclared field ' + field)
            contract(item, child, label + '.' + field)


def check_schema(schema):
    """Reject unsupported constraints instead of silently ignoring author intent."""
    import re
    if type(schema) is bool:
        return
    if not isinstance(schema, dict):
        raise Invalid('Schema must be an object or boolean')
    unknown = set(schema) - SCHEMA_KEYWORDS
    if unknown:
        raise Invalid('Unsupported schema keyword: ' + ', '.join(sorted(unknown)))
    if 'type' in schema:
        kinds = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not kinds or any(not isinstance(k, str) or k not in SCHEMA_TYPES for k in kinds) or len(set(kinds)) != len(kinds):
            raise Invalid('Schema type must name supported, unique JSON types')
    for key in ('oneOf', 'anyOf', 'allOf'):
        if key in schema:
            if not isinstance(schema[key], list) or not schema[key]:raise Invalid(key + ' must be a nonempty array of schemas')
            for child in schema[key]:check_schema(child)
    for key in ('if', 'then', 'else', 'not', 'items', 'additionalProperties'):
        if key in schema:check_schema(schema[key])
    if ('then' in schema or 'else' in schema) and 'if' not in schema:
        raise Invalid('then/else requires if')
    if 'properties' in schema:
        if not isinstance(schema['properties'], dict):raise Invalid('properties must be an object')
        for child in schema['properties'].values():check_schema(child)
    required_lists = [schema['required']] if 'required' in schema else []
    if 'dependentRequired' in schema:
        if not isinstance(schema['dependentRequired'], dict):raise Invalid('dependentRequired must be an object')
        required_lists += list(schema['dependentRequired'].values())
    for names in required_lists:
        if not isinstance(names, list) or any(not isinstance(k, str) for k in names) or len(set(names)) != len(names):
            raise Invalid('Required fields must be a unique array of names')
    if 'enum' in schema and (not isinstance(schema['enum'], list) or not schema['enum']):
        raise Invalid('enum must be a nonempty array')
    for key in ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'):
        if key in schema and (type(schema[key]) not in (int, float) or not math.isfinite(schema[key])):
            raise Invalid(key + ' must be finite numeric bound')
    for key in ('minItems', 'maxItems', 'minLength', 'maxLength', 'minProperties', 'maxProperties'):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            raise Invalid(key + ' must be a nonnegative integer')
    for key in ('nonempty', 'uniqueItems'):
        if key in schema and type(schema[key]) is not bool:raise Invalid(key + ' must be boolean')
    if 'pattern' in schema:
        try:
            if not isinstance(schema['pattern'], str):raise TypeError()
            re.compile(schema['pattern'])
        except (TypeError, re.error):raise Invalid('pattern must be a valid regular expression') from None
    for key in ('title', 'description', 'format'):
        if key in schema and not isinstance(schema[key], str):raise Invalid(key + ' must be text')
    if 'default' in schema:
        contract(schema['default'], schema, 'Schema default')


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
