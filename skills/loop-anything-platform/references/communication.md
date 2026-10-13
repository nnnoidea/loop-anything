# 具名 Agent 与通信群组

本机具名外援和群组远端外援使用同一请求接口。独立协作由平台内置 Loop 承接，无需用户构建 Loop。先调用 `read_capabilities` 检查 `agent_communication`，再读取当前服务工具 schema；不要为业务 Loop 自建 NAS 队列、心跳、轮询或回报脚本。

## 当前连接的是谁

先确认服务支持 `machine_identity` 能力；旧服务只有 instance_id 时，它仍只是工作区寻址标识，需要升级才能提供独立机器身份，不要自行生成替代值。

直接调用 `communication_status`，读取返回的 `self`；平台唤醒节点、具名外援或限定入口 Agent 时，上下文也提供同样的字段：

```json
{"self":{"machine_id":"machine-完整UUID","machine_name":"训练服务器","workspace_id":"工作区ID"}}
```

`self` 指当前连接的平台所在机器及工作区。连接远端平台时，它不一定是发出工具调用的电脑；远端外援的唤醒上下文标识实际执行端，不是任务来源。无需自己找 MAC、读数据库或从聊天记忆猜 ID。

机器 UUID 缺失时按需生成并保存，复用同一平台用户环境的多个工作区共享 machine_id。每个工作区独立寻址；顶层 `instance_id` 是 `self.workspace_id` 的兼容别名，发请求继续使用成员返回的 instance_id 和 agent_id，不把 machine_id 填进 instance_id。旧工作区可能保留 machine- 前缀的历史 instance_id，前缀不改变它的工作区含义。

`communication_config(operation=identity, name=...)` 修改显示名称，不改变 ID。重启、升级及正常移动数据库保留身份。发现副本或机器归属不符时，`identity_conflict` / `identity_error` 给出原因；明确为副本配置 `regenerate=true` 才建立新工作区身份。复制过来的 Run 和请求保留为只读历史，新工作应创建新 Run，不接管原执行。无机器身份的旧库首次升级如果原主机不同，需明确处理归属，不能猜测为改名。

## 首次组网：共享空间 → 群组 → 具名 Agent

安装后通过平台工具配置；可信工作区可直接配置，无需Loop编辑口令；远端worker限定入口不能修改组网配置。

1. **配置共享空间**：先在每台机器挂载同一个 NAS 目录，再调用 `communication_config`，参数如 `{"operation":"space","path":"/本机挂载目录/协作空间","name":"研究协作"}`。目录必须已存在；平台保存空间 ID 和本机路径，做本机读写检查，不代替 NAS 挂载或真实双机验收。首台写入空间标识，其他机器读取同一 ID；本机路径不同也可加入。
2. **发现或创建群组**：`communication_workspace({"discover":true})` 返回 `shared_spaces`，每个空间包含群组名称、用途、`id`、`relative_path`、是否已加入和读取错误。发现仅扫描该空间的 `groups/` 直接子目录，不自动加入，不扫描整台机器。创建调用 `communication_config({"operation":"group","space_id":"返回的空间ID","create":true,"name":"论文协作","description":"用途说明"})`；创建者同时加入。其他机器加入时传 `operation: group`、`space_id`、发现结果中的 `relative_path` 和 `group_id`，不用复制另一台机器的绝对路径。
3. **选择开放的 Agent**：每个具名 Agent 映射执行机器本地的 `implementation.command`、`cwd`、`resume_command`；用 `operation: agent` 保存，再在 `agent.groups` 中明确选择群组。不选择即不对群组开放，加入群组本身不会公开任何 Agent。可以只调用别人而不提供服务；配置不会启动模型。
4. **查看与使用**：`communication_status` 查看已开放成员及状态，随后给 Loop / Run 绑定群组，或设置普通对话默认群组。目录通过平台心跳更新，名称可重复，调用使用 `instance_id` 与 `agent_id` 消歧。

`communication_workspace({"group_id":"群组ID"})` 返回可转交的纯文本，包含空间/群组 ID、相对目录和配置步骤，不含 CLI 命令、凭据或本机绝对路径。NAS 地址和访问权限需由空间提供者另行提供。群组 ID 用于核对身份，不是邀请凭据；当前没有管理员审批入群机制。

同一空间更换本机挂载路径时，再保存新目录即可按空间 ID 更新路径；由该空间发现并加入的群组会校验身份后更新本机路径，保留开放范围和历史。目录缺失、空间身份变化或某个群组损坏会显示错误，不自动在缺失挂载位置创建新空间。此前直接配置的独立群组目录仍可用 operation=group、path 加入，不自动迁移。

