---
name: loop-anything-local
description: Use the Loop Anything client to schedule timed tasks or script-based condition checks, invoke scripts or agents, inspect or stop personal schedules, and receive tasks from a team server. Personal jobs need no web interface, server, or business Loop. Use loop-anything-dispatch to send work and loop-anything-platform to operate or build Loops with the same client.
---

# Local scheduling

This Skill covers local scheduling and receiving within the unified client. Install with `python3 install.py --role client` from source or a distribution; use the returned Python path with `-m loop_anything client local`. The same client operates Loops through `client tool`; install `loop-anything-platform` for Loop operation instructions when needed. Installation starts neither a server nor a receiver. The older `--role local` and `-m loop_anything local` remain compatible.

Confirm the registration directory with the user; a cluster can use a personal NAS directory. Use `list` to find, reuse, or update existing registrations. Registration does not start work. `start` the specific ID only when execution is requested. Moving machines or reloading the Skill must not automatically start historical jobs.

For a job the user wants to manage from the workspace's Scheduled Tasks page, register it on the server using the directory shown under “如何登记任务” as `--root`. The page lists those registrations and offers explicit start and stop. Personal client schedules in other directories remain accessible via their own CLI registry.

```sh
"<CLIENT_PYTHON>" -m loop_anything client local --root /nas/users/me/schedules list
"<CLIENT_PYTHON>" -m loop_anything client local --root /nas/users/me/schedules register task.json
"<CLIENT_PYTHON>" -m loop_anything client local --root /nas/users/me/schedules start <RETURNED_ID>
"<CLIENT_PYTHON>" -m loop_anything client local --root /nas/users/me/schedules show <ID>
"<CLIENT_PYTHON>" -m loop_anything client local --root /nas/users/me/schedules stop <ID>
```

`start` is a persistent process; it accepts multiple IDs and defaults to `--jobs 4`. Normal stopping closes the current action. Registrations survive machine shutdown. Use the user's existing terminal/process supervision for persistence, without configuring login startup by default. `stop` submits a request; verify the outcome with `show`. Killing the scheduler may leave child processes. `offline` does not prove completion, and an unconfirmed old execution blocks another start of the same registration.

`show.execution` identifies the action, host, PID/process group, start time, and captured original session. Only after actually confirming that a leftover action stopped, release its occupancy with `confirm-stopped <REGISTRATION_ID> --execution-id <ACTION_ID> --confirmed-stopped`. This does not start work and is unnecessary for normal registration, inspection, or clean restarts.

## Definitions and examples

Run a command periodically:

```json
{"name":"Organize artifacts","description":"Organize local artifacts every ten minutes","every":600,"command":["python3","/nas/me/organize.py"]}
```

Check an external condition and execute once when it holds:

```json
{"name":"Analyze after training","every":60,"check":["python3","/nas/me/check_training.py"],"command":["codex","exec","-"],"stdin":"Training has ended. Analyze the agreed results directory.","cwd":"/nas/me/project","agent_cli":"codex"}
```

- Choose either positive seconds in `every` or a timezone-aware ISO `at`. Explicitly starting a past `at` executes once immediately; reading old registrations never backfills execution.
- `check` exits 0 when satisfied, 1 to continue waiting, and another code on check failure. Checks default to a 60-second maximum. Conditional jobs default to one action; set `repeat:true` for intentional periodic use.
- An unconditional `every` repeats by default, measured from the previous completion, without overlap or accumulating missed occurrences. `repeat:false` runs once.
- `command` and `check` are argv arrays; invoke a shell explicitly for shell syntax. Optional fields include `cwd`, `stdin`, positive-seconds `timeout`, and `agent_cli`. An interactive CLI can set `terminal:true` and receive instructions via `{{prompt}}` / `{{prompt_file}}`.
- `register task.json --id ID` changes the definition for the next explicit start. Normal check/action failures stop that job and preserve the error rather than repeating unknown side effects.
- Retain only the latest result and bounded diagnostics. When a recoverable native session is identified, store its ID rather than copying the conversation. Commands write business artifacts to the user-agreed location.

Wake an agent only for actions requiring judgment; scripts perform recurring checks. Use `client tool <TOOL> --url <NAS_OR_HTTP_URL>` or the existing platform Skill's `call.py` with its saved connection to submit team-platform operations. Do not access the service database directly.

## Act as a team receiver

```json
{"name":"Local receiver","every":1,"receiver":{"server":"nas:///nas/team/loop-anything","name":"My compute node","capacity":2}}
```

`server` also accepts reachable HTTP(S). `capacity` defaults to 1, range 1–8. After registration and explicit start, `show` returns `runtime.executor_id`, also discoverable through platform `list_executors`. Concurrent receivers use different registration IDs. Select the returned executor ID in a node or named agent's `implementation.executor`. Required CLIs, working directories, and credentials must be available on the receiver.

The receiver executes processes; the team service advances the Loop state machine. Temporary disconnection records errors and keeps checking. Service restart reconnects original calls; receiver restart does not replay accepted commands with unknown results. A cancellation received before startup reports not-executed; already-started commands follow the original stop process. Task sessions resume on the original executor; preserve native CLI history on NAS when needed.

Remote queues and receipt waits are advanced by the service scheduler without occupying a service execution thread continuously. The executor persists and transfers large results in chunks; `delivering` means delivery is pending. Network retries resend results, not commands. Use `read_executor_call` for status and complete results.

Use the local mount path for NAS. Working directories and platform-generated tool/Skill references are adapted through explicit fields; ordinary parameters, instructions, replies, and command arguments remain unchanged. An argument needing the team directory can use `{{team_root}}/relative/path`. Other business files and CLIs must be available on the executor.
