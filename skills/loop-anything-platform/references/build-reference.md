# 构建工具与接入契约

构建时先读 [build.md](build.md) 的能力映射。本文件保留具体字段与接入步骤，按当前操作查阅；工具参数以运行中服务的 list 为准。

按需定位：[基础编辑](#基础编辑) · [节点 Skill 文件](#作者-skill-的文件与引用) · [条件步骤](#可选步骤满足条件才安排) · [脚本封装](#给运行时-agent-提供简洁入口) · [结果展示](#结果的通用展示) · [修改与参数契约](#修改既有设计) · [并行范围](#并行支线与全局决策) · [生命周期与重试](#执行生命周期与附属监控) · [等待节点](#平台等待节点) · [运行级检查](#运行级验证)。

## 基础编辑

- **开始或复用**：`list_loops` 找现有资产；`read_loop` 读它的实际定义。`create_loop` 建立草稿与通用入口；`copy_loop` 从已安装版本复制为草稿；普通修改传 new_version:true，保留 Loop ID 并自动选择后续版本，原有 Run 不变；只有用户要另建一个 Loop 时才使用普通复制。
- **业务说明**：`set_loop` 写入作者提供的 `handbook`、用途说明、初始输入默认值或明确的运行限额。平台 Skill 不维护这些业务内容。
- **节点**：`put_node` 写一个节点的职责、端口和可选作者 Skill。用 `skills: [{"name":"方法名","content":"作者提供的业务方法"}]` 直接绑定到该节点；Agent 读取节点任务时会获得这些内容。端口列表使用 `name` 加 `type`，嵌套契约使用 `schema`；工具生成输出记录类型。节点机械完成约束统一用 assertions 表达，例如 eq 比较字段值；不从约束自动填业务结果。入口端口变更会同步其初始位置。
- **可复用批次**：`put_step` 将节点加入一个命名模板。可用 implementation 指定模板选用的候选 ID，通常留给 Run 或任务选择。用 `plan_parameters` 声明运行时参数；`each` 指向参数里的列表。`connect_steps` 把上游 output 连到下游 input，`collect:true` 表示收集全部展开结果。
- **初始或复用输入**：在 `put_step.inputs` 中使用 `{"record":"initial.result"}` 等明确来源。入口的真实输出位置由 `read_loop` 返回，不猜名字。普通参数值用 `literal`；运行时替换值可以写 `{"literal":{"$":"values.参数名"}}`。列表元素对应 `item`。
- **候选实现**：`set_implementation` 提供 node_id、implementation_id 和 agent、command、external、event、timer 或 approval 配置。同一节点可多次添加不同 ID；default:true 选为 Loop 默认，default:false 取消该候选的默认地位，省略则不改默认。已存在的候选可只传 ID 与 default 调整默认。填写实际命令参数列表。外部任务还需 observe；删除指定候选时用 unbind:true，不能伪装成模拟实现。`put_asset` 把作者编写的脚本/文档附进包。
- **可选兜底**：与用户明确是否需要 Agent 兜底。需要时用 `put_node` 添加一个非入口节点，`inputs: []`，编写处理未覆盖状态的职责并绑定作者 Skill；通过 `set_implementation` 提供 Agent 候选，再用 `set_loop` 的 `fallback_node` 指定节点 ID。不需要时传空字符串关闭。兜底通过 Run 工具读取问题，使用同一套节点提交；不要自动挑其他节点的 Agent。
- **通知**：在生命周期转移的 notify 数组中配置消息/询问，或由脚本、Agent 调用 notify；使用 default 路由。使用者在平台配置实际出口并在 Run 中选择，详见 [notifications.md](notifications.md)。
- **结束条件**：作者说明完成目的与判定依据，运行时 Agent 把机械规则或终止信号写入 Timeline；不要给节点添加 terminal 标记。
- **Agent 命令**：用 `set_implementation` 设置 kind="agent" 和用户提供的 command，例如 `["codex", "exec", "-"]`；cwd/timeout 按实际需要明确设置；Agent 留空 timeout 时不限时，脚本命令默认 60 秒。平台向标准输入传入任务 prompt，原样执行命令；模型、工具和权限沿用用户配置。无需专用启动器或工具注册。
- **检查与交付**：`validate_loop` 检查结构并单列缺失实现。修正错误后继续保存草稿；用户要求本机可用版本或启动该版本时，`publish_loop` 安装为一个版本，auto_version:true 自动管理版本并复用相同内容，返回最新 draft_id/revision；`export_loop` 导出包含附件的包，客户端 `--output 文件.loop.zip` 保存它。

新建 Loop 默认提供无输入、无强制输出的 Agent 入口。用户与 Agent 讨论后，Agent 通过 start_run 接管入口，将目标、要求和约束写入完成报告的 settings，再按需安排任务并 finish。无需把对话复制到 request 表单，也不需要人为生成一条初始化结果；业务确需输入或共享初始结果时，用 put_node 明确添加端口。没有 command 的 Agent 候选由当前用户 Agent 操作；自动唤醒仍需配置用户选择的 Agent 命令。

每次编辑带上 `draft_id` 和刚返回的 `revision`。出现版本冲突，重新 `read_loop` 后再决定修改，不盲目覆盖。工具返回当前验证结果；未完整连接的草稿可保存，但必须修正结构错误才能发布。

## 作者 Skill 的文件与引用

作者已有完整 Skill 目录时，保留 SKILL.md、references/ 和 scripts/ 的相对结构，用现有 `put_asset` 将各文件附进 Loop 包；本地打包也可使用已有的目录附件能力。

- Loop Skill：`set_loop` 的 `handbook_path` 绑定包内入口，例如 `skills/research/SKILL.md`。可同时保留 handbook 简介；空字符串清除文件绑定。
- 节点 Skill：`put_node` 的 `skills` 使用 `[{"name":"评审方法","path":"skills/review/SKILL.md"}]`。原有 content 正文方式继续可用。
- 发布前 `validate_loop` 会检查绑定的入口文件已附入包。引用资源由作者完整附入，不自动扫描或改写 Markdown。

安装后 `read_loop` 返回 Loop 和节点 Skill 的 `resolved_path`；运行中 `read_timeline` 返回 Loop Skill 的该路径，`read_task` 返回对应节点 Skill 的该路径。Agent直接读取文件，以其所在目录解析 references/、scripts/ 等相对引用。`path` 是包内绑定，`resolved_path` 是读取结果，不写回 Loop 定义。

## 事件触发任务

作者先定义 plan，再用 `put_node` 的 `routes` 绑定源节点。省略 routes 保留原值，传数组整体替换，`[]` 清除。以下绑定将研究结果的两组参数展开为两项实验及一个汇总任务；research 节点必须声明 requests 数组输出。

```json
{
  "draft_id":"实际草稿ID", "revision":12, "node_id":"research",
  "routes":[{
    "id":"run_experiments", "event":"completed", "plan":"round",
    "values":{"experiments":{"$":"outputs.requests"}}
  }]
}
```

对应的 round 模板：

```json
{
  "parameters":{"type":"object","properties":{"experiments":{"type":"array","items":{"type":"object"}}},"required":["experiments"]},
  "steps":{
    "experiment":{"node":"experiment","each":"experiments","inputs":{},"parameters":{"$":"item"}},
    "review":{"node":"review","after":["experiment"],"inputs":{"results":{"from":"experiment","port":"result","collect":true}}}
  }
}
```

运行时研究节点只需 `report_task(event=completed, envelope.outputs={requests:[...]})`。Task 参数由模板绑定，业务命令从 parameters 读取；不在领域结果之外再手写 Task ID、依赖或聚合列表。初始化节点也可配置 routes，在同一次报告中提供初始 settings 和业务结果。

| route 字段 | 含义 |
| --- | --- |
| id、event、plan、values | 必填：节点内唯一规则 ID、生命周期报告事件、已有模板名、模板参数对象 |
| each | 可选：报告上下文的数组路径，每项展开一个 plan；如 outputs.groups。空数组生成零批 |
| when | 可选：每项触发前计算的确定性布尔表达式；false 跳过本项，缺字段或非布尔值报错 |
| steps | 可选：与 build_plan 的 steps 覆盖一致，可映射输入、参数、implementation 或 skip |
| round | 可选：本批任务显示名称，支持字符串插值，例如 `{item.name}` |

值可用 `{"$":"outputs.requests"}` 保留原类型，字符串中可用 `{parameters.name}` 插值。上下文有 `inputs`、`outputs`（completed 报告的业务输出）、`parameters`、`settings`（初始化时含本次 settings）、`detail`、`attempt`、`task_revision`、`task.id`、`task.node`、`task.outputs`（输出目的位置）及 `transition.from/event/to`。each 每项另有 item/index；未设置 each 时 item 为 null、index 为 0。这里没有操作令牌，也不能读取任意 Run 内部字段。

`when={"path":"outputs.decision.again"}` 可按决策结果继续；`each="outputs.groups"` 搭配 `when={"path":"item.enabled"}` 可逐组判断。route.when 在映射参数之前求值，跳过项不要求提供后续字段；plan 内 step.when 仍只读本批 values，并在步骤的 each 之前计算。route 的 steps 在报告上下文中展开一次，取得的业务数据原样传给模板，不再次解释数据中的 `{...}` 或 `$`。直接 build_plan 的 steps 仍使用 values/item/index 模板上下文。steps 可以按映射值选择已声明候选、覆盖参数或省略步骤；被省略步骤的消费者必须有有效的替代输入。

只有**被当前执行生命周期接受的报告事件**才触发，Agent、command、external、timer、event 共用此规则。自定义事件须先在候选 lifecycle 声明合法转移，再从 report_task.detail 取参数；本功能不订阅任意系统事件。外部业务事件先由匹配的 event Task 接收，再以 completed 触发。

平台在原报告事务中校验全部匹配规则、批次及同一 envelope.tasks：参数、实现、任务预算、输出位置和依赖全部通过才提交结果与生成任务。任务属于源 Task 的后代；routes 自身就是作者声明，不依赖脚本的 plan_nodes 权限。循环可生成新 Task，但具体任务依赖不能成环。

失败不留下部分生成的 Task：工具调用报错后可修正参数重报；脚本/定时器走已有错误报告路径，外部事件保留拒收信息；平台生成的错误事件如果自身触发规则也无效，保留可见 fault，不重复陷入报错。相同 execution/report_id 和相同内容重复报告返回原回执，不再创建任务；同 ID 不同内容冲突，过期监控报告不触发。

回执 `routes` 列出规则 ID、模板、batches（批次 ID、Task IDs、模板省略原因）及 omitted_items（条件为 false 的序号）。Timeline 记录 route_fired，每个 Task origin 含源 execution、route_id、report_id、plan 和 batch_id。没有规则的节点沿用原行为；不要在 helper 中再次创建这些后继。现有 Run 固定原定义，修改并保存 Loop 只影响新 Run。

## 可选步骤：满足条件才安排

参数映射可以直接写进模板：`put_step.parameters={"$":"values.options"}` 将本批 values.options 对象作为 Task parameters；逐项展开时也可引用 item。调用时可用 steps.<step>.parameters 覆盖少量字段：先展开模板参数和本次覆盖对象，再按顶层字段合并，本次值优先、嵌套对象整体替换。两者都必须解析为对象。无需 helper 逐字段搬运。each 使用相对于 values 的列表路径（如 experiments）；模板内部的 `$` 引用使用 values/item/index 上下文。

`put_step` 可设置 `when`，使用已有确定性表达式，只读取本批 `values`。例如 `when={"path":"values.action.stages.prediction.enabled"}`：字段为 true 才安排，false 时不创建该步骤的任何 Task 或输出占位。`put_step` 省略 when 保留现值，传 `when={}` 清除条件；直接编辑定义时删除 when 字段即可。

条件在 `build_plan` 时判断一次，作用于整个步骤，在 `each` 展开之前判断；不读取运行时结果或单个 item，不是运行过程中重新判断的分支。缺字段、非法表达式、非布尔结果会报错，不能当作 false。显式 `steps.<步骤>.skip=true` 优先表示本次不安排。

若下游仍引用被省略步骤的输出，构建会拒绝，必须显式复用已有输入或同时不安排该下游。仅有先后依赖的步骤沿用原省略语义，不为省略项占位。安排预览和工具回执列出未安排原因。业务输出中名为 status 的字段不会改变平台 Task 状态。

## 给运行时 Agent 提供简洁入口

结果触发模板任务优先用 routes；只有业务入口适配或临时组合操作确有重复时，才封装为随包脚本。用已有 `put_asset` 添加脚本及其说明，通过节点 `skills[].path` 绑定说明入口；不需要注册新工具。Skill 内写清命令、参数、回执和出错后的处理，业务规则由作者负责。

封装调用同一个平台 HTTP 接口或 Skill 中的 `scripts/call.py`。从本次唤醒上下文取得实际地址、Run、Task 和令牌，不写死本机路径或另存一份 Timeline。后台节点使用 `platform_url` 并传 run_id/token；上下文提供 `tool_url` 时，按[限定工具入口](scoped-entry.md)调用，其接口已绑定身份，参数中不再传 run_id/token。Skill 的 `resolved_path` 可直接读取，其 references、scripts 路径相对该文件所在目录解析。

封装负责重新读取所需版本、检查每步回执，并返回实际提交结果。成组任务编辑可复用 edit_tasks 的预览与原子提交。结果报告和任务编辑之间的多次调用不是一个事务：例如 complete_task 成功后 build_plan 失败，不能直接从头重跑已结束的完成步骤。为安排使用稳定 key，保留已完成操作的回执，恢复时读取当前任务和计划并跳过已提交步骤。少量已知的后续 Task 可随完成报告的 envelope.tasks 一起提交；批量模板后继可通过 routes 与报告原子提交；独立工具调用按其实际边界恢复。完成任务仍需提交必需输出，最后释放操作权。权限范围、版本冲突和输出校验由平台照常执行。

Agent 候选支持 `prompt` 字符串，与 command 一起保存、分享；已有候选可用 `set_implementation` 单独修改 prompt，无需重填命令。例如：

```text
读取本次上下文中 skills 的作者说明，按说明使用随包脚本完成工作。
{{context}}
```

只有 `{{context}}` 会替换为 JSON；其他文本原样发送，没有隐藏追加指令。不填写 prompt 时使用平台默认；显式空字符串就是空提示词。默认内容引导使用作者入口，平台手册仅在直接操作通用工具时按需读取。后台上下文含 run_id、execution_id、task_id、token、scope_task、platform_url、platform_client、platform_guide、loop_key、handbook、node_id、instructions 和 skills。限定入口的额外上下文见[限定工具入口](scoped-entry.md)。

## 结果的通用展示

平台按结果结构提供文本、字段和表格展示，无需作者另建结果展示功能。可在输入输出 schema 中提供 `title`、`description` 解释字段，平台不识别业务字段名称。轮次由运行时 `round` 明确提供，没有轮次的 Loop 无需填写。

文件输出使用 `schema: {"type":"string","format":"file"}`，结果值填写实际文件路径。相对路径以该次执行的工作目录为基准；没有工作目录时以安装的 Loop 包目录为基准。文件必须位于该目录内。平台提供图片预览及文件访问；文件不存在时会报错，不把普通字符串当文件，也不复制或保存外部文件历史。要保留旧产物，请每次执行使用不同文件名。

## 修改既有设计

1. 用 `list_loops` 的 loop_id 对照已有版本和草稿；普通修改继续现有草稿。revision 和 updated_at 帮助判断哪份是当前工作，不因重开会话就复制新 Loop。
2. 定向读取需要修改的对象，带回执里的最新 revision 修改。没有筛选参数的 `read_loop` 仍返回完整定义，适合第一次了解整体结构。
3. 看修改回执的 `changes`：每项包含字段路径和实际 before/after；新增没有 before，删除没有 after。文件回执只列大小、执行权限及 content_changed，不重复输出整份正文。`validation.valid=false` 表示草稿尚未可发布，不代表本次草稿保存失败。
4. 修正 `validation.issues` 指出的路径，继续校验。errors 保留原文本；issues 定位当前首先遇到的结构问题，不声称一次列出所有错误。明确需要时才 publish_loop，原有 Run 不迁移。

定向查询在同一个 `read_loop` 中完成，传 draft_id 或已安装 key 二选一：

| 想读取什么 | 附加参数 |
| --- | --- |
| 一个节点及其实现、输出记录类型 | node_id |
| 一个候选实现（包括生命周期） | node_id、implementation_id |
| 一个任务构建模板 | plan |
| 模板中的一个步骤 | plan、step |
| 包内脚本或 Skill 正文 | asset_path |

返回 value 和 references，以及草稿的 draft_id/revision 或已安装 key。references 列出声明中可确定的引用位置，例如节点被哪些步骤使用、某步骤输出被哪些输入使用、Skill 入口和命令参数引用了哪个包内文件；它不解析脚本逻辑或 Markdown 内的间接引用。读取普通包文件使用 UTF-8 正文；二进制文件明确返回 encoding=base64。安装版本只读，修改通过其草稿进行。

例如只改已有实现的命令：

```json
{"draft_id":"草稿ID","revision":12,"node_id":"train","implementation_id":"local","command":["python3","scripts/train_v2.py"]}
```

`set_implementation` 只修改传入字段。即使重复传 kind，也保留未传的 prompt、cwd、timeout、lifecycle 等字段；编辑既有候选不暗中改变默认选择，切换默认用 default:true。清除可选配置用 `clear:["timeout","prompt"]`，不能同时清除和设置同一个字段；空 prompt 表示发送空提示词，clear prompt 才表示恢复平台默认提示词。

候选实现可声明可选的 `parameter_schema`（type 为 object），约束该实现接收的 Task parameters；节点的 parameter_schema 继续表达公共要求，同一份参数必须同时满足两者。read_loop 定向读取候选可查看契约。set_implementation 未传则保留，clear:["parameter_schema"] 明确清除。只做校验，不在服务端补参数默认值。

新增、批量安排、修改与重试任务按有效实现校验参数，选择优先级仍是 Task 指定、Run 默认、Loop 默认。后续切换 Run 默认实现时，未执行且不满足新契约的任务会等待修正，不会带错参数启动；已派发执行保留原契约。没有选定实现时仍允许安排任务，选定后再检查。兜底候选由平台以空参数创建，因此不能要求必填的私有参数，应通过 Timeline 工具读取上下文。

更改 kind 时明确提供新 lifecycle，或 `clear:["lifecycle"]` 使用该方式的初始模板。旧配置中不适用于新方式的字段也要明确清除，工具不会偷偷删除作者内容。例如 Agent 改同步脚本时，可清除 prompt 并设置真实 command。

集合字段约定保持简单：未传则保留，传入则替换该字段整体。put_node 的端口/Skill 列表、put_step 的 inputs/after、set_implementation 的 lifecycle 都遵循这一约定；先定向读取再修改，不把只提供一个元素误当作追加。单条连接可用 connect_steps 修改，不用重写其他输入。

包文件用 read_loop 的 asset_path 读取，再用 put_asset 的 content 写回；未传 executable 会保留已有权限。删除用 `put_asset(..., path="包内路径", remove=true)`，不同时传 content 或 executable。删除不级联删除节点和 Skill，草稿可暂时存在缺失引用，修正后再发布；检查 references 及作者脚本中的实际使用位置。

删除节点或输出时，保存草稿会清理本次失去最后一个输出引用的自动生成记录类型（节点ID.端口名）；共享类型保留，已发布版本和已有 Run 不变。validate_loop 的 unused_records 列出其他未引用类型；核对后可用 set_loop 的 remove_records 数组删除，工具拒绝删除仍被引用的类型。

模板输入未指定时保持缺失，不自动填空值。通过 read_loop 查看各步骤的输入来源，根据校验回执中的位置修正缺失或已删除的上游引用。校验只检查已声明的契约，业务是否还需要其他数据由作者判断。

`remove_step` 要求先处理消费者；删除模板最后一步前还须移除引用该模板的 routes，`remove_node` 要求先移除引用它的步骤。工具会拒绝仍被引用的删除操作；先修改关联再删除。持续更新同一草稿，用 publish_loop 更新可用版本；分享时才调用 export_loop。

循环自动生成通过节点 routes 声明；脚本主动安排范围通过 plan_nodes 声明，运行任务依赖仍不能成环。可缺实现地构建、分享、安装和创建 Run；实际执行时才检查实现选择。业务脚本和环境配置由作者提供，不自动修复路径或依赖。构建完成后按 [run.md](run.md) 操作 Run；编辑 Loop 定义与修改正在运行的 Timeline 是不同操作。


## 并行支线与全局决策

运行时 Agent 默认在自己的 Task 支线内规划后续工作；相同节点模板可以用于多个并行 Task。归属由 parent_id 表达，输入/after 只表达数据与执行依赖。公共汇总任务由共同上层安排，后续业务步骤仍使用已有节点和批次模板。

需要某个正常决策节点处理整个 Run 时，通过 set_loop 的 global_agent_node 指定该节点，并提供 Agent 候选实现；初始化与兜底任务也具有全局范围。不要让普通节点靠改写同一全局记录协同，应输出各自结果再明确汇总。


## 执行生命周期与附属监控

状态保存和转移计算已分开：Timeline 保存事实、任务状态与历史，通用状态机按 lifecycle 计算转移，平台统一提交状态、结果与命中的后续安排。作者继续使用 set_implementation、routes 和 report_task；已有 Loop 无需迁移，不必编写独立的状态仓库或调用内部计算函数。waiting 的外部任务身份、观察时间及查询错误仍分别保存，不能仅凭状态名称判断是否正在正常观察。

同步/异步由候选实现决定，同一节点可切换实现。`set_implementation` 保存候选时会填入明确的 `lifecycle: {initial, transitions}` 初始模板；`read_loop` 可查看，通过 set_implementation 更新转移矩阵。模板不是业务决策。没有 lifecycle 的旧包保留原文；查看时展示对应初始模板，派发时将实际规则保存到执行快照。

转移行是 `{from, event, to}`，同一状态/事件可以有多行，但每行必须声明不同的 `when` 条件，运行时必须恰好命中一行；不按行顺序选择。`when` 使用现有确定性表达式，读取 inputs、parameters、settings、detail、outputs、attempt（执行次数，从 1 开始）和 task_revision。状态和事件 ID 使用字母、数字、下划线或连字符。`initial` 指定执行开始时的阶段；completed、fault、retry、agent 是本次执行的出口，不能作为普通阶段继续向外转移。retry 会让同一 Task 开始下一次执行；agent 交给运行已配置的兜底 Agent，未配置时保留异常。进入 completed 只能报告 completed 并一次提交全部输出，通过节点的输出和 assertions 校验。生命周期状态表示这次执行的阶段；任务仍可能在执行之前等待输入、权限或暂停点。

同步脚本一般使用 executing → completed/fault。external 将提交与检查绑定在一个候选里：command 提交工作，observe 是它的附属监控，接收同一 external_id；每次检查沿用同一任务和执行记录。用 report_task 报告 submitted、progress、completed 或 failed。监控进程失败由平台报告 check_error，默认保留最后的外部状态并停止检查、暴露异常；处理后恢复监控，不重复提交外部工作。作者可添加业务阶段和事件，但平台不会猜测缺失的转移；未覆盖的报告保留原状态及事件，进入明确的异常处理路径。

`process_error` 来自平台检测的未完成交付、非零退出、超时等。已成功提交的结果不会因后续进程退出而撤回。权限、版本、输出校验和进程存活保护始终有效，不能通过编辑矩阵绕过。正常等待不自动判为失败。未启用 fallback_node 时只展示问题；启用后仍按既有范围和三次失败规则处理。

脚本接入工具的用法见 [run.md](run.md#统一报告事件与结果)。作者可封装调用；业务事实与结果仍需真实验证。历史记录用于分析失败原因和后续优化建议，不会自动改写 Loop。


### 在矩阵中声明恢复

`to: "retry"` 使用原 Task 重试，不新建业务任务。可选 `parameters` 对象覆盖列出的顶层参数字段，其余参数保留；嵌套字段值整体替换，沿用模板已有的 `$` 路径引用。平台先按节点和有效候选校验完整参数，再记录匹配结果；真正重试时再检查当前契约和运行限额，在同一事务中应用参数、Task 修订与重试记录。原参重试不增加修订。

次数条件使用已有表达式，例如 `{"op":"le","args":[{"path":"attempt"},2]}` 表示前两次执行；其余分支可用 ge 3。未设置条件的既有 failed → fault 不会自行变成自动重试；要加分支时，应修改该事件原有行，避免与无条件行重叠。retry 与 agent 在候选矩阵和运行详情中直接显示。

下面是修改**已有同步脚本候选**的完整参数示例：第 1 次执行报告 failed 时原参重试，第 2 次将 batch 改为 8 后重试，第 3 次及以后交给已配置的兜底 Agent。batch 只是示例参数，须替换成作者实际允许修改且满足参数契约的字段和值；不默认启用这套策略。

先用 `read_loop` 传 draft_id、node_id、implementation_id 读取候选，确认 kind 为 command，并取得最新 revision。将以下 JSON 保存为 `recovery.json`，替换草稿 ID、revision、节点与候选 ID；已有 command 等未传字段保持不变。

```json
{
  "draft_id": "实际草稿ID",
  "revision": 12,
  "node_id": "train",
  "implementation_id": "local",
  "lifecycle": {
    "initial": "executing",
    "transitions": [
      {"from": "executing", "event": "progress", "to": "executing"},
      {"from": "executing", "event": "completed", "to": "completed"},
      {"from": "executing", "event": "process_error", "to": "fault"},
      {"from": "executing", "event": "failed", "to": "retry", "when": {"op": "eq", "args": [{"path": "attempt"}, 1]}},
      {"from": "executing", "event": "failed", "to": "retry", "when": {"op": "eq", "args": [{"path": "attempt"}, 2]}, "parameters": {"batch": 8}},
      {"from": "executing", "event": "failed", "to": "agent", "when": {"op": "ge", "args": [{"path": "attempt"}, 3]}}
    ]
  }
}
```

在 Skill 根目录调用；其他目录使用 scripts/call.py 的绝对路径：

```sh
python3 scripts/call.py set_implementation --arguments @recovery.json
python3 scripts/call.py validate_loop --arguments '{"draft_id":"实际草稿ID"}'
```

确认修改回执 `ok: true`、校验 `valid: true`，再定向 read_loop 核对保存的 lifecycle；下一次编辑使用修改回执中的新 revision。此操作只保存草稿，不会发布、启动或改变已有 Run。

`attempt` 是同一 Task 的总执行次数，不是连续失败计数；改参重试保留 Task ID 和下游引用，参数确实变化时增加 Task 修订。`agent` 需要作者显式配置 fallback_node 及可用的 Agent 候选，否则保留异常等待处理。示例只对主动报告的 failed 分支重试；漏报、非零退出等 process_error 保留 fault，仍按原有兜底设置处理，不应被误认为已命中上述次数分支。

注意 lifecycle 是整体替换。修改已有矩阵时保留其他业务阶段和转移，只替换相关的 failed 行；异步 external 不直接套用上述 executing 矩阵，应在读到的 submitting/waiting 矩阵上修改实际业务失败所在状态，保留 submitted 和 check_error 等行。

同一事件零条命中、多条命中、条件求值失败或重试参数不合法，均保留为明确异常，不擅自选择分支。`process_error` 可进入 fault/retry/agent，但进程未确认停止时禁止自动重试。`check_error` 只代表监控查询失败，不允许借此进入 completed/fault/retry 或重提外部工作；可以显式转到 agent，让已启用的兜底 Agent 检查。恢复监控仍沿用原 external_id，并回到转交前的监控状态。

接入前把 observer 会报告的事件与 lifecycle 的 from/event 对齐，同时覆盖平台产生的 process_error 和已提交 external 的 check_error。重试和等待上限按用户约束或外部系统已确认的故障条件设置；排队或运行耗时本身不等于失败。

重试等待上一进程退出和操作范围可写，暂停期间不执行。等待期间可由持权操作者明确接管重试或取消；原待应用转移随之失效。进程已确认结束的待重试动作会在重启后继续；重启时进程结局未知则标明原因，核实后通过已有 retry 工具恢复。调度复用现有限额，Agent 异常退出的三次暂停与通知机制继续有效。

监控到达 completed、fault、retry 或 agent 后，本次监控停止。已经在途的报告可能收到 `stale: true, accepted: false`：平台只保留证据，不改变任务、结果或失败次数；不要为此安排新 Task 或重复提交外部工作。

通过 `set_loop.fallback_node` 配置兜底节点，再用 set_implementation 配置该节点候选；Run 选用关系遵循现有绑定契约。未配置命令的 Agent 只能等待外部接管，不能自动唤醒。运行前检查会列出实际工作目录、程序/脚本缺项及 Agent 信任/登录未验证项；作者应在该目录确认 Agent 可以非交互运行。平台不会自动切换 cwd 或修改信任设置。

## 平台等待节点

通过 put_node + set_implementation 添加时间或事件等待，不需要守候脚本或常驻 Agent。

- 时间等待：`kind="timer"`，wait 提供且只提供 seconds 或 until。seconds 是等待秒数，until 是带时区的 ISO 日期，例如 `2026-10-01T09:00:00+08:00`。相对时间从本次 Task 开始等待时计算，期限保存后重启不重算。一般没有业务输出；若节点声明输出，显式配置 wait.outputs。
- 事件等待：`kind="event"`，event 为事件名称；wait.key 为关联标识，省略时沿用 Task parameters.event_key。可填 wait.timeout 作为最多等待秒数。收到匹配事件后，以 payload 作为节点全部输出，按原契约检查并提交。事件可先于等待到达；同一个事件只被一个等待执行消费。
- wait 支持原有 `{parameters.name}` 或 `{"$":"parameters.name"}` 引用。回复事件名称、关联标识和输出结构需与询问一致。
- 超时产生 timeout 事件，初始矩阵进入 fault；作者可在同一矩阵中改为重试或交给 Agent。取消等待不启动外部操作；下游是否改选输入仍由明确安排决定。暂停期间不推进，恢复时依据原期限处理。

示例为通用工具参数，不包含业务方法：

```json
{"draft_id":"DRAFT_ID","revision":1,"node_id":"wait_reply","kind":"event","event":"reply","wait":{"key":"{parameters.question_id}","timeout":86400}}
```

使用真实的草稿 revision；先声明该节点的输出契约。需要完成后通知时，在它的 completed 转移行加入 notify；通知内容和具体输出字段由作者定义。


## 运行级验证

`validate_loop` 和静态 `smoke` 不执行候选。需要验证安装后的 Agent 启动及 external 生命周期时，显式调用 `smoke_runtime(key, node_id?, implementation_id?, timeout?, cases?)`。它会按实际 argv/cwd 启动选定 Agent（可能调用模型，默认每个检查最多 30 秒），并在临时 Timeline 中模拟 external 报告、重复报告及重试后的 check_error；不会启动真实外部业务或修改已有 Run。省略选择器时检查全部候选，包括兜底。

有条件的状态转移用 cases 提供 node、implementation、state、event，以及需要的 attempt/parameters/inputs/settings/detail/expected。检查仅验证给定样例，业务输出契约及外部服务仍需验收。unknown 不表示成功，ready 仅表示没有已知失败，verified 表示全部项目通过。包损坏时不执行命令。命令行入口是 `smoke-runtime <key> --node <node> --implementation <id> --timeout 30 --cases cases.json`。

## 进一步的构建工具

条件参数、稳定 Task/输出引用、validate_parameters 和 preview_plan 的完整契约见 [contracts.md](contracts.md)。隔离流程验收 test_loop 及 set_loop.scenarios 的示例见 [testing.md](testing.md)。read_capabilities 可发现这些能力及其他已有机制。

导出时自动根据 routes、扩展 schema、稳定引用、scenarios 和 requires 计算包能力要求。使用新能力的包采用 package/2，旧服务会明确拒绝；普通旧包继续使用 package/1。requires 可显式追加能力要求。安装、导入草稿、复制和再次导出会保留包级要求；未知包格式会明确拒绝，不自动降级。更新运行服务后需重新读取实际工具目录；源码修改本身不代表服务已升级。
