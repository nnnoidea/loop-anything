"""One public request API for local named Agents and NAS group members."""
from loop_anything.interfaces.agent_tasks import object_schema
from loop_anything.runtime.communication import service, clean, request_summary
from loop_anything.runtime.model import Invalid

T, O, B = {'type': 'string'}, {'type': 'object'}, {'type': 'boolean'}


def definitions():
    common = {'request_id': T, 'token': T}
    rows = [
        ('communication_workspace', 'Owner-only configuration, request history and transport diagnostics. discover=true lists groups in configured shared spaces without joining or exposing Agents. group_id returns transferable join instructions without CLI commands or credentials. Requires workspace edit access, not a request token.', {'discover':B,'group_id':T}, [], True),
        ('communication_status', 'Read local named Agents and explicitly joined groups. Ordinary CLI sessions are never registered automatically. Select one group before remote requests.', {'group_id': T, 'run_id': T, 'token': T}, [], True),
        ('communication_config', 'Configure local identity, named Agents, groups and Loop/Run bindings. agent.notification_route maps that Agent to a local Bot outlet. operation=conversation registers captured conversation metadata and a local notification_command, returning conversation_id; owner-only, never accepted from a remote worker. operation=space saves an existing mounted NAS root and checks local read/write; it never joins groups. operation=group with space_id and create=true creates a named group; joining requires space_id, relative_path and the discovered group_id. Agent groups must be explicitly selected after joining; commands stay local. operation=group_notifications binds only this machine local named outlet in the group without replacing other machines (cc-connect or another existing adapter). Supply group_id, notification_route, notification_level; binding_id must match this machine current binding when replacing it; enabled=false disables only this machine outlet. Default group notices choose action machine, then direct request origin, otherwise record skipped; no fallback on uncertain delivery. Public routing is shared over NAS; commands/credentials stay on this machine. Does not send a message or start an Agent.', {'operation': T, 'conversation': O, 'notification_command': {'type':'array','items':T}, 'regenerate':B, 'revision': {'type':'integer'}, 'name': T, 'description':T, 'space_id':T, 'relative_path':T, 'agent_id': T, 'agent': O, 'path': T, 'create': B, 'group_id': T, 'context_id': T, 'loop_key': T, 'run_id': T,'notification_route':T,'notification_level':{'type':'string','enum':['attention','key','detailed']},'binding_id':T,'enabled':B}, ['operation'], False),
        ('request_assistance', 'Request an explicitly exposed local named Agent or a member of one selected group. No Loop is needed. source={run_id,task_id} requires its current token and restricts group to the Run binding. context is a JSON object with arbitrary nested business data; context.task may be text, null, an array or an object. Returns a private request_token for later reads/control. Session is independent of agent_id. Pass conversation_id from the captured chat (Skill client does this automatically) to reply in the original chat/thread; group execution prefers the named Agent Bot and falls back to the entry Bot only before sending. Omit notification_route and conversation_id to use group priority: action machine outlet, then this request direct origin, otherwise no external notice. Outside a group use the Run default or workspace. An explicit route overrides the group for this request.', {'location': {'type':'string','enum':['local','group']}, 'agent_id': T, 'instance_id':T, 'group_id': T, 'capability': T, 'context_id': T, 'conversation_id': T, 'message': T, 'context': O, 'source': O, 'token': T, 'result_schema': O, 'session': O, 'wait_seconds': {'type':'number'}, 'notification_route': T, 'notification_level': {'type':'string','enum':['attention','key','detailed']}}, ['message','location'], False),
        ('read_assistance', 'Read compact request status and structured results by default, without logs, context or full history. For diagnosis set include_details=true; for output set include_logs=true with max_chars (default 4000, max 16000). Continue with after=log_cursor and offset=log_offset while log_more=true; do not replay old pages. Does not start or resume an Agent. token is the private request_token returned on creation.', dict(common, after={'type':'integer','minimum':0}, offset={'type':'integer','minimum':0}, max_chars={'type':'integer','minimum':1,'maximum':16000}, include_logs=B, include_details=B), ['request_id'], True),
        ('control_assistance', 'Cancel, send interactive input, follow up (explicit resume or new session), or confirm a stopped unknown execution. Cancelling is not proof the process stopped.', dict(common, action=T, message=T, resume=B, confirmed_stopped=B, notification_id=T), ['request_id','action'], False),
        ('wait_assistance', 'Defer this platform-managed Agent task until its assistance requests end or the deadline expires. Record the actual native session first and configure an exact resume command. After acceptance call finish; remote nodes also complete their execution request. The platform resumes the SAME CLI session and Task with assistance results and fresh credentials, on the original executor. Missing/unavailable sessions never fall back to a new conversation.', {'run_id':T,'token':T,'task_id':T,'request_ids':{'type':'array','items':T},'seconds':{'type':'number'}}, ['run_id','token','task_id','request_ids'], False),
        ('communication_execute', 'Execution-only scoped bridge. Requires the worker token from the request prompt. Supports progress, complete, native_session, read_context, local/group assistance, source_call and source_result. read_context grants no Run writes.', dict(common, tool=T, arguments=O), ['request_id','token','tool','arguments'], False),
    ]
    return [{'name': n, 'description': d, 'inputSchema': object_schema(p, required), 'annotations': {'readOnlyHint': ro}}
            for n, d, p, required, ro in rows]


def call(store, name, a):
    comm = service(store)
    if name == 'communication_workspace':
        from loop_anything.runtime.communication_spaces import discover,join_instructions
        if a.get('group_id'):return join_instructions(comm,a['group_id'])
        import json
        with store.connection() as db:deliveries=[clean(json.loads(r[0])) for r in db.execute('SELECT document FROM communication_deliveries ORDER BY rowid DESC')]
        return {'configuration':comm.settings(),'directory':comm.directory(),'requests':[request_summary(r) for r in comm.requests()],'notification_deliveries':deliveries, 'transport_error':getattr(comm,'transport_error',None),'identity_conflict':comm.identity_conflict,**({'shared_spaces':discover(comm)} if a.get('discover') else {})}
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
        return comm.read(a['request_id'], **{k:a[k] for k in ('after','include_logs','include_details','offset','max_chars') if k in a})
    if name == 'control_assistance':
        return comm.control(a['request_id'], a['action'], **{k:v for k,v in a.items() if k not in ('request_id','action','token')})
    if name == 'wait_assistance':
        return comm.wait_assistance(**a)
    if name == 'communication_execute':
        return comm.worker_call(a['request_id'], a['token'], a['tool'], a['arguments'])
    raise Invalid('Unknown communication tool')
