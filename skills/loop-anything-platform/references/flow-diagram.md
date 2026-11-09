# User-facing workflow overview

The current building agent maintains the diagram when a Loop first becomes complete or nodes, branches, cycles, or task-generation logic change. Describe business relationships from actual definitions, node Skills, and scripts; do not invent unsupported routes. Ordinary parameter changes need no redraw, and viewing/running does not launch a drawing agent. This is construction guidance, not a mandatory save/run check.

## Every real node must be visible

Cover every node in read_loop.loop_definition.nodes. Initialization, research planning, review, execution stages, optional work, and recovery each need a visible shape and identifiable name, even outside the main path. Grouping is allowed; an aggregate "experiment pipeline" box cannot replace real nodes. Text outside the diagram or a node list is not a substitute for node shapes.

Before saving, compare IDs/names against the diagram, including new nodes and existing branches. Distinguish condition/end markers from real nodes. Explain evidenced conditions and cycles; optional scheduling must not appear inevitable. Multiple Tasks or retries of one node do not require separate node shapes.

For large diagrams use grouping, direction, canvas size, or scrolling rather than omitting nodes on narrow screens. Detail diagrams can supplement but not replace a complete overview.

## Express three dimensions separately

Show who executes, who decides progression, and runtime status independently. Reuse execution shapes/icons and text (script, agent, external task); solid/dashed borders and labels for rules/flow-agent progression, including explicit mixed branches; and separate labeled status badges. Include a concise legend and never rely on color alone. Label static definition diagrams as "Not running"; do not invent live status.

Purple rounded boxes can represent agents, blue rectangles scripts/external jobs, and two-tone boxes labeled "Agent + script" actual collaboration within one node. Use the selected implementation and real responsibilities. Alternative candidates, an agent invoking helper scripts, or failure handoff to a separate agent node do not automatically imply mixed execution. Explicitly show unselected implementations. When fill denotes execution type, status remains a separate badge. Execution location does not change this distinction. Reuse flow shape syntax; for color, put CSS in a Markdown html fence and target `.am-node[data-key="NODE_NAME"] > .am-node-shape` fill/stroke, keeping real names for detail binding.

The built-in flow_agent adds no business node. Mark decision events at the source node's exit; if the destination is undecided, say the flow agent decides rather than drawing an undeclared fixed route. Actual Task diagrams show recorded arrangements; decisions/sessions are accessed from the source node. Existing ordinary flow nodes remain visible as declared.

## Tools and template

The Skill bundles the offline Answer me with HTML renderer (MIT), so no additional Skill, frontend project, or drawing service is needed. Generation needs Node.js 20+; viewing saved HTML does not. Run from this Skill directory or use absolute paths:

```sh
# Copy the template and edit it for the actual workflow.
cp assets/flow.md /tmp/my-loop-flow.md
python3 scripts/render_flow.py /tmp/my-loop-flow.md --output /tmp/my-loop-flow.html

# Read the current draft revision, then render/save to that draft.
python3 scripts/render_flow.py /tmp/my-loop-flow.md --draft-id DRAFT_ID --revision REVISION
# Add --url http://127.0.0.1:8769 for a nondefault platform.
```

The command reuses call.py connection and existing put_asset to save docs/flow.md then docs/flow.html, returning the revision. It does not publish, start a Run, or change execution rules. These two writes are not atomic. A conflict identifies the stopped file; earlier successful writes remain. Reread/check the draft before continuing rather than overwriting newer work. Local rendering makes no platform connection. Upstream update checks are disabled, and theme configuration is isolated from global user settings.

The overview displays docs/flow.html; docs/flow.md is editable source. Read individual assets with read_loop(asset_path=...), and update/delete with put_asset. Ordinary package import/export carries them without a new protocol. Existing HTML can be saved directly, but prefer supplied components and renderer. Missing diagrams show an explicit placeholder instead of inferred business flow. An isolated iframe prevents access to platform DOM/APIs or external networks. Node selection opens information/state transitions in the same sidebar, retaining full configuration, execution states, and matrices. Rules group by source/target and can filter by target, while individual events, conditions, and actions remain visible and common effects are shown once. Execution, transition decision-maker, and destination handler have separate labels. A state machine deciding to hand off to an agent is not an agent deciding that transition. Flow-agent decisions are labeled separately; unknown targets are not guessed and terminal/wait states are not forced into script/agent categories. Explain custom-event business meaning in node Skills or implementation descriptions; names alone do not establish thresholds.

The platform provides node selection; authors need no messaging script. Bundled flow nodes bind by exact unique definition name or ID. For duplicate names or custom HTML/SVG, set `data-loop-node="REAL_NODE_ID"` on the shape. Do not bind auxiliary conditions/end markers or use fuzzy matches. Keep bindings when changing shapes/colors so details remain accessible.

## Syntax and available components

Use Markdown for titles, explanations, and sections; each second-level heading creates a panel. `template:doc` suits sequential reading, sheet suits panels. Use flow fences:

````markdown
```flow TB
(Clarify goal) -> Plan work: exploration needed
Clarify goal -> Execute work: plan already known
Plan work -> Execute work: submit round parameters
Execute work -> Analyze results: round results ready
Analyze results -> Plan work: another round needed
Analyze results -> (Done): goal achieved
```
````

- `A -> B: relationship`: solid; `A --> B: condition`: dashed; `A -> B & C`: fan-out.
- `(Start)`, `{Condition}`, `[(Data)]`: shapes; `group Group name: A, B`: grouping.
- TB is vertical, LR horizontal. Use node names directly, not Mermaid id[Name] syntax.
- Sequence, timeline, tree, and tables can supplement explanation. Query components as needed rather than using all of them:

```sh
node scripts/vendor/answer-me-with-html/am.mjs list
node scripts/vendor/answer-me-with-html/am.mjs help flow
node scripts/vendor/answer-me-with-html/am.mjs help sequence
```

The main diagram covers all real nodes, with concise notes for completion, exceptions, and optional branches. Ports, candidates, and state rules belong in the sidebar; expand the full matrix as needed, without turning them into extra workflow nodes. Preview the actual page for coverage, text, branches, and narrow-screen readability.
