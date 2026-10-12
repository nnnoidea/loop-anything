"""Check notification routing facts, leaving session ID validity to cc-connect."""
import json
import copy
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import quote, urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def config_options(config_path, project, platform):
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            raise ValueError('Reading cc-connect configuration needs Python 3.11+ or tomli on the sending machine')
    config = tomllib.loads(Path(config_path).expanduser().read_text(encoding='utf-8'))
    projects = [p for p in config.get('projects', []) if p.get('name') == project]
    if len(projects) != 1:
        raise ValueError('The cc-connect project is missing or ambiguous in the configured file')
    platforms = [p for p in projects[0].get('platforms', []) if p.get('type') == platform]
    if len(platforms) != 1:
        raise ValueError('Expected exactly one matching Feishu/Lark platform for this project')
    options = dict(platforms[0].get('options', {}))
    for key,value in options.items():
        if isinstance(value,str):options[key]=re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}',lambda m:os.environ.get(m[1],m[0]),value)
    return options


def tenant_token(base, options):
    if not all(isinstance(options.get(k), str) and options[k] and '${' not in options[k] for k in ('app_id', 'app_secret')):
        raise ValueError('The local cc-connect app credentials are unavailable')
    return api(base,'/open-apis/auth/v3/tenant_access_token/internal',
               data={k:options[k] for k in ('app_id','app_secret')})['tenant_access_token']