## 配置（平台所有者）

用 `communication_config` 配置本机具名 Agent 的名称、能力、CLI argv、cwd、接单上限及开放范围：

- **开放群组前先询问用户主要任务**，将用户回答整理成简短 description（适合什么任务、需要什么输入、返回什么结果），并确认开放群组。只有用户已明确确认该说明和开放范围，才能传顶层 `task_confirmed: true`；不要根据模型/CLI 或 Agent 自拟文字代替用户回答。说明修改或新增开放群组须重新确认。旧配置缺确认记录会显示待确认并停止接收新群组任务，已承接工作保留。
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

1. `communication_status` 查看显式开放的本机成员和群组目录，无需编辑口令或任务/请求 token。Loop 调用带 run_id；此时只显示其群组范围。查询不授权启动工作。
2. `request_assistance` 传 `location: local` 和 agent_id；或 `location: group`、明确 group_id 和 agent_id/capability。无默认群组时先选择，不跨组广播；同名目标以稳定 ID 消歧。
3. 提供 message、需要分享的 context，以及可选 result_schema（默认 object）。context 顶层须为 JSON 对象，内部业务字段可为文字、数组、null 等 JSON 值；例如 `{"task":"查找相关论文"}` 合法，不要求把 context.task 包装成平台 Task 对象。节点内调用带 `source: {run_id, task_id}`；托管节点使用当前操作 token，普通工作区操作可省略，由平台处理。独立请求可不传 source，平台创建内置协作 Run，调用方无需成为接单成员；已有协作继续传 collaboration_id。若已用 start_collaboration 承接当前 Agent，则沿用其 source 和 token。
4. 返回精简 request 摘要、request.collaboration（独立协作的 run_id/task_id）、request.id 和兼容旧客户端的 request_token。之后 `read_assistance(request_id)` 默认只取状态、结构化结果和最近通知状态，不附带日志、原始上下文及完整历史；读取不会启动 Agent。
5. **pending/offered 表示仍在等待接单，不能判断为无人接单。** 默认接单期限为 300 秒，以发起端记录的 deadline 为准；几秒钟无 grant、目录暂时无成员或几次查询仍 pending，都不能作为取消/重建请求的依据。可以继续其他工作，或用 wait_assistance 挂起；非托管外部会话可结束本轮对话并保留请求，等待通知。只有平台返回 unavailable 等终态才按该结果处理；用户撤回或任务已无需要时仍可显式取消，并可填写 reason。
6. `control_assistance` 可 cancel、input、followup。followup 默认要求继续准确记录的 session；明确 `resume: false` 才新建。取消已发出不等于远端已经停止。

接单拒绝会返回 selection_decision：包含 reason、发起端当时的 source_state、deadline 以及可用的取消原因或已分配执行者。not_selected 本身不等于“被取消”；旧版本空回执仍需查发起端详情。

对话默认群组通过 context_id 引用，单次 group_id 可覆盖，但不能绕过 Run 群组和执行范围。没有原生 session ID 也可以发送普通协助请求。可信工作区可按 request_id 读取或控制请求；worker 写回必须使用本次执行身份。

目录提供 instance_id 和 agent_id，跨机器同名或自定义 ID 重复时一并指定，不能猜测目标。外援执行端可通过限定入口的 `read_context` 按需读取关联 Loop 和 Task 上下文；这是只读授权，不授予原节点结果写入权。独立请求没有 Loop 时返回请求方提供的上下文。

## 正式远程节点

节点保持 `kind: agent`，配置 `dispatch: {location: group, agent_id: ...}` 或 capability。绑定实际 Run 群组；成员使用执行端已配置的 CLI。普通本地节点保持原有默认行为，远端只响应明确的执行请求，不调度来源 Run 的其他节点。

节点的正式 read_task/report_task/finish 通过执行端限定客户端转送来源平台，沿用任务修订、操作范围、输出契约和结果校验。不要用 CLI 最后一段文字代替结构化结果。原 Task 关联通信请求，远端不创建业务 Run。

Loop 包资源经受限 `read_asset` 调用取回到执行端请求资源目录；资源分块传递并核对包内校验值，沿用既有包大小上限；较大业务产物应使用可访问的共享引用。资源缺失明确失败；模型登录、依赖和工作目录由执行环境配置。消息发布不证明实际 NAS 环境可用。

