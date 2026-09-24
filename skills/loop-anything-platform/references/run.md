# 启动和操作 Run

本页是直接使用通用工具的参考，不是运行时必读流程。作者已提供封装时，按其节点 Skill 操作；封装内部仍调用这些工具。业务要求见 Loop 作者说明；处理节点任务时通过 `read_task` 读取该节点绑定的作者 Skill。已被唤醒的 Agent 使用现有 Run 和令牌。

## 查看任务推进还是执行阶段

read_timeline/next_tasks 用于查看任务是否已安排、为何等待和哪些问题需处理；read_task 的 execution_state 与 last_transition 用于查看当前执行的阶段、报告和实际转移。任务的 status 与执行的 lifecycle_state 属于这两个层次，不能相互替代。

网页任务关系图展示当前 Task 及依赖；选中 Task 后查看关系与等待原因，再从执行记录选择某次尝试，查看该次参数、实现、生命周期和转移历史。重试保留原 Task，新一轮安排产生新 Task。完成报告提交结果后，平台重新检查已有下游任务；finish 只释放 Agent 操作权。

## 从任意入口继续已有 Run

终端、网页、微信、飞书里的 Agent 连接同一个平台实例，读取同一条 Timeline。Run 不属于聊天会话；换入口不新建 Run，也不要求读取之前的聊天历史。

1. 已知 Run ID 就直接读取；否则用 `list_runs`，可传 query 按名称、Run ID、Loop 名称或目标筛选，或传 status 按运行状态筛选。返回列表按创建时间从新到旧；多个候选无法区分时请用户选择，不猜测“最近一个”就是目标。
2. 无需 token，调用 `read_timeline` 查看最新目标、要求、指导、授权、记录索引、任务和异常。需要时用 `next_tasks`、`read_task`、`read_record`、`read_plans` 读取详情；完整事实和变更历史由 `read_run` 读取。查看状态不取得操作权，其他 Agent 可以继续工作。
3. 需要修改时调用 `acquire_run`；全局修改不带 task_id，只修改某支线则带对应 task_id。使用这次返回的新 token，不从旧会话复制令牌。范围冲突时可以继续读取，但不能抢占或声称修改已生效。
4. 取得操作权后重新 `read_timeline` / `read_task`，按最新版本落实用户要求，再 `finish` 释放操作权。既有执行记录和结果保留；改变目标不自动作废旧任务，由用户决定具体调整。

```sh
python3 scripts/call.py list_runs --arguments '{"query":"研究","status":"running"}'
python3 scripts/call.py read_timeline --arguments '{"run_id":"RUN_ID"}'
python3 scripts/call.py acquire_run --arguments '{"run_id":"RUN_ID"}'
```

`read_timeline` 返回 `read_only: true` 时只是查看，不授予写入权；此时 scope_task 的 null 不能理解为有全局权限。带有效 token 读取时，`read_only: false`，scope_task 才表示本次操作范围；写入仍受 Run 终态及已派发任务的保护。显式传入过期或错误令牌会报错，不会默默切成只读。

把影响后续工作的已确认目标、约束和决定写入现有 settings、任务安排或任务结果，分别使用 change_settings、change_task/build_plan/add_task、report_task；不要只在聊天里说“记住了”。无需另外维护一份跨入口摘要或复制全部聊天记录。通知接收位置独立于操作入口；换聊天不会自动更改它。

## 在网页对话中操作

网页 prompt 提供 `tool_url` 时，所有调用都用这个地址覆盖 `--url`，先 `list` 查看本次可用工具。这个入口已绑定所选准备页或 Run，并代管本次 token；参数中不传 run_id 或 token；`acquire_run` 也不传 task_id，操作范围由网页选择。`read_task` 等任务工具仍需具体 task_id。下文普通终端示例中的 run_id/token 应省略，不能换回默认平台地址绕过范围限制。

- 启动前：`read_loop` 读取作者说明，`read_preparation` 读取页面选项与 revision。讨论确定的输入和候选用 `change_preparation`（revision、change）保存，用户会看到更新；不会因此执行业务工作。
- 用户明确要求启动时：`start_prepared_run`（revision）创建并取得同一个 Run 的操作权，返回 run_id、entry_task_id。再次 `list` 获取运行工具，然后按入口契约初始化并安排工作，最后 `finish`。脚本入口交给 Engine 执行。普通讨论不调用启动工具；启动后不重新创建 Run。
- 运行中：只读工具直接读取最新 Timeline。需要写入才 `acquire_run`，范围由用户在网页中选择；取得后重新读取版本再改动，完成后 `finish`。冲突时告知用户，不能抢占其他 Agent。

