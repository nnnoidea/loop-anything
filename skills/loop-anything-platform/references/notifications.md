# 通知接口与可选桥接

平台工具与通知发送是两条独立接口。任何入口里的 Agent 都可用 `scripts/call.py` 查找、读取和编辑同一个 Run；写入按 [run.md](run.md) 取得操作权。聊天桥接负责收消息和 Agent 会话，不参与 Engine 的状态判断。

通知适配器只做三件事：接收通知 JSON，向明确目标发送消息，返回真实结果。它是一个普通命令，无需插件注册、SDK 或平台内部模块。用户可以自行选择桥接；平台附带的 [cc-connect 适配](cc-connect.md)是可选示例。

## 配置平台出口

用 `read_notification_channels` 获取 `revision`、已有 `channels` 和本机 `cc_connect_command`。然后用 `set_notification_channels` 传入最新 revision 和修改后的完整 channels；保留不需要修改的出口。配置只保存在当前平台，不进入 Loop 包，也不会立即发送。

每个出口有独立 ID，以及 label、channel、identity、destination、command（argv）、可选 cwd 和 timeout。command 使用下文的通用发送契约；平台内置的 workspace 出口无需配置。身份和目的地由适配器解释，不能只给任意脚本填写这些字段就假定它会采用。

使用 cc-connect 时，command 可采用工具返回的 cc_connect_command；identity 填已配置的 project，destination 填明确的 session。适配器用这两个字段选择实际目标。非默认安装可在 argv 追加 `--executable` 和 `--data-dir`，不需要更改 Engine。已有连接方式见 [cc-connect.md](cc-connect.md)。

`start_run.notification_route` 或 `change_settings.change.notification_route` 选择本次运行的默认出口 ID，也可选 workspace。切换聊天入口不改变出口。网页侧栏「通知出口」配置平台出口；启动准备和运行设置选择本次使用哪个。

Loop 中的通知只能选择 default（本次 Run 出口）或 workspace（平台通知区），不得写入个人出口。旧 implementations.$notifications 已停用；导入或分享旧 Loop 前先将发送配置移到本地通知出口，再从草稿移除该字段。Run 的 notification_command 仍是本地调用配置，不随 Loop 分享。

## 网页中的选择与查看

启动准备页顶部显示本次出口，「选择出口」定位到本次运行设置；选择保存在该准备页，其他人的 Run 不受影响。运行页标题下显示实际出口，并提供「修改出口」和「通知安排与记录」。侧栏「通知出口」管理当前平台的命名出口。

Loop 的「任务关系」图显示等待条件与通知标记，「执行状态机」直接按所选实现展示实际矩阵；「通知发生在什么时候」列出节点、状态/事件、条件、消息及通用出口。运行页还会列出本 Run 的通知 Hooks；脚本/Agent 临时发送的消息以实际运行通知记录为准。

## 主动通知与询问

`notify` 参数：run_id、稳定 key、message；可选 task_id、route、reply。Agent 提供持有的 token；支线 Agent 必须指定自己范围内的 task_id。脚本提供上下文里的 token、task_id 和 execution_id。网页和用户 CLI 使用平台编辑授权；未解锁时不能发送。

```json
{"run_id":"RUN_ID","token":"TOKEN","task_id":"TASK_ID","key":"TASK_ID:progress-1","message":"阶段结果已记录","route":"default"}
```

相同 key 和内容返回原通知，不重复发送；同 key 不同内容会冲突。无需为通知新建 Task。脚本可按 context.report_client 导入 `notify(context, key, message, **fields)`，在本次执行结束前调用；完成后的通知可以挂到 completed 转移。

询问增加 reply，包含 event、key 和 schema：

```json
{"event":"reply","key":"question-1","schema":{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}}
```

询问本身不暂停运行；需要答案时安排同 event/key 的等待节点，其输出契约应与回复 schema 一致。网页可直接回复；聊天中的 Agent 通过 read_run 查看通知、read_task 查看等待节点，再调用 `send_event`，提供稳定 event_id、name、key、payload，可带 notification_id 检查回复 schema。支线 Agent 还需指定自己范围内的等待 task_id；用户授权的外部入口可直接提交事实，不需要占用 Agent 会话。发送通知的渠道和提交回复的入口可以不同。

