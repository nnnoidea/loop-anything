"""Only simulated handler replies. No Engine/Store import, DB access or dispatch.

Replace these command implementations to integrate real platforms / Agent services.
"""
import json
import re
import sys
import time
from pathlib import Path

# Standalone implementations may use the platform's public, pure Timeline builder.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from loop_anything.runtime.timeline_plan import build_plan


def result(domain, action, request):
    inputs = request['inputs']
    settings = request['timeline']['settings']
    if domain == 'research':
        if action == 'initialize':
            return {'settings': {'objective': '比较方法并基于组内指标迭代实验', 'constraints': '组间独立推进，最多4次实验；使用 GA 结果设计 GC'},
                    'outputs': {'plan': {'experiments': [{'id': 'A1', 'duration': .3}, {'id': 'A2', 'duration': .5}, {'id': 'B1', 'duration': request['timeline']['inputs'].get('slow_duration', 3)}],
                                         'groups': [{'id': 'GA', 'metrics': ['metric.A1', 'metric.A2']}, {'id': 'GB', 'metrics': ['metric.B1']}],
                                         'done': False, 'reasoning': '模拟初始化 Agent；并未调用模型解析自然语言。'}}}
        if action == 'data':
            id = inputs['experiment']['id']
            return {'outputs': {'dataset': {'experiment': id, 'uri': 'simulated://dataset/' + id}}}
        if action == 'train':
            task = request.get('external_id')
            if not task:
                task = json.dumps({'id': inputs['experiment']['id'], 'ready_at': time.time() + inputs['experiment']['duration']})
            data = json.loads(task)
            if time.time() < data['ready_at']:
                return {'event': 'progress' if request.get('external_id') else 'submitted', 'external_id': task, 'poll_after': .1}
            return {'event': 'completed', 'envelope': {'outputs': {'model': {'experiment': data['id'], 'uri': 'simulated://model/' + data['id']}}}}
        if action == 'predict':
            id = inputs['model']['experiment']
            return {'outputs': {'prediction': {'experiment': id, 'uri': 'simulated://prediction/' + id}}}
        if action == 'score':
            id = inputs['prediction']['experiment']
            return {'outputs': {'metric': {'experiment': id, 'score': {'A1': .7, 'A2': .8, 'B1': .75, 'C1': .85}[id]}}}
        if action == 'reason':
            group = inputs['group']
            return {'outputs': {'plan': {'experiments': [{'id': 'C1', 'duration': .3}] if group == 'GA' else [],
                'groups': [{'id': 'GC', 'metrics': ['metric.C1']}] if group == 'GA' else [],
                'done': group == 'GC', 'reasoning': '模拟判断 ' + group + ': ' + json.dumps(inputs['metrics'])}}}
    if domain == 'trip':
        if action in ('initialize', 'replan'):
            id = 'proposal-' + request['task_id']
            budget=re.search(r'预算[：:]?(\d+)',settings['constraints'])
            result = {'outputs': {'proposal': {'id': id, 'destination': ('北京' if '北京' in settings['constraints'] else '上海'),
                       'amount': min(int(budget.group(1)) if budget else 3000,2500),
                       'reason': inputs.get('reason', '模拟初始化；并未调用模型解析自然语言')}}}
            if action == 'initialize':
                result['settings'] = {'objective': '完成出差并处理行程异常', 'constraints': '预订必须确认，预算3000，目的地上海'}
            return result
        if action == 'book':
            p = inputs['proposal']
            return {'outputs': {'booking': {'id': 'simulated-' + p['id'], 'proposal_id': p['id'], 'destination': p['destination']}}}
        if action == 'continue':
            observation = inputs['observation']
            return {'outputs': {'watch': {'booking_record': observation['booking_record'], 'sequence': observation['sequence'] + 1}}}
        if action == 'route':
            return {'outputs': {'watch': {'booking_record': '', 'sequence': 0}}}
    if action == 'finish':
        return {'outputs': {'completion': {'summary': '模拟 Task 已完成；状态派发与写回由真实平台执行。'}}}
    raise ValueError('Unsupported simulated action')


