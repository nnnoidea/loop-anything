# 具名 Agent 与通信群组

本机具名外援和群组远端外援使用同一请求接口。通信不要求创建 Loop。先调用 `read_capabilities` 检查 `agent_communication`，再读取当前服务工具 schema；不要为业务 Loop 自建 NAS 队列、心跳、轮询或回报脚本。

## 配置（平台所有者）

在“Agent 通信”页面配置本机具名 Agent 的名称、能力、CLI argv、cwd、接单上限及开放范围。`communication_config` 提供相同操作：

- `operation: agent`：`agent_id` 可省略生成；`agent` 包含 name、description、capabilities（字符串数组）、local、enabled、groups、capacity、implementation。implementation 使用现有 `kind: agent` 命令契约。
- `operation: group`：path 是本机挂载目录；已有目录群组直接加入，首次创建需 `create: true`。各机器路径可以不同，但必须指向同一共享群组。
- `operation: leave`：group_id。停止该组接新任务；已有执行、通信回执和历史仍保留。
- `operation: probe`：group_id。本机写入、读回并清理测试文件；不将此结果当作双机 NAS 验收。
- `operation: bind_loop`：loop_key 或 run_id，以及 group_id。Loop 默认在新 Run 创建时固定；Run 覆盖只影响新请求。
- `operation: context`：创建/更新 context_id 与默认 group_id，供无 Loop 的对话使用。
- `operation: group_notifications`：在实际发送机器上，为 group_id 选择本地 notification_route 和 notification_level；当前机器成为群组发送机器。替换/停用需传当前 binding_id，enabled=false 停用群组外部通知。具体流程见下节。

普通节点 CLI 和正在运行的 session 不会自动注册。local 开关与 groups 开放范围分开；本机调用无需 NAS。命令由执行机器所有者配置，请求不能提供任意启动命令。组目录是可信内部传输，不是多租户认证系统。

## 调用外援

1. `communication_status` 查看显式开放的本机成员和群组目录。Loop 调用带 run_id；此时只显示其群组范围。
2. `request_assistance` 传 `location: local` 和 agent_id；或 `location: group`、明确 group_id 和 agent_id/capability。无默认群组时先选择，不跨组广播；同名目标以稳定 ID 消歧。
3. 提供 message、需要分享的 context，以及可选 result_schema（默认 object）。节点内调用还需 `source: {run_id, task_id}` 和当前操作 token。无 Loop 不传 source，调用方无需成为接单成员。
4. 返回 request.id 和私有 request_token。之后 `read_assistance(request_id, token)` 查看进度、结果和日志；读取不会启动 Agent。
5. `control_assistance` 可 cancel、input、followup。followup 默认要求继续准确记录的 session；明确 `resume: false` 才新建。取消已发出不等于远端已经停止。

对话默认群组通过 context_id 引用，单次 group_id 可覆盖，但不能绕过 Run 范围或平台授权。没有原生 session ID 也可以发送普通协助请求。request_id 是标识，不是读取/控制凭据。

目录提供 instance_id 和 agent_id，跨机器同名或自定义 ID 重复时一并指定，不能猜测目标。外援执行端可通过限定入口的 `read_context` 按需读取关联 Loop 和 Task 上下文；这是只读授权，不授予原节点结果写入权。独立请求没有 Loop 时返回请求方提供的上下文。

## 正式远程节点

节点保持 `kind: agent`，配置 `dispatch: {location: group, agent_id: ...}` 或 capability。绑定实际 Run 群组；成员使用执行端已配置的 CLI。普通本地节点保持原有默认行为，远端只响应明确的执行请求，不调度来源 Run 的其他节点。

节点的正式 read_task/report_task/finish 通过执行端限定客户端转送来源平台，沿用任务修订、操作范围、输出契约和结果校验。不要用 CLI 最后一段文字代替结构化结果。原 Task 关联通信请求，远端不创建业务 Run。

Loop 包资源经受限 `read_asset` 调用取回到执行端请求资源目录；资源分块传递并核对包内校验值，沿用既有包大小上限；较大业务产物应使用可访问的共享引用。资源缺失明确失败；模型登录、依赖和工作目录由执行环境配置。消息发布不证明实际 NAS 环境可用。

