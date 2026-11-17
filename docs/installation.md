# 安装与升级

安装 Loop Anything，一次具备本地工作台、任务工具和团队连接能力。日常按本地空间、团队空间使用，无需选择服务端或客户端。本文可在平台和 Skill 尚未安装时直接读取；日常构建、运行、通信和通知使用[平台 Skill](../skills/loop-anything-platform/SKILL.md)。

## 安装 Loop Anything

1. 复用已有安装、工作区和已记录地址。连接失败先确认平台与地址，不新建 Run 或数据库来测试。
2. 获取本仓库完整源码或发布的安装 ZIP。需要 Python 3.9 以上及 pip/venv；源码安装还需要 Python 构建依赖，不从同名第三方包替代安装。
3. 在源码或 ZIP 解压目录执行 `python3 install.py`（Windows 使用 `py -3 install.py`）。安装器创建独立环境，返回启动文件和 Python 路径，并登记 `loop-anything` 命令。升级保留已有个人地址、任务登记目录与启动配置；需要时可提供团队地址、默认空间和端口参数，默认无需填写。
4. 打开返回的 Loop Anything 启动文件。macOS 默认使用后台服务，关闭 Agent、终端或网页不会停止平台；Windows/Linux 使用前台启动器，需保持其进程运行。默认安装记录实际本地地址。
5. 可选：执行 `loop-anything spaces --team-url <团队地址>`，或在本地网页“平台地址与默认选择”设置配置团队地址。未手动指定默认时，只记录一个地址就使用它，两个都有时优先团队。切换不上传、合并或迁移已有工作。
6. 将平台操作、派单和本机调度 Skill 导出到当前 Agent 的 Skill 目录：

```sh
"<安装器返回的 Python 路径>" -m loop_anything skills --install-dir "<Agent Skill目录>" --url "<实际 NAS 或 HTTP 地址>"
```

7. 重新加载 Skill，执行 `loop-anything check` 检查所选空间，并用 `loop-anything tool list` 查看工具目录。也可在导出的平台 Skill 根目录执行 `python3 scripts/call.py check` 和 `list`。检查不调用模型、不创建 Run。

安装和查询不会启动旧定时任务或接单。需要执行时让 Agent 明确登记并启动。Agent 的模型、工具权限及启动参数由用户管理，Skill 安装不会替用户配置这些内容。

安装时也可以填写个人配置，例如：

```sh
python3 install.py --team-url https://team.example --default-space team
python3 install.py --port 8876
```

`--team-url`、`--team-web-url`、`--default-space auto|local|team` 只更新明确填写的个人设置；`--port` 用于指定监听端口，包括首次安装时避开占用。省略时沿用已有值，缺失的本地地址和登记目录才会初始化。没有安装角色、部署模式或跳过本地平台的选项。修改端口不会搬迁已有工作的原平台绑定；已有工作仍需原地址可用。

## 本地与团队空间

安装 Loop Anything 后即可使用本地工作台并连接团队空间。未手动指定时，按已记录地址自动选择，两个都有时优先团队。macOS 注册本地后台服务；Windows/Linux 启动器运行本地前台服务。个人服务仅监听回环地址，默认允许休眠；历史定时任务和接单不会因为安装而自动启动。

```sh
loop-anything spaces
loop-anything spaces --team-url https://team.example
loop-anything spaces --default team
loop-anything spaces --default local
loop-anything spaces --default auto
loop-anything tool list --space team
loop-anything client local list
```

空间决定工作记录的归属，执行位置由任务配置决定；团队任务可以交给本机 Agent 执行，连接团队空间本身不启动接单。

NAS 工具地址与网页地址可分别配置：`spaces --team-url nas:///挂载目录/team --team-web-url https://team.example`。默认配置在个人本机 `~/.config/loop-anything/spaces.json`；网页“平台地址与默认选择”设置与 Agent/CLI 共用它。地址与默认值通过 `loop-anything spaces` 配置；升级保留个人选择。更新 Skill 不修改地址或默认值。

脚本把创建或查询得到的资源绑定原平台，后续按资源 ID 自动接续；同名资源或无资源参数的后续操作使用返回的 `work_id`（`--work`），Agent 无需填写原地址。请求的 `routing_request_id` 用于原平台重试和查询，不随默认空间变化。本地不可用只报错，不转投团队。切换不上传本地数据；团队平台不提供个人配置读写。默认安装的本机任务登记目录与本地网页一致，显式 `--root` 仍可使用独立目录。

未指定 `--db` 的 `loop-anything tool` 与 `client tool` 使用相同的个人空间选择。显式 `--db` 表示直接操作指定本地工作区，不与 `--space`／`--url` 混用。

