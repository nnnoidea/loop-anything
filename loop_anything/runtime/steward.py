"""Durable user delegations and replaceable Run stewards on ordinary Tasks."""
import copy
import json
import time

from loop_anything.runtime.flow_agent import NODE, materialize as materialize_flow
from loop_anything.runtime.model import Conflict, Invalid, digest
from loop_anything.runtime.store import Store
from loop_anything.runtime.task_scope import owner_for

ACTIVE = {'planned', 'ready', 'blocked', 'held', 'executing', 'decision', 'waiting', 'retrying', 'waiting_user', 'fault', 'stale'}
READ_ONLY = {'read_timeline', 'read_task', 'read_record', 'read_run', 'next_tasks', 'read_plans'}
DIRECT = {'command', 'update_run'}
PROMPT = """You are the current Run steward. Own the user's request through completion or an explicit question.
Read the complete Loop handbook and relevant node Skills, current Timeline and request record. Use read_run(view=snapshot) for running, completed and failed tasks and read_task for details; execution snapshots are separate from Timeline business progress. Business rules belong in the handbook. Reuse existing tasks and exact result versions. Persist meaningful progress, parameters, results and unresolved work in the Timeline. Read contributions from every method; process logs and scripts are optional references.
For a start request, read the Timeline and use the current Loop handbook to advance its work. Existing goals and progress need no initialization. Arrange this method's tasks with explicit inputs; fill missing method-specific context yourself rather than requiring the previous method to supply it. Keep completed results and in-flight experiments. Inspect pending work and explicitly adjust it when the current method calls for a different next step. A declared entry Task is optional; operate it only when appropriate. Commit progress and arrangements in your completed report. Confirm actual arrangements before reporting startup complete. The Run ID is already durably bound to this request; reuse it on recovery.
For objective/constraint changes use update_timeline and follow its notice: inspect the full Timeline, especially running tasks, report to the user, and wait for the user's decision before extra task changes. Other explicitly requested operations use existing scoped tools. For an explanation, read relevant evidence and return the full answer. Use answer_run_request with status=waiting_user and a question when information is missing; then finish. Further user replies create another managed turn with the same request history.
When done, complete your own decision Task with outputs.decision containing the full result, reasoning and evidence, then finish. Review or adjust dependent work before completing a progression decision: completing it releases those successors. The platform delivers request results to the saved request origin, falling back to the Run outlet only when no origin was supplied. Normal task completion returns here unless its node selects rule progression. Explicit plan routes own their events. Long waits and monitoring belong to scripts/events, and assistance uses the existing wait/resume protocol.
You can operate this Run only through the provided execution identity. A steward replacement revokes old management turns. New stewards read saved requests and Timeline before continuing partial operations. Each request has a stable ID; use stable task keys to avoid duplicated work.
"""


def agents(store):
    from loop_anything.runtime.communication import service
    return service(store).settings()['agents']


def select_agent(store, ident):
    agent = agents(store).get(ident)
    if not agent or not agent.get('enabled', True) or not agent.get('local', True):
        raise Invalid('Select an enabled local named Agent from list_stewards')
    return {'agent_id': ident, 'name': agent['name'], 'implementation': copy.deepcopy(agent['implementation'])}


def materialize(run):
    from loop_anything.runtime.agent_prompt import DEFAULTS
    run['loop_definition'] = copy.deepcopy(run['loop_definition'])
    implementation = copy.deepcopy(run['steward']['implementation'])
    implementation['prompt'] = PROMPT + '\n' + DEFAULTS['task']
    materialize_flow(run, implementation)
    run['loop_definition']['nodes'][NODE]['label'] = 'Run 管家'


def management_task(task):
    return bool(task.get('origin', {}).get('steward'))


def attention(run, issues):
    items = [item for item in issues if item['kind'] in ('unexpected', 'request')
             and not management_task(run['tasks'].get(item.get('task_id'), {}))]
    if not items:
        return
    ident = run['id'] + '-attention-' + digest(items)[:24]
    if ident in run.get('steward_requests', {}):
        return
    request = {'id': ident, 'operation': 'repair', 'message': 'Handle current Run issues within user authorization',
               'arguments': {'issues': copy.deepcopy(items)}, 'created_at': time.time(), 'replies': [], 'automatic': True}
    run.setdefault('steward_requests', {})[ident] = request
    add_turn(run, request)


