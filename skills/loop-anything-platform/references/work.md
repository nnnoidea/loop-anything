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
   Read the returned runtime identity and continue initialization in the same
   session using read_task/report_task. Default progression returns to this
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

Continuing the same Loop version preserves completed initialization, runtime settings, inputs and hook firings; explicit startup overrides still apply. State display metadata never selects a different continuation path. When the user selects another Loop version, its entry initializes from the Timeline. Existing tasks retain original execution contracts and resources; their subsequent routes/progression come from the selected Loop's matching node. If that node was removed, ordinary undeclared-progression behavior applies. Continuation does not force steward mode.


A wait source `kind: run` observes the continuing work: it follows that Run's Timeline to the current Run, including later continuations. `kind: task` observes the specified task and only its exact committed output revisions. A superseded Run is exposed as `continued`; its original observers may still collect in-flight results, but it cannot arrange new work. Called Loops follow the same Timeline completion rule without resubmitting the child.

Retained tasks keep their original installed Loop package for Skills, handbook and executable assets. No resource mirror is created. Dispatched tasks retain the input versions actually read by their execution. Each remaining existing input and pending producer version is pinned; continuation receipts reuse the original execution's exact output references. A retained execution may finish its authorized state/result report while the current Run still awaits it; it cannot plan new work.

Read the goal, constraints and relevant state before working. Auto Research uses
`complete_research_decision.py` to submit its state, results and arrangements
atomically; no saved read snapshot or special handoff procedure is required.
Ordinary task prompts do not implicitly fetch all business evidence: use
`read_timeline`, paged `read_business_state`, and exact `read_record` revisions
as needed. Retained implementation snapshots belong to individual Tasks and are
reused on later continuation, without another layer of generated node names.
