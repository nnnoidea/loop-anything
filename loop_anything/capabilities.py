"""Service-owned discovery and compatibility, shared by every Agent entry point."""
import hashlib
from pathlib import Path

VERSION = '0.3.2'
API_REVISION = 2
CAPABILITIES = {
    'timeline_storage': ('Persistent Timeline, versioned records, execution history and atomic local writes.', ['read_timeline','read_record','read_run'], 'references/run.md'),
    'task_scheduler': ('Automatic input/dependency readiness, dispatch, parallelism and pause/scope checks.', ['next_tasks','change_settings'], 'references/run.md'),
    'execution_recovery': ('Persisted execution recovery and explicit handling of unknown process state.', ['read_task','command','change_task'], 'references/build-reference.md'),
    'implementation_selection': ('Task/Run/Loop candidate selection, parameter validation and execution snapshots.', ['read_loop','read_task','set_implementation'], 'references/contracts.md'),
    'workspace_inspection': ('Built-in structure, task, result, provenance and execution-history views.', ['read_run','read_loop'], 'references/build-reference.md'),
    'host_service': ('Persistent local host service, supported keep-awake and macOS background management.', [], 'references/platform-capabilities.md'),
    'authoring': ('Edit existing drafts; validate and save a usable local version; export separately.', ['list_loops','read_loop','create_loop','copy_loop','set_loop','put_node','remove_node','set_implementation','put_step','remove_step','connect_steps','validate_loop','publish_loop'], 'references/build.md'),
    'parameter_contracts': ('One parameter contract for tools, UI and runtime; validates types and nested fields without coercion or injecting defaults.', ['read_loop','read_task'], 'references/contracts.md'),
    'conditional_contracts': ('Schema subset with oneOf/anyOf/allOf/not, if/then/else, dependentRequired, const and union types. Unsupported keywords are rejected.', ['read_capabilities','validate_loop','validate_parameters'], 'references/contracts.md'),
    'plans': ('Expand each, collect outputs, omit steps with when/skip, select candidates and bind parameters.', ['put_step','build_plan','read_plans','preview_plan'], 'references/build-reference.md'),
    'event_routes': ('Accepted node events atomically map results into plans; duplicate reports do not recreate tasks.', ['put_node','read_task','report_task','test_loop'], 'references/build-reference.md#事件触发任务'),
    'task_refs': ('Run-unique ref labels resolve task_ref/task_refs and after_refs into concrete record IDs and dependencies, including across routes.', ['put_step','add_task','resolve_refs','preview_plan'], 'references/contracts.md'),
    'record_versions': ('Task output references pin the producing revision; collected records can carry a revisions array for mixed versions.', ['resolve_refs','read_record','build_plan','add_task'], 'references/contracts.md'),
    'task_edits': ('Preview and atomically apply ordered task additions, plan builds and edits with revision and scope checks.', ['edit_tasks','change_task'], 'references/run.md'),
    'lifecycle': ('Explicit report state machines; external submission/observation, retries and configured Agent recovery.', ['set_implementation','report_task','change_task'], 'references/build-reference.md'),
    'waits': ('Timer and external-event Tasks wait persistently; no business process is needed for waiting.', ['set_implementation','send_event'], 'references/notifications.md'),
    'notifications': ('Named local outlets, questions/replies, delivery receipts and visible waiting configuration.', ['notify','read_notification_channels','set_notification_channels','send_event','retry_notification'], 'references/notifications.md'),
    'scopes': ('Task ancestry scopes, concurrent independent branches, acquire/finish, immutable past results.', ['read_timeline','acquire_run','finish','read_task'], 'references/run.md'),
    'run_control': ('Find and start Runs, inspect task/result state, pause/resume with command, and resolve explicit user requests or defer tasks. Hooks in change_settings can pause/notify before, after or at a lifecycle transition.', ['list_runs','start_run','read_run','next_tasks','read_record','complete_task','command','defer_task','resolve_request','change_settings'], 'references/run.md'),
    'termination': ('Run ends only when explicit completion_rule or termination_signal applies. Task completion alone does not end a Run.', ['change_settings','read_timeline'], 'references/run.md'),
    'scenarios': ('Isolated author tests use real Engine scheduling and report transitions with supplied mock events and assertions; never execute commands, Agent models or notification transports.', ['test_loop','preview_plan'], 'references/testing.md'),
    'packages': ('Share definition, implementations and author Skills in one package; enforce required capabilities before installation.', ['export_loop','read_capabilities'], 'references/build-reference.md'),
    'author_skills': ('Read bound author handbook and node Skills from read_loop/read_timeline/read_task; package assets retain relative references.', ['read_loop','read_timeline','read_task','put_asset'], 'references/build-reference.md'),
    'runtime_smoke': ('Explicit Agent startup and isolated lifecycle checks; distinct from static validation and simulated workflow tests.', ['smoke_runtime'], 'references/build.md'),
}


