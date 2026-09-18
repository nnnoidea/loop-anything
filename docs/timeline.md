# Programmable Timeline

Timeline 是一次 Run 的完整持久化过程：既保存目标、任务和已经发生的结果，也保存后续如何推进的安排。完整文档由 `GET /api/runs/{id}` 返回；Agent 通常通过工具读取当前需要的部分。

## 组成与职责

| 部分 | 内容 |
| --- | --- |
| `loop_definition` | 本次 Run 使用的节点职责、输入输出契约和批次模板 |
| `implementations` | 可选的候选执行方式 |
| `settings` | 目标、授权、约束、运行设置、Bindings、Hooks 和终态条件 |
| `tasks` | 实际安排的任务、输入来源、输出目标、依赖、参数和状态 |
| `records` | 正式结果的版本、生产执行和来源 |
| `executions` | 每次执行尝试的输入、实现快照、状态及错误 |
| `events`、`history` | 外部事件和可追溯的运行变化 |

Agent 或脚本通过公开协议写入任务和结果；Engine 根据已有状态、依赖和控制条件推进。Engine 不解释自然语言授权，也不替业务规划后续任务。正式写入在同一数据库事务中校验并生效。

Loop 的节点是能力模板；一个节点可在同一 Run 中对应多项任务。候选实现和选用关系见 [Implementation 与 Binding](implementation-selection.md)。已派发执行保留当时的实现配置，修改默认选择只影响后续任务。

## 初始化与 Agent 操作

常用入口是用户自己的 Agent 与用户讨论后调用 `start_run`，原子创建 Run 并取得操作权，再完成入口任务。入口保存初始状态，不在每轮重新创建。

同一 Run 的 Agent 按具体 Task 的支线归属操作，不重叠的范围可并发，祖先/后代或全局范围互斥。普通 Agent 可规划自己支线的后续工作；全局 Agent 可处理整个 Run。正常脚本和外部事件仍按自己的契约执行、写回；不同 Run 不互斥。

- `read_timeline`：当前目标、设置、候选摘要和任务问题。
- `read_task`：指定任务的输入、来源、当前实现、输出契约、节点 Skill 和 `task_version`。
- `complete_task`：一次提交完整正式结果；输入或实际选择变化后旧 `task_version` 不能提交。
- `add_task`：从已声明节点创建单项任务，自动分配输出记录身份。
- `build_plan`：批量写入本次已确定的任务。
- `change_task`、`change_settings`：调整授权范围内的后续安排或设置。
- `next_tasks`：确定性列出当前任务、故障和用户请求，区分正常等待。
- `finish`：完成或明确等待本次唤醒任务、处理本范围异常后，释放自己的操作权；已安排的就绪后续任务可交回 Engine，无需清空任务列表，不直接完成 Run。

需要用户输入或授权时明确记录等待原因，不伪造成功。命令接入见 [Agent 接入](agent-integration.md)，操作顺序见 [平台运行说明](../skills/loop-anything-platform/references/run.md)。

## 任务、结果与依赖

任务引用节点并明确输入来源和输出记录：

```json
{
  "id": "evaluate.E1",
  "node": "evaluate",
  "inputs": {"model": {"record": "model.E1", "revision": 1}},
  "outputs": {"metric": {"id": "metric.E1", "expected_revision": 0}},
  "parameters": {"dataset": "validation"}
}
```

输入来源可为 `record`、`records`、`run`、`settings` 或 `literal`。记录引用可指定 revision 和值内 path；实际派发保留所用版本与来源。声明的必需输出必须完整提交，不存在输出草稿合并步骤。

同一工作或批次 ID 的相同写入不会重复创建；同 ID 不同安排会被拒绝。输出版本冲突不会覆盖已经提交的事实。

批次模板位于 `plans`，支持参数、步骤、`each` 展开、`from` 输入引用、`collect` 聚合和 `after` 顺序依赖。`build_plan` 可按步骤覆盖输入、参数和 implementation，或用 `skip:true` 不创建某一步；有消费者时须显式提供复用来源。

`round` 仅作展示分组，不参与调度。不同任务按真实依赖独立推进，不要求整轮统一完成。

