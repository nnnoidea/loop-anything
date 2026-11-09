"""Editable command stdin, with one literal context placeholder and no hidden suffix."""
import json
from pathlib import Path
from loop_anything.paths import platform_skill_directory
from loop_anything.packaging.packages import resolve_skill
from loop_anything.runtime.model import Invalid

DEFAULTS = {
    'task': """Loop Anything has work for you. This session handles its current Run tasks only; do not use it to edit the reusable Loop definition. Loop construction belongs to a separate external Agent or source-file editing. Follow the author handbook and node Skills in the context. If the author provides wrapper scripts, use those entry points.
For direct platform calls, use python3 PLATFORM_CLIENT TOOL --url PLATFORM_URL --arguments JSON with the context's platform_client and platform_url; include run_id and token for Run tools. Discovery tools use their own schema. Call read_capabilities to find existing mechanisms and references before writing helpers. The platform_guide is available when needed.
When using platform tools directly, read the wake-up task with read_task. Read relevant state before deciding; managed reads record basis automatically. Stateless edits must pass basis from the decision read. Thinking does not reserve Timeline; commit conflicts return changed fields and require reconsideration, not blindly refreshed versions. scope_task=null grants global permission, otherwise modify only that Task and descendants. Report completed with report_task using a stable report_id, the task_version from that decision read and envelope containing declared outputs; arranging future work does not complete the current task. Check ok=true and, for reports, accepted=true after each call. After completing or deferring your task and handling in-scope issues, call finish (or the author's wrapper that does so). Exit only after finish succeeds. Ready descendants can remain for Engine dispatch.
Declared node routes expand plans automatically from accepted events and mapped output parameters. Read routes with read_task, provide their required outputs, and inspect report receipt.routes; do not separately arrange the same work.
If this CLI exposes its native conversation ID, record it early with register_agent_session for execution_id (Codex tools can read CODEX_THREAD_ID from their environment). Use only the actual current CLI ID; do not guess or search unrelated sessions.
Communication uses the independent dispatch_skill and its shared publishing protocol; managed nodes retain this scoped platform entry for Run association. Read each member description (user-confirmed main task) before selecting help. For standalone work, start_collaboration provides a built-in Loop and supports adopting a real local caller session/PID; ordinary standalone request_assistance automatically tracks results in a built-in Run. Inside this Run keep using source={run_id,task_id}; do not start another collaboration. communication_status discovers explicitly exposed local named Agents and the Run group. request_assistance creates optional help with source={run_id,task_id} and token; read_assistance reads its request_id; scoped workers retain their execution credentials. Reads default to compact status/results; use include_logs only for diagnosis and advance after/offset from log_cursor/log_offset. Local help needs no group. pending/offered is not unavailable: the origin enforces the acceptance deadline (default 300 seconds). Do not cancel or recreate requests solely because a few seconds or reads show no grant; defer with wait_assistance or keep the request active. wait_assistance can defer this task until replies arrive. First register the actual native session and configure an exact resume command; after acceptance call finish. The platform resumes that SAME CLI session and Task with assistance_results and fresh credentials. Old tokens are obsolete. Missing sessions are an explicit error, never a reason to silently start a fresh conversation. Never build a polling loop, publish ordinary sessions as members, or treat help replies as your own completed output.
The self field identifies this platform machine and workspace; instance_id routing uses workspace_id, not machine_id.
For files and large answers, use NAS paths only when both parties have shared access, with purpose and shared-relative paths when mounts differ. Otherwise use Feishu attachments or accessible cloud links; ordinary replies can be submitted inline. Preserve complete artifacts. Feishu native attachments are optional when shared access is unavailable or a cloud copy is requested; see dispatch_skill references/artifacts.md.
Run context:
{{context}}""",

}


def render_prompt(implementation, mode, context):
    template = implementation.get('prompt', DEFAULTS[mode])
    if not isinstance(template, str):
        raise Invalid('Agent prompt must be a string')
    return template.replace('{{context}}', json.dumps(context, ensure_ascii=False, indent=2))


def process_prompt(config, context, template=None, indent=None):
    """Carry structured context until the execution machine resolves platform references."""
    config['_prompt_context']=context
    config['_prompt_template']=template
    config['_prompt_indent']=indent
    encoded=json.dumps(context,ensure_ascii=False,indent=indent)
    return encoded if template is None else template.replace('{{context}}',encoded)