def attach_decision(run, task):
    if not management_task(task) or task['origin'].get('request_id'):
        return
    ident = run['id'] + '-' + task['id']
    request = {'id': ident, 'operation': 'decide', 'message': 'Decide subsequent work from the completed Task',
               'arguments': copy.deepcopy(task['origin']['flow_agent']), 'created_at': time.time(),
               'replies': [], 'automatic': True, 'status': 'pending', 'task_id': task['id']}
    task['origin']['request_id'] = ident
    run.setdefault('steward_requests', {})[ident] = request


def current_owner(run, token):
    owner = owner_for(run, token)
    task = run['tasks'].get((owner or {}).get('task_id'), {})
    generation = task.get('origin', {}).get('steward')
    if not generation or generation != run.get('steward', {}).get('generation'):
        raise Conflict('Use the current steward execution identity')
    return task


def add_turn(run, request, trigger=None):
    from loop_anything.runtime.timeline_plan import add_task
    generation = run['steward']['generation']
    task_id = 'steward-' + digest([request['id'], generation, len(request.get('replies', []))])[:24]
    trigger = copy.deepcopy(trigger if trigger is not None else request.get('arguments', {}) if request['operation']=='decide' else {})
    trigger.update(request_id=request['id'], event=trigger.get('event', 'user_request'))
    spec = {'id': task_id, 'node': NODE, 'inputs': {'trigger': {'literal': trigger}},
            'outputs': {'decision': {'id': task_id + '.decision'}}}
    from loop_anything.runtime.implementations import selected
    seed=run['tasks'].get(run['loop_definition'].get('seed',{}).get('id'))
    if request['operation']=='start' and seed and (selected(run,seed)[1] or {}).get('kind')!='agent':
        spec['after']=[seed['id']]
    add_task(run, spec, {'flow_agent': trigger, 'steward': generation, 'request_id': request['id']})
    request.update(task_id=task_id, status='pending')


def receipt(run, request):
    task = run['tasks'].get(request.get('task_id'), {})
    attempt = next((e for e in run['executions'] if e['id'] == task.get('execution_id')), {})
    state = request['status']
    if state == 'pending' and task.get('status') == 'cancelled':
        state = 'cancelled'
    elif state == 'pending' and task.get('status') in ('fault', 'stale'):
        state = 'failed'
    if state == 'pending':
        failed=next((run['tasks'][ident] for ident in task.get('spec',{}).get('after',[])
                     if run['tasks'][ident]['status'] in ('fault','stale','cancelled')),None)
        if failed:
            state='failed'
            attempt=next((e for e in run['executions'] if e['id']==failed.get('execution_id')), {})
    if state == 'pending' and task.get('status') in ('executing', 'decision', 'waiting'):
        state = 'processing'
    return {'request_id': request['id'], 'run_id': run['id'], 'status': state,
            'steward': {k: run.get('steward', {}).get(k) for k in ('agent_id', 'name', 'generation')},
            'task_id': request.get('task_id'), 'task_status': task.get('status'),
            'error': attempt.get('error') or task.get('budget_error'),
            'result': request.get('result'), 'replies': request.get('replies', []),
            'operation': request['operation'], 'message': request.get('message', '')}


def expose_requests(run):
    # Call only on response copies; dispatch keeps the persisted request state.
    run['steward_requests'] = {key: dict(request, **receipt(run, request))
                               for key, request in run.get('steward_requests', {}).items()}
    return run


def request_context(store, arguments):
    """Capture the request origin once; sending stays in the existing outbox."""
    context = {k: copy.deepcopy(arguments[k]) for k in ('created_by', 'notification_route',
               'notification_command', 'conversation_id', 'chat_context') if k in arguments}
    if not any(k in context for k in ('notification_route', 'notification_command')):
        from loop_anything.runtime.communication import service
        from loop_anything.runtime.communication_conversations import from_source, resolve
        if context.get('chat_context') and not context.get('conversation_id'):
            context['conversation_id'] = from_source(service(store), context['chat_context'])['id']
        if context.get('conversation_id'):
            resolve(service(store), context['conversation_id'])
    return context


