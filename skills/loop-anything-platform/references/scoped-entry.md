# 限定工具入口

仅在本次唤醒上下文提供 `tool_url` 时读取。本入口已绑定某个准备记录或 Run 及用户选择的操作范围；普通 CLI、聊天入口和后台节点继续使用各自的连接契约。

## 地址与身份

所有调用使用 `scripts/call.py TOOL --url "上下文中的 tool_url" --arguments JSON`。先调用 `list` 读取本次可用工具。接口自动提供 run_id/token，参数中不再传这两个字段；`acquire_run` 也不传 task_id，操作范围由本入口绑定。`read_task` 等工具仍需具体 task_id。

不要换回 connection.json 或其他平台地址扩大权限。普通运行示例中的 run_id/token 必须省略；工具目录没有的操作不能通过更换入口绕过。

## 准备、启动与继续运行

- 启动前：用 `read_loop` 读取作者说明，`read_preparation` 读取输入、候选选择和 revision；用 `change_preparation`（revision、change）保存已确认的安排。保存准备信息不会执行业务工作。
- 用户明确要求启动或上下文 `start_requested=true` 时：用 `start_prepared_run`（revision）创建并取得同一个 Run 的操作权。返回 run_id、entry_task_id 后再次 `list`，按入口契约 `read_task`、提交完整报告、安排后续工作并 `finish`。脚本入口交给 Engine 执行；普通讨论不启动，已经启动不重复创建 Run。
- 运行中：先只读最新 Timeline；需要写入时 `acquire_run`，取得后重新读取版本，按绑定范围修改并在完成后 `finish`。冲突时保留现场并告知用户，不抢占其他 Agent。

最终 stdout 是给用户的回复，业务结果仍须通过工具提交。影响后续工作的决定写入 preparation 或 Timeline。上下文可能提供 preparation、run_id、scope_task、start_requested、messages 和作者 handbook；这些字段不授予额外操作权。

具体任务、报告、等待及恢复规则按需查[运行工具](run.md)。本入口复用同一平台契约，Agent 无需操作用户界面。