最终标准输出作为网页回复；业务结果仍必须由工具提交。网页对话记录保存在本机，其他入口仍通过 Timeline 获取已确认的业务事实。网页 Agent 的命令、目录、超时和唤醒提示词单独保存在本机，修改它不改变节点的候选实现。每条消息重新调用一次命令；当前回复在命令退出后整体显示。

## 被平台命令唤醒时

平台执行用户提供的命令并向标准输入传入任务 prompt。根据其中的 Run、task_id 和 token 处理当前任务，遵守用户授权；无需新建 Run。Agent 的工具与模型配置由用户负责；未显式配置 timeout 时，平台不会按默认时限终止 Agent。

使用本 Skill 自带的 `scripts/call.py`，传入 prompt 提供的运行身份；如果其中有 `platform_url`，用 `--url` 指向该地址。

在 Skill 根目录执行；其他工作目录使用脚本绝对路径：

```sh
python3 scripts/call.py read_task --arguments '{"run_id":"RUN_ID","token":"TOKEN","task_id":"TASK_ID"}'
```

命令名可换为下文列出的运行工具，`--arguments` 提供对应参数。读取任务时会返回作者 Skill 与输入输出要求；结果用 report_task（event=completed）提交，最后 finish 释放操作权。无需导入平台模块或直接访问数据库。

### 一次调用怎样才算完成

1. 带本次操作令牌 `read_timeline`，确认 `read_only` 为 false；此时 `scope_task` 为 null 可操作全局，否则只可修改该 Task 及其后代。再 `read_task` 读取当前 `task_version`、`outputs` 中每个端口的契约、输入与作者 Skill。
2. 按作者要求完成工作。用 `add_task` / `build_plan` 安排后续工作，只表示创建任务，不等于提交当前任务的结果。
3. `report_task`（event=completed）：带上稳定的 `report_id` 和刚读取的 `task_version`，一次提交当前任务的全部 `envelope.outputs`。只有工具返回 `ok: true` 且 `accepted: true` 才算写入成功；失败时按错误修正当前提交，不要重复创建后续任务。
4. `next_tasks`：检查自己范围内的任务和异常。完成本次任务、处理异常或用 `defer_task` 明确等待后，可将已安排的后续任务留给 Engine。不必清空任务列表；不要持有父任务范围等待子 Agent 启动，因为父子范围互斥。
5. `finish`：确认返回 `ok: true` 和 `finished: true` 后退出。它释放本次操作权，不会替你提交结果，也不代表整个 Run 已达成目的。终态见下文。

例如 `read_task` 的 outputs 只有一个名为 result 的字符串端口时，提交参数形如：

```json
{"run_id":"RUN_ID","token":"TOKEN","task_id":"TASK_ID","task_version":"读取到的版本","event":"completed","report_id":"本次交付的稳定ID","envelope":{"outputs":{"result":"实际工作结果"}}}
```

端口名和数据类型必须使用实际契约；初始化任务还需要按 `settings_schema` 提交已讨论的 `envelope.settings`。无输出端口时提交空对象 `{}`。不要照抄示例创建业务字段。

仍使用同一个脚本调用 finish：

```sh
python3 scripts/call.py finish --arguments '{"run_id":"RUN_ID","token":"TOKEN"}'
```

每次命令都检查 JSON 中的 `ok`，失败时脚本退出码为 2；文字回复“已完成”不能替代成功回执。若请求超时、结果不确定，先读取当前状态确认哪些操作已生效，再决定下一步；不要盲目重交结果或改 key 重建任务。当前工具无需 seal。

作者 Skill 带 `resolved_path` 时，直接读取该位置的 SKILL.md，并以它所在目录查找其中的相对引用。Loop Skill 可由 read_loop/read_timeline 获取，节点 Skill 随 read_task 返回；普通文件读取和脚本执行沿用 Agent 自己的工具。

## 用户自己的 Agent 启动

