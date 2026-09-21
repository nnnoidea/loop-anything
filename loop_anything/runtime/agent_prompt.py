"""Editable command stdin, with one literal context placeholder and no hidden suffix."""
import json
from loop_anything.paths import platform_skill_directory
from loop_anything.packaging.packages import resolve_skill
from loop_anything.runtime.model import Invalid

DEFAULTS = {
    'task': """Loop Anything has work for you. Follow the author handbook and node Skills in the context. If the author provides wrapper scripts, use those entry points.
For direct platform calls, use python3 PLATFORM_CLIENT TOOL --url PLATFORM_URL --arguments JSON with the context's platform_client and platform_url; include run_id and token. The platform_guide is available when needed.
When using platform tools directly, read the wake-up task with read_task. Read live state before editing; scope_task=null grants global scope, otherwise modify only that Task and its descendants. Report completed with report_task using a stable report_id, a fresh task_version and envelope containing declared outputs; arranging future work does not complete the current task. Check ok=true and, for reports, accepted=true after each call. After completing or deferring your task and handling in-scope issues, call finish (or the author's wrapper that does so). Exit only after finish succeeds. Ready descendants can remain for Engine dispatch.
Run context:
{{context}}""",
    'web': """You are the user Agent in the Loop Anything webpage. Follow the author handbook and Skills; use author wrapper scripts when provided.
For direct platform calls, use python3 PLATFORM_CLIENT TOOL --url TOOL_URL --arguments JSON with the context's platform_client and tool_url. This scoped endpoint supplies run_id/token; do not pass them. Call list to discover available tools. The platform_guide is an optional reference.
Before startup, read_loop and read_preparation; save agreed inputs and candidate selections using change_preparation. Do not start business work during discussion. Call start_prepared_run only when start_requested is true or the user explicitly requests startup. After starting, call list again; read_task for entry_task_id and report_task with event=completed, a stable report_id, fresh task_version and envelope containing the required initial settings/outputs if its implementation is agent. Script entries run through Engine.
For an existing Run, read live Timeline first; acquire_run only for edits. Respect the selected scope and conflicts. Write confirmed decisions into preparation or Timeline, not just chat. After acquiring rights, finish before exit. Never create another Run to bypass a conflict. Reply in the user language; replies are not business results.
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
    context = {'loop_key': key, 'platform_client': str(root / 'scripts/call.py'),
               'platform_guide': str(root / 'references/run.md'),
               'handbook': skill(definition.get('handbook', {}))}
    if node_id:
        node = definition['nodes'][node_id]
        context.update(node_id=node_id, instructions=node['instructions'],
                       skills=[skill(s) for s in node.get('skills', [])])
    return context


def task_context(store, run, execution, platform_url, scope_task):
    return dict(author_context(store, run['loop_key'], run['loop_definition'], execution['node']),
                run_id=run['id'], execution_id=execution['id'], task_id=execution['task_id'],
                token=execution['token'], scope_task=scope_task, platform_url=platform_url,
                lifecycle=execution['implementation'].get('lifecycle'), state=execution.get('lifecycle_state'))
