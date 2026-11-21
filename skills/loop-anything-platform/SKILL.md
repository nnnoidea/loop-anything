---
name: loop-anything-platform
description: Turn existing Skills into Loops; build, edit, test, debug, and run workflows; orchestrate sustained multistep or iterative work; inspect progress and results; pause or resume runs; and continue after training or other external results. Also use for local/team spaces and NAS/HTTP team deployment, including local execution, named agents, and team connections. Use loop-anything-local for independent scheduled or conditional tasks, and loop-anything-dispatch for requests, assistance, results, and follow-ups with local or remote named agents. Discover existing capabilities, Loops, and runs before building. One-off questions and local edits that need no workflow or collaboration can be handled directly.
metadata:
  provider: loop-anything-platform
---

# Loop Anything

For a live chart, summary, event-triggered observation, or hot update of a running method, use [observation arrangements](references/observations.md).

For persistent work, see [Timeline, startup and waits](references/work.md). Start the Run with the user objective or an existing Timeline. If the Loop has no initial tasks, arrange the first business steps using its handbook before reporting that work is underway. Read the Run for execution status and the Timeline for progress and decisions. Register the current session when the user wants a conditional wake.

The web interface is for reading and runtime operations, not editing or separate agent conversations. An external building agent edits Loop definitions; source files can also be edited and repackaged. Recipient runtime configuration can be edited in the file returned by `read_loop_config`. Node sessions handle their current Run tasks, not Loop authoring.

A Timeline is complete task progress, independent of any method. Readable goals, constraints, current progress and essential results let an Agent use this Loop to advance the work. Other Loops' contributions remain available; update only changed records. Detailed logs/scripts can be referenced without being required to understand saved progress. The Agent prepares this method's task inputs; scripts need no common cross-Loop schema. There is no mandatory initialization node or restart-specific business protocol.

Keep business progress and execution inspection separate. The Loop submits meaningful progress to Timeline; `read_timeline` does not reconstruct execution state. Use `read_run` with `view:"snapshot"` for running, completed or failed tasks, Run settings, arrangements and the handbook; use `read_task` for details. The default `read_run` returns the full Run and history. Timeline downloads do not carry execution snapshots or temporary arrangements.

## Choose an entry point