def progression_waits(run, task, predecessors):
    if management_task(task):
        return []
    if not task.get('origin',{}).get('entry'):
        starting=[r for r in run.get('steward_requests',{}).values() if r['operation']=='start' and r['status']!='completed']
        if starting:return [{'reason':'steward_decision','action':r.get('task_id'),'request_id':r['id'],'status':r['status']} for r in starting]
    predecessors = set(predecessors)
    review = task.get('origin', {}).get('steward_review')
    if review:
        predecessors.add(review)
    decisions = [r for r in run.get('steward_requests', {}).values()
                 if r['operation'] == 'decide' and r['arguments'].get('task_id') in predecessors]
    waits = [{'reason': 'steward_decision', 'action': request.get('task_id'),
             'request_id': request['id'], 'source': request['arguments']['task_id'], 'status': request['status']}
            for request in decisions
            if request['status'] != 'completed']
    if review == run['loop_definition'].get('seed',{}).get('id'):
        for request in run.get('steward_requests', {}).values():
            if request['operation']=='start' and request['status']!='completed':
                waits.append({'reason':'steward_decision','source':review,'action':request.get('task_id'),
                              'request_id':request['id'],'status':request['status']})
    elif review and not any(r['arguments']['task_id'] == review for r in decisions):
        waits.append({'reason': 'steward_decision', 'source': review, 'status': 'awaiting_source'})
    return waits


def review_origin(run, origin):
    """Business-created work waits for its creator's completion decision; rule and steward arrangements do not."""
    origin = copy.deepcopy(origin)
    if not run.get('steward') or origin.get('route_id') or origin.get('steward'):
        return origin
    execution = next((e for e in run['executions'] if e['id'] == (origin.get('execution') or origin.get('agent'))), {})
    task = run['tasks'].get(execution.get('task_id'), {})
    node = run['loop_definition']['nodes'].get(task.get('spec', {}).get('node'), {})
    actor = owner_for(run, execution.get('token'))
    if management_task(run['tasks'].get((actor or {}).get('task_id'), {})):
        return origin
    if task and not management_task(task) and (
            node.get('progression') == 'steward' or node.get('progression') != 'rules' and
            not any(r['event'] == 'completed' for r in node.get('routes', []))):
        origin['steward_review'] = task['id']
    return origin


def start_in_run(run, agent, ident, message, arguments, context=None, automatic=False):
    run['steward'] = dict(copy.deepcopy(agent), generation=1, assigned_at=time.time())
    materialize(run)
    request = {'id': ident, 'operation': 'start', 'message': message,
               'arguments': copy.deepcopy(arguments), 'context': copy.deepcopy(context or {}),
               'created_at': time.time(), 'replies': [], 'automatic': automatic}
    run['steward_requests'] = {ident: request}
    add_turn(run, request)
    return request


