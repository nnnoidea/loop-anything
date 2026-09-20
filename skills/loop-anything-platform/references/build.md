# 构建 Loop

本 Skill 由平台提供，只教平台操作。业务目标、流程职责、决策规则和专业 Skill 由 Loop 作者提供；不能用平台示例代替作者的业务设计。

工具调用方式见 [平台 Skill](../SKILL.md)。先检查连接并用 `list` 读取实际工具参数；编辑带上最新 draft_id/revision。连接失败先处理平台地址或服务问题，不创建业务 Run 测试连接。

## 从作者意图到可用 Loop

先与作者明确任务、每步输入输出、哪些工作由脚本或 Agent 完成。不要替作者增加未要求的业务步骤。

- **开始或复用**：`list_loops` 找现有资产；`read_loop` 读它的实际定义。`create_loop` 建立草稿与通用入口；`copy_loop` 从已安装版本复制为草稿；普通修改传 new_version:true，保留 Loop ID 并自动选择后续版本，原有 Run 不变；只有用户要另建一个 Loop 时才使用普通复制。
- **业务说明**：`set_loop` 写入作者提供的 `handbook`、用途说明、初始输入默认值或明确的运行限额。平台 Skill 不维护这些业务内容。
- **节点**：`put_node` 写一个节点的职责、端口和可选作者 Skill。用 `skills: [{"name":"方法名","content":"作者提供的业务方法"}]` 直接绑定到该节点；Agent 读取节点任务时会获得这些内容。端口列表使用 `name` 加 `type`，嵌套契约使用 `schema`；工具生成输出记录类型。节点机械完成约束统一用 assertions 表达，例如 eq 比较字段值；不从约束自动填业务结果。入口端口变更会同步其初始位置。
- **候选实现**：`set_implementation` 提供 node_id、implementation_id 和 agent、command、external、event 或 approval 配置。同一节点可多次添加不同 ID；default:true 选为 Loop 默认，default:false 取消该候选的默认地位，省略则不改默认。已存在的候选可只传 ID 与 default 调整默认。填写实际命令参数列表。外部任务还需 observe；删除指定候选时用 unbind:true，不能伪装成模拟实现。`put_asset` 把作者编写的脚本/文档附进包。
- **可选兜底**：与用户明确是否需要 Agent 兜底。需要时用 `put_node` 添加一个非入口节点，`inputs: []`，编写处理未覆盖状态的职责并绑定作者 Skill；通过 `set_implementation` 提供 Agent 候选，再用 `set_loop` 的 `fallback_node` 指定节点 ID。不需要时传空字符串关闭。兜底通过 Run 工具读取问题，使用同一套节点提交；不要自动挑其他节点的 Agent。
- **通知实现**：用 set_implementation，node_id="$notifications"、kind="command"，绑定用户提供的发送命令。平台调用并记录送达状态。用户聊天目的地通过启动 Run 时的 notification_command 设置，见 run.md，不写死在共享 Loop 中。
- **结束条件**：作者说明完成目的与判定依据，运行时 Agent 把机械规则或终止信号写入 Timeline；不要给节点添加 terminal 标记。
- **Agent 命令**：用 `set_implementation` 设置 kind="agent" 和用户提供的 command，例如 `["codex", "exec", "-"]`；cwd/timeout 按实际需要明确设置；Agent 留空 timeout 时不限时，脚本命令默认 60 秒。平台向标准输入传入任务 prompt，原样执行命令；模型、工具和权限沿用用户配置。无需专用启动器或工具注册。
- **可复用批次**：`put_step` 将节点加入一个命名模板。可用 implementation 指定模板选用的候选 ID，通常留给 Run 或任务选择。用 `plan_parameters` 声明运行时参数；`each` 指向参数里的列表。`connect_steps` 把上游 output 连到下游 input，`collect:true` 表示收集全部展开结果。
- **初始或复用输入**：在 `put_step.inputs` 中使用 `{"record":"initial.result"}` 等明确来源。入口的真实输出位置由 `read_loop` 返回，不猜名字。普通参数值用 `literal`；运行时替换值可以写 `{"literal":{"$":"values.参数名"}}`。列表元素对应 `item`。
- **检查与交付**：`validate_loop` 检查结构并单列缺失实现。修正错误后 `publish_loop` 安装为一个版本，不启动；日常迭代可传 auto_version:true，在版本已存在时自动选用新版本，返回最新 draft_id/revision 和实际 version，原版本不被覆盖；`export_loop` 导出包含附件的包，客户端 `--output 文件.loop.zip` 保存它。

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

先查看是否已有该 Loop 的未发布草稿并继续编辑，避免每次小改都复制一份。读取后只修改相关节点或步骤，不重写整个Loop 定义。`remove_step` 要求先处理消费者，`remove_node` 要求先移除引用它的步骤。新发布版本不迁移既有 Run。

网页编辑会自动保存草稿，“保存并使用”统一校验、安装版本并进入启动准备，不直接执行任务。循环安排通过节点的 plan_nodes 声明；它表示可安排后续的新任务，不是把同一批任务连成依赖环。脚本依此声明安排任务，Agent 仍按原授权与 Task 范围操作。删除节点或步骤时网页会列出引用，可定位修改，或显式确认一并断开；缺失输入必须修正后才可发布。

可缺实现地构建、分享、安装和创建 Run；实际需要执行任务时才检查实现选择。切换已有候选只需在 Run 或任务中指定 ID，不需要复制 Loop。平台不自动修复命令、路径或依赖。业务脚本怎样实现仍由作者及其 Agent 决定。

构建完成后，按 [run.md](run.md) 操作 Run，结合 Loop 作者说明和任务所属节点的 Skill。不要把编辑Loop 定义当作修改正在运行的 Timeline。


## 并行支线与全局决策

运行时 Agent 默认在自己的 Task 支线内规划后续工作；相同节点模板可以用于多个并行 Task。归属由 parent_id 表达，输入/after 只表达数据与执行依赖。公共汇总任务由共同上层安排，后续业务步骤仍使用已有节点和批次模板。

需要某个正常决策节点处理整个 Run 时，通过 set_loop 的 global_agent_node 指定该节点，并提供 Agent 候选实现；初始化与兜底任务也具有全局范围。不要让普通节点靠改写同一全局记录协同，应输出各自结果再明确汇总。