## 独立协作：内置 Loop

### 入口 Agent 与 session 登记

“把这次工作交给平台管理等待和续跑”指关联一次具体执行与原生 CLI session，不是把飞书 Bot 或当前 Agent 注册为长期接单成员。按实际需求选择：

| 场景 | 使用方式 | 当前 Agent 需要什么 |
|---|---|---|
| 飞书/终端入口请求外援，结果通知回来或稍后读取 | `request_assistance` | 不需要自身 execution_id、原生 session 登记或具名成员注册；平台自动建立结果跟踪 Run |
| 当前入口 Agent 暂停，结果到达后自动恢复原会话继续 | `start_collaboration(caller=…)` | 提供真实 session、当前 Agent 进程 PID 和恢复配置；平台创建并返回 execution_id，随后沿用其 Run/Task/token |
| 已在平台节点中执行，需补充当前 CLI 的真实 session ID | `register_agent_session` | 使用当前唤醒上下文中的自身 execution_id 和操作身份 |
| 希望其他成员以后能向本机 Agent 发布任务 | `communication_config(operation=agent)` | 配置具名 Agent 及开放范围；向群组开放前由用户确认主要任务 |

没有 execution_id 的入口不可遍历其他 Run 选择无关执行挂接。cc-connect 不会自动调用 start_collaboration；由入口 Agent/集成按需提供真实运行信息，用户无需手工登记，无法交接进程时使用普通求援与通知。

Codex 的 `CODEX_THREAD_ID` 属于原生 Agent session，用于恢复上下文；飞书的 chat_id、thread_id、thread_root 用于通知定位。保存飞书通知来源不需要调用 register_agent_session，这两组标识不能互换。

读取 `read_capabilities({"capability":"standalone_collaboration"})` 和实时工具 schema。一次完整协作对应一个 Run；后续求援用返回的 `run_id`（或 `request.collaboration.run_id`）填写 `collaboration_id`，追问 `control_assistance(action: followup)` 自动延续原 Run。消息、日志和进度不会各建一个 Run。

普通求援的返回结果通过内置事件等待 Task 写入 Timeline。`request_assistance` 立即返回；`wait_seconds` 是承接期限，不是工具阻塞时间。以下仅用于需要协调 Agent 持续推进的场景：
- **让平台启动协调 Agent**：`start_collaboration({"message":"完整协作任务","agent_id":"本机已开放的具名 Agent ID","group_id":"已加入群组"})`。返回 Run/Task；平台启动协调 Agent，它用普通节点工具提交、等待和恢复。纯本机协作可省略 group_id。
- **承接当前正在对话的 Agent**：入口适配器或当前 Agent 在同一机器调用 `start_collaboration`，提供 `caller.implementation`（本机 CLI 启动/准确恢复配置）、`caller.native_session`（实际 provider/id，可带 cwd）和 `caller.process_id`（当前 Agent 进程 PID，不是执行工具的临时子进程）。不能从聊天 ID 猜 session，不能使用最近会话或另一台机器的 PID。平台登记现有执行并返回 run_id/task_id/execution_id/token，不重复启动 Agent。

承接当前会话后，外援请求使用 `source={run_id,task_id}` 与返回的 token。需等待时调用 `wait_assistance`，成功后调用 `finish`，然后结束当前 Agent 进程。平台在外援结束/等待到期且原进程退出后，以原 session 和新凭据继续；任意外部聊天窗口并不自动具备进程移交能力。长驻入口应由适配器完成这一移交；无法准确提供上述信息时使用结果跟踪模式。

恢复后的协调节点仍需 `report_task(event: completed)` 提交 `outputs.result`（对象）；首次完成入口同时提交 `settings.objective`，然后 `finish`。通过 `read_task` 获取实时 task_version。不要把外援返回当作协调任务已完成，不要自建轮询或另一个通信调度器。Run 的暂停/终止、事件去重和会话恢复均由原有 Engine 承担。

## 等待回复后继续

需要自动续跑时检查 `assistance_session_resume` 能力；依赖它的 Loop 应声明 `requires: ["assistance_session_resume"]`。

