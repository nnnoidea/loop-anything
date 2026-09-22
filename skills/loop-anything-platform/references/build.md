# 构建 Loop

本 Skill 由平台提供，只教平台操作。业务目标、流程职责、决策规则和专业 Skill 由 Loop 作者提供；不能用平台示例代替作者的业务设计。

工具调用方式见 [平台 Skill](../SKILL.md)。先检查连接并用 `list` 读取实际工具参数；编辑带上最新 draft_id/revision。连接失败先处理平台地址或服务问题，不创建业务 Run 测试连接。

## 从作者意图到可用 Loop

先与作者明确任务、每步输入输出、哪些工作由脚本或 Agent 完成。不要替作者增加未要求的业务步骤。

按两层构建：先用 put_node 明确职责和端口，用 put_step/connect_steps 表达任务间关系，再用 set_implementation 选择实现及其执行生命周期。可先保留缺少实现的草稿。

- **任务关系与推进**：输入引用和 after 表达依赖，plan_nodes 声明可安排的后续工作。无依赖的支线可在权限与并发条件满足时并行；上游提交结果后，已有下游任务重新检查就绪条件。连线不自动创建任务，下一轮由 Agent 或脚本明确安排。
- **执行生命周期**：绑定在候选实现的 lifecycle 上，描述一次执行如何响应 report_task 的事件。同步脚本与异步提交/监控可以是同一节点的不同实现；先读取工具填入的可见初始模板，有特殊业务阶段或恢复要求时再编辑。

两层共用真实定义：不另写一份任务间转移表。retry 是原 Task 的下一次执行；再次安排业务工作创建新 Task。网页总览查看关系，选中节点展开候选的执行生命周期；运行中按 Task 选择具体执行记录。


- **开始或复用**：`list_loops` 找现有资产；`read_loop` 读它的实际定义。`create_loop` 建立草稿与通用入口；`copy_loop` 从已安装版本复制为草稿；普通修改传 new_version:true，保留 Loop ID 并自动选择后续版本，原有 Run 不变；只有用户要另建一个 Loop 时才使用普通复制。
- **业务说明**：`set_loop` 写入作者提供的 `handbook`、用途说明、初始输入默认值或明确的运行限额。平台 Skill 不维护这些业务内容。
- **节点**：`put_node` 写一个节点的职责、端口和可选作者 Skill。用 `skills: [{"name":"方法名","content":"作者提供的业务方法"}]` 直接绑定到该节点；Agent 读取节点任务时会获得这些内容。端口列表使用 `name` 加 `type`，嵌套契约使用 `schema`；工具生成输出记录类型。节点机械完成约束统一用 assertions 表达，例如 eq 比较字段值；不从约束自动填业务结果。入口端口变更会同步其初始位置。
- **可复用批次**：`put_step` 将节点加入一个命名模板。可用 implementation 指定模板选用的候选 ID，通常留给 Run 或任务选择。用 `plan_parameters` 声明运行时参数；`each` 指向参数里的列表。`connect_steps` 把上游 output 连到下游 input，`collect:true` 表示收集全部展开结果。
- **初始或复用输入**：在 `put_step.inputs` 中使用 `{"record":"initial.result"}` 等明确来源。入口的真实输出位置由 `read_loop` 返回，不猜名字。普通参数值用 `literal`；运行时替换值可以写 `{"literal":{"$":"values.参数名"}}`。列表元素对应 `item`。
- **候选实现**：`set_implementation` 提供 node_id、implementation_id 和 agent、command、external、event 或 approval 配置。同一节点可多次添加不同 ID；default:true 选为 Loop 默认，default:false 取消该候选的默认地位，省略则不改默认。已存在的候选可只传 ID 与 default 调整默认。填写实际命令参数列表。外部任务还需 observe；删除指定候选时用 unbind:true，不能伪装成模拟实现。`put_asset` 把作者编写的脚本/文档附进包。
- **可选兜底**：与用户明确是否需要 Agent 兜底。需要时用 `put_node` 添加一个非入口节点，`inputs: []`，编写处理未覆盖状态的职责并绑定作者 Skill；通过 `set_implementation` 提供 Agent 候选，再用 `set_loop` 的 `fallback_node` 指定节点 ID。不需要时传空字符串关闭。兜底通过 Run 工具读取问题，使用同一套节点提交；不要自动挑其他节点的 Agent。
- **通知实现**：用 set_implementation，node_id="$notifications"、kind="command"，绑定用户提供的发送命令。平台调用并记录送达状态。用户聊天目的地通过启动 Run 时的 notification_command 设置，见 run.md，不写死在共享 Loop 中。
- **结束条件**：作者说明完成目的与判定依据，运行时 Agent 把机械规则或终止信号写入 Timeline；不要给节点添加 terminal 标记。
- **Agent 命令**：用 `set_implementation` 设置 kind="agent" 和用户提供的 command，例如 `["codex", "exec", "-"]`；cwd/timeout 按实际需要明确设置；Agent 留空 timeout 时不限时，脚本命令默认 60 秒。平台向标准输入传入任务 prompt，原样执行命令；模型、工具和权限沿用用户配置。无需专用启动器或工具注册。
- **检查与交付**：`validate_loop` 检查结构并单列缺失实现。修正错误后 `publish_loop` 安装为一个版本，不启动；日常迭代可传 auto_version:true，在版本已存在时自动选用新版本，返回最新 draft_id/revision 和实际 version，原版本不被覆盖；`export_loop` 导出包含附件的包，客户端 `--output 文件.loop.zip` 保存它。

