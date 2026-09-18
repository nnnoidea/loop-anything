# 启动和操作 Run

本页由平台提供，只教通用工具。业务要求见 Loop 作者说明；处理节点任务时通过 `read_task` 读取该节点绑定的作者 Skill。已被唤醒的 Agent 使用现有 Run 和令牌。

## 从任意入口继续已有 Run

终端、微信、飞书里的 Agent 连接同一个平台实例，读取同一条 Timeline。Run 不属于聊天会话；换入口不新建 Run，也不要求读取之前的聊天历史。

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

把影响后续工作的已确认目标、约束和决定写入现有 settings、任务安排或任务结果，分别使用 change_settings、change_task/build_plan/add_task、complete_task；不要只在聊天里说“记住了”。无需另外维护一份跨入口摘要或复制全部聊天记录。通知接收位置独立于操作入口；换聊天不会自动更改它。

## 被平台命令唤醒时

平台执行用户提供的命令并向标准输入传入任务 prompt。根据其中的 Run、task_id 和 token 处理当前任务，遵守用户授权；无需新建 Run。Agent 的工具与模型配置由用户负责；未显式配置 timeout 时，平台不会按默认时限终止 Agent。

使用本 Skill 自带的 `scripts/call.py`，传入 prompt 提供的运行身份；如果其中有 `platform_url`，用 `--url` 指向该地址。

在 Skill 根目录执行；其他工作目录使用脚本绝对路径：

```sh
python3 scripts/call.py read_task --arguments '{"run_id":"RUN_ID","token":"TOKEN","task_id":"TASK_ID"}'
```

命令名可换为下文列出的运行工具，`--arguments` 提供对应参数。读取任务时会返回作者 Skill 与输入输出要求；结果用 complete_task 提交，最后 finish 释放操作权。无需导入平台模块或直接访问数据库。

### 一次调用怎样才算完成

1. 带本次操作令牌 `read_timeline`，确认 `read_only` 为 false；此时 `scope_task` 为 null 可操作全局，否则只可修改该 Task 及其后代。再 `read_task` 读取当前 `task_version`、`outputs` 中每个端口的契约、输入与作者 Skill。
2. 按作者要求完成工作。用 `add_task` / `build_plan` 安排后续工作，只表示创建任务，不等于提交当前任务的结果。
3. `complete_task`：带上刚读取的 `task_version`，一次提交当前任务的全部 `envelope.outputs`。只有工具返回 `ok: true` 才算写入成功；失败时按错误修正当前提交，不要重复创建后续任务。
4. `next_tasks`：检查自己范围内的任务和异常。完成本次任务、处理异常或用 `defer_task` 明确等待后，可将已安排的后续任务留给 Engine。不必清空任务列表；不要持有父任务范围等待子 Agent 启动，因为父子范围互斥。
5. `finish`：确认返回 `ok: true` 和 `finished: true` 后退出。它释放本次操作权，不会替你提交结果，也不代表整个 Run 已达成目的。终态见下文。

例如 `read_task` 的 outputs 只有一个名为 result 的字符串端口时，提交参数形如：

```json
{"run_id":"RUN_ID","token":"TOKEN","task_id":"TASK_ID","task_version":"读取到的版本","envelope":{"outputs":{"result":"实际工作结果"}}}
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
4. 入口选择 Agent 实现时，用 `complete_task` 提交完整 `envelope.outputs` 和讨论确定的 `envelope.settings`。遵循 read_task 返回的契约，不能凭空添加字段。入口结果在界面保留。若入口选择脚本实现，则由 Engine 执行，读取其结果，不代写脚本输出。
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
- 对每项可处理任务先 `read_task`，读取最新输入、输出契约及作者节点 Skill，再 `complete_task` 写入完整结果。结果当次生效；不能代写脚本、事件或审批结果。
- `read_plans` 查看模板，`build_plan` 提供 name、稳定 key、values。默认构建全部步骤；steps.<步骤>.skip=true 省略步骤，不产生假输出。显式提供被省略步骤的复用输入来源。
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

兜底是普通的已声明节点：read_task 返回其 Skill、输出契约及 origin 中的进入原因。处理当前问题后，用 complete_task 完成兜底任务自身，再 finish；已有全局 Agent 可一并处理。全局范围与其他 Agent 支线互斥，正常脚本仍继续。

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

通知通过本 Run 的 `notification_command` 发送；它是通用命令数组，与聊天入口独立。省略或清空该覆盖时沿用 Loop 的 `$notifications` 命令。纯终端使用不需要聊天桥接，个人聊天目标不写进共享 Loop 包。

配置方法与适配器契约见 [通知接口](notifications.md)。进度仍使用 notify Hooks，完成与连续失败暂停通知复用同一出口。用户主动终止不发送成功完成通知。更换聊天入口不会自动修改通知目标。

## Agent 异常退出与通知

平台启动的 Agent 命令退出后，若 Loop 仍异常且启用了兜底，会按同一操作权规则进入指定兜底节点并唤醒 Agent。未启用兜底则保留未处理问题，不自动挑选 Agent。初次失败加两次重试，连续三次后暂停并自动发出通知请求；支线转交兜底时继续计入初次失败，不重新计数；异常成功解决后清零，用户明确恢复后开始新的计数。
用户明确暂停或等待用户输入不作为失败。旧命令不能确认已经停止时保留操作权，使用现有确认停止恢复入口；交互 Agent 同样须先确认旧进程停止，再通过该入口恢复。

通知使用上述通用出口。非零退出、超时或未确认送达都会记录失败；未配置发送命令也会明确记录未送达，不假称已经通知成功。
执行前通知与业务运行并行；执行前暂停拦住目标 Task，直到放行。普通通知默认调用用户发送命令；`route: workspace` 可明确选择仅在工作台留存。

不同支线的失败计数分别保留，进入全局兜底后沿用未解决支线的最长失败链，不把并行支线的失败次数相加；恢复运行会清零这些计数；一个 Agent 退出不会释放其他 Agent 的操作权。无法确认旧进程停止时保留它的范围，重叠范围不得启动第二个 Agent。