def _source_build():
    root = Path(__file__).parent
    h = hashlib.sha256()
    for file in sorted(p for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.js','.css','.html')):
        h.update(str(file.relative_to(root)).encode());h.update(file.read_bytes())
    return h.hexdigest()[:16]


LOADED_BUILD = _source_build()


def service_info():
    current = _source_build()
    return {'version': VERSION, 'api_revision': API_REVISION, 'build': LOADED_BUILD,
            'source_build': current, 'restart_required': current != LOADED_BUILD,
            'capabilities': list(CAPABILITIES)}


def discover(capability=None):
    from loop_anything.runtime.model import Invalid, SCHEMA_KEYWORDS
    if capability is not None and capability not in CAPABILITIES:
        raise Invalid('Unknown capability: ' + capability)
    from loop_anything.authoring_guidance import authoring_context, mechanism_details, patterns_for
    names = [capability] if capability else CAPABILITIES
    return dict(service_info(), guide={name: {'description': CAPABILITIES[name][0], 'tools': CAPABILITIES[name][1],
                                             'reference': CAPABILITIES[name][2], **mechanism_details(name)} for name in names},
                authoring_context=authoring_context(), patterns=patterns_for(capability),
                schema_keywords=sorted(SCHEMA_KEYWORDS), schema_dialect='Loop JSON Schema subset v2; format is an annotation, not an existence or format validator')


def required_capabilities(bp, implementations=None):
    required = set(bp.get('requires', []))
    if any(n.get('routes') for n in bp.get('nodes', {}).values()):required.add('event_routes')
    if bp.get('scenarios'):required.add('scenarios')
    steps = [s for p in bp.get('plans', {}).values() for s in p.get('steps', {}).values()]
    if any('ref' in s or 'after_refs' in s or any(isinstance(v,dict) and {'task_ref','task_refs'} & v.keys() for v in s.get('inputs',{}).values()) for s in steps):
        required.add('task_refs')
    sources = [v for s in steps + [bp.get('seed', {})] for v in s.get('inputs',{}).values()]
    if any(isinstance(v,dict) and 'revisions' in v for v in sources):required.add('record_versions')
    from loop_anything.runtime.implementations import options
    schemas = list(bp.get('records', {}).values())
    for node in bp.get('nodes', {}).values():
        schemas += list(node.get('inputs', {}).values()) + [node[k] for k in ('parameter_schema','agent_settings_schema') if k in node]
    schemas += [p['parameters'] for p in bp.get('plans',{}).values() if 'parameters' in p]
    schemas += [c['parameter_schema'] for entry in (implementations or {}).values() for c in options(entry).values() if 'parameter_schema' in c]
    old = {'type','title','description','default','format','nonempty','enum','minimum','maximum','minItems','maxItems','uniqueItems','properties','required','additionalProperties','items'}
    def extended(schema):
        if not isinstance(schema,dict):return True
        return 'type' not in schema or schema.get('type') == 'null' or bool(set(schema)-old) or isinstance(schema.get('type'),list) or isinstance(schema.get('additionalProperties'),dict) or any(extended(s) for s in schema.get('properties',{}).values()) or ('items' in schema and extended(schema['items']))
    if any(extended(s) for s in schemas):required.add('conditional_contracts')
    return sorted(required)


def require_supported(required):
    from loop_anything.runtime.model import Invalid
    if not isinstance(required,list) or any(not isinstance(s,str) for s in required):raise Invalid('requires must be an array of capability IDs')
    missing = set(required)-CAPABILITIES.keys()
    if missing:raise Invalid('This service lacks required capabilities: ' + ', '.join(sorted(missing)) + '. Upgrade the running service and read its tool catalog.')
