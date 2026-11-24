# Persistent work, session continuation and monitoring

A Timeline exists independently of Runs. It has two user semantic fields:
objective (what is to be completed, including success criteria) and constraints
(method/time/resource/authorization boundaries). Entries retain work progress, decisions and references. Do not archive raw user
messages; keep effective user requirements in objective and constraints. Do not expand authorization.

## Begin or resume work

For existing work, first read its Run/Timeline/Loop using its known resource ID. The script resolves the original platform. Pass the returned `--work WORK_ID` when registering a new session or creating associated work, so a changed default cannot split one workflow across platforms. For brand-new independent work, the first discovery/creation selects the default and returns its work_id. Managed wake-ups already carry this binding. No address copying is needed.

1. Call `start_run` with a stable request ID, Loop key and title. Supply objective and constraints or an existing timeline_id. The receipt identifies the Run and Timeline. If a declared entry needs the starting Agent to supply its result, the receipt also gives entry_task_id and its temporary token. Report the entry result and finish. A registered session may include its session_id and session_token to associate the conversation.
2. The engine runs the declared entry and arranged tasks. For a method without a seed, read the Timeline and handbook, then arrange initial work using submit_run_request(operation=edit_tasks) or acquire_run for a temporary editing scope. Finish the scope when done.
3. Read existing runs directly. Pause/resume controls operate on the same Run. A new Run can continue an existing Timeline and observe in-flight tasks at their original identities. Explicit waits notify the session that requested them.
4. For a conditional wake, register the actual session with register_work_session, including native_session, the current Agent PID and a resumable implementation. Use wait_for with its session credentials.

Run-scoped read_timeline includes the latest 50 progress entries from every contributor alongside business state and the saved result index. If entries_complete=false, use read_work_timeline pagination for earlier entries. Read relevant detail on demand; a new method does not require complete process logs. Execution arrangements belong to read_run(view=snapshot).

Record useful work progress and decisions, not raw chat transcripts.
update_timeline uses the Timeline revision and returns an instruction to inspect
the whole Timeline, especially ongoing tasks, and report findings to the user.
Do that inspection. Do not pause, cancel, invalidate or rearrange work just
because objectives changed; the user decides additional modifications.

## Loop-defined business state

Business state is defined and interpreted by the Loop. Optional `state.types`
metadata supplies `summary` field names for display. Schemas or update modes
written in the Loop are business conventions, not platform permission gates.
Changing the Loop does not validate or translate existing business values.

`read_timeline` and `read_work_timeline` include compact `business_state` plus
current execution references. `read_business_state(timeline_id,type?,id?,revision?,offset?,limit?)`
reads full current or historical records; follow `next_offset`. Summaries declare
coverage and retain exact identities. Absence from a submitted batch never deletes
an existing direction, question or other state record.

A completed `report_task` may include `envelope.state` updates, each with
`type,id,value,refs?`. The platform automatically saves a new record revision
when its value or references change. refs pin either `{type,id,revision}` business
evidence or `{record,revision}` execution output evidence in this Timeline.
Previous revisions remain available; unchanged values and refs are reused.


The same envelope can include `operations=[{tool,arguments}]` for build_plan,
add_task and change_task. State, outputs and arrangements commit together or not
at all. Stable report_id handles a lost reply.
`build_plan.work_key` binds one business operation across Runs; reuse returns its
original arrangement, changed contents conflict. A deliberate new experiment
uses a new key. `add_task.after_work=[{key,step}]` resolves dependencies on those
arrangements, including retained experiments. No external command runs inside
this database transaction.

## 规划托管

A user can give a one-off arrangement that calls existing Loops. Keep the goal and progress on the ordinary Timeline. At each wait, identify an observable fact that makes another Agent turn useful:

- Use a Run or Task result when it exists. For an external condition use an existing monitor or a script that can check it. A readiness script may poll; the Agent exits while waiting. Keep any semantic decision for the wake-up turn.
- Register only the branch that has actually been reached. For example, wait for evaluation to finish, read the score once, and only if it improved register a wait for at least eight available GPUs. In wait_for.message write both the trigger and next action in the user's language, e.g. “等评测完成后比较基线；若提升，再等 8 张 GPU”。 Keep the receipt, finish any held scope and exit. After waking, read the Timeline and act on the evidence, then acknowledge the wait.
- If there is no reliable signal, first offer a concrete one (a user reply or a ready file, for example). If repeated Agent inspection is the viable fallback, explain the gap and offer manual continuation or polling with a specific cadence and stopping condition. Record the pending choice on the Timeline and wait for the reply before registering or starting the polling job. Do not start a sleep/read loop inside an Agent. A user's explicit instructions such as “每半小时检查一次，直到今晚八点” already supply the decision.
- Record the agreed fallback on the Timeline with append_timeline(kind=decision). Apply the agreed interval and stop condition through the existing scheduler; a wall-clock cutoff maps to until, with the user's timezone. A single command timeout governs one invocation. [Local schedules](../../loop-anything-local/SKILL.md) describes the runner.

