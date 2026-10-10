"""One public request API for local named Agents and NAS group members."""
from loop_anything.interfaces.agent_tasks import object_schema
from loop_anything.runtime.communication import service, clean
from loop_anything.runtime.model import Invalid

T, O, B = {'type': 'string'}, {'type': 'object'}, {'type': 'boolean'}


def definitions():
    common = {'request_id': T, 'token': T}
    rows = [
        ('communication_workspace', 'Owner-only configuration, request history and transport diagnostics. Requires workspace edit access, not a request token.', {}, [], True),
        ('communication_status', 'Read local named Agents and explicitly joined groups. Ordinary CLI sessions are never registered automatically. Select one group before remote requests.', {'group_id': T, 'run_id': T, 'token': T}, [], True),
        ('communication_config', 'Configure local identity, named Agents, groups and Loop/Run bindings. operation=group_notifications binds a local named outlet and makes this machine the group notification sender (cc-connect or another existing adapter). Supply group_id, notification_route, notification_level; binding_id must match the current binding when replacing it; enabled=false disables group external notices. Public routing is shared over NAS; commands/credentials stay on this machine. Does not send a message or start an Agent.', {'operation': T, 'regenerate':B, 'revision': {'type':'integer'}, 'name': T, 'agent_id': T, 'agent': O, 'path': T, 'create': B, 'group_id': T, 'context_id': T, 'loop_key': T, 'run_id': T,'notification_route':T,'notification_level':{'type':'string','enum':['attention','key','detailed']},'binding_id':T,'enabled':B}, ['operation'], False),
        ('request_assistance', 'Request an explicitly exposed local named Agent or a member of one selected group. No Loop is needed. source={run_id,task_id} requires its current token and restricts group to the Run binding. Returns a private request_token for later reads/control. Session is independent of agent_id. Omit notification_route to inherit the selected group’s designated sender/outlet; without a binding use the Run default or workspace. An explicit route overrides the group for this request.', {'location': {'type':'string','enum':['local','group']}, 'agent_id': T, 'instance_id':T, 'group_id': T, 'capability': T, 'context_id': T, 'message': T, 'context': O, 'source': O, 'token': T, 'result_schema': O, 'session': O, 'wait_seconds': {'type':'number'}, 'notification_route': T, 'notification_level': {'type':'string','enum':['attention','key','detailed']}}, ['message','location'], False),
        ('read_assistance', 'Read one request, structured results, progress and logs. Does not start or resume an Agent. token is the private request_token returned on creation.', dict(common, after={'type':'integer','minimum':0}), ['request_id'], True),
        ('control_assistance', 'Cancel, send interactive input, follow up (explicit resume or new session), or confirm a stopped unknown execution. Cancelling is not proof the process stopped.', dict(common, action=T, message=T, resume=B, confirmed_stopped=B, notification_id=T), ['request_id','action'], False),
        ('wait_assistance', 'Defer this platform-managed Agent task until its assistance requests end or the deadline expires. Record the actual native session first and configure an exact resume command. After acceptance call finish; remote nodes also complete their execution request. The platform resumes the SAME CLI session and Task with assistance results and fresh credentials, on the original executor. Missing/unavailable sessions never fall back to a new conversation.', {'run_id':T,'token':T,'task_id':T,'request_ids':{'type':'array','items':T},'seconds':{'type':'number'}}, ['run_id','token','task_id','request_ids'], False),
        ('communication_execute', 'Execution-only scoped bridge. Requires the worker token from the request prompt. Supports progress, complete, native_session, read_context, local/group assistance, source_call and source_result. read_context grants no Run writes.', dict(common, tool=T, arguments=O), ['request_id','token','tool','arguments'], False),
    ]
    return [{'name': n, 'description': d, 'inputSchema': object_schema(p, required), 'annotations': {'readOnlyHint': ro}}
            for n, d, p, required, ro in rows]


def call(store, name, a):
    comm = service(store)
    if name == 'communication_workspace':
        import json
        with store.connection() as db:deliveries=[clean(json.loads(r[0])) for r in db.execute('SELECT document FROM communication_deliveries ORDER BY rowid DESC')]
        return {'configuration':comm.settings(),'directory':comm.directory(),'requests':[clean(r) for r in comm.requests()],'notification_deliveries':deliveries, 'transport_error':getattr(comm,'transport_error',None),'identity_conflict':comm.identity_conflict}
    if name == 'communication_status':
        if a.get('run_id'):
            a['group_id'] = comm.run_group(store.get(a['run_id']))
        result = comm.directory(a.get('group_id'))
        if a.get('run_id'):
            result['agents'] = [x for x in result['agents'] if x['location']=='local' or x.get('group_id')==a.get('group_id')]
            result['groups'] = [x for x in result['groups'] if x['id']==a.get('group_id')]
            result['loops'] = [x for x in result['loops'] if x['group_id']==a.get('group_id')]
        return result
    if name == 'communication_config':
        return comm.config(**a)
    if name == 'request_assistance':
        return comm.request(a)
    if name == 'read_assistance':
        return comm.read(a['request_id'], a.get('after', 0))
    if name == 'control_assistance':
        return comm.control(a['request_id'], a['action'], **{k:v for k,v in a.items() if k not in ('request_id','action','token')})
    if name == 'wait_assistance':
        return comm.wait_assistance(**a)
    if name == 'communication_execute':
        return comm.worker_call(a['request_id'], a['token'], a['tool'], a['arguments'])
    raise Invalid('Unknown communication tool')