1. 已在平台执行的节点登记真实原生 session，并配置准确恢复命令，见[保存 ID 与恢复命令](terminal.md#保存真实原生-id)。已通过 start_collaboration 接入的 caller 沿用返回的执行身份。
2. 调用 `wait_assistance(run_id, token, task_id, request_ids, seconds)`。只有成功后才 `finish` 并退出；远端节点还需在来源 finish 被接受后 complete 执行请求。
3. 回复到达或等待到期后，平台在原进程退出、操作权释放后恢复**同一 CLI session、同一 Task**，提供 `assistance_results` 和新凭据。远端固定原机器、具名 Agent、工作目录及恢复配置；原 token 作废，不添加业务图节点，也不把等待当完成。

缺少 session/恢复配置时 wait_assistance 拒绝；旧等待任务缺此信息时也不能通过通用重试新开会话。进程状态未知、会话文件丢失或 CLI 恢复失败时明确阻塞/失败，不能改用新会话。CLI 存储须保留在原机器；目前自动恢复使用 macOS/Linux 交互终端后端。

Run 暂停或 Task 取消时不自动续跑，Run 终止后保留迟到结果但不推进。停用 Agent 或退出群组只影响新工作，已承接任务仍由原机器恢复。可选外援不可用由请求方判断如何继续；固定节点缺执行者不能伪造完成。

## 控制通信上下文大小

先检查运行服务的 `communication_context` 能力或实际工具 schema。`read_assistance` 默认摘要适合查进度、取结果；历史记录仍在平台保存，不会为了压缩上下文删除。

排错时显式读取：

```json
{"request_id":"请求ID","include_logs":true,"max_chars":4000}
```

每页日志默认最多 4000 字符，可设置 1–16000。返回 `logs`、`log_cursor`、`log_offset` 和 `log_more`。需要继续时用 `after=log_cursor`、`offset=log_offset`；单个日志块也可以跨页，不会因截断丢字。不要每次从零重读，定位问题后停止获取多余日志。

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

共享目录发布完整消息或分块消息，单个逻辑消息上限 32 MiB；大业务数据使用产物引用。未确认消息保留重发，日志按序号单独持久化。

平台自动分离待收消息与历史：`messages/<机器ID>/` 是待收区，`messages/broadcast/` 保留等待认领的公告，已确认消息进入 `archive/<日期>/<接收方>/`，普通轮询不扫描归档。接收确认只表示消息已持久化，不代表任务完成；公告由发起方在分配、取消或到期后归档。ACK 发布后停止定时重发，重复原消息可触发同一回执补发。归档失败保留待办和诊断，重启继续，不阻断其他消息；历史及去重记录继续保留，不自动按日期删除。Agent 使用已有通信工具，无需自己搬移文件或编写清理脚本。

为兼容在途消息，保留旧传输路径和消息格式；服务启动或切换挂载后会一次性检查待收目录中的旧记录，只归档本机有权处理且已确认的内容。各机器升级后才能完整停止旧版 ACK 的定时重发。本机数据库仍保留历史，真实多机 NAS 的性能与故障恢复需在安装环境验收。

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

## 聊天入口通知

有聊天来源时通知跟随原会话；显式出口覆盖，无来源时使用上面的群组/Run 路由。飞书入口采集、Bot 映射、根消息保存与回退细则集中在 [cc-connect](cc-connect.md#自动跟随原聊天)。

## 目录查询与操作凭据

`communication_status` 是公开的只读发现接口，独立会话无需先创建 Run、获取 token 或解锁编辑即可发现已开放成员。目录不包含 CLI 命令、本机挂载路径及操作凭据。

可信工作区的配置、请求、状态读取和取消/追问无需编辑口令或 request_token。读取结果默认只返回精简状态；日志和完整上下文按需读取。旧 request_token 参数保留兼容，不承担工作区登录作用。

- Loop 编辑口令：只保护对应 Loop 的定义、实现、手册和随包资源，不能用来选择任务执行者。
- Run/Task token：平台为实际执行 Agent 提供的操作范围标识，退出或恢复时沿用既有生命周期。普通用户操作可省略，平台自动处理临时范围；显式错误 token 仍拒绝。
- worker token：承接者写回本次外援的进度和结果，不能操作其他请求；限定 worker 入口只能查看其相关请求。

原生 CLI session ID 只用于恢复上下文。任务认领依赖具名 Agent、实例与群组匹配，session 不决定认领；过期执行写回仍校验。平台托管节点须沿用唤醒入口和身份，不能借公开工作区入口扩大范围。

cc-connect 接入用 `read_cc_connect` / `configure_cc_connect`；具名 Agent 直接绑定 Bot，固定接收位置才建立 `cc_connect={project,platform}` 通知出口。见[本机接入与 Bot 发现](cc-connect.md#本机接入与-bot-发现)。
