"""Read-only Feishu preflight for cc-connect. No credentials leave this process."""
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen


def config_options(config_path, project, platform):
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            raise ValueError('Feishu conversation capture needs Python 3.11+ or tomli; run call.py with that interpreter')
    config = tomllib.loads(Path(config_path).read_text(encoding='utf-8'))
    projects = [p for p in config.get('projects', []) if p.get('name') == project]
    if len(projects) != 1:
        raise ValueError('The cc-connect project is missing or ambiguous in the configured file')
    platforms = [p for p in projects[0].get('platforms', []) if p.get('type') == platform]
    if len(platforms) != 1:
        raise ValueError('Expected exactly one matching Feishu/Lark platform for this project')
    options = dict(platforms[0].get('options', {}))
    for key,value in options.items():
        if isinstance(value,str):options[key]=re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}',lambda m:os.environ.get(m[1],m[0]),value)
    if not all(isinstance(options.get(k), str) and options[k] and '${' not in options[k] for k in ('app_id', 'app_secret')):
        raise ValueError('The local cc-connect app credentials are unavailable')
    return options


def api(base, path, token=None, data=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(base + path, headers=headers,
                      data=json.dumps(data).encode() if data is not None else None)
    try:
        with urlopen(request, timeout=4) as response:
            result = json.load(response)
    except Exception:
        raise ValueError('Feishu preflight could not reach the read-only API') from None
    if result.get('code') != 0:
        raise ValueError('Feishu preflight rejected (code %s); check Bot permissions and membership' % result.get('code'))
    return result


def bridge_ready(directory, project, config_path):
    path = Path(directory) / 'run/api.sock'
    if Path(config_path).stat().st_mtime > path.stat().st_mtime:
        raise ValueError('cc-connect configuration changed after startup; reload/restart and verify before replying to a topic')
    class UnixConnection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(str(path))
    conn = UnixConnection('localhost', timeout=4)
    try:
        conn.request('GET', '/sessions')
        response = conn.getresponse()
        sessions = json.load(response)
        if response.status != 200 or sessions is not None and not isinstance(sessions, list):
            raise ValueError('cc-connect local API unavailable')
        # /sessions contains only active chats; absence does not mean an unloaded project.
        # The explicit --project send rejects unknown projects without selecting another.
    finally:
        conn.close()


def inspect(project, session, directory, config_path, expected=None):
    parts = session.split(':')
    if len(parts) not in (2, 3, 4) or parts[0] not in ('feishu', 'lark') or not re.fullmatch(r'oc_[A-Za-z0-9_-]+', parts[1]):
        raise ValueError('Unsupported cc-connect Feishu session key; use the full original key')
    root = parts[3] if len(parts) == 4 and parts[2] in ('root', 'thread') else None
    if len(parts) == 4 and (not root or not re.fullmatch(r'om_[A-Za-z0-9_-]+', root)):
        raise ValueError('Invalid original thread root')
    options = config_options(config_path, project, parts[0])
    bridge_ready(directory, project, config_path)
    base = 'https://open.larksuite.com' if parts[0] == 'lark' else 'https://open.feishu.cn'
    token = api(base, '/open-apis/auth/v3/tenant_access_token/internal', data={k:options[k] for k in ('app_id','app_secret')})['tenant_access_token']
    chat = api(base, '/open-apis/im/v1/chats/' + quote(parts[1], safe=''), token)['data']
    mode = chat.get('chat_mode')
    if mode not in ('p2p', 'group', 'topic'):
        raise ValueError('Cannot determine whether this is a private chat or group')
    context = {'platform':parts[0], 'chat_id':parts[1], 'chat_type':'p2p' if mode == 'p2p' else 'group',
               'session_key':session, 'thread_root':root, 'entry_project':project}
    if expected:
        if any(context[k] != expected.get(k) for k in ('platform','chat_id','session_key','thread_root')):
            raise ValueError('The destination no longer matches the original conversation')
        if expected.get('chat_type') not in (None,'unknown',context['chat_type']):
            raise ValueError('The destination no longer matches the original chat type')
        if context['chat_type'] == 'p2p' and project != expected['entry_project']:
            raise ValueError('Only the entry Bot may reply to this private chat')
    if (mode == 'topic' or chat.get('group_message_type') == 'thread') and not root:
        raise ValueError('Topic chat lacks its original root ID; enable cc-connect thread_isolation and start from that topic')
    if context['chat_type'] == 'group':
        member = api(base, '/open-apis/im/v1/chats/' + quote(parts[1], safe='') + '/members/is_in_chat', token)['data']
        if member.get('is_in_chat') is not True:
            raise ValueError('This Bot is not in the original group')
        # Restricted posting cannot be proven with chat metadata alone. Use the entry Bot.
        if expected and project != expected['entry_project'] and chat.get('moderation_permission') != 'all_members':
            raise ValueError('Cannot confirm this Bot may post in the moderated group')
    if root:
        if options.get('thread_isolation') is not True or options.get('reply_to_trigger', True) is not True:
            raise ValueError('Topic replies require thread_isolation=true and reply_to_trigger=true in this Bot project')
        messages = api(base, '/open-apis/im/v1/messages/' + quote(root, safe=''), token)['data'].get('items', [])
        if not any(m.get('message_id') == root and m.get('chat_id') == parts[1] and not m.get('deleted') for m in messages):
            raise ValueError('The original thread root is inaccessible or belongs to another chat')
    return context


def capture():
    from notify_cc_connect import sender_command
    command = sender_command()
    project, session = os.environ['CC_PROJECT'], os.environ['CC_SESSION_KEY']
    directory = str(Path(os.environ.get('CC_DATA_DIR') or Path.home() / '.cc-connect').expanduser().resolve())
    config_path = str(Path(os.environ.get('CC_CONFIG_PATH') or Path.home() / '.cc-connect/config.toml').expanduser().resolve())
    context = inspect(project, session, directory, config_path)
    return {'operation':'conversation','conversation':context,
            'notification_command':command + ['--config', config_path, '--conversation']}


def toml_python():
    candidates = [sys.executable] + [shutil.which(n) for n in ('python3','python3.14','python3.13','python3.12','python3.11')]
    for exe in dict.fromkeys(x for x in candidates if x):
        check = subprocess.run([exe, '-c', 'try:\n import tomllib\nexcept ImportError:\n import tomli'], capture_output=True, timeout=5)
        if check.returncode == 0:return exe
    raise ValueError('Feishu conversation capture requires an installed Python 3.11+ or tomli')


def helper(arguments=(), expected=None):
    result = subprocess.run([toml_python(), str(Path(__file__).resolve()), *arguments],
                            input=json.dumps(expected), capture_output=True, text=True, timeout=35)
    data = json.loads(result.stdout)
    if result.returncode:raise ValueError(data.get('error','Could not capture conversation'))
    return data


def capture_arguments():
    """Use an installed TOML-capable Python; do not install or change the bridge."""
    return helper()


def inspect_compatible(project, session, directory, config_path, expected=None):
    try:
        import tomllib
    except ImportError:
        try:import tomli
        except ImportError:return helper(['--inspect',project,session,directory,config_path],expected)
    return inspect(project,session,directory,config_path,expected)


if __name__ == '__main__':
    try:
        value=inspect(*sys.argv[2:],expected=json.load(sys.stdin)) if sys.argv[1:2]==['--inspect'] else capture()
        print(json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
