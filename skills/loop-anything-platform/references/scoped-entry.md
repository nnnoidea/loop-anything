# Scoped tool entry

Managed wake-up processes automatically carry their scoped work binding. Read the directory with `scripts/call.py list` and call tools without selecting a URL. Supply execution identity fields required by the schema; the script and server preserve the original scope. A separately started Agent must use discovered resources and the returned work_id instead of guessing an endpoint.

Node sessions only handle current Run tasks, reporting, waiting, and recovery. Read the task and current state, submit with the corresponding versions/scope, then `finish`. Edit reusable Loop definitions through an independent building agent or source files, not a node session.

Independent web-agent conversations and preparation-session tools have been removed. Start with `start_run`; see [runtime tools](run.md) for tasks, reports, waits, and recovery. Do not call retired `read_preparation`, `change_preparation`, or `start_prepared_run`.