## 终端命令注册

安装后在新终端运行 `loop-anything --help`。安装器在用户 `~/.local/bin` 创建命令，并更新当前 shell 的 PATH：zsh 使用 `.zshrc`（尊重 `ZDOTDIR`），bash 使用 `.bashrc` 和现有登录配置，fish 使用 `conf.d`；Windows 更新用户 PATH，不改系统 PATH。重复安装更新同一登记段，保留其他配置，不覆盖无关同名命令。

已打开的终端环境不会被子进程自动改写；安装结果会打印一条即时生效命令，也可以直接打开新终端。已有安装可补登记：

```sh
"<已安装的 Python 路径>" -m loop_anything register
```

注册不启动服务、不创建数据库、不注册具名 Agent，也不启动接单或定时任务。

## 本地预览

在源码目录运行：

```sh
python3 -m loop_anything serve --demo --open
```

默认地址为 `http://127.0.0.1:8767`。示例展示模拟流程，不执行真实训练或预订；前台预览需要保持进程运行。已有服务占用默认端口或工作区时，请复用已有服务，或用独立的 `--db` 和 `--port` 启动预览。

## 安装位置、工作区与升级

安装器默认在用户数据目录的 `app/` 下创建环境，也可用 `--prefix 绝对路径` 指定。macOS 启动文件是 `Loop Anything.command`，Windows 是 `Loop Anything.cmd`，Linux 是 `loop-anything`。

| 系统 | 本地空间默认数据库 |
| --- | --- |
| macOS | `~/Library/Application Support/Loop Anything/runs.sqlite3` |
| Windows | `%LOCALAPPDATA%\Loop Anything\runs.sqlite3` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/loop-anything/runs.sqlite3` |

以下为 macOS 本地空间及团队平台的后台托管管理。macOS 后台服务使用系统 launchd，登录时自动启动；注销或关机时停止。手动“停止”会保持停止，直到再次“启动”，不会立即被自动拉起。异常退出由 launchd 重启；平台自身的恢复规则仍会保留无法确认停止的旧 Agent 操作权。

```sh
"<平台 Python 路径>" -m loop_anything service start --open
"<平台 Python 路径>" -m loop_anything service stop
"<平台 Python 路径>" -m loop_anything service status
"<平台 Python 路径>" -m loop_anything service remove
```

安装目录也提供 `Stop Loop Anything.command`。移除服务仅取消后台托管，不删除平台、Loop 包或数据库。开发调试使用安装后的 `service stop` 停止后台平台，再手动 `serve`；不要让前台预览与后台服务争用同一工作区或端口。安装时发现占用会报错，不擅自结束其他进程。

原生配置位于 `~/Library/LaunchAgents/com.loop-anything.platform.plist`，日志位于用户数据目录的 `logs/`；没有第二套平台服务配置。安装时保存 PATH 和显式配置的服务环境，不会复制全部终端环境。其他必需环境变量可按需配置到该 plist 的 EnvironmentVariables，停止后修改，再启动。

指定已有工作区时，将 `--db 绝对路径` 放在 `serve` 等子命令前；平台不自动搬迁或合并数据库。平台状态 `/api/platform` 返回实际路径。换本地端口或工作区时，用 `loop-anything spaces --local-url http://127.0.0.1:PORT --local-registry /绝对路径/workspace.db.schedules` 更新个人配置；已有任务仍使用其原地址。

升级前确认没有在途操作，再用新源码或安装包执行原安装命令。统一执行 `python3 install.py`，保留原 `--prefix`；安装器自动沿用已保存的后台服务配置，不再接收安装角色或部署模式参数。先正常停止本机调度和接单进程，升级后按需要明确启动。macOS 安装器先验证设置并备份原程序环境，再停止旧服务、更新并启动；可用性检查、安装或启动失败时恢复原环境、plist 和启动文件，只重新启动升级前正在运行的服务。如果恢复也失败，会保留备份并明确报告位置。不会以新库替代原工作区。Windows/Linux 保留原前台启动器的工作区和启动命令；显式 --port 只修改该命令的端口，不猜测自定义任务登记目录对应哪个数据库。前台平台先退出进程再升级。

升级后也要更新 Agent 实际加载的 Skill，保留原 `--url` 或 `--only local` 并在导出命令中加 `--replace`；已有内容不同且未指定更新时会明确报告冲突。随后重新加载 Skill；连接服务的客户端执行 `scripts/call.py check`，仅本机调度用 `client local --help` 核对入口。仅替换源码不会自动刷新 Agent 的 Skill。

