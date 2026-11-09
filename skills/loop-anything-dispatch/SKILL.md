---
name: loop-anything-dispatch
description: Contact named agents on remote or other machines; request help, publish or delegate tasks, read complete collaboration results, and follow up. Dispatch-only clients need no Loop Anything platform installation or service. Connect through one NAS or Feishu Base team link. Loop nodes use the same Skill with their existing execution identity and wait/resume mechanism. Use loop-anything-platform for receivers, local agent configuration, and building or running Loops.
---

# Dispatch work to agents

`scripts/dispatch.py` works independently with Python 3.9+. A platform service receives work; a centralized team service can delegate execution to lightweight receivers without a full platform on every machine. Submission normally returns a request ID immediately. The caller may leave; the receiver does not need a second online grant from it.

## Ordinary sessions

Save the team link once. You may join both NAS and Base; old connections remain. An enabled, configured Base always has priority, irrespective of join order. NAS is used only if no Base exists or Base is explicitly disabled. Network, permission, and missing-agent errors on Base are reported, not retried through NAS. Use each machine's local NAS mount path. Feishu accepts Base links, including Wiki-hosted Base links, and reuses authenticated local `lark-cli`; user identity is the default, `identity:"bot"` selects app identity. A link grants no access by itself. Follow CLI authentication guidance rather than copying another process's credentials. Communication uses the new Base API through `lark-cli base +…` (verified with 1.0.98). If `--filter-json` is unsupported, run `lark-cli update`. Do not request legacy `bitable:app` or fall back to the old API; address the specific missing new-API scopes reported by the CLI.

```sh
python3 scripts/dispatch.py join --arguments '{"link":"TEAM_BASE_LINK_OR_NAS_DIRECTORY"}'
python3 scripts/dispatch.py agents --arguments '{"name":"Papers Agent"}'
python3 scripts/dispatch.py submit --arguments '{"agent_name":"Papers Agent","message":"Find papers relevant to this experimental hypothesis; explain evidence and limitations","context":{"hypothesis":"..."}}'
python3 scripts/dispatch.py read --arguments '{"request_id":"RETURNED_REQUEST_ID"}'
```

Choose helpers by their **main-purpose descriptions**. Look up even a user-specified name in the directory. `submit` resolves `agent_name` to the real agent_id + instance_id; disambiguate duplicate names using returned IDs. Supplying both IDs still requires directory resolution. Offline members that remain registered can queue work; unknown IDs are not guessed or published blindly. Joining does not expose the caller as a receiver. On failed or uncertain publication, retain and retry the same `request_id`, not a new task. `pending` means acceptance has not yet been observed; the default acceptance deadline is 300 seconds. Do not cancel and resend after seconds. Read results later or use a managed Loop wait rather than agent polling.

Text replies normally go directly in `result`, are stored in Base, and are read in full through tools. **Prefer shared paths only after confirming both parties can read that NAS.** Most machines sharing NAS does not prove that this recipient can. Put paths and their purposes in `context` or `result`; include a shared-directory identity and relative path when mounts differ. The platform passes references unchanged and does not read/upload the referenced files. Preserve complete deliverables; do not substitute a summary for the full answer. Use [native Feishu attachments](references/artifacts.md) when the recipient cannot access NAS or a cloud copy is explicitly needed.

`read` returns complete business results without automatically adding execution logs. Base inline messages over 90000 UTF-16 units automatically use native attachments and are read back in full. This fallback does not require reading shared files into messages or uploading every artifact. NAS retains chunked transport. Over 32 MiB, pass an accessible artifact reference. To keep a large answer out of immediate context, use `read --output /absolute/path/result.json` and inspect the saved complete response as needed; it is not summarized or truncated.

Base retains requests and complete results. Handled messages move out of routine polling into cloud history; normal communication neither deletes them one by one nor requires delete permission. Users may clean handled history while retaining in-flight work. `read` accesses team results directly, without automatically caching the full answer or sending a result-read receipt. For requests in a terminal state, the local client retains only cloud references; use `--output` explicitly for offline results. Old caches remain readable, and old receivers retain read-receipt compatibility. The platform keeps workflow state, delivered results, and session locations, not another full copy of native conversation history. Resume the original session to inspect a completed agent's execution history.