## 等待回复后继续

先检查 `read_capabilities(capability: assistance_session_resume)`。依赖原会话续跑的 Loop 应声明 `requires: ["assistance_session_resume"]`，防止安装到仅支持重新唤醒 Task 的旧平台。

节点 Agent 可以继续其他工作并稍后查询；确实需要暂停时，先登记实际原生 session，再调用 `wait_assistance(run_id, token, task_id, request_ids, seconds)`。该操作会检查是否有准确的 session 和恢复命令；只有成功后才调用 finish。远端节点还需在来源 finish 已接受后 complete 执行请求。

回复到达或等待期限结束后，平台恢复等待前的**同一个 CLI session**，以最新任务状态、`assistance_results` 和新的操作凭据继续同一个 Task。CLI 会话保留原推理上下文，历史 token 全部过期。远端续跑固定原机器和具名 Agent，沿用原工作目录及恢复配置；不会由其他机器重建一个对话。不添加业务图节点，也不把等待当成完成。

旧版等待任务若缺少原 session 恢复信息，自动续跑和通用“重试”都会阻止；应先修复原会话关联，不能用重试隐式新开对话。

本机制适用于平台托管的 Agent CLI。通过 `register_agent_session`（普通节点）或 `native_session`（限定执行客户端）登记真实 ID；可识别的 CLI 输出也会自动记录。Codex/Claude 可使用平台已有的准确 ID 恢复命令；自定义 CLI 或需要额外模型/权限参数时须显式配置 `resume_command`，含 `{{session_id}}` 和 `{{prompt}}` / `{{prompt_file}}`。当前自动恢复使用已有 macOS/Linux 交互终端后端。

暂停接新任务或退出群组不会把这项已承接的工作转交他人；原机器仍可为同一 Task 恢复原会话。取消 Task、终止 Run 或暂停 Run 会阻止自动继续；未知的旧进程仍需先确认停止。

缺少 session 或恢复配置时，wait_assistance 明确拒绝，Agent 不应先退出。旧版本留下的等待若没有可恢复身份，会保留等待并显示原因。原进程停止状态未知时不继续；会话文件丢失或 CLI 恢复失败时明确失败，**不退回新会话**。CLI 自身的会话存储必须保留在原执行机器。

回复在 `assistance_results` 中提供。缺少可选外援时由请求方自行处理或继续；固定节点缺执行者不能伪造完成。Run 暂停时不唤醒，终止后保存迟到回复但不推进。

普通外部对话只保证结果持久保存、可查询及通知；不会无条件向任意聊天窗口注入回复。

## 远端执行客户端

平台提供 `scripts/communication.py`，唤醒上下文包含其本机绝对路径、platform_url、request_id、限定 token。

同时提供本机标准 platform_client 与限定 platform_url，原有 call.py 的 read_task/report_task/finish 操作可以通过该地址使用；平台负责跨 NAS 转送。communication.py 使用 execution_url 调用执行端工具，或在未提供时使用 platform_url。限定地址的工具目录说明当前允许的操作，不需要作者再写桥接客户端。

```sh
python3 /实际客户端路径/communication.py --context 请求上下文.json progress --arguments '{"message":"正在检索"}'
python3 /实际客户端路径/communication.py --context 请求上下文.json complete --arguments '{"result":{"papers":[]}}'
```

正式节点用 `source_call` 调用来源工具，返回持久 call.id。只有 call.state=completed 才表示来源已接受；pending/executing 时调用 `source_result` 查看，failed 时检查错误及可能已产生的副作用，不盲目重复。

远端节点需要本机外援时，直接通过该客户端调用 communication_status/request_assistance/read_assistance；本机指执行端平台，群组范围限于父请求群组。本机外援会保留父请求的群组调用范围，但本机请求本身不经 NAS。子请求结果也会回传到来源记录。

`read_context` 提供关联 Loop 与任务的只读上下文，必要时经父请求转送来源平台；关联上下文不代表有权完成原节点。无 Loop 时返回提供的上下文。

`native_session` 登记实际 provider/id。认领按 agent_id，session 只用于执行连续性。恢复需匹配原来源、具名 Agent 和父任务范围；session ID 不授予跨任务调用权。查看日志不唤醒，原会话不可访问时不猜测最近会话。

