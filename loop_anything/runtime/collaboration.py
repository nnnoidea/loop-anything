"""Built-in standalone collaboration, using ordinary Timeline tasks and events."""
import copy
import os
import time

from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.store import Store

LOOP_ID = 'platform-collaboration'
EVENT = 'platform-assistance-result'


def ensure_loop(store):
    if getattr(store, '_collaboration_loop_key', None):return store._collaboration_loop_key
    definition = {
        'schema_version': 2, 'id': LOOP_ID, 'version': '1', 'name': '独立协作',
        'requires': ['standalone_collaboration'],
        'description': '平台内置：独立会话的协作、结果等待和原会话续跑。',
        'entry': 'coordinate', 'defaults': {'message': ''},
        'handbook': {'instructions': '推进用户交付的协作任务。先读 communication_status 的主要任务说明选择外援。'
            'request_assistance 提交临时外援；需要结果时登记真实 session，调用 wait_assistance 后 finish。'
            '平台恢复同一 session；完成时 report_task 提交 result，然后 finish。'
            '首次完成 coordinate 时同时提交 settings.objective。'},
        'records': {'result': {'type': 'object'}},
        'nodes': {
            'coordinate': {'label': '推进协作', 'initialize_timeline': True,
                'instructions': '完成 inputs.message；必要时临时求援并挂起，恢复原 session 后继续。',
                'inputs': {'message': {'type': 'string'}}, 'outputs': {'result': {'record_type': 'result'}}},
            'collect': {'label': '等待外援结果', 'instructions': '由平台把外援终态写入关联事件，复用事件等待。',
                'inputs': {}, 'outputs': {'result': {'record_type': 'result'}}}},
        'seed': {'id': 'coordinate', 'node': 'coordinate', 'inputs': {'message': {'run': 'message'}},
                 'outputs': {'result': {'id': 'collaboration.result'}}}, 'plans': {}}
    key = store.publish(definition, {'coordinate': {'kind': 'agent'},
        'collect': {'kind': 'event', 'event': EVENT, 'wait': {'key': '{parameters.request_id}'}}})['key']
    store._collaboration_loop_key = key
    return key


def create(comm, key, title, message, group_id, db, observer=False):
    run = comm.store.create(key, title, {'message': message}, authorization=message, _db=db)
    run['collaboration'] = {'mode': 'results' if observer else 'agent'}
    run['communication_group'] = group_id
    # Completion, pause, restart and event consumption belong to the existing Engine.
    run['settings']['completion_rule'] = {'op': 'eq', 'args': [{'path': 'active_tasks'}, 0]}
    run['settings']['notification_route'] = 'workspace'
    if observer:
        from loop_anything.interfaces.agent_tasks import acquire_in_run, release_in_run, RunTools
        task = run['tasks']['coordinate']
        runtime = RunTools(comm.store, run['id']).runtime
        e = runtime.new_execution(run, task, {'kind': 'agent'}, {'message': message}, {})
        acquire_in_run(run, 'background', e['token'], e['id'])
        runtime.report_in_run(run, e, {'event': 'completed', 'report_id': 'initialize',
            'envelope': {'settings': {'objective': message or title}, 'outputs': {'result': {}}}}, 'agent')
        release_in_run(run, e['token'])
    comm.store._save(db, run)
    return run


def attach(comm, request, key, collaboration_id, db):
    """Atomically record a request and its event-wait Task; no background Agent needed."""
    from loop_anything.runtime.timeline_plan import add_task
    if collaboration_id:
        run = comm.store._load(db, collaboration_id)
        if run.get('identity_read_only'):raise Conflict('Copied collaboration is inspect-only; start a new collaboration')
        if not run.get('collaboration'):
            raise Invalid('collaboration_id must identify a built-in collaboration Run')
        if comm.run_group(run, comm.settings(db)) != request.get('scope_group_id'):
            raise Conflict('Use the collaboration Run group')
        if run['status'] == 'terminated':
            raise Conflict('Collaboration was terminated')
        if run['status'] == 'completed':
            run['status'] = 'running'
            run.pop('completion', None)
            Store.log(run, 'collaboration_followup', 'Continue this collaboration with a new request')
    else:
        run = create(comm, key, request['message'][:100], request['message'],
                     request.get('scope_group_id'), db, observer=True)
    task_id = 'collect-' + request['id']
    add_task(run, {'id': task_id, 'node': 'collect', 'inputs': {},
        'parameters': {'request_id': request['id']},
        'outputs': {'result': {'id': 'result.' + request['id']}}}, {'communication_request': request['id']})
    request['collaboration'] = {'run_id': run['id'], 'task_id': task_id}
    if not request.get('source_reference'):
        request['source_reference'] = dict(request['collaboration'])
    comm.store._save(db, run)


def reconcile(comm):
    from loop_anything.runtime.communication import END
    from loop_anything.runtime.communication_views import summary
    from loop_anything.runtime.notifications import receive_event
    for row in comm.requests():
        link = row.get('collaboration')
        if not link or row.get('mirror') or (row['origin'] != comm.settings()['instance_id'] and not row.get('dispatch_client')):
            continue
        run = comm.store.get(link['run_id'])
        if run['status'] == 'terminated':
            if row['state'] not in END | {'cancelling'}:
                if row.get('dispatch_client'):
                    with comm.transaction() as db:
                        current=comm.get(row['id'],db);current['cancel_requested']=True
                        current['state']='cancelling' if current['state'] in ('starting','running','unknown') else 'cancelled'
                        comm.save(db,current)
                else:comm.control(row['id'], 'cancel',reason='Source collaboration Run was terminated')
            continue
        event_id = 'assistance:' + row['id']
        if row['state'] not in END or any(e['id'] == event_id for e in run['events']):
            continue
        with comm.store.edit(run['id']) as current:
            if current['status'] in ('running', 'paused'):
                receive_event(current, event_id, EVENT, {'result': summary(row)}, row['id'], link['task_id'])