## Wait for results with lightweight wait

```sh
python3 scripts/dispatch.py wait --arguments '{"request_id":"RETURNED_REQUEST_ID","timeout":300}'
python3 scripts/dispatch.py wait --arguments '{"request_ids":["request-A","request-B"],"timeout":300}'
```

The script polls and returns once with complete results on terminal status or timeout. Multiple results are associated by request ID; completed requests are not repeatedly fetched. `finished` means every request is terminal, including failures. `timed_out` ends only this wait, without cancellation, resubmission, or restart; later `read`/`wait` remains available. Base checks no faster than every 15 seconds, NAS defaults to every second. `timeout` defaults to 300 seconds and differs from submit's acceptance deadline `wait_seconds`. Increase `poll_interval` when appropriate. The CLI process waits, not the model. Give the terminal tool enough execution time or use a background command session. Interrupting the wait does not withdraw requests. `--output` also saves complete results without filling agent context.

Managed Loop nodes should use `wait_assistance` / `finish` and exit the CLI for original-session recovery. Do not replace their state-machine wait with this lightweight command.

Use `group_id` in agents/submit to select a team explicitly. Among several teams on the same medium, the selected team remains; specify one when none is selected. `leave --arguments '{"group_id":"TEAM_ID"}'` disables that connection for new work; omitting the ID disables the current default. Rejoining reenables it. Reading, waiting, retrying, cancelling, and following up existing requests always use their original connection, regardless of a changed default. One wait can include requests across media.

Follow up using `control` with `{"request_id":"...","action":"followup","message":"..."}`. It reuses the recorded original session by default. Missing sessions are reported; use `resume:false` only when the user explicitly wants a new session. Cancel with `action:"cancel"`; send interactive input with `action:"input",message:"..."`. A cancellation submission is not proof that the process has ended.

Feishu cc-connect entry automatically carries `CC_PROJECT` / `CC_SESSION_KEY`. Pass existing `chat_context`, including a real `thread_root`, directly. The receiver uses existing Bot mappings and original-conversation rules, without message-history or permission preflights. Delivery depends on configured cc-connect/notification outlets; task records and results do not depend on notification success.

## Existing Loops and local agents

When the context supplies a scoped `tool_url`, retain it (the same endpoint as platform call.py's `--url`):

```sh
python3 scripts/dispatch.py submit --tool-url 'EXISTING_SCOPED_TOOL_URL' --arguments '{"location":"group","agent_id":"papers","message":"..."}'
```

The platform associates the request with the current Task and uses the same dispatch implementation. The source platform retains ownership of the Run. Use equivalent native `request_assistance` / `read_assistance` tools when provided; no extra CLI wrapper is needed. Do not bypass the scoped endpoint to create unrelated standalone requests.

For background nodes supplied with platform_url / run_id / token, use `--platform-url`, `source:{run_id,task_id}`, and the token to register the request. Keep its Task association.

An ordinary workspace or local named-agent call can use `--platform-url` with `location:"local"`; it is not published to remote teams. Loop nodes needing assistance before continuing use the platform Skill's `wait_assistance` / `finish` and restore their real original session. Installing only the dispatch Skill does not make an ordinary chat platform-managed; automatic recovery requires `start_collaboration` first.

Base creates Agent directory, requests/results, and machine-heartbeat views with readable names, purposes, states, and replies; protocol JSON is hidden by default. Receivers publish directory and acceptance settings; edit purpose through the owning platform. Tools derive online status from heartbeat. Agents use agents/read/wait for the needed records rather than scanning or manually parsing the whole Base.

Configuration defaults to `~/.config/loop-anything-dispatch`, overridable with `--config-dir` or `LOOP_ANYTHING_DISPATCH_HOME`. It stores team connections, caller identity, and each request's original connection. Old single-connection configuration remains usable. If it overwrote a connection required by an old request, rejoin the original link; the tool will not redirect that request to a new team. Separate configuration directories provide independent dispatch identities.