1. 通过 `list_loops` 找到用户选择的 Loop，取得实际 key，显式传给 `read_loop`，了解所选 Loop 的作者说明、入口要求和节点实现，与用户讨论并确认目标和授权。
2. 调用 `start_run`，提供 `key`、`title`、已讨论的 `inputs` 和自然语言 `authorization`。返回 `run_id`、`token`、`entry_task_id`。当前 Agent 已取得操作权，Engine 不会抢先重复初始化。
3. 调用 `read_task`，带 run_id/token/task_id=entry_task_id，读取初始化要求和 `task_version`。
4. 入口选择 Agent 实现时，用 `report_task`（event=completed） 提交完整 `envelope.outputs` 和讨论确定的 `envelope.settings`。遵循 read_task 返回的契约，不能凭空添加字段。入口结果在界面保留。若入口选择脚本实现，则由 Engine 执行，读取其结果，不代写脚本输出。
5. 使用后面的当前任务与问题/构建工具继续处理，最后 `finish`。

已被 Engine 唤醒的 Agent 已有 Run 和令牌，跳过创建步骤；操作范围由 prompt 和 read_timeline 的 scope_task 确定。

## 支线归属与操作范围

- 持有效操作令牌时，`scope_task` 为任务 ID：可操作该 Task 及其后代；为 null：本次有全局操作权。普通节点的 Agent 默认负责自己的 Task 支线，入口初始化、兜底任务和明确配置的 `global_agent_node` 使用全局范围。
- `parent_id` 表示具体 Task 的归属，独立于输入来源和 `after`。两个任务即便使用同一 Node 模板，也可能是独立支线。读取兄弟支线结果不会获得修改权限。
- `add_task`、`build_plan` 默认将新工作挂到当前 scope_task；全局 Agent 默认挂到唤醒任务。可提供本范围内的 `parent_id` 指定父任务；全局 Agent 可传空字符串明确创建顶层任务。父任务关系建立后不更改，公共汇总应由上层创建，不能因依赖多个支线就归各支线共同修改。
- 普通 Agent 可调整自己支线内尚未执行任务的输入、参数、实现和依赖。全局设置、Run 暂停/结束及用户请求处理需要全局操作权。已派发任务保持保护。
- 同一 Run 的不重叠支线可同时运行，范围重叠时等待。`acquire_run` 不带 task_id 请求全局操作权，带 task_id 请求该任务支线；冲突时不能抢占。
- 完成本次唤醒任务并处理本范围的异常后可 `finish`，已安排的后续 Agent 任务可以交还 Engine 并行派发，无需在本次会话中全部做完。finish 只释放自己的令牌。

这些检查作用于平台工具调用；Agent 使用外部文件和服务仍沿用用户配置，不是操作系统隔离。需要并行修改文件时，由作者安排独立工作目录或明确串行依赖。

## 运行中的统一操作

- `next_tasks` 和 `read_timeline` 读取当前节点任务与异常、用户授权及作者整体说明。read_timeline 的 records 列出记录 ID、类型和最新版本，需要正文时用 `read_record`。正常运行或等待的脚本不需要 Agent 接管。
- 对每项可处理任务先 `read_task`，读取最新输入、输出契约及作者节点 Skill，再 `report_task`（event=completed） 写入完整结果。结果当次生效；不能代写脚本、事件或审批结果。
- `read_plans` 查看模板，`build_plan` 提供 name、稳定 key、values。默认安排无条件或 when 为真的步骤；steps.<步骤>.skip=true 明确不安排。省略不会创建 Task、skipped 占位或假输出，回执 omitted 与安排记录说明原因。需要其输出的下游必须显式提供复用输入来源。相同 key 重试必须保持参数与安排不变；不要用重复 key 隐式撤回已安排任务。已存在的任务不再需要时，明确取消，保留事实。
- 若作者的 Loop 有轮次，build_plan 可传 `round`，例如作者确定的轮次名称。它只组织显示，不强制串行、不控制何时推进；不要给没有轮次的业务强加轮次。
- `add_task` 从已声明的非入口节点安排单项工作：提供稳定 `key`、`node_id`、`inputs`，可选 `parameters`、`implementation`、`after` 和 `round`。返回任务 ID 与自动分配的输出记录 ID，供后续输入引用；不手写完整任务。
- `change_task` 修正尚未执行的 `inputs`、`parameters`、`implementation` 和 `after`（前置任务 ID 列表）；重试前先核实是否已经产生外部副作用。执行中的正常脚本不应被当成待修复问题。
- `change_settings` 修改已授权的要求；提供刚读到的 settings.revision。`command` 使用暂停、恢复、暂停点放行等已支持操作。
- 无法按现有授权解决时 `defer_task`，记录需要用户输入的具体事项。不要伪造成功或自行扩大授权。
- 每次写入后重新 `next_tasks`，本次任务完成且本范围异常已处理或明确等待后 `finish`。旧令牌立即失效，已安排的后续任务交给 Engine。

