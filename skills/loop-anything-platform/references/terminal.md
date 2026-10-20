# Agent 执行会话与 CLI 接入

平台自动保存后台 Agent 每次执行的实时标准输出和错误输出。输出关联具体 Run、Task 与执行尝试，可按执行身份查询。同一尝试内再次唤醒时保留独立会话；重试不会覆盖旧输出。断开查看连接不停止进程，重新连接可读取历史并跟随当前输出。

这是平台已有能力。Loop 作者只需提供命令和业务方法，不需要另建日志查看功能、终端服务器、任务身份映射或对话代理。构建前用 `read_capabilities(capability="agent_terminal")` 核实运行中的平台支持情况。

## 普通命令：默认只读输出

现有 Agent 命令保持原行为：平台把完整提示词一次性写入 stdin 并关闭输入，持续收集 stdout/stderr。例如：

```json
{"kind":"agent","command":["codex","exec","-"]}
```

显示速度取决于 CLI 自己是否及时输出/刷新缓冲。平台不追加模型、权限、工具或输出格式参数。CLI 的结构化输出会按原文显示；不是所有 Agent 都会输出详细进度。

## 交互终端：同一进程内输入

在候选实现中设置 `terminal: true`。当前 PTY 主机支持 macOS/Linux；Windows 可使用普通命令实时输出，交互终端会明确拒绝启动。

通过公开工具配置：

```json
{
  "tool":"set_implementation",
  "arguments":{
    "draft_id":"实际草稿 ID","revision":1,"node_id":"实际节点 ID",
    "kind":"agent","terminal":true,"command":["codex","{{prompt}}"],
    "cwd":"/用户选择的工作目录"
  }
}
```

命令参数中的 `{{prompt}}` 替换为完整任务提示词，作为一个参数传入，不经过 shell。CLI 必须支持初始提示词参数；可自行添加其支持的参数。

对于较长的上下文或接受文件的 CLI，使用 `{{prompt_file}}`：平台写入本次执行专用的 UTF-8 文件（权限 0600），替换为文件路径，并通过 `LOOP_ANYTHING_PROMPT_FILE` 环境变量提供相同路径。配置的程序必须读取该文件；进程结束时文件移除。`{{prompt_file}}` 不能自动让不支持文件输入的 CLI 读取文件。

每个交互命令必须包含至少一种占位符。平台不会把长提示词模拟成终端按键；终端 stdin 留给真实交互。PTY 使用 `TERM=xterm-256color`，支持 ANSI 屏幕、键盘输入和窗口尺寸调整；主机维护终端状态并回复标准光标/设备查询，不依赖查看连接。CLI 的登录、模型、信任目录、权限和工具配置仍由用户管理；程序必须能调用平台工具才能参与 Loop。

## 任务与退出约定

- 交互连接使用已经运行的同一个 Agent，不新建 Agent，不取得另一份任务操作权。
- 可以直接输入补充要求、回答 CLI 提问；Ctrl+C 原样发送给该 CLI，其效果由 CLI 决定。
- CLI 通过既有 `read_task`、`report_task`/`complete_task`、`finish` 协议提交结果。终端文字不作为业务结果。
- 交互 Agent 成功调用 `finish` 释放操作权后，平台停止该会话的进程组，保存输出。普通命令仍保留原先自然退出语义。
- 完成后的终端只可回看，不能继续向已失去操作权的 Agent 发指令。继续工作使用现有任务编排工具，失败后重试产生新的执行记录。
- 用户配置的 timeout、平台关闭及未知进程状态恢复规则仍有效。平台重启会保留输出，标记旧会话中断；不会自动重连或恢复厂商 CLI 会话，也不会把未知副作用视为成功。

## 访问与验收

终端日志可能包含工作目录或业务数据，输入仍核对实际终端session及执行状态。运行令牌在持久化输出中遮蔽；这不是通用业务数据脱敏服务。输出保存在本机工作区 SQLite，按游标分页读取，完整记录随工作区保留，不随 Loop 包分享。

`smoke_runtime` 能检查配置的交互命令启动，并在观察到探针标记后关闭探针会话；交互界面可能回显提示词，检查明确保留模型回复未验证，不能将回显当成模型成功。它不能证明该 CLI 的所有交互、登录和业务工具均可用；`test_loop` 仍只做模拟流程验收。

## 每个任务的结果与原生会话恢复

