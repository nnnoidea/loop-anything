# Starting and operating Runs

This is a reference for direct tool use, not a mandatory runtime procedure. If the author supplies a wrapper, follow the node Skill; wrappers still call these tools. Business requirements belong in the Loop handbook; read_task returns the node's author Skill. An awakened agent uses its existing Run and token.

If the context includes tool_url, read [Scoped tool entry](scoped-entry.md) first. The ordinary run_id/token examples here cannot be copied directly to that entry.

When receiving a Loop or adapting paths, agents, and services, use [separate runtime configuration](loop-config.md). start_run, web launch, and child Loop calls read the installed version's configuration. This call's inputs take precedence; explicit bindings replace the configured selection as a whole. Existing Runs retain their creation snapshot.

## Task progression versus execution phases

read_timeline/next_tasks show whether work is scheduled, why it is waiting, and what needs attention. read_task.execution_state and last_transition show the current execution phase, reports, and actual transitions. Task status and execution lifecycle_state describe different layers and are not interchangeable.

Use read_task for dependencies, waiting reasons, and the current execution; read_run retrieves previous parameters, implementations, lifecycles, and transition history by execution ID. A retry keeps the same Task; scheduling another round creates new Tasks. After a completion report commits results, the platform reevaluates existing downstream Tasks. finish only releases the agent's operation identity.

## Run lists, attribution, and management

The initiator is a team display name, not an account or permission boundary. Use a user-provided or already confirmed name; do not infer it from the server's OS username. Once configured on the client, start_run, start_collaboration, and request_assistance that creates standalone collaboration carry it automatically. Child Runs inherit the parent Run's attribution. An unset name does not block startup; historical records appear as unattributed.

```sh
python3 scripts/call.py profile --name tdh
python3 scripts/call.py profile
python3 scripts/call.py list_runs --arguments '{"created_by":"tdh","query":"research","sort":"last_activity_at","limit":30,"root_only":true}'
```

The caller's `.config/loop-anything/profile.json` stores the name; LOOP_ANYTHING_PROFILE can select a file, and Skill updates do not overwrite it. On creation, --created-by or arguments.created_by overrides it explicitly; LOOP_ANYTHING_USER_NAME overrides the saved default. Web launch remembers the entered name in that browser. Attribution organizes records without changing the objective or authorization. A corrupt optional profile does not block queries; creation warns and omits that default. Supply created_by explicitly or repair it with profile --name.

list_runs returns runs, total, groups (matching counts by person), loops (including archived versions represented in the matches), and next_offset, without execution history or result bodies. HTTP API revision 3 GET /api/runs returns this paginated object rather than a full array. limit defaults to 50, maximum 200. Keep filters unchanged and pass next_offset as offset for another page. Filters:

- created_by exactly matches a name; an empty string selects unattributed Runs. query searches titles, Run IDs, names, Loop names, and objectives.
- loop_key selects an installed version; loop_id spans versions of one Loop; status filters runtime status.
- sort=last_activity_at|created_at and order=desc|asc. created_from/created_to and active_from/active_to select startup/activity intervals in Unix seconds, inclusive lower bound and exclusive upper bound. Interpret dates in the user's timezone.
- archived=exclude|include|only defaults to hiding archived Runs. root_only=true lists parents; parent_run_id pages through their children. kind selects workflow or collaboration.

Activity includes dispatch, state changes, results, meaningful progress changes, and user actions. Viewing, heartbeats, check calls, and unchanged progress do not update activity. Do not bulk read_run just for summaries; select a Run, then read Tasks and records as needed.

update_run(run_id, metadata_revision, title?, created_by?, archived?) edits names, attribution, or archival, including ended Runs. Read metadata_revision from the list summary; it is separate from execution revision. Updates do not rewrite objectives, Tasks, or results. Use Timeline tools for business changes. Archival affects ordinary lists and does not stop work.

