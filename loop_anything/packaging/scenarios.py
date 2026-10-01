"""Author scenarios run the real Engine in a private Store; every command is intercepted."""
import copy
import json
import tempfile
from pathlib import Path
from concurrent.futures import Future

from loop_anything.runtime.model import Invalid, contract, digest
from loop_anything.runtime.checks import evaluate, validate_expression
from loop_anything.runtime.timeline_model import validate_v2
from loop_anything.runtime.timeline_plan import add_task, build_plan, validate_task_dependencies
from loop_anything.runtime.task_refs import describe_references
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.interfaces.agent_tasks import RunTools


def validate_scenarios(scenarios):
    if not isinstance(scenarios, list) or len(scenarios) > 20:
        raise Invalid('scenarios must be an array of at most 20 cases')
    names = set()
    for case in scenarios:
        if not isinstance(case, dict) or set(case) - {'name','inputs','bindings','steps','assertions'} or not {'name','steps','assertions'} <= case.keys():
            raise Invalid('Scenario requires name, steps, assertions and optional inputs/bindings')
        if not isinstance(case['name'], str) or not case['name'].strip() or case['name'] in names:
            raise Invalid('Scenario names must be nonempty and unique')
        names.add(case['name'])
        if any(not isinstance(case[k], dict) for k in ('inputs','bindings') if k in case):raise Invalid('Scenario inputs/bindings must be objects')
        if not isinstance(case['steps'], list) or len(case['steps']) > 200:raise Invalid('Scenario steps must be an array of at most 200 steps')
        for step in case['steps']:
            if not isinstance(step, dict) or len(step.keys() & {'report','send_event','ticks'}) != 1:
                raise Invalid('Scenario step needs exactly one of report, send_event, ticks')
            if 'ticks' in step:
                if set(step) != {'ticks'} or type(step['ticks']) is not int or not 1 <= step['ticks'] <= 20:raise Invalid('ticks must be 1..20')
            elif 'send_event' in step:
                if set(step) != {'send_event'} or not isinstance(step['send_event'],dict):raise Invalid('send_event must contain Run tool arguments')
            else:
                if set(step) - {'report','task_id','ref','node','attempt','duplicate','accepted','expect_error'} or len(step.keys() & {'task_id','ref','node'}) != 1:
                    raise Invalid('Report step selects exactly one task_id, ref or node')
                if not isinstance(step['report'],dict):raise Invalid('report must be an object')
                if 'attempt' in step and (type(step['attempt']) is not int or step['attempt'] < 1):raise Invalid('attempt must be positive')
                for field in ('accepted','duplicate'):
                    if field in step and type(step[field]) is not bool:raise Invalid(field + ' must be boolean')
                if 'expect_error' in step and (not isinstance(step['expect_error'],str) or not step['expect_error']):raise Invalid('expect_error must be nonempty text')
        if not isinstance(case['assertions'],list) or not case['assertions']:raise Invalid('Scenario requires at least one assertion')
        for check in case['assertions']:
            if not isinstance(check,dict) or set(check) != {'message','test'} or not isinstance(check['message'],str):raise Invalid('Assertion needs message and test')
            validate_expression(check['test'])


def preview_plan(document, name, key, values, steps=None, bindings=None, round=None):
    bp = document['loop_definition']
    summary = {}
    specs = build_plan(bp, name, key, values, steps, round, summary)
    run = {'loop_definition':bp,'implementations':document['implementations'], 'tasks':{},'executions':[],
           'records':{},'history':[], 'settings':{'revision':1,'bindings':bindings or {}}}
    from loop_anything.runtime.implementations import validate_bindings
    validate_bindings(bp, document['implementations'], bindings or {})
    for spec in specs:add_task(run,spec,{'preview':True})
    validate_task_dependencies(run)
    return dict(summary, tasks=specs, preview=True)


class InlinePool:
    """Local interception only; cannot race a live Engine or monkeypatch global commands."""
    def submit(self, fn, *args):
        future = Future()
        try:future.set_result(fn(*args))
        except Exception as exc:future.set_exception(exc);raise
        return future
    def shutdown(self, **kwargs):pass


def scenario_state(run):
    rows = []
    for task in run['tasks'].values():
        attempt = next((e for e in reversed(run['executions']) if e['task_id']==task['id']), {})
        rows.append(dict(task['spec'],status=task['status'],wait_reasons=task.get('wait_reasons',[]),error=attempt.get('error'),resolved_inputs=attempt.get('inputs'),outputs_value=attempt.get('outputs'),attempt=attempt.get('attempt',0)))
    counts = {node:{'total':0,'completed':0} for node in run['loop_definition']['nodes']}
    for task in rows:
        counts[task['node']]['total'] += 1
        counts[task['node']][task['status']] = counts[task['node']].get(task['status'],0)+1
    return {'status':run['status'],'task_count':len(rows),'tasks':rows,'by_ref':{t['ref']:t for t in rows if 'ref' in t},
            'by_id':{t['id']:t for t in rows},'counts':counts,
            'records':{k:v[-1]['value'] for k,v in run['records'].items()},
            'route_count':sum(h['kind']=='route_fired' for h in run['history'])}


