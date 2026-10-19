# 用户 Agent 启动与命令接入

安装平台、安装 Skill 和连接检查见 [README 安装说明](../README.md#安装平台)。通过 `set_implementation` 直接绑定用户提供的 Agent 命令。

用户自己的 Agent 在讨论后创建并初始化 Run；后台在节点有 Agent 任务时按命令唤醒；用户显式启用的兜底节点可以承接未覆盖状态，使用它自己的 Agent 候选。
入口节点仍有初始化任务，由当前用户 Agent 完成，结果在界面和执行记录中保留。

## 用户自己的 Agent 创建 Run

通过 list_loops/read_loop 取得所选 Loop 的 key、作者说明和入口要求。
使用当前服务地址，POST `/api/runs`，携带 `X-Loop-Anything: workspace` 和 JSON：

```json
{
  "key": "实际安装的 Loop key",
  "title": "本次运行名称",
  "inputs": {"request": "已经讨论确定的要求"},
  "authorization": "用户允许的自主操作范围",
  "acquire": true
}
```

平台在同一次持久化提交中创建 Run 并取得 Agent 操作权；Engine 看不到“已创建但尚未持权”的中间状态。
返回对象中的 `id`、`agent_sessions[0].token` 和 `loop_definition.seed.id` 分别是 Run、操作令牌和入口任务。
用户 Agent 对 `/api/runs/{id}/agent` 发送 `{token,tool,arguments}`，按顺序：

1. `read_task` 读取入口任务的完整要求、task_version 和输出契约。
2. `complete_task` 提交已讨论好的初始 settings 和入口输出，不重复询问用户。
3. 使用 `read_plans/build_plan` 安排本次需要的 Task；继续处理当前可处理任务与问题。
4. 完成本次任务、处理本范围异常后 `finish`，后续已安排任务可以交给 Engine。

创建后初始化未完成时，入口显示未完成；完成后显示其真实结果，不伪造完成状态。
持权不阻塞正常脚本。若已构建的脚本输入就绪，它仍可执行。
不传 acquire（或传 false）的旧创建入口仍可由 Engine 唤醒初始化 Agent，适用于表单或无人值守启动。

通过安装到 Agent 的平台 Skill 调用同一组操作：

```sh
python3 /平台Skill/scripts/call.py start_run --arguments @启动参数.json
python3 /平台Skill/scripts/call.py read_task --arguments '{"run_id":"RUN_ID","token":"TOKEN","task_id":"ENTRY_TASK_ID"}'
```

`start_run` 返回 run_id、token、entry_task_id；已有平台服务负责推进和显示。完整 Skill 包含脚本和连接文件，无需查找平台源码或安装环境。

## 网页也是用户 Agent 的入口

在 Loop 库卡片或详情选择「启动」，进入启动准备页。准备页立即列在左侧，可在多个准备页与已有 Run 间切换；刷新后仍保留，启动后转到对应 Run。节点卡片显示当前实现；点击节点在图旁查看候选的执行方式、命令配置与共用节点 Skill，直接选用、恢复默认或暂不选用。选择自动保存，只用于本次运行；「编辑 Loop 定义」继续编辑同一个 Loop，草稿自动保存；“保存并使用”统一校验和处理版本，随后进入该版本的启动准备。另建 Loop 使用单独的“复制为另一个 Loop”。准备内容与对话保存在本地平台数据库，刷新后可继续；正式启动前没有业务 Run。节点关系图区分模板依赖和作者声明可安排的工作，标出返回已有节点的循环关系；默认按依赖链合并重复安排线，可展开全部连线或选中节点查看完整声明。它不把动态决定画成必然执行路线。

「网页使用的 Agent」可沿用已有 Agent 候选，或填写用户自己的命令、工作目录、可选超时与唤醒提示词。命令按参数逐项填写，例如三行 `codex`、`exec`、`-`；模型、权限和其他参数仍由用户选择。网页命令与节点实现独立，不随 Loop 包分享。保持平台运行后，可直接在网页讨论、明确要求初始化并启动，随后查看同一 Run 的过程、回复和通知。

每条消息调用一次配置的本机命令，prompt 携带本页对话与限定到当前准备页／Run 的工具地址。沿用 Skill 的调用脚本和既有 Timeline 工具；读取不取得操作权，修改时按页面选择的范围取得操作权并检查版本，最后 finish。创建 Run、绑定准备页和取得初始化操作权在同一次事务中完成。具体操作见 [平台运行 Skill](../skills/loop-anything-platform/references/scoped-entry.md)。

当前网页回复在命令退出后整体显示，不提供逐字输出或独立模型配置。网页历史用于对话连续性，业务事实仍由 Timeline 保存；不会把 Agent 的普通回复当成任务结果。后台节点继续按各自候选实现执行。关闭网页不停止命令；平台中断且无法确认旧命令停止时，保留操作权，确认停止后才恢复。

进度与通知直接展示 Run 中的记录。网页新建通知 Hook 可选择「工作台」或用户发送命令；外部通知仍使用原有接口，不因打开网页自动改变接收方。

## 后台 Agent：命令与 prompt

平台原样执行用户提供的 argv，按需使用其 cwd/timeout；Agent 未配置 timeout 时不限时。提示词通过标准输入传入。Agent 候选的可选 `prompt` 字符串完整替换默认内容；只有 `{{context}}` 展开成 JSON，不拼接额外指令。缺少该字段时使用平台默认，显式空字符串则发送空内容。

后台上下文提供 run_id、execution_id、task_id、token、scope_task、platform_url、platform_client、platform_guide、loop_key、handbook，以及当前节点的 node_id、instructions、skills。安装包中绑定的 Skill 包含实际 resolved_path，可按其目录找到 references 和封装脚本；完整业务状态仍通过作者脚本或平台工具读取。

节点候选的唤醒提示词在网页中只读展示，由 Agent 通过平台工具修改，随 Loop 分享；修改只影响新版本，既有 Run 及执行保留原配置。网页对话入口自身的提示词仍可配置、预览。网页对话的提示词另存在本机，选用候选命令不会把节点任务提示词带进网页讨论。网页上下文以 tool_url 代替后台身份参数，还包含 preparation、run_id、scope_task、start_requested、messages 和作者 handbook；需要节点 Skill 时可 read_loop/read_task。

预览不唤醒 Agent，不创建 Run 或取得操作权；尚未生成的运行身份和令牌用占位文字标注。实际唤醒记录保存发送内容，网页在执行尝试或 Agent 回复下可展开查看，平台令牌已遮蔽。以后改提示词不改写旧记录；旧执行没有记录时不从当前模板补造历史。

默认提示词不强制读取平台手册。作者可用随包脚本封装 Timeline 工具，由节点 Skill 说明业务入口；Agent 只需理解作者接口。封装沿用原权限、版本、输出与 finish 校验，没有另一份状态或独立工具注册。

例如，用户选择从标准输入接收 prompt 的 Codex 命令：

```json
{
  "kind": "agent",
  "command": ["codex", "exec", "-"],
  "timeout": 180
}
```

平台不追加模型、工具、权限或其他启动参数，不配置用户的 Agent，也不需要专用 Codex 启动器。用户需要的参数直接写在 command 中。其他 Agent 使用相同方式。

结果通过平台工具提交；最终文字不作为业务结果。平台记录执行与失败，现有 Engine 负责命令超时、退出处理、范围重叠互斥的 Agent 操作权以及已配置的失败恢复。

候选实现与运行时选择见 [Implementation 与 Binding](implementation-selection.md)。

## 实时输出与交互终端

后台 Agent 每次执行自动保存实时输出。在 Run 任务详情中选择执行尝试，打开输出或终端；关闭页面继续执行，重开读取历史。查看和输入均使用工作台编辑权限。

候选设置 `terminal: true` 可在 macOS/Linux 启动交互 PTY，例如 `command: ["codex", "{{prompt}}"]`。`{{prompt}}` 作为一个参数传入完整任务上下文；`{{prompt_file}}` 则提供权限为 0600 的提示词文件路径，供支持文件输入的程序读取。普通命令继续一次性 stdin 提示词，交互命令保留 stdin 给用户输入；所有其他 argv 保持不变。

交互面板连接同一 Agent 进程和操作权；结果仍通过平台工具写入。Agent 调用 `finish` 后，平台关闭交互进程组，防止 CLI 完成任务后持续停留。历史输出保留，重试独立记录。平台重启后标记会话中断并沿用旧操作权恢复规则，不承诺恢复厂商 CLI 会话。Windows 当前只支持普通命令实时输出。

任务卡片现提供「查看结果」与 Agent「打开会话 / 恢复会话」。平台单独保存 CLI 原生 ID，支持输出识别、Agent 主动登记以及用户明确关联旧会话；恢复签发新操作权，保持原任务结果。候选可设置 agent_cli/resume_command，CLI 记录缺失时明确失败，不使用最近会话代替。

完整配置、限制和验收见 [终端接入说明](../skills/loop-anything-platform/references/terminal.md)。组件本地打包，运行时不访问 CDN。

## 可选聊天桥接与通知适配

用户可选择任意能调用本机 Agent 的聊天桥接。桥接负责聊天接入和 Agent 会话；Agent 通过同一组平台工具操作 Run，平台通过通用命令接口发送通知。终端使用不需要桥接。

完整契约见[通知接口](../skills/loop-anything-platform/references/notifications.md)。平台提供 [cc-connect 适配器](../skills/loop-anything-platform/references/cc-connect.md)作为第一个可用示例；其他实现按相同输入和回执契约接入，无需修改 Engine、Loop 或注册插件。个人接收目标保存在 Run 设置中，不随 Loop 包共享。

通信群组按机器独立绑定通知入口。没有聊天来源的新群组请求，通知默认优先动作发生方，其次直接请求发起方，均无入口则仅记录；来源继续持久生成、去重并保存回执。发送失败或结果未知不自动切换机器。详见[群组通知优先级](../skills/loop-anything-platform/references/communication.md#群组按机器绑定出口与通知优先级)。

## 跨入口继续同一 Run

终端、网页或聊天桥接背后的 Agent 连接同一个平台实例。list_runs 定位已有运行；read_timeline/next_tasks/read_task/read_record/read_plans 无 token 时仅从当前快照读取，不取得写入权。普通工作区写入可省略 token，由平台处理临时操作范围；连续或支线操作仍可显式 acquire_run，重新读取版本后使用原有工具，最后 finish。托管节点使用唤醒身份，错误或过期 token 不会自动放宽范围。read_timeline 的 read_only=true 明确表示没有操作权，带令牌读取仍按原范围展示。显式无效令牌报错。Run 目标、约束、决定、结果和任务是共同上下文，聊天记录与通知目的地不承担状态同步。

## 本机具名外援与群组远端 Agent

使用通信群组时，每台机器保留独立平台与数据库。正式远程节点通过 Agent dispatch 接入；临时外援和普通对话通过统一 request_assistance 接口调用本机具名目录或明确群组。已有本机 Agent 不会因为加入群组而被远端启动。

远端上下文提供本机 platform_client 和限定的 platform_url，原 read_task/report_task/finish 工具经此入口回到来源 Run；模型/CLI 配置不被平台替换。结果仍需结构化提交。消息尚未确认的 pending 回执不等于成功。包内资源分块传递并核验，业务产物使用可访问的共享引用。详细配置见[通信说明](../skills/loop-anything-platform/references/communication.md)。

### Agent 的轻量入口与通信读取

平台 Skill 按持续工作、独立外援、查询已有任务和组网场景选择入口，详细调用与连接说明按需加载。升级平台后需同步导出/更新 Agent 实际加载的 Skill，并保留连接地址。

通信查询默认返回精简状态和结果；仅排错时设置 read_assistance 的 include_logs（4000 字符默认、16000 上限），沿 log_cursor/log_offset 继续；include_details 单独请求原始上下文和历史。追问保留原始业务上下文及最近结果，外援续跑不携带完整通信档案；原 session 身份与结果契约保持不变。

## 聊天入口通知（0.5.7）

飞书入口经 Skill 客户端自动保存原会话；私聊由入口 Bot 回复，群聊的执行确认和结果优先使用具名 Agent 的 `notification_bot={project,platform}` 所映射 Bot（旧 notification_route 兼容），并保持原话题。发送前明确不可用才回退入口，发送结果未知不自动换 Bot。嵌套外援继承原来源；显式通知出口覆盖，无聊天来源保留按机器优先级。先用 read_cc_connect/configure_cc_connect 接入本机桥接并发现 Bot，再用 communication_config 设置具名 Agent 的映射；无需自行拼接命令。接入、直接发送及 API 用法见平台 Skill 的 `references/cc-connect.md`；话题需开启 cc-connect 话题隔离并保留 root session key。

## Loop 编辑保护

可信工作区无需全局编辑解锁。set_loop_password 为具体 Loop ID 设置可选口令，只保护定义、实现、手册及随包资源；修改提供 loop_password 或对此 Loop 解锁。list_loops/read_loop 返回 edit_protected，read_capabilities 的 loop_edit_protection 说明边界。草稿、版本共用保护，包导出/安装/载入草稿保留校验值，明文和本机解锁 Cookie 不打包。Run、外援、通知、终端不受编辑口令限制，实际执行仍校验范围、版本、过期结果和原生会话。

## 通知接入职责

call.py 只将聊天入口的渠道、Bot project和完整session key作为chat_context随request_assistance/start_run传递；不探测cc-connect、读取配置或查询飞书，也不提前注册会话。平台保存并复用来源、选择出口与回退，发送适配器直接调用cc-connect，不自行查询飞书、读取Bot凭据或预检渠道权限。配置或桥接不可用仅形成通知错误，任务仍可执行。旧conversation_id和显式通知出口继续兼容；原话题不静默改投，未知送达不重复发送。
