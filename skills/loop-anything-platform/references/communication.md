# Receiving platforms and team communication

Use the standalone loop-anything-dispatch Skill for dispatch, result lookup, and follow-up. It installs independently; ordinary callers need no local platform service. This reference covers receiving configuration and Loop integration. Managed nodes submit through their existing scoped entry, which invokes the same dispatch implementation. Do not build NAS queues or table send/receive scripts.

## Which machine is connected

First confirm the service supports machine_identity. On an old service with only instance_id, that value is a workspace address, not an independent machine identity. Upgrade rather than inventing a replacement.

Call communication_status and read self. Awakening contexts for nodes, named helpers, and scoped agents provide the same fields:

```json
{"self":{"machine_id":"machine-FULL_UUID","machine_name":"Training server","workspace_id":"WORKSPACE_ID"}}
```

self identifies the connected platform's machine/workspace, not necessarily the computer making the tool call. A remote helper's context identifies its actual execution host, not the source. Do not find MAC addresses, read databases, or guess IDs from chat memory.

A missing machine UUID is generated and persisted on demand. Workspaces using the same platform user environment share machine_id but have separate addresses. Top-level instance_id aliases self.workspace_id for compatibility. Address requests with the directory's instance_id and agent_id, not machine_id in place of instance_id. Old workspace IDs may retain a machine- prefix; the prefix does not change their meaning.

communication_config(operation=identity,name=...) changes the display name without changing IDs. Restarts, upgrades, and ordinary database relocation preserve identity. identity_conflict/identity_error explains copies or host mismatches. Explicit regenerate=true for a copy establishes a new workspace identity. Copied Runs/requests remain read-only history; create new Runs instead of taking over original executions. A legacy database first acquiring machine identity on a different host needs explicit ownership resolution, not an assumed rename.

## First connection: one team link

Install/run the receiving platform, then call communication_config:

```json
{"operation":"team","link":"FEISHU_BASE_LINK_OR_LOCAL_NAS_TEAM_DIRECTORY"}
```

Existing connections remain. The result includes team.id; configuration.default_team reports the default: an enabled Base takes precedence, with NAS used only when no Base is enabled. Joining NAS later does not replace Base. New unbound Runs pin this choice; existing Runs, manual bindings, and explicit unbinding are not overridden. Base network/permission/target failures do not redispatch over NAS. operation=leave disables new acceptance/default selection for that team; accepted work finishes through its original transport.

For a new NAS team add create:true. Mount paths may differ but must identify the same directory. Base uses the local authenticated lark-cli (user identity by default; identity:"bot" or a custom lark_cli path is optional). Internal tables/fields are managed automatically. A link grants no access; the selected identity must be able to read/write that Base. Do not copy individual table IDs. Legacy space/group configuration remains compatible. Tables, fields, records, and views use newer `lark-cli base +…` commands (verified with CLI 1.0.98); keys/inboxes use precise --filter-json queries. If an older CLI lacks them, run lark-cli update. Do not request legacy bitable:app or fall back to old APIs. Let actual CLI authentication/new-scope errors explain missing access, without permission preflight checks. Existing tables, team IDs, requests, and wait/resume associations remain.

Next, have the user confirm the local agent's main duties; configure CLI/cwd/resume_command and put the returned team ID in agent.groups. Joining alone neither publishes an agent nor starts a model. communication_status lists members; communication_workspace(group_id=...) returns a shareable team link. Send-only users install the dispatch Skill and join with that link.

Base send/receive intervals are at least 15 seconds; heartbeat-only updates at least 60 seconds, with an offline threshold of at least 180 seconds. Heartbeats update existing member timestamps without new rows or repeated directory writes; directory content changes publish a new version. A few seconds without response is not failure. Dispatch fixes one agent/machine before acceptance; receivers no longer await a second grant from an online sender. Legacy in-flight claim/grant requests remain supported.

## Configuration by the platform owner

Before registration/rejoining, communication_workspace({"registered_agents":true}) reads registrations across known local workspaces. It returns name, duties, agent_id, owning workspace/database, command program/cwd, teams, and enabled state. It does not read team networks/request history or start other workspaces. Offline/disabled does not mean unregistered. Nonempty unavailable_workspaces means some registrations could not be read; do not claim no registrations exist.

