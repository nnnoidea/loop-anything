"""Two user-authored loop packages. No runtime imports or private state mutations.

Definitions and execution implementations are separate. Export JSON with:
  python3 -m loop_anything.examples.loops research loop_definition
  python3 -m loop_anything.examples.loops research implementations
"""
import json
import sys
from pathlib import Path


def obj(**properties):
    return {'type': 'object', 'required': list(properties), 'properties': properties}


TEXT, BOOL, NUMBER = {'type': 'string'}, {'type': 'boolean'}, {'type': 'number'}
OBJECT = {'type': 'object'}


def array(items):
    return {'type': 'array', 'items': items}


def node(label, inputs, outputs, instructions, **extra):
    return dict(label=label, inputs=inputs, outputs={p: {'record_type': t} for p, t in outputs.items()},
                instructions=instructions, **extra)


def tasks(id, node_id, inputs, outputs, **extra):
    return dict(id=id, node=node_id, inputs=inputs, outputs={p: {'id': rid} for p, rid in outputs.items()}, **extra)


def ref(id, **extra):
    return dict(record=id, **extra)


def value(path):
    return {'$': path}


def equals(left, right):
    return {'message': left + ' must equal ' + right,
            'test': {'op': 'eq', 'args': [{'path': left}, {'path': right}]}}


def research():
    records = {
        'plan': obj(experiments=array(obj(id=TEXT, duration=NUMBER)),
                    groups=array(obj(id=TEXT, metrics=array(TEXT))), done=BOOL, reasoning=TEXT),
        'dataset': obj(experiment=TEXT, uri=TEXT),
        'model': obj(experiment=TEXT, uri=TEXT),
        'prediction': obj(experiment=TEXT, uri=TEXT),
        'metric': obj(experiment=TEXT, score=NUMBER), 'completion': obj(summary=TEXT)}
    nodes = {
        'initialize': node('理解研究目标', {'request': TEXT}, {'plan': 'plan'},
            '按手册将用户要求写入 settings.objective/requirements/constraints，并提交首批实验与对比组。', initialize_timeline=True),
        'data': node('准备数据', {'experiment': OBJECT}, {'dataset': 'dataset'}, '为本实验准备数据；提交 dataset URI。'),
        'train': node('异步训练', {'dataset': records['dataset'], 'experiment': OBJECT}, {'model': 'model'},
            '启动外部训练，返回任务 ID；观察到成功后提交 model，等待期间无需 Agent。'),
        'predict': node('批量预测', {'model': records['model']}, {'prediction': 'prediction'}, '使用模型执行预测并提交产物 URI。'),
        'score': node('计算指标', {'prediction': records['prediction']}, {'metric': 'metric'}, '计算本实验指标，提交带实验身份的记录。'),
        'reason': node('组内研究决策', {'metrics': array(records['metric']), 'group': TEXT}, {'plan': 'plan'},
            '只分析当前组已全部提交的指标。可在计划中添加独立实验/组；禁止等待其他组。明确写 done 与 reasoning。'),
        'finish': node('完成研究', {'plan': records['plan']}, {'completion': 'completion'},
            '提交研究总结。此任务只保存结果，Engine 按 Timeline 中的终态规则结束 Run。')}
    nodes['initialize']['plan_nodes'] = nodes['reason']['plan_nodes'] = ['data', 'train', 'predict', 'score', 'reason', 'finish']
    plans = {
        'experiments': {'parameters': obj(experiments=array(OBJECT), group=TEXT), 'steps': {
            'data': {'node': 'data', 'each': 'experiments', 'inputs': {'experiment': {'literal': value('item')}}},
            'train': {'node': 'train', 'each': 'experiments', 'inputs': {
                'dataset': {'from': 'data', 'port': 'dataset'}, 'experiment': {'literal': value('item')}}},
            'predict': {'node': 'predict', 'each': 'experiments', 'inputs': {'model': {'from': 'train', 'port': 'model'}}},
            'score': {'node': 'score', 'each': 'experiments', 'inputs': {'prediction': {'from': 'predict', 'port': 'prediction'}}},
            'reason': {'node': 'reason', 'inputs': {'metrics': {'from': 'score', 'port': 'metric', 'collect': True},
                                                  'group': {'literal': value('values.group')}}}}},
        'finish': {'parameters': obj(plan_record=TEXT), 'steps': {
            'finish': {'node': 'finish', 'inputs': {'plan': {'record': value('values.plan_record')}}}}}}
    bp = dict(schema_version=2, id='research-platform', version='7', name='Auto Research · 平台版',
              description='共享记录驱动；GA 就绪即分析并追加 GC，不等待仍在训练的 GB。Task/Agent 返回为模拟。',
              entry='initialize', defaults={'request': '比较 A/B 方法，基于 GA 指标提出下一组实验；预算最多 4 个实验。'},
              handbook={'name': '研究 Loop · 业务说明', 'instructions':
                '与用户确定研究目标、证据需求、预算和已有资料。此示例仅模拟研究判断和实验结果，不执行真实训练。'
                '每个实验分别准备数据、训练、预测和评分，dataset/model/prediction/metric 按实验身份隔离。'
                '每组只等待自己引用的指标，GA 就绪后可提出 GC，不等待仍在训练的 GB；各组记录自己的推理与下一批实验。'
                '用户决定哪些既有结果可复用以及何时完成研究；最终保存研究总结。'},
              records=records, nodes=nodes, seed=tasks('initialize', 'initialize', {'request': {'run': 'request'}}, {'plan': 'plan.initial'}),
              plans=plans)
    return bp, implementations('research', nodes, external={'train'}, agents={'initialize', 'reason'})


