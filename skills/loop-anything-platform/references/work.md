# Persistent work, session continuation and monitoring

A Timeline exists independently of Runs. It has two user semantic fields:
objective (what is to be completed, including success criteria) and constraints
(method/time/resource/authorization boundaries). Entries retain work progress, decisions and references. Do not archive raw user
messages; keep effective user requirements in objective and constraints. Do not expand authorization.

## Begin or resume work

For existing work, first read its Run/Timeline/Loop using its known resource ID. The script resolves the original platform. Pass the returned `--work WORK_ID` when registering a new session or creating associated work, so a changed default cannot split one workflow across platforms. For brand-new independent work, the first discovery/creation selects the default and returns its work_id. Managed wake-ups already carry this binding. No address copying is needed.

1. Register the actual current SERVER Agent session with register_work_session.
   Supply native_session={provider,id,cwd}, the current Agent process_id (not a
   tool subprocess), and an Agent implementation with its exact resume_command.
   Keep the returned session_id/session_token. Registration launches nothing.
2. For work without a Loop, create_timeline and append_timeline are sufficient.
   Read read_work_timeline with after/cursor to retrieve all relevant entries.
3. start_run requires request_id, session_id/session_token, key and title.
   It binds the caller, not a separately selected named Agent. Supply objective
   and constraints for new work, or timeline_id for existing work.
   Read the returned runtime identity, handbook and Timeline; arrange work in the same
   session using read_task/report_task. No initialization report is required. Default progression returns to this
   session; explicit rule progression still runs in Engine.
4. Starting with an existing timeline_id uses its current work automatically.
   The platform retains committed results and observes in-flight executions using
   their original identities. A Loop may change its strategy or nodes while using
   the saved business state directly. The platform does not match or validate
   cross-Loop business schemas. Only one Run plans current work; retained
   executions can still deliver their results. A previous management process
   must stop before its management task is replaced.
   Business Agents always read intent and current state; do not branch on whether
   a Run or Loop changed. Use resolve_continuation for an explicit observer retry
   or user-authorized cancellation/retry after checking the original execution.
5. claim_run returns the bound current session's identity for the next management
   task. Finish management turns with their actual output contract and finish.
   Run normally continues until the Timeline task is complete.

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

## Wait without a business Loop

wait_for takes your session identity, timeline_id, stable key, sources, condition
and optional message for continuation. A source is:
- {kind:run,id:run_id}: status/revision/records
- {kind:task,id:run_id,task_id}: status/revision/outputs
- {kind:monitor,id:monitor_id,max_age?:seconds}: status/at/data/call_id

Conditions use the existing deterministic path/op/args vocabulary. For example,
sources={experiment:{kind:run,id:...}} and
condition={op:eq,args:[{path:experiment.status},completed]}.
Only explicitly typed conditions are evaluated; the platform does not infer
business decisions from prose. Unavailable/stale data is unknown, not false.

Registration checks the current state, including work already completed.
Finish active management scopes and exit the Agent process. Once safe, the
platform resumes the exact native session with evidence and fresh work context.
Read current Timeline and claim_run before changing a Run. acknowledge_wait
after handling its evidence; cancel_wait removes a wait without cancelling
observed work. Reuse keys only for identical registrations.

The current implementation resumes CLI sessions on the server (macOS/Linux).
It cannot inject into an arbitrary live chat. Ready events remain pending while
the original process is alive. Missing/failed/unknown sessions are explicit;
resume_work_session requires checking that the prior process stopped. Never
silently replace an unavailable session. Another Agent can explicitly take over
or recover the work from its Timeline.

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
monitor samples, pending waits and registered definitions. It never polls or
starts a script. The webpage links to the existing Run view for task/flow detail.
No application-specific monitoring scripts are bundled or registered by default.

Script definitions may optionally declare metrics=[{key,label,unit}]; keys may
address nested fields with dots. Units are never inferred. read_monitor_history
returns the latest 240 checks, including failure gaps; samples are retained per
instance. Native Loop external observers keep their existing contract and link
to the corresponding Run rather than duplicating its execution interface.

`list_timelines` returns `groups` (Loop IDs, display names and counts) and a page of `timelines`. Pass `loop_id` to select a Loop across versions, or `unbound:true` for temporary work with no retained Run. Follow `next_offset` with the same filter; `limit` defaults to 20 (maximum 100). Grouping is derived from the latest retained Run and does not bind or modify a Timeline.


### Continuation and precise observations

Pause/resume preserves the same Run and its progress; pausing stops new business dispatch without freezing already-started external jobs. A new Run continuation uses the same normal scheduler and report routing. Existing executions return their results through continuation receipts.

Continuing the same Loop preserves saved work, runtime settings, inputs and hook firings; explicit startup overrides still apply. State display metadata never selects a continuation path. Selecting another method does not initialize the Timeline again. Existing tasks retain their complete original execution contracts, resources and declared routes; new rules are never grafted onto old task inputs. The current Agent reads all contributions and uses current Loop nodes for new work. It may explicitly replace pending planning Tasks using existing task operations, retaining in-flight experiments and established dependencies. New dispatch waits for the startup management turn; in-flight observation continues. No automatic cancellation, schema converter, or permanent Loop ownership of business state is introduced.


## Download and import progress

The Timeline page downloads a `.timeline.json` file; the Timeline library imports it with a short preview. `export_timeline(timeline_id)` returns `filename` and `document`. The portable CLI supports `export_timeline --arguments '{"timeline_id":"..."}' --output progress.timeline.json`.

On the receiving platform, call `import_timeline` with `{document: <file contents>, request_id: <stable ID>}`. Import is independent new work: select the receiving space for this operation, then use the returned Timeline identity and normal origin binding. Reuse request_id on retries; an intentional separate copy uses a new request_id. Import never starts a Run or task, and never merges into another existing Timeline.

Files contain goals, constraints, all progress entries, business-state history, immutable saved results. They do not contain platform session tokens, Agent configuration, executable implementations or observers. External artifacts, scripts and logs remain references and are not automatically read or uploaded. Maximum file size is 20 MiB.

Read `read_work_timeline`, `read_business_state`, and `read_work_result(timeline_id,id,revision)` before arranging work. Saved results can be read without the original Run or Loop. Use saved results as inputs for the current method. If continuing the business requires an external experiment reference, the Loop must submit it as meaningful progress; exporting does not search old executions to infer it. A recipient uses its own available capabilities rather than assuming the original execution moved.

Use `start_run(timeline_id=...)` with a relevant locally available Loop to continue. Its Agent reads the imported progress, preserves other contributions, and supplies its own method-specific task inputs. A missing local file reference is not proof that the prior experiment failed; retain known results and obtain the materials actually needed for the next step.

Timeline reads and exports contain business progress, not a reconstruction of Run tasks, input values, monitoring or temporary waits. The Loop submits the meaningful progress; the platform does not infer missing business facts. For the execution scene use `read_run` with `view:"snapshot"`, then `read_task` for individual details. Temporary arrangements are not transferred.

Deleting an ended Run preserves its Timeline and committed results. Pending waits on a Run keep following the Timeline's current Run. While there is no current Run, they can evaluate the last observed terminal status and the saved result versions required by the condition. A Task source stays tied to that Task and its exact outputs. Other sources, such as available GPUs, are evaluated at poll time. Use completed when the condition specifically requires successful completion.