Compare names/duties against the user's goal. Show similar entries and let the user choose reuse, edit, or addition; follow an already explicit choice without asking again. The current chat need not identify itself as a named agent. Do not impose similarity thresholds or ban duplicate names. Reuse/edit in the current workspace uses the existing agent_id; a genuinely new registration omits it so the platform allocates a distinct record, even with the same display name. Other-workspace entries belong to the returned owner: dispatch to their existing team address, or connect to that workspace to edit them. Do not paste their IDs into this workspace as if updating them. Internal addressing remains workspace_id + agent_id.

communication_config configures local names, capabilities, CLI argv, cwd, capacity, and exposure:

- **Ask the user for the agent's main duties before exposing it to a group.** Turn the answer into a short description of suitable tasks, required inputs, and delivered results; confirm the allowed groups. Set top-level task_confirmed:true only after the user confirms duties/scope. Do not substitute model/CLI names or an agent-invented description. Changed descriptions or newly allowed groups require confirmation. Legacy configurations lacking confirmation show pending confirmation and stop accepting new group work; accepted work remains.
- operation:agent accepts optional agent_id; agent contains name, description, capabilities (string array), local, enabled, groups, capacity, and implementation, using the existing kind:agent command contract.
- operation:space saves a mounted shared-space path, optionally name on first use. It does not join a group or publish agents.
- operation:group accepts the space_id discovery flow or legacy direct path. Existing groups join directly; creating one requires create:true. Local mount paths may differ but must point to the same group.
- operation:leave takes group_id and stops new acceptance there; executions, receipts, and history remain.
- operation:probe takes group_id and writes/reads/cleans a local test file. This is not two-machine NAS acceptance.
- operation:bind_loop takes loop_key or run_id plus group_id. Loop defaults pin at Run creation; Run overrides affect new requests only.
- operation:context creates/updates context_id and default group_id for conversations without a Loop.
- operation:group_notifications binds this machine's notification_route/notification_level to group_id without overwriting others. Replacing/disabling requires its current binding_id; enabled=false disables only this machine. See notification priority below.

Ordinary node CLIs/running sessions do not register automatically. local exposure is separate from groups; local assistance needs no NAS. The receiving owner configures commands; requests cannot supply arbitrary startup commands. Group directories are trusted internal transport, not multitenant authentication.

## Requesting assistance

Use loop-anything-dispatch. These tools are equivalent entries for managed Loops/compatible clients and share the publication protocol:

1. communication_status discovers explicitly exposed local/group members without Task/request tokens. Loop calls include run_id and see only its group scope. Discovery does not authorize execution.
2. request_assistance takes location:local with agent_id, or location:group with explicit group_id and agent_id/capability. Select a group if no default exists; do not broadcast across groups. Disambiguate names with stable IDs.
3. Supply message, shared context, and optional result_schema (object by default). context must be a JSON object; its business fields may be strings, arrays, null, or other JSON values. For example {"task":"Find relevant papers"} is valid; context.task need not be a platform Task object. Node calls include source:{run_id,task_id}; managed nodes use their current token, while ordinary workspace calls may omit it. Standalone requests can omit source; the platform creates a built-in collaboration Run without making the caller a receiving member. Continue existing collaboration with collaboration_id. After start_collaboration adopts the caller, reuse its source/token.
4. The response contains a compact request, request.collaboration (standalone run_id/task_id), request.id, and legacy request_token. read_assistance(request_id) defaults to status, full structured result, and recent notification state, without logs/raw context/full history. Reading does not awaken an agent.
5. **pending/offered means awaiting acceptance, not nobody will accept.** The default acceptance deadline is 300 seconds, checked before first acceptance. A few seconds without a receipt, a temporarily empty directory, or repeated pending queries do not justify cancellation/recreation. Do other work or suspend with wait_assistance. An unmanaged external session may end its turn and await notification while retaining the request. Only terminal states such as unavailable establish that outcome. Explicit cancellation is still available when the user withdraws or work is no longer needed, with optional reason.
6. control_assistance supports cancel, input, and followup. followup defaults to the exactly recorded session; only explicit resume:false starts a new one. Sending cancellation does not prove remote execution stopped.