When a later plan step depends on a scheduled action, register and start it once in the host registry (`loop-anything client local --root <schedule_directory> …` for a web plan). Keep its ID. The scheduler’s `start` runs in the foreground: launch it as a separate host process with its own output, so the Agent can exit immediately. Before exiting use the existing `wait_for` with `sources={"job":{"kind":"schedule","id":"SCHEDULE_ID"}}` and `condition={"op":"eq","args":[{"path":"job.terminal"},true]}` for a one-off job. The platform observes the registry while the Agent is away. On wake inspect `job.status`, `job.last_result`, and `job.error`, acknowledge the wait, and continue. For a recurring schedule select the relevant result or stop condition. A registered schedule must be explicitly started. Use a stable schedule ID for retries.

## Wait without a business Loop

wait_for takes your session identity, timeline_id, stable key, sources, condition
and optional message for continuation. A source is:
- {kind:run,id:run_id}: status/revision/records
- {kind:task,id:run_id,task_id}: status/revision/outputs
- {kind:monitor,id:monitor_id,max_age?:seconds}: status/at/data/call_id
- {kind:schedule,id:schedule_id}: status/terminal/last_result/error

Conditions use the existing deterministic path/op/args vocabulary. For example,
sources={experiment:{kind:run,id:...}} and
condition={op:eq,args:[{path:experiment.status},completed]}.
Only explicitly typed conditions are evaluated; the platform does not infer
business decisions from prose. Unavailable/stale data is unknown, not false.

Registration checks the current state, including work already completed.
Finish active execution scopes and exit the Agent process. Once safe, the
platform resumes the exact native session with evidence and fresh work context.
Read the current Timeline and Run before acting. acknowledge_wait
after handling its evidence; cancel_wait removes a wait without cancelling
observed work. Reuse keys only for identical registrations.

The current implementation resumes CLI sessions on the server (macOS/Linux).
It cannot inject into an arbitrary live chat. Ready events remain pending while
the original process is alive. Missing/failed/unknown sessions are explicit;
resume_work_session requires checking that the prior process stopped. Never
silently replace an unavailable session. Another Agent can continue the work from its Timeline.

On the planning page, **发送指令** resumes the original Agent after its process
exits, including plans that are waiting, completed or stopped. The instruction
is recorded on the same Timeline. The resumed Agent checks registered waits
and cancels ones superseded by the new instruction. On the local page, **停止规划** cancels the
plan's pending and ready waits after the Agent exits. Existing Runs and their
external jobs keep their own lifecycle. To wait again after a cancellation,
register a new wait key.

## Monitor scripts and instances

Users may keep scripts inside a Loop using existing command/observe/event
implementations. Registration is optional; do not force migration.

register_monitor stores a reusable script definition, without starting it.
A definition contains command argv and optional cwd, timeout, description,
parameter_schema. revision=0 creates; later edits require the current revision.

start_monitor accepts either script_id OR an inline script, parameters, a
positive interval and a stable request_id. An optional run_id associates the
instance with one experiment/Run; omitting it creates a standing monitor.
Each instance snapshots the script and owns its own results. Registering a
definition does not create a standing instance.
Set show_on_dashboard=true when the user should see the instance. The default
keeps it in Agent tools only. set_monitor_visibility changes this setting for an
existing instance and leaves its sampling and waits intact.

Each check receives JSON {monitor_id,run_id,parameters} on stdin. It returns one
JSON object on stdout. Business fields are arbitrary, such as available_gpu,
progress or smu; the platform does not define their business units. done=true
ends that instance. A thin wrapper can adapt an existing script; Loop-owned
observe scripts keep their existing lifecycle envelope unchanged.

read_monitor returns timestamped samples and errors. Waiting on a sample
requires freshness (default two intervals plus check timeout); errors never
silently reuse a successful sample. stop_monitor stops future checks, not the
observed experiment. It does not stop other instances. A running check may
finish; restart_monitor rejects active/unconfirmed processes.

Standing monitoring keeps its explicit enabled state across service restarts.
Interrupted checks retain unknown process state and require confirming stopped;
they are not replayed blindly. Existing personal/local schedules retain their
original explicit-start behavior.


## Monitoring overview

