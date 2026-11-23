"""Readable details for the installed research workflows, including retained attempts."""

from loop_anything.interfaces.run_results import mapping, numeric
from loop_anything.runtime.timelines import logical_node


RESEARCH_LOOPS = {'auto-research-structure', 'auto-research-value-debate'}
DETAIL_NODES = {'design_research', 'debate', 'runtime_repair', 'acquire_data',
                'prepare_dataset', 'train_model', 'run_prediction'}


def detail_kind(run, node_id):
    node = logical_node(run, node_id)
    loop = run['loop_definition']['id']
    if loop in RESEARCH_LOOPS and node in DETAIL_NODES:
        return node
    if loop == 'platform-collaboration' and node == 'collect':
        return 'collaboration_result'
    if node == '$flow_agent':
        return node
    return None


def text(value):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    return value if len(value) <= 1800 else value[:1799] + '…'


def entries(value):
    return value[:12] if isinstance(value, list) else []


def first_count(*values):
    return next((v for v in values if type(v) is int and v >= 0), None)


def train_rows(dataset):
    manifest = mapping(dataset.get('data_manifest'))
    return first_count(mapping(dataset.get('metrics')).get('train_rows'), manifest.get('train_rows'))


def merlin_runtime(db, run_id, attempt):
    if not attempt.get('external_id'):
        return None
    first, last = db.execute("""
        SELECT min(json_extract(document, '$.at')), max(json_extract(document, '$.at'))
        FROM timeline_parts WHERE run_id=? AND section='history'
          AND json_extract(document, '$.execution')=?
          AND json_extract(document, '$.kind')='transition'
          AND json_extract(document, '$.detail.accepted')=1
          AND json_extract(document, '$.detail.detail.external_status')='RUNNING'
        """, (run_id, attempt['id'])).fetchone()
    end = attempt.get('completed_at') if attempt['status'] == 'completed' else last
    if numeric(first) and numeric(end) and end > first:
        return round(end - first)
    return None