def run_scenarios(document, scenarios=None):
    bp, implementations = document['loop_definition'], document['implementations']
    validation = validate_v2(bp, implementations)
    if not validation['valid']:raise Invalid('; '.join(validation['errors']))
    cases = bp.get('scenarios', []) if scenarios is None else scenarios
    validate_scenarios(cases)
    if not cases:raise Invalid('Supply scenarios or save them with set_loop.scenarios')
    results=[]
    for case in cases:
        with tempfile.TemporaryDirectory(prefix='loop-scenario-') as directory:
            store=Store(Path(directory)/'test.sqlite3')
            # Persist only in this throwaway Store; no package assets or user database are opened.
            with store.connection() as db:
                db.execute('INSERT INTO loop_definitions VALUES (?,?,?,?)',('scenario',digest(bp),json.dumps(bp),json.dumps(implementations)))
                db.commit()
            engine=Engine(store);engine.pool.shutdown(wait=True);engine.pool=InlinePool()
            intercepted=[]
            engine.timeline_runtime.execute=lambda run_id,e,snapshot,observe:intercepted.append({'task_id':e['task_id'],'kind':e['implementation']['kind'],'observe':observe})
            def delivery(run_id, notice, snapshot):
                with store.edit(run_id) as current:
                    row=next(n for n in current['notifications'] if n['id']==notice['id'])
                    row.update(status='delivered',receipt={'simulated':True},error=None)
            engine.timeline_runtime.deliver=delivery
            run=None;receipts=[];checks=[];error=None;step_index=None
            try:
                run=store.create('scenario',case['name'],case.get('inputs'),bindings=case.get('bindings'),authorization='Isolated author scenario',notification_route='workspace')
                run_id=run['id']
                def tick():
                    if len(store.get(run_id)['tasks'])>1000:raise Invalid('Scenario exceeded 1000 tasks')
                    engine.tick(run_id)
                for step_index,step in enumerate(case['steps']):
                    tick()
                    if 'ticks' in step:
                        for _ in range(step['ticks']-1):tick()
                        continue
                    if 'send_event' in step:
                        RunTools(store,run_id).call('send_event',step['send_event']);tick();continue
                    snapshot=store.get(run_id)
                    tasks=[t for t in snapshot['tasks'].values() if
                           (t['id']==step['task_id'] if 'task_id' in step else t['spec'].get('ref')==step['ref'] if 'ref' in step else t['spec']['node']==step['node'])]
                    if len(tasks)!=1:raise Invalid('Report selector must identify exactly one Task; use ref or task_id')
                    task=tasks[0]
                    attempts=[e for e in snapshot['executions'] if e['task_id']==task['id'] and ('attempt' not in step or e['attempt']==step['attempt'])]
                    if not attempts:raise Invalid('Selected task is not dispatched; inspect dependencies and implementation')
                    execution=attempts[-1];report=copy.deepcopy(step['report']);report.setdefault('report_id','scenario-'+str(step_index))
                    source='agent' if execution['implementation']['kind']=='agent' else 'monitor' if execution.get('external_id') else 'script'
                    try:
                        with store.edit(run_id) as current:
                            e=engine.execution(current,execution['id'])
                            receipt=engine.timeline_runtime.report_in_run(current,e,report,source)
                            if step.get('duplicate'):
                                duplicate=engine.timeline_runtime.report_in_run(current,e,report,source)
                                if not duplicate.get('duplicate'):raise Invalid('Duplicate report was not deduplicated')
                                receipt=dict(receipt,duplicate_verified=True)
                        if step.get('expect_error'):raise AssertionError('Expected report error: '+step['expect_error'])
                    except Invalid as exc:
                        if step.get('expect_error') and step['expect_error'] in str(exc):
                            receipts.append({'step':step_index,'expected_error':str(exc)});continue
                        raise
                    receipts.append(dict(receipt,step=step_index))
                    if receipt['accepted'] != step.get('accepted',True):raise Invalid('Report acceptance differs from expected value')
                    if execution['implementation']['kind']=='agent' and receipt.get('completed'):
                        RunTools(store,run_id,execution['token']).call('finish',{})
                tick()
                state=scenario_state(store.get(run_id))
                for check in case['assertions']:
                    try:
                        actual=evaluate(check['test'],state)
                        passed=actual is True;detail=None
                    except (KeyError,IndexError,TypeError,ValueError) as exc:passed=False;detail=str(exc)
                    checks.append(dict(message=check['message'],passed=passed,detail=detail))
            except (Invalid,AssertionError,KeyError,TypeError,IndexError) as exc:
                error=str(exc)
            finally:
                state=scenario_state(store.get(run['id'])) if run else None
                engine.close()
            results.append({'name':case['name'],'passed':error is None and bool(checks) and all(c['passed'] for c in checks),
                            'error':error,'failed_step':step_index if error else None,'assertions':checks,
                            'state':state,'receipts':receipts,'intercepted_calls':intercepted})
    return {'passed':all(r['passed'] for r in results),'simulated':True,'scenarios':results,
            'limitations':['Commands, Agent reasoning and notification delivery were simulated; external environments were not verified.',
                           'Tests use real time. Long waits need explicit mock lifecycle reports; no virtual clock is provided.']}
