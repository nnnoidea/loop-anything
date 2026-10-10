# 具名 Agent 与通信群组

本机具名外援和群组远端外援使用同一请求接口。通信不要求创建 Loop。先调用 `read_capabilities` 检查 `agent_communication`，再读取当前服务工具 schema；不要为业务 Loop 自建 NAS 队列、心跳、轮询或回报脚本。

## 首次组网：共享空间 → 群组 → 具名 Agent

安装后打开“Agent 通信”，按四步配置；工具操作需要平台所有者的编辑权限，普通任务令牌不能修改组网配置。

1. **配置共享空间**：先在每台机器挂载同一个 NAS 目录，再调用 `communication_config`，参数如 `{"operation":"space","path":"/本机挂载目录/协作空间","name":"研究协作"}`。目录必须已存在；平台保存空间 ID 和本机路径，做本机读写检查，不代替 NAS 挂载或真实双机验收。首台写入空间标识，其他机器读取同一 ID；本机路径不同也可加入。
2. **发现或创建群组**：`communication_workspace({"discover":true})` 返回 `shared_spaces`，每个空间包含群组名称、用途、`id`、`relative_path`、是否已加入和读取错误。发现仅扫描该空间的 `groups/` 直接子目录，不自动加入，不扫描整台机器。创建调用 `communication_config({"operation":"group","space_id":"返回的空间ID","create":true,"name":"论文协作","description":"用途说明"})`；创建者同时加入。其他机器加入时传 `operation: group`、`space_id`、发现结果中的 `relative_path` 和 `group_id`，不用复制另一台机器的绝对路径。
3. **选择开放的 Agent**：每个具名 Agent 映射执行机器本地的 `implementation.command`、`cwd`、`resume_command`；用 `operation: agent` 保存，再在 `agent.groups` 中明确选择群组。不选择即不对群组开放，加入群组本身不会公开任何 Agent。可以只调用别人而不提供服务；配置不会启动模型。
4. **查看与使用**：`communication_status` 查看已开放成员及状态，随后给 Loop / Run 绑定群组，或设置普通对话默认群组。目录通过平台心跳更新，名称可重复，调用使用 `instance_id` 与 `agent_id` 消歧。

“复制加入说明”或 `communication_workspace({"group_id":"群组ID"})` 返回可转交的纯文本，包含空间/群组 ID、相对目录和配置步骤，不含 CLI 命令、凭据或本机绝对路径。NAS 地址和访问权限需由空间提供者另行提供。群组 ID 用于核对身份，不是邀请凭据；当前没有管理员审批入群机制。

同一空间更换本机挂载路径时，再保存新目录即可按空间 ID 更新路径；由该空间发现并加入的群组会校验身份后更新本机路径，保留开放范围和历史。目录缺失、空间身份变化或某个群组损坏会显示错误，不自动在缺失挂载位置创建新空间。此前直接配置的独立群组目录继续使用“直接加入已有群组目录”，不自动迁移。

## 配置（平台所有者）

在“Agent 通信”页面配置本机具名 Agent 的名称、能力、CLI argv、cwd、接单上限及开放范围。`communication_config` 提供相同操作：

- `operation: agent`：`agent_id` 可省略生成；`agent` 包含 name、description、capabilities（字符串数组）、local、enabled、groups、capacity、implementation。implementation 使用现有 `kind: agent` 命令契约。
- `operation: space`：path 是已挂载的共享空间目录；首次可给 name。保存空间映射，不加入或公开 Agent。
- `operation: group`：可使用上面的 space_id 发现流程；兼容旧版直接 path。path 是本机挂载目录；已有目录群组直接加入，首次创建需 `create: true`。各机器路径可以不同，但必须指向同一共享群组。
- `operation: leave`：group_id。停止该组接新任务；已有执行、通信回执和历史仍保留。
- `operation: probe`：group_id。本机写入、读回并清理测试文件；不将此结果当作双机 NAS 验收。
- `operation: bind_loop`：loop_key 或 run_id，以及 group_id。Loop 默认在新 Run 创建时固定；Run 覆盖只影响新请求。
- `operation: context`：创建/更新 context_id 与默认 group_id，供无 Loop 的对话使用。
- `operation: group_notifications`：在实际发送机器上，为 group_id 选择本地 notification_route 和 notification_level；仅绑定当前机器的入口，不覆盖其他机器。替换/停用需传本机当前 binding_id，enabled=false 只停用本机入口。具体流程见下节。

普通节点 CLI 和正在运行的 session 不会自动注册。local 开关与 groups 开放范围分开；本机调用无需 NAS。命令由执行机器所有者配置，请求不能提供任意启动命令。组目录是可信内部传输，不是多租户认证系统。

## 调用外援

1. `communication_status` 查看显式开放的本机成员和群组目录。Loop 调用带 run_id；此时只显示其群组范围。
2. `request_assistance` 传 `location: local` 和 agent_id；或 `location: group`、明确 group_id 和 agent_id/capability。无默认群组时先选择，不跨组广播；同名目标以稳定 ID 消歧。
3. 提供 message、需要分享的 context，以及可选 result_schema（默认 object）。context 顶层须为 JSON 对象，内部业务字段可为文字、数组、null 等 JSON 值；例如 `{"task":"查找相关论文"}` 合法，不要求把 context.task 包装成平台 Task 对象。节点内调用还需 `source: {run_id, task_id}` 和当前操作 token。无 Loop 不传 source，调用方无需成为接单成员。
4. 返回精简 request 摘要、request.id 和私有 request_token。之后 `read_assistance(request_id, token)` 默认只取状态、结构化结果和最近通知状态，不附带日志、原始上下文及完整历史；读取不会启动 Agent。
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

