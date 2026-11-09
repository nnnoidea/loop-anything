"""The same tool calls over HTTP or a durable NAS mailbox. No platform imports."""
import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import urlparse, unquote
import uuid

_path=Path(__file__).resolve().parents[2]/'loop-anything-dispatch/scripts/team_transport.py'
_spec=importlib.util.spec_from_file_location('_loop_tool_files',_path)
files=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(files)


def mount_path(value, roots, destination):
    """Only call for a known path field, never for arbitrary text or containers."""
    if not isinstance(value,str):return value
    for root in sorted(set([*roots,destination]),key=len,reverse=True):
        root=root.rstrip('/')
        if value==root or value.startswith(root+'/'):
            return destination.rstrip('/')+value[len(root):]
    return value


def endpoint(url):
    parsed=urlparse(url)
    if parsed.scheme!='nas' or parsed.netloc:raise ValueError('Use nas:///absolute/mounted/team/path')
    root=Path(unquote(parsed.path))
    if not root.is_absolute():raise ValueError('NAS team path must be absolute on this machine')
    scope=parsed.fragment.split('/') if parsed.fragment else []
    if scope and (len(scope)!=3 or scope[0]!='communication'):raise ValueError('Unknown scoped NAS endpoint')
    return root,scope


def scoped_url(base, ident, token):
    return base+('#' if base.startswith('nas:') else '/')+'communication/'+ident+'/'+token


def result(url, ident):
    root,_=endpoint(url);files.address(ident)
    try:return files.read_message(root/'api/replies'/(ident+'.json'))
    except FileNotFoundError:
        rejected=root/'api/rejected'/(ident+'.error.json')
        if rejected.exists():return files.read_message(rejected)
        if not (root/'api/requests'/(ident+'.json')).exists():raise ValueError('Unknown request ID at this NAS team')
        return {'ok':True,'pending':True,'request_id':ident,'notice':'Request remains queued; read this same request ID. Do not submit a new request.'}


def invoke(url, tool, arguments=None, request_id=None, wait=30):
    root,scope=endpoint(url)
    manifest=json.loads((root/'team.json').read_text(encoding='utf-8'))
    ident=files.address(request_id or 'api-'+uuid.uuid4().hex)
    packet={'version':1,'id':ident,'team_id':manifest['id'],'tool':tool,'arguments':arguments or {},'scope':scope,'client_root':str(root)}
    path=root/'api/requests'/(ident+'.json')
    # An identical ID is an identical operation. Retrying never changes the payload.
    reply=root/'api/replies'/(ident+'.json')
    if reply.exists():
        prior=files.read_message(root/'api/history'/(ident+'.json'))
        if prior!=packet:raise ValueError('Request ID already belongs to a different operation')
        return files.read_message(reply)
    files.publish_message(path,packet)
    until=time.monotonic()+max(0,min(float(wait),86400))
    while True:
        answer=result(url,ident)
        if not answer.get('pending') or time.monotonic()>=until:return answer
        time.sleep(min(.5,max(0,until-time.monotonic())))


def fetch(url, data=None, request_id=None, wait=30):
    if url.endswith('/api/platform'):return invoke(url[:-13],'_platform',request_id=request_id,wait=wait)
    if not url.endswith('/api/tools'):raise ValueError('Unknown NAS API endpoint')
    base=url[:-10]
    if data is None:return invoke(base,'_list',request_id=request_id,wait=wait)
    packet=json.loads(data)
    return invoke(base,packet['tool'],packet.get('arguments',{}),request_id,wait)
