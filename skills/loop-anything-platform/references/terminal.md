# Agent execution sessions and CLI integration

The platform provides live background-agent output and interaction tied to a Run, Task, and attempt. With a registered recoverable native session, it retains only a bounded live tail; successful exit keeps session location/business results and removes duplicate terminal text/prompt. `output_source=native_session` means resume the original session to inspect its execution history, not that nothing executed. Diagnostics remain for failures, absent native sessions, or custom agents lacking a resume command. Disconnecting a viewer does not stop execution; old history is not bulk-deleted.

This is an existing platform capability. Authors supply commands and business methods, not another log viewer, terminal server, identity map, or conversation proxy. Check `read_capabilities(capability="agent_terminal")` on the running service before relying on it.

## Ordinary commands: read-only output by default

Existing agent commands retain their behavior: the platform writes the full prompt once to stdin, closes input, and collects stdout/stderr continuously. Example:

```json
{"kind":"agent","command":["codex","exec","-"]}
```

Output timing depends on CLI flushing. The platform does not append model, permission, tool, or output-format options. Structured CLI output remains verbatim; not every agent emits detailed progress.

## Interactive terminals: input to the same process

Set candidate `terminal:true`. PTY hosts currently support macOS/Linux. Windows supports ordinary live output but rejects interactive startup explicitly.

Configure through public tools:

```json
{
  "tool":"set_implementation",
  "arguments":{
    "draft_id":"ACTUAL_DRAFT_ID","revision":1,"node_id":"ACTUAL_NODE_ID",
    "kind":"agent","terminal":true,"command":["codex","{{prompt}}"],
    "cwd":"/user-selected/workdir"
  }
}
```

`{{prompt}}` becomes the full task prompt in one argv element, without a shell. The CLI must accept an initial prompt argument; add only options that it supports.

For long context or file-aware CLIs, use `{{prompt_file}}`. The platform creates a private per-execution UTF-8 file (0600), substitutes its path, and also provides `LOOP_ANYTHING_PROMPT_FILE`. The program must read it; it is removed when the process ends. The placeholder does not make a CLI support file input automatically.

Interactive commands require at least one prompt placeholder. Long prompts are not simulated keystrokes; terminal stdin remains available for interaction. PTY uses TERM=xterm-256color, supports ANSI screen/input/resize, and maintains screen state and standard cursor/device responses without a viewer. Users manage CLI login, model, trusted directories, permissions, and tools. The program must be able to call platform tools to participate in a Loop.

## Task and exit contract

- Interaction connects to the same running agent, not a new agent or another task owner.
- Enter additional instructions or answer CLI questions directly. Ctrl+C is forwarded unchanged; the CLI determines its effect.
- Use read_task, report_task/complete_task, and finish to submit results. Terminal text is not a business result.
- After an interactive agent successfully calls finish, the platform stops that session's process group and saves output. Ordinary commands retain natural-exit behavior.
- A completed terminal is inspection-only; do not send instructions to an agent that lost its operation identity. Continue through task orchestration; retry creates another attempt.
- Configured timeout, platform shutdown, and unknown-process recovery still apply. Restart preserves output and marks old sessions interrupted; it does not automatically reconnect/resume vendor sessions or treat unknown side effects as success.

## Access and acceptance

Logs can contain working directories/business data. Input checks the actual terminal session and execution state. Runtime tokens are masked in persisted output; this is not general business-data redaction. Retained output is local SQLite data read by cursor, not shared with Loop packages. The original machine's CLI manages native session files.

`smoke_runtime` starts the configured interactive command and closes its probe after observing a marker. Because an interactive UI may echo the prompt, the check explicitly leaves model response unverified; echo is not model success. It cannot prove all interaction, login, or business tools work. `test_loop` remains simulated acceptance.

## Task results and native-session recovery

Use read_task/read_record/read_run for results/history; reading neither starts a CLI nor changes results. Existing capabilities inspect by execution identity, connect to live processes, and resume native sessions. Configure accurate identity/resume commands rather than creating another recovery service.

