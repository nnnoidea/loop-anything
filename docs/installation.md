# 安装与升级

平台安装是一次性准备，本文可在平台和 Skill 尚未安装时直接读取。日常构建、运行、通信和通知使用[平台 Skill](../skills/loop-anything-platform/SKILL.md)。

**安装前先询问用户：本机需要服务端、客户端，还是兼任两者？** 已有明确选择时直接沿用，不重复询问。按选择使用对应命令：

| 用户选择 | 安装命令 | 本机用途 |
| --- | --- | --- |
| 服务端 | `python3 install.py --role server` | 保存 Loop、Run 并推进流程，提供网页 |
| 客户端 | `python3 install.py --role client` | 操作已有服务，以及本机接单执行、个人定时或条件任务 |
| 兼任两者 | `python3 install.py --role server` | 服务端安装已包含客户端能力，只需安装一次 |

安装及升级时显式保留所选 `--role`；为兼容旧用法，省略该参数仍会按服务端安装。客户端安装不注册或启动服务，也不会自动接单或启动个人任务。

1. 复用已有安装和服务。客户端使用实际 NAS 或 HTTP 地址连接团队服务；仅使用个人调度无需服务。本机服务默认地址为 `http://127.0.0.1:8767`。连接失败先确认服务与地址，不新建 Run 或数据库来测试。
2. 获取本仓库完整源码；已有发布附件时，也可获取其中的安装 ZIP。需要 Python 3.9 或以上及 pip/venv。源码安装还需要 Python 构建依赖；不要从同名第三方包代替安装。
3. 在源码或安装 ZIP 解压目录执行上表所选命令；Windows 将 `python3` 换成 `py -3`，保留 `--role`。安装器创建独立环境并返回 Python 和启动文件路径。macOS **服务端**默认注册并启动用户后台服务；已有工作区加 `--db 绝对路径`，已有非默认端口加 `--port 端口`。前台托管服务端加 `--no-service`。
4. **服务端**：macOS 用返回的 Python 执行 `-m loop_anything service status` 确认服务与工作区，或双击 `Loop Anything.command` 打开页面。关闭 Agent、终端和浏览器不停止后台服务。Windows/Linux 使用 `-m loop_anything serve --open` 前台运行，尚未提供其系统服务安装。**客户端**：用返回的 Python 执行 `-m loop_anything client --help` 查看操作与本机任务入口；需要接单时按[本机调度 Skill](../skills/loop-anything-local/SKILL.md)登记并明确启动。
5. 将平台操作、派单和本机调度 Skill 导出到当前 Agent 的 Skill 目录，写入实际服务地址。Skill 包含 Loop 构建、Timeline 操作说明及调用脚本，不包含平台安装手册：

```sh
"<安装器返回的 Python 路径>" -m loop_anything skills --install-dir "<Agent Skill目录>" --url "<实际 NAS 或 HTTP 地址>"
```

6. 需要连接服务时，在导出的 `loop-anything-platform` Skill 根目录执行 `python3 scripts/call.py check` 和 `list`，核实连接、工作区和工具目录。其他工作目录使用脚本绝对路径。仅使用个人调度时，第 5 步改用 `skills --only local --install-dir "<Agent Skill目录>"`，无需服务地址或连接检查。安装与检查不调用模型，不创建业务 Run。

平台程序位于 `loop_anything/`，操作 Skill 位于根目录 `skills/`。Agent 的模型、工具权限及启动参数由用户管理，Skill 安装不会替用户配置这些内容。

## 本地预览

在源码目录运行：

```sh
python3 -m loop_anything serve --demo --open
```

默认地址为 `http://127.0.0.1:8767`。示例展示模拟流程，不执行真实训练或预订；前台预览需要保持进程运行。已有服务占用默认端口或工作区时，请复用已有服务，或用独立的 `--db` 和 `--port` 启动预览。

## 安装位置、工作区与升级

安装器默认在用户数据目录的 `app/` 下创建环境，也可用 `--prefix 绝对路径` 指定。macOS 启动文件是 `Loop Anything.command`，Windows 是 `Loop Anything.cmd`，Linux 是 `loop-anything`。