def trip():
    proposal = obj(id=TEXT, destination=TEXT, amount=NUMBER, reason=TEXT)
    decision = obj(approved=BOOL, proposal_id=TEXT, proposal_record=TEXT)
    booking = obj(id=TEXT, proposal_id=TEXT, destination=TEXT)
    observation = obj(status={'type': 'string', 'enum': ['unchanged', 'cancelled', 'arrived', 'unknown']}, detail=TEXT, booking_record=TEXT, sequence=NUMBER)
    records = dict(proposal=proposal, decision=decision, booking=booking, observation=observation,
                   watch=obj(booking_record=TEXT, sequence=NUMBER), completion=obj(summary=TEXT))
    nodes = {
        'initialize': node('理解差旅要求', {'request': TEXT}, {'proposal': 'proposal'},
            '将用户语义写入通用控制字段，再提交有唯一身份的方案。未经确认不得预订。', initialize_timeline=True),
        'replan': node('重新规划', {'request': TEXT, 'settings': OBJECT, 'reason': TEXT}, {'proposal': 'proposal'},
            '读取最新用户要求及共享历史，提交新的方案身份，不复用旧确认。'),
        'approve': node('确认当前方案', {'proposal': proposal}, {'decision': 'decision'},
            '确认结果必须引用当前 proposal.id 与参数中的 proposal_record；不能替换方案。',
            assertions=[equals('outputs.decision.proposal_id', 'inputs.proposal.id'),
                        equals('outputs.decision.proposal_record', 'parameters.proposal_record')]),
        'book': node('执行预订', {'proposal': proposal, 'decision': decision}, {'booking': 'booking'},
            '仅在对应方案获批后预订；返回预订身份。生产接入必须使用幂等键。',
            assertions=[equals('outputs.booking.proposal_id', 'inputs.proposal.id')]),
        'monitor': node('等待行程事件', {'booking': booking}, {'observation': 'observation'},
            '等待准确 booking_record 对应事件；不需要 Agent 在线。事件包含递增 sequence。',
            assertions=[equals('outputs.observation.booking_record', 'parameters.event_key'),
                        equals('outputs.observation.sequence', 'parameters.sequence')]),
        'continue': node('继续观察', {'observation': observation}, {'watch': 'watch'}, '无变化事件只递增观察序号，提交下一次等待参数；不唤醒 Agent。'),
        'finish': node('行程完成', {'observation': observation}, {'completion': 'completion'}, '记录行程完成。')}
    nodes['route'] = node('处理确认结果', {'proposal': proposal, 'decision': decision}, {'watch': 'watch'},
        '按 approved 布尔值调用平台构建工具安排预订或重新规划；不做语义判断。',
        plan_nodes=['book', 'replan'])
    nodes['initialize']['plan_nodes'] = nodes['replan']['plan_nodes'] = ['approve', 'route']
    nodes['book']['plan_nodes'] = ['monitor', 'continue']
    nodes['continue']['plan_nodes'] = ['monitor', 'continue', 'replan', 'finish']
    plans = {
        'confirm': {'parameters': obj(proposal_record=TEXT), 'steps': {
            'approve': {'node': 'approve',
                'inputs': {'proposal': ref(value('values.proposal_record'))},
                'parameters': {'proposal_record': value('values.proposal_record')}},
            'route': {'node': 'route',
                'inputs': {'proposal': ref(value('values.proposal_record')), 'decision': {'from': 'approve', 'port': 'decision'}},
                'parameters': {'proposal_record': value('values.proposal_record')}}}},
        'booking': {'parameters': obj(proposal_record=TEXT, decision_record=TEXT), 'steps': {
            'book': {'node': 'book', 'inputs': {
                'proposal': ref(value('values.proposal_record')), 'decision': ref(value('values.decision_record'))}}}},
        'watch': {'parameters': obj(booking_record=TEXT, sequence=NUMBER), 'steps': {
            'monitor': {'node': 'monitor', 'inputs': {'booking': ref(value('values.booking_record'))},
                'parameters': {'event_key': value('values.booking_record'), 'sequence': value('values.sequence')}},
            'continue': {'node': 'continue', 'inputs': {'observation': {'from': 'monitor', 'port': 'observation'}}}}},
        'replan': {'parameters': obj(reason=TEXT), 'steps': {
            'replan': {'node': 'replan', 'inputs': {
                'request': {'run': 'request'}, 'settings': {'settings': ''}, 'reason': {'literal': value('values.reason')}}}}},
        'finish': {'parameters': obj(observation_record=TEXT), 'steps': {
            'finish': {'node': 'finish', 'inputs': {'observation': ref(value('values.observation_record'))}}}}}
    bp = dict(schema_version=2, id='trip-platform', version='7', name='差旅助手 · 平台版',
              description='版本化方案、人工确认、预订前临时暂停、关联事件与重新规划。不会真实预订。',
              entry='initialize', defaults={'request': '下周去上海出差，预算 3000 元；预订必须经我确认。'},
              handbook={'name': '差旅 Loop · 业务说明', 'instructions':
                '与用户确定目的地、日期、预算、偏好和哪些操作需要确认。示例只模拟方案与预订，不连接航司或支付。'
                '方案有独立身份；允许规划不等于批准预订，确认必须匹配当前方案身份。'
                '用户要求变化时，由用户决定是否取消旧确认与后续预订，已有事实保留。'
                '行程事件按预订记录和序号匹配：unchanged 继续观察，cancelled/unknown 重新规划并再次确认，arrived 保存完成记录。'},
              records=records, nodes=nodes, seed=tasks('initialize', 'initialize', {'request': {'run': 'request'}}, {'proposal': 'proposal.initial'}), plans=plans)
    return bp, implementations('trip', nodes, agents={'initialize', 'replan'}, approval={'approve'}, events={'monitor': 'trip-status'})


def implementations(domain, nodes, external=(), agents=(), approval=(), events=None):
    script = str(Path(__file__).with_name('simulated_tasks.py').resolve())
    result = {}
    for name in nodes:
        cmd = [sys.executable, script, domain, name]
        if name in (events or {}):
            result[name] = {'kind': 'event', 'event': events[name]}
        elif name in approval:
            result[name] = {'kind': 'approval'}
        elif name in external:
            result[name] = {'kind': 'external', 'command': cmd, 'observe': cmd + ['observe'], 'simulation': True}
        else:
            result[name] = {'kind': 'agent' if name in agents else 'command', 'command': cmd, 'simulation': True}
    return result


if __name__ == '__main__':
    bp, bound = {'research': research, 'trip': trip}[sys.argv[1]]()
    print(json.dumps(bp if sys.argv[2] == 'loop_definition' else bound, ensure_ascii=False, indent=2))