def read_request(store, ident):
    with store.connection() as db:
        row = db.execute('SELECT run_id,receipt FROM run_requests WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise Invalid('Unknown Run request')
        if row['receipt']:
            if db.execute('SELECT 1 FROM runs WHERE id=?',(row[0],)).fetchone():
                current=store._load(db,row[0])
                if ident in current.get('steward_requests',{}):return receipt(current,current['steward_requests'][ident])
            return json.loads(row['receipt'])
        if not db.execute('SELECT 1 FROM runs WHERE id=?', (row[0],)).fetchone():
            return {'request_id': ident, 'run_id': row[0], 'status': 'deleted'}
        run = store._load(db, row[0])
        return receipt(run, run['steward_requests'][ident])


def submit(store, arguments):
    """The business Run, request ID and first managed turn commit together."""
    ident = arguments['request_id']
    fingerprint = digest(arguments)
    with store.connection() as db:
        prior = db.execute('SELECT run_id,fingerprint FROM run_requests WHERE id=?', (ident,)).fetchone()
        if prior:
            if prior[1] != fingerprint:
                raise Conflict('Request ID belongs to another request')
            return read_request(store, ident)
    operation = arguments.get('operation', 'message')
    if operation in READ_ONLY:
        raise Invalid('Use the read tool directly; reads do not create durable Run requests')
    context = request_context(store, arguments)
    if operation == 'start':
        agent = select_agent(store, arguments['steward_id'])
        with store.connection() as db:
            fields = {k: arguments[k] for k in ('inputs', 'bindings', 'authorization', 'created_by', 'notification_route',
                       'notification_command', 'conversation_id', 'chat_context') if k in arguments}
            run = store.create(arguments['key'], arguments['title'], _db=db, **fields)
            request = start_in_run(run, agent, ident, arguments.get('message', ''), fields, context)
            # A simultaneous identical submission may have committed during package loading.
            prior = db.execute('SELECT run_id,fingerprint FROM run_requests WHERE id=?', (ident,)).fetchone()
            if prior:
                db.rollback()
                if prior[1] != fingerprint:
                    raise Conflict('Request ID belongs to another request')
                return read_request(store, ident)
            db.execute('INSERT INTO run_requests (id,run_id,fingerprint) VALUES (?,?,?)', (ident, run['id'], fingerprint))
            store._save(db, run)
            db.commit()
            return receipt(run, request)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT run_id,fingerprint FROM run_requests WHERE id=?', (ident,)).fetchone()
        if prior:
            db.rollback()
            if prior[1] != fingerprint:
                raise Conflict('Request ID belongs to another request')
            return read_request(store, ident)
        if operation == 'delete_run':
            from loop_anything.runtime.run_library import delete_run
            params = arguments.get('arguments', {})
            from loop_anything.runtime.model import contract
            contract(params, {'type':'object','properties':{'metadata_revision':{'type':'integer'}},'required':['metadata_revision'],'additionalProperties':False}, 'arguments')
            run = store._load(db, arguments['run_id'])
            result = delete_run(store, run['id'], params['metadata_revision'], _db=db)
            answer = {'request_id':ident, 'run_id':run['id'], 'operation':operation, 'status':'completed',
                      'message':arguments.get('message',''), 'result':result, 'context':context}
            db.execute('INSERT INTO run_requests (id,run_id,fingerprint,receipt) VALUES (?,?,?,?)',
                       (ident, run['id'], fingerprint, json.dumps(answer)))
            db.commit()
            return answer
        with store.edit(arguments['run_id'], _db=db) as run:
            if not run.get('steward') and operation not in DIRECT:
                raise Invalid('Assign a steward to this Run before submitting a request')
            request = {'id': ident, 'operation': operation, 'message': arguments.get('message', ''),
                       'arguments': copy.deepcopy(arguments.get('arguments', {})), 'context': context,
                       'created_at': time.time(), 'replies': []}
            if 'authorization' in arguments:
                request['authorization'] = arguments['authorization']
            run.setdefault('steward_requests', {})[ident] = request
            if operation in DIRECT:
                request.update(status='completed', result=direct(store, run, operation, request['arguments']))
            else:
                add_turn(run, request)
            Store.log(run, 'steward_request', request['message'] or operation, detail={'request_id': ident})
            db.execute('INSERT INTO run_requests (id,run_id,fingerprint) VALUES (?,?,?)', (ident, run['id'], fingerprint))
        db.commit()
        return receipt(run, request)


def direct(store, run, operation, arguments):
    """Explicit simple requests share the same persisted receipt without a model call."""
    from loop_anything.interfaces.agent_tasks import RunTools
    tools = RunTools(store, run['id'])
    from loop_anything.runtime.model import contract
    if operation == 'update_run':
        schema = {'type':'object','properties':{'metadata_revision':{'type':'integer'},'title':{'type':'string'},
                  'created_by':{'type':'string'},'archived':{'type':'boolean'}},'required':['metadata_revision'],'additionalProperties':False}
        contract(arguments, schema, 'arguments')
        from loop_anything.runtime.run_library import update_run_in_run
        return update_run_in_run(store, run, **arguments)
    definition = next(d for d in tools.definitions() if d['name'] == 'command')
    contract(arguments, definition['inputSchema'], 'arguments')
    tools.runtime.command_in_run(run, **arguments)
    return {'status': run['status']}


def answer(store, run_id, token, request_id, status, result):
    from loop_anything.runtime.notifications import enqueue
    with store.edit(run_id) as run:
        task = current_owner(run, token)
        request = run.get('steward_requests', {}).get(request_id)
        if not request or request.get('task_id') != task['id']:
            raise Invalid('Answer the request assigned to this management Task')
        if request['status'] in ('completed', 'cancelled'):
            if request['status'] == status and request.get('result') == result:
                return receipt(run, request)
            raise Conflict('Request already resolved')
        request.update(status=status, result=copy.deepcopy(result))
        if status == 'waiting_user':
            task['status'] = 'waiting_user'
            if task.get('execution_id'):
                execution = next(e for e in run['executions'] if e['id'] == task['execution_id'])
                execution['status'] = 'waiting_user'
        Store.log(run, 'steward_reply', 'Steward answered request', task.get('execution_id'),
                  {'request_id': request_id, 'status': status, 'result': result})
        enqueue(store, run, 'steward-reply:' + digest([request_id, status, result]),
                {'message': result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)},
                context=request.get('context'))
        return receipt(run, request)


def completed(store, run, task, outputs):
    ident = task.get('origin', {}).get('request_id')
    if not ident:
        return
    request = run['steward_requests'][ident]
    if request.get('task_id') != task['id'] or request['status'] in ('cancelled', 'completed'):
        return
    result = copy.deepcopy(outputs['decision'])
    request.update(status='completed', result=result)
    from loop_anything.runtime.notifications import enqueue
    enqueue(store, run, 'steward-result:' + ident,
            {'message': result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)},
            context=request.get('context'))


