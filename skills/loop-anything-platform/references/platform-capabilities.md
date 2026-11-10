# Platform capabilities and author responsibilities

Generated from platform capability definitions. The running service read_capabilities is authoritative; pass capability to read relevant mechanisms and composition examples on demand.

## How capabilities shape a Loop

During design discussion, proactively select features relevant to the user goal that affect work organization. Explain a possible structure and its benefit; users need not know platform features beforehand. Use this table as needed, not as a checklist. Continue when an existing design fits; do not recite every feature or add checks/confirmation steps.

| Clue in the user goal | Available capability | Design suggestion | Details on demand |
| --- | --- | --- | --- |
| An existing Skill needs situational next-step decisions | Natural-language flow decisions alongside deterministic rules | Separate long work/waits, encode known transitions, and let a flow agent handle uncertain decisions. Gradually encode stable behavior from runtime records. | [Flow agent](flow-agent.md) |
| A reusable Loop already handles part of the work | Nodes can call existing Loops | Configure target, inputs, and result mapping; the platform creates a child Run, waits, and returns results without custom startup/polling scripts. | [Loop calls](loop-calls.md) |
| Long training, queues, or external results | Agents appear only when judgment is needed | Separate planning, automatic execution/waiting, and analysis. The platform runs short periodic query scripts or receives completion events, then advances to the next decision. | [Lifecycle/observation](#lifecycle), [durable waits](#waits) |
| Experiment counts, branches, or next rounds depend on results | Results can generate later Tasks | Define reusable templates. Agents submit round parameters; the platform expands work and aggregates results. Explicit conditions determine another round or completion. | [Event routes](#event_routes), [plans](#plans), [termination](#termination) |
| Work spans days, sessions, or entry points | Business state persists independently of chat | Divide long work into stages and persist goals/progress/results in Timeline; later agents read current facts to continue. | [Storage](#timeline_storage), [recovery](#execution_recovery) |
| Different tools, compute, or machine environments | Mix execution methods in one Loop | Divide by responsibility/resource: prepare data on the platform host, train externally, use receiving clients for other environments, and dispatch specialists through the named directory when needed. | [Candidates](#implementation_selection), [executors](#headless_execution), [communication](#agent_communication) |
| A team shares NAS and machines change often | Use one server and unified clients | The server keeps state machines/runtime facts; clients edit/run through NAS/HTTP tools and can explicitly start local receiving or personal jobs. | [Team service](#team_service), [execution](#headless_execution) |
| Local timers or conditions should awaken an agent | Independent local scheduling | Register a timer/condition without building a Loop. Keep definitions; start only on explicit request. A different machine can inspect them without restarting them. | [Local scheduling](#local_scheduling) |
| Multiple specialties, stage-specific methods, or a long handbook | Separate Loop and node Skills/instructions | Keep shared objectives/rules at Loop level and node methods/tools/contracts at their relevant nodes, read on demand. For example, share experiment goals while separating training operations from evaluation methods. | [Author Skills](#author_skills) |
| Analysis occasionally needs papers or specialist advice | Temporary named helpers | Keep required steps in the main workflow. Request optional help during execution, suspend if needed, and resume the original session with results. | [Assistance](#agent_communication), [session resume](#assistance_session_resume) |
| Research/debugging reveals new information or direction | Revise future work during a Run | Preserve existing facts/results and adjust future Tasks, parameters, or dependencies. The first plan need not enumerate every path. | [Task edits](#task_edits), [Run control](#run_control) |

Respect actual integration prerequisites: external systems need submit/query scripts or event callbacks; dynamic work needs templates/routes/completion conditions; client receivers must be explicitly started and bound; named dispatch needs directory members (local help needs no team); exact resumption needs native session IDs and commands. Timeline business state does not restore arbitrary chat context. The platform waits between short queries, without resident agent/script polling loops. Combining event and polling fallback requires an explicit design; it is not the default.

For “keep running experiments,” suggest “propose parameters → expand experiments → platform waits for training → agent analyzes → choose the next round from results.” For a one-off summary of existing results, handle that task without inventing loops, helpers, or waits.

Organize instructions by responsibility and read on demand to reduce irrelevant context and conflicting instructions. Loading every node Skill at once loses this benefit. Keep shared rules at Loop level and reference them from nodes. Clear short instructions need no split; do not require a new Skill per node, add nodes solely to shorten files, or promise zero context drift.

## Mechanism details

Read the relevant mechanism when implementing a design. activation=automatic means platform-managed; declared/configured requires author declarations or user configuration; operator requires an explicit operation.

## run_library

- Activation: operator
- Platform handles: Server-side paginated summaries by person, Loop, status, and dates; meaningful progress updates activity, and child Runs inherit attribution. Archival preserves history; deletion protects references and live executions.
- Author provides: Set the caller's name once and pass created_by on creation. Query with filters/next_offset; use metadata_revision to change title, attribution, and archival.
- Configuration: `call.py profile --name`, `start_run.created_by`, `list_runs`, `update_run`, `delete_run`, `archive_loop`, `delete_loop`
- Limits: Attribution is not an account or permission boundary. Reads/unchanged polling do not refresh activity. Deletion leaves native sessions and external artifacts. Archive referenced Loop versions instead of deleting them.
- Tools: list_runs, start_run, update_run, delete_run, list_loops, archive_loop, delete_loop
- Reference: [references/run.md](run.md)

## loop_calls

- Activation: declared
- Platform handles: Creates and links child Runs, executes their entries, durably waits in the parent node, and validates returned results. Recovery/retry reuses the same child Run.
- Author provides: Declare kind=loop with loop.key/inputs/result for an installed Loop on the same service and input/result-envelope mappings.
- Configuration: `set_implementation.loop`, `read_task.execution_state.child_run_id`, `read_run.parent_call`
- Limits: One Task maps to one child Run; new execution requires a new call Task. Parent/child pause or terminate separately; the child uses its own completion conditions. Ancestor-recursive calls are unsupported.
- Tools: set_implementation, list_loops, read_task, read_run, read_record, command
- Reference: [references/loop-calls.md](loop-calls.md)

## team_service

- Activation: configured
- Platform handles: One server persists team Loops, Runs, and state machines. Unified clients operate it over NAS/HTTP and optionally execute work locally; the server web UI is optional.
- Author provides: Install with --role server or --role client. Clients combine service operations and local execution; save NAS addresses using local mount paths. Operations-only use still supports portable Skills without the runtime.
- Configuration: `serve --team-dir`, `serve --no-web`, `client tool`, `call.py --url`, `call.py result`
- Limits: Only one service opens the team database, using DELETE journaling. NAS must support locking/durable writes. Timeout does not cancel requests; a processing crash returns outcome_unknown without automatic replay. Validate real NAS behavior in deployment.
- Tools: list_loops, list_runs, read_capabilities
- Reference: [references/team-runtime.md](team-runtime.md)

## headless_execution

- Activation: configured
- Platform handles: The unified client can receive assigned processes, persist deduplication/results, and forward interactive terminals. The service retains business state machines; exact sessions resume on their original executor.
- Author provides: Use client local to register and explicitly start a receiver. Discover IDs with list_executors and select implementation.executor on a node or named agent. Install required CLIs/environment on the receiving client.
- Configuration: `client local --root register/start`, `list_executors`, `read_executor_call`, `implementation.executor`
- Limits: Disconnection does not reassign/restart work. A restarted service reconnects to the original call; a restarted receiver does not replay accepted commands with unknown outcomes. Native session history must remain accessible on the original executor. Legacy NAS/Base named communication remains supported.
- Tools: list_executors, read_executor_call, set_implementation, confirm_executor_stopped, executor_poll, executor_report
- Reference: [references/team-runtime.md](team-runtime.md)

## local_scheduling

- Activation: operator
- Platform handles: Shares a small scheduling, pure-transition, and process-management core for timers, script conditions, and local CLIs without a service, Run, or web UI.
- Author provides: Use the same client with loop-anything-local, optionally using NAS for persistent definitions; explicitly select IDs with client local start.
- Configuration: `client local --root register/list/show/start/stop`
- Limits: Definitions persist; processes stop with their machine. Loading/moving machines does not restart them. Intervals run after completion; conditions fire once by default. Failure stops with a saved error; receiver communication errors retry at the configured interval.
- Tools: Provided by the runtime; no separate call required
- Reference: [references/team-runtime.md](team-runtime.md)

## flow_agent

- Activation: declared
- Platform handles: Built-in flow decisions awaken on explicit event routes, reusing execution, sessions, wait/resume, and Timeline writes without extra authored flow nodes.
- Author provides: Choose decision points from the user's goal, keep full business rules in the Loop handbook, and configure an actual CLI, executor, or dispatch. Do not choose a default progression mode for the user.
- Configuration: `Loop.flow_agent`, `nodes.*.routes.flow_agent`, `read_task.flow_decisions`, `build_plan/edit_tasks/report_task/finish`
- Limits: Configuring an executor alone does not trigger it. Without a matching route no agent is called. Decisions have global Run scheduling scope with commit validation. Explicit rule and agent routes can both fire; read receipts to avoid duplicate scheduling.
- Tools: set_loop, put_node, acquire_run, read_timeline, read_task, build_plan, edit_tasks, report_task, finish, test_loop
- Reference: [references/flow-agent.md](flow-agent.md)

## builtin_flow_agent

- Activation: declared
- Platform handles: Identifies the built-in decision configuration/route protocol so old services cannot interpret it as ordinary event routing.
- Author provides: Package capability declarations detect it automatically; see flow_agent for usage.
- Configuration: `Loop.flow_agent`, `nodes.*.routes.flow_agent`
- Limits: A compatibility declaration alone does not awaken an agent; explicit routing is required.
- Tools: set_loop, put_node, read_task
- Reference: [references/flow-agent.md](flow-agent.md)

## loop_configuration

- Activation: configured
- Platform handles: Ships config.example.json; recipient overrides persist separately, are snapshotted for new Runs, and survive retry/restart. Sharing excludes personal overrides.
- Author provides: Expose paths/services as startup inputs with documented templates. Recipients use read_loop_config/set_loop_config and explicit bindings after adding local candidates.
- Configuration: `config.example.json`, `read_loop_config`, `set_loop_config`
- Limits: Does not change nodes/routes/lifecycles/Skills, probe availability, or rewrite hardcoded paths. Existing Runs ignore later configuration changes.
- Tools: read_loop_config, set_loop_config, read_loop, put_asset, start_run
- Reference: [references/loop-config.md](loop-config.md)

## flow_diagram

- Activation: author-maintained
- Platform handles: Ships ready-made drawing components/templates in the Skill. Saved package assets appear in the overall workflow view; actual IDs/unique names link diagram nodes to detail panels. Custom shapes can use data-loop-node.
- Author provides: After initial construction or changes to nodes, branches, loops, or task generation, draw every defined node, including optional/fallback branches. Do not replace actual nodes with summary boxes; compare against the node list and preview before saving.
- Configuration: `scripts/render_flow.py`, `assets/flow.md`, `docs/flow.md`, `docs/flow.html`, `put_asset`
- Limits: Rendering requires Node.js 20+, viewing does not. Diagrams do not change execution rules, awaken agents on page open/every round, or become save/run preflight gates.
- Tools: read_loop, put_asset
- Reference: [references/flow-diagram.md](flow-diagram.md)

## machine_identity

- Activation: automatic
- Platform handles: Generates and persists a full machine UUID on demand, separate from workspace identity. communication_status.self and awakening contexts expose both directly.
- Author provides: Read self and address directory members using instance_id plus agent_id; do not infer identity from MAC, hostname, or session.
- Configuration: `communication_status.self`, `context.self`, `communication_config(operation=identity)`
- Limits: Identity belongs to the connected platform user environment. instance_id aliases workspace_id. Moving/renaming preserves identity; copies need an explicitly new workspace identity without historical takeover. Do not copy identity storage with a business database to another machine.
- Tools: communication_status, communication_workspace, communication_config
- Reference: [references/communication.md](communication.md)

## cc_connect

- Activation: configured/operator
- Platform handles: Shares local cc-connect configuration, discovers existing Bots without returning credentials, and lets named agents select a Bot directly.
- Author provides: Discover with read_cc_connect. If missing, configure_cc_connect with actual config/executable paths. Map notification_bot from returned project/platform; create a cc_connect outlet only for a fixed destination.
- Configuration: `read_cc_connect`, `configure_cc_connect`, `agent.notification_bot`, `channels.*.cc_connect`
- Limits: Do not guess config directories, write per-Bot commands, or install/start Bots. Listing proves neither online status nor group membership. Ambiguity does not auto-select. Explicit references can be saved without availability preflight. Paths/secrets stay local.
- Tools: read_cc_connect, configure_cc_connect, communication_config, read_notification_channels, set_notification_channels
- Reference: [references/cc-connect.md](cc-connect.md)

## conversation_notifications

- Activation: automatic/configured
- Platform handles: Feishu-origin calls reply to the original conversation by default. Private chats use the entry Bot; group chats prefer the named agent's Bot while preserving the topic.
- Author provides: Skill call.py carries chat_context only. The platform persists/reuses origin; the adapter retains the original entry, uses a known root with cc-connect, or passes an unresolved session unchanged. No Feishu permission/credential lookups. agent.notification_bot maps discovered local Bots; legacy notification_route remains compatible. Nested assistance inherits origin without rebuilding notification commands.
- Configuration: `request_assistance.chat_context`, `start_run.chat_context`, `communication_config(operation=agent)`, `existing conversation_id compatibility`
- Limits: Notification integration failure does not block business work. Fall back to the entry Bot only after definitive non-delivery (not started, not connected, or explicit rejection), not ambiguous failure. Preserve raw session_key; map an explicit topic to a root target in the same chat/topic, never to the main timeline. cc-connect owns actual delivery. Explicit outlets win; without origin use per-machine group outlets.
- Tools: communication_config, request_assistance, start_run, read_assistance
- Reference: [references/cc-connect.md](cc-connect.md)

## group_notification_priority

- Activation: automatic/configured
- Platform handles: Without chat origin, each group notification prefers the action machine, then the immediate requester; with neither outlet, record only in the platform.
- Author provides: Bind outlets per machine and omit request.notification_route to use priority. Nested assistance falls back to its immediate requester.
- Configuration: `communication_config(operation=group_notifications)`, `communication_status.groups[].notification_bindings`, `read_assistance.notifications[].routing`
- Limits: Fallback requires an absent/explicitly disabled outlet, not offline/failure/unknown delivery. Explicit outlets win; retries pin the original binding.
- Tools: communication_config, communication_status, read_assistance
- Reference: [references/communication.md](communication.md)

## communication_context

- Activation: automatic/operator
- Platform handles: Queries default to compact status/full result. Base logs remain on the executor and paginate on demand (logs_pending means waiting). Resumption/follow-up preserve business context, results, and original session without embedding full communication archives.
- Author provides: Read status/structured results first. Pass NAS paths only with confirmed shared access, even with Base communication. Use dispatch references/artifacts.md for optional cloud attachments when needed. Page through logs only for diagnostics.
- Configuration: `read_assistance.include_logs`, `read_assistance.include_details`, `read_assistance.max_chars`, `read_assistance.after/offset`
- Limits: Logs default to 4000 characters per page, maximum 16000. Successful native-session execution keeps no duplicate full terminal transcript. Scripts, failures, and sessionless execution retain diagnostics. Structured business results are not automatically shortened.
- Tools: read_assistance, request_assistance, control_assistance
- Reference: [references/communication.md](communication.md)

## standalone_collaboration

- Activation: configured/operator
- Platform handles: A built-in Loop handles standalone collaboration. Event waits record results; current sessions or named coordinators suspend/resume the same Task/session.
- Author provides: request_assistance returns a collaboration Run; follow-ups continue it. Automatic resumption uses start_collaboration with the actual local session, agent PID, and resume configuration; after wait_assistance, finish and exit the original process.
- Configuration: `start_collaboration`, `request_assistance`, `wait_assistance`
- Limits: Unknown external sessions receive result tracking/notification only. Never guess sessions or resume alongside a still-live original process.
- Tools: start_collaboration, request_assistance, read_assistance, wait_assistance, communication_status
- Reference: [references/communication.md](communication.md)

## confirmed_agent_directory

- Activation: configured
- Platform handles: Group directories share user-confirmed duties, capabilities, and availability. Legacy unconfirmed descriptions do not accept new group work.
- Author provides: Ask about duties and confirm description/group exposure before communication_config(task_confirmed=true). Reconfirm changed descriptions or added groups.
- Configuration: `communication_config`, `communication_status`
- Limits: An agent-written description is not user confirmation.
- Tools: communication_config, communication_status
- Reference: [references/communication.md](communication.md)

## assistance_session_resume

- Activation: configured/operator
- Platform handles: Checks the native session/exact resume command before waiting; replies/deadlines resume that session and Task with results and fresh credentials.
- Author provides: Configure managed CLI/resume_command and register the actual session. finish only after wait_assistance succeeds; remote nodes also complete their execution request.
- Configuration: `wait_assistance`, `register_agent_session`, `implementations.*.resume_command`
- Limits: Original machine/agent/session stay fixed. Missing data or resume failure blocks explicitly, never starts a new conversation. Current resumption uses macOS/Linux terminals; retain CLI session files.
- Tools: wait_assistance, register_agent_session, communication_execute, read_assistance
- Reference: [references/communication.md](communication.md)

## group_notifications

- Activation: configured/operator
- Platform handles: Machines bind their own group outlets. The source durably creates notifications; the selected machine uses existing adapters such as cc-connect and returns receipts.
- Author provides: Configure named local outlets, then group_notifications to bind each machine's group entry.
- Configuration: `communication_config(operation=group_notifications)`, `platform notification channels`
- Limits: Commands/credentials do not enter team transport. Created notifications pin their outlet; old-policy requests finish under it. Verify unknown delivery before explicit retry.
- Tools: communication_status, communication_config, read_notification_channels, set_notification_channels, read_assistance, control_assistance
- Reference: [references/communication.md](communication.md)

## agent_communication

- Activation: configured/operator
- Platform handles: All dispatch reuses loop-anything-dispatch; only receiving needs a running platform. Replies persist in full. Pass NAS artifacts only with shared access; native Feishu attachments are optional and automatically handle oversized inline messages. Base coalesces state, updates heartbeats in place, and archives acknowledged messages in the cloud. Requests/results remain for optional manual cleanup; clients do not auto-copy full bodies. One NAS/Base team link supplies directory/result views. Enabled Base wins; NAS is used only without Base, never to reroute failures. Existing Runs/requests retain transport. Names and IDs resolve through the directory; script wait timeouts do not cancel requests.
- Author provides: Set the receiving default with communication_config(operation=team,link=...), then expose agents after user-confirmed duties. Send-only clients use the independent Skill's join/leave/agents/submit/read/wait/control. Loop nodes retain scoped entries for registration/dispatch; wait_assistance then finish when needed.
- Configuration: `communication_config`, `implementations.*.dispatch`, `request_assistance`, `wait_assistance`
- Limits: Dispatch fixes one machine/agent; receivers persist then execute without another source grant. Old in-flight protocols remain compatible; the source owns the business Run. Recovery pins the original session; disconnection never auto-reruns work. Validate actual NAS/Base environments.
- Tools: communication_workspace, communication_status, communication_config, request_assistance, read_assistance, control_assistance, wait_assistance, communication_execute
- Reference: [references/communication.md](communication.md)

## timeline_storage

- Activation: automatic
- Platform handles: Persists Runs, Tasks, attempts, versioned results, events, and history; formal writes share a database transaction.
- Author provides: Define business-result schemas and report facts through official tools.
- Configuration: `nodes.*.outputs`, `records`, `report_task.envelope`
- Limits: External side effects are outside local transactions; the platform cannot provide exactly-once submission for an external service.
- Tools: read_timeline, read_record, read_run
- Reference: [references/run.md](run.md)

## task_scheduler

- Activation: automatic
- Platform handles: Checks inputs/after dependencies, pause points, implementation selection, concurrency, and scope, then dispatches ready Tasks.
- Author provides: Declare Tasks, sources, and dependencies; configure routes when successors should be generated automatically.
- Configuration: `plans.*.steps.*.inputs`, `plans.*.steps.*.after`, `settings.max_parallel`, `nodes.*.routes`
- Limits: Dependency edges advance existing Tasks only; missing business work is not inferred by default.
- Tools: next_tasks, change_settings
- Reference: [references/run.md](run.md)

## execution_recovery

- Activation: automatic
- Platform handles: Recovers persisted execution state after restart, preserves retry/observation identities, and exposes processes/identities whose stopping cannot be confirmed.
- Author provides: Make submission/observation recoverable, investigate unknown external effects, and confirm old processes stopped when needed.
- Configuration: `implementations.*.observe`, `implementations.*.lifecycle`, `command`
- Limits: Unknown process status is not safe completion. External idempotency and identity resolution belong to adapters.
- Tools: read_task, command, change_task
- Reference: [references/build-reference.md](build-reference.md)

## implementation_selection

- Activation: declared
- Platform handles: Selects Task override, then Run binding, then Loop default; validates node/candidate parameters and preserves execution snapshots.
- Author provides: Provide real candidates, parameter contracts, and entries; determine automatic-stage parameters when scheduling.
- Configuration: `implementations`, `settings.bindings`, `Task.implementation`, `Task.parameters`
- Limits: The platform does not inject default parameters, generate business commands, or repair execution environments.
- Tools: read_loop, read_task, set_implementation
- Reference: [references/contracts.md](contracts.md)

## workspace_inspection

- Activation: automatic
- Platform handles: Provides Loop structure, dependencies, execution state, results, input provenance, history, parameter editing tools, previews, and file-result display.
- Author provides: Provide meaningful node names, schema title/description, explicit file outputs, and business results.
- Configuration: `nodes.*.label`, `records.*.title`, `records.*.description`, `records.*.format`
- Limits: The workspace supports runtime operations; there is no separate sanitized team-only dashboard. Displaying a file does not prove artifact validity.
- Tools: read_run, read_loop
- Reference: [references/build-reference.md](build-reference.md)

## agent_resume

- Activation: configured/operator
- Platform handles: Shows results per attempt, records actual CLI session IDs, and resumes the selected original session on request with fresh operation identity and preserved historical results.
- Author provides: Provide CLI/resume commands; let the CLI output or agent register its real ID. The user selects the target and new request.
- Configuration: `implementations.*.agent_cli`, `implementations.*.resume_command`, `register_agent_session`, `command argv {{session_id}}`
- Limits: Do not guess with --last or scan unrelated CLI history. Native IDs are exclusive across Runs until process exit; users manage manually started external CLIs. Missing old IDs need explicit registration; missing local history can prevent recovery. Resume only running/paused Runs. CLI storage/model access remain the CLI's responsibility.
- Tools: register_agent_session, read_task, set_implementation, read_execution_session, control_execution_session
- Reference: [references/terminal.md](terminal.md)

## agent_terminal

- Activation: automatic/configured
- Platform handles: Streams output; with native sessions it keeps a bounded live tail, then session location after success. Failures/sessionless runs retain diagnostics. Optional terminals attach to the same CLI process, forwarding keyboard/size and closing after finish.
- Author provides: Provide CLI, cwd, login, and permissions. Interactive commands receive context through {{prompt}} or {{prompt_file}}.
- Configuration: `implementations.*.terminal`, `implementations.*.command`, `read_capabilities(agent_terminal)`
- Limits: Ordinary command output is read-only; interactive terminals currently support macOS/Linux. After process restart, history/recovery follow existing operation rules without guaranteeing CLI session recovery. Terminal identity/execution checks and report_task/finish still apply. Do not duplicate logging/interaction services.
- Tools: set_implementation, read_task, read_execution_session, control_execution_session
- Reference: [references/terminal.md](terminal.md)

## host_service

- Activation: configured
- Platform handles: Keeps the workspace service running on its installed host, with supported keep-awake controls and macOS background hosting.
- Author provides: Choose/install the host, database, port, and credentials; configure the host to suit runtime needs.
- Configuration: `service CLI`, `platform keep-awake setting`
- Limits: Remote compute, credentials, training environments, and cross-machine deployment belong to installation/business integration.
- Tools: Provided by the runtime; no separate call required
- Reference: [references/platform-capabilities.md](platform-capabilities.md)

## authoring

- Activation: operator
- Platform handles: Saves drafts/revisions, validates definitions, and produces locally usable versions; Runs pin their startup version.
- Author provides: Design business nodes/methods, keep editing the existing draft, and export when sharing.
- Configuration: `Loop.id/version`, `draft revision`
- Limits: Draft save, usable-version save, and share packaging serve different purposes. Historical Runs do not migrate automatically.
- Tools: list_loops, read_loop, create_loop, copy_loop, set_loop, put_node, remove_node, set_implementation, put_step, remove_step, connect_steps, validate_loop, publish_loop
- Reference: [references/build.md](build.md)

## parameter_contracts

- Activation: automatic
- Platform handles: Validates nested inputs/outputs and parameters at formal Task writes and implementation selection.
- Author provides: Declare actual contracts and use validation tools to locate missing fields.
- Configuration: `nodes.*.parameter_schema`, `implementations.*.parameter_schema`, `records`
- Limits: It does not interpret domain meaning or inject schema.default into parameters.
- Tools: read_loop, read_task
- Reference: [references/contracts.md](contracts.md)

## conditional_contracts

- Activation: declared
- Platform handles: Checks conditional requirements, exclusive alternatives, and union types; unsupported schema keywords fail explicitly.
- Author provides: Declare deterministic parameter requirements in schemas.
- Configuration: `parameter_schema.if/then/else`, `parameter_schema.oneOf`, `parameter_schema.dependentRequired`
- Limits: Only the published JSON Schema subset is supported; implementations still project business CLI arguments.
- Tools: read_capabilities, validate_loop, validate_parameters
- Reference: [references/contracts.md](contracts.md)

## plans

- Activation: declared
- Platform handles: Allocates Task/output identities, expands each, aggregates collect, resolves inputs/after, and omits steps by when/skip.
- Author provides: Define reusable work structure, batch parameters, input mapping, and optional steps.
- Configuration: `plans.*.parameters`, `plans.*.steps`, `steps.*.each/when`, `inputs.*.from/collect`
- Limits: Omission produces no placeholder output; consumers need explicit reusable sources. Plan when applies to a step before that step's each expansion.
- Tools: put_step, build_plan, read_plans, preview_plan
- Reference: [references/build-reference.md](build-reference.md)

## event_routes

- Activation: declared
- Platform handles: Maps accepted node events to plan parameters/expansion, committing with results. Duplicate reports return the same receipt.
- Author provides: Declare event, plan, values, and needed each/when/steps; nodes submit business results.
- Configuration: `nodes.*.routes`, `report_task.report_id`
- Limits: Only accepted lifecycle reports trigger routes. Do not generate the same successors again in helpers.
- Tools: put_node, read_task, report_task, test_loop
- Reference: [references/build-reference.md#event-triggered-task-generation](build-reference.md#event-triggered-task-generation)

## task_refs

- Activation: declared
- Platform handles: Resolves business refs to actual Task/record identities, including forward references across batches in one report.
- Author provides: Provide Run-unique names and explicit aggregation members; include rounds in repeated names.
- Configuration: `steps.*.ref`, `steps.*.after_refs`, `inputs.*.task_ref/task_refs`
- Limits: Missing/duplicate references reject submission. No task-group scheduler infers members automatically.
- Tools: put_step, add_task, resolve_refs, preview_plan
- Reference: [references/contracts.md](contracts.md)

## record_versions

- Activation: automatic
- Platform handles: Pins Task-output references to producer versions and preserves actual input provenance; aggregation can consume different record revisions.
- Author provides: Declare task_ref/task_refs sources and explicitly specify version overrides.
- Configuration: `inputs.*.revision/revisions`, `resolve_refs`
- Limits: Unversioned ordinary record sources use latest-value semantics. Pinning a revision does not verify remote file contents.
- Tools: resolve_refs, read_record, build_plan, add_task
- Reference: [references/contracts.md](contracts.md)

## task_edits

- Activation: operator
- Platform handles: Atomically validates/applies ordered edits against basis and business scope, rolling back the group on failure.
- Author provides: Decide from read evidence and reconsider after conflicts.
- Configuration: `edit_tasks.basis`, `edit_tasks.changes`, `edit_tasks.preview`
- Limits: Separate calls are not cross-call transactions. Use routes to commit results and successors together.
- Tools: edit_tasks, change_task
- Reference: [references/run.md](run.md)

## lifecycle

- Activation: declared
- Platform handles: A generic state machine computes transitions independently; Timeline stores state/results/history and applies same-Task retry, observation failures, and configured fallback in the existing transaction.
- Author provides: Adapters report bounded facts; lifecycle declares transitions/retry conditions/business repair methods. No business-specific transition functions or state stores are needed.
- Configuration: `implementations.*.lifecycle`, `implementations.*.command/observe`, `Loop.fallback_node`
- Limits: Existing Loops need no migration. waiting retains external identity, observation timing, and query errors. Healthy queuing/long duration is not automatically failure. Retry, deduplication, and atomicity remain unchanged.
- Tools: set_implementation, report_task, change_task
- Reference: [references/build-reference.md](build-reference.md)

## waits

- Activation: declared
- Platform handles: Native timer/event/approval Tasks persist waits; external events match by name/correlation key.
- Author provides: Declare wait times, event keys, or approvals, and routes for subsequent work.
- Configuration: `implementations.*.kind`, `implementations.*.wait`, `implementations.*.event`
- Limits: Notifications alone do not pause work; waiting needs an explicit Task. Adapters connect chat replies/business event sources.
- Tools: set_implementation, send_event
- Reference: [references/notifications.md](notifications.md)

## notifications

- Activation: configured
- Platform handles: Queues, deduplicates, and records delivery receipts per outlet. Missing configuration waits; delivery failures remain visible.
- Author provides: Configure actual send commands/destinations and declare content/question correlation keys.
- Configuration: `platform notification channels`, `settings.notification_route`, `lifecycle.transitions.*.notify`, `notify.reply`
- Limits: A platform notification record is not external delivery. The platform does not install chat Bots automatically.
- Tools: notify, read_notification_channels, set_notification_channels, send_event, retry_notification
- Reference: [references/notifications.md](notifications.md)

## optimistic_edits

- Activation: automatic/operator
- Platform handles: Managed identities remember read versions; short commit transactions check basis, scope, and execution state without long Timeline occupancy.
- Author provides: Without a sustained token, pass returned basis on edits. Use read_task for focused work and read_timeline/next_tasks for collection/absence decisions. Reconsider conflicts.
- Configuration: `read_task.basis`, `read_timeline.basis`, `edit_tasks.basis`, `change_task.basis`
- Limits: Do not merely replace version numbers and retry unchanged. Logs/ordinary progress are not conflicts. Identity, same-Task exclusivity, and native-session protection remain, including exit gaps after finish, resumed historical terminals, and unfinished remote processes.
- Tools: read_task, read_timeline, next_tasks, edit_tasks, change_task, change_settings
- Reference: [references/run.md](run.md)

## scopes

- Activation: automatic
- Platform handles: Restricts changes by Task ownership without excluding concurrent thinking; one valid executor remains per Task.
- Author provides: Align ownership with responsibility and finish after completion/explicit waiting. Use an explicit global node for global decisions.
- Configuration: `Task.parent_id`, `Loop.global_agent_node`, `acquire_run/finish`
- Limits: Dependency differs from ownership; ready descendants can run before the parent agent finishes.
- Tools: read_timeline, acquire_run, finish, read_task
- Reference: [references/run.md](run.md)

## run_control

- Activation: operator
- Platform handles: Supports pause/resume, Task edits, user requests, and registered waits. Hooks can pause/notify before, after, or at transitions.
- Author provides: Choose intervention points/actions from user intent.
- Configuration: `settings.hooks`, `command`, `defer_task`, `resolve_request`
- Limits: The user's agent interprets natural-language authorization; the platform applies explicit operations and scope checks.
- Tools: list_runs, start_run, read_run, next_tasks, read_record, complete_task, command, defer_task, resolve_request, change_settings
- Reference: [references/run.md](run.md)

## termination

- Activation: declared
- Platform handles: Closes the Run and stops remaining work through completion_rule or termination_signal.
- Author provides: Declare decidable conditions or persist a confirmed completion judgment in settings.
- Configuration: `settings.completion_rule`, `settings.termination_signal`
- Limits: Business output satisfied/status, an empty Task list, or finish does not end a Run by itself.
- Tools: change_settings, read_timeline
- Reference: [references/run.md](run.md)

## scenarios

- Activation: operator
- Platform handles: Uses the real Engine in an isolated database with authored simulated reports to check expansion, dependencies, deduplication, and completion.
- Author provides: Supply representative inputs, simulated facts, and observable expectations.
- Configuration: `Loop.scenarios`, `test_loop`, `preview_plan`
- Limits: Commands/models/notification delivery are intercepted; this does not replace real environment/model acceptance.
- Tools: test_loop, preview_plan
- Reference: [references/testing.md](testing.md)

## packages

- Activation: operator
- Platform handles: Packages definitions/candidates/author assets, checks capability requirements, installs versions, and preserves workspace history.
- Author provides: Include actual files/dependencies/requirements and target-environment configuration.
- Configuration: `Loop.requires`, `package assets`, `export_loop`
- Limits: The platform does not supply missing business dependencies; installation does not launch a business Run.
- Tools: export_loop, read_capabilities
- Reference: [references/build-reference.md](build-reference.md)

## author_skills

- Activation: declared
- Platform handles: Returns author methods and installed paths by Loop/node binding, preserving relative package structure.
- Author provides: Write domain methods, required evidence, inputs/outputs, and completion criteria.
- Configuration: `Loop.handbook`, `nodes.*.skills`, `put_asset`
- Limits: Attaching a script asset does not register an implementation; the platform does not invent business methods.
- Tools: read_loop, read_timeline, read_task, put_asset
- Reference: [references/build-reference.md](build-reference.md)

## runtime_smoke

- Activation: operator
- Platform handles: Performs explicitly requested real minimal agent startup and simulated lifecycle-report paths.
- Author provides: Select authorized candidates/cases and separately validate real external business work.
- Configuration: `smoke_runtime`
- Limits: May invoke models. Passing static/simulated checks does not establish target-environment readiness.
- Tools: smoke_runtime
- Reference: [references/build.md](build.md)

## Common compositions

### flow_agent_decision

An existing Skill needs situational decisions about what happens next. Get it running, then gradually encode stable rules; the building agent configures explicit points from user goals.

```json
{
  "use_when": "An existing Skill needs situational decisions about what happens next. Get it running, then gradually encode stable rules; the building agent configures explicit points from user goals.",
  "capabilities": [
    "flow_agent",
    "builtin_flow_agent",
    "event_routes",
    "scopes"
  ],
  "prerequisites": "The Loop handbook keeps full objectives, rules, and completion conditions. set_loop accepts the loop fields below. Complete flow_agent with the actual user CLI or dispatch. With kind only, acquire_run(run_id,task_id) claims a pending decision; it will not run automatically. No extra node, port, or intermediary plan is required.",
  "loop": {
    "flow_agent": {
      "kind": "agent"
    }
  },
  "source_routes": [
    {
      "id": "decide",
      "event": "completed",
      "flow_agent": true
    }
  ],
  "execution": "The platform saves source Task/execution/report, event, conditions, and exact result-version references. The flow agent reads the full handbook, read_task.trigger, and source route_receipts, schedules successors, submits the full decision output, and calls finish. read_task(source_task) returns flow_decisions; read_task(decision_task)/read_record retrieve full results.",
  "scope": "Built-in decisions have global scheduling scope in the current Run. Thinking does not lock Timeline; commits validate read evidence. One event can explicitly match both rule and agent routes; do not reschedule work already created by rules. No declared route means no flow-agent call.",
  "verification": [
    "test_loop",
    "read_task",
    "read_record"
  ]
}
```

### shared_space_onboarding

Independently installed machines need to discover a shared team and expose named agents.

```json
{
  "use_when": "Independently installed machines need to discover a shared team and expose named agents.",
  "capabilities": [
    "agent_communication"
  ],
  "configuration": [
    "The receiver calls communication_config(operation=team,link=BASE_LINK_OR_NAS_DIRECTORY), returning the joined team ID and current default. Base is preferred; NAS is the fallback. A new NAS team needs create=true; Base tables are managed automatically.",
    "operation=agent configures local CLI, cwd, resume_command, and team scope after the user confirms duties. Joining a team does not expose agents automatically.",
    "Send-only users install loop-anything-dispatch and join the same link without running a platform.",
    "Bind Loops to the team and retain scoped call entries. The web shows members, work, and results. Legacy NAS spaces/groups remain compatible."
  ],
  "loop_configuration": {
    "tool": "read_capabilities",
    "arguments": {
      "capability": "loop_configuration"
    },
    "reference": "references/loop-config.md",
    "guidance": "When sharing or moving a Loop, expose paths/services as startup inputs and provide config.example.json. Recipients adapt agents/environments with separate runtime configuration, without copying the workflow or building configuration loaders."
  },
  "author_provides": "A team link and access; local receiving CLI commands and user-confirmed duties.",
  "verification": [
    "communication_workspace",
    "communication_status",
    "communication_config"
  ]
}
```

### chat_origin_delivery

A Feishu private chat/group topic requests local or remote help and needs results returned to that conversation.

```json
{
  "use_when": "A Feishu private chat/group topic requests local or remote help and needs results returned to that conversation.",
  "capabilities": [
    "cc_connect",
    "conversation_notifications",
    "agent_communication",
    "notifications"
  ],
  "configuration": [
    "Skill call.py sends request_assistance/start_run with chat_context alongside the business request. The platform stores origin/available thread_root; the adapter reuses roots directly with cc-connect, without channel preflight.",
    "Discover Bots through read_cc_connect and select project/platform in the named agent notification_bot. Group confirmations/results prefer that Bot; private chats retain the entry Bot.",
    "Preserve raw session_key/topic information. Use thread_root when present; otherwise pass the session unchanged to cc-connect. Agents need not query Feishu, supply secrets, or configure preflights. The bridge owns actual topic delivery/permissions. Unknown outcomes after sending are not automatically resent; notification failure does not block work."
  ],
  "loop_configuration": {
    "tool": "read_capabilities",
    "arguments": {
      "capability": "loop_configuration"
    },
    "reference": "references/loop-config.md",
    "guidance": "When sharing or moving a Loop, expose paths/services as startup inputs and provide config.example.json. Recipients adapt agents/environments with separate runtime configuration, without copying the workflow or building configuration loaders."
  },
  "author_provides": "A named-agent Bot reference (notification_bot) and existing cc-connect access. Loops do not need Bot credentials.",
  "verification": [
    "read_assistance",
    "communication_workspace"
  ]
}
```

### group_cc_connect_delivery

Without chat origin, A requests B; notifications prefer the action machine, falling back to A only if no outlet exists.

```json
{
  "use_when": "Without chat origin, A requests B; notifications prefer the action machine, falling back to A only if no outlet exists.",
  "capabilities": [
    "conversation_notifications",
    "group_notifications",
    "group_notification_priority",
    "agent_communication",
    "notifications"
  ],
  "configuration": [
    "Configure the bridge on A/B with read_cc_connect/configure_cc_connect. Fixed outlets use cc_connect={project,platform} and explicit destination, without command assembly.",
    "Each machine calls communication_config(operation=group_notifications); changes include its current binding_id without overwriting others.",
    "communication_status exposes per-machine notification_bindings. Omit request.notification_route: execution/result events prefer B, then A if B has no outlet, otherwise platform records only."
  ],
  "loop_configuration": {
    "tool": "read_capabilities",
    "arguments": {
      "capability": "loop_configuration"
    },
    "reference": "references/loop-config.md",
    "guidance": "When sharing or moving a Loop, expose paths/services as startup inputs and provide config.example.json. Recipients adapt agents/environments with separate runtime configuration, without copying the workflow or building configuration loaders."
  },
  "author_provides": "The group and each machine's actual chat destination. Business agents need not implement queues, select senders, or invoke cc-connect themselves.",
  "verification": [
    "communication_status",
    "read_assistance",
    "communication_workspace"
  ]
}
```

### named_agent_assistance

A current node or ordinary conversation needs temporary help locally or in an explicitly selected team.

```json
{
  "use_when": "A current node or ordinary conversation needs temporary help locally or in an explicitly selected team.",
  "capabilities": [
    "agent_communication",
    "agent_terminal",
    "assistance_session_resume"
  ],
  "configuration": [
    "communication_status discovers exposed local agents/allowed groups. Disambiguate with agent_id and instance_id as needed.",
    "request_assistance returns a durable ID readable by trusted workspaces. Local requests need no NAS. A built-in Run tracks standalone collaboration; further requests use collaboration_id and follow-ups continue that Run.",
    "Managed nodes register native sessions/resume configuration, then wait_assistance and finish. Reply/deadline resumes the same CLI session and Task on the original machine with new credentials/results. Inability to resume blocks explicitly, without a new session.",
    "Helpers use scoped read_context for associated context and complete for results, without write authority over the original node."
  ],
  "loop_configuration": {
    "tool": "read_capabilities",
    "arguments": {
      "capability": "loop_configuration"
    },
    "reference": "references/loop-config.md",
    "guidance": "When sharing or moving a Loop, expose paths/services as startup inputs and provide config.example.json. Recipients adapt agents/environments with separate runtime configuration, without copying the workflow or building configuration loaders."
  },
  "author_provides": "The question, shared context, result requirements, and business choice if unavailable. Machine owners configure named CLIs/exposure.",
  "verification": [
    "communication_config",
    "read_assistance"
  ]
}
```

### group_agent_node

A formal agent node needs to execute on another machine.

```json
{
  "use_when": "A formal agent node needs to execute on another machine.",
  "capabilities": [
    "agent_communication",
    "implementation_selection",
    "lifecycle"
  ],
  "configuration": [
    "Keep kind=agent, set dispatch.location=group plus agent_id or capability, and bind the Run group.",
    "Dispatch fixes one machine/agent; the receiver persists then starts without a second source grant. The source retains the business Run. Other local nodes are not published.",
    "Use read_task/report_task/finish through scoped platform_client/URL with the original contracts and scope."
  ],
  "loop_configuration": {
    "tool": "read_capabilities",
    "arguments": {
      "capability": "loop_configuration"
    },
    "reference": "references/loop-config.md",
    "guidance": "When sharing or moving a Loop, expose paths/services as startup inputs and provide config.example.json. Recipients adapt agents/environments with separate runtime configuration, without copying the workflow or building configuration loaders."
  },
  "author_provides": "Node business contracts/member selection; the executor supplies CLI, environment, and accessible artifacts.",
  "verification": [
    "communication_config",
    "read_assistance"
  ]
}
```

### result_to_batch_and_review

A source produces several resolved parameter sets; execute each and aggregate this batch's results.

```json
{
  "use_when": "A source produces several resolved parameter sets; execute each and aggregate this batch's results.",
  "capabilities": [
    "event_routes",
    "plans",
    "task_refs",
    "task_scheduler",
    "scopes"
  ],
  "prerequisites": "The source outputs jobs, each with id and params. work outputs result; review accepts a results array. Authors supply real implementations and business parameter contracts.",
  "source_routes": [
    {
      "id": "dispatch",
      "event": "completed",
      "plan": "work_and_review",
      "values": {
        "jobs": {
          "$": "outputs.jobs"
        }
      }
    }
  ],
  "plan": {
    "parameters": {
      "type": "object",
      "properties": {
        "jobs": {
          "type": "array"
        }
      },
      "required": [
        "jobs"
      ]
    },
    "steps": {
      "work": {
        "node": "work",
        "each": "jobs",
        "inputs": {},
        "parameters": {
          "$": "item.params"
        },
        "ref": "work:{item.id}"
      },
      "review": {
        "node": "review",
        "inputs": {
          "results": {
            "from": "work",
            "port": "result",
            "collect": true
          }
        },
        "after": [
          "work"
        ],
        "ref": "review:batch"
      }
    }
  },
  "execution": "After the source reports completed with jobs, the platform creates work/review Tasks and schedules them when dependencies are ready. The source agent then calls finish. Include rounds in refs when repeating.",
  "verification": [
    "preview_plan",
    "test_loop"
  ]
}
```

### external_job

An external submission needs repeated status queries, then result consumption.

```json
{
  "use_when": "An external submission needs repeated status queries, then result consumption.",
  "capabilities": [
    "implementation_selection",
    "lifecycle",
    "execution_recovery",
    "event_routes"
  ],
  "configuration": [
    "An external candidate uses command for submission and observe for queries; submitted saves external_id.",
    "Observers report progress/completed or declared failure events; lifecycle defines retry/agent handling.",
    "Completion routes can generate successors; inputs/after make consumers await results."
  ],
  "loop_configuration": {
    "tool": "read_capabilities",
    "arguments": {
      "capability": "loop_configuration"
    },
    "reference": "references/loop-config.md",
    "guidance": "When sharing or moving a Loop, expose paths/services as startup inputs and provide config.example.json. Recipients adapt agents/environments with separate runtime configuration, without copying the workflow or building configuration loaders."
  },
  "author_provides": "External APIs, execution identity, status translation, artifact checks, and submission idempotency.",
  "verification": [
    "smoke_runtime",
    "test_loop"
  ]
}
```

### question_then_continue

Ask a question, wait for its correlated reply, then generate later work.

```json
{
  "use_when": "Ask a question, wait for its correlated reply, then generate later work.",
  "capabilities": [
    "notifications",
    "waits",
    "event_routes"
  ],
  "configuration": [
    "notify.reply declares event/key/schema.",
    "Create an event Task for the same event/key; received payload maps to node outputs.",
    "Its completed route expands successors using the reply parameters."
  ],
  "loop_configuration": {
    "tool": "read_capabilities",
    "arguments": {
      "capability": "loop_configuration"
    },
    "reference": "references/loop-config.md",
    "guidance": "When sharing or moving a Loop, expose paths/services as startup inputs and provide config.example.json. Recipients adapt agents/environments with separate runtime configuration, without copying the workflow or building configuration loaders."
  },
  "author_provides": "Question text, notification outlet, reply bridge, and business handling of the answer.",
  "verification": [
    "test_loop"
  ]
}
```