def receiver_context(value, team_root=None, mounted_root=None):
    import copy
    from loop_anything.runtime.tool_client import module
    value=copy.deepcopy(value);root=platform_skill_directory()
    helpers={'platform_client':root/'scripts/call.py','report_client':root/'scripts/report.py',
             'client':root/'scripts/communication.py','dispatch_skill':root.parent/'loop-anything-dispatch/SKILL.md'}
    for key,path in helpers.items():
        if key in value:value[key]=str(path)
    if 'platform_guide' in value:
        old=Path(value['platform_guide'])
        value['platform_guide']=str(root/'references'/old.name)
    if team_root and mounted_root:
        mount=lambda path:module('platform_transport').mount_path(path,[team_root],mounted_root)
        if 'resource_root' in value:value['resource_root']=mount(value['resource_root'])
        for key in ('platform_url','execution_url'):
            if isinstance(value.get(key),str) and value[key].startswith('nas://'):
                url,sep,scope=value[key][6:].partition('#');value[key]='nas://'+mount(url)+sep+scope
        for skill in [value.get('handbook'),*(value.get('skills') or [])]:
            if isinstance(skill,dict) and 'resolved_path' in skill:skill['resolved_path']=mount(skill['resolved_path'])
    return value


def mask_prompt(text, *tokens):
    for token in tokens:
        if token:
            text = text.replace(token, '[REDACTED]')
    return text


def author_context(store, key, definition, node_id=None):
    def skill(value):
        return resolve_skill(store.filename, key, value) if key else value
    root = platform_skill_directory()
    from loop_anything.capabilities import service_info
    from loop_anything.authoring_guidance import authoring_context
    from loop_anything.runtime.communication import service
    context = {'self': service(store).self_info(), 'platform': service_info(), 'platform_responsibilities': authoring_context(), 'capability_tool': 'read_capabilities', 'loop_key': key, 'platform_client': str(root / 'scripts/call.py'),
               'platform_guide': str(root / 'references/run.md'),
               'dispatch_skill': str(root.parent / 'loop-anything-dispatch/SKILL.md'),
               'handbook': skill(definition.get('handbook', {}))}
    if node_id:
        node = definition['nodes'][node_id]
        context.update(node_id=node_id, instructions=node['instructions'],
                       skills=[skill(s) for s in node.get('skills', [])], routes=node.get('routes', []))
    return context


def task_context(store, run, execution, platform_url, scope_task):
    from loop_anything.runtime.communication_views import summary
    from loop_anything.runtime.native_sessions import provider_for
    from loop_anything.runtime.communication import service
    return dict(author_context(store, run['loop_key'], run['loop_definition'], execution['node']),
                run_id=run['id'], created_by=run.get('created_by',''), execution_id=execution['id'], task_id=execution['task_id'],
                token=execution['token'], scope_task=scope_task, platform_url=platform_url,
                execution_executor=execution['implementation'].get('executor'),
                flow_trigger=run['tasks'][execution['task_id']].get('origin', {}).get('flow_agent'),
                assistance_results=[summary(r) for r in run['tasks'].get(execution['task_id'],{}).get('assistance_results',[])],
                assistance_resume=({'previous_execution_id':execution['assistance_resume']['execution_id'],
                                    'native_session':execution['assistance_resume']['native_session'],
                                    'instruction':'Continue this exact saved CLI session using assistance_results and fresh task state. Earlier platform tokens are obsolete; use only the current token.'} if execution.get('assistance_resume') else None),
                communication={'group_id':service(store).run_group(run),'discovery_tool':'communication_status','request_tool':'request_assistance'},
                execution_session={'interactive': bool(execution['implementation'].get('terminal')), 'output_recorded': True,
                                   'output_retention':'Live output; successful native-session executions retain session identity instead of duplicate transcripts.',
                                   'provider':provider_for(execution['implementation']),
                                   'native_session':execution.get('native_session'), 'registration_tool':'register_agent_session',
                                   'finish_closes_terminal': bool(execution['implementation'].get('terminal'))},
                lifecycle=execution['implementation'].get('lifecycle'), state=execution.get('lifecycle_state'))