新增或修改任务在事务提交前校验依赖循环，失败时整批回滚。历史异常仍可诊断。输入缺口、失败及实际需要任务时的 `missing_implementation` 会明确报告。正常执行、等待已知外部事件和未使用的节点不算异常。任务列表为空不表示目标已完成。

## 执行接口

Agent 只通过 read_task/complete_task 写入结果，旧 submit 不接受 Agent 提交，命令的最终文字仅供观察。脚本命令通过 stdin 接收本次输入、参数、执行身份、Timeline 和输出契约，通过 stdout 返回结果 JSON：

```json
{"outputs":{"result":"业务结果"}}
```

初始化结果同时提供 `settings` 中的目标等语义字段。脚本可以在 `tasks` 中提供已经明确构建的后续工作，受节点 `plan_nodes` 限制；Agent 按用户授权和当前操作范围使用已声明能力；普通 Agent 仅修改自己的 Task 子树。

异步实现 start/observe 可返回 `{"status":"waiting","external_id":"...","poll_after":10}`，之后由 Engine 观察；正式完成时仍提交完整 outputs。外部事件按名称、关联 key 和事件 ID 匹配、去重。

HTTP 写请求携带 `X-Loop-Anything: workspace`。持有 Agent 操作权时，相关写入口还要求当前令牌：

| Run 路由 | 用途 |
| --- | --- |
| `/agent` | `{token, tool, arguments}`，调用同一套 Agent 工具 |
| `/submit` | 仅接收脚本或审批执行的 token 和完整 envelope；Agent 必须用 complete_task |
| `/event` | 写入 event_id、name、key、payload |
| `/tasks` | 复用 add_task/change_task/build_plan；以 revision 校验，支持只读 preview |
| `/settings` | 使用 settings revision 更新目标、Bindings、Hooks 或终态条件 |
| `/command` | 暂停、恢复、终止、重试及放行等控制操作 |

修改目标、要求、约束、授权或 guidance 不会自动使任何任务、审批或结果失效。是否取消或调整工作，由用户决定，或由用户授权的 Agent 明确调用 change_task 落实。取消待确认的审批会撤销其提交令牌；已发生的执行和结果保留。Agent 提交仍检查最新 task_version，脚本和审批提交仍验证执行令牌及输出契约。旧 policy/intent_revision 不再参与运行。已有外部副作用不会被自动撤回。外部实现应使用稳定的 Run/任务身份处理业务幂等，不能把执行 token 当作永久业务身份。

## 显式 Agent 兜底

Loop 的可选 `fallback_node` 指向一个真实、可见的非入口节点。未设置或为空表示关闭；节点用现有 implementations/bindings 选择 Agent，并可绑定作者 Skill。它通过 Run 工具读取未覆盖状态，不需要固定业务输入端口；可以声明自己的输出。

作者已覆盖的执行、等待和结束状态按既定规则处理；执行失败、非法输入、依赖缺口、未识别事件等确定性检查识别的未覆盖状态进入所选兜底节点。无需逐条枚举异常连线，平台不猜测自然语言业务遗漏。

兜底任务使用正常 Task 派发、Hooks、Agent 操作权和 complete_task。origin 保留进入原因。已有全局 Agent 可以处理该节点；全局范围与其他 Agent 范围互斥。处理或明确等待相关事项后，仍需完成兜底节点自身的输出契约，再 finish。

`start_run.fallback_node` 可覆盖 Loop 默认，空字符串明确关闭；运行中用 `change_settings.change.fallback_node` 设置节点 ID 或 null。关闭会取消尚未派发的自动兜底任务，已派发调用保留原操作权和实现。未启用时保留问题，不隐式选择其他 Agent。

## Hooks 与终态

Hook 包含 `id`、`target:{node或tasks}`、`action:pause或notify`、`phase:before或after`、`frequency:once或always`，以及可选消息、发送 route 和 enabled。暂停仅支持执行前拦截；通知可独立于业务推进。放行针对具体 Hook 触发记录。

通知默认调用用户提供的 `$notifications` 命令；只有返回 `{"delivered":true}` 才记为送达。显式 `route:workspace` 仅代表本地收录。失败或结果未知如实记录，不假称已经通知用户。

结束统一由 Engine 判定：

1. Agent 写入 `settings.completion_rule`，Engine 机械求值后进入终态。
2. Agent 判断目的已达成，写入带原因的 `settings.termination_signal`，Engine 识别后进入终态。