新增或修改任务造成循环依赖时，整次写入会被拒绝，不会留下部分任务或结果。读取最新任务及来源后修正；不要把循环的 Loop 定义误当成运行时同一批任务可以互相等待。

## 选择节点实现

候选与默认值在 `read_loop` 的 implementations 中；多候选保存为 `{options:{ID:配置}, default:ID或null}`。已有单个实现是名为 default 的默认候选简写。不要为更换候选复制 Loop。

- `start_run` 可带 bindings 映射，例如 `{"train":"cluster"}`。省略节点沿用 Loop 默认；值 null 暂不选用。
- 运行中 `change_settings` 的 change.bindings 更新 Run 选择，带最新 settings revision。映射整体替换，保留仍需覆盖的其他节点。
- `build_plan` 的 steps.<step>.implementation 为本批任务指定候选；空字符串恢复继承 Run 默认。`change_task` 的 implementation 改选未派发任务，或结合 retry 在确认副作用后切换失败任务的实现；空字符串恢复继承。
- 优先使用任务明确指定的实现，其次 Run 选择，再其次 Loop 默认。`read_task` 会返回候选、当前选择及 task_version；改选后重新读取再提交。

已派发的执行保留当时的实现与配置。候选为空或未设默认不阻止创建 Run；实际需要执行任务时才报告 missing_implementation。用工具落实选择，或明确等待用户提供实现，不伪造执行结果。

## 可选 Agent 兜底

`read_loop` 返回 Loop 的 fallback_node。`start_run` 可传 fallback_node 覆盖，空字符串表示本次关闭；省略沿用 Loop。运行中用 change_settings 的 change.fallback_node 设节点 ID 或 null。兜底 Agent 通过该节点的 bindings 选择，不会隐式借用其他节点命令。

兜底是普通的已声明节点：read_task 返回其 Skill、输出契约及 origin 中的进入原因。处理当前问题后，用 report_task（event=completed）完成兜底任务自身，再 finish；已有全局 Agent 可一并处理。全局范围与其他 Agent 支线互斥，正常脚本仍继续。

## 用户中途提出新要求

按上面的继续运行流程，先只读查看，再 `acquire_run` 取得操作权并重新读取最新状态，决定怎样落实用户要求。若有 Agent 持有重叠范围的操作权，需要等待，不自行抢占。修改要求本身不会作废旧任务、审批或结果。由用户决定哪些工作需要改变，再按授权用 change_task 明确取消或修改；必要时先暂停推进。待确认审批可以取消，已派发脚本不能靠取消假定外部操作已停止。保留已有结果和来源，再检查当前任务与问题并结束。

工具报错时读取 error 和当前状态：输入版本变化就重新 read_task；Timeline 版本变化就重新 read_timeline；缺字段按输出契约补齐。不要通过重复创建另一批任务绕过原错误，也不要重建 Run。

## 终态由 Engine 推进

用户目的在 Timeline 中。结束有两条路径，都用 `change_settings` 写入，由 Engine 推进到终态；任务查询不承担终态判定，也不生成结束判断任务。

- 可机械判断：写 `completion_rule`，使用现有确定性表达式。支持 eq/le/ge/add/len/and/or，`path` 可为点分隔字符串或路径段数组。求值根为 settings、inputs、records（每个记录 ID 的最新正式值）、completed（各节点已完成 Task 数）和 active_tasks（尚未结束的业务 Task 数）。and/or 按顺序短路；只有实际求值访问的记录尚未产生时规则才暂不成立；规则类型错误作为实际异常报告。
- Agent 已判断目的达成：写 `termination_signal`，内容为结束原因。Engine 识别后进入终态，保留原因与 Timeline revision。

例如已完成至少两次 review 且没有其他在途业务工作：

```json
{"completion_rule":{"op":"and","args":[{"op":"ge","args":[{"path":["completed","review"]},2]},{"op":"eq","args":[{"path":"active_tasks"},0]}]}}
```

使用真实节点 ID 和业务条件，不机械照抄。带点的记录 ID 用路径段数组，例如 `["records","metric.round-2","score"]`。
规则不应无意截断仍需完成的工作；若需等待在途工作结束，明确纳入条件。终态会取消尚未结束的 Task 并拒绝其后续提交，不撤销已发生的外部副作用。