Legacy claim/grant rejection includes selection_decision with reason, sender source_state, deadline, and available cancellation/assignee details. not_selected alone does not mean canceled. Empty old-version receipts require checking the sender's record.

context_id selects a conversation default group; a one-call group_id override cannot bypass Run or execution scopes. Ordinary assistance does not require a native session ID. Trusted workspaces read/control by request_id; worker reports require their current execution identity.

Use both directory instance_id and agent_id where names/custom IDs repeat across machines. Do not guess. Helpers can read associated Loop/Task context through scoped read_context; this is read-only and grants no authority to report the original node's result. Standalone requests without a Loop return caller-provided context.

## Formal remote nodes

Keep kind:agent and configure dispatch:{location:group,agent_id:...} or capability. Bind the actual Run group; the receiving member uses its configured CLI. Ordinary local nodes retain their behavior. Remote machines respond only to explicit execution requests, not scheduling other source-Run nodes.

Formal read_task/report_task/finish calls forward through the receiver's scoped client to the source platform, preserving revisions, scope, contracts, and validation. CLI final text does not replace structured output. The original Task links to a communication request; the remote side creates no business Run.

Scoped read_asset retrieves Loop package assets into the receiver's request asset directory. Chunks verify package checksums and existing size limits; large business artifacts should use accessible shared references. Missing assets fail explicitly. Model login, dependencies, and cwd belong to execution-environment configuration. Published messages do not prove a real NAS deployment works.

## Standalone collaboration: a built-in Loop

### Entry agents and session registration

Letting the platform manage waiting/resumption means associating one execution with its native CLI session, not registering a Feishu Bot/current agent as a permanent receiving member. Choose by need:

| Scenario | Entry | What the current agent needs |
|---|---|---|
| Request help from Feishu/terminal, receive notification or read results later | Standalone dispatch Skill | No local platform, own execution_id, or named-member registration; the receiving platform creates a result-tracking Run |
| Suspend the current entry agent and automatically resume its original session on arrival | start_collaboration(caller=…) | Actual session, current agent process PID, and resume configuration; the platform returns execution_id, Run/Task/token |
| Register the actual CLI session of a node already running under the platform | register_agent_session | Its own execution_id and operation identity from the awakening context |
| Allow others to publish future work to a local agent | communication_config(operation=agent) | Named agent and exposure configuration; user-confirmed duties/scope before group exposure |

An entry without execution_id must not search other Runs to attach an unrelated execution. cc-connect does not call start_collaboration automatically; the entry agent/integration supplies actual runtime information as needed, without manual user registration. If process handoff is unavailable, use ordinary assistance/notification.

Codex CODEX_THREAD_ID is a native agent session identifier for context recovery. Feishu chat_id/thread_id/thread_root locate notifications. Saving chat origin does not require register_agent_session; these identifiers are not interchangeable.

Read read_capabilities({"capability":"standalone_collaboration"}) and live schemas. One complete collaboration is one Run. Later requests use returned run_id (or request.collaboration.run_id) as collaboration_id; control_assistance(action:followup) automatically continues that Run. Messages, logs, and progress do not each create Runs.

Ordinary assistance results enter the Timeline through built-in event-wait Tasks. request_assistance returns immediately; wait_seconds is an acceptance deadline, not a blocking tool duration. For ongoing coordination:

- **Platform-started coordinator:** start_collaboration({"message":"Complete collaboration task","agent_id":"EXPOSED_LOCAL_AGENT_ID","group_id":"JOINED_GROUP"}) returns Run/Task. The coordinator uses ordinary node reporting/wait/resume tools. Omit group_id for purely local collaboration.
- **Adopt the current conversational agent:** on the same machine, the adapter/current agent calls start_collaboration with caller.implementation (local startup/exact-resume configuration), caller.native_session (actual provider/id, optional cwd), and caller.process_id (the current agent PID, not a temporary tool subprocess). Do not infer sessions from chat IDs, use the latest session, or supply another machine's PID. The platform records this execution and returns run_id/task_id/execution_id/token without launching another agent.

