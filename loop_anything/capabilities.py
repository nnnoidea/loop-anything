"""Service-owned discovery and compatibility, shared by every Agent entry point."""
import hashlib
from pathlib import Path

VERSION = '0.6.11'
API_REVISION = 3
CAPABILITIES = {
    'run_library': ('Human-attributed Run library with server-side summary pagination, person counts, creation/activity date filters, root/child browsing and workflow/collaboration filtering. Local CLI profile supplies created_by; child Runs inherit it. update_run edits title/attribution/archive using independent metadata_revision, including ended Runs. delete_run requires ended work and retains native sessions/external artifacts. archive_loop hides a version/draft without breaking history; delete_loop preserves referenced versions. No login or person-based access control.', ['list_runs','start_run','update_run','delete_run','list_loops','archive_loop','delete_loop'], 'references/run.md'),
    'loop_calls': ('A kind=loop node calls an installed Loop on this service using loop={key,inputs,result}. Existing parameter expansion maps inputs and the child records/settings/inputs/run_id into a validated report envelope. The child starts through its own entry implementation; the parent waits without a process or Agent. Creation and parent linkage are atomic; the same Task always reuses its child across service recovery and retries. A new invocation needs a new Task. Parent/child pause and termination are independent; ancestor recursion is unsupported.', ['set_implementation','list_loops','read_task','read_run','read_record','command'], 'references/loop-calls.md'),
    'team_service': ('One service owns shared Loop/Run state on NAS. Unified clients operate the service over a durable nas:///mounted/team/path mailbox or HTTP and optionally receive work or run personal jobs. Install with --role client; client tool and client local reuse existing implementations. Operations-only clients can still use portable Skills without installing the runtime. Clients never open the team database. NAS waiting timeouts retain request IDs; unknown interrupted mutations are not replayed. Optional web UI is independent of scheduling.', ['list_loops','list_runs','read_capabilities'], 'references/team-runtime.md'),
    'headless_execution': ('The unified client can explicitly start a receiver through client local and run Agent/command/external implementations on another machine; receiving is a client capability, not a separate installation role. Select implementation.executor from list_executors; the service keeps Timeline ownership. Remote waiting uses durable state without occupying service command workers. Durable execution IDs prevent replay; service restart, session resume and terminal interaction retain the original call/executor. delivering means execution ended but complete result delivery is pending: automatic chunk retransmission never reruns the command. Known cancellation is applied before launch. Only explicit path fields/platform references are remapped; business text remains verbatim. No automatic reassignment on silence.', ['list_executors','read_executor_call','set_implementation','confirm_executor_stopped','executor_poll','executor_report'], 'references/team-runtime.md'),
    'local_scheduling': ('The client local CLI supports standalone interval/one-shot time scheduling, script conditions, commands and Agent CLI execution, without a platform service or Run. Registrations retain history across machines; list/register/runtime restart never start old tasks. Explicit client local start selects IDs; the older local command remains compatible. Persisted action identity survives scheduler death; show exposes the old execution, and confirm-stopped requires its exact ID and verified stop without starting anything. Same scheduler and process/transition machinery serves personal tasks and receivers.', [], 'references/team-runtime.md'),
    'flow_agent': ('Built-in flow decisions: set_loop(flow_agent={kind:agent,command/...}) configures execution only. Explicit node routes {id,event,flow_agent:true,when?} wake the controller; no default advancement mode, extra business node or plan. It reads the full Loop handbook and trigger, uses existing task tools with global scope and commit-time conflict checks, and writes a full decision result. read_task exposes flow_decisions, flow_trigger and route_receipts; sessions, help waiting/resume and retries reuse normal execution. Without command/dispatch, the decision remains unclaimed until acquire_run(run_id,task_id). Related decision/route reads participate in commit-time checks. Legacy authored flow nodes remain supported.', ['set_loop','put_node','acquire_run','read_timeline','read_task','build_plan','edit_tasks','report_task','finish','test_loop'], 'references/flow-agent.md'),
    'builtin_flow_agent': ('Compatibility requirement for built-in flow_agent configuration and explicit flow_agent event routes; see flow_agent for the authoring contract. No implicit trigger or default advancement policy.', ['set_loop','put_node','read_task'], 'references/flow-agent.md'),
    'loop_configuration': ('Separate recipient execution configuration from the shared workflow. Every exported package contains config.example.json. Installed versions have a writable loop-configs/<key>.json; read/set_loop_config discovers and updates it with revision checks, without availability probes. Inputs, candidate choices/execution settings and the existing flow Agent are applied to new Run snapshots; exports and existing Runs keep their original values.', ['read_loop_config','set_loop_config','read_loop','put_asset','start_run'], 'references/loop-config.md'),
    'flow_diagram': ('Agent-authored business overview: bundled Answer me with HTML renderer and template in the platform Skill. render_flow.py renders locally and optionally saves docs/flow.md + docs/flow.html through put_asset. The editor displays the saved page with a full node-details sidebar: bundled flow nodes match exact unique labels/IDs; custom HTML/SVG uses data-loop-node. No inferred business routes, background Agent, publish or Run start. Node.js 20+ is needed only for generation.', ['read_loop','put_asset'], 'references/flow-diagram.md'),
    'machine_identity': ('On-demand local Agent registration discovery through communication_workspace(registered_agents=true), across known workspaces, without starting them or contacting team media. Compare names/tasks before registration and ask about similar profiles; explicit duplicates are allowed and no current-chat named identity is needed. Lazy persistent full-UUID machine identity outside workspace databases. communication_status.self and wake-up context self expose machine_id, machine_name and workspace_id of the connected platform. instance_id remains the workspace routing alias. Moves and renames preserve identity; copied workspaces require explicit new identity and retain old Runs as inspect-only history.', ['communication_status','communication_workspace','communication_config'], 'references/communication.md'),
    'cc_connect': ('One machine-level bridge connection shared by local workspaces; discover configured Bots without credentials, map named Agents directly with notification_bot={project,platform}, or use cc_connect Bot references in fixed-destination outlets. No per-Bot wrapper command. No guessed configuration path. Discovery is not proof of live Bot availability.', ['read_cc_connect','configure_cc_connect','communication_config','read_notification_channels','set_notification_channels'], 'references/cc-connect.md'),
    'conversation_notifications': ('The Skill client only carries originating Feishu/Lark metadata; the platform persists provenance and selects senders, and the sending adapter preserves the original session, reuses saved thread roots and calls cc-connect send directly. No Bot credential access, Feishu API lookup, membership/permission/config preflight or per-send catalog checks. Missing roots and unfamiliar session formats are passed to the bridge; Agents must not build a second probe or copy bridge secrets. Notification setup failures do not block business requests. Private replies use the entry Bot; group execution prefers the named Agent Bot in the original thread, with entry fallback only after a confirmed pre-send rejection. Nested assistance inherits provenance; explicit routes override.', ['communication_config','request_assistance','start_run','read_assistance'], 'references/cc-connect.md'),
    'group_notification_priority': ('Group notices prefer the action machine outlet, then this request direct origin; with neither, record a skipped external notice. Each notice fixes its sender; unknown delivery never switches machines.', ['communication_config','communication_status','read_assistance'], 'references/communication.md'),
    'communication_context': ('Compact status and full results by default. Base keeps logs on the executor; opt-in reads return bounded pages or logs_pending. Store ordinary answers directly; use NAS file references only when shared access is known; Feishu native attachments are optional for cloud copies, with automatic fallback only for oversized inline messages. Referenced files are never automatically read, uploaded or deleted. Confirmed Base messages move to a cloud history bucket; results remain readable without automatic deletion or new client result mirrors. Successful native-session executions retain session identity instead of duplicate transcripts. Follow-ups and assistance resumes omit embedded request archives.', ['read_assistance','request_assistance','control_assistance'], 'references/communication.md'),
    'standalone_collaboration': ('Built-in collaboration Loop: one Run per standalone task, event-backed result collection and same-Run follow-ups. start_collaboration launches a local named coordinator or adopts a real local caller session/PID; wait_assistance resumes the exact session only after the caller exits. No caller metadata means result tracking/notification only.', ['start_collaboration','request_assistance','read_assistance','wait_assistance','communication_status'], 'references/communication.md'),
    'confirmed_agent_directory': ('Group-exposed Agents require a user-confirmed main task description and group scope. Ask the user before task_confirmed=true; never infer confirmation. Old unconfirmed members cannot accept new group work.', ['communication_config','communication_status'], 'references/communication.md'),
    'assistance_session_resume': ('Waiting Agent tasks resume their exact native CLI session with assistance results and fresh credentials; remote work stays on the original instance/Agent and never silently starts a new conversation.', ['wait_assistance','register_agent_session','communication_execute','read_assistance'], 'references/communication.md'),
    'group_notifications': ('Communication group notification bindings, per-machine outlets and one selected delivery machine, existing cc-connect outlets, durable team-transport forwarding and delivery receipts.', ['communication_status','communication_config','read_notification_channels','set_notification_channels','read_assistance','control_assistance'], 'references/communication.md'),
    'agent_communication': ('Independent loop-anything-dispatch Skill publishes named-Agent work without a caller platform. Names and explicit IDs resolve against the published member directory. The standalone Skill wait command polls in script, returns results or timeout without cancelling requests, and needs no caller platform. Base provides readable directory/request/result views. Base transport uses native lark-cli Base v3 commands (verified with 1.0.98), exact server-side filters and native attachments; upgrade old CLI versions instead of granting bitable:app or falling back to legacy APIs. No permission preflight. All dispatch uses one explicit-target protocol; receivers persist and execute without a second source grant. NAS and Feishu Base share request/result semantics. communication_config(operation=team,link=...) retains team connections: enabled Base takes priority over NAS regardless of join order. Errors never trigger cross-media resubmission. Existing Runs/requests, retries and follow-ups retain their original connection; internal tables are managed automatically. Receiving platforms retain execution dedup, source-Run scope, event waiting, exact native-session resume, notifications and legacy in-flight claim/grant handling. Ordinary sessions are not automatically exposed.', ['communication_workspace','communication_status','communication_config','request_assistance','read_assistance','control_assistance','wait_assistance','communication_execute'], 'references/communication.md'),
    'timeline_storage': ('Persistent Timeline, versioned records, execution history and atomic service-owned writes.', ['read_timeline','read_record','read_run'], 'references/run.md'),
    'task_scheduler': ('Automatic input/dependency readiness, dispatch, parallelism and pause/scope checks.', ['next_tasks','change_settings'], 'references/run.md'),
    'execution_recovery': ('Persisted execution recovery and explicit handling of unknown process state.', ['read_task','command','change_task'], 'references/build-reference.md'),
    'implementation_selection': ('Task/Run/Loop candidate selection, parameter validation and execution snapshots.', ['read_loop','read_task','set_implementation'], 'references/contracts.md'),
    'workspace_inspection': ('Built-in structure, task, result, provenance and execution-history views.', ['read_run','read_loop'], 'references/build-reference.md'),
    'agent_resume': ('Task result buttons and exact native CLI session continuation, fresh scoped credentials, immutable historical results; explicit user resume action.', ['register_agent_session','read_task','set_implementation','read_execution_session','control_execution_session'], 'references/terminal.md'),
    'agent_terminal': ('Live Agent output per execution; successful resumable native sessions keep their identity instead of duplicate transcripts, optional interactive CLI terminal on macOS/Linux, same process and task ownership; finish closes an interactive session.', ['set_implementation','read_task','read_execution_session','control_execution_session'], 'references/terminal.md'),
    'host_service': ('Persistent local host service, supported keep-awake and macOS background management.', [], 'references/platform-capabilities.md'),
    'authoring': ('Edit existing drafts; validate and save a usable local version; export separately.', ['list_loops','read_loop','create_loop','copy_loop','set_loop','put_node','remove_node','set_implementation','put_step','remove_step','connect_steps','validate_loop','publish_loop'], 'references/build.md'),
    'parameter_contracts': ('One parameter contract for tools, UI and runtime; validates types and nested fields without coercion or injecting defaults.', ['read_loop','read_task'], 'references/contracts.md'),
    'conditional_contracts': ('Schema subset with oneOf/anyOf/allOf/not, if/then/else, dependentRequired, const and union types. Unsupported keywords are rejected.', ['read_capabilities','validate_loop','validate_parameters'], 'references/contracts.md'),
    'plans': ('Expand each, collect outputs, omit steps with when/skip, select candidates and bind parameters.', ['put_step','build_plan','read_plans','preview_plan'], 'references/build-reference.md'),
    'event_routes': ('Accepted node events atomically map results into plans; duplicate reports do not recreate tasks.', ['put_node','read_task','report_task','test_loop'], 'references/build-reference.md#event-triggered-task-generation'),
    'task_refs': ('Run-unique ref labels resolve task_ref/task_refs and after_refs into concrete record IDs and dependencies, including across routes.', ['put_step','add_task','resolve_refs','preview_plan'], 'references/contracts.md'),
    'record_versions': ('Task output references pin the producing revision; collected records can carry a revisions array for mixed versions.', ['resolve_refs','read_record','build_plan','add_task'], 'references/contracts.md'),
    'task_edits': ('Preview and atomically apply ordered task additions, plan builds and edits with revision and scope checks.', ['edit_tasks','change_task'], 'references/run.md'),
    'lifecycle': ('Pure lifecycle transition calculation with atomic Timeline state/result writes; unchanged report contracts, external submission/observation, retries and configured Agent recovery.', ['set_implementation','report_task','change_task'], 'references/build-reference.md'),
    'waits': ('Timer and external-event Tasks wait persistently; no business process is needed for waiting.', ['set_implementation','send_event'], 'references/notifications.md'),
    'notifications': ('Named local outlets, questions/replies, delivery receipts and visible waiting configuration.', ['notify','read_notification_channels','set_notification_channels','send_event','retry_notification'], 'references/notifications.md'),
    'optimistic_edits': ('Agents think concurrently. Managed identities track read versions; stateless callers pass basis from read tools. Atomic commits validate relevant tasks, settings, records and task-set predicates; conflicts require reconsideration. No long-held Timeline lock; same-Task and native-session execution claims remain exclusive.', ['read_task','read_timeline','next_tasks','edit_tasks','change_task','change_settings'], 'references/run.md'),
    'scopes': ('Task ancestry permissions without long-lived planning exclusion, same-Task execution claims, acquire/finish identity lifecycle, immutable past results.', ['read_timeline','acquire_run','finish','read_task'], 'references/run.md'),
    'run_control': ('Find and start Runs, inspect task/result state, pause/resume with command, and resolve explicit user requests or defer tasks. Hooks in change_settings can pause/notify before, after or at a lifecycle transition.', ['list_runs','start_run','read_run','next_tasks','read_record','complete_task','command','defer_task','resolve_request','change_settings'], 'references/run.md'),
    'termination': ('Run ends only when explicit completion_rule or termination_signal applies. Task completion alone does not end a Run.', ['change_settings','read_timeline'], 'references/run.md'),
    'scenarios': ('Isolated author tests use real Engine scheduling and report transitions with supplied mock events and assertions; never execute commands, Agent models or notification transports.', ['test_loop','preview_plan'], 'references/testing.md'),
    'packages': ('Share definition, implementations and author Skills in one package; enforce required capabilities before installation.', ['export_loop','read_capabilities'], 'references/build-reference.md'),
    'author_skills': ('Read bound author handbook and node Skills from read_loop/read_timeline/read_task; package assets retain relative references.', ['read_loop','read_timeline','read_task','put_asset'], 'references/build-reference.md'),
    'runtime_smoke': ('Explicit Agent startup and isolated lifecycle checks; distinct from static validation and simulated workflow tests.', ['smoke_runtime'], 'references/build.md'),
}