| Need | Start with | Read as needed |
|---|---|---|
| Build, edit, test, or debug a Loop | Discover existing Loops and capabilities; reuse, edit, and verify using the build guide; start a Run when execution is needed | [Build](references/build.md), [testing](references/testing.md), [run](references/run.md) |
| Share a Loop or adapt paths, agents, and services | Read the separate runtime configuration; reuse inputs and implementation candidates rather than rewriting the workflow | [Loop configuration](references/loop-config.md) |
| Convert an existing Skill into a Loop | Suggest the built-in flow agent where appropriate; configure decision points explicitly for the goal, read the complete Loop handbook, and delegate known actions and waits to the platform | [Flow agent](references/flow-agent.md) |
| Iterative work, dependencies, or continuation after external results | Use `list_loops` and `list_runs` to reuse existing work; build only when a new workflow is needed | [Build](references/build.md), [run](references/run.md) |
| Call an existing Loop from a node | Configure `kind:loop`, the target key, and input/result mappings. Supply `loop.seed` for a child without an entry | [Loop calls](references/loop-calls.md) |
| Contact a remote agent, request help, delegate work, or use a local named agent | Use `loop-anything-dispatch`; managed nodes retain their scoped endpoint and execution identity | [Communication](references/communication.md) |
| Automatically continue an independent session after assistance | Use `start_collaboration` with the real original session, current agent PID, and resume command, or start a local named coordinator; then `wait_assistance` | [Standalone collaboration](references/communication.md#standalone-collaboration-a-built-in-loop) |
| Find runs by person, rename, attribute, archive, or delete | Store attribution on the client and query paginated summaries; keep library metadata separate from execution configuration | [Run library](references/run.md#run-lists-attribution-and-management) |
| Inspect progress, retrieve results, or continue previous work | Reuse Run/request IDs and supplied task tokens; do not recreate the work | [Run](references/run.md), [communication](references/communication.md) |
| Register or update a local named agent | Discover registrations with `communication_workspace(registered_agents=true)`; clarify reuse, update, or addition when a similar local name/purpose exists; an explicitly requested same-name addition is allowed | [Registration](references/communication.md#configuration-by-the-platform-owner) |
| Share Loops with team members who only have terminals | Connect their Loop Anything to the team space through NAS/HTTP; configure execution machines separately and explicitly start receiving when needed | [Team runtime](references/team-runtime.md) |
| Local schedules, conditional polling, or receiving jobs | Use `loop-anything-local` for this capability; persistent registration never automatically restarts old jobs | [Local scheduling](../loop-anything-local/SKILL.md) |
| Establish collaboration between machines | Connect with `communication_config(operation=team,link=...)`; ask the user for the agent's main purpose before opening it to work | [Team setup](references/communication.md#first-connection-one-team-link) |

A normal chat or terminal entry need not have an `execution_id`. Do not search other Runs for an execution to register against. See [entry agents and session registration](references/communication.md#entry-agents-and-session-registration) for assistance, continuation, and existing-execution registration.

## Propose construction choices that fit the goal

When discussing a new Loop or changing a design, use [capabilities and construction patterns](references/platform-capabilities.md#how-capabilities-shape-a-loop) to suggest specific capabilities that materially improve the workflow for this goal. Explain their benefit without waiting for the user to ask what the platform supports.

Integrate suggestions into the discussion. For repeated experiments, separate planning, training waits, and analysis; let the platform monitor training and arrange the next round from its results. Continue when the existing design fits, and respect choices already made. Do not recite every feature, add nodes to showcase capabilities, or turn suggestions into mandatory checks, scores, approvals, or extra confirmations. State actual capability gaps.

Use the business handbook as the **main Loop Skill entry**. Retain applicable goals, overall business methods, shared constraints, progression decisions, and completion criteria. Node instructions are references read as needed; platform operations link to the relevant platform reference. The entry must guide the business and explain when to read each reference, not merely list files or architecture. See [three instruction layers](references/build.md#three-instruction-layers-and-on-demand-reading) for ownership, bindings, and reading scope.

Suggest this separation when it reduces irrelevant context or duplicate instructions. Short, clear material need not be split. Do not require a new or independently installed Skill for every node, copy shared rules, add nodes just to shorten files, impose a checklist, or promise to eliminate context drift.

When the workflow first becomes complete, or nodes, branches, loops, or task-generation logic change, update its user-facing diagram. Show every real node, including initialization, optional branches, and recovery. Do not omit nodes or replace several with an aggregate box such as "experiment pipeline". Use the [diagram tools and template](references/flow-diagram.md), retain real IDs or unique names for clickable details, check coverage, and preview the result. Use layout, grouping, or scrolling for a large diagram. No separate drawing agent, custom page framework, or save/run gate is needed.

When building a Loop, encode fixed actions as rules. For cases the user leaves to judgment, declare a [decision route](references/flow-agent.md) and describe the question and constraints in the handbook. If it is the remaining branch, make its condition mutually exclusive with the fixed branches. The Run evaluates these declarations.

## Connect and discover

The installer registers `loop-anything` in the user PATH. Use `loop-anything --help` in a new terminal; an existing installation can repair registration with its Python: `-m loop_anything register`. No platform service is needed for registration.

Install Loop Anything once for the local platform, task tools, and team connections; do not ask ordinary users to choose a server/client role. Use `loop-anything tool` and `loop-anything spaces` for everyday platform operations, and the local Skill for scheduling/receiving. Choose the platform for new work. Each task can run on its configured execution machine. [Team operation](references/team-runtime.md) covers configuring and running the installed application for a team. The portable Skill below also works without the runtime.

Use tools and structured receipts. If the wake-up context contains `tool_url`, follow the [scoped entry](references/scoped-entry.md). Otherwise, run in this Skill directory, or use absolute script paths from elsewhere:

```sh
python3 scripts/call.py check
python3 scripts/call.py read_capabilities --arguments '{"capability":"authoring"}'
```

Choose capabilities such as `authoring`, `task_scheduler`, or `agent_communication`. Use `list` for the actual tool schemas, then `scripts/call.py TOOL --arguments @arguments.json`. Personal spaces configuration supports local and team HTTP/NAS addresses. `scripts/call.py spaces` inspects it; new operations use recorded addresses, preferring team when both exist unless the user chooses otherwise. If the user explicitly requests local/personal platform work, select `--space local`; a missing local address is an error, not permission to use the team. The script automatically binds discovered/created resources to their original platform. Continue by resource ID; use returned `--work WORK_ID` for ambiguous names or platform-wide follow-up. Managed Agent processes inherit this binding automatically; a conflicting explicit work reference is rejected. `--space`/`--url` only select new work or discovery and cannot override existing origins. Retain `routing_request_id` for `result --request-id ID` or `retry --request-id ID`; do not create a new request after an uncertain outcome. Diagnose connection failures instead of creating another platform or Run. See [connection](references/connection.md) for setup and updates. Trust the running service's capabilities and check `ok` and `accepted`. Timeline writes use the supplied scoped execution identity and stable report/task keys. Client Agents can apply explicit controls or acquire a temporary Run editing scope. Reads do not create write prerequisites; see [execution and atomic writes](references/run.md#execution-identity-and-atomic-writes).

## Operating principles

- Before opening an agent to a group, obtain the user's description of its main purpose and allowed scope, then set `task_confirmed=true`. Reuse an explicit prior answer; an agent-written description alone is not confirmation. See [registration](references/communication.md#configuration-by-the-platform-owner).
- Discover platform capabilities before writing business scripts. Scheduling, persistence, communication, waits/resume, and result inspection already exist.
- Read `self` from wake-up context or `communication_status`: machine_id, machine_name, and workspace_id identify the connected platform. See [current identity](references/communication.md#which-machine-is-connected).
- Use `read_cc_connect` to discover local Bots and `configure_cc_connect` when configuration is missing. Named agents bind `notification_bot` directly; named outlets are for fixed destinations. Do not implement another sender.
- For Feishu entry through cc-connect, `call.py` carries notification context automatically. Do not query message history or assemble send commands. Delegate delivery to cc-connect without collecting extra Feishu credentials or prechecking membership, permissions, or topics. See [conversation notifications](references/cc-connect.md#follow-the-original-conversation-automatically).
- `pending`/`offered` means waiting for acceptance, not that nobody is available. Do not cancel, recreate, or shorten the deadline after a few seconds. Suspend through the platform or retain the request for notification; an explicit withdrawal is still allowed.
- Read assistance status and results by default. Request paginated logs only for diagnosis; avoid repeatedly embedding logs, notification history, or old requests.
- Stay within existing authorization. Capability discovery does not authorize new tasks, messages, or arbitrary remote execution.
- Resume using the recorded original session and current operation credentials; never guess the latest session. Follow the author Skill returned by `read_task`.

Read only what the current task needs: [authoring fields and assets](references/build-reference.md), [capability map](references/platform-capabilities.md), [contracts](references/contracts.md), [testing](references/testing.md), [notifications](references/notifications.md), and [execution terminals](references/terminal.md).