def adopt_pending(comm):
    """Upgrade active legacy standalone work without restarting its executor."""
    from loop_anything.runtime.communication import END
    instance = comm.settings()['instance_id']
    for row in comm.requests():
        if row['origin'] != instance or row.get('mirror') or row.get('collaboration') or row.get('parent_request') or row.get('source', {}).get('run_id') or row['state'] in END:
            continue
        key = ensure_loop(comm.store)
        with comm.transaction() as db:
            current = comm.get(row['id'], db)
            if current.get('collaboration'):continue
            attach(comm, current, key, None, db)
            comm.save(db, current)


def caller_active(execution):
    pid = execution.get('collaboration_caller_pid')
    if not pid:return False
    try:os.kill(pid, 0)
    except ProcessLookupError:return False
    except PermissionError:return True
    return True


def start(comm, arguments):
    """Start a managed coordinator, or adopt a caller with an exact session and PID."""
    from loop_anything.runtime.implementations import validate_implementation
    from loop_anything.runtime.native_sessions import resume_config, bind, active_native
    from loop_anything.interfaces.agent_tasks import acquire_in_run
    if not comm.engine:raise Invalid('Collaboration requires the platform service')
    if comm.identity_conflict:raise Conflict('Resolve the copied workspace or mismatched machine identity before starting collaboration')
    message = arguments['message']
    if not isinstance(message, str) or not message.strip():raise Invalid('Describe the collaboration task')
    config = comm.settings()
    group = arguments.get('group_id') or (config['contexts'].get(arguments['context_id'], {}).get('group_id')
        if arguments.get('context_id') else config.get('default_team'))
    if group and not config['groups'].get(group, {}).get('enabled'):raise Invalid('Choose one joined group')
    caller = arguments.get('caller')
    if bool(caller) == bool(arguments.get('agent_id')):raise Invalid('Choose a local coordinator agent_id or an existing caller session')
    if caller:
        if not isinstance(caller, dict):raise Invalid('caller must be an object')
        if set(caller) != {'implementation', 'native_session', 'process_id'}:raise Invalid('Caller needs implementation, native_session and its current process_id')
        if not isinstance(caller['implementation'],dict) or not isinstance(caller['native_session'],dict):raise Invalid('Caller implementation and native_session must be objects')
        implementation = copy.deepcopy(caller['implementation'])
        validate_implementation(implementation)
        if implementation.get('kind') != 'agent' or not implementation.get('command') or implementation.get('dispatch'):
            raise Invalid('Caller must provide a local Agent CLI implementation')
        resume_config(implementation, caller['native_session'])
        pid = caller['process_id']
        if type(pid) is not int or pid <= 1 or pid == os.getpid():raise Invalid('Supply the actual caller Agent PID on this machine')
        if not caller_active({'collaboration_caller_pid': pid}):raise Invalid('Caller process is not running on this machine')
    else:
        agent = config['agents'].get(arguments['agent_id'])
        if not agent or not agent.get('local', True) or not agent.get('enabled', True):raise Invalid('Choose an enabled local named coordinator')
        implementation = copy.deepcopy(agent['implementation'])
    conversation_id = arguments.get('conversation_id')
    notification_route=arguments.get('notification_route')
    if 'notification_route' in arguments and (not isinstance(notification_route,str) or not notification_route):
        raise Invalid('notification_route must be nonempty')
    if arguments.get('chat_context') and not conversation_id and notification_route is None:
        from loop_anything.runtime.communication_conversations import from_source
        conversation_id = from_source(comm, arguments['chat_context'])['id']
    if conversation_id:
        from loop_anything.runtime.communication_conversations import resolve
        resolve(comm,conversation_id)
    key = ensure_loop(comm.store)
    with comm.transaction() as db:
        if not caller and comm.agent_load(arguments['agent_id'],db)>=agent.get('capacity',1):
            raise Conflict('The named coordinator is busy; reuse its current collaboration or wait for capacity')
        if caller and active_native(db, caller['native_session']['provider'], caller['native_session']['id'], comm.store):
            raise Conflict('This native session is already managed by the platform')
        run = create(comm, key, arguments.get('title') or message[:100], message, group, db)
        if not caller:run['collaboration']['agent_id']=arguments['agent_id']
        run['collaboration']['coordinator_implementation']=copy.deepcopy(implementation)
        run['implementations']['coordinate'] = implementation
        if conversation_id and notification_route is None:
            run['notification_conversation_id'] = conversation_id
            run['settings']['notification_route'] = 'user'
        if notification_route is not None:run['settings']['notification_route'] = notification_route
        result = {'run_id': run['id'], 'task_id': 'coordinate', 'mode': 'managed'}
        if caller:
            task = run['tasks']['coordinate']
            e = comm.engine.timeline_runtime.new_execution(run, task, implementation, {'message': message}, {})
            task['status'] = 'executing'
            e['started_at'] = time.time()
            e['collaboration_caller_pid'] = pid
            bind(run, e, caller['native_session']['provider'], caller['native_session']['id'], 'caller', caller['native_session'].get('cwd'))
            acquire_in_run(run, 'background', e['token'], e['id'])
            result.update(mode='caller', token=e['token'], execution_id=e['id'],
                next='Use source={run_id,task_id} for help; wait_assistance, then finish and exit this Agent process. Resume waits for its exit.')
        comm.store._save(db, run)
    return result
