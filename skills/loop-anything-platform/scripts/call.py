"""Portable client included in exported Skills; calls the platform's real tools."""
import argparse
import base64
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(url, data=None, request_id=None, wait=30):
    if url.startswith('nas:'):
        try:
            from platform_transport import fetch as nas_fetch
            return nas_fetch(url,data,request_id,wait)
        except (OSError,ValueError) as exc:return {'ok':False,'transport_error':True,'error':str(exc)}
    headers = {'Content-Type': 'application/json', 'X-Loop-Anything': 'workspace'}
    request = Request(url, data=data, headers=headers)
    try:
        # Scoped remote tools return a durable pending handle after at most 20 seconds.
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            return {'ok': False, 'error': json.load(exc)}
        except (ValueError, OSError):
            return {'ok': False, 'error': 'HTTP %s' % exc.code}
    except (URLError, OSError, ValueError) as exc:
        return {'ok': False, 'transport_error':True, 'error': str(exc), 'hint': 'Start Loop Anything and check your local/team spaces configuration or the explicit --url. No other space was contacted.'}


def check_connection(url):
    url = url.rstrip('/')
    status = fetch(url + '/api/platform')
    tools = fetch(url + '/api/tools')
    if not isinstance(status, dict) or 'keep_awake' not in status:
        return {'ok': False, 'url': url, 'error': status}
    if not isinstance(tools, dict) or not isinstance(tools.get('tools'), list):
        return {'ok': False, 'url': url, 'error': tools}
    return {'ok': True, 'url': url, 'tool_count': len(tools['tools']),
            'platform': status, 'service': tools.get('service', status.get('service')), 'agent_execution': 'not_checked'}


def load_json(value):
    return json.loads(Path(value[1:]).read_text(encoding='utf-8') if value.startswith('@') else value)


def space_config_module(name):
    import importlib.util
    spec=importlib.util.spec_from_file_location('_personal_spaces',Path(__file__).with_name(name+'.py'))
    config=importlib.util.module_from_spec(spec);spec.loader.exec_module(config)
    return config


def space_config():return space_config_module('spaces')


