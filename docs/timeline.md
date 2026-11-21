# Programmable Timeline

## 状态保存与状态转移

Timeline 保存目标、限制、业务进度和正式结果。Run 保存任务安排和执行状态。节点报告事件时，状态机按生命周期规则计算下一状态，平台在同一事务中写入结果和命中路由产生的任务，再由调度器执行。

生命周期与报告仍使用统一机制。业务状态及正式结果由 Timeline 持有，Run 保留执行过程与来源；读取按实际运行结构校验，不按存储格式编号拒绝数据，也不增加旧格式转换分支。外部等待仍包含 external_id、观察时间与观察错误；check_error 会暂停观察，恢复监控继续使用原外部任务。同 Task 重试、报告去重和依赖调度行为保持不变。规则可以用于训练、渲染、审批等不同场景，业务适配器负责外部接入。

## Timeline 内容

Timeline 独立保存目标、限制、Loop 定义的业务状态和正式结果。Run 使用某个 Loop 版本推进它，保存具体执行过程。切换 Run／Loop 后，业务 Agent 仍按目标、限制和当前状态工作，不执行额外交接流程。用户有效要求直接维护，不归档聊天原话。

`read_work_timeline(timeline_id)` 返回业务状态汇总、关联 Run、结果索引和分页进展记录；`read_business_state` 读取完整业务记录及历史版本。Run 内 `read_timeline` 返回同一业务状态入口，`read_record` 可读同一 Timeline 的已有正式结果。

业务状态由 Loop 定义、解释和校验。可选的 `state.types` 提供 summary 等展示信息；平台不按 schema、current/append 模式或节点类型白名单阻止状态写入，也不在接续时判定新旧 Loop 业务契约是否兼容。

`report_task(event=completed)` 可同时提交 envelope.state、outputs 和 operations，在同一事务保存。state 每项包含 type、id、value 及可选精确 refs；平台自动保存逐条历史版本，内容和引用未变则复用。未出现在更新中的记录保持不变。

实验用 build_plan.work_key 取得 Timeline 内稳定安排；同键同内容复用原安排，不重复提交。add_task.after_work 使用工作键和步骤名关联已有实验。外部执行由事务外的 Engine 完成。

新 Run 绑定已有 Timeline 后，平台保留在途执行的原身份与已安排任务的定义和已知输入版本；原执行可完成当前 Run 仍等待的状态／结果报告，新安排由当前 Run 负责。接续前，平台核对仍在执行的入口或路由 Agent 的进程状态。优化 Loop 后的业务节点不需要判断自己是否接续。具体契约见[持续工作说明](../skills/loop-anything-platform/references/work.md)。

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

Agent 或脚本通过公开协议写入任务和结果；节点声明 routes 时，平台在接受报告事件的事务内映射参数并展开指定 plan，自动创建 Task；Engine 根据已有状态、依赖和控制条件推进。Engine 不解释自然语言授权，也不替业务规划后续任务。正式写入在同一数据库事务中校验并生效。

Loop 的节点是能力模板；一个节点可在同一 Run 中对应多项任务。候选实现和选用关系见 [Implementation 与 Binding](implementation-selection.md)。已派发执行保留当时的实现配置，修改默认选择只影响后续任务。

## 初始化与 Agent 操作

用户的 Agent 可以在对话中调用 `start_run`，获得 Run 和 Timeline 的标识。带固定入口的 Loop 由平台调度；需要启动 Agent 亲自完成的入口会返回该任务的临时操作身份。无入口的顶层 Run 由启动 Agent 根据手册安排首批任务；作为子 Loop 时可由父节点提前声明 `loop.seed`。

同一 Run 的 Agent 按具体 Task 的支线归属操作，各范围可以同时思考，提交时校验执行身份、作用范围和任务状态；同 Task 只保留一个有效执行者。普通 Agent 可规划自己支线的后续工作；全局 Agent 可处理整个 Run。正常脚本和外部事件仍按自己的契约执行、写回；不同 Run 不互斥。

