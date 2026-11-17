"""Built-in flow decisions reuse ordinary Task execution, sessions and writes.

The selected Run steward handles default progression and explicit decision routes,
without an extra business node or plan. Internal tasks keep decisions inspectable.
"""
import copy

from loop_anything.runtime.model import Invalid, digest

NODE = '$flow_agent'
RECORD = '$flow_agent.decision'


def materialize(run, implementation):
    """Derive an internal execution template in the Run snapshot only."""
    run['loop_definition'] = copy.deepcopy(run['loop_definition'])
    run['implementations'] = copy.deepcopy(run['implementations'])
    bp = run['loop_definition']
    bp['records'][RECORD] = {}
    bp['nodes'][NODE] = {
        'builtin': 'flow_agent', 'label': '流程决策',
        'instructions': '完整读取 Loop handbook，依据触发事件及相关记录决定下一步。'
                        '先读取当前任务安排和来源事件的 routes 回执，复用已有安排；'
                        '用既有任务工具安排或调整工作，将决定、业务理由及证据引用完整提交到 decision。'
                        '完成后 finish。等待交给平台，不能用持续轮询代替等待。',
        'inputs': {'trigger': {'type': 'object'}},
        'outputs': {'decision': {'record_type': RECORD}},
    }
    run['implementations'][NODE] = {'options': {'default': implementation}, 'default': 'default'}


def prepare(run, execution, report, route, context):
    if NODE not in run['loop_definition']['nodes']:
        raise Invalid('This route needs a Run steward')
    ident = 'flow-' + digest([execution['id'], report['report_id'], route['id']])[:24]
    source = run['tasks'][execution['task_id']]
    records = {name: {'record': destination['id'], 'revision': destination.get('expected_revision', 0) + 1}
               for name, destination in source['spec']['outputs'].items()} if report['event'] == 'completed' else {}
    trigger = {'task_id': source['id'], 'node_id': execution['node'], 'execution_id': execution['id'],
               'report_id': report['report_id'], 'route_id': route['id'], 'event': report['event'],
               'transition': copy.deepcopy(context['transition']), 'detail': copy.deepcopy(report.get('detail', {})),
               'records': records}
    spec = {'id': ident, 'node': NODE, 'inputs': {'trigger': {'literal': trigger}},
            'outputs': {'decision': {'id': ident + '.decision'}}, 'parent_id': source['id']}
    if 'round' in source['spec']:
        spec['round'] = source['spec']['round']
    origin = {'flow_agent': trigger, 'execution': execution['id'], 'route_id': route['id'], 'report_id': report['report_id']}
    if run.get('steward'):
        origin['steward'] = run['steward']['generation']
    return spec, origin


def decisions(run, task_id):
    """Small navigable references; complete results remain in ordinary records."""
    return [{'task_id': task['id'], 'status': task['status'], 'execution_id': task.get('execution_id'),
             'trigger': task['origin']['flow_agent'], 'outputs': task['spec']['outputs']}
            for task in run['tasks'].values() if task.get('origin', {}).get('flow_agent', {}).get('task_id') == task_id]


def route_receipts(run, task_id):
    return [h['detail'] for h in run['history']
            if h['kind'] == 'route_fired' and h['detail'].get('task_id') == task_id]