没有 Task 不等于完成。`finish` 只释放本次 Agent 操作权；它不会直接把 Run 置为完成。已写入终止信号时可以交还操作权，随后由 Engine 执行终态转移。不要创建 terminal 节点或额外完成判断任务。

`set_loop.global_agent_node`、`start_run.global_agent_node` 或 `change_settings.change.global_agent_node` 可指定正常全局决策节点，选用该节点的现有 Agent 实现。留空默认使用兜底；设置该资格不会自动创造业务任务或启动 Agent。兜底触发仍要求显式启用。

## 配置通知出口

使用 read_notification_channels 查看平台已配置出口，在 start_run.notification_route 或 change_settings.change.notification_route 中选择本 Run 的默认出口。workspace 表示平台通知区。终端、网页和聊天入口共用该设置，切换聊天不会自动更换接收位置。个人发送配置只保存在平台与 Run，不放在 Loop 定义中。

通知、询问、回复和适配器参数见 [notifications.md](notifications.md)。Agent 调用 notify 时沿用当前操作权，支线关联自己的 task_id；不要为了发消息再安排一个业务 Task。重复请求保持 key 和内容一致。询问不会暂停其他工作，需要答案时安排等待节点，完成当前工作后 finish 释放 Agent，不持权守候。

read_task.execution_state.wait 显示实际等待时刻、事件关联和截止时间。网页能回复询问，也能在等待详情提交事件；其他入口通过 send_event 提交。使用稳定 event_id，回复的 payload 必须符合等待节点输出契约；重复事件不重复推进。时间和事件等待可通过现有 change_task cancel 取消，已完成输出不会被撤回。

## Agent 异常退出与通知

平台启动的 Agent 命令退出后，若 Loop 仍异常且启用了兜底，会按同一操作权规则进入指定兜底节点并唤醒 Agent。未启用兜底则保留未处理问题，不自动挑选 Agent。初次失败加两次重试，连续三次后暂停并自动发出通知请求；支线转交兜底时继续计入初次失败，不重新计数；异常成功解决后清零，用户明确恢复后开始新的计数。
用户明确暂停或等待用户输入不作为失败。旧命令不能确认已经停止时保留操作权，使用现有确认停止恢复入口；交互 Agent 同样须先确认旧进程停止，再通过该入口恢复。

通知使用上述通用出口。非零退出、超时或未确认送达都会记录失败；未配置发送命令也会明确记录未送达，不假称已经通知成功。
执行前通知与业务运行并行；执行前暂停拦住目标 Task，直到放行。普通通知使用本 Run 的默认出口；未选外部出口的新 Run 使用平台通知区。`route: workspace` 可明确选择仅在工作台留存。

不同支线的失败计数分别保留，进入全局兜底后沿用未解决支线的最长失败链，不把并行支线的失败次数相加；恢复运行会清零这些计数；一个 Agent 退出不会释放其他 Agent 的操作权。无法确认旧进程停止时保留它的范围，重叠范围不得启动第二个 Agent。


## 统一报告事件与结果

`report_task` 参数包含 task_id、event、稳定 report_id。Agent 先 read_task，读取实际生命周期、当前执行阶段及 last_transition，附带最新 task_version；脚本/监控使用本次上下文的 execution_id。普通平台入口还要传 run_id/token；网页 scoped 入口自动提供身份。completed 报告的 envelope 包含全部 outputs，初始化时还包含 settings；progress 等报告只带 detail，不提前发布结果或安排任务。

```json
{"task_id":"任务ID","task_version":"read_task返回的版本","report_id":"这次交付的稳定ID","event":"completed","envelope":{"outputs":{"result":"实际结果"}}}
```

检查 `ok=true` 且 `accepted=true`。工具接收了格式正确但未覆盖的事件时会返回 accepted=false，并保存原状态、事件和异常原因；先检查当前任务及规则，不盲目重试。网络回执不确定时用相同 report_id 和相同内容重试，不生成新 ID。相同报告不会重复产生结果；改变报告内容须使用新 ID。失效的执行或操作令牌始终不能再写入。

脚本从 stdin 读取 JSON 上下文，其中 report_client 是随平台 Skill 提供的 scripts/report.py 绝对路径。它可作为命令行工具调用，也可按该路径导入 `report`：

