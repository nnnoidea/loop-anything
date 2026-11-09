"""Portable client included in exported Skills; calls the platform's real tools."""
import argparse
import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(url, data=None, request_id=None, wait=30):
    if url.startswith('nas:'):
        try:
            from platform_transport import fetch as nas_fetch
            return nas_fetch(url,data,request_id,wait)
        except (OSError,ValueError) as exc:return {'ok':False,'error':str(exc)}
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
        return {'ok': False, 'error': str(exc), 'hint': 'Start Loop Anything and check the URL in connection.json or --url.'}


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', nargs='?', default='list')
    parser.add_argument('--arguments', default='{}', help='JSON object or @UTF8_JSON_FILE')
    parser.add_argument('--name', help='Set the local human display name with the profile command')
    parser.add_argument('--created-by', help='Override human attribution for a new Run or standalone collaboration')
    parser.add_argument('--url', help='Override the platform address in connection.json')
    parser.add_argument('--request-id', help='Reuse a NAS operation ID, or read it with the result command')
    parser.add_argument('--wait', type=float, default=30, help='Seconds to wait for a NAS tool receipt; timeout never cancels the operation')
    parser.add_argument('--notification-command', help='Sender argv as JSON or @UTF8_JSON_FILE (start_run/change_settings only)')
    parser.add_argument('--output', help='Write an exported Loop ZIP to this new file')
    args = parser.parse_args()
    if args.notification_command is not None and args.tool not in ('start_run', 'change_settings'):
        parser.error('--notification-command is only for start_run or change_settings')
    connection = Path(__file__).resolve().parent.parent / 'connection.json'
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
    if args.created_by is not None and args.tool not in ('start_run','start_collaboration','request_assistance'):
        parser.error('--created-by is only for creating Runs or standalone collaboration')
    settings = json.loads(connection.read_text(encoding='utf-8')) if connection.exists() else {}
    url = (args.url or settings.get('url') or '').rstrip('/')
    if not url:
        parser.error('Specify --url for the running platform')
    if args.tool == 'check':
        result = check_connection(url)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result['ok'] else 2)
    if args.tool=='result':
        if not url.startswith('nas:') or not args.request_id:parser.error('result requires a NAS URL and --request-id')
        from platform_transport import result
        answer=result(url,args.request_id)
        print(json.dumps(answer,ensure_ascii=False,indent=2))
        raise SystemExit(0 if answer.get('ok',True) and answer.get('accepted',True) else 2)
    values = load_json(args.arguments)
    if args.created_by is not None:values['created_by']=args.created_by
    if args.tool in ('start_run','start_collaboration','request_assistance') and 'created_by' not in values:
        author=args.created_by if args.created_by is not None else os.environ.get('LOOP_ANYTHING_USER_NAME',profile.get('user_name',''))
        if author:values['created_by']=author
    if args.notification_command is not None:
        target = values if args.tool == 'start_run' else values.setdefault('change', {})
        if 'notification_command' in target:
            parser.error('Supply notification_command once, in arguments or --notification-command')
        target['notification_command'] = load_json(args.notification_command)
    if args.tool in ('request_assistance','start_run','start_collaboration') and not any(k in values for k in ('notification_route','conversation_id','notification_command')) and not values.get('source',{}).get('run_id') and os.environ.get('CC_PROJECT') and os.environ.get('CC_SESSION_KEY','').split(':')[0] in ('feishu','lark'):
        # Carry bridge provenance only; platform adapters resolve and deliver later.
        if 'chat_context' not in values:
            values['chat_context']={'platform':os.environ['CC_SESSION_KEY'].split(':')[0],
                                    'entry_project':os.environ['CC_PROJECT'],
                                    'session_key':os.environ['CC_SESSION_KEY']}
    data = None if args.tool == 'list' else json.dumps({'tool': args.tool, 'arguments': values}, ensure_ascii=False).encode('utf-8')
    result = fetch(url + '/api/tools', data=data,request_id=args.request_id,wait=args.wait) if url.startswith('nas:') else fetch(url+'/api/tools',data=data)
    if args.output and result.get('ok') and 'base64' in result:
        with Path(args.output).open('xb') as output:
            output.write(base64.b64decode(result.pop('base64')))
        result['file'] = str(Path(args.output).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get('ok', args.tool == 'list') and result.get('accepted', True) else 2)


if __name__ == '__main__':
    main()