### Store the real native ID

Platform execution IDs and CLI session IDs are stored separately. Sources include:

- Codex: recognize thread.started.thread_id from `codex exec --json` or an explicit `session id:` output line. The platform does not add --json itself.
- Claude Code: recognize session_id in JSON/stream-json. Interactive startup can explicitly use `["claude","--session-id","{{session_id}}","{{prompt}}"]`; each execution receives a fresh UUID.
- A currently executing managed agent can call `register_agent_session(execution_id, provider, session_id, cwd)` with its actual CLI identity. A Codex tool process can read CODEX_THREAD_ID. Do not guess an unavailable ID, register another execution, or overwrite a different existing association. External entry without its own execution_id follows [entry/session guidance](communication.md#entry-agents-and-session-registration), not another Run's execution.
- Older executions may recover an ID from their own saved startup output. Otherwise the user supplies it explicitly. The platform does not scan unrelated CLI history or use --last.

Direct codex/claude commands can be recognized. Wrappers declare `agent_cli:"codex"|"claude"|"custom"` explicitly.

### Resume commands

Candidates may declare `resume_command` as argv:

```json
{
  "agent_cli": "codex",
  "resume_command": ["codex", "resume", "{{session_id}}", "{{prompt}}"]
}
```

For Claude use `["claude","--resume","{{session_id}}","{{prompt}}"]`; other CLIs can provide explicit commands. Include the real ID placeholder and a fresh `{{prompt}}` or `{{prompt_file}}` for current task context/user instructions. The user explicitly chooses the resume command; retain required model, permission, and profile options rather than guessing or adding them.

Recovery is available only for running/paused Runs and keeps the selected task branch's scope. Existing execution of the Task, an active native CLI session, or unknown old process state blocks duplicates. Repeated requests for an execution already resuming attach to its existing process.

Each recovery issues a new platform token; old tokens cannot be reused. Source tasks and committed results retain their historical meaning. Explaining results does not rerun work; modifications use explicit task tools. A recovered session's finish ends that conversation and releases scope without pretending the source Task completed again. Missing native CLI history remains a failure, not an automatic new session.

Retain the CLI's session files. An ID does not replace them and does not move them with a Loop package. The platform already provides registration, resume processes, and result viewing; authors need not rebuild them.

Interface references: [Codex JSON events](https://learn.chatgpt.com/docs/non-interactive-mode), [Claude session/resume options](https://code.claude.com/docs/en/cli-reference). Match the CLI version actually installed on the host.

### Recovery boundaries and corrections

Within one platform, a native CLI session stays exclusive until its process truly exits, including the interval after finish and recovery across Tasks/Runs. For unknown state, inspect records and confirm the old CLI and child processes stopped on the host before confirming stoppage through the platform and resuming. Confirming a recovered conversation's process stopped does not change the source business task's failure count.

Automatic native-ID detection is auxiliary. Conflicting IDs produce diagnostics and preserve the existing association without aborting business execution. Users may explicitly correct a wrong manual association. The platform checks the observed prior association, rejects replacing active/unconfirmed sessions, and preserves old-session and association-change history.

For direct Codex/Claude commands, the platform checks explicit resume syntax and a separate session ID, rejecting latest/continue/fork options. Authors of custom wrappers must ensure equivalent native recovery semantics.

An interactive CLI's own exit cleans children still in its process group. Detached or externally launched CLIs are not adopted. A user-provided agent may register its ID after its first report establishes an execution and before finish, with its own token/scope.

## Terminal clients and lightweight executors

Without the web UI, use `read_execution_session(run_id,execution_id,session_id?,after?)` for paginated output. `prepare:true` returns the saved native session and exact resume command. User-requested input uses `control_execution_session(action=input,data=...,session_id=...)`; continuation uses `action=resume,continuation={provider,native_session_id,command,cwd,message}` with preparation's identity/command. Execution stays on the original implementation.executor over HTTP/NAS. Verify unknown processes before confirm_executor_stopped or session confirm_stopped; neither automatically reexecutes work.
