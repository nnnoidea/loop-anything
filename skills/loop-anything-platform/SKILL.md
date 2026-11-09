---
name: loop-anything-platform
description: Turn existing Skills into Loops; build, edit, test, debug, and run workflows; orchestrate sustained multistep or iterative work; inspect progress and results; pause or resume runs; and continue after training or other external results. Also use for NAS/HTTP team services, lightweight executors, named agents, and team connections. Use loop-anything-local for independent scheduled or conditional tasks, and loop-anything-dispatch for requests, assistance, results, and follow-ups with local or remote named agents. Discover existing capabilities, Loops, and runs before building. One-off questions and local edits that need no workflow or collaboration can be handled directly.
metadata:
  provider: loop-anything-platform
---

# Loop Anything

The web interface is for reading and runtime operations, not editing or separate agent conversations. An external building agent edits Loop definitions; source files can also be edited and repackaged. Recipient runtime configuration can be edited in the file returned by `read_loop_config`. Node sessions handle their current Run tasks, not Loop authoring.

## Choose an entry point

| Need | Start with | Read as needed |
|---|---|---|
| Build, edit, test, or debug a Loop | Discover existing Loops and capabilities; reuse, edit, and verify using the build guide; start a Run when execution is needed | [Build](references/build.md), [testing](references/testing.md), [run](references/run.md) |
| Share a Loop or adapt paths, agents, and services | Read the separate runtime configuration; reuse inputs and implementation candidates rather than rewriting the workflow | [Loop configuration](references/loop-config.md) |
| Convert an existing Skill into a Loop | Suggest the built-in flow agent where appropriate; configure decision points explicitly for the goal, read the complete Loop handbook, and delegate known actions and waits to the platform | [Flow agent](references/flow-agent.md) |
| Iterative work, dependencies, or continuation after external results | Use `list_loops` and `list_runs` to reuse existing work; build only when a new workflow is needed | [Build](references/build.md), [run](references/run.md) |
| Call an existing Loop from a node | Configure `kind:loop`, the target key, and input/result mappings; the platform creates, waits for, and links the child Run | [Loop calls](references/loop-calls.md) |
| Contact a remote agent, request help, delegate work, or use a local named agent | Use `loop-anything-dispatch`; managed nodes retain their scoped endpoint and execution identity | [Communication](references/communication.md) |
| Automatically continue an independent session after assistance | Use `start_collaboration` with the real original session, current agent PID, and resume command, or start a local named coordinator; then `wait_assistance` | [Standalone collaboration](references/communication.md#standalone-collaboration-a-built-in-loop) |
| Find runs by person, rename, attribute, archive, or delete | Store attribution on the client and query paginated summaries; keep library metadata separate from execution configuration | [Run library](references/run.md#run-lists-attribution-and-management) |
| Inspect progress, retrieve results, or continue previous work | Reuse Run/request IDs and supplied task tokens; do not recreate the work | [Run](references/run.md), [communication](references/communication.md) |
| Register or update a local named agent | Discover registrations with `communication_workspace(registered_agents=true)`; clarify reuse, update, or addition when a similar local name/purpose exists; an explicitly requested same-name addition is allowed | [Registration](references/communication.md#configuration-by-the-platform-owner) |
| Share Loops with team members who only have terminals | Connect through NAS/API to one service; run lightweight receivers on compute machines | [Team runtime](references/team-runtime.md) |
| Local schedules, conditional polling, or receiving jobs | Use `loop-anything-local`; persistent registration never automatically restarts old jobs | [Local scheduling](../loop-anything-local/SKILL.md) |
| Establish collaboration between machines | Connect with `communication_config(operation=team,link=...)`; ask the user for the agent's main purpose before opening it to work | [Team setup](references/communication.md#first-connection-one-team-link) |

A normal chat or terminal entry need not have an `execution_id`. Do not search other Runs for an execution to register against. See [entry agents and session registration](references/communication.md#entry-agents-and-session-registration) for assistance, continuation, and existing-execution registration.

## Propose construction choices that fit the goal

When discussing a new Loop or changing a design, use [capabilities and construction patterns](references/platform-capabilities.md#how-capabilities-shape-a-loop) to suggest specific capabilities that materially improve the workflow for this goal. Explain their benefit without waiting for the user to ask what the platform supports.

Integrate suggestions into the discussion. For repeated experiments, separate planning, training waits, and analysis; let the platform monitor training and arrange the next round from its results. Continue when the existing design fits, and respect choices already made. Do not recite every feature, add nodes to showcase capabilities, or turn suggestions into mandatory checks, scores, approvals, or extra confirmations. State actual capability gaps.

Use the business handbook as the **main Loop Skill entry**. Retain applicable goals, overall business methods, shared constraints, progression decisions, and completion criteria. Node instructions are references read as needed; platform operations link to the relevant platform reference. The entry must guide the business and explain when to read each reference, not merely list files or architecture. See [three instruction layers](references/build.md#three-instruction-layers-and-on-demand-reading) for ownership, bindings, and reading scope.

Suggest this separation when it reduces irrelevant context or duplicate instructions. Short, clear material need not be split. Do not require a new or independently installed Skill for every node, copy shared rules, add nodes just to shorten files, impose a checklist, or promise to eliminate context drift.

When the workflow first becomes complete, or nodes, branches, loops, or task-generation logic change, update its user-facing diagram. Show every real node, including initialization, optional branches, and recovery. Do not omit nodes or replace several with an aggregate box such as "experiment pipeline". Use the [diagram tools and template](references/flow-diagram.md), retain real IDs or unique names for clickable details, check coverage, and preview the result. Use layout, grouping, or scrolling for a large diagram. No separate drawing agent, custom page framework, or save/run gate is needed.

Configure the built-in flow agent with `set_loop(flow_agent=...)`; invoke it through explicit business-node `routes`. Do not add business nodes for it or choose a default progression mode. Show execution, progression decisions, and runtime status separately. See [flow agents](references/flow-agent.md).

## Connect and discover

Use tools and structured receipts. If the wake-up context contains `tool_url`, follow the [scoped entry](references/scoped-entry.md). Otherwise, run in this Skill directory, or use absolute script paths from elsewhere:

```sh
python3 scripts/call.py check
python3 scripts/call.py read_capabilities --arguments '{"capability":"authoring"}'
```

Choose capabilities such as `authoring`, `task_scheduler`, or `agent_communication`. Use `list` for the actual tool schemas, then `scripts/call.py TOOL --arguments @arguments.json`. `connection.json` supports HTTP or `nas:///locally-mounted-team-directory`; `--url` overrides it. When NAS returns `pending`, retain the request ID and use `call.py result --request-id ID`; do not resubmit. Diagnose connection failures instead of creating another platform or Run. See [connection](references/connection.md) for setup and updates. Trust the running service's capabilities and check `ok` and `accepted`. Timeline writes validate versions at submission: managed identities record read dependencies, while calls without a persistent token supply the returned `basis`. Reassess conflicts; see [optimistic submission](references/run.md#think-concurrently-check-versions-at-commit).

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
