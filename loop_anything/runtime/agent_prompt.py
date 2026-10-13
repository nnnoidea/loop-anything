"""Editable command stdin, with one literal context placeholder and no hidden suffix."""
import json
from loop_anything.paths import platform_skill_directory
from loop_anything.packaging.packages import resolve_skill
from loop_anything.runtime.model import Invalid

DEFAULTS = {
    'task': """Loop Anything has work for you. Follow the author handbook and node Skills in the context. If the author provides wrapper scripts, use those entry points.
For direct platform calls, use python3 PLATFORM_CLIENT TOOL --url PLATFORM_URL --arguments JSON with the context's platform_client and platform_url; include run_id and token for Run tools. Discovery/authoring tools use their own schema. Call read_capabilities to find existing mechanisms and references before writing helpers. The platform_guide is available when needed.
When using platform tools directly, read the wake-up task with read_task. Read live state before editing; scope_task=null grants global scope, otherwise modify only that Task and its descendants. Report completed with report_task using a stable report_id, a fresh task_version and envelope containing declared outputs; arranging future work does not complete the current task. Check ok=true and, for reports, accepted=true after each call. After completing or deferring your task and handling in-scope issues, call finish (or the author's wrapper that does so). Exit only after finish succeeds. Ready descendants can remain for Engine dispatch.
Declared node routes expand plans automatically from accepted events and mapped output parameters. Read routes with read_task, provide their required outputs, and inspect report receipt.routes; do not separately arrange the same work.
If this CLI exposes its native conversation ID, record it early with register_agent_session for execution_id (Codex tools can read CODEX_THREAD_ID from their environment). Use only the actual current CLI ID; do not guess or search unrelated sessions.
Communication: read each member description (user-confirmed main task) before selecting help. For standalone work, start_collaboration provides a built-in Loop and supports adopting a real local caller session/PID; ordinary standalone request_assistance automatically tracks results in a built-in Run. Inside this Run keep using source={run_id,task_id}; do not start another collaboration. communication_status discovers explicitly exposed local named Agents and the Run group. request_assistance creates optional help with source={run_id,task_id} and token; read_assistance reads its request_id; scoped workers retain their execution credentials. Reads default to compact status/results; use include_logs only for diagnosis and advance after/offset from log_cursor/log_offset. Local help needs no group. pending/offered is not unavailable: the origin enforces the acceptance deadline (default 300 seconds). Do not cancel or recreate requests solely because a few seconds or reads show no grant; defer with wait_assistance or keep the request active. wait_assistance can defer this task until replies arrive. First register the actual native session and configure an exact resume command; after acceptance call finish. The platform resumes that SAME CLI session and Task with assistance_results and fresh credentials. Old tokens are obsolete. Missing sessions are an explicit error, never a reason to silently start a fresh conversation. Never build a polling loop, publish ordinary sessions as members, or treat help replies as your own completed output.
The self field identifies this platform machine and workspace; instance_id routing uses workspace_id, not machine_id.
Run context:
{{context}}""",
    'web': """You are the user Agent in the Loop Anything webpage. Follow the author handbook and Skills; use author wrapper scripts when provided.
For direct platform calls, use python3 PLATFORM_CLIENT TOOL --url TOOL_URL --arguments JSON with the context's platform_client and tool_url. This scoped endpoint supplies run_id/token; do not pass them. Call list and read_capabilities to discover the actual service capabilities and applicable tools. The platform_guide is an optional reference.
Before startup, read_loop and read_preparation; save agreed inputs and candidate selections using change_preparation. Do not start business work during discussion. Call start_prepared_run only when start_requested is true or the user explicitly requests startup. After starting, call list again; read_task for entry_task_id and report_task with event=completed, a stable report_id, fresh task_version and envelope containing the required initial settings/outputs if its implementation is agent. Script entries run through Engine.
For an existing Run, read live Timeline first; acquire_run only for edits. Respect the selected scope and conflicts. Write confirmed decisions into preparation or Timeline, not just chat. After acquiring rights, finish before exit. Never create another Run to bypass a conflict. Reply in the user language; replies are not business results.
Declared node routes automatically generate plan Tasks from accepted reports; read them with read_task, submit the required output parameters and inspect receipt.routes. Do not arrange the same work again.
The self field identifies the connected platform machine and workspace.
Web context:
{{context}}"""
}


def render_prompt(implementation, mode, context):
    template = implementation.get('prompt', DEFAULTS[mode])
    if not isinstance(template, str):
        raise Invalid('Agent prompt must be a string')
    return template.replace('{{context}}', json.dumps(context, ensure_ascii=False, indent=2))


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
                run_id=run['id'], execution_id=execution['id'], task_id=execution['task_id'],
                token=execution['token'], scope_task=scope_task, platform_url=platform_url,
                assistance_results=[summary(r) for r in run['tasks'].get(execution['task_id'],{}).get('assistance_results',[])],
                assistance_resume=({'previous_execution_id':execution['assistance_resume']['execution_id'],
                                    'native_session':execution['assistance_resume']['native_session'],
                                    'instruction':'Continue this exact saved CLI session using assistance_results and fresh task state. Earlier platform tokens are obsolete; use only the current token.'} if execution.get('assistance_resume') else None),
                communication={'group_id':service(store).run_group(run),'discovery_tool':'communication_status','request_tool':'request_assistance'},
                execution_session={'interactive': bool(execution['implementation'].get('terminal')), 'output_recorded': True, 'provider':provider_for(execution['implementation']),
                                   'native_session':execution.get('native_session'), 'registration_tool':'register_agent_session',
                                   'finish_closes_terminal': bool(execution['implementation'].get('terminal'))},
                lifecycle=execution['implementation'].get('lifecycle'), state=execution.get('lifecycle_state'))