- `read_timeline`：目标、限制、业务状态与进度。执行状态、当前设置和任务问题从 `read_run(view="snapshot")` 或 `next_tasks` 查看。
- `read_task`：指定任务的输入、来源、当前实现、输出契约和节点 Skill。
- `report_task(event=completed)`：使用实际执行身份和稳定 report_id 一次提交完整正式结果。
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

Agent 只通过 read_task/report_task(event=completed) 写入结果，旧 submit 不接受 Agent 提交，命令的最终文字仅供观察。脚本命令通过 stdin 接收本次输入、参数、执行身份、Timeline 和输出契约，通过 stdout 返回显式事件报告 JSON：

```json
{"event":"completed","envelope":{"outputs":{"result":"业务结果"}}}
```

初始化报告在 `envelope.settings` 中提供目标等语义字段。脚本可以在 `envelope.tasks` 中提供已经明确构建的后续工作，受节点 `plan_nodes` 限制；Agent 按用户授权和当前操作范围使用已声明能力；普通 Agent 仅修改自己的 Task 子树。

异步实现 start 返回 `{"event":"submitted","external_id":"...","poll_after":10}`，之后由 Engine 观察；observe 用 `event:"progress"` 报告进度，用 `event:"completed"` 和完整 `envelope.outputs` 报告完成。stdout 未指定 `report_id` 时，平台使用本次调用的 ID；旧 `status:"waiting"` 和裸结果对象不接受。外部事件按名称、关联 key 和事件 ID 匹配、去重。

HTTP 写请求携带 `X-Loop-Anything: workspace`。持有 Agent 操作权时，相关写入口还要求当前令牌：

| Run 路由 | 用途 |
| --- | --- |
| `/agent` | `{token, tool, arguments}`，调用同一套 Agent 工具 |
| `/submit` | 仅接收脚本或审批执行的 token 和完整 envelope；Agent 必须用 report_task(event=completed) |
| `/event` | 写入 event_id、name、key、payload |
| `/tasks` | 复用 add_task/change_task/build_plan；以 revision 校验，支持只读 preview |
| `/settings` | 使用 settings revision 更新目标、Bindings、Hooks 或终态条件 |
| `/command` | 暂停、恢复、终止、重试及放行等控制操作 |

修改目标、要求、约束、授权或 guidance 不会自动使任何任务、审批或结果失效。是否取消或调整工作，由用户决定，或由用户授权的 Agent 明确调用 change_task 落实。取消待确认的审批会撤销其提交令牌；已发生的执行和结果保留。提交仍验证执行身份、作用范围及正式输出契约。旧 policy/intent_revision 不再参与运行。已有外部副作用不会被自动撤回。外部实现应使用稳定的 Run/任务身份处理业务幂等，不能把执行 token 当作永久业务身份。

## 节点事件触发模板

`nodes.<id>.routes` 声明 `{id,event,plan,values}`，可加 each、when、steps 和 round。只有接受的生命周期事件才触发；Agent 或上游只报告业务结果，平台映射到 plan 参数、生成任务并保留来源。timer 到期和匹配的外部 event 节点也通过 completed 触发。用户仍可通过 Timeline 工具追加未预定义工作。

报告转移、结果写入和所有规则生成的任务原子生效。校验失败无部分 Task；重复 report_id 返回原 routes 回执，过期报告不展开。任务归属源 Task，沿用候选参数、预算和依赖校验。Run 历史以 `route_fired` 和 `route_skipped` 分别记录命中与跳过，生成任务的 `origin` 可追溯到来源。规则不读取任意 Run 内部状态，也不解释自然语言。