通过 read_task/read_record/read_run 读取任务结果及执行历史，查看不启动 CLI 或改变结果。平台已有按执行身份查看输出、连接运行进程及恢复原生会话的能力；构建时配置准确身份和恢复命令，无需另建恢复服务。

### 保存真实原生 ID

平台执行 ID 与 CLI session ID 分开保存。支持以下来源：

- Codex：自动识别 `codex exec --json` 的 `thread.started.thread_id`，以及普通输出中的明确 `session id:` 行。平台不会擅自追加 `--json`。
- Claude Code：识别 JSON/stream-json 中的 `session_id`；交互启动可以显式配置 `command: ["claude","--session-id","{{session_id}}","{{prompt}}"]`，平台在每次执行生成新的 UUID 并替换占位符。
- 已在平台执行中的 Agent 可调用 `register_agent_session(execution_id, provider, session_id, cwd)` 记录自己当前 CLI 的真实会话 ID。例如 Codex 的工具进程可读取 `CODEX_THREAD_ID`；拿不到真实 ID 时不猜测。只能登记自己持权的当前执行，不能覆盖另一个已关联的 ID。没有自身 execution_id 的外部入口先按[入口 Agent 与 session 登记](communication.md#入口-agent-与-session-登记)选择方式，不借用其他 Run 的执行。
- 旧执行可从其自身已保存的启动输出识别 ID；没有记录时由用户明确补充。平台不扫描无关 CLI 历史，也不使用 `--last`。

直接命令的 `codex` / `claude` 可自动识别；包装脚本通过候选字段 `agent_cli: "codex" | "claude" | "custom"` 显式说明。

### 恢复命令

候选可声明 `resume_command`（每个元素一个 argv）：

```json
{
  "agent_cli": "codex",
  "resume_command": ["codex", "resume", "{{session_id}}", "{{prompt}}"]
}
```

Claude 示例为 `["claude","--resume","{{session_id}}","{{prompt}}"]`。其他 CLI 也可使用显式命令。恢复命令必须包含真实 ID 占位符以及新提示词 `{{prompt}}` 或 `{{prompt_file}}`，由平台传入最新任务上下文及用户要求。本次恢复命令需由用户明确选择；所需模型、权限、profile 等参数须显式保留，平台不猜测或添加。

恢复仅对仍处于 running/paused 的 Run 开放，沿用所选任务支线的操作范围。同 Task 已有执行者、同 CLI 会话仍在运行或旧进程状态未知时，平台拒绝重复恢复。重复请求同一正在恢复的执行只连接已有进程。

每次恢复签发新的平台操作令牌，旧令牌不能复用。源任务及其正式结果保持历史语义；解释结果不重复执行，修改工作必须通过明确的任务工具。恢复会话调用 `finish` 仅结束本次对话并释放操作权，不把原任务伪造成重新完成。CLI 找不到原生记录时保留失败信息，不自动改为新会话。

CLI 自己的会话文件仍需保留。会话 ID 不能替代这些文件，也不随 Loop 包搬迁到另一台机器。此能力已经由平台提供，作者无需另建会话注册、恢复进程或任务结果展示功能。

接口参考：[Codex JSON 事件](https://learn.chatgpt.com/docs/non-interactive-mode)、[Claude CLI session/resume 参数](https://code.claude.com/docs/en/cli-reference)。具体版本以主机安装的 CLI 为准。


### 恢复边界与纠错

同一平台内，同一个原生 CLI 会话在进程真正退出前保持互斥，包括已调用 finish 但仍在退出的间隔，以及跨任务/跨 Run 的恢复。进程状态未知时先查看会话记录，在主机确认旧 CLI 及其子进程已停止后，通过平台确认旧进程停止后再恢复。确认恢复对话进程停止不改变原业务任务的失败计数。

自动识别原生 ID 是辅助功能。ID 来源冲突会显示诊断并保留既有关联，不中止业务执行。用户如手动关联错误，可明确纠正 ID；平台按读取到的旧关联检查并发变化，拒绝替换仍活动或未确认停止的会话，保留旧会话和关联变更历史。

直接使用 Codex/Claude 命令时，平台检查明确的 resume 子命令/参数和独立的 session ID，拒绝最近会话/继续/分叉选项。自定义包装程序仍须由作者保证真正实现对应 CLI 的恢复语义。

交互 CLI 自行退出也会清理仍处于同一进程组的子进程。平台不接管脱离进程组或外部手动启动的 CLI。用户自带 Agent 可在首次报告建立实际 execution 后、finish 之前登记会话 ID，登记仍需自己的 token 和任务范围。