read_monitor_dashboard is read-only and returns compact Run states (paged),
saved result curves, monitor samples, external execution readings, pending
waits and registered definitions. The webpage requests dashboard_only=true to
receive Run states, result curves and explicitly displayed monitor instances.
The script library lists the registered definitions used by those instances.
Execution readings belong to the Run detail page. Agents can read pending
waits through their normal tools. Reading the overview never starts a script.

Script definitions may optionally declare metrics=[{key,label,unit}]; keys may
address nested fields with dots. Units are never inferred. Set optional `display` to
`stat` for current values, `table` for exact comparisons, `bars` for relative
sizes, or `trend` for changes over time. Omit it for automatic layout. Labels
such as “Queue A · Free” and “Queue B · Free” can share a measure column.
For a changing set of measurements, omit the fixed `metrics` definition and
return `metric_groups: [{label, metrics: [{key, label, unit}]}]` alongside the
sample values. The table and stat views group the measurements by label.
Keep metric keys stable across samples to preserve their trends.
Viewers can override the instance view in their browser. `read_monitor_history`
returns up to 240 recent checks. Pass `metric` to read just its timestamp/value
points, with missing or failed readings returned as gaps. Native Loop external observers keep their existing contract and link
to the corresponding Run rather than duplicating its execution interface.

`list_timelines` returns `groups` (Loop IDs, display names and counts) and a page of `timelines`. Pass `loop_id` to select a Loop across versions, or `unbound:true` for temporary work with no retained Run. Follow `next_offset` with the same filter; `limit` defaults to 20 (maximum 100). Grouping is derived from the latest retained Run and does not bind or modify a Timeline.


### Continuation and precise observations

Pause/resume preserves the same Run and its progress; pausing stops new business dispatch without freezing already-started external jobs. A new Run continuation uses the same normal scheduler and report routing. Existing executions return their results through continuation receipts.

Continuing the same Loop preserves saved work, runtime settings, inputs and hook firings; explicit startup overrides still apply. State display metadata never selects a continuation path. Selecting another method does not initialize the Timeline again. Existing tasks retain their complete original execution contracts, resources and declared routes; new rules are never grafted onto old task inputs. The current Agent reads all contributions and uses current Loop nodes for new work. It may explicitly replace pending planning Tasks using existing task operations, retaining in-flight experiments and established dependencies. Eligible tasks advance using the retained dependencies and event routes; in-flight observation continues. No automatic cancellation, schema converter, or permanent Loop ownership of business state is introduced.


## Download and import progress

The Timeline page downloads a `.timeline.json` file; the Timeline library imports it with a short preview. `export_timeline(timeline_id)` returns `filename` and `document`. The portable CLI supports `export_timeline --arguments '{"timeline_id":"..."}' --output progress.timeline.json`.

On the receiving platform, call `import_timeline` with `{document: <file contents>, request_id: <stable ID>}`. Import is independent new work: select the receiving space for this operation, then use the returned Timeline identity and normal origin binding. Reuse request_id on retries; an intentional separate copy uses a new request_id. Import never starts a Run or task, and never merges into another existing Timeline.

Files contain goals, constraints, all progress entries, business-state history, immutable saved results. They do not contain platform session tokens, Agent configuration, executable implementations or observers. External artifacts, scripts and logs remain references and are not automatically read or uploaded. Maximum file size is 20 MiB.

Read `read_work_timeline`, `read_business_state`, and `read_work_result(timeline_id,id,revision)` before arranging work. Saved results can be read without the original Run or Loop. Use saved results as inputs for the current method. If continuing the business requires an external experiment reference, the Loop must submit it as meaningful progress; exporting does not search old executions to infer it. A recipient uses its own available capabilities rather than assuming the original execution moved.

Use `start_run(timeline_id=...)` with a relevant locally available Loop to continue. Its Agent reads the imported progress, preserves other contributions, and supplies its own method-specific task inputs. A missing local file reference is not proof that the prior experiment failed; retain known results and obtain the materials actually needed for the next step.

Timeline reads and exports contain business progress, not a reconstruction of Run tasks, input values, monitoring or temporary waits. The Loop submits the meaningful progress; the platform does not infer missing business facts. For the execution scene use `read_run` with `view:"snapshot"`, then `read_task` for individual details. Temporary arrangements are not transferred.

Deleting an ended Run preserves its Timeline and committed results. Pending waits on a Run keep following the Timeline's current Run. While there is no current Run, they can evaluate the last observed terminal status and the saved result versions required by the condition. A Task source stays tied to that Task and its exact outputs. Other sources, such as available GPUs, are evaluated at poll time. Use completed when the condition specifically requires successful completion.
