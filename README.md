# Loop Anything

**Your agent builds it. The engine keeps it running.**

让你的 Agent 把工作安排好，让平台持续推进。你能看见每一步做了什么、得到什么结果，也能随时调整接下来怎么做。

## 看见整个过程，改变下一步

比如做一项研究：先准备数据、跑几组实验，再让 Agent 比较结果、提出下一组实验。你可以点开每一步查看结果；中途换一个研究方向，保留已有成果，修改后面的安排。

比如安排一次差旅：收集方案、等你确认、执行预订、关注行程变化。出现变化后，按你的新要求调整方案，而不是从头再来。

仓库提供这两类**模拟示例**，可先体验过程查看与调整；实际训练、预订等工作需要接入你自己的实现。

![工作台中的实际任务、结果与后续安排](docs/images/run-workspace.png)

*本地工作台截图：模拟流程中的已完成结果和可以调整的后续任务。*

- **每一步都有迹可循**：看结果、输入来源和历次执行。
- **运行中也能调整**：保留已发生的过程，修改还没开始的工作。
- **和 Agent 一起设计**：说清目的，让 Agent 构建流程；也可以在画布上连接和编辑步骤。修改自动保存为草稿，准备好后“保存”。
- **安排一次，持续推进**：保持平台运行，关闭网页也会继续；需要你时按配置发送通知。
- **启动前先选好**：为这次运行选择本地或远端等执行方式，在网页中与自己的 Agent 讨论，准备好再开始。
- **把好用的流程分享出去**：安装别人提供的 Loop，也能替换其中的执行方式。

![在画布上编辑步骤和连接](docs/images/loop-editor.png)

你可以在网页中与自己的 Agent 讨论并启动，运行后边看过程边调整；也可以直接在终端工作。也可以通过自己选择的聊天桥接接入飞书、微信，继续查看和修改同一次运行。平台附带可选的 cc-connect 通知适配器；真实聊天渠道需在你的环境中配置和联调。