def main():
    if len(sys.argv)>1 and sys.argv[1]=='spaces':
        return space_config().main(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', nargs='?', default='list')
    parser.add_argument('--arguments', default='{}', help='JSON object or @UTF8_JSON_FILE')
    parser.add_argument('--name', help='Set the local human display name with the profile command')
    parser.add_argument('--created-by', help='Override human attribution for a new Run or standalone collaboration')
    parser.add_argument('--url', help='Target for new work/discovery; cannot override existing work')
    parser.add_argument('--space',choices=['local','team'],help='Choose a configured space for this call')
    parser.add_argument('--work', help='Returned work_id for same-name resources or platform-wide follow-up; no address needed')
    parser.add_argument('--request-id', help='Reuse a NAS operation ID, or read it with the result command')
    parser.add_argument('--wait', type=float, default=30, help='Seconds to wait for a NAS tool receipt; timeout never cancels the operation')
    parser.add_argument('--notification-command', help='Sender argv as JSON or @UTF8_JSON_FILE (start_run/change_settings only)')
    parser.add_argument('--output', help='Write an exported Loop ZIP or Timeline JSON to this new file')
    args = parser.parse_args()
    if args.notification_command is not None and args.tool not in ('start_run', 'change_settings'):
        parser.error('--notification-command is only for start_run or change_settings')
    profile_path = Path(os.environ.get('LOOP_ANYTHING_PROFILE') or Path.home()/'.config/loop-anything/profile.json')
    profile = {}
    if args.tool in ('profile','start_run','start_collaboration','request_assistance'):
        try:
            saved=json.loads(profile_path.read_text(encoding='utf-8')) if profile_path.exists() else {}
            name=saved.get('user_name','') if isinstance(saved,dict) else None
            if not isinstance(name,str) or len(name)>120 or any(ord(c)<32 for c in name):raise ValueError('invalid user_name')
            profile=saved
        except (OSError,ValueError) as exc:
            if args.tool=='profile' and args.name is None:parser.error('Cannot read name profile '+str(profile_path)+': '+str(exc))
            print('Ignoring unavailable optional name profile '+str(profile_path)+'; explicit attribution remains available.',file=sys.stderr)
    if args.tool == 'profile':
        if args.name is not None:
            name=args.name.strip()
            if len(name)>120 or any(ord(c)<32 for c in name):parser.error('Name must be at most 120 characters without control characters')
            profile['user_name']=name
            profile_path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=profile_path.parent,prefix=profile_path.name+'.',delete=False) as stream:
                temporary=Path(stream.name)
                stream.write(json.dumps(profile,ensure_ascii=False,indent=2)+'\n')
            try:temporary.replace(profile_path)
            finally:temporary.unlink(missing_ok=True)
        print(json.dumps({'user_name':profile.get('user_name',''),'path':str(profile_path)},ensure_ascii=False))
        return
    if args.name is not None:parser.error('--name is only for profile')
    if args.created_by is not None and args.tool not in ('start_run','start_collaboration','request_assistance','submit_run_request'):
        parser.error('--created-by is only for creating Runs or standalone collaboration')
    values = load_json(args.arguments)
    if not isinstance(values,dict):parser.error('Arguments must be an object')
    if args.created_by is not None:values['created_by']=args.created_by
    if (args.tool in ('start_run','start_collaboration','request_assistance','submit_run_request')) and 'created_by' not in values:
        author=args.created_by if args.created_by is not None else os.environ.get('LOOP_ANYTHING_USER_NAME',profile.get('user_name',''))
        if author:values['created_by']=author
    if args.notification_command is not None:
        target = values if args.tool == 'start_run' else values.setdefault('change', {})
        if 'notification_command' in target:
            parser.error('Supply notification_command once, in arguments or --notification-command')
        target['notification_command'] = load_json(args.notification_command)
    if (args.tool in ('request_assistance','start_run','start_collaboration','submit_run_request')) and not any(k in values for k in ('notification_route','notification_command')) and not values.get('source',{}).get('run_id') and os.environ.get('CC_PROJECT') and os.environ.get('CC_SESSION_KEY','').split(':')[0] in ('feishu','lark'):
        # Carry bridge provenance only; platform adapters resolve and deliver later.
        if 'chat_context' not in values:
            values['chat_context']={'platform':os.environ['CC_SESSION_KEY'].split(':')[0],
                                    'entry_project':os.environ['CC_PROJECT'],
                                    'session_key':os.environ['CC_SESSION_KEY']}
    routing=space_config_module('routing');ledger=routing.Ledger()
    # Reserve before any network I/O, including failures or a lost response.
    request_id=args.request_id or ('api-'+routing.hashlib.sha256((args.tool+':'+str(values['request_id'])).encode()).hexdigest() if args.tool in routing.NEW_REQUESTS and values.get('request_id') else 'api-'+uuid.uuid4().hex)
    try:
        if args.tool=='retry':
            prior=ledger.db.execute('SELECT tool,args FROM requests WHERE id=?',(args.request_id,)).fetchone()
            if not prior:raise ValueError('Unknown retry reference; no default platform was contacted.')
            if values:raise ValueError('retry uses the saved arguments; do not supply new arguments')
            args.tool,encoded=prior;values=json.loads(encoded)
        work=ledger.choose(args.tool,values,args.url,args.space,args.work,request_id)
        request_id=work['request_id']
        url=work['url']
        print(json.dumps({'work_id':work['id'],'routing_request_id':request_id}),file=sys.stderr,flush=True)
        cached=ledger.db.execute('SELECT response FROM requests WHERE id=?',(request_id,)).fetchone()
        if cached and cached[0] is not None and args.tool!='check':
            result=json.loads(cached[0])
        elif args.tool=='check':
            result=check_connection(url)
            if result.get('ok'):ledger.verify(work['id'],result['platform'].get('workspace_id'))
            ledger.finish(work['id'],args.tool,values,result,request_id)
        else:
            if url.startswith('nas:'):
                transport=space_config_module('platform_transport');root,_=transport.endpoint(url)
                identity=json.loads((root/'team.json').read_text(encoding='utf-8'))['workspace_id']
            else:
                status=fetch(url+'/api/platform')
                if status.get('transport_error'):raise ValueError('Original platform is unavailable; no other platform was contacted.')
                identity=status.get('workspace_id')
            ledger.verify(work['id'],identity)
            if args.tool=='result':
                prior=ledger.db.execute('SELECT tool,args,response FROM requests WHERE id=?',(request_id,)).fetchone()
                if prior[2] is not None:result=json.loads(prior[2])
                elif url.startswith('nas:'):
                    result=transport.result(url,request_id)
                    ledger.finish(work['id'],prior[0],json.loads(prior[1]),result,request_id)
                else:result={'ok':False,'outcome_unknown':True,'error':'No confirmed HTTP receipt; inspect original work before another operation.'}
            else:
                result=ledger.begin(request_id,nas=url.startswith('nas:'))
                if result is None:
                    data=None if args.tool=='list' else json.dumps({'tool':args.tool,'arguments':values,'expected_workspace':identity},ensure_ascii=False).encode('utf-8')
                    result=fetch(url+'/api/tools',data=data,request_id=request_id,wait=args.wait)
                    ledger.finish(work['id'],args.tool,values,result,request_id)
        result.update(platform_url=url,work_id=work['id'],routing_request_id=request_id)
    except (ValueError,OSError,KeyError) as exc:
        parser.error(str(exc))
    finally:ledger.close()
    if args.output and result.get('ok') and 'base64' in result:
        with Path(args.output).open('xb') as output:
            output.write(base64.b64decode(result.pop('base64')))
        result['file'] = str(Path(args.output).resolve())
    if args.output and result.get('ok') and args.tool=='export_timeline':
        with Path(args.output).open('x',encoding='utf-8') as output:
            json.dump(result.pop('document'),output,ensure_ascii=False,separators=(',',':'))
        result['file']=str(Path(args.output).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get('ok', args.tool == 'list') and result.get('accepted', True) else 2)


if __name__ == '__main__':
    main()