def _source_build():
    from loop_anything.paths import platform_skill_directory
    root = Path(__file__).parent
    h = hashlib.sha256()
    for file in sorted(p for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.js','.css','.html')):
        h.update(str(file.relative_to(root)).encode());h.update(file.read_bytes())
    # Runtime imports this canonical portable implementation from the dispatch Skill.
    for skill in ('loop-anything-platform','loop-anything-dispatch'):
        scripts = platform_skill_directory().parent / skill / 'scripts'
        for file in sorted(scripts.glob('*.py')):
            h.update((skill+'/' + file.name).encode());h.update(file.read_bytes())
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
    required = set(bp.get('requires', [])) - {'loop_edit_protection'}
    if bp.get('flow_agent') is not None or any(r.get('flow_agent') for n in bp.get('nodes', {}).values() for r in n.get('routes', [])):
        required.add('builtin_flow_agent')
    implementations = dict(implementations or {})
    if bp.get('flow_agent') is not None:implementations['$flow_agent'] = bp['flow_agent']
    from loop_anything.runtime.implementations import options
    if any(c.get('kind')=='loop' for entry in (implementations or {}).values() for c in options(entry).values()):required.add('loop_calls')
    if any(c.get('executor') for entry in (implementations or {}).values() for c in options(entry).values()):required.add('headless_execution')
    if any(c.get('dispatch') for entry in (implementations or {}).values() for c in options(entry).values()):required.add('agent_communication')
    if any(n.get('routes') for n in bp.get('nodes', {}).values()):required.add('event_routes')
    if bp.get('scenarios'):required.add('scenarios')
    steps = [s for p in bp.get('plans', {}).values() for s in p.get('steps', {}).values()]
    if any('ref' in s or 'after_refs' in s or any(isinstance(v,dict) and {'task_ref','task_refs'} & v.keys() for v in s.get('inputs',{}).values()) for s in steps):
        required.add('task_refs')
    sources = [v for s in steps + [bp.get('seed', {})] for v in s.get('inputs',{}).values()]
    if any(isinstance(v,dict) and 'revisions' in v for v in sources):required.add('record_versions')
    from loop_anything.runtime.implementations import options
    if any(c.get('agent_cli') or c.get('resume_command') or any('{{session_id}}' in a for a in c.get('command',[])) for entry in (implementations or {}).values() for c in options(entry).values()):required.add('agent_resume')
    if any(c.get('terminal') for entry in (implementations or {}).values() for c in options(entry).values()):required.add('agent_terminal')
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
    # Old packages may still declare the removed editing feature; it imposes no requirement.
    missing = set(required)-CAPABILITIES.keys()-{'loop_edit_protection'}
    if missing:raise Invalid('This service lacks required capabilities: ' + ', '.join(sorted(missing)) + '. Upgrade the running service and read its tool catalog.')