```python
import importlib.util, json, sys
context = json.load(sys.stdin)
spec = importlib.util.spec_from_file_location("loop_report", context["report_client"])
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
# 在业务工作完成并验证后，最后提交；不要仅凭进程退出判断业务成功。
client.report(context, "completed", report_id="final", envelope={"outputs": {"result": "实际结果"}})
```

也可调用 `python3 REPORT_CLIENT completed --context 上下文.json --data @报告.json`。作者可把接入封装进已有业务脚本，无需修改远端服务。

异步提交用 `submitted` 携带 external_id 和可选 poll_after 秒数；监控使用上下文中的 external_id，报告 progress（detail 中放进度）或 completed（envelope 中放结果），业务明确失败才报告 failed。查询失败与业务失败不同；查询脚本可以抛出异常交给平台记录 check_error。作者可以将 check_error 明确转到 agent，由已启用的兜底节点处理；未启用时保留问题。查询失败后用 change_task retry 恢复原外部任务的监控，并回到转交前的监控状态；此操作不能同时改变输入或实现。确认原工作失败且需要重新提交时，走正常任务重试并核实外部副作用。

旧 `complete_task` 仍作为 completed 报告的兼容入口；旧脚本的 JSON stdout 结果也汇入同一转移处理。直接调用工具后，stdout 可用于普通日志，回执以工具为准。完成任务不会自动释放 Agent 操作权，最后仍需 finish。


### 转移与重复报告

矩阵判断“当前状态＋事件”能否转移；同一次执行中的 report_id 识别是否为同一个逻辑事件。相同 ID、相同内容的并发或重试只确认一次，状态检查、结果写入、报告回执及完成 Hook 在同一事务中处理。相同 ID 却改变内容会被拒绝。程序重试一次发送时必须沿用原 ID；若每次生成新 ID，平台会将其视为新事件。

不要把矩阵行理解为整个 Run 只能命中一次：进度可以合法自循环；离开 A 后又进入 A，也可以再次使用 A 的出边。已离开 A 时，新事件只能匹配当前状态的规则，不能再次执行 A 的旧出边；已完成的任务拒绝新的状态报告。当前矩阵没有任意“状态进入动作”或通知配置，已有通知 Hook 按 Hook/Task 去重；如果业务需要每次重新进入都通知，不能靠持续观察“当前处于 A”反复发送。


### Task 修订与执行尝试

新 Task 的 revision 从 1 开始；修改其 inputs、parameters、implementation 或 after 才递增，原配置重试、恢复监控和无实际配置变化不递增。change_task 回执和 read_task 返回 task_revision；并发提交仍使用刚读取的 task_version，不能用整数修订号替代。

每次执行保存 task_revision、task_spec 及实际输入、参数和实现快照。原参数重试可以是修订 1 的第 2 次执行；改参后重试则是修订 2 的第 3 次执行。历史修改保留前后修订、配置、原因与可识别的操作者，不记录操作令牌。下游继续引用同一个 Task ID 和输出位置，不自动重建。

Run 默认实现或输入记录的变化不直接改写 Task 声明，因此不自动增加 Task 修订；执行记录另存实际选用的实现、运行设置修订及消费的记录版本。旧历史没有修订号时标为未记录，只从后续修改或新执行开始记录，不推算已有历史。


### 状态机安排的恢复

报告返回 state=retry 时，表示重试转移已记录，Task 处于 retrying，需等待进程结束及操作范围可写后才能应用。read_task 的 execution_state.retry 可查看 pending/applied/blocked/superseded 和已确定的参数。Agent 报告后仍需 finish 释放操作权；本任务明确转入 agent 时也可 finish，将该问题交还给已配置兜底，其他未处理问题仍须遵守原范围规则。

不要重复 add_task 代替重试。报告重放沿用同一 report_id 和内容，已应用的转移不会再次改参或重提。服务重启后若标明旧进程结局未知，先核实它已停止及外部副作用，再用 change_task retry；平台不会自动冒险重提。自动恢复与手动操作共用 Task 修订、参数契约和操作范围。

监控报告返回 `stale: true` 表示旧检查已结束或凭证已被恢复/重试替换，报告只保留为证据。随 Skill 提供的 report.py 将其作为正常的过期回执返回；调用者应停止该旧检查，不再推进状态。错误凭证仍会被拒绝。

执行记录的 `failure_kind=command_start` 表示命令/工作目录无法启动，`agent_command` 表示 Agent 命令异常；它们不证明外部训练等业务失败。读取原始错误和实际 cwd，检查命令及 Agent 信任/登录配置，不擅自修改信任范围或重提外部任务。