def api(base, path, token=None, data=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(base + path, headers=headers,
                      data=json.dumps(data).encode() if data is not None else None)
    try:
        with urlopen(request, timeout=4) as response:
            result = json.load(response)
    except HTTPError as exc:
        try:result=json.load(exc)
        except (ValueError,TypeError):
            raise ValueError('Feishu metadata lookup rejected (HTTP %s)' % exc.code) from None
    except Exception:
        raise ValueError('Feishu metadata lookup could not reach the API') from None
    if result.get('code') != 0:
        scopes=sorted(set(re.findall(r'\bim:[A-Za-z0-9_.:]+',str(result.get('msg','')))))
        detail='; required scope: '+', '.join(scopes) if scopes else '; check Bot permissions and membership'
        raise ValueError('Feishu metadata lookup rejected (code %s)' % result.get('code')+detail)
    return result


def inspect(project, session, directory, config_path, expected=None):
    """Original entry is opaque passthrough; probes only decide alternate Bot use."""
    if not isinstance(session,str) or not session or not isinstance(project,str) or not project:
        raise ValueError('The original session and sending project must be explicit')
    if expected and session != expected.get('session_key'):
        raise ValueError('The destination no longer matches the original conversation')
    parts=session.split(':',3)
    context=copy.deepcopy(expected) if expected else {
        'platform':parts[0], 'chat_id':parts[1] if len(parts)>1 else '',
        'chat_type':'unknown', 'session_key':session, 'entry_project':project}
    # No parsing, config reads, API access, socket checks or TOML interpreter
    # discovery may stand between the original entry and cc-connect send.
    if project == context.get('entry_project'):
        return context
    if context.get('chat_type') == 'p2p':
        raise ValueError('Only the entry Bot may reply to this private chat')
    if context.get('platform') not in ('feishu','lark') or not context.get('chat_id'):
        raise ValueError('Cannot confirm an alternate Bot destination; use the entry Bot')
    options=config_options(config_path,project,context['platform'])
    base='https://open.larksuite.com' if context['platform']=='lark' else 'https://open.feishu.cn'
    token=tenant_token(base,options)
    chat=api(base,'/open-apis/im/v1/chats/'+quote(context['chat_id'],safe=''),token)['data']
    # Positive evidence selects an alternate; unknown channel metadata means
    # fallback, never rejection of the original session's validity.
    if chat.get('chat_type') == 'p2p' or chat.get('chat_mode') not in ('group','topic'):
        raise ValueError('Cannot confirm a group for the alternate Bot; use the entry Bot')
    member=api(base,'/open-apis/im/v1/chats/'+quote(context['chat_id'],safe='')+'/members/is_in_chat',token)['data']
    if member.get('is_in_chat') is not True or chat.get('moderation_permission') != 'all_members':
        raise ValueError('Cannot confirm the alternate Bot may post; use the entry Bot')
    context['chat_type']='group'
    return context


def prepare_delivery(project, session, config_path, expected=None):
    """Translate a known thread target to a root message; retain source identity."""
    context=copy.deepcopy(expected) if expected else inspect(project,session,'',config_path)
    if context.get('session_key') != session:
        raise ValueError('The destination no longer matches the original conversation')
    parts=session.split(':',3)
    if len(parts)!=4 or parts[0] not in ('feishu','lark') or parts[2]!='thread' or not parts[3]:
        return {'session':session,'conversation':context}
    platform,chat,_,thread=parts
    if context.get('platform',platform)!=platform or context.get('chat_id',chat) not in ('',chat) or context.get('thread_id',thread)!=thread:
        raise ValueError('Thread metadata does not match the original conversation')
    context.update(platform=platform,chat_id=chat,thread_id=thread)
    options=config_options(config_path,project,platform)
    # These options control ReplyInThread in the supported bridge, not ID validity.
    if options.get('thread_isolation') is not True or options.get('reply_to_trigger') is False:
        raise ValueError('Topic delivery requires cc-connect thread_isolation=true and reply_to_trigger=true (or omitted); apply the configuration to the running bridge')
    root=context.get('thread_root')
    # Older records incorrectly stored the thread ID in thread_root.
    if not root or root==thread:
        base='https://open.larksuite.com' if platform=='lark' else 'https://open.feishu.cn'
        token=tenant_token(base,options)
        query=urlencode({'container_id_type':'thread','container_id':thread,'page_size':20,'sort_type':'ByCreateTimeAsc'})
        items=api(base,'/open-apis/im/v1/messages?'+query,token)['data'].get('items',[])
        roots=set()
        for item in items:
            if item.get('chat_id')!=chat or item.get('thread_id')!=thread:
                raise ValueError('Thread lookup did not confirm the original chat and topic')
            candidate=item.get('root_id') or (item.get('message_id') if not item.get('parent_id') else None)
            if isinstance(candidate,str) and candidate and candidate!=thread:roots.add(candidate)
        if len(roots)!=1:
            raise ValueError('Could not resolve one root message for the original topic; supply its actual thread_root or check Bot history access')
        root=roots.pop()
    if not isinstance(root,str) or not root:
        raise ValueError('thread_root must be the actual root message ID')
    context['thread_root']=root
    return {'session':f'{platform}:{chat}:root:{root}','conversation':context}


def prepare_compatible(project, session, config_path, expected=None):
    parts=session.split(':',3)
    if len(parts)==4 and parts[0] in ('feishu','lark') and parts[2]=='thread' and parts[3]:
        try:
            import tomllib
        except ImportError:
            try:import tomli
            except ImportError:return helper(['--prepare',project,session,config_path],expected)
    return prepare_delivery(project,session,config_path,expected)


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
    raise ValueError('Reading cc-connect configuration requires an installed Python 3.11+ or tomli')


def helper(arguments=(), expected=None):
    result = subprocess.run([toml_python(), str(Path(__file__).resolve()), *arguments],
                            input=json.dumps(expected), capture_output=True, text=True, timeout=35)
    data = json.loads(result.stdout)
    if result.returncode:raise ValueError(data.get('error','Could not capture conversation'))
    return data


def capture_arguments():
    """Capture metadata without probing the bridge or channel."""
    return capture()


def inspect_compatible(project, session, directory, config_path, expected=None):
    if not expected or project == expected.get('entry_project'):
        return inspect(project,session,directory,config_path,expected)
    try:
        import tomllib
    except ImportError:
        try:import tomli
        except ImportError:return helper(['--inspect',project,session,directory,config_path],expected)
    return inspect(project,session,directory,config_path,expected)


if __name__ == '__main__':
    try:
        if sys.argv[1:2]==['--inspect']:value=inspect(*sys.argv[2:],expected=json.load(sys.stdin))
        elif sys.argv[1:2]==['--prepare']:value=prepare_delivery(*sys.argv[2:],expected=json.load(sys.stdin))
        else:value=capture()
        print(json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