安装器不转换旧数据格式，也不以新建空库替代已有工作区。

## 安装后运行团队平台

所有机器统一安装 Loop Anything。普通成员填写团队地址即可；需要提供团队平台时，在安装后配置服务运行方式。

### 内部共享访问

在可信内网的一台机器上运行平台，其他人通过浏览器访问 `http://服务器地址:8767`。默认仅监听本机；开放内部监听时：

```sh
python3 -m loop_anything --db /绝对路径/runs.sqlite3 serve --space team --host 0.0.0.0
```

macOS 安装后先执行 `loop-anything service stop`，再执行 `loop-anything service install --space team --host 0.0.0.0` 配置团队服务。未指定的工作区和端口沿用已有配置。

共享访问面向可信内部环境。多机 Agent 协作见[通信说明](../skills/loop-anything-platform/references/communication.md)。

### 固定连接测试地址

其他机器可访问 `http://服务器地址:实际端口/api/health`，成功返回 HTTP 200 和 `{"ok":true,"service":"loop-anything","version":"..."}`，无需凭据或特殊请求头。使用实际监听端口，并按上文让服务监听可访问地址。

```sh
curl -fsS --max-time 5 http://服务器地址:8767/api/health
# 如果入口经过 HTTPS 代理，调用方用 -k 跳过证书与主机名校验：
curl -kfsS --max-time 5 https://服务器地址/api/health
```

平台原生监听 HTTP，不涉及 HTTPS 证书校验，也不向外部服务发起验证。HTTPS 代理入口的证书检查发生在调用方，服务端接口无法替调用方关闭。此地址只用于可选的 HTTP 连通性测试，不证明 Agent 或外部任务可运行，不创建 Run 或启动任务；`--no-web` 模式没有 HTTP 接口。完整工具连接检查继续使用 `scripts/call.py check`。

### NAS 团队平台与执行机器

内部职责与完整操作见[团队运行说明](../skills/loop-anything-platform/references/team-runtime.md)。先用 `python3 install.py` 安装，再启动团队服务；前台运行时由团队已有进程托管方式维持服务。macOS 先停止自动安装的后台平台，避免同时打开同一工作区。数据库与 NAS 通信目录分别指定：

```sh
"<安装器返回的 Python 路径>" -m loop_anything --db /srv/loop-anything/workspace.sqlite3 serve --space team --team-dir /nas/team/loop-anything
# 仅通过 NAS 通信、不提供 HTTP 或网页时，加 --no-web。
```

`--db` 是服务端的数据位置，可在服务器本地或其他持久目录；`--team-dir` 仅用于请求、回执、执行派发和传输分片。Loop 包、运行配置与结果留在服务端，接收端通过通信取得声明的脚本和 Skill。省略 `--db` 时，新部署使用本机默认数据库。已有数据库须通过 `--db` 明确指定；不提供旧格式转换。

NAS 通信统一使用这个根目录，内部由平台管理：`api/` 保存平台调用和回执，`executors/` 保存客户端执行派发与会话控制，`agents/` 保存具名 Agent 目录、派单、求助和回复。服务端启动时自动连接 `agents/` 团队；具名 Agent 的职责与开放范围仍按用户确认配置。独立派单 Skill 的 `join` 和平台 `communication_config(operation=team,link=...)` 都填写同一个根目录或 `nas:///...` 链接，无需单独记子目录地址。

NAS 团队只使用统一根目录下的 agents/ 布局，不识别旧平铺目录。新建或重新连接统一 NAS 入口时，用于后续 NAS 派单；飞书 Base 的优先级不变。已退出的具名通信团队不会因服务重启而被自动重新启用。

同一 NAS 收件箱只由一个服务处理，并绑定原工作区身份。迁移服务器时，先停止旧服务并保留／恢复完整服务端工作区（数据库及旁边的 packages、loop-configs、结果等目录），再连接原收件箱。NAS 消息不能代替数据库备份；客户端无需挂载服务端数据目录。

## 安装后的命令与 Skill

安装一次即可使用 `loop-anything tool` 操作平台，使用 `loop-anything client local` 管理本机任务及接单。三个 Skill 按平台工作、派单、本机调度组织说明，不代表不同安装方式。

导出的平台 Skill 与安装后的命令共用个人空间配置和原平台绑定记录。更新 Skill 不修改默认地址，也不启动旧任务；接单和个人调度仍需明确启动。


当前 0.6.19 使用 API revision 10。平台不为旧实现增加兼容转换或回退，也不按存储格式编号人为拒绝可用数据；读取时校验实际所需结构。安装包构建和验证使用独立临时工作区，不自动替换正在运行的用户工作区。
