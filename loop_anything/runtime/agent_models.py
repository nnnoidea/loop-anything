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


def model_arguments(command):
    """Separate model options from the rest of the Codex argv, up to --."""
    args = [command[0]]
    boundary = command.index('--') if '--' in command else len(command)
    source = iter(command[1:boundary])
    model = config_model = None
    for operand in source:
        if operand in ('--model', '-m'):
            model = next(source, None)
        elif operand.startswith('--model='):
            model = operand[len('--model='):]
        elif operand.startswith('-m'):
            model = operand[2:].lstrip('=')
        elif operand in ('--config', '-c') or operand.startswith(('--config=', '-c')):
            separate = operand in ('--config', '-c')
            value = next(source, None) if separate else operand.removeprefix('--config=').removeprefix('-c').lstrip('=')
            key, sep, setting = (value or '').partition('=')
            if sep and key.strip() == 'model':
                config_model = setting.strip().strip("'\"")
            else:
                args.append(operand)
                if separate and value is not None:
                    args.append(value)
        else:
            args.append(operand)
    return model or config_model, args, command[boundary:]


def effective_model(config, ident, settings, fallback):
    return (settings.get('nodes', {}).get(ident) or settings.get('default')
            or model_arguments(config['command'])[0] or fallback)


def describe(document, settings, fallback=DEFAULT_MODEL):
    return {'default': settings.get('default'), 'fallback': fallback, 'nodes': {
        ident: {'label': label, 'override': settings.get('nodes', {}).get(ident),
                'candidates': {key: mode(config) for key, config in agents.items()},
                'models': {key: effective_model(config, ident, settings, fallback) for key, config in agents.items()
                           if mode(config) == 'managed'}}
        for ident, label, agents in targets(document)
    }}


def annotate(document, settings, fallback):
    for ident, _, agents in targets(document):
        for config in agents.values():
            if mode(config) == 'managed':
                config['agent_model'] = effective_model(config, ident, settings, fallback)


def launch_command(command, model):
    """Keep an explicit matching model and all arguments after the separator."""
    if not model or not codex_command(command):
        return command
    declared, args, tail = model_arguments(command)
    if declared == model:
        return command
    position = 1
    for index, operand in enumerate(args[1:], 1):
        if operand in ('exec', 'e', 'resume'):
            position = index + 1
            if operand in ('exec', 'e') and 'resume' in args[position:] and '{{session_id}}' in args:
                position = args.index('resume', position) + 1
            break
    return args[:position] + ['--model', model] + args[position:] + tail
