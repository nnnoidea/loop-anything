# 平台已承担的能力与作者分工

由平台能力定义生成；运行服务的 read_capabilities 为实际可用能力依据。可传 capability 按需读取详细机制与组合示例。

## 特性如何改变 Loop 的组织方式

讨论构建方案时，主动选择与用户目标相关、会影响工作组织的特性，说明可以怎样组织及其帮助。用户无需先知道这些能力。下表提供构建思路，按需使用；已有方案合适时直接继续，不逐项宣读、不强制覆盖所有特性，不增加检查或确认步骤。

| 用户目标中的线索 | 可利用的特性 | 可以提出的构建建议 | 按需深入 |
| --- | --- | --- | --- |
| 已有 Skill，后续动作需要临场判断 | 自然语言流程 Agent 与确定规则混合推进 | 先把 Skill 中的长任务和等待拆出，已确定转移用规则，其余让流程 Agent 决定；多次运行后依据记录逐步固化。 | [流程 Agent](flow-agent.md) |
| 耗时训练、排队、等待外部结果 | Agent 只在需要判断时出现 | 拆开方案制定、自动执行与等待、结果分析。平台按时调用短查询脚本，或接收完成事件，随后推进到下一个决策点。 | [生命周期与监控](#lifecycle)、[持久等待](#waits) |
| 实验数量、分支或下一轮方案依赖结果 | 后续任务可以根据结果生成 | 先定义可复用的工作模板，让 Agent 提交本轮参数，平台展开任务并汇总结果；按明确条件决定下一轮或结束。 | [结果触发](#event_routes)、[批量任务](#plans)、[结束条件](#termination) |
| 工作持续多天、需要换会话或换入口继续 | 工作状态独立于聊天会话保存 | 把长期工作划成阶段，目标、进度和结果存入 Timeline；后续 Agent 读取当前状态继续处理。 | [持久状态](#timeline_storage)、[执行恢复](#execution_recovery) |
| 工作需要不同的工具、算力或机器环境 | 一个 Loop 可组合多种执行方式 | 按职责与资源拆分：本机脚本准备数据，外部平台训练，显式指定的远端 Agent 分析。 | [候选实现](#implementation_selection)、[远端协作](#agent_communication) |
| 多种专业职责、阶段说明不同或手册过长 | Loop 与节点可分别绑定 Skill／说明 | 结合目标建议知识分工：Loop 层保存整体目标和共享规则，节点说明各自的方法、工具与输入输出，执行时按需读取。例如共享实验目标，把训练操作与结果评价分别放到对应节点。 | [作者与节点 Skill](#author_skills) |
| 分析中偶尔需要查论文或咨询其他专长 | 专业 Agent 可以作为临时外援 | 必需步骤留在主流程；偶发协助由执行中的 Agent 按需请求，必要时挂起，结果回来后恢复原会话继续。 | [具名外援](#agent_communication)、[原会话续跑](#assistance_session_resume) |
| 研究、排障过程中会产生新信息或改变方向 | 运行中可以调整后续安排 | 保存已发生的事实与结果，按新目标修改后续任务、参数或依赖；不要求第一次规划就确定全部路径。 | [任务编辑](#task_edits)、[运行控制](#run_control) |

这些建议要结合实际接入条件：外部系统需要提交/查询脚本或事件回传；动态任务需要模板、触发规则和结束条件；远端执行需要已配置的群组与成员；恢复原会话需要真实 session 和恢复命令。Timeline 保存业务状态，不等于自动恢复任意聊天上下文。每次查询结束后由平台等待，不需要 Agent 或脚本常驻循环；事件与轮询双通道兜底需另行明确设计，并非默认组合。

例如用户说“持续跑实验”：可建议“提出参数 → 展开实验 → 平台等待训练 → Agent 分析 → 按结果决定下一轮”。若用户只要求汇总一份现成结果，则直接处理相应任务，不凭空增加循环、外援或等待节点。

说明按职责组织并按需读取，才能减少无关上下文和指令干扰；把全部节点说明一次性塞给 Agent 不会得到这一收益。共享规则保留在 Loop 层，节点引用，避免重复和矛盾。已有说明简短清楚时无需拆分，不强制每个节点新建 Skill，不仅为缩短文件而增加节点，不承诺完全消除上下文漂移。

## 机制详情

需要落实方案时再读取对应机制。activation=automatic 表示平台自动执行；declared/configured 需要作者声明或使用者配置；operator 需要显式操作。

## flow_agent

- 生效方式：declared
- 平台承担：复用普通 Agent 节点、事件 routes、依赖调度和任务工具；在声明的决策点唤醒，记录实际安排和结果。
- 作者提供：从已有 Skill 提炼阶段，将目标、约束、推进规则和结束条件写入 Loop 说明，流程 Agent 完整读取；声明唤醒事件与可安排工作。
- 配置入口：`Loop.handbook`、`nodes.*.routes`、`plans`、`Loop.global_agent_node`、`build_plan/edit_tasks/report_task/finish`
- 边界：完全确定性流程无需调用流程 Agent。普通节点只操作自身分支；需修改全局设置或其他支线时显式选择 global_agent_node。长期等待交给平台，规则文本自身不会触发唤醒。
- 工具入口：put_node、put_step、set_implementation、set_loop、read_timeline、read_task、build_plan、edit_tasks、report_task、finish、test_loop
- 详细说明：[references/flow-agent.md](flow-agent.md)

## flow_diagram

- 生效方式：author-maintained
- 平台承担：随 Skill 提供现成绘图组件和模板，复用包资产保存，整体流程视图展示已保存页面。
- 作者提供：首次完成流程及修改节点、分支、循环或任务生成逻辑后，逐一画出定义中的全部节点，包括按需分支与异常兜底；不以汇总框替代真实节点，保存前对照节点清单并预览。
- 配置入口：`scripts/render_flow.py`、`assets/flow.md`、`docs/flow.md`、`docs/flow.html`、`put_asset`
- 边界：绘图需要 Node.js 20+，查看不需要；不改执行规则，不在打开网页或每轮运行时调用 Agent，不作为保存或运行的前置检查。
- 工具入口：read_loop、put_asset
- 详细说明：[references/flow-diagram.md](flow-diagram.md)

## machine_identity

- 生效方式：automatic
- 平台承担：按需生成并持久保存完整机器 UUID，独立于工作区；communication_status.self 与唤醒上下文直接提供当前机器和工作区身份。
- 作者提供：读取 self；按成员返回的 instance_id 与 agent_id 寻址，不从 MAC、主机名或会话推断身份。
- 配置入口：`communication_status.self`、`context.self`、`communication_config(operation=identity)`
- 边界：身份属于连接的平台用户环境。instance_id 是 workspace_id 的兼容别名。移动/改名不改身份；副本显式建立新工作区身份，历史不接管。身份存储不要随业务数据库复制到另一机器。
- 工具入口：communication_status、communication_workspace、communication_config
- 详细说明：[references/communication.md](communication.md)

## loop_edit_protection

- 生效方式：configured
- 平台承担：可选编辑口令按Loop身份保护定义、节点实现、手册及随包资源；草稿和版本共用，导出导入携带校验信息。
- 作者提供：按需set_loop_password，受保护编辑提供对应Loop的loop_password。
- 配置入口：`set_loop_password`、`copy_loop`、`publish_loop`、`export_loop`
- 边界：日常Run、通信和终端不需要全局解锁；平台自动处理普通操作执行标识，实际worker仍受执行范围、版本和过期结果校验。
- 工具入口：set_loop_password、read_loop、copy_loop、publish_loop、export_loop
- 详细说明：[references/connection.md](connection.md)

## cc_connect

- 生效方式：configured/operator
- 平台承担：本机共用 cc-connect 接入配置，读取已有 Bot 列表，不返回凭据；具名 Agent 直接选择 Bot。
- 作者提供：read_cc_connect 发现；缺接入时 configure_cc_connect 指定实际配置文件和可执行文件，按返回 project/platform 建立 notification_bot 映射。固定目的地才建 cc_connect 引用出口。
- 配置入口：`read_cc_connect`、`configure_cc_connect`、`agent.notification_bot`、`channels.*.cc_connect`
- 边界：不猜配置文件目录、不为每个 Bot 写命令、不安装/启动 Bot。列表不证明在线或在群；目录歧义不自动选择；明确填写引用可保存，不作可用性预检。路径和密钥留本机。
- 工具入口：read_cc_connect、configure_cc_connect、communication_config、read_notification_channels、set_notification_channels
- 详细说明：[references/cc-connect.md](cc-connect.md)

## conversation_notifications

- 生效方式：automatic/configured
- 平台承担：飞书入口调用默认回复原会话；私聊由入口Bot回复，群聊优先具名Agent对应Bot并保持原话题。
- 作者提供：Skill call.py 只携带 chat_context；平台持久保存并复用来源，发送适配器保存原入口，话题用根消息调用cc-connect，缺根消息原样交给cc-connect；不查飞书权限或凭据；agent.notification_bot 直接映射本机已发现Bot，旧notification_route兼容。嵌套外援继承来源，不需要Agent重新拼接通知命令。
- 配置入口：`request_assistance.chat_context`、`start_run.chat_context`、`communication_config(operation=agent)`、`兼容已有conversation_id`
- 边界：通知接入失败不阻断业务任务；适配器明确确认未投递（未启动、未连接或明确拒绝）时才回退入口Bot；其他失败或结果未知不改投。原始session_key保留；适配器将明确话题目标转换为同群同话题的root发送目标，不自行改投群时间线；实际投递由cc-connect负责。显式出口优先；无聊天来源沿用群组按机器出口。
- 工具入口：communication_config、request_assistance、start_run、read_assistance
- 详细说明：[references/cc-connect.md](cc-connect.md)

## group_notification_priority

- 生效方式：automatic/configured
- 平台承担：无聊天来源时，群组通知逐条优先动作发生方，再回退本次请求的直接发起方；均无入口则仅平台记录。
- 作者提供：按机器绑定入口；省略请求 notification_route 使用优先级。嵌套外援按子请求直接发起方回退。
- 配置入口：`communication_config(operation=group_notifications)`、`communication_status.groups[].notification_bindings`、`read_assistance.notifications[].routing`
- 边界：缺入口或明确停用才回退；离线、失败及送达未知不自动改投。显式出口优先，通知重试固定原绑定。
- 工具入口：communication_config、communication_status、read_assistance
- 详细说明：[references/communication.md](communication.md)

## communication_context

- 生效方式：automatic/operator
- 平台承担：通信查询默认摘要，日志按需分段读取；外援续跑及追问不嵌入完整通信历史，保留业务上下文、结果及原 session。
- 作者提供：优先读状态和结构化结果；排错时请求 include_logs 或 include_details，用返回的 log_cursor/log_offset 继续读取。
- 配置入口：`read_assistance.include_logs`、`read_assistance.include_details`、`read_assistance.max_chars`、`read_assistance.after/offset`
- 边界：单页日志默认 4000、最多 16000 字符；完整诊断按需返回，原始日志保留；结构化业务结果不自动删减。
- 工具入口：read_assistance、request_assistance、control_assistance
- 详细说明：[references/communication.md](communication.md)

## standalone_collaboration

- 生效方式：configured/operator
- 平台承担：独立协作由内置 Loop 承接；事件等待记录结果，当前会话或具名协调 Agent 复用原 Task/session 挂起续跑。
- 作者提供：request_assistance 返回协作 Run；追问延续原 Run。自动续跑使用 start_collaboration，提供真实本机会话、Agent PID 和恢复配置，wait_assistance 后 finish 并退出原进程。
- 配置入口：`start_collaboration`、`request_assistance`、`wait_assistance`
- 边界：未知外部会话仅保存结果并通知；不猜 session，不并行恢复尚存活的原进程。
- 工具入口：start_collaboration、request_assistance、read_assistance、wait_assistance、communication_status
- 详细说明：[references/communication.md](communication.md)

## confirmed_agent_directory

- 生效方式：configured
- 平台承担：群组目录共享用户确认的主要任务、能力与可用状态；旧的未确认说明不接收新群组工作。
- 作者提供：先询问用户主要任务并确认说明及开放群组，再 communication_config(task_confirmed=true)。修改说明或新增群组重新确认。
- 配置入口：`communication_config`、`communication_status`
- 边界：Agent 自拟描述不等于用户确认。
- 工具入口：communication_config、communication_status
- 详细说明：[references/communication.md](communication.md)

## assistance_session_resume

- 生效方式：configured/operator
- 平台承担：等待外援前检查原生 session 和准确恢复命令；回复或期限到达后恢复同一会话与 Task，携带结果和新操作凭据。
- 作者提供：配置托管 CLI 与 resume_command，登记真实 session；wait_assistance 成功后再 finish，远端还需完成执行请求。
- 配置入口：`wait_assistance`、`register_agent_session`、`implementations.*.resume_command`
- 边界：原机器/Agent/session 固定；缺失或恢复失败时明确阻塞，不新建对话。当前恢复使用 macOS/Linux 终端，CLI 自身的会话文件须保留。
- 工具入口：wait_assistance、register_agent_session、communication_execute、read_assistance
- 详细说明：[references/communication.md](communication.md)

## group_notifications

- 生效方式：configured/operator
- 平台承担：各机器独立绑定群组通知入口；来源持久生成通知，选定机器复用 cc-connect 等适配器并写回回执。
- 作者提供：在各机器配置本地命名出口，再用 group_notifications 绑定该机器的群组入口。
- 配置入口：`communication_config(operation=group_notifications)`、`platform notification channels`
- 边界：命令和凭据不写入 NAS；已生成通知固定出口。旧策略请求按原策略完成；未知送达须核实后显式重试。
- 工具入口：communication_status、communication_config、read_notification_channels、set_notification_channels、read_assistance、control_assistance
- 详细说明：[references/communication.md](communication.md)

## agent_communication

- 生效方式：configured/operator
- 平台承担：平台提供本机具名Agent目录、NAS群组收发、明确认领、进度结果、会话和等待恢复；独立协作自动使用平台内置 Loop。待收消息与历史自动分离，确认后归档，回执按需补发；作者无需自建归档或清理脚本。
- 作者提供：先配置已挂载的共享空间，用 communication_workspace(discover=true) 发现群组并显式加入；再配置具名 Agent 对应的本机 CLI/工作目录/恢复命令及开放群组，支持转交加入说明；Loop绑定群组，节点显式声明群组执行；外援由Agent按需请求；pending/offered表示等待，默认接单期限300秒，不得因几秒无回应而取消或重建，按需挂起等待。
- 配置入口：`communication_config`、`implementations.*.dispatch`、`request_assistance`、`wait_assistance`
- 边界：可信工作区配置、请求、查询无需全局编辑解锁；普通操作由平台处理内部标识，worker写回仍校验本次执行范围。原生 session ID 只用于恢复；本地节点只由来源平台执行，群组不是业务Run副本，session不决定认领。失联不自动重跑。NAS实际环境需安装时检查，逐键远程PTY尚不承诺。
- 工具入口：communication_workspace、communication_status、communication_config、request_assistance、read_assistance、control_assistance、wait_assistance、communication_execute
- 详细说明：[references/communication.md](communication.md)

## timeline_storage

- 生效方式：automatic
- 平台承担：持久化 Run、Task、执行尝试、版本化结果、事件和历史；正式写入使用同一数据库事务。
- 作者提供：定义业务结果 schema，并通过正式报告提交事实。
- 配置入口：`nodes.*.outputs`、`records`、`report_task.envelope`
- 边界：外部系统的副作用不属于本地事务；平台不会代替外部服务提供 exactly-once 提交。
- 工具入口：read_timeline、read_record、read_run
- 详细说明：[references/run.md](run.md)

## task_scheduler

- 生效方式：automatic
- 平台承担：检查输入与 after 依赖、暂停点、实现选择、并发额度和操作范围，派发就绪任务。
- 作者提供：声明任务、数据来源和依赖；需要后继自动生成时配置 routes。
- 配置入口：`plans.*.steps.*.inputs`、`plans.*.steps.*.after`、`settings.max_parallel`、`nodes.*.routes`
- 边界：依赖连线仅推进已有任务；默认不会推断缺失业务任务。
- 工具入口：next_tasks、change_settings
- 详细说明：[references/run.md](run.md)

## execution_recovery

- 生效方式：automatic
- 平台承担：重启后恢复已持久化执行状态，保留重试和监控身份，暴露无法确认停止的进程与操作权。
- 作者提供：让外部提交和观察可恢复，核对未知外部副作用，必要时确认旧进程已停止。
- 配置入口：`implementations.*.observe`、`implementations.*.lifecycle`、`command`
- 边界：未知进程状态不会被当作安全完成；外部幂等和身份解析由适配器负责。
- 工具入口：read_task、command、change_task
- 详细说明：[references/build-reference.md](build-reference.md)

## implementation_selection

- 生效方式：declared
- 平台承担：按 Task 指定、Run binding、Loop 默认的顺序选择候选；校验节点和候选参数，保留执行快照。
- 作者提供：提供真实候选、参数契约与入口；在安排任务时确定自动阶段所需参数。
- 配置入口：`implementations`、`settings.bindings`、`Task.implementation`、`Task.parameters`
- 边界：平台不自动补默认参数、不生成业务命令、不修复执行环境。
- 工具入口：read_loop、read_task、set_implementation
- 详细说明：[references/contracts.md](contracts.md)

## workspace_inspection

- 生效方式：automatic
- 平台承担：提供 Loop 结构、任务依赖、执行状态、结果、输入来源、历史、参数编辑、预览及文件结果展示。
- 作者提供：提供有意义的节点名称、schema title/description、明确的文件输出和业务结果。
- 配置入口：`nodes.*.label`、`records.*.title`、`records.*.description`、`records.*.format`
- 边界：现有工作台是操作界面；没有独立的脱敏团队只读看板。文件展示不证明产物有效。
- 工具入口：read_run、read_loop
- 详细说明：[references/build-reference.md](build-reference.md)

## agent_resume

- 生效方式：configured/operator
- 平台承担：每个任务直接查看对应尝试的结果；记录CLI原生ID，按用户请求恢复同一会话，签发新操作权并保持历史结果。
- 作者提供：提供CLI及恢复命令；让CLI输出或Agent报告真实ID。用户选择恢复目标和本次要求。
- 配置入口：`implementations.*.agent_cli`、`implementations.*.resume_command`、`register_agent_session`、`command argv {{session_id}}`
- 边界：不使用--last猜测，不扫描无关CLI历史。进程退出前同原生ID跨Run互斥；外部手动CLI进程由用户管理。旧任务没有原生ID时需明确补充；CLI本机记录丢失会恢复失败。恢复只适用于仍在运行或暂停的Run；原生CLI会话存储与模型访问由CLI负责。
- 工具入口：register_agent_session、read_task、set_implementation
- 详细说明：[references/terminal.md](terminal.md)

## agent_terminal

- 生效方式：automatic/configured
- 平台承担：为后台 Agent 每次执行持久化实时输出；可选交互终端连接同一 CLI 进程，转发键盘和窗口尺寸，finish 后关闭会话。
- 作者提供：提供 CLI 命令、工作目录、登录与权限配置；交互命令用 {{prompt}} 或 {{prompt_file}} 接收任务上下文。
- 配置入口：`implementations.*.terminal`、`implementations.*.command`、`read_capabilities(agent_terminal)`
- 边界：普通命令只读；交互终端当前支持 macOS/Linux。进程重启后只保留历史并按既有操作权恢复，不保证恢复 CLI 会话。终端不需要Loop编辑解锁，session身份和执行状态仍校验，结果仍须 report_task/finish；不要重复构建日志查看与交互通道。
- 工具入口：set_implementation、read_task
- 详细说明：[references/terminal.md](terminal.md)

## host_service

- 生效方式：configured
- 平台承担：在已安装主机持续运行服务，保存工作区；提供受支持系统的防休眠和 macOS 后台托管。
- 作者提供：安装并选择主机、数据库、端口与所需凭据；可按运行需求配置主机。
- 配置入口：`service CLI`、`platform keep-awake setting`
- 边界：远程计算平台、凭据、训练环境和跨机器部署由安装或业务适配负责。
- 工具入口：由运行平台提供，无须单独调用
- 详细说明：[references/platform-capabilities.md](platform-capabilities.md)

## authoring

- 生效方式：operator
- 平台承担：保存同一草稿及 revision，校验定义，生成本机可用版本；运行固定在启动时版本。
- 作者提供：设计业务节点和方法，持续编辑已有草稿；需要分享时导出。
- 配置入口：`Loop.id/version`、`draft revision`
- 边界：保存草稿、保存可用版本、打包分享用途不同；不会自动迁移历史 Run。
- 工具入口：list_loops、read_loop、create_loop、copy_loop、set_loop、put_node、remove_node、set_implementation、put_step、remove_step、connect_steps、validate_loop、publish_loop
- 详细说明：[references/build.md](build.md)

## parameter_contracts

- 生效方式：automatic
- 平台承担：在正式任务写入及执行选择时校验嵌套输入输出与参数。
- 作者提供：声明真实契约，调用预校验工具定位缺失字段。
- 配置入口：`nodes.*.parameter_schema`、`implementations.*.parameter_schema`、`records`
- 边界：不解释领域含义，也不把 schema.default 注入参数。
- 工具入口：read_loop、read_task
- 详细说明：[references/contracts.md](contracts.md)

## conditional_contracts

- 生效方式：declared
- 平台承担：执行条件必填、互斥与组合类型检查，对不支持的 schema 关键字报错。
- 作者提供：将确定性的参数要求声明在 schema 中。
- 配置入口：`parameter_schema.if/then/else`、`parameter_schema.oneOf`、`parameter_schema.dependentRequired`
- 边界：仅支持公布的 JSON Schema 子集；业务 CLI 参数投影仍由实现负责。
- 工具入口：read_capabilities、validate_loop、validate_parameters
- 详细说明：[references/contracts.md](contracts.md)

## plans

- 生效方式：declared
- 平台承担：生成 Task/输出身份，按 each 展开，按 collect 聚合，解析输入和 after，按 when/skip 省略步骤。
- 作者提供：定义稳定工作骨架、批次参数、输入映射和可选步骤。
- 配置入口：`plans.*.parameters`、`plans.*.steps`、`steps.*.each/when`、`inputs.*.from/collect`
- 边界：省略项不创建占位结果，消费者需明确复用来源；plan.when 作用于步骤，先于该步骤 each。
- 工具入口：put_step、build_plan、read_plans、preview_plan
- 详细说明：[references/build-reference.md](build-reference.md)

## event_routes

- 生效方式：declared
- 平台承担：接受节点事件后映射结果参数并展开计划，与结果写入一起提交；重复报告返回同一回执。
- 作者提供：声明 event、plan、values 和需要的 each/when/steps；节点只提交业务结果。
- 配置入口：`nodes.*.routes`、`report_task.report_id`
- 边界：仅由接受的生命周期报告触发；同一后继不要又在 helper 中主动生成。
- 工具入口：put_node、read_task、report_task、test_loop
- 详细说明：[references/build-reference.md#事件触发任务](build-reference.md#事件触发任务)

## task_refs

- 生效方式：declared
- 平台承担：把业务 ref 解析为真实 Task/record 身份，支持同一报告各批次间前向引用。
- 作者提供：提供 Run 内唯一名称及明确的汇总成员；循环名称包含轮次。
- 配置入口：`steps.*.ref`、`steps.*.after_refs`、`inputs.*.task_ref/task_refs`
- 边界：引用缺失或重复会拒绝提交；没有自动推断成员的任务组调度器。
- 工具入口：put_step、add_task、resolve_refs、preview_plan
- 详细说明：[references/contracts.md](contracts.md)

## record_versions

- 生效方式：automatic
- 平台承担：任务输出引用固定生产者版本，保存真实输入来源；汇总可读取不同版本的记录。
- 作者提供：通过 task_ref/task_refs 声明来源；需要覆盖版本时明确指定。
- 配置入口：`inputs.*.revision/revisions`、`resolve_refs`
- 边界：普通 record 来源未指定版本时沿用最新值语义；版本固定不校验远端文件内容。
- 工具入口：resolve_refs、read_record、build_plan、add_task
- 详细说明：[references/contracts.md](contracts.md)

## task_edits

- 生效方式：operator
- 平台承担：按 revision 和范围检查预览或原子应用有序任务编辑，失败时整组回滚。
- 作者提供：选择本次改动并检查预览。
- 配置入口：`edit_tasks.changes`、`edit_tasks.preview`、`Timeline.revision`
- 边界：独立工具调用不是跨调用事务；结果和后继一起提交可用 routes。
- 工具入口：edit_tasks、change_task
- 详细说明：[references/run.md](run.md)

## lifecycle

- 生效方式：declared
- 平台承担：通用状态机独立计算转移，Timeline 统一保存状态、结果和历史；沿原事务应用同 Task 重试、异常观察与配置的兜底。
- 作者提供：外部适配器报告有限事实；沿用 lifecycle 声明转移、重试条件和业务修复方法，无需业务专属转移函数或状态仓库。
- 配置入口：`implementations.*.lifecycle`、`implementations.*.command/observe`、`Loop.fallback_node`
- 边界：已有 Loop 无需迁移；waiting 仍带外部任务身份、观察时间及查询错误。正常排队或耗时不会自动成为业务失败；重试、去重与原子提交语义不变。
- 工具入口：set_implementation、report_task、change_task
- 详细说明：[references/build-reference.md](build-reference.md)

## waits

- 生效方式：declared
- 平台承担：原生 timer/event/approval Task 表达等待；外部事件按名称和关联键匹配，状态持久化。
- 作者提供：声明等待时间、事件键或审批任务，以及收到结果后的 routes。
- 配置入口：`implementations.*.kind`、`implementations.*.wait`、`implementations.*.event`
- 边界：通知本身不暂停运行；等待需有明确 Task。聊天桥接和业务事件来源由适配器接入。
- 工具入口：set_implementation、send_event
- 详细说明：[references/notifications.md](notifications.md)

## notifications

- 生效方式：configured
- 平台承担：按出口排队投递、去重、保存回执；未配置出口显示等待配置，投递失败保留故障。
- 作者提供：配置实际发送命令/目标，声明通知内容和询问关联键。
- 配置入口：`platform notification channels`、`settings.notification_route`、`lifecycle.transitions.*.notify`、`notify.reply`
- 边界：本地通知区收录不代表外部送达；平台不会自行安装聊天机器人。
- 工具入口：notify、read_notification_channels、set_notification_channels、send_event、retry_notification
- 详细说明：[references/notifications.md](notifications.md)

## scopes

- 生效方式：automatic
- 平台承担：按父子归属保护操作范围，允许不相交支线并行，维护获取和释放操作权。
- 作者提供：让任务归属对应真实责任，完成或明确等待后 finish；全局判断使用明确的全局节点。
- 配置入口：`Task.parent_id`、`Loop.global_agent_node`、`acquire_run/finish`
- 边界：依赖与归属含义不同；父 Agent 持有范围时，子 Agent 需等待释放。
- 工具入口：read_timeline、acquire_run、finish、read_task
- 详细说明：[references/run.md](run.md)

## run_control

- 生效方式：operator
- 平台承担：提供暂停/恢复、任务编辑、用户请求与等待登记，Hooks 可在前后或状态转移时暂停/通知。
- 作者提供：按用户意图选择干预位置和动作。
- 配置入口：`settings.hooks`、`command`、`defer_task`、`resolve_request`
- 边界：自然语言授权由用户的 Agent 理解，平台执行显式操作与权限检查。
- 工具入口：list_runs、start_run、read_run、next_tasks、read_record、complete_task、command、defer_task、resolve_request、change_settings
- 详细说明：[references/run.md](run.md)

## termination

- 生效方式：declared
- 平台承担：按 completion_rule 或 termination_signal 将 Run 收口并停止剩余工作。
- 作者提供：声明可判定的终止条件，或将已确认的完成判断写入相应设置。
- 配置入口：`settings.completion_rule`、`settings.termination_signal`
- 边界：业务输出里的 satisfied/status、没有剩余任务或 finish 都不会自行结束 Run。
- 工具入口：change_settings、read_timeline
- 详细说明：[references/run.md](run.md)

## scenarios

- 生效方式：operator
- 平台承担：用真实 Engine 在隔离库中推进作者提供的模拟报告，检查任务展开、依赖、去重和收口。
- 作者提供：给出代表性输入、模拟事实与可观察预期。
- 配置入口：`Loop.scenarios`、`test_loop`、`preview_plan`
- 边界：拦截命令/模型/通知投递，不能替代真实外部环境和模型行为验收。
- 工具入口：test_loop、preview_plan
- 详细说明：[references/testing.md](testing.md)

## packages

- 生效方式：operator
- 平台承担：打包定义、候选和作者资源，检查能力要求并安装；工作区历史保留。
- 作者提供：附带实际使用的文件、声明依赖和能力要求，提供目标环境配置。
- 配置入口：`Loop.requires`、`package assets`、`export_loop`
- 边界：平台不自动补业务依赖；包安装不启动业务 Run。
- 工具入口：export_loop、read_capabilities
- 详细说明：[references/build-reference.md](build-reference.md)

## author_skills

- 生效方式：declared
- 平台承担：按 Loop/节点绑定返回作者方法及安装后的路径，保留包内相对结构。
- 作者提供：编写领域方法、所需证据、输入输出和完成标准。
- 配置入口：`Loop.handbook`、`nodes.*.skills`、`put_asset`
- 边界：绑定脚本资产不会自动把它注册成候选实现；业务方法不会由平台生成。
- 工具入口：read_loop、read_timeline、read_task、put_asset
- 详细说明：[references/build-reference.md](build-reference.md)

## runtime_smoke

- 生效方式：operator
- 平台承担：执行显式请求的真实最小 Agent 启动，并模拟生命周期矩阵的报告路径。
- 作者提供：按授权选择候选/用例，另行验证真实外部业务。
- 配置入口：`smoke_runtime`
- 边界：该检查可能调用模型；静态校验和模拟通过不代表目标环境已可用。
- 工具入口：smoke_runtime
- 详细说明：[references/build.md](build.md)

## 常见组合

### flow_agent_decision

已有 Skill 的后续动作需要临场判断，先跑通，再逐步固化稳定规则。

```json
{
  "use_when": "已有 Skill 的后续动作需要临场判断，先跑通，再逐步固化稳定规则。",
  "capabilities": [
    "flow_agent",
    "event_routes",
    "plans",
    "scopes"
  ],
  "prerequisites": "Loop handbook 保存目标、约束和已有业务方法，无需穷举所有分支；源节点有 result 对象输出；下列 node 可用 put_node 保存，plan.steps 用 put_step 保存。Agent 候选配置实际 CLI 或群组 dispatch。",
  "node": {
    "node_id": "flow_agent",
    "instructions": "完整读取 Loop handbook，结合当前目标与结果判断下一步；提交决策和依据，安排后续后 finish 退出。",
    "inputs": [
      {
        "name": "trigger",
        "type": "object"
      },
      {
        "name": "result",
        "type": "object"
      }
    ],
    "outputs": [
      {
        "name": "decision",
        "type": "object"
      }
    ]
  },
  "source_routes": [
    {
      "id": "decide",
      "event": "completed",
      "plan": "decide_next",
      "values": {
        "record": {
          "$": "task.outputs.result.id"
        },
        "trigger": {
          "task_id": {
            "$": "task.id"
          },
          "transition": {
            "$": "transition"
          }
        }
      }
    }
  ],
  "plan": {
    "steps": {
      "decide": {
        "node": "flow_agent",
        "inputs": {
          "trigger": {
            "literal": {
              "$": "values.trigger"
            }
          },
          "result": {
            "record": {
              "$": "values.record"
            }
          }
        }
      }
    }
  },
  "execution": "流程 Agent 完整读取 Loop handbook（唤醒上下文或 read_timeline 返回），用 read_task/read_timeline 取当前事实，build_plan/add_task 或 edit_tasks 安排后续；report_task 提交 decision 后 finish 退出。已声明 routes 的后续只提交映射结果，不重复安排。确定的脚本或等待节点完成后可再沿同样路由唤醒流程 Agent。",
  "scope": "本分支决策沿用普通节点范围；需要改全局目标、收口或调整其他支线时用 set_loop(global_agent_node=\"flow_agent\") 显式配置全局节点。global_agent_node 赋予范围，不自行轮询或触发。不要把正常判断配置为 fallback。",
  "verification": [
    "test_loop",
    "read_record"
  ]
}
```

### shared_space_onboarding

各机器独立安装后，首次寻找共同群组并开放具名 Agent。

```json
{
  "use_when": "各机器独立安装后，首次寻找共同群组并开放具名 Agent。",
  "capabilities": [
    "agent_communication"
  ],
  "configuration": [
    "communication_config(operation=space,path=本机已挂载目录) 保存共享空间并检查本机读写；各机路径可以不同，核对返回 space_id。",
    "communication_workspace(discover=true) 返回各空间群组及读取错误；发现不自动加入。创建用 operation=group、space_id、create=true、name；加入用 space_id、relative_path、group_id。",
    "用 operation=agent 显式配置本机 CLI、cwd、resume_command，并选择 groups；加入群组不自动开放任何 Agent，也可只调用别人。",
    "communication_workspace(group_id=...) 返回不含本机命令、凭据和挂载路径的加入说明；communication_status 查看开放成员，再绑定 Loop 或普通对话。"
  ],
  "author_provides": "共享 NAS 的访问方式与本机挂载路径、群组用途、本机允许启动的 Agent 命令；NAS 权限负责准入。",
  "verification": [
    "communication_workspace",
    "communication_status",
    "communication_config"
  ]
}
```

### chat_origin_delivery

用户在飞书私聊或群话题中请求本机/远端外援，结果需要回到这段对话。

```json
{
  "use_when": "用户在飞书私聊或群话题中请求本机/远端外援，结果需要回到这段对话。",
  "capabilities": [
    "cc_connect",
    "conversation_notifications",
    "agent_communication",
    "notifications"
  ],
  "configuration": [
    "通过 Skill call.py 发起 request_assistance 或 start_run，只随业务请求携带 chat_context；平台保存来源及可用thread_root，适配器复用根消息直接调用cc-connect，不作渠道预检。",
    "通过 read_cc_connect 发现 Bot，在具名 Agent 的 notification_bot 直接选择 project/platform；群内执行确认和结果优先该 Bot，私聊仍由入口回复。",
    "保存原始session_key和话题信息；发送时优先使用thread_root，缺失时原样交给cc-connect，Agent无需查飞书、补密钥或配置预检。桥接负责实际话题回复和发送权限；发送已开始后的未知结果不自动重发，通知失败不阻断任务。"
  ],
  "author_provides": "具名Agent对应Bot引用（notification_bot）；复用已有cc-connect接入；Loop不需要Bot凭据。",
  "verification": [
    "read_assistance",
    "communication_workspace"
  ]
}
```

### group_cc_connect_delivery

没有聊天来源时，A 请求 B 工作，通知优先由动作发生的机器发送，无入口时回退 A。

```json
{
  "use_when": "没有聊天来源时，A 请求 B 工作，通知优先由动作发生的机器发送，无入口时回退 A。",
  "capabilities": [
    "conversation_notifications",
    "group_notifications",
    "group_notification_priority",
    "agent_communication",
    "notifications"
  ],
  "configuration": [
    "在 A、B 各自通过 read_cc_connect / configure_cc_connect 接入桥接；固定出口使用 cc_connect={project,platform} 和明确 destination，无需拼接命令。",
    "各机器调用 communication_config operation=group_notifications；修改需带本机当前 binding_id，互不覆盖其他机器。",
    "communication_status 返回按机器索引的 notification_bindings；请求省略 notification_route，执行/返回事件优先 B，无 B 入口回退 A，均无入口只记录。"
  ],
  "author_provides": "群组及各机器实际聊天目标；业务 Agent 无需编写通知队列、选发送方或自行调用 cc-connect。",
  "verification": [
    "communication_status",
    "read_assistance",
    "communication_workspace"
  ]
}
```

### named_agent_assistance

当前节点或普通对话需要临时外援；外援可在本机，也可在明确选定的 NAS 群组中。

```json
{
  "use_when": "当前节点或普通对话需要临时外援；外援可在本机，也可在明确选定的 NAS 群组中。",
  "capabilities": [
    "agent_communication",
    "agent_terminal",
    "assistance_session_resume"
  ],
  "configuration": [
    "communication_status 发现显式开放的本机目录和获准群组，使用 agent_id 与必要的 instance_id 消歧。",
    "request_assistance 返回持久请求ID，可信工作区按ID读取；本机调用不要求 NAS，独立调用由内置协作 Run 跟踪；后续求援传 collaboration_id，追问自动沿用原 Run。",
    "平台托管节点先记录原生 session 和恢复配置，再使用 wait_assistance 持久等待并 finish；回复或期限到达后在原机器恢复同一个 CLI session，以新凭据和外援结果继续同一个 Task；不可恢复时明确阻塞，不新建会话。",
    "外援通过限定客户端 read_context 按需读取关联上下文，通过 complete 提交协助结果；不取得原节点写权限。"
  ],
  "author_provides": "具体问题、需分享的上下文、结果要求和不可用时的业务判断；机器所有者配置具名 CLI 与开放范围。",
  "verification": [
    "communication_config",
    "read_assistance"
  ]
}
```

### group_agent_node

某个正式 Agent 节点需要在其他机器完成。

```json
{
  "use_when": "某个正式 Agent 节点需要在其他机器完成。",
  "capabilities": [
    "agent_communication",
    "implementation_selection",
    "lifecycle"
  ],
  "configuration": [
    "保持 kind=agent，设置 dispatch.location=group 和 agent_id 或 capability；绑定 Run 群组。",
    "成员申请承接，来源确认后启动；来源平台继续拥有业务 Run。其他本地节点不发布到群组。",
    "通过限定 platform_client/URL 使用 read_task、report_task 和 finish，沿用原结果契约与操作范围。"
  ],
  "author_provides": "节点业务契约、成员选择；执行端提供 CLI、环境和可访问的产物。",
  "verification": [
    "communication_config",
    "read_assistance"
  ]
}
```

### result_to_batch_and_review

源节点给出多组已确定参数，每项工作执行后汇总本批结果。

```json
{
  "use_when": "源节点给出多组已确定参数，每项工作执行后汇总本批结果。",
  "capabilities": [
    "event_routes",
    "plans",
    "task_refs",
    "task_scheduler",
    "scopes"
  ],
  "prerequisites": "源节点输出 jobs 数组，每项有 id 和 params；work 输出 result；review 输入 results 数组。作者补齐真实实现与业务参数契约。",
  "source_routes": [
    {
      "id": "dispatch",
      "event": "completed",
      "plan": "work_and_review",
      "values": {
        "jobs": {
          "$": "outputs.jobs"
        }
      }
    }
  ],
  "plan": {
    "parameters": {
      "type": "object",
      "properties": {
        "jobs": {
          "type": "array"
        }
      },
      "required": [
        "jobs"
      ]
    },
    "steps": {
      "work": {
        "node": "work",
        "each": "jobs",
        "inputs": {},
        "parameters": {
          "$": "item.params"
        },
        "ref": "work:{item.id}"
      },
      "review": {
        "node": "review",
        "inputs": {
          "results": {
            "from": "work",
            "port": "result",
            "collect": true
          }
        },
        "after": [
          "work"
        ],
        "ref": "review:batch"
      }
    }
  },
  "execution": "源节点报告 completed 并提交 jobs 后，平台创建工作和汇总任务；依赖就绪时调度。源 Agent 提交后 finish 释放范围。循环使用时给 ref 加轮次。",
  "verification": [
    "preview_plan",
    "test_loop"
  ]
}
```

### external_job

外部系统提交后需要持续查询，结束后消费结果。

```json
{
  "use_when": "外部系统提交后需要持续查询，结束后消费结果。",
  "capabilities": [
    "implementation_selection",
    "lifecycle",
    "execution_recovery",
    "event_routes"
  ],
  "configuration": [
    "同一 external 候选的 command 提交，observe 查询；报告 submitted 时保存 external_id。",
    "observer 报告 progress/completed 或已声明失败事件；lifecycle 定义 retry/agent 等处理。",
    "完成事件可通过 routes 生成后继，输入/after 让消费者等待结果。"
  ],
  "author_provides": "外部 API、执行身份、状态翻译、产物检查与提交幂等策略。",
  "verification": [
    "smoke_runtime",
    "test_loop"
  ]
}
```

### question_then_continue

发送问题，等待对应回复，再生成后续工作。

```json
{
  "use_when": "发送问题，等待对应回复，再生成后续工作。",
  "capabilities": [
    "notifications",
    "waits",
    "event_routes"
  ],
  "configuration": [
    "notify.reply 声明问题的 event/key/schema。",
    "创建 event Task 等待同一 event/key；收到的 payload 对应节点输出。",
    "该节点的 completed route 使用回复参数展开后继。"
  ],
  "author_provides": "提问内容、通知出口、外部回复桥接和回复后的业务处理。",
  "verification": [
    "test_loop"
  ]
}
```
