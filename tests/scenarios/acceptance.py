"""Public HTTP acceptance; leaves inspectable Runs. All responses are simulated."""
import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from loop_anything.examples.loops import research, trip


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8766')
    parser.add_argument('--report', default='.loop-anything/acceptance.json')
    args = parser.parse_args()

    def api(route, body=None):
        request = Request(args.url + '/api/' + route, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json', 'X-Loop-Anything': 'workspace'})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def until(id, predicate):
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            run = api('runs/' + id)
            faults = [e for e in run['executions'] if e['status'] == 'fault']
            if faults:
                raise AssertionError(faults)
            if predicate(run):
                return run
            time.sleep(.15)
        raise AssertionError('Timeout: ' + id)

    report = {'url': args.url, 'at': time.time(), 'simulated': 'All Task and Agent responses; not the Engine', 'runs': {}}
    for factory, name in ((research, 'research'), (trip, 'trip')):
        bp, implementations = factory()
        result = api('publish', {'loop_definition': bp, 'implementations': implementations})
        inputs = dict(bp['defaults'], **({'slow_duration': 14} if name == 'research' else {}))
        run = api('runs', {'key': result['key'], 'title': name + ' · 平台验收', 'inputs': inputs})
        id = run['id']
        report['runs'][name] = {'id': id, 'checks': []}
        checks = report['runs'][name]['checks']
        if name == 'research':
            run = until(id, lambda r: any(e['node'] == 'reason' and e['inputs']['group'] == 'GA' and e['status'] == 'completed' for e in r['executions']))
            assert next(e for e in run['executions'] if e['node'] == 'train' and e['inputs']['experiment']['id'] == 'B1')['status'] != 'completed', 'GA was blocked by GB'
            checks.append('GA completed while GB training')
            assert any(w['spec']['node'] == 'train' and w['spec']['inputs']['experiment'].get('literal', {}).get('id') == 'C1' for w in run['tasks'].values())
            checks.append('GC dynamically planned while GB training')
        else:
            def pending(status):
                current = until(id, lambda r: any(e['status'] == status for e in r['executions']) and (status != 'approval' or not r.get('agent_sessions')))
                return next(e for e in current['executions'] if e['status'] == status)

            def approve(e):
                return api('runs/' + id + '/submit', {'execution_id': e['id'], 'token': e['token'],
                    'envelope': {'outputs': {'decision': {'approved': True,
                    'proposal_id': e['inputs']['proposal']['id'], 'proposal_record': e['parameters']['proposal_record']}}}})

            old = pending('approval')
            owner = api('runs/' + id + '/agent', {'operation': 'acquire'})
            def operator(tool, arguments=None):
                result = api('runs/' + id + '/agent', {'token': owner['token'], 'tool': tool, 'arguments': arguments or {}})
                assert result['ok']
                return result
            old_run = api('runs/' + id)
            decision_record = old_run['tasks'][old['task_id']]['spec']['outputs']['decision']['id']
            for task in old_run['tasks'].values():
                if task['id'] == old['task_id'] or any(v.get('record') == decision_record for v in task['spec']['inputs'].values()):
                    operator('change_task', {'task_id': task['id'], 'operation': 'cancel', 'reason': 'User explicitly replaces old approval and downstream route'})
            operator('change_settings', {'revision': 1, 'change': {'constraints': {'destination': '北京', 'budget': 2200}}})
            try:
                approve(old)
                raise AssertionError('Stale approval accepted')
            except HTTPError as exc:
                assert exc.code == 409
            checks.append('Explicitly cancelled approval rejected over HTTP (409)')
            run = until(id, lambda r: any(e['id'] == old['id'] and e['status'] == 'cancelled' for e in r['executions']))
            planned = operator('build_plan', {'name': 'replan', 'key': 'changed-requirements', 'values': {'reason': 'User changed requirements'}})
            replan_id = planned['tasks'][0]['id']
            info = operator('read_task', {'task_id': replan_id})
            operator('build_plan', {'name': 'confirm', 'key': 'confirm-user-change',
                'values': {'proposal_record': info['task']['spec']['outputs']['proposal']['id']}})
            operator('complete_task', {'task_id': replan_id, 'task_version': info['task_version'],
                'envelope': {'outputs': {'proposal': {'id': 'user-' + replan_id, 'destination': '北京', 'amount': 2200,
                    'reason': 'Simulated user Agent implementing the explicit changed requirements'}}}})
            operator('finish')
            until(id, lambda r: any(e['node'] == 'approve' and e['id'] != old['id'] and e['status'] == 'approval' for e in r['executions']))
            current = pending('approval')
            assert current['inputs']['proposal']['destination'] == '北京'
            hooks = [{'id': 'acceptance-gate', 'target': {'node': 'book'}, 'action': 'pause', 'phase': 'before', 'frequency': 'once'},
                     {'id': 'acceptance-notice', 'target': {'node': 'book'}, 'action': 'notify', 'route': 'workspace', 'phase': 'after', 'frequency': 'always', 'message': '差旅预订结果已写入'}]
            api('runs/' + id + '/settings', {'revision': 2, 'change': {'hooks': hooks}})
            approve(current)
            run = until(id, lambda r: any(w['status'] == 'held' for w in r['tasks'].values()))
            assert not any(e['node'] == 'book' for e in run['executions'])
            checks.append('Before-dispatch gate prevented booking execution')
            firing = next(f for f in run['hook_firings'] if f['status'] == 'held')
            api('runs/' + id + '/command', {'action': 'release_gate', 'hook_firing': firing['id']})
            for status in ('cancelled', 'arrived'):
                waiting = pending('waiting')
                key = waiting['parameters']['event_key']
                api('runs/' + id + '/event', {'event_id': 'event-' + waiting['id'], 'name': 'trip-status', 'key': key,
                    'payload': {'observation': {'status': status, 'detail': '模拟行程事件', 'booking_record': key, 'sequence': 0}}})
                if status == 'cancelled':
                    approve(pending('approval'))
            checks += ['Correlated cancellation woke replan; approval required again', 'Arrival completed run']
        run = until(id, lambda r: r['status'] == 'completed' and all(n['status'] == 'delivered' for n in r['notifications']))
        assert not run['diagnostics']
        report['runs'][name].update(status=run['status'], executions=len(run['executions']), records=len(run['records']),
                                   notifications=run['notifications'], history=run['history'])
        print(name + ': completed; ' + str(len(run['executions'])) + ' executions; ' + id, flush=True)
    output = Path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('Acceptance evidence: ' + str(output.resolve()))


if __name__ == '__main__':
    main()
