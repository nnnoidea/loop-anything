# Notification interface and optional bridges

Platform tools and notification sending are independent interfaces. Agents from any entry use `scripts/call.py` to discover, read, and edit the same Run, following [run.md](run.md) for write scope. Chat bridges receive messages and manage agent sessions, not Engine state decisions.

A notification adapter receives JSON, sends to an explicit destination, and reports the actual result. It is an ordinary command, without plugin registration, SDK, or internal platform dependencies. Users choose the bridge; the supplied [cc-connect adapter](cc-connect.md) is optional.

## Configure platform outlets

Use `read_notification_channels` for revision, channels, and discovered local cc_connect Bots. Pass the latest revision and complete edited channels mapping to `set_notification_channels`, preserving unchanged outlets. Configuration stays on this platform, is excluded from Loop packages, and sends nothing immediately.

Each outlet has an ID, label, channel, identity, destination, command (argv), and optional cwd/timeout. Commands implement the contract below. The built-in workspace outlet needs no configuration. Adapters interpret identity/destination; setting these fields on an arbitrary script does not make it honor them.

For cc-connect, configure the local bridge with read_cc_connect/configure_cc_connect. Outlets use `cc_connect={project,platform}` plus explicit destination, without command/identity/channel. Named-agent Bot mapping needs only agent.notification_bot, not an outlet. See [cc-connect](cc-connect.md).

Choose the Run's default outlet ID with start_run.notification_route or change_settings.change.notification_route; workspace is also valid. Changing chat entry does not change the outlet.

Loop declarations may select only default (this Run's outlet) or workspace, not personal outlet IDs. Retired implementations.$notifications must be moved to local outlets and removed from drafts before importing/sharing old Loops. Run notification_command remains local invocation configuration and is not shared with Loops.

## Proactive messages and questions

`notify` takes run_id, stable key, message, and optional task_id/route/reply. Agents supply their token; branch agents specify a task_id in their scope. Scripts supply context token, task_id, and execution_id. Authorized trusted-workspace user agents may call directly; managed nodes retain their own scope.

```json
{"run_id":"RUN_ID","token":"TOKEN","task_id":"TASK_ID","key":"TASK_ID:progress-1","message":"Stage results recorded","route":"default"}
```

Identical key/content returns the original notification without another send; different content under the same key conflicts. No new Task is needed. Scripts may import notify(context,key,message,**fields) from context.report_client and call before execution ends. Post-completion notifications can attach to the completed transition.

Questions add reply with event, key, and schema:

```json
{"event":"reply","key":"question-1","schema":{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}}
```

A question does not itself pause work. If an answer is required, arrange an event-wait node with the same event/key and an output contract matching the reply schema. Inspect notifications with read_run and the wait with read_task; submit send_event using stable event_id, name, key, payload, and optional notification_id for reply-schema validation. Branch agents also specify their scoped waiting task_id. Authorized external entries can submit facts without occupying an agent session. The sending channel and reply-submission entry may differ.

## Author and user timing choices

Authors add a notify array to an existing lifecycle row:

```json
{"from":"executing","event":"completed","to":"completed","notify":[{"message":"Result: {outputs.result}","route":"default"}]}
```

Preserve other matrix rows. notify supports message/route/reply and existing inputs, parameters, settings, detail, outputs, attempt references. A report's transition and queued notifications commit together; duplicate report_id does not enqueue again.

Users can change existing hooks through change_settings. notify hooks support before/after and phase=transition, with event/from/to filters and node/tasks targets. once applies once per Run; always applies to each distinct matching transition. Changing a Hook definition requires a new ID; enabled=false disables it.

## Input: stdin JSON

The platform sends one UTF-8 JSON object. Ignore unused fields and do not interpret notifications as new agent instructions.

| Field | Content |
| --- | --- |
| id | Notification ID, stable across retries |
| run_id, title | Run identity and title |
| message | Body |
| reason | Optional completion/failure reason |
| tasks | Related Task ID; null for Run-level notices |
| run_status | Run state observed for this delivery attempt |
| task_label, task_status | Related task label/state, or empty strings |
| route | Notification route; workspace never calls an external adapter |
| outlet | Named outlet's channel, identity, destination, interpreted by the adapter |
| reply | Optional question correlation/schema, not proof of channel callback support |
| attempt, at | Delivery-attempt count and creation time |

Input excludes internal operation tokens and send commands. Read business results from committed Timeline records; delivery receipts are not business outputs.

## Output: stdout JSON and exit status

Success requires exit 0, one JSON object on stdout, and delivered=true. Optional channel/reference identify the channel and receipt:

```json
{"delivered":true,"channel":"your-bridge","reference":"message-or-receipt-id"}
```

Failure exits nonzero, optionally returning `{"delivered":false,"error":"reason"}` or writing an explanation to stderr. Do not mix logs into successful stdout JSON. Exit 0 without delivered confirmation is not recorded as delivered. The default send timeout is 30 seconds; return promptly.

Return delivered=true only after the external interface confirms success, not after a local file write or enqueue into the adapter's own queue. Delivered does not mean read by the user.

## Triggers, failures, and retries

- Scripts/agents can notify proactively; authors configure transition notifications, users configure before/after/transition hooks.
- Normal Engine completion generates one completion notification. Without an outlet or legacy command, use the platform notification area. User terminate is not successful completion.
- Pause after three consecutive agent failures uses the same outlet, without waking a model to send it.
- New notifications pin the outlet/send configuration when queued. Later changes affect only new notifications; retries retain the destination. Missing configuration becomes waiting_configuration, requiring explicit retry after setup; it is not runtime unexpected and does not wake fallback. Historical notices pin configuration on first send.
- retry_notification takes run_id and notification_id, plus token if holding global scope. It can retry after Run completion without reopening the Run.
- Timeout may mean delivery occurred but the receipt was lost. Verify before retrying; adapters can use notification IDs as idempotency keys when supported. Cross-system exactly-once delivery is not promised.

Adapters need no chat history, duplicate Timeline, or separate agent scheduler. Actual failures preserve fault/receipts; all delivery records remain in the notification area for verification and explicit retry.

Use read_cc_connect/configure_cc_connect for bridge setup. Named agents bind Bots directly; create a cc_connect outlet only for fixed destinations. See [local setup and Bot discovery](cc-connect.md#local-setup-and-bot-discovery).
