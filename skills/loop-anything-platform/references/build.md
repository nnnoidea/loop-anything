# Build a Loop

Compose platform mechanisms for the user's workflow and reuse existing implementations. The agent discovers capabilities, chooses representations, and integrates them; the user determines business intent, resources, and authorization. Read [authoring fields/contracts](build-reference.md) and the [platform Skill](../SKILL.md) as needed.

## Start from an existing Skill or incomplete rules

For an existing operating Skill or decisions requiring judgment, suggest [flow agents combined with deterministic rules](flow-agent.md). Separate long execution/waits, declare known transitions, and use an on-demand flow agent for the remaining decisions. A first version need not enumerate every state transition. The flow agent reads the complete Loop handbook and records its decisions/rationale through normal results. Deterministic workflows need no extra agent; this is a suggestion, not a mandatory construction process.

## Three instruction layers and on-demand reading

Organize business guidance as a main Loop Skill with node references, divided by decision scope:

| Layer | Purpose |
| --- | --- |
| Platform Skill | Discover capabilities and construction choices; reference common build/run/wait/communication/report operations. |
| Loop Skill (handbook) | Preserve applicable goals, overall business methods, node responsibilities, shared constraints, progression decisions, and completion criteria; point to relevant node/platform references. |
| Node reference | Context, methods, script entry points, inputs/outputs, success criteria, and recovery for this responsibility; reference shared rules in the handbook and generic operations in platform topics. |

When importing a Skill, preserve its business reasoning and decision methods, then move stage-specific operations into references. The handbook must still explain the business, not become a list of fields, files, or architecture. Each reference identifies when to read it and its real path. Maintain implementation lists, contracts, and steps in their responsible documents rather than duplicating them.

