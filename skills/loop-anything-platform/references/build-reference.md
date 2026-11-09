# Authoring tools and integration contracts

Start with capability mapping in [build.md](build.md). This reference covers fields and integration steps; consult only the current operation. Live service list schemas are authoritative.

Jump to [editing](#basic-editing), [Skill files](#author-skill-files-and-references), [conditional steps](#optional-steps-arrange-only-when-conditions-hold), [runtime wrappers](#simple-entry-points-for-runtime-agents), [result display](#generic-result-display), [existing designs](#modify-an-existing-design), [parallel scopes](#parallel-branches-and-global-decisions), [lifecycles/retries](#execution-lifecycle-and-attached-monitoring), [wait nodes](#platform-wait-nodes), and [runtime verification](#runtime-verification).

## Basic editing

- **Start/reuse:** list_loops finds assets and read_loop reads actual definitions. create_loop creates a draft/common entry. copy_loop copies an installed version to a draft; for ordinary revisions use new_version:true to preserve Loop ID and select a later version automatically, without changing Runs. Ordinary copy is for an explicitly separate Loop.
- **Business handbook:** set_loop writes the author's handbook, purpose, default startup inputs, and explicit runtime limits. Platform Skills do not own business content.
- **Nodes:** put_node writes responsibilities, ports, and optional author Skills. `skills:[{"name":"Method","content":"Author-provided method"}]` binds content returned when agents read tasks. Port lists use name plus type, or schema for nested contracts; output record types are generated. Use assertions, such as eq over values, for mechanical completion constraints; constraints do not fill results. Entry-port changes update initial locations.

Optional node description is a short user-facing purpose: what it does and delivers, without API fields, commands, port lists, or repeated rules. instructions/skills retain full execution requirements, folded in the web view. Store nodes.<id>.description directly or use put_node(description=...). Empty clears the introduction without changing instructions. An absent description is not extracted, truncated, or rewritten from instructions and does not block building/running.

- **Reusable batches:** put_step adds a node to a named plan. implementation optionally fixes a candidate, but normally leave selection to Run/Task bindings. plan_parameters declares runtime parameters; each points to a list. connect_steps connects output/input; collect:true gathers expanded results.
- **Initial/reused inputs:** use explicit put_step.inputs sources such as `{"record":"initial.result"}`. Obtain real entry-output locations from read_loop rather than guessing. Use literal for values and `{"literal":{"$":"values.parameter"}}` for substitutions; item refers to list elements.
- **Candidates:** set_implementation takes node_id, implementation_id, and agent/command/external/event/timer/approval configuration; Loop calls are described in [loop-calls.md](loop-calls.md). Add several candidate IDs per node. default:true selects the Loop default, false clears that candidate's default status, omission preserves selection. Existing candidates can update selection with only ID/default. Provide real argv; external also needs observe. unbind:true removes a candidate, not a fake simulated implementation. put_asset attaches authored scripts/docs.
- **Optional fallback:** establish whether the user wants agent recovery. If so, create a nonentry node with inputs:[], recovery responsibilities and author Skill; bind an agent candidate and set_loop.fallback_node to its ID. Empty string disables it. It reads issues through Run tools and uses ordinary node reporting. Never select another node's agent implicitly.
- **Notifications:** configure lifecycle notify arrays or call notify from scripts/agents, using default routing. Users configure/select actual platform/Run outlets. See [notifications](notifications.md).
- **Completion:** authors explain goals/evidence; runtime agents write mechanical rules or termination signals to Timeline settings. Do not add node terminal flags.
- **Agent commands:** set kind=agent and user-provided command such as `["codex","exec","-"]`; set cwd/timeout explicitly as needed. An omitted agent timeout is unlimited; script commands default to 60 seconds. The platform supplies a prompt on stdin and runs argv unchanged, retaining user model/tool/permission choices. No special launcher or tool registration is needed.
- **Recipient configuration:** packages include config.example.json; authors can provide an explained template with put_asset. Recipients adapt paths/agents/services with read_loop_config/set_loop_config. New Runs snapshot configuration; see [configuration](loop-config.md).
- **Verify/deliver:** validate_loop checks structure and separately lists missing implementations. Continue saving the draft after fixes. Publish when the user wants a locally usable version or to run it. publish_loop(auto_version:true) manages versions/reuses identical content and returns current draft_id/revision. export_loop includes assets; client --output FILE.loop.zip saves it.

New Loops have an agent entry without inputs or mandatory outputs. After discussing the goal, the user agent takes the entry through start_run, submits goals/requirements/constraints in completion-envelope settings, arranges work as needed, and finishes. Do not copy conversation into a request form or invent an initialization result. Add ports explicitly when business inputs/shared initial results are needed. An agent candidate without command is operated by the current user agent; automatic wake-up requires the user's chosen command.

Every edit includes draft_id and the latest returned revision. Reread/reassess conflicts instead of overwriting. Tools return validation; incomplete drafts can be saved, but structural errors must be fixed before publication.

## Author Skill files and references

Preserve an author's SKILL.md, references/, and scripts/ relative structure. Attach files with put_asset or existing directory-asset packaging.

- Loop Skill: set_loop.handbook_path binds a package entry such as skills/research/SKILL.md. An inline handbook introduction may remain; empty clears the file binding.
- Node Skill: put_node.skills accepts `[{"name":"Review method","path":"skills/review/SKILL.md"}]`; inline content remains supported.
- validate_loop checks bound entry files are attached before publication. Authors include referenced resources; Markdown is not automatically scanned/rewritten.

handbook_path is a tool argument stored as loop_definition.handbook.path. Direct loop.json edits use `"handbook":{"path":"skills/research/SKILL.md"}`, optionally with an instructions introduction, not a top-level handbook_path field. Node bindings are loop_definition.nodes.<id>.skills[].path. Verify the actual binding resolves to registered assets; parseable JSON or file existence alone is insufficient.

Installed read_loop returns resolved_path for Loop/node Skills; read_timeline returns the handbook's path and read_task the node Skill's path. Read files directly and resolve references/scripts relative to their directory. path is the package binding; resolved_path is a read result, never written back into the definition.

## Event-triggered task generation

Define a plan, then bind source-node routes with put_node. Omission preserves, a supplied array replaces, and [] clears. This maps research output parameter sets into experiments plus aggregation; research must declare requests as an array output:

```json
{
  "draft_id":"ACTUAL_DRAFT_ID", "revision":12, "node_id":"research",
  "routes":[{
    "id":"run_experiments", "event":"completed", "plan":"round",
    "values":{"experiments":{"$":"outputs.requests"}}
  }]
}
```

The corresponding round plan:

```json
{
  "parameters":{"type":"object","properties":{"experiments":{"type":"array","items":{"type":"object"}}},"required":["experiments"]},
  "steps":{
    "experiment":{"node":"experiment","each":"experiments","inputs":{},"parameters":{"$":"item"}},
    "review":{"node":"review","after":["experiment"],"inputs":{"results":{"from":"experiment","port":"result","collect":true}}}
  }
}
```

Research only reports `report_task(event=completed,envelope.outputs={requests:[...]})`. The template binds Task parameters for commands; do not separately handcraft IDs, dependencies, or aggregation lists. Initialization can use routes and submit settings/business outputs together.

| Route field | Meaning |
| --- | --- |
| id, event, plan, values | Required: unique rule ID within the node, lifecycle-report event, existing plan, parameter object |
| each | Optional report-context array path, e.g. outputs.groups; one plan batch per item, zero for an empty array |
| when | Optional deterministic boolean evaluated per item before triggering; false omits, missing fields/nonbooleans error |
| steps | Optional build_plan-style input/parameter/implementation/skip overrides |
| round | Optional display label with interpolation such as `{item.name}` |

`{"$":"outputs.requests"}` preserves types; strings can interpolate `{parameters.name}`. Context includes inputs, outputs (completed business outputs), parameters, settings (including current initialization settings), detail, attempt, task_revision, task.id, task.node, task.outputs (output destinations), and transition.from/event/to. each adds item/index; without each they are null/0. No operation tokens or arbitrary Run internals are exposed here.

Use `when={"path":"outputs.decision.again"}` or `each="outputs.groups"` with `when={"path":"item.enabled"}`. route.when runs before mapping, so omitted items need not supply later fields. Plan step.when reads batch values and runs before step.each. Route steps expand once in report context; resulting business data is passed unchanged, without reinterpreting embedded braces or $. Direct build_plan steps still use values/item/index. Overrides may select declared candidates, parameters, or omission; consumers of omitted steps require valid alternatives.

Only events accepted by the current execution lifecycle trigger routes, across agents, commands, external jobs, timers, and events. Declare custom lifecycle transitions first, then use report_task.detail. Routes do not subscribe to arbitrary system events; receive those through a matching event Task and its completed report.

The report transaction validates all matching rules/batches and envelope.tasks: parameters, implementations, task budget, output destinations, and dependencies must pass before results/tasks commit. Generated tasks are descendants of the source. Routes are themselves author declarations, independent of script plan_nodes permission. Cycles may generate new Tasks; actual Task dependencies cannot cycle.

Failure leaves no partial generated Tasks. Tool callers can fix/re-report; scripts/timers follow existing error reporting; event delivery records rejection. Invalid rules on a platform-generated error produce a visible fault rather than recursive errors. Identical execution/report_id/content returns the original receipt; conflicting content errors, and stale monitor reports do not trigger routes.

Receipt routes lists rule IDs, plans, batches (IDs, Task IDs, omissions), and omitted_items (false-condition indices). Timeline logs route_fired; Task origin includes source execution, route_id, report_id, plan, batch_id. Nodes without routes retain behavior. Helpers must not recreate these successors. Existing Runs retain definitions; saved changes affect new Runs.

## Optional steps: arrange only when conditions hold

put_step.parameters can use `{"$":"values.options"}` for a complete Task parameter object, or item during expansion. Call-time steps.<step>.parameters overrides selected fields: expand both objects, then merge top-level keys with current values winning and nested objects replaced whole. Both must resolve to objects. No field-copying helper is needed. each uses a values-relative list path, e.g. experiments; $ references use values/item/index.

put_step.when uses deterministic expressions over batch values only. Example `{"path":"values.action.stages.prediction.enabled"}` creates Tasks only for true; false creates neither Tasks nor output placeholders. Omission preserves the condition; when={} clears it; direct definition editing removes the field.

The condition is evaluated once during build_plan for the entire step before each, not against runtime results or individual items. Missing fields, invalid expressions, and nonbooleans error rather than mean false. Explicit steps.<step>.skip=true takes precedence for this invocation.

Consumers of omitted outputs are rejected unless given valid reused input or also omitted. Order-only dependencies follow existing omission behavior, without placeholders. Preview/receipts explain omissions. A business output named status does not change Task state.

## Simple entry points for runtime agents

Prefer routes for result-triggered plans. Package wrappers are for genuinely repeated business adaptations/compositions. Add scripts/instructions with put_asset and bind skills[].path, without registering new tools. Document commands, parameters, receipts, and error handling; business rules remain author-owned.

Wrappers call the same HTTP tools or call.py and read actual address/Run/Task/token from wake-up context. Do not hardcode local paths or copy the Timeline. Background nodes use platform_url with run_id/token. A provided tool_url is already identity-bound; follow [scoped entry](scoped-entry.md), without those fields in arguments. Read resolved_path directly and resolve references/scripts relative to its directory.

Reread required versions, check every receipt, and return actual submission outcomes. Reuse edit_tasks preview/atomic commit for grouped edits. Reports and independent task edits are separate transactions: if complete_task succeeds and build_plan fails, do not rerun completion from scratch. Use stable arrangement keys, retain completed receipts, reread Tasks/plans, and skip committed steps on recovery. A few known successors may be submitted in completion-envelope tasks; batched successors use atomic routes. Recover separate calls according to their actual boundaries. Required outputs and finish still apply; scope/version/output checks remain enforced.

Agent candidates support a shared prompt string alongside command. set_implementation can edit prompt alone. Example:

```text
Read the author instructions in this context's skills and use their packaged scripts to perform the work.
{{context}}
```

Only {{context}} expands to JSON; other text is unchanged, with no hidden appended instructions. Omission uses the platform prompt; an explicit empty string means an empty prompt. Defaults direct agents to author entry points and platform references only when generic operations are needed. Background context includes run_id, execution_id, task_id, token, scope_task, platform_url, platform_client, platform_guide, loop_key, handbook, node_id, instructions, skills. See [scoped entry](scoped-entry.md) for its additional context.

## Generic result display

The platform renders structured results as text, fields, and tables; do not rebuild a viewer. Use schema title/description to explain fields; business field names are not interpreted. Runtime round explicitly groups work; workflows without rounds need not provide it.

File outputs use `schema:{"type":"string","format":"file"}` and an actual path value. Relative paths resolve under the attempt's cwd, or the installed package if cwd is absent. Files must be inside that directory. The platform previews images/provides file access, errors on absent files, and does not treat arbitrary strings as files or retain external file history. Use distinct filenames per execution to keep older artifacts.

## Modify an existing design

1. Match loop_id across versions/drafts with list_loops and continue the current draft. revision/updated_at identify ongoing work; a new conversation is not a reason to copy the Loop.
2. Read the needed object and edit against its latest returned revision. Unfiltered read_loop still returns the complete definition for initial orientation.
3. Inspect changes with field paths and actual before/after; additions omit before, deletions omit after. Asset receipts report size, executable, content_changed, not full bodies. validation.valid=false means not publishable, not a failed save.
4. Fix validation.issues paths and validate again. errors retains text; issues locates the first encountered structural problem, not necessarily every error. Publish only when needed; old Runs do not migrate.

Targeted queries use read_loop with either draft_id or installed key:

| Object | Extra arguments |
| --- | --- |
| Node, implementations, output types | node_id |
| One candidate including lifecycle | node_id, implementation_id |
| Plan | plan |
| Step | plan, step |
| Script/Skill asset body | asset_path |

Results include value/references and draft identity/revision or installed key. references finds declarative uses: plan nodes, consumed step outputs, bound Skills, and command arguments referring to package files. It does not analyze scripts or indirect Markdown references. Text assets return UTF-8; binary assets use encoding=base64. Installed versions are read-only; edit via drafts.

Change only an existing candidate's command:

```json
{"draft_id":"DRAFT_ID","revision":12,"node_id":"train","implementation_id":"local","command":["python3","scripts/train_v2.py"]}
```

set_implementation changes supplied fields only, even when kind is repeated. Omitted prompt/cwd/timeout/lifecycle remain; editing a candidate does not change its default selection implicitly. Use default:true explicitly. clear:["timeout","prompt"] removes optional fields; the same field cannot be cleared/set together. Empty prompt sends empty content; clear prompt restores the platform default.

Optional object parameter_schema constrains a candidate's Task parameters in addition to the node contract. Read it through targeted read_loop. Omission preserves it; clear:["parameter_schema"] removes it. Validation never injects defaults.

Adding, batching, editing, and retrying validate against the effective implementation: Task selection, then Run binding, then Loop default. Changing Run bindings leaves incompatible unexecuted Tasks waiting for correction, not starting with invalid parameters. Dispatched attempts keep their contract. Tasks can be arranged unbound and checked after selection. Fallback uses empty parameters, so its candidate cannot require private fields; read context through Timeline tools.

A kind change requires a new lifecycle or clear:["lifecycle"] for the kind template, plus explicit removal of incompatible old fields. Tools never silently delete author content. For example, clear agent prompt when changing to a real command implementation.

Collections are preserved when omitted and wholly replaced when supplied: ports/Skills, step inputs/after, and lifecycle all follow this rule. Read first; one element is not an append. connect_steps edits one connection without rewriting other inputs.

Read assets by asset_path and write with put_asset.content. Omitted executable retains permissions. Delete with put_asset(path="PACKAGE_PATH",remove=true), without content/executable. Deletion does not cascade through nodes/Skills; drafts may temporarily have missing references but must be fixed before publishing. Inspect both references and actual script uses.

Deleting nodes/outputs removes generated node.port record types that lost their final output reference in this edit. Shared types, published versions, and Runs remain. validate_loop.unused_records lists other unused types; remove explicitly with set_loop.remove_records after checking. Referenced types cannot be removed.

Unspecified template inputs remain missing, not empty-filled. Inspect step sources and receipt locations to repair absent/deleted upstream references. Validation checks declared contracts; authors determine additional business needs.

remove_step requires consumers handled first; deleting the last step also requires removing routes that use its plan. remove_node requires removal of referencing steps. Change references before deletion. Continue the same draft; publish for a usable version and export for sharing.

Routes declare cyclic task generation, plan_nodes permits explicit script arrangements, and concrete dependencies remain acyclic. Loops may be built/shared/installed and Runs created with missing implementations; selection is required for actual execution. Authors supply scripts/environments; paths/dependencies are not automatically repaired. See [run.md](run.md); definition editing differs from changing an active Timeline.

## Parallel branches and global decisions

Agents normally arrange work in their own Task branch; one node template can serve several parallel Tasks. parent_id expresses ownership, while inputs/after express dependency. Common aggregation is arranged by the shared ancestor. Later steps reuse existing nodes/plans.

For a normal decision node that needs whole-Run scope, set global_agent_node and provide an agent candidate. Initialization and fallback also have global scope. Ordinary branches should produce separate results and explicit aggregation rather than coordinating by overwriting one global record.

## Execution lifecycle and attached monitoring

Storage and transition calculation are separate: Timeline stores facts/state/history; the generic state machine evaluates lifecycle rules; the platform commits state/results/matching arrangements together. Authors still use set_implementation, routes, and report_task; existing Loops need no migration, state store, or internal transition calls. External identity, observation times, and check errors remain separate; waiting alone does not prove monitoring is healthy.

Candidates determine sync/async execution. set_implementation stores an explicit lifecycle:{initial,transitions} template, readable/editable through tools. Templates are not business decisions. Old packages without lifecycle remain unchanged; views show the kind template and dispatch snapshots the actual rules.

Rows are {from,event,to}. Multiple rows for one state/event require distinct when conditions, with exactly one runtime match; row order is not priority. Expressions read inputs, parameters, settings, detail, outputs, attempt (one-based execution count), task_revision. State/event IDs allow letters, numbers, underscores, hyphens. initial starts the attempt; completed/fault/retry/agent are exits, not ordinary stages with outgoing transitions. retry starts another attempt of the same Task. agent uses the configured fallback or leaves an issue. completed requires a completed event with every output, passing outputs/assertions validation. Lifecycle describes an execution stage; the Task may wait for inputs, scope, or pause points before execution.

Commands generally use executing → completed/fault. An external candidate combines command submission with attached observe monitoring of the same external_id/Task/attempt. Report submitted/progress/completed/failed through report_task. Monitor process failure produces check_error; by default it preserves external state, stops checking, and exposes an issue. Resume observation after repair without resubmission. Authors may add stages/events; uncovered reports preserve state/event and enter explicit issue handling rather than guessed transitions.

process_error covers platform-detected missing delivery, nonzero exit, timeout, etc. Later process exit does not retract committed success. Scope/version/output/live-process protection cannot be bypassed through matrix edits. Normal waiting is not automatically failure. Without fallback_node, issues remain visible; with it, existing scopes and three-failure handling apply.

See [reporting](run.md#unified-event-and-result-reporting) for script integration. Helpers may wrap tools, but business facts/results still require real verification. History supports diagnosis and optimization suggestions, not automatic Loop rewriting.

### Declare recovery in the matrix

`to:"retry"` reuses the Task. Optional parameters overrides listed top-level fields, retaining others; nested values replace whole objects and existing $ references apply. The platform validates complete parameters against node/effective candidate before recording the match. At retry it rechecks current contracts/budgets and atomically applies parameters, Task revision, and retry record. Unchanged-parameter retry does not increment revision.

Use attempt expressions, e.g. `{"op":"le","args":[{"path":"attempt"},2]}` for the first two attempts and ge 3 afterward. An unconditional failed → fault does not become automatic retry by itself. Replace the original event row when adding branches to avoid overlapping an unconditional row. Retry/handoff are visible in configuration and execution details.

Example for an existing command candidate: first failed attempt retries unchanged, second retries with batch=8, third and later hand off. batch is illustrative; use an actually permitted field/value satisfying contracts. This policy is not enabled by default.

Read draft_id/node_id/implementation_id first, confirm kind=command, and use the current revision. Save the following as recovery.json with real identities/revision. Omitted command and other fields remain:

```json
{
  "draft_id": "ACTUAL_DRAFT_ID",
  "revision": 12,
  "node_id": "train",
  "implementation_id": "local",
  "lifecycle": {
    "initial": "executing",
    "transitions": [
      {"from": "executing", "event": "progress", "to": "executing"},
      {"from": "executing", "event": "completed", "to": "completed"},
      {"from": "executing", "event": "process_error", "to": "fault"},
      {"from": "executing", "event": "failed", "to": "retry", "when": {"op": "eq", "args": [{"path": "attempt"}, 1]}},
      {"from": "executing", "event": "failed", "to": "retry", "when": {"op": "eq", "args": [{"path": "attempt"}, 2]}, "parameters": {"batch": 8}},
      {"from": "executing", "event": "failed", "to": "agent", "when": {"op": "ge", "args": [{"path": "attempt"}, 3]}}
    ]
  }
}
```

Run at the Skill root or use an absolute script path:

```sh
python3 scripts/call.py set_implementation --arguments @recovery.json
python3 scripts/call.py validate_loop --arguments '{"draft_id":"ACTUAL_DRAFT_ID"}'
```

Check edit ok:true and validation valid:true, reread the saved lifecycle, and use the new revision for later edits. This only saves a draft; it does not publish/start/change existing Runs.

attempt counts all executions of that Task, not consecutive failures. Parameter changes preserve Task ID/downstream references and increment revision only if values actually change. agent needs explicit fallback_node and a usable candidate or leaves an issue. The example retries actively reported failed only; missing reports/nonzero exits remain process_error → fault under original fallback handling, not these attempt branches.

Lifecycle is replaced whole. Preserve unrelated stages/rows when changing failure behavior. Do not apply this executing matrix directly to external: modify its actual submitting/waiting failure states while retaining submitted/check_error rows.

Zero/multiple matches, expression errors, or invalid retry parameters become explicit issues. process_error may go to fault/retry/agent, but automatic retry waits for confirmed process termination. check_error means observation failure only; it cannot complete/fault/retry or resubmit external work. It may explicitly hand off to enabled fallback. Resumed observation retains external_id and returns to its pre-handoff observation state.

Align observer reports with lifecycle from/event rows, including platform process_error and post-submission external check_error. Use user constraints or confirmed external failure conditions for retry/wait limits; time in queue/running is not itself failure.

Retry waits for the old process to exit and writable scope; paused Runs do not retry. An authorized operator may explicitly take over retry or cancel, invalidating the pending transition. Confirmed-ended pending retries continue after restart; unknown process outcomes retain a reason until verified and recovered through existing retry tools. Existing limits and three-agent-failure pause/notification remain.

Observation stops on completed/fault/retry/agent. In-flight reports may return stale:true,accepted:false: evidence is retained without changing Tasks/results/failure counts. Do not create another Task or resubmit external work for that reason.

Configure fallback_node and its candidate through existing bindings. An agent without command waits for external takeover and cannot auto-wake. Runtime checks list actual cwd, missing programs/scripts, and unverified agent trust/login. Authors verify noninteractive startup there; the platform never changes cwd/trust automatically.

## Platform wait nodes

Add timer/event nodes with put_node + set_implementation; no polling script or resident agent is required.

- timer: wait contains exactly one seconds or timezone-aware ISO until, e.g. 2026-10-01T09:00:00+08:00. Relative time begins when the Task starts waiting; persisted deadlines are not recalculated on restart. Usually there are no outputs; declare wait.outputs if outputs exist.
- event: event names the event; wait.key correlates it, defaulting to Task parameters.event_key. Optional wait.timeout limits seconds. A matching payload supplies all outputs and is validated/committed. Events may arrive first; one event is consumed by one waiting execution.
- wait supports `{parameters.name}` and `{"$":"parameters.name"}`. Question/reply event name, correlation key, and output structure must agree.
- Expiry reports timeout; the initial matrix faults, but authors may configure retry/agent. Cancelling a wait starts no external operation; alternative downstream inputs require explicit arrangement. Pausing stops progression; resume respects the original deadline.

Generic example, without business methods:

```json
{"draft_id":"DRAFT_ID","revision":1,"node_id":"wait_reply","kind":"event","event":"reply","wait":{"key":"{parameters.question_id}","timeout":86400}}
```

Use the real revision and declare output contracts first. Add notify to the completed row for completion messages; authors choose content/output fields.

## Runtime verification

validate_loop and static smoke do not execute candidates. Explicit smoke_runtime(key,node_id?,implementation_id?,timeout?,cases?) checks installed agent startup and external lifecycles. It runs selected agents with real argv/cwd, potentially invoking models (default 30 seconds per check), and simulates external reports, duplicates, and post-retry check_error in a temporary Timeline. It does not run real external business work or modify Runs. Omitted selectors check every candidate, including fallback.

For conditional transitions, cases supplies node, implementation, state, event, and required attempt/parameters/inputs/settings/detail/expected. Only those cases are verified; business output contracts/services still need acceptance. unknown is not success; ready means no known failure; verified means every item passed. Corrupt packages do not execute. CLI: `smoke-runtime <key> --node <node> --implementation <id> --timeout 30 --cases cases.json`.

## Further construction tools

See [contracts](contracts.md) for conditional parameters, stable Task/output refs, validate_parameters, and preview_plan, and [testing](testing.md) for test_loop/scenarios. read_capabilities exposes these and other mechanisms.

Exports derive capability requirements from routes, extended schemas, refs, scenarios, and requires. New-capability packages use package/2 so older services reject explicitly; ordinary old packages retain package/1. requires may add explicit requirements. Install/import/copy/reexport preserve package requirements; unknown formats reject rather than downgrade. Reread live schemas after updating a service; source edits alone are not a running-service upgrade.