## 作者和用户选择时机

作者在已有 lifecycle 转移行中增加 notify 数组：

```json
{"from":"executing","event":"completed","to":"completed","notify":[{"message":"结果：{outputs.result}","route":"default"}]}
```

保留矩阵其他行；notify 支持上述 message/route/reply，引用使用已有的 inputs、parameters、settings、detail、outputs、attempt 上下文。一次报告的转移与通知入队共同保存，重报相同 report_id 不再产生通知。

用户可以通过 change_settings 调整原 hooks：notify 除 before/after 外支持 phase=transition，可按 event、from、to 筛选，target 仍选择 node 或 tasks。once 表示本 Hook 在 Run 中仅一次；always 对每次不同的匹配转移生效。修改现有 Hook 的定义需换新 ID，停用可改 enabled=false。网页「通知与控制」提供这些表单。

## 输入：stdin JSON

平台传入一条 UTF-8 JSON 对象，适配器应忽略不使用的字段，不把运行通知解释成新的 Agent 指令。

| 字段 | 内容 |
| --- | --- |
| id | 通知 ID，重试时保持不变 |
| run_id、title | Run ID 和运行名称 |
| message | 通知正文 |
| reason | 可选的完成原因或错误原因 |
| tasks | 关联 Task ID；运行级通知可为 null |
| run_status | 发送尝试所读取的 Run 状态 |
| task_label、task_status | 关联任务名称、状态；无关联任务时为空字符串 |
| route | 通知路由；workspace 路由不调用外部适配器 |
| outlet | 命名出口的 channel、identity、destination；由适配器解释 |
| reply | 可选询问关联及回复 schema；不代表发送渠道自动支持回调 |
| attempt、at | 发送尝试次数、通知创建时间 |

输入不包含内部操作令牌或发送命令。业务结果仍从 Timeline 的正式记录读取，不把发送回执当成业务结果。

## 输出：stdout JSON 与退出码

成功：进程退出码为 0，stdout 是一个 JSON 对象，`delivered` 必须为 true。可附带 channel 和 reference，说明渠道及回执标识：

```json
{"delivered":true,"channel":"your-bridge","reference":"message-or-receipt-id"}
```

失败：退出码非 0；stdout 可返回 `{"delivered":false,"error":"原因"}`，或把错误说明写到 stderr。日志不要混入 stdout 的成功 JSON。退出码为 0 但未确认 delivered，也不会记为送达。平台默认发送超时为 30 秒，适配器应及时返回。

只有外部发送接口确认成功后才返回 delivered=true；不因为请求已写入本地文件或加入适配器自己的待发队列就声称已送达。送达不等于用户已读。

## 触发、失败与重试

- 脚本和 Agent 可以主动 notify；作者可配置转移通知，用户可配置前后或转移 Hooks。
- Engine 正常进入完成终态生成一次完成通知；未选出口且没有旧发送命令时，使用平台通知区；用户主动 terminate 不冒充成功。
- Agent 连续失败三次的暂停通知使用同一出口，不额外唤醒模型来发送。
- 新通知入队时固定出口与发送配置，重试保留原目的地。尚未配置的出口可补配后重试；历史通知在首次发送时固定配置。
- `retry_notification` 带 run_id、notification_id；持有全局操作权时再带 token。Run 已结束也可单独重试通知，不重开 Run。
- 超时可能表示消息已发出但回执未收到。重试前先核实；桥接支持幂等键时可使用通知 ID 去重，平台不承诺跨系统恰好一次送达。

适配器只需要遵守上述契约，无需实现聊天历史、Timeline 副本或另一套 Agent 调度。

命名出口在通知入队时固定实际发送配置；之后修改出口只影响新通知，重试仍使用原目的地。未配置的出口明确报错，不随意换其他渠道。平台通知区保留所有发送记录；外部渠道的网络不确定性仍须检查回执，不承诺跨渠道严格恰好送达一次。