表达式支持 `eq/le/ge/add/len/and/or`；`path` 可为点分隔字符串或路径段数组。求值根为 settings、inputs、records 的最新正式值、completed 的各节点完成任务数，以及 active_tasks。and/or 按参数顺序短路；只有求值需要访问而尚未产生的结果才使规则暂不成立，类型错误作为异常报告。

需要等待在途任务结束时，将 `active_tasks == 0` 纳入规则。进入终态会取消未结束任务并拒绝旧提交，不撤回已经发生的外部影响。不存在终点节点或额外完成判断任务。

## 恢复与运行边界

平台确认 Agent 命令退出且 Loop 仍异常时会再次唤醒；同一段异常从首次失败起计数，合计三次后暂停并调用用户的通知实现。支线转交全局兜底时沿用未解决支线的最长失败链，不叠加不同支线同时发生的失败；异常解决或显式恢复后清零。主动暂停或等待用户不计作失败；已有明确执行预算继续生效。

未确认旧命令停止时保留操作权；显式确认停止后才可恢复。平台不为独立交互客户端添加心跳或自动抢占。Agent 未显式配置 timeout 时不限时；脚本命令默认 60 秒，通知默认 30 秒。

平台进程运行期间推进各个 Run，并申请系统防休眠保护。系统自启动、平台退出后的常驻及分布式容灾不属于当前实现。界面显示实际保护状态；真实业务、真实模型和各系统原生环境仍需分别验收。

## 可视化操作

运行页默认显示实际任务依赖图，可切换实际执行开始时间顺序与作者提供的轮次分组。新执行保留派发 created_at 和开始 started_at，排队时 started_at 为 null；旧执行没有开始时间，明确显示历史派发时间，不补造事实。平台记录自己观察到的执行开始或人工结果提交；用户 Agent 在平台外的准备对话不计时。任务详情展示正式输入输出、所用来源版本、执行尝试及变更记录；定义图在单独的折叠区，不与实际运行任务混淆。

网页通过 `POST /api/runs/{id}/tasks` 提交 `{revision, changes:[{tool, arguments}]}`，tool 限于 `add_task`、`change_task`、`build_plan`。设置 `preview:true` 可在内存副本中展开并校验修改，返回实际任务差异，数据库不变。正式提交复用 Agent 工具参数与同一事务校验；版本冲突或修改范围与其他 Agent 重叠时拒绝提交。未开始任务可调整 inputs、parameters、implementation、after；已派发的脚本及已完成任务受保护。修改展示仅表示明确变更及依赖关联，不自动推断业务失效。

文件输出的声明与路径约定见平台 [构建说明](../skills/loop-anything-platform/references/build.md#结果的通用展示)。结果值及来源保留历史；文件本体不会自动归档，作者应提供不同的产物路径。


## Task 归属与多 Agent

Task 的 `parent_id` 指向所属的父 Task，顶层为 null；归属固定，独立于数据依赖。`agent_sessions` 列表保存当前操作者的 token、scope_task、task_id 及执行身份。scope_task 为 null 时是全局范围。既有单操作者格式读取时保留其原全局资格，不撤销仍有效的操作权。

支线令牌只能新增或修改该子树内的任务。公共汇总应由共同上层创建，并通过 inputs/after 等待各支线结果。支线可读其他结果但不能修改别人的任务或借新任务输出覆盖其他支线记录。批次幂等 key 在支线范围内区分，兄弟支线使用相同 key 不互相覆盖。

入口、兜底和明确配置的 global_agent_node 具有全局操作资格。全局资格不意味着常驻；范围取得与释放使用同一套机制。Agent finish 可将就绪后续任务交给 Engine；它只释放自己的操作权。失败及进程恢复也按对应操作者处理。

通知发送可由本 Run 的 settings.notification_command 覆盖 Loop 的 `$notifications`。它是通用 argv 数组，由 start_run 或全局 change_settings 设置；空数组沿用 Loop 默认。首次发送时固定发送实现，重试保留原目标；没有配置过发送实现的失败可补配后重试。通知载荷不包含内部执行 token/发送命令。已配置发送实现时，Engine 进入完成终态生成一次完成通知；用户主动 terminate 不生成成功通知。