After adoption, requests use source={run_id,task_id} and the returned token. To wait, call wait_assistance, then finish after success, and end the agent process. When assistance ends/wait expires and the original process has exited, the platform resumes the same session with new credentials. Arbitrary external chat windows do not automatically support process handoff; long-lived entries need adapter support. Use result tracking if exact runtime details cannot be supplied.

The resumed coordinator still reports event:completed with outputs.result (object). First completion of the entry also supplies settings.objective; then finish. Read current task_version through read_task. A helper's response does not complete the coordinator's task. Do not build polling or another communication scheduler; existing Engine handles pause/termination, event deduplication, and session recovery.

## Lightweight waiting and directory discovery

The dispatch Skill's wait(request_id or request_ids,timeout) waits inside its script and returns each request's status/full result. Timeout/interruption does not cancel work. To release an agent CLI and later resume its original session, use wait_assistance below. request_assistance supports agent_name resolved through the directory; explicit agent/machine IDs must also exist there. Retained offline directory entries may queue work. Receiving agents need a duties description before enablement; team exposure also needs user-confirmed duties/scope. Accepted node work retains its execution/session ownership despite disabling new work or leaving a group.

One Base link automatically configures readable fields and views for the agent directory, requests/results, and machine heartbeats. Requests/replies correlate by request ID; internal protocol JSON is hidden from those default views. The platform maintains readable fields; edit members through receiving-machine configuration. Tools query only directory/request IDs and resolve attachments automatically; agents need not read entire tables.

## Continuing after assistance

For automatic resumption, check assistance_session_resume; dependent Loops declare requires:["assistance_session_resume"].

