"""Loop model preferences for Agent commands launched by the platform."""
from pathlib import PureWindowsPath
import re

from loop_anything.runtime.implementations import options
from loop_anything.runtime.model import Invalid


DEFAULT_MODEL = 'gpt-6.1-sol'
MODEL_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,99}')


def codex_command(command):
    return bool(command and PureWindowsPath(command[0]).name.lower().removesuffix('.exe') == 'codex')


def mode(config):
    if config.get('dispatch'):
        return 'delegated'
    command = config.get('command')
    if not command:
        return 'manual'
    if codex_command(command) and config.get('agent_cli', 'codex') == 'codex':
        return 'managed'
    return 'executor'


def targets(document):
    from loop_anything.runtime.flow_agent import NODE
    definition = document['loop_definition']
    candidates = document.get('implementations', {})
    for ident, node in definition['nodes'].items():
        agents = {key: config for key, config in options(candidates.get(ident)).items()
                  if config.get('kind') == 'agent'}
        if agents:
            yield ident, node.get('label') or ident, agents
    if definition.get('flow_agent'):
        yield NODE, '流程决策', {'default': definition['flow_agent']}


def validate(document, settings):
    if not isinstance(settings, dict) or set(settings) - {'default', 'nodes'}:
        raise Invalid('agent_models 只接受 default 和 nodes')
    overrides = settings.get('nodes', {})
    if not isinstance(overrides, dict):
        raise Invalid('agent_models.nodes 必须按节点 ID 配置')
    allowed = {ident for ident, _, _ in targets(document)}
    if set(overrides) - allowed:
        raise Invalid('只能为有 Agent 实现的节点配置模型')
    for model in ([settings['default']] if 'default' in settings else []) + list(overrides.values()):
        if not isinstance(model, str) or not MODEL_NAME.fullmatch(model):
            raise Invalid('模型名须以字母或数字开头，最长 100 个字符')


def describe(document, settings, fallback=DEFAULT_MODEL):
    default = settings.get('default', fallback)
    overrides = settings.get('nodes', {})
    return {'default': default, 'nodes': {
        ident: {'label': label, 'override': overrides.get(ident),
                'candidates': {key: mode(config) for key, config in agents.items()}}
        for ident, label, agents in targets(document)
    }}


def annotate(document, settings, fallback):
    default = settings.get('default', fallback)
    overrides = settings.get('nodes', {})
    for ident, _, agents in targets(document):
        for config in agents.values():
            if mode(config) == 'managed':
                config['agent_model'] = overrides.get(ident, default)


def launch_command(command, model):
    """Override Codex's model flag while keeping its other arguments and prompt."""
    if not model or not codex_command(command):
        return command
    args = [command[0]]
    boundary = command.index('--') if '--' in command else len(command)
    source = iter(command[1:boundary])
    for operand in source:
        if operand in ('--model', '-m'):
            next(source, None)
        elif operand in ('--config', '-c'):
            value = next(source, None)
            if value is None or value.partition('=')[0].strip() != 'model':
                args.append(operand)
                if value is not None:
                    args.append(value)
        elif not operand.startswith(('--model=', '-m', '--config=model=', '-cmodel=')):
            args.append(operand)
    position = 1
    for index, operand in enumerate(args[1:], 1):
        if operand in ('exec', 'e', 'resume'):
            position = index + 1
            if operand in ('exec', 'e') and 'resume' in args[position:] and '{{session_id}}' in args:
                position = args.index('resume', position) + 1
            break
    return args[:position] + ['--model', model] + args[position:] + command[boundary:]