完整配置与上下文见 [构建契约](../skills/loop-anything-platform/references/build-reference.md#event-triggered-task-generation)。

## 显式 Agent 兜底

Loop 的可选 `fallback_node` 指向一个真实、可见的非入口节点。未设置或为空表示关闭；节点用现有 implementations/bindings 选择 Agent，并可绑定作者 Skill。它通过 Run 工具读取未覆盖状态，不需要固定业务输入端口；可以声明自己的输出。

作者已覆盖的执行、等待和结束状态按既定规则处理；执行失败、非法输入、依赖缺口、未识别事件等确定性检查识别的未覆盖状态进入所选兜底节点。无需逐条枚举异常连线，平台不猜测自然语言业务遗漏。

兜底任务使用正常 Task 派发、Hooks、Agent 操作权和 report_task(event=completed)。origin 保留进入原因。其他全局 Agent 可协助处理问题；兜底 Task 自身仍只有一个有效执行者，全局身份与其他支线可同时存在。处理或明确等待相关事项后，仍需完成兜底节点自身的输出契约，再 finish。

构建时可用 `set_loop.fallback_node` 指定运行异常处理节点。正常业务中的语义判断在节点的显式 `flow_agent` 路由中安排。运行中用 `change_settings.change.fallback_node` 设置节点 ID 或 null。关闭会取消尚未派发的自动兜底任务，已派发调用保留原操作权和实现。未启用时保留问题，不隐式选择其他 Agent。

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

网页通过 `POST /api/runs/{id}/tasks` 提交 `{revision, changes:[{tool, arguments}]}`，tool 限于 `add_task`、`change_task`、`build_plan`。设置 `preview:true` 可在内存副本中展开并校验修改，返回实际任务差异，数据库不变。正式提交复用 Agent 工具参数与同一事务校验；相关版本变化或与同 Task 的执行状态冲突时拒绝提交，修改资格范围重叠本身不阻塞。未开始任务可调整 inputs、parameters、implementation、after；已派发的脚本及已完成任务受保护。修改展示仅表示明确变更及依赖关联，不自动推断业务失效。

文件输出的声明与路径约定见平台 [构建说明](../skills/loop-anything-platform/references/build-reference.md#generic-result-display)。结果值及来源保留历史；文件本体不会自动归档，作者应提供不同的产物路径。


## Task 归属与多 Agent

Task 的 `parent_id` 指向所属的父 Task，顶层为 null；归属固定，独立于数据依赖。`agent_sessions` 列表保存当前操作者的 token、scope_task、task_id 及执行身份。scope_task 为 null 时是全局范围。既有单操作者格式读取时保留其原全局资格，不撤销仍有效的操作权。

支线令牌只能新增或修改该子树内的任务。公共汇总应由共同上层创建，并通过 inputs/after 等待各支线结果。支线可读其他结果但不能修改别人的任务或借新任务输出覆盖其他支线记录。批次幂等 key 在支线范围内区分，兄弟支线使用相同 key 不互相覆盖。

入口任务、运行异常兜底任务、由显式路由触发的决策任务和明确配置的 global_agent_node 具有全局操作资格。全局资格不意味着常驻；范围取得与释放使用同一套机制。Agent finish 可将就绪后续任务交给 Engine；它只释放自己的操作权。失败及进程恢复也按对应操作者处理。

通知发送可由本 Run 的 settings.notification_command 覆盖 Loop 的 `$notifications`。它是通用 argv 数组，由 start_run 或全局 change_settings 设置；空数组沿用 Loop 默认。首次发送时固定发送实现，重试保留原目标；没有配置过发送实现的失败可补配后重试。通知载荷不包含内部执行 token/发送命令。已配置发送实现时，Engine 进入完成终态生成一次完成通知；用户主动 terminate 不生成成功通知。


## 明确的执行生命周期

候选实现的 `lifecycle` 保存初始状态和 `{from,event,to,when?,parameters?}` 转移表。构建工具为新候选填入可编辑的模板，Engine 派发时固定该候选及转移表，网页从同一份定义显示执行阶段、附属监控和矩阵。已有 Run 的执行快照不跟随草稿变化；省略 lifecycle 的当前候选使用该 kind 的默认状态模板。

`report_task` 是脚本、监控和 Agent 的统一事件入口。权限与版本校验后，由状态机匹配转移；completed 同时验证和提交所有结果，Agent 通过 report_task 提交；命令脚本可通过报告工具或当前 JSON stdout 契约提交。任务状态仍表达输入、操作权、派发、暂停与结束；执行的 lifecycle_state 表达作者定义的执行阶段，二者在界面中分别可见，不把监控轮询当作新的业务 Task。

转移记录含来源、时间、前后状态、事件、命中规则与进度/原因。未覆盖的转移保留原执行阶段并将任务标记为需要处理，依显式 fallback_node 进入既有兜底。检查失败保留最后已知外部状态并暂停监控；恢复沿用 external_id。已提交结果不因进程后来退出而撤回。没有完整交付的进程退出、超时和恢复异常由平台记录；正常外部等待本身不构成异常。

接入示例和完整工具约定见平台 Skill 的 [报告说明](../skills/loop-anything-platform/references/run.md#unified-event-and-result-reporting)；作者可封装工具。状态与异常记录可用于后续优化分析，本次没有引入自动改写 Loop 的机制。


恢复仍属于同一矩阵：分支条件可读取 Engine 提供的 attempt；必须唯一匹配。retry 固定待应用参数并保存在原执行中，Task 保持 retrying，待原进程确认结束且范围可写后，复用 change_task retry 原子应用并标记 applied；重启不重复应用。agent 进入既有显式兜底路径。查询失败仍恢复同一个外部任务的监控。改参受原有契约约束，执行快照保留；参数变更才增加 Task 修订，下游依赖不变。

## 稳定任务引用

模板步骤可声明 Run 内唯一 ref；输入的 task_ref/task_refs 和 after_refs 在写入时解析为既有 record/records/after。报告的所有 routes 批次共同解析，允许该报告内前向引用；单次 build_plan 可引用当前 Run 或该批任务。缺失、重复、未知端口及循环均拒绝，不创建占位或另设任务组生命周期。refs 保留在 Task spec，resolve_refs 和构建回执提供映射。

参数契约和验收入口见 [contracts.md](../skills/loop-anything-platform/references/contracts.md) 与 [testing.md](../skills/loop-anything-platform/references/testing.md)。


### 接续与精确观察

暂停与继续沿用同一个 Run；暂停停止平台派发新的业务执行，不自动冻结已启动的外部训练。结果、状态、待办和自动推进规则保留，恢复后由原调度器继续。新 Run 接续也使用同一套正常推进逻辑，原执行仅通过既有结果回填入口交回事实，不另建恢复调度器。

同一个 Loop 版本接续时，已经完成的入口不重新执行，保留原运行设置、输入与暂停点记录；显式传入的新启动设置覆盖对应项。state 展示元数据不参与该判断。选择另一个 Loop 接续时，Agent 读取同一份目标、限制和业务状态，根据新方法补充所需信息、安排新任务。已安排的任务保留原节点的输入、实现、结果契约、资源和推进规则。新安排的任务按所选 Loop 的定义执行。

等待来源 `kind: run` 表示整项工作，平台沿其 Timeline 观察当前 Run，后续再接续也无需改写引用。`kind: task` 表示指定任务，只读取该任务实际提交的精确结果版本。旧 Run 对外显示“已接续”，原观察器仍可收取在途结果，但不能安排新工作。被调用的子 Loop 也沿同一 Timeline 判断完成，不重复启动子任务。

保留任务的 Skill、手册和执行资产从原安装包读取，不另外保存资源镜像。已派发任务沿原执行实际读取的输入版本；其余既有输入逐项固定版本，尚未产生的输出固定生产者的目标版本；原 Run 启动参数保留为已安排任务的输入。接续代理复用原执行精确结果。当前 Run 仍在等待的原执行可以完成已授权的状态和结果报告，但不能安排新工作。

Agent 按需读取目标、限制和状态后工作。Auto Research 通过 `complete_research_decision.py` 一次提交业务状态、正式结果和任务安排；不再保存读取快照，也不要求提交时证明判断未过期。


普通任务上下文不默认携带全局业务摘要；需要研究状态时显式读取 `read_timeline` 或分页 `read_business_state`，完整证据通过具体记录查询。读取不修改运行状态，也不构成后续提交的版本门槛。

保留任务按 Task 保存所选实现快照，同一节点选择不同候选的任务不会共用一个实现；后续接续直接复用原快照身份，不继续叠加名称和定义。
