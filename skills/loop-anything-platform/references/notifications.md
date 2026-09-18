# 通知接口与可选桥接

平台工具与通知发送是两条独立接口。任何入口里的 Agent 都可用 `scripts/call.py` 查找、读取和编辑同一个 Run；写入按 [run.md](run.md) 取得操作权。聊天桥接负责收消息和 Agent 会话，不参与 Engine 的状态判断。

通知适配器只做三件事：接收通知 JSON，向明确目标发送消息，返回真实结果。它是一个普通命令，无需插件注册、SDK 或平台内部模块。用户可以自行选择桥接；平台附带的 [cc-connect 适配](cc-connect.md)是可选示例。

## 设置发送命令

`start_run.notification_command` 或 `change_settings.change.notification_command` 是非空字符串组成的 argv 数组，平台不经 shell 拼接执行。个人接收目标随该命令保存到 Run 中。省略或设为空数组时沿用 Loop 的 `$notifications` 默认发送命令。

适配器可以生成一份 JSON 数组文件，例如 notification-command.json。使用同一个通用客户端配置：

```sh
python3 scripts/call.py start_run --notification-command @notification-command.json --arguments @启动参数.json
```

已有 Run：取得全局操作权并读取最新 settings.revision，在修改参数 JSON 中提供 run_id、token、revision、change，再执行：

```sh
python3 scripts/call.py change_settings --notification-command @notification-command.json --arguments @修改参数.json
```

也可直接把 notification_command 放进工具的 JSON 参数，不需要命令行选项；不能两处重复提供。命令及适配器路径必须在平台执行环境可用。指定目标，不依赖后台进程的“当前聊天”或“最近联系人”。

读取、编辑 Run 不会自动更改通知接收位置。需要更换目标时，由用户明确要求再修改，并 finish 释放操作权。

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

- 节点进度用 notify Hooks 在执行前/后触发，只配置用户关心的节点。
- 已配置发送命令时，Engine 正常进入完成终态生成一次完成通知；用户主动 terminate 不冒充成功。
- Agent 连续失败三次的暂停通知使用同一出口，不额外唤醒模型来发送。
- 首次实际尝试发送时固定发送命令，重试保留原目的地。未配置过发送命令的失败，可补配后重试。
- `retry_notification` 带 run_id、notification_id；持有全局操作权时再带 token。Run 已结束也可单独重试通知，不重开 Run。
- 超时可能表示消息已发出但回执未收到。重试前先核实；桥接支持幂等键时可使用通知 ID 去重，平台不承诺跨系统恰好一次送达。

适配器只需要遵守上述契约，无需实现聊天历史、Timeline 副本或另一套 Agent 调度。
