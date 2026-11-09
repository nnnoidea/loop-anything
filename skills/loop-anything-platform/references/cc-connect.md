# Optional adapter: cc-connect

This supplied example implements the [generic notification interface](notifications.md). Other bridges and terminal-only use do not require cc-connect. The platform does not create Bots, manage chat sessions, or start the bridge for users.

## Prerequisites

The user has installed/configured [cc-connect](https://github.com/chenhg5/cc-connect) and connected the target channel. The entry agent and platform use the same platform instance. These examples require the adapter, Python, and cc-connect command on the platform host.

Channel capabilities depend on the bridge/version. Follow its documentation for Feishu/WeChat login, Bot setup, and send limits. Adapter integration alone is not a successful real-channel test.

Notifications use official `cc-connect send` over its local Unix socket. The bridge main process creates the socket; no separate socket service, HTTP management interface, or HTTP token is needed. Working Bot chat does not prove CLI delivery works. For socket errors, inspect bridge startup logs and the real data directory. The CLI locates run/api.sock using explicit --data-dir, then CC_DATA_DIR, then its user default. Save the correct directory with configure_cc_connect rather than implementing another sender or per-notification preflight.

## Local setup and Bot discovery

Read local configuration, revision, and bots with read_cc_connect. Configuration is shared across this platform user's workspaces, stays local, and is not shared in Loops/NAS. Bot credentials remain in cc-connect's configuration.

When unset, determine the running bridge's actual config file and call configure_cc_connect:

```json
{"revision":0,"connection":{"config_path":"/actual/path/config.toml","executable":"/actual/path/cc-connect"}}
```

executable may be omitted for PATH discovery; no config directory is guessed. data_dir comes from configuration. Supply an absolute override for a different directory or a relative configured path. Setup saves the resolved directory. If none is configured, no --data-dir is added and cc-connect chooses its default. Reading a config does not prove the running bridge loaded it; changes must take effect there. `connection={}` clears local setup.

read_cc_connect.bots returns project, platform, label, selectable, and ambiguity reasons, never secrets. Do not read private configuration yourself, write sending scripts, or create an outlet for every Bot. Multiple same-type Bots in one project are reported as ambiguous and not automatically chosen in the UI. Tools accept explicit user-provided project/platform references without using config readability or directory membership as save gates. cc-connect handles actual selection. Reading refreshes discovery without installing/starting Bots or sending tests.

Bind a named agent using a discovered reference through communication_config:

```json
{"operation":"agent","agent_id":"papers","agent":{"notification_bot":{"project":"papers","platform":"feishu"},"notification_route":""}}
```

notification_bot=null clears mapping. Legacy notification_route remains supported; choosing either mapping clears the other, and two nonempty mappings are invalid. Changing a Bot does not change agent commands or sessions.

## Follow the original conversation automatically

call.py carries CC_PROJECT, CC_SESSION_KEY, and available chat_context with business requests. The platform persists entry Bot, raw session, chat/topic, and real root message ID. Notifications do not need native agent-session registration; continuation is separate in [entry/session registration](communication.md#entry-agents-and-session-registration).

- Known direct chats reply through the entry Bot. In groups/unknown chat types, execution acceptance/results prefer the named agent's Bot, falling back to the entry Bot when unmapped.
- Nested assistance inherits the original chat. Explicit notification_route/conversation_id can override it; the destination does not follow whichever chat the current agent is now using.
- The adapter only calls cc-connect send. It does not query membership, permissions, chat type, or topic settings; call Feishu APIs; read Bot secrets; or require the Loop service to copy cc-connect's secret environment. **Do not use relay send for notifications: it invokes the target agent again.**
- Sending does not reread configuration or Bot directories. Those are for setup/discovery; sending uses the saved binary/data directory. Update local setup if the bridge directory changes.
- With thread_root and a recognized thread-form session, construct a root target from the actual root message. Existing root targets and other formats pass through unchanged. Without a root, pass the raw session_key to cc-connect without history lookup or credential hunting. Never substitute a topic ID for a root message ID.
- The running bridge handles delivery, membership, and topics. Loop preserves the original session and does not downgrade to the group timeline. Record actual outcomes. Missing binary, execution permission errors, explicitly absent/unconnected sockets, missing projects, or Feishu's explicit Bot-not-in-chat rejection (230002) can fall back to the entry Bot under the existing policy. These facts come from the actual call's receipt, not another membership query. Other failures, disconnects, or timeouts do not switch Bots automatically.

cc-connect main 9bef91f was verified to reconstruct uncached reply targets from root message IDs, but a real thread ID is not a message ID. Preserve a root when supplied by the entry event; otherwise let the actual bridge handle/report the raw target. Loop does not add another lookup/preflight implementation. This does not assert every bridge version supports every topic format.

Direct HTTP/MCP clients can pass metadata:

```json
{"chat_context":{"platform":"feishu","entry_project":"ENTRY_BOT_PROJECT","session_key":"feishu:oc_chat:root:om_root"}}
```

Include chat_id/thread_id/thread_root when present in the entry event. chat_type is optional and otherwise unknown. Workers cannot rewrite the entry origin. The platform extracts/persists ordinary cc-connect root sessions automatically, without extra environment variables.

Legacy clients can register conversation_id with `communication_config(operation=conversation,conversation=METADATA,notification_command=LOCAL_ARGV)`. Old --config/--platform/--conversation arguments remain parseable but are not send preflights. Custom instances must supply actual --data-dir or use machine-level setup.

## Named platform outlets

Direct Bot mapping and original-chat replies need no named outlet. Use one for a fixed destination, such as group notifications without chat origin. Read channels/revision with read_notification_channels, preserve existing entries, then set_notification_channels:

```json
{"revision":0,"channels":{"research-updates":{"label":"Research updates","cc_connect":{"project":"research","platform":"feishu"},"destination":"RAW_FEISHU_SESSION_KEY"}}}
```

Omit command, cwd, identity, and channel; the platform resolves the Bot reference. Generic command outlets retain their original contract. See [group notification priority](communication.md#per-machine-group-outlets-and-priority).

An agent may read the Timeline and use send_event for a user's answer. This adapter sends only; it does not take over chat entry.

## Generate a send command for the current chat

This supports legacy explicit-command workflows. Prefer platform setup tools for new integration.

From an agent invoked in the destination chat, run at the Skill root:

```sh
python3 scripts/notify_cc_connect.py --print-command > notification-command.json
```

It sends nothing. It reads CC_PROJECT, CC_SESSION_KEY, and optional CC_DATA_DIR and creates JSON argv with the destination/local paths. Explicit --executable, --data-dir, and --config are accepted. Missing project/session/executable is an error, not a guessed target.

Configure the Run through generic tools:

```sh
python3 scripts/call.py start_run --notification-command @notification-command.json --arguments @startup.json
```

For an existing Run, keep it. Acquire global scope and use the latest settings version:

```sh
python3 scripts/call.py change_settings --notification-command @notification-command.json --arguments @changes.json
```

Once saved in the Run, the temporary JSON file is not a runtime dependency; the adapter and executable paths still are. The command binds the chat at generation time. Changing chats does not alter it; reconfigure only for an explicitly requested destination change.

## Sending behavior

The background service passes notifications to scripts/notify_cc_connect.py, which invokes:

```text
cc-connect send --project SELECTED_PROJECT --session SELECTED_SESSION --data-dir SELECTED_DIRECTORY --stdin
```

The body includes Run name/ID, notification text, available task state, and notification ID. Arguments use argv, body uses stdin. Return delivered=true only on cc-connect confirmation. Failure/timeout follows existing notification records and retries.