| 系统 | 服务端默认数据库 |
| --- | --- |
| macOS | `~/Library/Application Support/Loop Anything/runs.sqlite3` |
| Windows | `%LOCALAPPDATA%\Loop Anything\runs.sqlite3` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/loop-anything/runs.sqlite3` |

以下后台服务管理仅适用于服务端。macOS 后台服务使用系统 launchd，登录时自动启动；注销或关机时停止。手动“停止”会保持停止，直到再次“启动”，不会立即被自动拉起。异常退出由 launchd 重启；平台自身的恢复规则仍会保留无法确认停止的旧 Agent 操作权。

```sh
"<平台 Python 路径>" -m loop_anything service start --open
"<平台 Python 路径>" -m loop_anything service stop
"<平台 Python 路径>" -m loop_anything service status
"<平台 Python 路径>" -m loop_anything service remove
```

服务端安装目录也提供 `Stop Loop Anything.command`。移除服务仅取消后台托管，不删除平台、Loop 包或数据库。开发调试可以用 `python3 install.py --role server --no-service` 仅安装程序，再手动 `serve`；不要让前台预览与后台服务争用同一工作区或端口。安装时发现占用会报错，不擅自结束其他进程。

原生配置位于 `~/Library/LaunchAgents/com.loop-anything.platform.plist`，日志位于用户数据目录的 `logs/`；没有第二套平台服务配置。安装时保存 PATH 和显式配置的服务环境，不会复制全部终端环境。其他必需环境变量可按需配置到该 plist 的 EnvironmentVariables，停止后修改，再启动。

指定已有工作区时，将 `--db 绝对路径` 放在 `serve` 等子命令前；平台不自动搬迁或合并数据库。平台状态 `/api/platform` 返回实际路径。换端口时同步 Skill 的 `connection.json`，也可用 `--url` 覆盖。

升级前确认没有在途操作，再用新源码或安装包执行原安装命令，保留 `--prefix` 和角色：客户端为 `--role client`，服务端或兼任为 `--role server`，前台部署同时保留 `--no-service`。客户端先正常停止本机调度和接单进程，升级后按需要明确启动。macOS 后台服务端由安装器停止旧服务、更新程序，再按原工作区、端口和监听地址启动；不会新建空工作区。前台服务端先退出进程再升级。

升级后也要更新 Agent 实际加载的 Skill，保留原 `--url` 或 `--only local` 并在导出命令中加 `--replace`；已有内容不同且未指定更新时会明确报告冲突。随后重新加载 Skill；连接服务的客户端执行 `scripts/call.py check`，仅本机调度用 `client local --help` 核对入口。仅替换源码不会自动刷新 Agent 的 Skill。

0.2 以前的数据库使用旧字段，需要备份并转换；不要用新建空库代替原工作区。

## 内部共享访问

在可信内网的一台机器上运行平台，其他人通过浏览器访问 `http://服务器地址:8767`。默认仅监听本机；开放内部监听时：

```sh
python3 -m loop_anything --db /绝对路径/runs.sqlite3 serve --host 0.0.0.0
```

macOS 首次后台服务端安装使用 `python3 install.py --role server --host 0.0.0.0`；已有后台服务先 `service stop`，再 `service install --host 0.0.0.0`。未指定的工作区和端口沿用已有配置。

共享访问面向可信内部环境。多机 Agent 协作见[通信说明](../skills/loop-anything-platform/references/communication.md)。

## 服务端与客户端

角色和完整操作见[团队运行说明](../skills/loop-anything-platform/references/team-runtime.md)。服务端用 `install.py --role server` 安装，用 `serve --team-dir /nas/team/loop-anything` 托管团队工作区；仅 NAS 接入可加 `--no-web`。集群前台部署可加 `--no-service`，由团队已有进程托管方式维持服务。

客户端用 `python3 install.py --role client` 安装，统一提供查看、编辑、运行 Loop，以及本机接单执行和个人定时/条件任务。使用安装返回的 Python 执行 `-m loop_anything skills --install-dir <Agent Skill目录> --url nas:///本机挂载路径/team/loop-anything`，一次导出平台操作、派单、本机调度三个按场景读取的 Skill。客户端不启动服务数据库或网页。

`-m loop_anything client tool <TOOL> --url <NAS或HTTP地址>` 调用服务工具；`-m loop_anything client local --root <登记目录> ...` 管理本机任务和接单。导出的平台 Skill 仍可通过 `scripts/call.py` 复用 `connection.json` 中保存的地址。个人登记放在约定目录（可选 NAS）；安装、登记、查询和升级均不会启动旧任务，明确 `client local ... start ID` 才开始运行。接单本身也是一个这样的登记任务。

只操作服务或派单时，仍可仅复制导出的 Skill 并使用 Python 3.9+，无需安装运行程序。只使用个人调度时，可用 `skills --only local --install-dir <Agent Skill目录>` 导出小型 Skill，无需平台地址。这些是同一客户端的按需使用方式；服务端与客户端共用安装包，旧 `--role platform` / `--role local` 分别兼容为 server/client，旧 `local` 命令及已登记任务、执行端 ID 保留。