def invalidate(run, task, reason):
    if task['status'] in ACTIVE:
        task['status'] = 'cancelled'
    for execution in run['executions']:
        if execution['task_id'] == task['id']:
            if execution['status'] in ACTIVE:
                execution['status'] = 'cancelled'
            execution['token'] = 'revoked-' + digest([execution['id'], reason])
    run['agent_sessions'] = [owner for owner in run['agent_sessions'] if owner.get('task_id') != task['id']]
    run.get('task_dispositions', {}).pop('task:' + task['id'], None)


def follow_up(store, request_id, reply_id, message, cancel=False):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT run_id FROM run_requests WHERE id=?', (request_id,)).fetchone()
        if row is None:
            raise Invalid('Unknown Run request')
        with store.edit(row[0], _db=db) as run:
            request = run['steward_requests'][request_id]
            prior = next((r for r in request['replies'] if r['id'] == reply_id), None)
            reply = {'id': reply_id, 'message': message, 'cancel': cancel}
            if prior and prior != reply:
                raise Conflict('Reply ID already belongs to another reply')
            if not prior:
                reopen = request['status']=='cancelled' and request['operation']=='decide' and not cancel and run['status'] in ('running','paused')
                if request['status'] in ('completed', 'cancelled') and not reopen:
                    raise Conflict('Request ended; submit a new request')
                task = run['tasks'].get(request.get('task_id'))
                if task:
                    invalidate(run, task, 'request-follow-up:' + reply_id)
                request['replies'].append(reply)
                if cancel:
                    request['status'] = 'cancelled'
                    if request['operation'] == 'start':
                        direct(store, run, 'command', {'action': 'terminate'})
                else:
                    add_turn(run, request)
                Store.log(run, 'steward_request_reply', message, detail={'request_id': request_id, 'reply_id': reply_id})
        db.commit()
        return receipt(run, request)


def assign(store, run_id, agent_id, generation, session=None, _db=None):
    if session:
        from loop_anything.runtime.work import steward_for
        agent=steward_for(session)
    else:agent = select_agent(store, agent_id)
    with store.edit(run_id,_db=_db) as run:
        previous = run.get('steward', {})
        if session:
            if previous.get('session_id'):
                from loop_anything.runtime.work import get
                with store.connection() as db:original=get(db,'session',previous['session_id'])
                if original['state']=='unknown' or (original.get('wake') and original['id']!=session['id']):
                    raise Conflict('Previous session wake is active or unconfirmed')
            from loop_anything.runtime.task_scope import process_active
            if any(process_active(e) for e in run['executions'] if management_task(run['tasks'].get(e['task_id'],{}))):
                raise Conflict('Previous manager process is active or unconfirmed')
        if previous.get('generation', 0) != generation:
            raise Conflict('Steward changed; reread the Run')
        pending = [task for task in run['tasks'].values() if management_task(task) and task['status'] in ACTIVE]
        for task in run['tasks'].values():
            if management_task(task):
                invalidate(run, task, 'steward-replacement')
        run['steward'] = dict(agent, generation=generation + 1, assigned_at=time.time())
        materialize(run)
        for task in pending:
            ident = task['origin'].get('request_id')
            if ident:
                request = run['steward_requests'][ident]
            else:
                ident = run['id'] + '-takeover-' + task['id']
                request = {'id': ident, 'operation': 'continue', 'message': 'Continue the prior decision from saved evidence',
                           'arguments': task['spec']['inputs']['trigger']['literal'], 'created_at': time.time(), 'replies': [], 'automatic': True}
                run.setdefault('steward_requests', {})[ident] = request
            add_turn(run, request, task['spec']['inputs']['trigger']['literal'])
        if not pending:
            ident = run['id'] + '-takeover-' + str(generation + 1)
            request = {'id': ident, 'operation': 'continue', 'message': 'Review this Run and continue authorized work after takeover',
                       'arguments': {}, 'created_at': time.time(), 'replies': [], 'automatic': True}
            run.setdefault('steward_requests', {})[ident] = request
            add_turn(run, request)
        Store.log(run, 'steward_changed', 'Run steward changed', detail={'previous': previous.get('agent_id'),
                  'agent_id': agent_id, 'generation': generation + 1})
        return {k: run.get('steward', {}).get(k) for k in ('agent_id', 'name', 'generation')}