def respond(domain, action, request):
    reply = result(domain, action, request)
    if action == 'initialize':
        reply['settings']['completion_rule'] = {'op': 'and', 'args': [{'op': 'ge', 'args': [{'path': ['completed', 'finish']}, 1]}, {'op': 'eq', 'args': [{'path': 'active_tasks'}, 0]}]}
    if domain == 'research' and action == 'train':
        return reply
    run = request['timeline']
    current = run['tasks'][request['task_id']]['spec']
    execution = {'sources': request['input_sources']} if 'input_sources' in request else next(e for e in run['executions'] if e['id'] == request['execution_id'])
    def arrange(name, values, suffix=''):
        reply.setdefault('tasks', []).extend(build_plan(run['loop_definition'], name,
            request['task_id'] + ':' + suffix, values, round_name=('第1轮' if action == 'initialize' else '追加轮' if name != 'finish' else '收尾') if domain == 'research' else None))
    if domain == 'research' and action in ('initialize', 'reason'):
        plan = reply['outputs']['plan']
        for group in plan['groups']:
            ids = {rid.removeprefix('metric.') for rid in group['metrics']}
            arrange('experiments', {'experiments': [x for x in plan['experiments'] if x['id'] in ids], 'group': group['id']}, group['id'])
            group['metrics'] = next(w['inputs']['metrics']['records'] for w in reply['tasks']
                if w['node'] == 'reason' and w['inputs']['group']['literal'] == group['id'])
        if plan['done']:
            arrange('finish', {'plan_record': current['outputs']['plan']['id']})
    if domain == 'trip':
        if action in ('initialize', 'replan'):
            arrange('confirm', {'proposal_record': current['outputs']['proposal']['id']})
        elif action == 'route':
            if request['inputs']['decision']['approved']:
                arrange('booking', {'proposal_record': execution['sources']['proposal']['record'],
                                    'decision_record': execution['sources']['decision']['record']})
            else:
                arrange('replan', {'reason': 'User rejected proposal'})
        elif action == 'book':
            arrange('watch', {'booking_record': current['outputs']['booking']['id'], 'sequence': 0})
        elif action == 'continue':
            observation = request['inputs']['observation']
            if observation['status'] == 'unchanged':
                arrange('watch', {'booking_record': observation['booking_record'], 'sequence': observation['sequence'] + 1})
            elif observation['status'] in ('cancelled', 'unknown'):
                arrange('replan', {'reason': observation['status']})
            elif observation['status'] == 'arrived':
                arrange('finish', {'observation_record': execution['sources']['observation']['record']})
    return reply


if __name__ == '__main__':
    incoming = sys.stdin.read()
    # The simulated Agent reads the identifying context from the task prompt.
    request = json.loads(incoming.split("\nRun context:\n", 1)[-1])
    if 'Run context:\n' in incoming:
        import copy
        from urllib.request import Request, urlopen
        def api(route, body=None):
            req = Request(request['platform_url'] + '/api/' + route,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json', 'X-Loop-Anything': 'workspace'})
            with urlopen(req, timeout=10) as response:
                return json.load(response)
        def call(tool, arguments):
            result = api('runs/' + request['run_id'] + '/agent',
                         {'token': request['token'], 'tool': tool, 'arguments': arguments})
            if not result['ok']:
                raise ValueError(result['error'])
            return result
        request['timeline'] = api('runs/' + request['run_id'])
        while True:
            pending = call('next_tasks', {})['items']
            if not pending:
                break
            for task in pending:
                if task['kind'] != 'task':
                    call('defer_task', {'task_id': task['id'], 'reason': '模拟 Agent 不解释未知业务问题，需要用户确认'})
                    continue
                info = call('read_task', {'task_id': task['task_id']})
                scoped = copy.deepcopy(request)
                scoped.update(task_id=task['task_id'], inputs=info['inputs'], input_sources=info['sources'], parameters=info['task']['spec'].get('parameters', {}))
                scoped['timeline']['settings'] = call('read_timeline', {})['settings']
                scoped['timeline']['tasks'][task['task_id']] = info['task']
                envelope = respond(sys.argv[1], info['task']['spec']['node'], scoped)
                call('report_task', {'event':'completed','report_id':'result:'+task['task_id'],'task_id': task['task_id'], 'envelope': envelope})
        call('finish', {})
        print(json.dumps({'submitted': True}))
    else:
        reply = respond(sys.argv[1], sys.argv[2], request)
        report = reply if (sys.argv[1], sys.argv[2]) == ('research', 'train') else {'event': 'completed', 'envelope': reply}
        print(json.dumps(report, ensure_ascii=False))