想先看一眼：[本地预览](#本地预览)。准备安装：把本 README 链接交给自己的 Agent，让它按下面的说明完成。

网页操作见[工作台使用说明](docs/user-guide.md)。

## 安装平台

平台安装是一次性准备。把本 README 链接交给自己的 Agent，让它完成下面的步骤；日常操作使用平台 Skill。

1. 检查是否已有可用平台，默认地址为 `http://127.0.0.1:8767`；已有实例就复用。连接失败先确认服务与地址，不新建 Run 或数据库来测试。
2. 获取本仓库完整源码；已有发布附件时，也可获取其中的安装 ZIP。需要 Python 3.9 或以上及 pip/venv。源码安装还需要 Python 构建依赖；不要从同名第三方包代替安装。
3. 在源码或安装 ZIP 解压目录执行 `python3 install.py`，Windows 可用 `py -3 install.py`。安装器创建独立环境并返回平台 Python 和启动文件路径。macOS 默认同时注册并启动系统用户后台服务；已有工作区请加 `--db 绝对路径`，已有非默认端口加 `--port 端口`。
4. macOS 安装成功后用该 Python 执行 `-m loop_anything service status` 确认服务与实际工作区，或双击安装目录的 `Loop Anything.command` 打开页面。关闭 Agent 应用、终端和浏览器均不停止后台服务。Windows/Linux 当前仍使用 `-m loop_anything serve --open` 前台运行，需要独立终端保持运行；尚未提供其系统服务安装。
5. 将完整[平台操作 Skill](skills/loop-anything-platform/SKILL.md)导出到当前 Agent 支持的 Skill 目录，写入实际平台地址。Skill 包含 Loop 构建、Timeline 操作说明及调用脚本，不包含平台安装手册：

```sh
"<平台 Python 路径>" -m loop_anything skills --install-dir "<Agent Skill目录>" --url http://127.0.0.1:8767
```

6. 在安装后的 Skill 根目录，用本机兼容 Python 执行 `python3 scripts/call.py check` 和 `list`，核实连接、工作区、工具目录和防休眠状态。其他工作目录使用脚本绝对路径。安装与检查不调用模型，不创建业务 Run。

平台程序位于 `loop_anything/`，操作 Skill 位于根目录 `skills/`。Agent 的模型、工具权限及启动参数由用户管理，Skill 安装不会替用户配置这些内容。

<details>
<summary>安装位置、工作区与升级</summary>

安装器默认在用户数据目录的 `app/` 下创建环境，也可用 `--prefix 绝对路径` 指定。macOS 启动文件是 `Loop Anything.command`，Windows 是 `Loop Anything.cmd`，Linux 是 `loop-anything`。

| 系统 | 默认数据库 |
| --- | --- |
| macOS | `~/Library/Application Support/Loop Anything/runs.sqlite3` |
| Windows | `%LOCALAPPDATA%\Loop Anything\runs.sqlite3` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/loop-anything/runs.sqlite3` |

macOS 后台服务使用系统 launchd，登录时自动启动；注销或关机时停止。手动“停止”会保持停止，直到再次“启动”，不会立即被自动拉起。异常退出由 launchd 重启；平台自身的恢复规则仍会保留无法确认停止的旧 Agent 操作权。

```sh
"<平台 Python 路径>" -m loop_anything service start --open
"<平台 Python 路径>" -m loop_anything service stop
"<平台 Python 路径>" -m loop_anything service status
"<平台 Python 路径>" -m loop_anything service remove
```

安装目录也提供 `Stop Loop Anything.command`。移除服务仅取消后台托管，不删除平台、Loop 包或数据库。开发调试可以用 `python3 install.py --no-service` 仅安装程序，再手动 `serve`；不要让前台预览与后台服务争用同一工作区或端口。安装时发现占用会报错，不擅自结束其他进程。

原生配置位于 `~/Library/LaunchAgents/com.loop-anything.platform.plist`，日志位于用户数据目录的 `logs/`；没有第二套平台服务配置。安装时保存 PATH 和显式配置的服务环境，不会复制全部终端环境。其他必需环境变量可按需配置到该 plist 的 EnvironmentVariables，停止后修改，再启动。

指定已有工作区时，将 `--db 绝对路径` 放在 `serve` 等子命令前；平台不自动搬迁或合并数据库。平台状态 `/api/platform` 返回实际路径。换端口时同步 Skill 的 `connection.json`，也可用 `--url` 覆盖。

升级前确认没有在途操作，再用新源码或安装包执行原安装命令。macOS 安装器先停止自己管理的旧服务、更新程序，再按原工作区、端口和监听地址启动；不会重新建一个空工作区。其他系统先退出前台平台。升级后也要更新 Agent 实际加载的平台 Skill，保留原 `--url` 并在导出命令中加 `--replace`；已有内容不同且未指定更新时会明确报告冲突。随后重新加载 Skill，执行 `scripts/call.py check` 核对运行服务；仅替换平台源码不会自动刷新 Agent 的 Skill。

0.2 以前的数据库使用旧字段，需要备份并转换；不要用新建空库代替原工作区。

</details>

## 内部共享访问

在可信内网的一台机器上运行平台，其他人通过浏览器访问 `http://服务器地址:8767`。默认仅监听本机；开放内部监听时：

```sh
python3 -m loop_anything --db /绝对路径/runs.sqlite3 serve --host 0.0.0.0
```

macOS 首次后台安装使用 `python3 install.py --host 0.0.0.0`；已有后台服务先 `service stop`，再 `service install --host 0.0.0.0`。未指定的工作区和端口沿用已有配置。

### 每个 Loop 的可选编辑口令

在 Loop 详情或草稿编辑页点击「设置编辑口令」。口令保护这个 Loop 的定义、节点实现、手册和随包资源；同一个 Loop ID 的草稿和版本共享设置。修改口令或清除保护需要当前口令或已解锁的浏览器。一次解锁固定 **24 小时**，刷新、新标签页和同一工作区重启均保留；可随时锁定此 Loop。换口令立即使旧解锁失效。

导出/导入同一个 Loop 携带盐和口令校验信息，不包含明文口令或浏览器 Cookie；复制为新 Loop ID 可独立设置保护。保护属于 Loop 内容，不是平台登录机制。查看、使用和分享未改动的 Loop 不需要解锁。

查看状态、启动 Run、修改运行参数与任务安排、通信配置、请求外援、通知和终端操作均无需编辑口令。普通用户操作由平台处理内部执行标识；实际节点执行仍检查操作范围、任务版本、过期结果与真实 session。具名 Agent 的 CLI 命令、工作目录和外部服务凭据仍在各自执行机器配置。

Agent 修改受保护的 Loop 时，可在工具参数中提供 `loop_password`，或为调用脚本设置 `LOOP_ANYTHING_LOOP_PASSWORD`。旧客户端的 `LOOP_ANYTHING_EDIT_PASSWORD` 作为这一单 Loop 口令的兼容别名；它不再启用服务器全局锁。不要将明文口令写入 Loop、Skill 或提示词。

普通 Agent 和脚本默认在**启动该 Run 的平台所在机器**执行。显式配置为群组执行的 Agent 节点由通信群组成员承接；外部训练等继续使用 external 适配。远端 Agent 可使用下载的 Skill 或通过 `--url` 指定平台地址。该共享模式面向可信内部环境。

## 具名 Agent 与通信群组

平台的“Agent 通信”入口提供本机具名 Agent 目录、NAS 群组、独立请求及运行记录。首次组网按页面四步操作：配置共享空间的本机挂载路径 → 发现并显式加入群组 → 选择开放的具名 Agent → 查看成员并绑定 Loop 或请求外援。各机器核对相同空间/群组 ID；可复制加入说明转交其他机器。发现不会自动加入，加入不会自动开放所有 Agent。无 Loop 时也可通过平台 Skill 请求本机或远端外援。本机调用无需 NAS；普通后台节点和任意 CLI 会话不会自动公开。

每台执行机器安装平台、使用独立本地数据库，配置自己的 CLI 命令与工作目录。加入同一个 NAS 群组时分别填写本机挂载路径；第一次明确创建群组，其他机器加入已有群组。选择允许接单的具名 Agent，并在 Loop 使用准备或 Run 设置中绑定群组。只有显式设置为群组执行的节点才发布远端任务。

安装时再提供真实机器和 NAS 信息。“检查连接”只确认本机读写；仍需验证另一台机器可见、认领及结果回传。目录必须是获授权的可信共享空间；不要在 NAS 上共用 SQLite 数据库，也不要复制运行数据库来注册新机器。

成员退出后停止接新任务；失联中的执行保留未知状态，不自动重跑。飞书/微信复用已配置的通知出口，不承担任务和结果传输。操作、会话及恢复边界见[通信说明](skills/loop-anything-platform/references/communication.md)。

没有聊天来源时，群组通知按机器独立绑定本地出口（例如 cc-connect project 和聊天 session）。每条通知优先动作发生方，无入口时回退本次请求发起方；都无入口则仅保留平台记录。嵌套外援按直接发起方回退。已选定发送方后，离线、失败或送达未知不自动改投；命令、凭据留在本机，NAS 负责持久交付和回执。保存配置不会发送消息。

节点等待外援后会恢复原 CLI session，带入外援结果和新凭据继续同一个任务。等待前需记录真实 session，并配置准确的恢复命令；远端续跑固定原机器和 Agent。缺少会话、会话丢失或恢复失败时明确报错，不静默新建对话。

## 本地预览

需要 Python 3.9 或以上。在源码目录运行：

```sh
python3 -m loop_anything serve --demo --open
```

工作台默认地址为 [http://127.0.0.1:8767](http://127.0.0.1:8767)。保持平台进程运行，它会持续推进各个 Run；关闭浏览器页面不会停止平台。

页面顶部的「防休眠保护」开关作用于平台所在机器，无需重启；选择保存在当前工作区，服务重启后保留。关闭只释放平台的防休眠申请，Loop 仍继续运行，也不更改系统永久电源设置。实际保护失败时页面会显示原因。局域网模式下须先解锁编辑。本机未设置口令时可直接操作。`--allow-sleep` 作为没有保存网页选择时的初始值。


在 Loop 库打开详情，点击「启动」进入启动准备页，选择节点实现并填写本次目标。需要网页对话时，展开「网页使用的 Agent」填写本机命令；不配置时仍可通过表单启动。准备内容与对话会保存到本机。

`--demo` 注册研究与差旅两个模拟 Loop，不自动创建 Run。它们展示通用机制，不执行真实训练、预订或模型推理。参见 [示例说明](tests/scenarios/README.md)。

## 核心概念

| 名称 | 含义 |
| --- | --- |
| Loop | 可复用的节点、连接、构建模板和使用说明 |
| Run | 为一个目标启动的一次运行 |
| Node／节点 | 工作职责及输入输出契约 |
| Task／任务 | 本次 Run 中实际安排的工作，同一节点可产生多项任务 |
| Implementation／候选实现 | 具体的脚本、Agent 命令、外部服务或事件接入 |
| Binding／选用关系 | 任务或 Run 使用哪个候选实现 |
| Timeline | 目标、授权、任务、结果、执行记录和变更历史的整体 |
| Hooks | 临时通知、执行前暂停等控制动作 |

Timeline 的 `settings` 分区保存目标与运行设置，`tasks` 保存任务。`finish` 只释放 Agent 操作权，空任务列表不代表目标完成。

## 文档与 Skills

- [平台 Skill](skills/loop-anything-platform/SKILL.md)：按需读取 Loop 构建与 Timeline 操作说明。
- [平台运行说明](skills/loop-anything-platform/references/run.md)：启动、初始化和使用工具操作 Timeline。作者 Skill 直接绑定节点，随 Loop 包分享，处理任务时按需读取。
- [Timeline 协议](docs/timeline.md)：状态、任务、执行与终态契约。
- [候选实现与 Binding](docs/implementation-selection.md)：配置候选和运行时选择。
- [Agent 命令接入](docs/agent-integration.md)：用户 Agent 与后台命令的分工。
- [通知接口](skills/loop-anything-platform/references/notifications.md)：通用发送契约及可选适配器。
- [Loop 包](docs/loop-packages.md)：分享、安装和只读检查。
- [开发与发布](docs/development.md)：测试、构建和仓库结构。

当前为本地单机预览版本。最新协议尚未完成真实 Agent 业务全流程及 Windows/Linux 原生验收；外部副作用和通知发送由用户配置的实现负责。

## 聊天入口通知（0.5.7）

飞书入口由 Skill 客户端只随请求传递会话标识；平台保存来源并调度通知，适配器核实和调用 cc-connect。通知接入失败只记录通知状态，不阻断业务请求。私聊由入口 Bot 回复，群聊的执行确认和结果优先使用具名 Agent 的 `notification_bot={project,platform}` 所映射 Bot（旧 notification_route 兼容），并保持原话题。发送前明确不可用才回退入口，发送结果未知不自动换 Bot。嵌套外援继承原来源；显式通知出口覆盖，无聊天来源保留按机器优先级。先用 read_cc_connect/configure_cc_connect 接入本机桥接并发现 Bot，再用 communication_config 设置具名 Agent 的映射；无需自行拼接命令。完整前提、只读权限及 API 用法见平台 Skill 的 `references/cc-connect.md`；话题需开启 cc-connect 话题隔离并保留 root session key。
