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
- **和 Agent 一起设计**：说清目的，让 Agent 构建流程；也可以在画布上连接和编辑步骤。修改自动保存为草稿，准备好后“保存并使用”。
- **安排一次，持续推进**：保持平台运行，关闭网页也会继续；需要你时按配置发送通知。
- **启动前先选好**：为这次运行选择本地或远端等执行方式，在网页中与自己的 Agent 讨论，准备好再开始。
- **把好用的流程分享出去**：安装别人提供的 Loop，也能替换其中的执行方式。

![在画布上编辑步骤和连接](docs/images/loop-editor.png)

你可以在网页中与自己的 Agent 讨论并启动，运行后边看过程边调整；也可以直接在终端工作。也可以通过自己选择的聊天桥接接入飞书、微信，继续查看和修改同一次运行。平台附带可选的 cc-connect 通知适配器；真实聊天渠道需在你的环境中配置和联调。

想先看一眼：[本地预览](#本地预览)。准备安装：把本 README 链接交给自己的 Agent，让它按下面的说明完成。

## 安装平台

平台安装是一次性准备。把本 README 链接交给自己的 Agent，让它完成下面的步骤；日常操作使用平台 Skill。

1. 检查是否已有可用平台，默认地址为 `http://127.0.0.1:8767`；已有实例就复用。连接失败先确认服务与地址，不新建 Run 或数据库来测试。
2. 获取本仓库完整源码；已有发布附件时，也可获取其中的安装 ZIP。需要 Python 3.9 或以上及 pip/venv。源码安装还需要 Python 构建依赖；不要从同名第三方包代替安装。
3. 在源码或安装 ZIP 解压目录执行 `python3 install.py`，Windows 可用 `py -3 install.py`。安装器创建独立环境并返回平台 Python 和启动文件路径。
4. 用该 Python 执行 `-m loop_anything serve` 启动平台；需要界面时加 `--open`。使用当前 Agent 的进程管理能力保持服务运行，并确认任务结束后不会被自动清理；需要用户维持终端时如实说明。
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

指定已有工作区时，将 `--db 绝对路径` 放在 `serve` 等子命令前；平台不自动搬迁或合并数据库。平台状态 `/api/platform` 返回实际路径。换端口时同步 Skill 的 `connection.json`，也可用 `--url` 覆盖。

升级前确认没有在途操作，退出平台后用新源码或安装包执行原安装命令，保留原工作区。更新已安装的操作 Skill 时可使用导出命令的 `--replace`；已有内容不同会明确报告冲突。

0.2 以前的数据库使用旧字段，需要备份并转换；不要用新建空库代替原工作区。

</details>

## 本地预览

需要 Python 3.9 或以上。在源码目录运行：

```sh
python3 -m loop_anything serve --demo --open
```

工作台默认地址为 [http://127.0.0.1:8767](http://127.0.0.1:8767)。保持平台进程运行，它会持续推进各个 Run；关闭浏览器页面不会停止平台。

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