## 退出、断线与通知

平台维护心跳、接单状态和执行回报，不需要模型常驻。忙碌、停用、离线和退出不是同一状态。失联的在途工作标为未知，不能仅因超时重新执行；确认停止后再处理。来源恢复后按消息 ID 去重并接受结果，发送与被接受分别记录。

对未知执行发送取消只记录取消意图，不能证明旧进程已停。核实后使用 confirm_stopped；远端请求须等执行端确认，本机相关终端的占用记录也会同步释放。

共享目录发布完整消息或分块消息，单个逻辑消息上限 32 MiB；大业务数据使用产物引用。未确认消息保留重发，日志按序号单独持久化。当前保留历史记录，不自动删除仍可能被引用的内容。大规模归档时需关注目录与本地数据库占用。

通知使用已有命名出口，独立请求默认 workspace，节点执行可沿用 Run 出口。飞书/微信只用于通知；未配置时不猜接收人，不承担请求和正式结果传输。

### 群组绑定 cc-connect 与指定发送机器

先通过 `read_capabilities(capability: group_notifications)` 确认支持此能力。群组通信通知的默认路径是：通信群组 → 指定发送机器上的通知出口 → cc-connect project / 聊天 session → 飞书群。聊天 session 与 Agent CLI session 是两个标识。

1. 在准备负责发送的机器 C 上安装并配置 cc-connect，确保能访问指定聊天目标；C 加入同一个 NAS 群组。
2. 在 C 的“通知出口”选择 cc-connect，填写 project 和聊天 session；工具方式用 read_notification_channels 返回的 cc_connect_command，再用 set_notification_channels 保存命名出口。无需把发送命令复制到其他机器。
3. 在 C 的“Agent 通信 → 群组 → 通知绑定”选择该出口和通知档位。工具等价调用：

```json
{"operation":"group_notifications","group_id":"group-实际ID","notification_route":"feishu-research","notification_level":"key"}
```

4. A/B 的后台服务会从 NAS 读取公共绑定；`communication_status.groups[].notification_binding` 可查看发送机器、出口及目的地。确认目录显示绑定后，请求省略 notification_route 即继承群组设置。正式远端节点、本机外援和嵌套外援同样继承其所属调用范围的设置。
5. 只有 C 调用 cc-connect，实际发送命令及凭据保留在 C 的本地数据库；NAS 不保存命令。通知请求、接收去重和回执均持久化。`read_assistance` 的 notifications 显示 awaiting_delivery（等待指定机器回执）、delivered、fault 或 waiting_configuration；C 的通信页另有本机投递记录。

已有绑定变更时先读取 binding.id，并作为 binding_id 提交，避免覆盖未看过的设置。在新机器上保存绑定代表明确改由这台机器发送；不根据在线状态自动切换。停用外部通知后，新请求使用平台记录。保存绑定本身不发送消息。

新请求固定当时的绑定、通知档位和发送配置；原请求、嵌套外援、追问及重试继续使用原绑定。修改 cc-connect 出口后需要重新绑定，才应用于新请求。发送机器离线时持续保留 awaiting_delivery；重连后继续。发送过程中重启会标为结果未知，核实实际送达后由来源机器显式重试，不自动重发。

路由选择：显式请求 notification_route 优先；未指定时使用已发现的群组绑定；没有群组绑定时沿用 Run 默认出口或独立请求的 workspace。嵌套外援统一继承父请求。此绑定管理协作通知，业务 lifecycle/notify 的既有出口设置仍由 Run 控制。

`notification_level` 可选 attention（仅需处理）、key（默认关键进展）、detailed（含进度摘要）。仅需处理档位不为无人承接的可选外援报警。通知显示关联 Loop/Run/节点、执行 Agent 和机器、结果摘要；嵌套外援由最初来源平台统一通知，避免两端重复发送。失败回执可用 `control_assistance(action: retry_notification, notification_id: ...)` 显式重试；结果未知时先核实送达情况。群组目录只公开明确绑定的 Loop/Run 摘要。

安装时提供真实 NAS 和机器信息；连接检查、本机双实例、真实 NAS 多机、真实 CLI/模型与实际渠道送达分别验收，不相互替代。
