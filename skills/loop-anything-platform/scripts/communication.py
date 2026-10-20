"""Scoped execution client; source calls travel via the team transport when required. Stdlib only."""
import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen


def call(context, tool, arguments):
    def invoke(name, values):
        body = {'tool': 'communication_execute', 'arguments': {'request_id': context['request_id'], 'token': context['token'], 'tool': name, 'arguments': values}}
        request = Request((context.get('execution_url') or context['platform_url']).rstrip('/') + '/api/tools', data=json.dumps(body).encode(),
                          headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        if not result.get('ok'):
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        return result
    result = invoke(tool, arguments)
    if tool in ('source_call','read_context') and 'call' in result:
        deadline = time.monotonic() + 25
        while result['call']['state'] in ('pending', 'executing', 'awaiting_context') and time.monotonic() < deadline:
            time.sleep(.25)
            result = invoke('source_result', {'id': result['call']['id']})
        if result['call']['state'] == 'failed':
            raise RuntimeError(result['call']['error'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context')
    parser.add_argument('--url')
    parser.add_argument('--request')
    parser.add_argument('--token')
    parser.add_argument('tool')
    parser.add_argument('--arguments', default='{}')
    a = parser.parse_args()
    context = json.loads(Path(a.context).read_text()) if a.context else dict(platform_url=a.url, request_id=a.request, token=a.token)
    arguments = json.loads(Path(a.arguments[1:]).read_text() if a.arguments.startswith('@') else a.arguments)
    print(json.dumps(call(context,a.tool,arguments), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