新建 Loop 默认提供无输入、无强制输出的 Agent 入口。用户与 Agent 讨论后，Agent 通过 start_run 接管入口，将目标、要求和约束写入完成报告的 settings，再按需安排任务并 finish。无需把对话复制到 request 表单，也不需要人为生成一条初始化结果；业务确需输入或共享初始结果时，用 put_node 明确添加端口。没有 command 的 Agent 候选由当前用户 Agent 操作；网页若需自动唤醒，仍需配置用户选择的 Agent 命令。

每次编辑带上 `draft_id` 和刚返回的 `revision`。出现版本冲突，重新 `read_loop` 后再决定修改，不盲目覆盖。工具返回当前验证结果；未完整连接的草稿可保存，但必须修正结构错误才能发布。

## 作者 Skill 的文件与引用

作者已有完整 Skill 目录时，保留 SKILL.md、references/ 和 scripts/ 的相对结构，用现有 `put_asset` 将各文件附进 Loop 包；本地打包也可使用已有的目录附件能力。

- Loop Skill：`set_loop` 的 `handbook_path` 绑定包内入口，例如 `skills/research/SKILL.md`。可同时保留 handbook 简介；空字符串清除文件绑定。
- 节点 Skill：`put_node` 的 `skills` 使用 `[{"name":"评审方法","path":"skills/review/SKILL.md"}]`。原有 content 正文方式继续可用。
- 发布前 `validate_loop` 会检查绑定的入口文件已附入包。引用资源由作者完整附入，不自动扫描或改写 Markdown。

安装后 `read_loop` 返回 Loop 和节点 Skill 的 `resolved_path`；运行中 `read_timeline` 返回 Loop Skill 的该路径，`read_task` 返回对应节点 Skill 的该路径。Agent直接读取文件，以其所在目录解析 references/、scripts/ 等相对引用。`path` 是包内绑定，`resolved_path` 是读取结果，不写回 Loop 定义。

## 给运行时 Agent 提供简洁入口

作者可以把常用 Timeline 操作封装为随包脚本，例如 `submit_experiment`、`arrange_next_round`。用已有 `put_asset` 添加脚本及其说明，通过节点 `skills[].path` 绑定说明入口；不需要注册新工具。Skill 内写清命令、参数、回执和出错后的处理，业务规则由作者负责。

封装调用同一个平台 HTTP 接口或 Skill 中的 `scripts/call.py`。从本次唤醒上下文取得实际地址、Run、Task 和令牌，不写死本机路径或另存一份 Timeline。后台节点使用 `platform_url` 并传 run_id/token；网页 Agent 使用 `tool_url`，其接口已绑定身份，参数中不再传 run_id/token。Skill 的 `resolved_path` 可直接读取，其 references、scripts 路径相对该文件所在目录解析。

封装负责重新读取所需版本、检查每步回执，并返回实际提交结果。多次工具调用不是一个事务：中途失败时应报告已完成的操作，继续前先读取当前状态，避免重复安排。完成任务仍需提交必需输出，最后释放操作权；封装可以把这些步骤包在一个业务命令里。权限范围、版本冲突和输出校验由平台照常执行。

Agent 候选支持 `prompt` 字符串，与 command 一起保存、分享；已有候选可用 `set_implementation` 单独修改 prompt，无需重填命令。网页在节点候选中可编辑、恢复默认和预览。例如：

```text
读取本次上下文中 skills 的作者说明，按说明使用随包脚本完成工作。
{{context}}
```

只有 `{{context}}` 会替换为 JSON；其他文本原样发送，没有隐藏追加指令。不填写 prompt 时使用平台默认；显式空字符串就是空提示词。默认内容引导使用作者入口，平台手册仅在直接操作通用工具时按需读取。后台上下文含 run_id、execution_id、task_id、token、scope_task、platform_url、platform_client、platform_guide、loop_key、handbook、node_id、instructions 和 skills。网页上下文使用 tool_url，并提供 preparation、run_id、scope_task、start_requested 和 messages；网页 prompt 与节点候选单独配置。

## 结果的通用展示

界面按结果结构展示文本、字段和表格。可在输入输出 schema 中提供 `title`、`description` 解释字段，平台不识别业务字段名称。轮次由运行时 `round` 明确提供，没有轮次的 Loop 无需填写。

文件输出使用 `schema: {"type":"string","format":"file"}`，结果值填写实际文件路径。相对路径以该次执行的工作目录为基准；没有工作目录时以安装的 Loop 包目录为基准。文件必须位于该目录内。图片可预览，其他文件通过浏览器查看或下载；文件不存在时会报错，不把普通字符串当文件，也不复制或保存外部文件历史。要保留旧产物，请每次执行使用不同文件名。

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