delete_run(run_id, metadata_revision) deletes the platform Run and Timeline only after it has ended, with no live execution or unfinished assistance, confirmed original-process status, and persisted remote receipts. A child cannot be deleted while its parent needs the result; explicitly handle retained children before deleting a parent. Deletion does not cascade to other Runs, stop external jobs, or delete native agent sessions or external/NAS artifacts. Full collaboration replies remain; their deleted Run association no longer advances.

Use existing draft tools to edit Loops. archive_loop(archived, key|draft_id, revision?) archives/restores a version or draft; find these with list_loops(include_archived=true). delete_loop(key|draft_id, revision?) deletes an entire draft or an unreferenced installed version; drafts require their current revision. Versions referenced by Runs or other Loops remain; archive them to hide them. Historical Runs still show their actual version. Source packages, recipient configuration, and external artifacts are not removed. If an installed directory contains runtime-generated files or user changes, the whole directory is retained; the receipt includes package_files_retained=true and retained_package_path. These files are not treated as disposable package assets.

Discover these operations through read_capabilities(capability="run_library"). Organizing a list is not restarting, recreating a Run, or editing its business workflow.

## Continuing an existing Run from any entry

Agents using different entries connect to the same platform instance and Timeline. A Run does not belong to a chat session; changing entry neither creates a Run nor requires old chat history.

