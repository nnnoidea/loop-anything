"""Report from a script/monitor using the command's JSON stdin context. Standard library only."""
import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def _call(context, tool, fields):
    url = context.get('platform_url')
    if not url:
        raise RuntimeError('Reporting requires the running platform HTTP address from command context')
    arguments = {key: context[key] for key in ('run_id', 'task_id', 'execution_id', 'token')}
    arguments.update(fields)
    request = Request(url.rstrip('/') + '/api/tools',
                      data=json.dumps({'tool': tool, 'arguments': arguments}).encode(),
                      headers={'Content-Type': 'application/json', 'X-Loop-Anything': 'workspace'})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(exc.read().decode('utf-8', errors='replace')) from None
    if not result.get('ok'):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def report(context, event, *, report_id=None, **fields):
    result = _call(context, 'report_task', dict(fields,event=event,report_id=report_id or str(uuid.uuid4())))
    if not (result.get('accepted') or result.get('stale')):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def notify(context, key, message, **fields):
    """Queue a notification/question under this script's current execution identity."""
    return _call(context, 'notify', dict(fields,key=key,message=message))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('event')
    parser.add_argument('--context', default='-', help='Context JSON file; - reads command stdin')
    parser.add_argument('--data', default='{}', help='JSON or @file: envelope, detail, external_id, poll_after, report_id')
    args = parser.parse_args()
    context = json.load(sys.stdin) if args.context == '-' else json.loads(Path(args.context).read_text(encoding='utf-8'))
    fields = json.loads(Path(args.data[1:]).read_text(encoding='utf-8') if args.data.startswith('@') else args.data)
    print(json.dumps(report(context, args.event, **fields), ensure_ascii=False))


if __name__ == '__main__':
    main()
