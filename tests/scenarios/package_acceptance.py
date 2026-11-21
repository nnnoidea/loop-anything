"""Package HTTP acceptance. Explicitly simulated initialization; no model calls."""
import argparse
import base64
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from managed_http import register, start, claim, finish_turn
from loop_anything.examples.loops import node, tasks, TEXT, BOOL


def definition():
    return {'schema_version': 2, 'id': 'package-handoff', 'version': '1', 'name': 'Loop 包交付验收',
        'entry': 'initialize', 'handbook': {'instructions': '模拟初始化写目标和结果，确定性脚本消费结果并结束。'},
        'records': {'text': TEXT, 'flag': BOOL},
        'nodes': {'initialize': node('模拟初始化', {}, {'result': 'text'}, '提交初始化结果', plan_nodes=['finish']),
                  'finish': node('确定性结束', {'value': TEXT}, {'done': 'flag'}, '检查结果并结束')},
        'seed': tasks('first', 'initialize', {}, {'result': 'result'}),
        'plans': {}}


SCRIPT = """import json,sys
request=json.load(sys.stdin)
if sys.argv[1]=='initialize':
    print(json.dumps({'event':'completed','envelope':{'settings':{'objective':'Package handoff with simulated initialization','completion_rule':{'op':'ge','args':[{'path':['completed','finish']},1]}},'outputs':{'result':'portable'},'tasks':[{'id':'last','node':'finish','inputs':{'value':{'record':'result'}},'outputs':{'done':{'id':'done'}}}]}}))
else:
    print(json.dumps({'event':'completed','envelope':{'outputs':{'done':request['inputs']['value']=='portable'}}}))
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8768')
    parser.add_argument('--output', required=True, help='New evidence directory')
    args = parser.parse_args()
    folder = Path(args.output).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    def api(route, body=None):
        req = Request(args.url + '/api/' + route, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json', 'X-Loop-Anything': 'workspace'})
        with urlopen(req, timeout=15) as response:
            return json.load(response)
    session = register(api)
    bp = definition()
    for node in bp['nodes'].values():
        node['progression'] = 'rules'
    implementations = {n: {'options': {'default': {'kind': 'command', 'command': ['python3', 'scripts/action.py', n], 'simulation': True}}, 'default': 'default'} for n in bp['nodes']}
    reports = []
    for count in (0, 1, 2):
        doc = {'loop_definition': bp, 'implementations': dict(list(implementations.items())[:count])}
        assets = [{'path': 'scripts/action.py', 'base64': base64.b64encode(SCRIPT.encode()).decode()}] if count else []
        packed = api('packages/export', {'document': doc, 'assets': assets})
        (folder / ('implementations-%s.loop.zip' % count)).write_bytes(base64.b64decode(packed['base64']))
        inspected = api('packages/inspect', {'base64': packed['base64']})
        assert inspected['document']['implementations'] == doc['implementations']
        installed = api('packages/install', {'base64': packed['base64']})
        assert installed['started'] is False
        check = api('packages/smoke', {'key': installed['key']})
        assert check['ready'] == (count == 2)
        assert len(check['unbound_nodes']) == 2 - count
        report = {'implementations': count, 'installed': installed, 'smoke': check}
        turn = start(api, session, installed['key'], 'Loop 包交付验收')
        run = api('runs/'+turn['run_id'])
        if count != 2:
            assert run['status'] == 'running'
            report.update(run_id=run['id'],status=run['status'],created_with_missing_implementations=True)
        else:
            finish_turn(api, turn if turn.get('token') else claim(api, session, turn['run_id']))
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                run = api('runs/' + run['id'])
                assert not any(e['status'] == 'fault' for e in run['executions'])
                if run['status'] == 'completed':
                    break
                time.sleep(.2)
            assert run['status'] == 'completed'
            assert run['records']['done'][-1]['value'] is True
            report['run_id'], report['status'] = run['id'], run['status']
            (folder / 'completed-run.json').write_text(json.dumps(run, ensure_ascii=False, indent=2))
        reports.append(report)
        print(json.dumps({'implementations': count, 'installed': True, 'ready': check['ready'], 'status': report.get('status')}, ensure_ascii=False), flush=True)
    (folder / 'report.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
