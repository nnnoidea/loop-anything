"""Read non-secret bridge metadata for setup; reuse captured conversation IDs."""
import json
import copy
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def read_config(config_path):
    try:
        import tomllib
    except ImportError:
        try:import tomli as tomllib
        except ImportError:raise ValueError('Reading cc-connect configuration needs Python 3.11+ or tomli')
    try:return tomllib.loads(Path(config_path).expanduser().read_text(encoding='utf-8'))
    except Exception:raise ValueError('Cannot read or parse the selected cc-connect config file') from None


def catalog(config_path):
    config=read_config(config_path)
    bots=[]
    for project in config.get('projects',[]):
        name=project.get('name','')
        platforms=project.get('platforms',[])
        for platform in platforms:
            kind=platform.get('type','')
            unique=sum(p.get('name')==name for p in config.get('projects',[]))==1 and sum(p.get('type')==kind for p in platforms)==1
            bots.append({'project':name,'platform':kind,'label':name+' · '+kind,'selectable':bool(name and kind and unique),
                         **({} if unique else {'error':'Multiple Bots share this project/platform; cc-connect send cannot select one reliably'})})
    directory=config.get('data_dir')
    if isinstance(directory,str):directory=re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}',lambda m:os.environ.get(m[1],m[0]),directory)
    if directory and not isinstance(directory,str):raise ValueError('cc-connect data_dir must be text')
    return {'bots':bots,'data_dir':directory or None}


def prepare_delivery(session, expected=None):
    """Use an already saved root; all other session interpretation belongs to the bridge."""
    context=copy.deepcopy(expected) if expected else None
    parts=session.split(':',3)
    root=(context or {}).get('thread_root')
    if len(parts)==4 and parts[0] in ('feishu','lark') and parts[2]=='thread' and root and root!=parts[3]:
        session=f'{parts[0]}:{parts[1]}:root:{root}'
    return {'session':session,'conversation':context}


def capture_arguments():
    from notify_cc_connect import sender_command
    project,session=os.environ['CC_PROJECT'],os.environ['CC_SESSION_KEY']
    return {'operation':'conversation',
            'conversation':{'platform':session.split(':',1)[0],'chat_type':'unknown','session_key':session,'entry_project':project},
            'notification_command':sender_command()}


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



if __name__ == '__main__':
    try:
        if sys.argv[1:2]==['--catalog']:
            try:value=catalog(sys.argv[2])
            except ValueError as exc:
                if 'Python 3.11+' not in str(exc):raise
                value=helper(['--catalog',sys.argv[2]])
        else:value=capture_arguments()
        print(json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
