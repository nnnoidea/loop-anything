# 安装与升级

平台安装是一次性准备，本文可在平台和 Skill 尚未安装时直接读取。日常构建、运行、通信和通知使用[平台 Skill](../skills/loop-anything-platform/SKILL.md)。

1. 检查是否已有可用平台，默认地址为 `http://127.0.0.1:8767`；已有实例就复用。连接失败先确认服务与地址，不新建 Run 或数据库来测试。
2. 获取本仓库完整源码；已有发布附件时，也可获取其中的安装 ZIP。需要 Python 3.9 或以上及 pip/venv。源码安装还需要 Python 构建依赖；不要从同名第三方包代替安装。
3. 在源码或安装 ZIP 解压目录执行 `python3 install.py`，Windows 可用 `py -3 install.py`。安装器创建独立环境并返回平台 Python 和启动文件路径。macOS 默认同时注册并启动系统用户后台服务；已有工作区请加 `--db 绝对路径`，已有非默认端口加 `--port 端口`。
4. macOS 安装成功后用该 Python 执行 `-m loop_anything service status` 确认服务与实际工作区，或双击安装目录的 `Loop Anything.command` 打开页面。关闭 Agent 应用、终端和浏览器均不停止后台服务。Windows/Linux 当前仍使用 `-m loop_anything serve --open` 前台运行，需要独立终端保持运行；尚未提供其系统服务安装。
5. 将完整[平台操作 Skill](../skills/loop-anything-platform/SKILL.md)导出到当前 Agent 支持的 Skill 目录，写入实际平台地址。Skill 包含 Loop 构建、Timeline 操作说明及调用脚本，不包含平台安装手册：

```sh
"<平台 Python 路径>" -m loop_anything skills --install-dir "<Agent Skill目录>" --url http://127.0.0.1:8767
```

6. 在安装后的 Skill 根目录，用本机兼容 Python 执行 `python3 scripts/call.py check` 和 `list`，核实连接、工作区、工具目录和防休眠状态。其他工作目录使用脚本绝对路径。安装与检查不调用模型，不创建业务 Run。

平台程序位于 `loop_anything/`，操作 Skill 位于根目录 `skills/`。Agent 的模型、工具权限及启动参数由用户管理，Skill 安装不会替用户配置这些内容。

## 安装位置、工作区与升级

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

## 内部共享访问

在可信内网的一台机器上运行平台，其他人通过浏览器访问 `http://服务器地址:8767`。默认仅监听本机；开放内部监听时：

```sh
python3 -m loop_anything --db /绝对路径/runs.sqlite3 serve --host 0.0.0.0
```

macOS 首次后台安装使用 `python3 install.py --host 0.0.0.0`；已有后台服务先 `service stop`，再 `service install --host 0.0.0.0`。未指定的工作区和端口沿用已有配置。

共享访问面向可信内部环境。Loop 编辑口令见[连接说明](../skills/loop-anything-platform/references/connection.md)，多机 Agent 协作见[通信说明](../skills/loop-anything-platform/references/communication.md)。