候选实现可声明可选的 `parameter_schema`（type 为 object），约束该实现接收的 Task parameters；节点的 parameter_schema 继续表达公共要求，同一份参数必须同时满足两者。read_loop 定向读取候选可查看契约，网页在候选的“此实现的任务参数”中编辑。set_implementation 未传则保留，clear:["parameter_schema"] 明确清除。只做校验，不在服务端补参数默认值。

新增、批量安排、修改与重试任务按有效实现校验参数，选择优先级仍是 Task 指定、Run 默认、Loop 默认。后续切换 Run 默认实现时，未执行且不满足新契约的任务会等待修正，不会带错参数启动；已派发执行保留原契约。没有选定实现时仍允许安排任务，选定后再检查。兜底候选由平台以空参数创建，因此不能要求必填的私有参数，应通过 Timeline 工具读取上下文。

更改 kind 时明确提供新 lifecycle，或 `clear:["lifecycle"]` 使用该方式的初始模板。旧配置中不适用于新方式的字段也要明确清除，工具不会偷偷删除作者内容。例如 Agent 改同步脚本时，可清除 prompt 并设置真实 command。

集合字段约定保持简单：未传则保留，传入则替换该字段整体。put_node 的端口/Skill 列表、put_step 的 inputs/after、set_implementation 的 lifecycle 都遵循这一约定；先定向读取再修改，不把只提供一个元素误当作追加。单条连接可用 connect_steps 修改，不用重写其他输入。

包文件用 read_loop 的 asset_path 读取，再用 put_asset 的 content 写回；未传 executable 会保留已有权限。删除用 `put_asset(..., path="包内路径", remove=true)`，不同时传 content 或 executable。删除不级联删除节点和 Skill，草稿可暂时存在缺失引用，修正后再发布；检查 references 及作者脚本中的实际使用位置。

删除节点或输出时，保存草稿会清理本次失去最后一个输出引用的自动生成记录类型（节点ID.端口名）；共享类型保留，已发布版本和已有 Run 不变。validate_loop 的 unused_records 列出其他未引用类型；核对后可用 set_loop 的 remove_records 数组删除，工具拒绝删除仍被引用的类型。网页在模板下列出这些类型并提供清理按钮。

模板输入未指定时保持缺失，不自动填空值。节点输入可查看每个模板步骤的实际来源；缺失或已删除的上游以提示色标出，点击输入或校验结果的“定位修正”直接编辑对应端口。校验只检查已声明的契约，业务是否还需要其他数据由作者判断。

`remove_step` 要求先处理消费者，`remove_node` 要求先移除引用它的步骤。网页删除会列出引用，可定位修改或明确确认断开。网页编辑自动保存草稿，“保存并使用”统一校验、安装版本并进入准备页，不直接执行任务。

循环安排通过节点的 plan_nodes 声明，运行任务依赖仍不能成环。可缺实现地构建、分享、安装和创建 Run；实际执行时才检查实现选择。业务脚本和环境配置由作者提供，不自动修复路径或依赖。构建完成后按 [run.md](run.md) 操作 Run；编辑 Loop 定义与修改正在运行的 Timeline 是不同操作。


## 并行支线与全局决策

运行时 Agent 默认在自己的 Task 支线内规划后续工作；相同节点模板可以用于多个并行 Task。归属由 parent_id 表达，输入/after 只表达数据与执行依赖。公共汇总任务由共同上层安排，后续业务步骤仍使用已有节点和批次模板。

需要某个正常决策节点处理整个 Run 时，通过 set_loop 的 global_agent_node 指定该节点，并提供 Agent 候选实现；初始化与兜底任务也具有全局范围。不要让普通节点靠改写同一全局记录协同，应输出各自结果再明确汇总。


## 执行生命周期与附属监控

同步/异步由候选实现决定，同一节点可切换实现。`set_implementation` 保存候选时会填入明确的 `lifecycle: {initial, transitions}` 初始模板；`read_loop` 可查看，网页候选中可查看图示、编辑转移矩阵。模板不是业务决策。没有 lifecycle 的旧包保留原文；查看时展示对应初始模板，派发时将实际规则保存到执行快照。

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

同一事件零条命中、多条命中、条件求值失败或重试参数不合法，均保留为明确异常，不擅自选择分支。`process_error` 可进入 fault/retry/agent，但进程未确认停止时禁止自动重试。`check_error` 只代表监控查询失败，不允许借此重提外部工作；恢复监控仍沿用原 external_id。

重试等待上一进程退出和操作范围可写，暂停期间不执行。等待期间可由持权操作者明确接管重试或取消；原待应用转移随之失效。进程已确认结束的待重试动作会在重启后继续；重启时进程结局未知则标明原因，核实后通过已有 retry 工具恢复。调度复用现有限额，Agent 异常退出的三次暂停与通知机制继续有效。