Use [author Skill file bindings](build-reference.md#author-skill-files-and-references) for the handbook and node files. Link the same bound node file from the handbook; distinguish tool arguments from stored fields. Existing node SKILL.md files need not be renamed, copied, separately registered, or independently installed. Resolve platform references from the installed Skill/context, not hardcoded author-machine paths. Short inline instructions remain supported.

Read by role: building agents use platform construction guidance, handbook, and affected node references; flow agents read the complete handbook plus relevant references; node agents use shared business rules and their current node reference, consulting platform operations when needed. Script nodes need an execution contract, not an extra agent to read it. Neither preload every reference nor prohibit further reading when relevant.

Skills hold reusable methods/rules. Read current goals, constraints, state, and results from Run settings, Tasks, and records, without another document copy of runtime state. Natural-language progression still requires explicit flow_agent routes; prose alone does not enable an agent.

Propose separation based on the goal. Do not force splitting, extra nodes, or a fixed directory template when material is already clear. Evaluate usefulness by whether an agent can find required references and complete representative work. Needing a reference beyond the main file is not itself a defect.

## Separate platform and author responsibilities

Read returned authoring_context when creating/copying a Loop or reading a complete definition. The platform already persists Timeline state, schedules dependencies, enforces concurrency/scope, snapshots executions, and recovers after restart. Declared mechanisms handle batches, routes, retries, waits, notifications, and completion. It also displays structure, tasks, results, provenance, and history. Authors provide business methods, contracts, real implementations, and external adaptations.

Inspect activation, configuration, and limits through read_capabilities(capability=...) or the same [capability guide](platform-capabilities.md). Prefer declarations for existing mechanisms. When capability is genuinely missing, identify the absent semantics and minimum adapter rather than rebuilding scheduling, ownership, storage, or viewers in the business package.

For "parameters → parallel work → aggregate judgment", use source.routes parameter mapping, plan.each/collect/after and stable refs, then let the Engine schedule and tasks submit results. The platform displays them; authors supply commands and reasoning methods. read_capabilities.patterns provides adaptable examples.

## Map business needs to mechanisms first

Read live read_capabilities/list instructions and tool arguments. Find existing drafts/versions with list_loops, inspect definitions/assets, and continue the same Loop. When adapting another system, inspect its business methods, stable entry points, and dependencies; distinguish reusable implementations, adapters, and responsibilities already handled here.

Use the conversation/materials to establish entry intent, judgment points, execution after decisions, and the evidence for continuing or ending. Explain this mapping concisely. Act on clear existing answers; ask only about gaps affecting business meaning or authorization. Do not require users to design every node/schema/tool field.

Verify a representative complete path before expanding other requested branches/implementations. Include how downstream tasks consume results and when work continues, waits, or ends. Small examples expose interface issues early without reducing the requested delivery scope.

## Assign responsibilities to existing capabilities

| Need | Platform mechanism | Author supplies |
| --- | --- | --- |
| Goals, constraints, guidance, authorization | Timeline settings | Agreed business meaning |
| Situational progression decisions | Built-in flow agent + explicit event routes | Natural-language rules, decision points, executor; no default progression or extra flow node; [flow agents](flow-agent.md) |
| Known automatic work | command/external candidates | Real commands, parameters, inputs/outputs; observe for async work |
| Conditional, exclusive, composed parameters | parameter_schema, validate_parameters | Actual candidate contracts; [contracts](contracts.md) |
| Select tasks/results by business item | ref, after_refs, task_ref/task_refs, resolve_refs | Unique refs, members, output ports |
| Expansion and workflow acceptance | preview_plan, test_loop, set_loop.scenarios | Sample inputs, simulated reports, observable expectations; [testing](testing.md) |
| Reusable work group | plan, input sources, after | Responsibilities, real data handoffs, ordering |
| Batch a list then collect results | plan each, input collect | List path, item parameters, required outputs; reuse generated Task/record IDs |
| Include a step or omit it | plan when, build_plan.steps.skip | Explicit choice and valid downstream inputs after omission |
| Preview/commit several task edits | edit_tasks | Ordered add_task/build_plan/change_task operations and current Timeline revision |
| Generate another round from results/events | node routes → plan | Event, condition, parameter sources; upstream reports, platform creates Tasks |
| Append unplanned work | add_task / build_plan | Explicit node, parameters, inputs, dependencies |
| External progress and recovery | external reports, lifecycle, optional fallback | Finite events, mechanical conditions, permitted retries/handoffs |
| Pause, notify, wait | Hooks, notify, timer/event | Trigger locations, questions, events |
| End the Run | settings.completion_rule / termination_signal | Mechanical condition or an agent's actual completion judgment |

Nodes represent independent business responsibilities, deliverables, or work worth tracking separately. Do not copy another system's scheduler, state store, ownership, or viewer into business nodes. Keep internal source-system objects only at the adapter boundary where a stable API genuinely requires them, and explain that dependency.

Try composing these mechanisms for complex requirements. Conditions, batching, collection, follow-up scheduling, and recovery serve distinct roles; one tool not solving the entire problem is no reason to rebuild a controller. If composition is insufficient, record desired behavior, limits, and missing interface rather than hiding the gap in business scripts. Real needs determine node/candidate counts; fewer is not inherently more correct.

Represent ordinary mode differences through Task parameters or task inclusion. One agent can handle several entry intents without separate implementations; reuse a shared execution skeleton rather than copying plans. Register distinct candidates for genuinely different mechanisms, backends, or parameter contracts.

Verify relationships separately from execution states. `after` delays already-created tasks. `routes` generates tasks from events/templates. `plan_nodes` permits explicit script scheduling. With routes declared, upstream agents/scripts report parameters/results and the platform creates the batch; do not also call build_plan manually. Prearranging a follow-up decision with after usually expresses "analyze when this batch is ready" without a resident coordinator.

## Declare events and parameter sources

Use put_node.routes for event → plan → parameter origin. For example, research.completed maps outputs.requests to plan experiments; each expands experiments and collect aggregates them. Runtime submits `{requests:[PARAMETER_SET_1,PARAMETER_SET_2]}` and the platform generates Tasks, dependencies, and output IDs. An aggregation node can use when to decide whether the same rules should create another round.

Route mapping can bind candidates, Task parameters, and inputs while retaining plan conditions, omission, batching, and collection. Timers or matching external-event nodes report completed and trigger routes too. Authors specify source output schemas, conditions, and destination plans; business decisions are not inferred. See [event-driven generation](build-reference.md#event-triggered-task-generation).

Result submission, state transition, and all matching routes' generated tasks commit together. Invalid parameters/tasks reject the batch. Retrying a stable report_id returns the same receipt, with generated work in receipt.routes. No separate post-report pipeline-creation helper is needed.

## Set execution contracts when arranging work

Choose implementations/parameters when creating automatic Tasks. Use agents for steps still needing business judgment at execution. Read the selected candidate's parameter_schema; node and candidate contracts both apply, without default injection.

| Information | Execution source |
| --- | --- |
| Candidate | Task implementation; steps.<step>.implementation for a batch |
| Implementation parameters | Task parameters; a template may use `parameters:{"$":"values.options"}` or call-time steps.<step>.parameters |
| Upstream data/artifacts | Explicit input sources referencing outputs/records |
| Run purpose and constraints | Timeline settings |

A domain plan may retain intent and parameter copies, but identify what actually controls execution, who writes the Task, and how edits remain consistent. Do not create a second implementation selector, parameter validator, or runtime truth store per Loop. The platform validates parameters but does not turn them into argv; adapters distinguish business CLI parameters, orchestration fields, and artifact declarations.

For omitted stages, inspect actual tasks/data flow. Do not create a task when neither execution nor a deliverable is needed. Keep a genuine delivery task when a usable manifest/reference must still be produced. completed plus a skipped flag is not equivalent to not arranging work. Declare every upstream artifact needed by inputs, not only the most obvious edge.

## Reuse implementations with understandable adapters

Prefer stable existing entry points. The platform supplies call.py and reporting clients. Add a package helper only for repeated business operations; it maps node contracts to existing interfaces and submits real results. Explain added dependencies, identity resolution, and registries. A bound command does not prove its environment works.

Share mapping, validation, submission, and recovery across entry intents for the same plan. Keep external implementation complexity in that implementation. Confirm that constructing its internal context is a stable interface requirement before adapting it. Avoid importing a whole old control plane and patching it piecemeal.

Node references point directly to actual candidates, shared contracts, and business entry points using [instruction layers](#three-instruction-layers-and-on-demand-reading). Script stages must not depend on another agent filling in parameters at runtime.

Use package-relative paths internally and real target-machine configuration externally. Helpers obtain platform/client locations from wake-up context. Ordinary run_id/token interfaces and identity-bound tool_url are different entries; state which a wrapper supports. See [integration contracts](build-reference.md#simple-entry-points-for-runtime-agents) for wrappers, prompts, and recovery.

For grouped task changes, preview with edit_tasks(preview=true), inspect IDs/parameters/dependencies/omissions, and submit against the same revision. A later task can use preview-returned IDs and be previewed again. Reread/reassess conflicts. edit_tasks covers task editing only. Use routes to commit results and generated successors together; separate calls remain separate transactions.

## Verify that intent becomes action

Use validate_parameters and preview_plan, then save meaningful paths as scenarios and run test_loop. It uses the real Engine while intercepting commands/models. Explicit smoke_runtime or real integration tests verify external environments; simulated reports are not real business evidence.

Check observable behavior along representative paths, limited to branches this Loop uses:

| Intent/event | Expected observation |
| --- | --- |
| Execute known work | Initialization directly arranges needed tasks; automatic stages need no new decision |
| Explore and iterate | Decisions create this round's work; successors reference exact predecessor Tasks/results |
| Omit stages or reuse artifacts | Omitted tasks are absent and remaining inputs resolve |
| Parameters/candidate already decided | Task choices, parameters, and actual command agree; orchestration fields do not leak into business argv |
| Queue, failure, or observation failure | Declared state transitions occur; check failure is not business failure; retry does not duplicate successful work |
| Continue after partial submission failure | Read committed results and resume remaining arrangements using stable keys |
| Goal satisfied | completion_rule or termination_signal is written to platform settings; Engine reaches terminal state |

Business output fields named satisfied, terminated, or completion_rule do not end a Run themselves. Identify who writes platform settings and ensure helpers do not filter that step out. finish only releases scope, and no remaining tasks does not imply completion. Pause/notification fields likewise need actual consumers/platform actions.

Validate definitions/assets with validate_loop; check task construction, parameter handoff, and submission recovery in isolation; use [runtime checks](build-reference.md#runtime-verification) when needed, then authorized real-business acceptance. A dry-run plan, static validation, minimal agent response, and real external work are distinct evidence; report what passed and remains unverified. Prove one integration path before expanding similar candidates.

Locate faults in business methods, Loop adaptation, environment, or generic platform contracts. Record concrete cases/minimal gaps for missing platform capability; business-specific mappings remain in the implementation. Do not promote one workflow's timeouts, repair thresholds, or research objects into universal rules.

## Explain the workflow to users

On initial completion or changes to nodes, branches, cycles, or task generation, the current agent updates the diagram with [existing components/tools](flow-diagram.md). Show every node, including optional/recovery paths, without aggregate replacements. Explain evidenced relationships and save source/page together with the Loop. Viewing does not launch drawing, ordinary parameter edits need no redraw, and no mandatory gate is added.

## Save, use, and share

The web interface supports reading and runtime operations, not lightweight editing, changing defaults, or standalone chat. An external building agent edits definitions, contracts, Skills/scripts, and rules through authoring tools, or edits source and repackages. Node sessions only handle their current Run tasks.

Keep saving the same draft using returned revisions. Use `publish_loop` when the user requests an updated locally usable version or wants to start it. Use `export_loop` for sharing, not every edit. Existing Runs keep their snapshots.

Report the actual business path, implementation/environment dependencies, verification boundary, and genuinely missing user information. See [authoring details](build-reference.md#modify-an-existing-design) for edits/conflicts/assets and [run.md](run.md) for operations.

Live background-agent output and optional CLI terminals are built in; see [terminal configuration/limits](terminal.md). Do not create another log page or interaction service.
