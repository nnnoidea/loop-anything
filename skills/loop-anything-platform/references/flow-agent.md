# Built-in flow agent: start with a Skill, stabilize over time

Configure the decision Agent in the Loop definition with `set_loop(flow_agent={...})`. The implementation uses the normal Agent command or dispatch configuration. The recipient can override its execution settings in the Loop configuration file.

## Explicit event decision points

At build time, choose the event and the question the Agent should answer. For a semantic fallback alongside a fixed plan, give the plan the known condition and the decision route its complement. Without a `when`, the decision route matches every accepted event of the declared type, even when a plan also matches.

Declare a decision point on the business node with `put_node(routes=...)`:

```json
{"routes":[{"id":"review_next","event":"completed","flow_agent":true}]}
```

Optional `when` reuses event-route expressions and `inputs/outputs/parameters/settings/detail/attempt/task/transition` context. For example, trigger when an aggregation node finishes with the round's results. **No flow-agent business node, extra ports, or intermediary plan is needed.** No matching declaration means no decision invocation. Uncovered events follow the existing lifecycle; this is not an implicit fallback.

Deterministic progression continues through `routes.plan/values`, dependencies, and lifecycle rules. A route uses either `flow_agent:true` or `plan/values`; a node can use different mechanisms for different events/conditions. Every explicitly matching route executes. Use mutually exclusive conditions for alternatives; the platform does not infer priority. Do not invoke an agent on every progress report unless the user needs judgment on every report. Duplicate reports do not duplicate decisions.

A route receipt reports `fired` or `skipped`. A skipped decision route creates no decision Task. The Run history and task details distinguish it from a requested decision.

## Complete a decision

A matching route creates an internal decision Task using existing execution, session, retry, and assistance wait/resume mechanisms. It is absent from the author's business-node definition. Decisions can arrange work across the current Run, but thinking never exclusively occupies the Timeline; submissions check execution identity, scope and required outputs. Separate triggers remain separate records rather than being automatically merged.

The routing Agent reads the complete Loop Skill handbook: business methods, constraints, natural-language rules, and completion conditions. Do not duplicate it as a flow-node Skill. Read relevant node references and platform topics for the current decision, not all references upfront; see [instruction layers](build.md#three-instruction-layers-and-on-demand-reading). `read_task` returns `flow_trigger` / `inputs.trigger` with exact source Task, execution, report, event, and result-version references. Read complete evidence with `read_record(id, revision)`, then the current Timeline and source Task's `route_receipts`; reuse work already created by deterministic routes.

Arrange or adjust work through `build_plan/add_task/edit_tasks`. Use stable keys and inspect previous arrangements on reentry. Separate scheduling calls and result submission are different transactions. Submit `report_task(event="completed", report_id=STABLE_ID, envelope={"outputs":{"decision":FULL_DECISION_AND_RATIONALE}})`, check `accepted`, then `finish`. The decision may be full text or structured data; no summary is required. End a satisfied Run with `completion_rule` or `termination_signal`; `finish` alone does not end it.

For assistance waits, register the real session and use `wait_assistance` to resume that same session. Training and other external waits remain external/event/timer work. Decision failure, pause, retry, and process exit use ordinary execution mechanisms, without long agent polling or another workflow-state store.

## Inspect, illustrate, and stabilize

`read_task(source_task)` returns `flow_decisions`; follow Task, execution, and output references to complete results and sessions. The web interface attaches decisions to the source business node; chronological history retains every decision execution. These records support later stabilization, but the platform does not automatically learn or compile rules and has no specialized evidence tool.

Show **who executes, who decides progression, and runtime status** separately: execution shapes/icons, progression borders/text, and status badges. Expand actual events and conditions as needed. Follow [diagram guidance](flow-diagram.md) for static definitions; do not invent fixed destinations for undecided work or depict templates as running.

Existing author-defined ordinary flow-agent nodes, plans/routes, and `global_agent_node` continue without automatic migration. Use the built-in mechanism for new designs. Existing Runs retain their definition; changes apply to subsequent Runs.