1. A managed node registers its actual native session and accurate resume command; see [saving native IDs](terminal.md#store-the-real-native-id). An adopted start_collaboration caller reuses its returned execution identity.
2. Call wait_assistance(run_id,token,task_id,request_ids,seconds). Only after success, finish and exit. A remote node also completes its execution request after the source accepts finish.
3. After reply/deadline and original-process exit/identity release, the platform resumes **the same CLI session and Task**, with assistance_results and fresh credentials. Remote resumption pins the original machine, named agent, cwd, and resume configuration. The old token expires; no business node is added and waiting is not completion.

Missing session/resume configuration causes rejection. Legacy waits lacking it cannot start a fresh session through generic retry. Unknown process status, missing session files, or resume failure blocks/fails explicitly rather than switching sessions. CLI storage must remain on the original machine; automatic resume currently uses the macOS/Linux interactive-terminal backend.

Paused Runs or canceled Tasks do not resume automatically. Terminated Runs retain late results without progressing. Disabling an agent/leaving a group affects new work only; accepted Tasks resume on their original machine. The requester decides how to proceed without optional help; a required node lacking an executor cannot be marked complete falsely.

## Controlling communication context size

Check communication_context or the live schema. read_assistance's default compact view still returns full result. Logs/history are on demand. The platform retains required execution state and deliveries; acknowledged Base messages become cloud history. It does not duplicate a native session's full execution transcript.

For diagnostics, explicitly request:

```json
{"request_id":"REQUEST_ID","include_logs":true,"max_chars":4000}
```

Base terminal logs stay on the execution machine until include_logs requests them. With logs_pending:true, retain the cursor and query later; it is not an empty log or a reason for continuous agent polling. Mirrored child logs are readable at their source/execution platform. The web fetches logs only when output is expanded. Pages default to 4000 characters, configurable 1–16000; responses include logs, log_cursor, log_offset, and log_more. Continue with after=log_cursor and offset=log_offset, including across a single large chunk without dropped characters. Do not reread from zero or keep fetching after diagnosis.

include_details:true retrieves original business context/full notifications/history, not logs unless include_logs is also true. Read potentially large diagnostics only when relevant. Structured business results remain complete, without automatic semantic truncation; large artifacts should still use files/shared references.

assistance_results on resume contains only request summaries/results. Follow-up context keeps recent request summaries and original_context without recursively nesting old archives. Native-session resumption remains unchanged. Ordinary read_context retrieves authorized business context as needed.

## Remote execution client

The platform supplies scripts/communication.py; awakening context includes its local absolute path, platform_url, request_id, and scoped token.

It also supplies standard local platform_client and scoped platform_url. Existing call.py read_task/report_task/finish calls use that URL and forward through the team transport. communication.py uses execution_url for receiver tools when provided, otherwise platform_url. The scoped tool list states permitted operations; authors need not write a bridge client.

```sh
python3 /actual/client/path/communication.py --context request-context.json progress --arguments '{"message":"Searching"}'
python3 /actual/client/path/communication.py --context request-context.json complete --arguments '{"result":{"papers":[]}}'
```

Formal nodes use source_call for source tools, returning durable call.id. Only call.state=completed means source acceptance. For pending/executing, query source_result; on failed, inspect errors/possible effects rather than blindly repeat.

A remote node needing local help calls communication_status/request_assistance/read_assistance through this client. Local means the execution platform; group scope is restricted to the parent request's group. Local helpers retain that group-call scope, but their local request does not traverse NAS. Child results return to the source record too.

read_context provides read-only associated Loop/Task context, forwarding through the parent request when needed. This association does not grant authority to complete the original node. Without a Loop it returns supplied context.

native_session registers actual provider/id. agent_id determines assignment; session only preserves continuity. Resumption must match the source, named agent, and parent Task scope. Session IDs grant no cross-task authority. Reading logs does not awaken agents; never guess the latest session when the original is unavailable.

## Leaving, disconnection, and notifications

The platform handles heartbeats, availability, and execution reports without a resident model. Busy, disabled, offline, and left are different states. Disconnected in-flight work is unknown; timeout alone cannot justify reexecution. Confirm stopping before recovery. When the source returns it deduplicates by message ID and accepts results; sending and acceptance are recorded separately.

Cancellation of unknown execution records intent, not proof of stopping. After verification use confirm_stopped. Remote requests await receiver confirmation; related local-terminal occupancy is released too.

Shared directories publish complete/chunked messages with a 32 MiB logical-message limit. Large data uses artifact references. Unacknowledged messages persist for retry; logs persist separately by sequence number.

NAS separates inboxes/history: messages/<machine-ID>/ holds pending messages; messages/broadcast/ supports old in-flight announcements only. New dispatch targets one receiver. Acknowledged messages enter archive/<date>/<receiver>/, excluded from normal polling. Receipt confirms durable storage, not completion. Senders archive announcements after assignment/cancel/expiry. Publishing ACK stops periodic resends; duplicate original messages can trigger the same receipt again. Archival failure retains pending work/diagnostics and resumes after restart without blocking other messages. History/deduplication persists without age-based automatic deletion. Use communication tools, not custom moving/cleanup scripts.

Prefer NAS artifact paths only after confirming both sides can access them. Pass path and purpose in context/result; if mounts differ include shared-directory identity/relative path. This is independent of Base versus NAS communication. The platform does not read/upload referenced files. Helpers preserve complete artifacts rather than replacing them with summaries. If NAS is inaccessible or a cloud copy is requested, optional Feishu native attachments are available; see dispatch [shared files and optional attachments](../../loop-anything-dispatch/references/artifacts.md). Reading a result does not confirm its referenced file was read or clean NAS artifacts.

Acknowledged Base messages/receipts become cloud history outside ordinary polling; original records/results remain for optional manual cleanup. Daily communication needs no deletion permission. The new standalone Skill reads team results by ID without automatically copying full results locally or sending result-read receipts; use --output for an explicit offline copy. Old caches/in-flight read receipts remain compatible. Small states update in place and unsent progress coalesces. Inline messages exceeding 90000 UTF-16 units automatically use attachments; obsolete versions enter history.

Locally, execution state, deliveries, session locations, and deduplication fingerprints remain. Outbound payloads persist until delivered. Base messages no longer create full local archives. Successful executions with a registered native session do not retain duplicate terminal transcripts: include_logs returns logs_source=native_session with viewing guidance, using the original machine's resume facility. Executions without sessions, failures, and scripts retain diagnostics.

Old paths/message formats remain compatible. Service startup or mount changes make a one-time scan of old inbox records, archiving only acknowledged records this machine may handle. All machines must upgrade to fully stop old periodic ACK resends. Local database history remains; real multi-machine NAS performance/recovery requires deployment acceptance.

Notification titles show agent/progress. The first actual notification includes a request preview even if already executing/completed; later ones correlate by request ID without repeating it. Completion can show an existing short textual summary, otherwise a result-returned message. Do not present truncated JSON as a summary or require the helper to write summary. Requesters/resumed agents still receive full result. Machine names/internal Run/notification IDs are hidden by default; delivery/retry keeps identifiers/original snapshots. Feishu/WeChat chats are notification channels; Feishu Base is a separate communication transport. Missing notification configuration neither guesses recipients nor blocks results.

### Per-machine group outlets and priority

Check group_notification_priority. For new group requests without chat origin and without explicit notification_route, choose one sender per event: **action machine's group outlet → immediate requester's group outlet → no external notification, platform record only**. The requester owns request/timeout/unavailable events; the executor is preferred for start/progress/completion/execution failure. For A→B→C, the child falls back C→B, not root A.

1. Configure a named local outlet on each sending machine, e.g. cc-connect project and chat session. Each machine can use its own destination. Chat sessions differ from native agent CLI sessions.
2. Bind the current machine through communication_config:

```json
{"operation":"group_notifications","group_id":"group-ACTUAL_ID","notification_route":"feishu-research","notification_level":"key"}
```

3. communication_status.groups[].notification_bindings indexes bindings by instance_id. Changes require the local binding's id as binding_id; enabled=false disables only that outlet. Machines do not overwrite each other. The directory exposes sender/destination/level, while commands/credentials stay local. Saving sends no message.
4. Source platforms generate/deduplicate managed notifications; standalone dispatch notifications originate at the receiver. Team transport delivers them to the selected local adapter. read_assistance.notifications[].routing includes actor_instance, request_origin, sender_instance, binding_id, and reason: action_machine, request_origin, or no_bound_outlet. No outlet yields skipped without affecting execution.

Fallback applies only to absent/explicitly disabled bindings. A bound machine that is offline, fails, or has unknown delivery retains awaiting_delivery/fault rather than switching senders. Created notifications/explicit retries pin their original sender, destination, and command; binding changes affect future notifications only. Level defaults to the selected outlet unless request.notification_level overrides it. Filtered events do not move to another outlet.

Explicit request.notification_route still wins. Requests without groups use Run default/workspace. Business lifecycle/notify routing is unchanged. Nested assistance retains notification receipts at the root source to prevent duplicates, while fallback targets the child's immediate requester.

Legacy single bindings belong to their original sending machine, not arbitrary third-party fallback. Existing requests/notifications keep old policy; new group requests and group-bound follow-ups use new priority. All participants should upgrade; no automatic migration of running work or replay of historical notifications occurs.

Levels: attention (action needed), key (default milestones), detailed (progress summaries). Unavailable optional help does not always alert at attention level. Explicitly retry failed receipts with control_assistance(action:retry_notification,notification_id:...); verify unknown delivery first. Real NAS, multiple machines, models, and channels need separate deployment acceptance.

## Chat-origin notifications

With chat origin, follow the original conversation unless an explicit outlet overrides it. Without origin use group/Run routing above. Feishu capture, Bot mapping, saved roots, and fallback rules are in [cc-connect](cc-connect.md#follow-the-original-conversation-automatically).

## Directory reads and operation credentials

communication_status is public read-only discovery. Independent sessions need no Run/token to discover exposed members. The directory excludes CLI commands, local mount paths, and operation credentials.

Trusted workspace configuration, requests, reads, cancellation, and follow-up need no request_token. Results default to compact status/full result, with logs/context on demand. Legacy request_token remains compatible but is not workspace login.

- Run/Task token identifies an actual executor's operation scope and follows existing exit/resume lifecycle. Ordinary user calls may omit it; the platform manages temporary scope. Explicit invalid tokens still fail.
- Worker token allows progress/results for this accepted request only. Scoped worker entries can view only associated requests.

Native CLI session IDs restore context only. Assignment matches named agent, instance, and group, not session; stale execution writes are still checked. Managed nodes must retain their awakening entry/identity rather than widen scope through public workspace entry.

Use read_cc_connect/configure_cc_connect for bridge access. Named agents bind directly to Bots; create cc_connect={project,platform} notification outlets only for fixed destinations. See [local setup and Bot discovery](cc-connect.md#local-setup-and-bot-discovery).
