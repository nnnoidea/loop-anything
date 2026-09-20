"""Portable client included in exported Skills; calls the platform's real tools."""
import argparse
import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(url, data=None):
    headers = {'Content-Type': 'application/json', 'X-Loop-Anything': 'workspace'}
    if data is not None and os.environ.get('LOOP_ANYTHING_EDIT_PASSWORD'):
        headers['Authorization'] = 'Basic ' + base64.b64encode((':' + os.environ['LOOP_ANYTHING_EDIT_PASSWORD']).encode('utf-8')).decode('ascii')
    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
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
            'platform': status, 'agent_execution': 'not_checked'}


def load_json(value):
    return json.loads(Path(value[1:]).read_text(encoding='utf-8') if value.startswith('@') else value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', nargs='?', default='list')
    parser.add_argument('--arguments', default='{}', help='JSON object or @UTF8_JSON_FILE')
    parser.add_argument('--url', help='Override the platform address in connection.json')
    parser.add_argument('--notification-command', help='Sender argv as JSON or @UTF8_JSON_FILE (start_run/change_settings only)')
    parser.add_argument('--output', help='Write an exported Loop ZIP to this new file')
    args = parser.parse_args()
    if args.notification_command is not None and args.tool not in ('start_run', 'change_settings'):
        parser.error('--notification-command is only for start_run or change_settings')
    connection = Path(__file__).resolve().parent.parent / 'connection.json'
    settings = json.loads(connection.read_text(encoding='utf-8')) if connection.exists() else {}
    url = (args.url or settings.get('url') or '').rstrip('/')
    if not url:
        parser.error('Specify --url for the running platform')
    if args.tool == 'check':
        result = check_connection(url)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result['ok'] else 2)
    values = load_json(args.arguments)
    if args.notification_command is not None:
        target = values if args.tool == 'start_run' else values.setdefault('change', {})
        if 'notification_command' in target:
            parser.error('Supply notification_command once, in arguments or --notification-command')
        target['notification_command'] = load_json(args.notification_command)
    data = None if args.tool == 'list' else json.dumps({'tool': args.tool, 'arguments': values}, ensure_ascii=False).encode('utf-8')
    result = fetch(url + '/api/tools', data=data)
    if args.output and result.get('ok') and 'base64' in result:
        with Path(args.output).open('xb') as output:
            output.write(base64.b64decode(result.pop('base64')))
        result['file'] = str(Path(args.output).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get('ok', args.tool == 'list') else 2)


if __name__ == '__main__':
    main()
