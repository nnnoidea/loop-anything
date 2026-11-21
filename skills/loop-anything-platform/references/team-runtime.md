# Team platform operation

Install Loop Anything with `python3 install.py`. There is one installation path; do not ask the user to select a server/client role or a deployment mode. Installation includes the local platform, task tools and team connections. Configure addresses/defaults with `spaces` afterwards.

The default selects recorded addresses, preferring team when both exist unless the user chooses otherwise. A space owns work and records; execution machines are configured separately. A team task can run on a member’s machine. Server/client remain internal responsibilities in the same application.

## Use the installed tools

```sh
python3 install.py
loop-anything spaces --team-url nas:///local-mount/team/loop-anything
loop-anything skills --install-dir <AGENT_SKILL_DIRECTORY> --url nas:///local-mount/team/loop-anything
loop-anything tool list_loops --space team
loop-anything client local list
```

The three Skills organize instructions by capability: platform work, dispatch, and local scheduling/receiving. `client tool` exposes the full transport options of `call.py`; `client local` uses the existing local scheduler. Work origins are bound automatically; exporting/updating Skills never changes addresses or defaults. Receiving and personal jobs require an explicit start.

## Host the team platform after installation

Use the runtime commands below to configure team hosting. On macOS, stop the automatically installed local background platform before running the same platform in the foreground. These are runtime settings, not alternative installers.

## Connect to the team service

```sh
"<PLATFORM_PYTHON>" -m loop_anything --db /srv/loop-anything/workspace.sqlite3 serve --space team --team-dir /nas/team/loop-anything --port 8767
# Provide NAS tools without HTTP or a web interface.
"<PLATFORM_PYTHON>" -m loop_anything --db /srv/loop-anything/workspace.sqlite3 serve --space team --team-dir /nas/team/loop-anything --no-web
```

Machines use the same team directory through their own mount paths. Run `loop-anything spaces --team-url nas:///local-mount/team/loop-anything`, then select `--space team` for a new call. Existing work keeps its original platform automatically; use its returned work_id if resource names are ambiguous. NAS clients need not connect to the service's network port.

Use this same NAS root for every communication entry. The platform manages the internal layout:

```text
TEAM_DIR/
  api/        platform tool requests and receipts
  executors/  client process dispatch, progress, results, and session controls
  agents/     named-agent directory, assistance requests, and replies
```

Starting with `--team-dir` creates/connects the `agents/` team too. Named-agent configuration uses `communication_config(operation=team,link=NAS_ROOT)`; standalone dispatch uses `dispatch.py join` with that same root or `nas:///...` URL. Callers need not remember an `agents/` link. Read `communication_status` for the team ID and expose only user-confirmed named agents; connecting does not publish them automatically. Base retains its configured priority. Explicitly joining a unified NAS root selects it for future NAS dispatch when no Base is preferred. Existing Runs, bindings, request IDs, and disabled memberships retain their state. NAS communication uses the unified root layout; existing requests retain their recorded transport without moving messages during execution.

`--db` selects server storage independently of `--team-dir`, which is only the communication mailbox. The database, installed packages, configuration, and final results can remain on server storage; clients need no access to that directory. New mailboxes without `--db` use the normal local default database. Existing databases must be selected explicitly with --db. Nothing is automatically moved or deleted. NAS discovery returns the actual server `database` with `database_location:server`, and the client's own mailbox path separately; do not open that database from a client.

HTTP uses a reachable service URL; `--space team --host 0.0.0.0` exposes listening on a trusted internal network. `--public-url http://reachable-host:8767` chooses callback URLs in task context; team mode defaults to NAS callbacks. Both entries use the same tools, revision checks, execution identities, and original-session recovery. The service does not provide a public-network authentication gateway.

The fixed health URL is `http://SERVER:PORT/api/health`. It uses plain HTTP without certificate checks and returns a small JSON response. For a test through an HTTPS proxy, the caller can use `curl -k`; see [health URL](connection.md#fixed-http-health-url). This optional check starts no work and is unavailable with `--no-web`.

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

Update the receiving client runtime when enabling private server storage. Declared Loop assets travel with the execution request over the existing NAS/HTTP transport and are materialized in the receiver's resource cache. This includes scripts and Skills; a shared server package directory is not required. Package working directories and instruction references point to that cache, exposed as `resource_root`. For a later tool reply containing server-side Skill paths, use its declared relative `path` under the supplied `resource_root`. External data, CLIs, credentials, and explicitly configured working directories still belong to the recipient environment.

Different mounts are adapted only in explicit working-directory, platform-address, and resolved Skill-reference fields. Business names, inputs, instructions, replies, and arbitrary argv text remain unchanged. Use `{{team_root}}/relative/path` explicitly in arguments needing the mailbox root. The service transfers structured context and renders the original prompt template on the executor, without guessed substitutions across prose. Resource snapshots share the existing 32 MiB request bound; declared assets use the existing 20 MiB limit. Completed execution inbox messages and their transport parts are removed; caches remain with the receiver.

Assistance still uses `wait_assistance` + `finish`, resuming the exact native session on its original executor with its ID/command, never `--last`. Service restart reconnects the original call rather than starting another process. Receiver exit/disconnection does not redispatch. Accepted calls with unknown results become unknown; inspect the old process before `confirm_executor_stopped(id,confirmed_stopped=true)` releases unknown occupancy. Late terminal receipts can use the same confirmation path; read their actual results first. Confirmation does not retry the task. A receiver registration cannot run twice concurrently.

## Persistence boundaries

Only the server opens its database; clients use NAS/API. The service locks both the database and its NAS mailbox before opening the platform database. A second database cannot consume the same mailbox concurrently; the mailbox's platform identity also prevents attaching unrelated server data. NAS carries routing metadata, requests, receipts, progress, and transport chunks, not a copy of the platform data. Team services retain SQLite DELETE journaling, including when the selected database is local.

NAS must implement file locking, atomic replacement, and durable writes correctly for the mailbox. Local temporary-directory tests do not establish real NAS semantics. Validate two-machine exclusion and result visibility on the actual cluster. Changing service machines requires preserving/restoring the platform data (database plus packages/configuration/results), then attaching its existing mailbox; mailbox messages alone cannot reconstruct Run history. Stop the old service before relocating its data. Existing databases and NAS history are not automatically moved, merged, or deleted.

Personal registrations differ from running instances: definitions/latest results remain in the selected directory, while processes stop with the machine. Inspecting history, starting another job, or changing machines never restarts old jobs. Persistent team-service recovery and personal explicit start are distinct lifecycles.

Personal actions persist execution identity before launch and release occupancy on normal exit. After killing an executor, use local show to inspect leftovers. Only confirm-stopped on the exact action after verifying it stopped, then explicitly start again if wanted. Old heartbeats or a missing parent scheduler do not authorize another execution.