1. Read a known Run ID directly. Otherwise use list_runs by initiator, keyword, Loop, status, or dates; it defaults to recent activity. Follow next_offset; see [Run management](#run-lists-attribution-and-management). Ask the user to distinguish ambiguous candidates instead of assuming the latest is correct.
2. Without a token, read_timeline retrieves current objectives, requirements, guidance, authorization, record index, Tasks, and issues. Use next_tasks, read_task, read_record, and read_plans for details; read_run for full facts/history. Reading does not acquire operation rights or stop other agents.
3. Ordinary workspace writes accept run_id without a password or manual token. The platform creates and releases a temporary identity for that call. Supply the basis from the relevant reads; only the commit transaction checks related versions and current execution state, without waiting for another agent to finish thinking.
4. Apply user requests against current revisions and task_version from read_timeline/read_task. For a sustained execution identity, explicitly acquire_run (task_id selects a branch), use the new token, and finish afterward. Platform-awakened nodes use their prompt identity and cannot widen scope through an ordinary entry. Existing history/results remain; changing the objective does not automatically invalidate old Tasks.

```sh
python3 scripts/call.py list_runs --arguments '{"query":"research","status":"running"}'
python3 scripts/call.py read_timeline --arguments '{"run_id":"RUN_ID"}'
# Ordinary edits carry the basis returned by the reads; acquire_run is optional for sustained execution.
```

read_timeline with read_only:true grants no writing rights; scope_task:null in this view does not imply global scope. With a valid token, read_only:false makes scope_task describe this identity's scope; terminal Runs and dispatched Tasks remain protected. Explicit invalid/expired tokens fail rather than silently becoming read-only.

Persist confirmed objectives, constraints, and decisions that affect later work through change_settings, change_task/build_plan/add_task, or report_task, as appropriate. Saying "remembered" in chat is not persistence. No separate cross-entry summary or full chat copy is needed. Notification destinations are independent of the operation entry; changing chat does not change them automatically.

## Think concurrently; check versions at commit

Parent, child, global, and other branch agents can think simultaneously, within Task ownership scopes. The same Task and native CLI session still cannot execute twice. A process may still be exiting after finish releases its identity. Resumed historical terminals, live registered external callers, and unfinished remote executions for the same Task also block duplicates; other Tasks continue. read_task.execution_state exposes worker_active and communication_state. Resolve an unknown process through the existing confirm-stopped recovery entry. Do not use acquire_run to block other agents or wait for their finish before editing your own work.

Reads return basis. For managed agents using their prompt token, the platform remembers versions read through read_task/read_timeline/next_tasks/read_record/read_run and validates subsequent writes automatically. Ordinary workspace calls without a sustained token must pass this decision's basis unchanged to add_task/build_plan/change_task/edit_tasks/change_settings/command. Explicit basis can select the focused reads actually used, instead of an earlier broader work list. Settings still require settings.revision; reports require task_version from the same read and a stable report_id.

Prefer read_task for one Task. Decisions such as "there is no next round" or "all work has ended" require reading the corresponding collection, not one Task. Reading the whole Timeline checks broader changes; focused reads do not conflict over unrelated branch completions or logs. Latest read_record values participate in validation; an explicitly fixed revision remains that historical value.

edit_tasks previews or commits a group with basis; legacy revision still provides conservative whole-Run validation. Conflicts return error.code=conflict with changed fields in conflicts, without partial writes. Read the changes and reconsider before resubmitting; do not merely swap in a new version. Successful writes advance the caller's observed versions. Network retries reuse report_id/stable Task keys instead of creating new work.

## When awakened by a platform command

The platform runs the user-provided command and sends a Task prompt on stdin. Use its Run, task_id, and token for this work under the user's authorization; do not create a Run. Users configure agent tools/models. Without an explicitly configured timeout, the platform does not kill the agent after a default time limit.

Use this Skill's scripts/call.py with the prompt identity. If platform_url is provided, select it with --url. Run from the Skill root, or use the script's absolute path elsewhere:

```sh
python3 scripts/call.py read_task --arguments '{"run_id":"RUN_ID","token":"TOKEN","task_id":"TASK_ID"}'
```

Replace the tool name and supply its parameters via --arguments. read_task returns author Skills and input/output requirements. Submit results with report_task(event=completed), then finish. Do not import platform modules or access its database directly.

### Completing one invocation

1. With the operation token, read_task for current task_version, output-port contracts, inputs, and author Skills. Respect scope_task: null means global scope; otherwise only that Task and descendants. Read read_timeline/next_tasks when global guidance, record indexes, or work lists are needed; focused work need not read the whole Timeline first.
2. Do the author's work. Read read_task.routes first: declared rules may only need results/parameters, after which the platform creates Tasks when accepting the event. Inspect receipt.routes; do not schedule those Tasks again. Use add_task/build_plan for ad hoc work; scheduling alone does not submit the current result.
3. report_task(event=completed) with a stable report_id, the just-read task_version, and all envelope.outputs in one submission. With routes, results and generated Tasks validate and commit together. Only ok:true and accepted:true confirm success. Correct failed submissions without duplicating downstream work.
4. next_tasks checks work/issues in your scope. After completing this Task, resolving issues, or explicitly waiting via defer_task, leave scheduled downstream work to Engine. You need not empty the list; ready children can dispatch before their parent agent calls finish.
5. finish, verify ok:true and finished:true, then exit. This releases the identity; it neither submits results nor means the Run objective is fulfilled. See terminal-state rules below.

If read_task.outputs has one string port named result, a report looks like:

```json
{"run_id":"RUN_ID","token":"TOKEN","task_id":"TASK_ID","task_version":"VERSION_FROM_READ","event":"completed","report_id":"STABLE_DELIVERY_ID","envelope":{"outputs":{"result":"Actual work result"}}}
```

Use actual port names/types. Initialization also submits the discussed envelope.settings under settings_schema. With no output ports, submit {}. Do not invent business fields by copying examples.

```sh
python3 scripts/call.py finish --arguments '{"run_id":"RUN_ID","token":"TOKEN"}'
```

Check JSON ok for every call; script failure exits with code 2. A text claim of completion cannot replace a successful receipt. If a timeout leaves the outcome unknown, read current state before choosing the next action; do not blindly resubmit or change keys to recreate Tasks. Current tools do not require seal.

When an author Skill includes resolved_path, read SKILL.md there and resolve its references relative to that directory. read_loop/read_timeline provide the Loop Skill; read_task provides node Skills. Use the agent's own tools for ordinary file reads and script execution.

## Starting with the user's own agent

1. Find the user's selected Loop with list_loops, pass its actual key to read_loop, and read the handbook, entry requirements, and implementations. Discuss/confirm objectives and authorization.
2. start_run with key, title, discussed inputs, and natural-language authorization. It returns run_id, token, and entry_task_id. The caller already owns this initialization identity; Engine does not initialize it again.
3. read_task with run_id/token/task_id=entry_task_id for requirements and task_version.
4. For an agent entry implementation, report_task(event=completed) submits complete envelope.outputs and agreed envelope.settings under the returned contracts. Do not invent fields. Entry results persist. A script entry runs through Engine; read its results rather than authoring script outputs yourself.
5. Continue with task/issue and construction tools below, then finish.

An Engine-awakened agent already has a Run/token and skips creation. Prompt/read_timeline.scope_task determines its scope.

## Branch ownership and operation scope

- With a valid operation token, scope_task=Task ID grants that subtree; null grants global scope. Ordinary node agents own their branch; initialization, fallback, and an explicitly configured global_agent_node have global scope.
- parent_id represents Task ownership, independent of input sources and after. Tasks sharing a Node template may be separate branches. Reading a sibling's result does not grant write access.
- add_task/build_plan attach new work to scope_task by default; global agents default to the awakening Task. Specify an in-scope parent_id to choose a parent; global agents may pass an empty string for a top-level Task. Parentage is immutable. A shared aggregation belongs to an upper-level creator, not every branch whose outputs it consumes.
- Ordinary agents can change inputs, parameters, implementation, and dependencies of undispatched Tasks in their branch. Global settings, Run pause/end, and user-request handling need global scope. Dispatched Tasks remain protected.
- Parent, child, global, and branch identities may think concurrently; commits validate versions/state and same-Task execution stays exclusive. acquire_run without task_id registers global identity; with task_id it registers that subtree. It does not preempt an existing executor.
- After the awakening Task and in-scope issues are handled, finish and leave later agent Tasks to Engine for parallel dispatch. They need not all complete in this session. finish releases only the caller's token.

These are platform-tool checks, not OS isolation. External files/services use user configuration. Authors needing concurrent file edits should use separate working directories or explicit serial dependencies.

## Common runtime operations

- next_tasks/read_timeline show current work, issues, authorization, and the Loop handbook. read_timeline.records lists IDs, types, and latest revisions; read_record fetches bodies. Healthy running/waiting scripts do not need agent takeover.
- For each actionable Task, read_task first, then report_task(event=completed) with full results under current contracts. Results take effect immediately. Do not submit script, event, or approval results on their behalf.
- read_plans lists templates; build_plan takes name, stable key, and values. It schedules unconditional/true-when steps; steps.<step>.skip=true explicitly omits one. Omission creates no Task, skipped placeholder, or fake output. Receipt.omitted and scheduling records explain why. Consumers must explicitly supply reusable input sources for omitted producers. Reusing a key requires identical parameters/scheduling; it cannot silently withdraw prior Tasks. Explicitly cancel unnecessary existing Tasks while preserving facts.
- edit_tasks groups changes using this decision's basis (legacy revision can conservatively validate the whole Run). changes is an ordered list of {"tool":"add_task","arguments":{...}}, using add_task, build_plan, or change_task. preview:true returns before/after Tasks, actual generated IDs, and omission reasons without persistence/dispatch. Commit with the same basis and preview:false; any failure rolls back the group. The commit receipt returns only run_id, revision, and applied; read the Timeline for details. Preview respects scope. To add a successor to a freshly expanded batch, obtain IDs from preview.changes[].after, add them to add_task.after, and preview again; do not duplicate the ID-generation algorithm. This transaction excludes report_task, change_settings, and finish; a helper's multiple calls are not one transaction.
- If the authored business has rounds, build_plan accepts round. It organizes display, not serialization or progression timing; do not impose rounds on unrelated work.
- add_task schedules one declared nonentry node with stable key, node_id, inputs, and optional parameters, implementation, after, and round. It returns a Task ID and allocated output record IDs for later references; do not handwrite whole Tasks.
- change_task edits undispatched inputs, parameters, implementation, and after (predecessor Task IDs). Check external side effects before retrying; healthy scripts are not repair targets.
- change_settings updates authorized requirements with the just-read settings.revision. command supplies supported pause, resume, and pause-point release operations.
- If current authorization is insufficient, defer_task with the specific user input needed. Do not fake success or expand authorization.
- After writes, reread next_tasks. Once this Task and in-scope issues are handled or explicitly waiting, finish. The old token expires immediately; Engine handles scheduled successors.

An added/edited cyclic dependency rejects the entire write without partial Tasks/results. Read current Tasks and sources to correct it. A looping workflow does not mean one runtime batch may wait cyclically on itself.

## Selecting node implementations

read_loop.implementations contains candidates/defaults. Multiple candidates use {options:{ID:configuration},default:ID-or-null}; a single legacy implementation abbreviates a default candidate named default. Do not copy a Loop to switch candidates.

- start_run.bindings maps nodes to candidates, e.g. {"train":"cluster"}. Omitted nodes inherit Loop defaults; null leaves selection unset.
- change_settings.change.bindings changes Run selection with current settings revision. It replaces the whole mapping; retain other desired overrides.
- build_plan.steps.<step>.implementation selects for that batch; an empty string restores Run inheritance. change_task.implementation changes an undispatched Task, or accompanies retry to switch a failed Task after checking side effects. Empty restores inheritance.
- Task override wins over Run selection, then Loop default. read_task returns candidates, current selection, and task_version; reread after changes before reporting.

Dispatched executions retain their chosen configuration. No candidates/default does not prevent Run creation; missing_implementation is reported only when execution is needed. Make a real selection or wait explicitly for the user, without fabricating results.

## Optional agent fallback

read_loop returns fallback_node. start_run may override it; an empty string disables it for that Run, omission inherits the Loop. During a Run set change_settings.change.fallback_node to an ID or null. Its bindings select the fallback agent; commands are not borrowed implicitly from another node.

Fallback is an ordinary declared node. read_task returns its Skill, output contract, and entry cause in origin. Resolve the issue, report_task(event=completed) for the fallback Task itself, then finish. Other authorized global agents may help, but one executor completes the fallback Task. Global/branch identities coexist; commits check related versions while healthy scripts continue.

## New user requirements during a Run

Follow the continuation procedure: read current state, let the platform establish ordinary call identities, or acquire_run for a long operation. Other agents thinking do not block edits; commits validate dependencies and same-Task execution remains exclusive. Changing requirements does not invalidate old Tasks, approvals, or results. The user decides what should change; explicitly cancel/edit with change_task under authorization, pausing progression first if necessary. Pending approvals can be canceled; canceling a dispatched script does not prove external work stopped. Preserve results/provenance, check current work/issues, and finish.

On tool errors, read error and current state: reread read_task for input-version changes, read_timeline for Timeline changes, and output contracts for missing fields. Do not bypass an error by creating another batch or Run.

## Engine advances terminal states

The objective lives in the Timeline. Both completion paths use change_settings, then Engine advances the terminal state. Task queries neither decide completion nor create completion-decision Tasks.

- Mechanical completion: set completion_rule using deterministic expressions eq/le/ge/add/len/and/or. path is a dotted string or path-segment array. Roots: settings, inputs, records (latest formal value per record ID), completed (completed Task counts per node), and active_tasks (unfinished business Task count). and/or short-circuit in order. A missing record only defers the rule if evaluation actually visits it; type errors become real issues.
- Agent-decided completion: set termination_signal to the reason. Engine marks the Run completed and records the reason and Timeline revision. This completion signal differs from command(action=terminate), which aborts as terminated.

For at least two review completions and no other in-flight business work:

```json
{"completion_rule":{"op":"and","args":[{"op":"ge","args":[{"path":["completed","review"]},2]},{"op":"eq","args":[{"path":"active_tasks"},0]}]}}
```

Use actual node IDs/business conditions. For dotted record IDs, use segments, e.g. ["records","metric.round-2","score"]. Avoid unintentionally cutting off required work; include in-flight completion in the condition when needed. Terminal states cancel unfinished Tasks and reject later reports without undoing external side effects.

No Tasks does not mean completion. finish only releases this identity, not the Run. After writing a termination signal, release it and let Engine apply the terminal transition. Do not create terminal nodes or extra completion-decision Tasks.

set_loop.global_agent_node, start_run.global_agent_node, or change_settings.change.global_agent_node can select a normal global decision node using its existing agent implementation. Empty defaults to fallback. This eligibility does not create Tasks or start agents; fallback still requires explicit enablement.

## Notification destinations

read_notification_channels lists configured outlets. Select the Run default through start_run.notification_route or change_settings.change.notification_route. workspace means the platform notification area. All entries share this setting; changing chat does not change it. Personal delivery configuration lives in the platform/Run, not the Loop definition.

See [notifications.md](notifications.md) for notifications, questions, replies, and adapters. notify uses the current identity; branch agents associate their task_id. Do not add a business Task merely to send a message. Retries keep the same key/content. A question does not pause other work; schedule a wait node if its answer is required, finish current work, and release the agent instead of holding it open.

read_task.execution_state.wait shows actual wait times, event correlation, and deadlines. send_event supplies replies/events with stable event_id and payload matching the waiting node's outputs. Duplicate events do not advance twice. Existing change_task cancel can cancel time/event waits without retracting completed outputs.

## Agent exits and failure notifications

After a platform-started agent command exits, an enabled fallback is awakened through the same operation rules if the Loop still has issues. Without fallback, issues remain; no agent is selected automatically. An initial failure plus two retries pauses after three consecutive failures and automatically requests notification. Branch handoff retains the initial failure count; successful resolution clears it, and explicit user resume starts a fresh count.

Explicit pause or waiting for user input is not failure. If the old command cannot be confirmed stopped, its execution identity remains. Interactive agents likewise require confirming the old process stopped before the existing recovery entry can resume them.

Notifications use the outlets above. Nonzero exit, timeout, or unconfirmed delivery records failure. An explicit unconfigured outlet records waiting_configuration until configuration/retry, without counting as unexpected or triggering fallback. A default outlet without a send command uses the platform notification area. Pre-execution notifications run alongside work; a pre-execution pause blocks its Task until released. Ordinary notifications use the Run default; new Runs without an external outlet use workspace, which can also be selected explicitly.

Branch failure counts remain separate. Global fallback inherits the longest unresolved branch chain, not the sum of parallel failures. Resuming clears these counts. One agent's exit does not release another's identity. Unknown process status blocks a second executor for the same Task/native session, while other Tasks continue.

## Unified event and result reporting

report_task takes task_id, event, and stable report_id. Agents first read_task for the actual lifecycle, phase, and last_transition, then include current task_version. Scripts/observers use execution_id from their context. Ordinary workspace calls supply run_id and may omit token; awakened nodes must use their prompt token, while scoped tool_url supplies identity automatically. completed includes all envelope.outputs, plus settings for initialization. progress and similar events use detail without prematurely publishing results or scheduling work.

```json
{"task_id":"TASK_ID","task_version":"VERSION_FROM_READ_TASK","report_id":"STABLE_DELIVERY_ID","event":"completed","envelope":{"outputs":{"result":"Actual result"}}}
```

Check ok=true and accepted=true. A well-formed but uncovered event returns accepted=false and preserves the original state, event, and issue reason. Inspect current work/rules before retrying. If a network receipt is unknown, retry with the same report_id/content. An identical report does not duplicate results; changed content requires a new ID. Expired execution/operation identities cannot write again.

Scripts read JSON context from stdin; report_client is the absolute path to this Skill's scripts/report.py. Invoke it as a CLI or import report from that path:

```python
import importlib.util, json, sys
context = json.load(sys.stdin)
spec = importlib.util.spec_from_file_location("loop_report", context["report_client"])
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
# Submit after completing and verifying the business work; process exit alone is not business success.
client.report(context, "completed", report_id="final", envelope={"outputs": {"result": "Actual result"}})
```

Alternatively: `python3 REPORT_CLIENT completed --context context.json --data @report.json`. Authors can wrap this integration in existing scripts without changing remote services.

Asynchronous submission reports submitted with external_id and optional poll_after seconds. Observers use context.external_id and report progress (detail) or completed (envelope); only confirmed business failure is failed. Query failure differs from business failure; the query script may raise an exception recorded as check_error. Authors may explicitly route check_error to agent for enabled fallback; otherwise the issue remains. change_task retry after query failure resumes observation of the original external job in its pre-handoff monitoring state, without simultaneously changing inputs/implementation. For confirmed failed work needing resubmission, use normal Task retry after checking side effects.

Legacy complete_task remains a completed-report alias; legacy JSON stdout results enter the same transition handling. After direct tool calls, stdout may contain ordinary logs; tool receipts are authoritative. Completion does not release an agent identity; finish remains required.

### Transitions and duplicate reports

The matrix decides whether current state plus event can transition; report_id identifies the logical event within one execution. Identical concurrent/retried reports are accepted once; state validation, result writes, receipts, and completion hooks share a transaction. Reusing an ID with different content fails. A send retry must reuse its ID; a new ID denotes a new event.

A matrix row is not limited to one use per Run. Progress may self-loop, and after leaving and reentering A its outgoing edges can apply again. Once A is left, new events match current-state rules, not A's old edges. Completed Tasks reject new reports. The matrix does not support arbitrary state-entry actions or notification configuration. Existing hooks deduplicate by hook/Task; repeated state observation is not a way to notify once per reentry.

### Task revisions and execution attempts

New Tasks start at revision 1. Changes to inputs, parameters, implementation, or after increment it; same-configuration retries, observation recovery, and no-op edits do not. change_task/read_task return task_revision. Concurrent reports still use the freshly read task_version, not the integer revision.

Each execution saves task_revision, task_spec, and actual input/parameter/implementation snapshots. Attempt 2 may still use revision 1; changed parameters can make attempt 3 use revision 2. History preserves before/after revisions, configuration, reason, and identifiable actor, not tokens. Consumers keep the same Task ID/output location; they are not rebuilt automatically.

Run default implementation or input-record changes do not rewrite the Task declaration or increment its revision. Executions separately save their selected implementation, settings revision, and consumed record versions. Old history without revisions is marked unrecorded; tracking begins with later edits/executions, without reconstructing history.

### Recovery scheduled by the state machine

A report returning state=retry records a retry transition and puts the Task in retrying. Application waits for the original process to exit and its identity to release. read_task.execution_state.retry exposes pending/applied/blocked/superseded and resolved parameters. Agents still finish after reporting. An explicit transition to agent also permits finish to hand this issue to configured fallback; other unresolved issues retain scope rules.

Do not add_task as a substitute for retry. Replay the same report_id/content; applied transitions do not reapply parameter changes/resubmission. After restart, if old-process outcome is unknown, verify it stopped and check external side effects before change_task retry. The platform does not automatically risk resubmission. Automatic/manual recovery share Task revisions, parameter contracts, and scope.

An observer receipt with stale:true means its check ended or recovery/retry replaced its credentials; the report remains evidence only. Bundled report.py returns this as an ordinary stale receipt. Stop that old check and do not advance state; incorrect credentials still fail.

Execution failure_kind=command_start means command/cwd startup failed; agent_command means an abnormal agent command. Neither proves external training/business failure. Read the raw error and actual cwd; check command and agent trust/login configuration without changing trust or resubmitting external work on your own.

## Discovering capabilities and Task references

read_capabilities returns current service capabilities and tools/docs without acquiring operation rights. The current entry's list is authoritative. Scoped entries permit only their listed tools; do not change addresses to bypass scope. Background context.platform gives version/capability identifiers.

resolve_refs resolves stable Task refs to Task IDs/output records. add_task.ref/after_refs and task_ref/task_refs input sources resolve to actual dependencies at write time. build_plan/route receipts also return references. See [contracts.md](contracts.md).

The platform provides live output and optional CLI interaction terminals; see [execution terminals](terminal.md). Do not build separate log pages or interaction services.
