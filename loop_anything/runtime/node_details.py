"""Read-only presentation of the fields a Loop author declared for a node."""

import re
import sys

from loop_anything.runtime.checks import evaluate, validate_expression
from loop_anything.runtime.model import Invalid, contract, path


TEXT = {'type': 'string', 'minLength': 1}


def object_with(fields, required=()):
    return {'type': 'object', 'properties': fields, 'required': list(required), 'additionalProperties': False}


FIELD = object_with({
    'label': TEXT, 'sources': {'type': 'array', 'minItems': 1, 'maxItems': 12}, 'unit': TEXT,
    'format': {'enum': ['text', 'folded', 'duration', 'percent']},
    'labels': {'type': 'object', 'additionalProperties': TEXT}, 'when': {'type': 'object'},
}, ('label', 'sources'))
DETAILS = {'type': 'array', 'maxItems': 12, 'items': object_with({
    'title': TEXT, 'note': TEXT, 'when': {'type': 'object'},
    'fields': {'type': 'array', 'minItems': 1, 'maxItems': 24, 'items': FIELD},
    'observation': object_with({'key': TEXT, 'value': TEXT}, ('key', 'value')),
}, ('title', 'fields'))}
SOURCES = {'outputs', 'inputs', 'parameters', 'timing', 'status'}
LOOKUP_ERRORS = (TypeError, ValueError, KeyError, IndexError, ArithmeticError)


def validate(panels):
    contract(panels, DETAILS, 'Node details')
    for panel in panels:
        if 'observation' in panel and not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*', panel['observation']['key']):
            raise Invalid('Node details observation key must be a dotted report-detail path')
        expressions = [expr for field in panel['fields'] for expr in field['sources']]
        expressions.extend(field['when'] for field in panel['fields'] if 'when' in field)
        if 'when' in panel:
            expressions.append(panel['when'])
        for expr in expressions:
            validate_expression(expr)
            validate_sources(expr)


def validate_sources(expr):
    if isinstance(expr, dict):
        if 'path' in expr:
            parts = expr['path'].split('.') if isinstance(expr['path'], str) else expr['path']
            if not parts or parts[0] not in SOURCES or len(parts) > 16 or parts.count('*') > 1:
                raise Invalid('Node details must reference an allowed field of the selected execution')
        else:
            for child in expr['args']:
                validate_sources(child)


def specifications(db, run):
    loop = run['loop_definition']
    configs = {name: node['details'] for name, node in loop['nodes'].items() if node.get('details')}
    # A new display declaration can read old results of this same Loop. The
    # retained task's method and exact result versions still govern execution.
    loop_ids = {run['loop_key']: loop['id']}
    for name, retained in run.get('retained_nodes', {}).items():
        candidate = configs.get(retained['node_id'])
        if name in configs or not candidate:
            continue
        key = retained['loop_key']
        if key not in loop_ids:
            row = db.execute("SELECT json_extract(document, '$.id') FROM loop_definitions WHERE key=?", (key,)).fetchone()
            loop_ids[key] = row[0] if row else None
        if loop_ids[key] == loop['id']:
            configs[name] = candidate
    return configs


def number(value):
    return type(value) in (int, float) and -sys.float_info.max <= value <= sys.float_info.max


def elapsed(start, end):
    if number(start) and number(end) and end >= start:
        return round(end - start)
    return None


def observed_seconds(db, run_id, attempt, config):
    if not attempt.get('external_id'):
        return None
    first, last = db.execute("""
        SELECT min(json_extract(document, '$.at')), max(json_extract(document, '$.at'))
        FROM timeline_parts WHERE run_id=? AND section='history'
          AND json_extract(document, '$.execution')=?
          AND json_extract(document, '$.kind')='transition'
          AND json_extract(document, '$.detail.accepted')=1
          AND json_extract(document, ?)=?
        """, (run_id, attempt['id'], '$.detail.detail.' + config['key'], config['value'])).fetchone()
    end = attempt.get('completed_at') if attempt['status'] == 'completed' else last
    return elapsed(first, end) if first != end else None


def read_source(context, key):
    parts = key.split('.') if isinstance(key, str) else key
    try:
        if '*' not in parts:
            return path(context, parts)
        index = parts.index('*')
        values = path(context, parts[:index])
        return [read_source(item, parts[index + 1:]) for item in values[:12]] if isinstance(values, list) else []
    except LOOKUP_ERRORS:
        return None


def value_of(expr, context):
    def read(key, *, size=False):
        value = read_source(context, key)
        return len(value) if size else value

    try:
        return evaluate(expr, context, read_path=read)
    except LOOKUP_ERRORS:
        return None


def texts(value):
    for item in value[:12] if isinstance(value, list) else [value]:
        if isinstance(item, str) and (item := item.strip()):
            yield item if len(item) <= 1800 else item[:1799] + '…'


def project(db, run_id, attempt, panels):
    timing = {'elapsed_seconds': elapsed(attempt.get('started_at'), attempt.get('completed_at'))}
    context = {key: attempt.get(key) for key in ('outputs', 'inputs', 'parameters', 'status')}
    context['timing'] = timing
    for panel in panels:
        if value_of(panel.get('when', True), context) is not True:
            continue
        observation = panel.get('observation')
        timing['observed_seconds'] = observed_seconds(db, run_id, attempt, observation) if observation else None
        facts, sections = [], []
        for field in panel['fields']:
            if value_of(field.get('when', True), context) is not True:
                continue
            label, fmt = field['label'], field.get('format')
            values = (value_of(expr, context) for expr in field['sources'])
            if fmt in ('text', 'folded'):
                items = list(dict.fromkeys(item for value in values for item in texts(value)))
                if items:
                    sections.append({'label': label, 'items': items, 'supplementary': fmt == 'folded'})
                continue
            if 'labels' in field:
                values = (field['labels'].get(str(value)) for value in values)
            if fmt in ('duration', 'percent'):
                values = (value for value in values if number(value) and value >= 0)
            value = next((value for value in values if number(value) or type(value) is bool
                          or isinstance(value, str) and value.strip()), None)
            if isinstance(value, str):
                value = next(texts(value))
            if value is not None:
                facts.append({'label': label, 'value': value, 'unit': field.get('unit'), 'format': fmt})
        if facts or sections:
            note = panel.get('note') if not observation or timing['observed_seconds'] is not None else None
            return {'title': panel['title'], 'facts': facts, 'sections': sections, 'note': note}
    return None