def node_details(kind, attempt, observed_seconds=None):
    outputs = mapping(attempt.get('outputs'))
    inputs = mapping(attempt.get('inputs'))
    params = mapping(attempt.get('parameters'))
    facts, sections = [], []

    def fact(label, value, unit=None, **options):
        if value is not None and value != '':
            facts.append(dict(label=label, value=value, unit=unit, **options))

    def section(label, *values, supplementary=False):
        content = list(dict.fromkeys(value for raw in values if (value := text(raw))))
        if content:
            sections.append({'label': label, 'items': content, 'supplementary': supplementary})

    if kind in ('design_research', '$flow_agent'):
        title = '研究决策' if kind == 'design_research' else '流程决策'
        decision = outputs.get('decision')
        result = mapping(decision)
        judgments = [mapping(j) for j in entries(result.get('judgments'))]
        conclusions = [text(j.get('conclusion')) for j in judgments]
        section('结论', *(conclusions if any(conclusions) else [result.get('conclusion') or result.get('summary') or decision]))
        section('下一步', *(j.get('next_step') for j in judgments), result.get('next_step'))
        section('实验方案', *(mapping(a).get('summary') for a in entries(result.get('action_requests'))))
        section('依据', *(j.get('evidence_summary') for j in judgments if text(j.get('evidence_summary')) not in conclusions),
                result.get('reason') or result.get('rationale'), supplementary=True)
    elif kind == 'debate':
        title = '审查结论'
        audit = mapping(outputs.get('audit'))
        verdict = audit.get('verdict')
        if verdict in ('accept', 'revise'):
            fact('审查决定', '通过提案' if verdict == 'accept' else '需要修改')
        section('评估', audit.get('assessment'))
        section('需修改', *entries(audit.get('requested_changes')))
        section('整体取舍', audit.get('portfolio_review'), supplementary=True)
    elif kind == 'runtime_repair':
        title = '修复结果'
        repair = mapping(outputs.get('resolution'))
        section('结论', repair.get('summary'))
        section('下一步', repair.get('next_step'))
        section('已做的调整', *entries(repair.get('actions_taken')), supplementary=True)
    elif kind == 'collaboration_result':
        title = '协作结果'
        response = mapping(outputs.get('result')).get('result')
        section('回复', mapping(response).get('confirmation') or mapping(response).get('summary') or response)
    elif kind == 'acquire_data':
        title = '数据获取'
        acquired = mapping(outputs.get('acquired_data'))
        if acquired.get('implementation') == 'existing_files' and acquired.get('raw_data_ref'):
            fact('数据来源', '复用已有数据')
        fact('获取样本', first_count(mapping(acquired.get('metrics')).get('rows')), '条')
    elif kind == 'prepare_dataset':
        title = '数据集'
        dataset = mapping(outputs.get('dataset'))
        fact('训练样本', train_rows(dataset), '条')
        metrics = mapping(dataset.get('metrics'))
        fact('沿用样本', first_count(metrics.get('retained_anchor_rows')), '条')
        fact('新增样本', first_count(metrics.get('new_rows')), '条')
        counts = mapping(metrics.get('train_target_counts'))
        composition = mapping(mapping(dataset.get('data_manifest')).get('composition'))
        for name in ('A', 'B', 'C', 'D'):
            fact(f'{name} 类样本', first_count(counts.get(name), mapping(composition.get(name)).get('rows')), '条')
    else:
        training = kind == 'train_model'
        title = '训练信息' if training else '预测信息'
        action = mapping(inputs.get('action'))
        stage = mapping(mapping(action.get('stages')).get('train' if training else 'prediction'))
        artifact = mapping(outputs.get('checkpoint' if training else 'predictions'))
        if stage.get('enabled') is False or artifact.get('status') == 'skipped':
            fact('本次操作', '复用已有模型' if training else '复用已有预测')
        elif (training and stage.get('implementation') == 'user_script'
              and len(entries(params.get('source_checkpoints'))) == 2
              and numeric(params.get('second_weight')) and 0 <= params['second_weight'] <= 1):
            title = '模型合并'
            second = params['second_weight'] * 100
            fact('两个来源模型的权重', f'{100-second:g} : {second:g}')
            start, end = attempt.get('started_at'), attempt.get('completed_at')
            if numeric(start) and numeric(end) and end > start:
                fact('合并用时', round(end - start), format='duration')
        else:
            if training:
                fact('训练样本', train_rows(mapping(inputs.get('dataset'))), '条')
                epochs = params.get('num_train_epochs')
                fact('训练轮数', epochs if numeric(epochs) and epochs > 0 else None, '轮')
            else:
                rows = first_count(mapping(artifact.get('metrics')).get('rows'))
                fact('预测样本' if rows is not None else '预计预测样本',
                     rows if rows is not None else first_count(params.get('expected_rows')), '条')
                fact('最大生成长度', first_count(params.get('max_tokens')), 'token')
            resources = mapping(mapping(stage.get('executor')).get('resources'))
            cards, instances = first_count(resources.get('gpu')), first_count(resources.get('instances'))
            if cards:
                gpu_type = text(resources.get('gpu_type'))
                model = gpu_type.replace('_', ' ') if gpu_type and all(c.isalnum() or c in '_-' for c in gpu_type) else ''
                fact('GPU 配置' if instances else '每实例 GPU 配置', cards * (instances or 1), '张' + (f' {model}' if model else ''))
            if observed_seconds is not None:
                label = '训练时长' if training else '预测时长'
                fact(f'{label}（约）' if attempt['status'] == 'completed' else f'已观测{label}（约）',
                     observed_seconds, format='duration')
                note = ('从平台首次观测到运行，到确认完成。' if attempt['status'] == 'completed'
                        else '按平台首次和最近一次观测到运行的时间计算。')
                return {'title': title, 'facts': facts, 'sections': sections, 'note': note}
    if facts or sections:
        return {'title': title, 'facts': facts, 'sections': sections}
    return None
