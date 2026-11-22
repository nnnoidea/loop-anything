"""Project committed outputs into measurements, readable text and declared files."""

import sys

from loop_anything.runtime.timeline_runtime import result_readings


TEXT_FIELDS = {'summary': '摘要', 'assessment': '评估', 'verdict': '结论', 'next_step': '下一步'}
LOG_FIELDS = {'log', 'logs', 'stdout', 'stderr', 'traceback'}


def mapping(value):
    return value if isinstance(value, dict) else {}


def numeric(value):
    return type(value) in (int, float) and -sys.float_info.max <= value <= sys.float_info.max


def numeric_values(values, prefix=''):
    for name, value in values.items():
        if not isinstance(name, str) or not name.strip():
            continue
        label = f'{prefix}.{name}' if prefix else name
        if numeric(value):
            yield label, value
        elif isinstance(value, dict):
            yield from numeric_values(value, label)


def measurement_values(value, record_type):
    result = mapping(value)
    metrics = mapping(result.get('metrics'))
    primary = mapping(metrics.get('primary')) or mapping(result.get('primary'))
    if record_type.rsplit('.', 1)[-1] != 'metrics' and not primary and not isinstance(metrics.get('values'), dict):
        return {}
    values = dict(numeric_values(mapping(result.get('values'))))
    reported = metrics.get('values')
    if not isinstance(reported, dict):
        reported = {k: v for k, v in metrics.items() if k not in ('primary', 'values', 'comparison')}
    values.update(numeric_values(reported))
    name, primary_value = primary.get('name'), primary.get('value')
    if isinstance(name, str) and name.strip() and numeric(primary_value):
        values.pop(name, None)
        return {name: primary_value, **values}
    return values


def display_fields(value, schema, port, label, path=()):
    if schema.get('format') == 'file' and isinstance(value, str) and value.strip():
        name = value.replace('\\', '/').rsplit('/', 1)[-1]
        if name:
            yield {'label': label or name, 'file': {'port': port, 'path': list(path), 'name': name}}
    elif isinstance(value, dict):
        for key, field in schema.get('properties', {}).items():
            if key in value and key not in LOG_FIELDS:
                yield from display_fields(value[key], field, port, field.get('title') or TEXT_FIELDS.get(key), (*path, key))
    elif isinstance(value, list) and mapping(schema.get('items')).get('format') == 'file':
        for index, item in enumerate(value):
            yield from display_fields(item, schema['items'], port, label, (*path, index))
    elif label and isinstance(value, str) and value.strip():
        yield {'label': label, 'text': value.strip()}
    elif label and (numeric(value) or type(value) is bool):
        yield {'label': label, 'value': value}


def display_results(node, output_schemas, outputs):
    outputs = outputs or {}
    readings = {field['label']: field for field in result_readings(node, outputs)}
    content = []
    declared_text = {field['value'].strip() for field in readings.values() if isinstance(field['value'], str)}
    for port, output in node.get('outputs', {}).items():
        if port not in outputs or port in LOG_FIELDS:
            continue
        value = outputs[port]
        record_type = output['record_type']
        schema = output_schemas.get(record_type, {})
        measurements = measurement_values(value, record_type)
        for name, number in measurements.items():
            readings.setdefault(name, {'label': name, 'value': number, 'source': 'outputs'})
        for field in display_fields(value, schema, port, schema.get('title') or output.get('title') or port):
            if 'value' in field:
                readings.setdefault(field['label'], dict(field, source='outputs'))
            elif 'text' not in field or field['text'] not in declared_text:
                content.append(field)
    return list(readings.values()), content
