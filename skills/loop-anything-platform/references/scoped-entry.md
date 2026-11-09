# Scoped tool entry

When wake-up context supplies `tool_url`, retain that execution endpoint. Read its directory with `scripts/call.py list --url <tool_url>`. Supply identity fields as its schema requires; do not switch endpoints to bypass scope. Without `tool_url`, use the ordinary platform entry and actual Run/Task identity.

Node sessions only handle current Run tasks, reporting, waiting, and recovery. Read the task and current state, submit with the corresponding versions/scope, then `finish`. Edit reusable Loop definitions through an independent building agent or source files, not a node session.

Independent web-agent conversations and preparation-session tools have been removed. Start with `start_run`; see [runtime tools](run.md) for tasks, reports, waits, and recovery. Do not call retired `read_preparation`, `change_preparation`, or `start_prepared_run`.