## 控制通信上下文大小

先检查运行服务的 `communication_context` 能力或实际工具 schema。`read_assistance` 默认摘要适合查进度、取结果；历史记录仍在平台保存，不会为了压缩上下文删除。

排错时显式读取：

```json
{"request_id":"请求ID","token":"请求读取凭据","include_logs":true,"max_chars":4000}
```

每页日志默认最多 4000 字符，可设置 1–16000。返回 `logs`、`log_cursor`、`log_offset` 和 `log_more`。需要继续时用 `after=log_cursor`、`offset=log_offset`；单个日志块也可以跨页，不会因截断丢字。不要每次从零重读，定位问题后停止获取多余日志。浏览器日志区使用同一分页方式。

需要原始业务上下文、完整通知与历史时使用 `include_details:true`；它不自动打开日志，仍需 `include_logs:true`。详细诊断可能较大，仅在当前问题确实需要时读取。结构化业务结果保持完整，不做自动语义裁剪；大业务产物仍应通过文件或共享引用交付。

等待外援后的 `assistance_results` 只带请求摘要与结果；追问上下文只保留最近请求摘要和 `original_context`，不递归嵌入旧请求档案。原 session 恢复保持不变。普通 `read_context` 仍可按授权读取所需的业务上下文。

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

通知使用已有命名出口，独立请求默认 workspace，节点执行可沿用 Run 出口。通信消息统一显示请求 ID；首条实际生成的通知包含请求正文（即使请求很快进入执行或完成），后续通知引用同一 ID，保留状态、结果摘要或错误，不重复原请求。cc-connect 对通信消息不另附内部通知 ID，投递和重试回执仍按通知记录保存。飞书/微信只用于通知；未配置时不猜接收人，不承担请求和正式结果传输。

### 群组按机器绑定出口与通知优先级

先检查 `group_notification_priority` 能力。没有聊天来源的新群组请求省略 notification_route 时，按每条事件选择一个发送方：**动作发生方的群组入口 → 本次请求直接发起方的群组入口 → 不发外部通知，仅平台记录**。请求、超时和无人承接等由发起方负责；开始执行、进度、完成或执行失败优先执行方。A 请求 B、B 又请求 C 时，子请求按 C → B 回退，不回退根请求 A。

1. 在各台需要提供通知入口的机器上配置本地命名出口，例如 cc-connect 的 project 和聊天 session；各机器可以绑定自己的目标。聊天 session 与 Agent CLI session 是不同标识。
2. 在“Agent 通信 → 群组 → 通知绑定”保存**本机入口**，或调用：

```json
{"operation":"group_notifications","group_id":"group-实际ID","notification_route":"feishu-research","notification_level":"key"}
```

3. `communication_status.groups[].notification_bindings` 按 instance_id 列出各机器绑定。修改时传本机绑定的 id 作为 binding_id；enabled=false 仅停用本机入口。不同机器互不覆盖。目录公开发送机器、目的地和档位，命令与凭据留在各自本地。保存配置不会发送消息。
4. 来源平台继续统一生成和去重通知，经 NAS 交给选定机器调用本地适配器。`read_assistance.notifications[].routing` 给出 actor_instance、request_origin、sender_instance、binding_id 和 reason；action_machine 表示动作方，request_origin 表示回退发起方，no_bound_outlet 表示两者都没有入口。无入口状态为 skipped，不会影响任务执行。

缺少绑定或明确停用才回退。绑定存在但机器离线、发送失败或送达未知时，保留 awaiting_delivery/fault 等状态，不切换机器重发。已经生成的通知和显式重试固定当时的发送机器、目的地及命令；更改绑定只影响后续新生成的通知。通知档位默认取选中入口的 level，请求明确指定 notification_level 时优先使用请求值；过滤掉的事件不会改投另一个入口。

显式请求 notification_route 仍优先；无群组请求沿用 Run 默认或 workspace。业务 lifecycle/notify 的 Run 出口不变。嵌套外援仍由根来源平台保存通知回执以避免重复，路由回退对象使用子请求的直接发起方。

旧单一群组绑定读取为原发送机器自己的入口，不作为新请求的任意第三方兜底。升级前已创建的请求和通知保留原策略；新群组请求及沿用群组绑定的追问采用新优先级。所有参与平台应升级以使用新路由；不会自动迁移运行中的任务或重发历史通知。

通知档位支持 attention（仅需处理）、key（默认关键进展）、detailed（含进度摘要）。可选外援无人承接时 attention 不一律报警。失败回执通过 control_assistance(action: retry_notification, notification_id: ...) 显式重试；结果未知先核实。真实 NAS、多机、模型及渠道送达仍在安装时分别验收。

## 聊天入口通知（0.5.7）

飞书入口经 Skill 客户端自动保存原会话；私聊由入口 Bot 回复，群聊的执行确认和结果优先使用具名 Agent 的 `notification_route` 所映射 Bot，并保持原话题。发送前明确不可用才回退入口，发送结果未知不自动换 Bot。嵌套外援继承原来源；显式通知出口覆盖，无聊天来源保留按机器优先级。配置入口在具名 Agent 编辑界面。完整前提、只读权限及 API 用法见平台 Skill 的 `references/cc-connect.md`；话题需开启 cc-connect 话题隔离并保留 root session key。
