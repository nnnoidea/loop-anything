# Team server and clients

| Role | Install/run | Responsibility |
|---|---|---|
| Server | `install.py --role server`; one machine runs `serve --team-dir /nas/team/loop-anything` | Shared definitions, Runs, Timeline, state machine, tools, optional web UI |
| Client | `install.py --role client`; install the bundled Agent Skills | Inspect/edit/run Loops through NAS/HTTP tools, receive and execute assigned work, and run personal timed/conditional jobs; no server database or web service |

Both roles use the same package and can coexist on a machine. A client starts receiving only when requested; installation, registration, and history reads never start work. Personal jobs need no server. Existing independent platforms and NAS/Base named-agent communication remain supported without migration to centralized service mode.

## Install and use a client

```sh
python3 install.py --role client
# Use the actual Python path returned by the installer.
"<CLIENT_PYTHON>" -m loop_anything skills --install-dir <AGENT_SKILL_DIRECTORY> --url nas:///local-mount/team/loop-anything
"<CLIENT_PYTHON>" -m loop_anything client tool list_loops --url nas:///local-mount/team/loop-anything
"<CLIENT_PYTHON>" -m loop_anything client local --root /nas/users/me/schedules list
```

The platform Skill supplies editing/running tools; dispatch supplies named-agent communication; local supplies scheduling and receiving. These are task-specific instructions for one client, not separate installation roles. `client tool` forwards to the existing `call.py` (including `--arguments`, `--request-id`, `--wait`, and `--output`); `client local` forwards to the existing local scheduler. Use the exported Skill's `call.py` to reuse its saved `connection.json`, or supply `--url` to the installed client.

Clients that only submit operations or dispatch work can still use the exported Skills with Python 3.9+, without installing the runtime. Install the client runtime when local execution is needed. The previous `--role platform` / `--role local` names remain aliases for server/client, and the `local` command remains compatible. Existing registrations and executor IDs are unchanged.

## Connect to the team service

```sh
"<PLATFORM_PYTHON>" -m loop_anything serve --team-dir /nas/team/loop-anything --port 8767
# Provide NAS tools without HTTP or a web interface.
"<PLATFORM_PYTHON>" -m loop_anything serve --team-dir /nas/team/loop-anything --no-web
```

Machines use the same team directory through their own mount paths. Store `{"url":"nas:///local-mount/team/loop-anything"}` in client connection.json, or pass `call.py ... --url nas:///...`. NAS clients need not connect to the service's network port.

HTTP uses a reachable service URL; `--host 0.0.0.0` exposes listening on a trusted internal network. `--public-url http://reachable-host:8767` chooses callback URLs in task context; team mode defaults to NAS callbacks. Both entries use the same tools, revision checks, execution identities, and original-session recovery. The service does not provide a public-network authentication gateway.

NAS calls wait up to 30 seconds by default. `pending` means the operation remains queued; do not resubmit:

```sh
python3 scripts/call.py create_loop --arguments '{"name":"Research"}' --request-id api-my-operation --wait 0
python3 scripts/call.py result --request-id api-my-operation
```

Retrying an ID requires identical arguments; the service executes it once. A crash after operation submission but before saving its receipt yields `outcome_unknown`: query the target state before deciding what to do, rather than retrying under a new ID. Business report_id and version checks still apply. Records live in api/requests, api/history, api/replies, and invalid input in api/rejected. Read results through tools, not by scanning all JSON files.

## Execute nodes on clients

Register and explicitly start the client's receiver using the [local Skill](../../loop-anything-local/SKILL.md), then read names, IDs, and online status through `list_executors`. The protocol calls a receiving client an executor; this is not another installation role. Configure through authoring tools:

```json
{"draft_id":"RETURNED_DRAFT_ID","revision":1,"node_id":"analyze","kind":"agent","executor":"RETURNED_EXECUTOR_ID","command":["codex","exec","-"],"cwd":"/nas/project"}
```

`executor` supports agent, command, and external (both submission and observation run there). Omission executes on the service machine. Named-agent implementations also support executor for central registration with remote execution. `dispatch` retains named-agent communication semantics and cannot coexist with executor in one implementation.

The service owns the single business Run and Task execution. Executors run commands, persist acceptance receipts, and return results; the service owns the directory and notifications. Existing context carries inputs, author Skills, and tools. Do not rebuild receiving, polling, result-writeback, or log services. `execution_executor` is the chosen execution host; `self` still identifies the connected team service. `read_executor_call(id)` returns one call's state, result, and associations. Terminal interaction reaches the original process. `read_execution_session` reads cursor-paginated output; `prepare:true` returns the native session and resume configuration. On user request, `control_execution_session(action=input/resume)` operates that process/exact session without a browser.

After dispatch, the service releases its execution thread and schedules progress/results; offline queues do not exhaust the local worker pool. Execution and delivery states are separate: `delivering` means the command ended but its complete result still needs delivery. The same call's result is resent automatically. Large results are persisted and delivered in ordered NAS/HTTP chunks, not turned into business process_error retries merely for size. Agents need not implement chunking, compress full replies, or create another task to retry transport.

Different mounts are adapted only in explicit working-directory, platform-address, and resolved Skill-reference fields. Business names, inputs, instructions, replies, and arbitrary argv text remain unchanged. Use `{{team_root}}/relative/path` explicitly in arguments needing the team root. The service transfers structured context and renders the original prompt template on the executor, without guessed substitutions across prose. HTTP executors still need configured files; the platform does not distribute business environments automatically.

Assistance still uses `wait_assistance` + `finish`, resuming the exact native session on its original executor with its ID/command, never `--last`. Service restart reconnects the original call rather than starting another process. Receiver exit/disconnection does not redispatch. Accepted calls with unknown results become unknown; inspect the old process before `confirm_executor_stopped(id,confirmed_stopped=true)` releases unknown occupancy. Late terminal receipts can use the same confirmation path; read their actual results first. Confirmation does not retry the task. A receiver registration cannot run twice concurrently.

## Persistence boundaries

Only the team service opens platform.sqlite3; others use NAS/API. It obtains an exclusive file lock before writing through SQLite DELETE journal. Do not treat an old WAL database as a multi-host shared database. A replacement service acquires the same lock before taking over, preserving workspace/Run identity.

NAS must implement file locking, atomic replacement, and durable writes correctly. Local temporary-directory tests do not establish real NAS semantics. Validate two-machine exclusion, result visibility, and service migration on the actual cluster. Do not point several services at the database or use another machine's --db to bypass tools. Existing single-machine databases are not automatically moved or merged.

Personal registrations differ from running instances: definitions/latest results remain in the selected directory, while processes stop with the machine. Inspecting history, starting another job, or changing machines never restarts old jobs. Persistent team-service recovery and personal explicit start are distinct lifecycles.

Personal actions persist execution identity before launch and release occupancy on normal exit. After killing an executor, use local show to inspect leftovers. Only confirm-stopped on the exact action after verifying it stopped, then explicitly start again if wanted. Old heartbeats or a missing parent scheduler do not authorize another execution.
