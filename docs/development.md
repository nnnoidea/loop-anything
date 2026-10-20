# 开发与发布

## 仓库结构

```text
loop_anything/
  __main__.py        平台命令入口
  paths.py           共用的安装与数据路径
  runtime/           状态模型、存储、调度和系统进程支持
  interfaces/        HTTP 与平台、Agent 任务工具
  packaging/         Loop 包和平台 Skill 的导入导出
  web/               可视化界面
  examples/          随平台安装的模拟 Loop 与节点实现
skills/              可独立安装到 Agent 的平台操作 Skill、调用脚本及连接文件
tests/               行为测试及浏览器验收
  scenarios/         主动运行、保留结果的模拟场景验收
scripts/             构建脚本
docs/                现行协议和开发说明
README.md            项目介绍、当前界面截图与安装入口
docs/installation.md 一次性安装、升级与工作区说明
install.py           独立环境安装器
pyproject.toml       包元数据与 CLI 入口
```

`SEMANTICS.md` 是当前产品语义入口，`semantics/` 按主题保存权威正文；二者作为本地研发记录不提交。`.local-history/` 保存研发历史与一次性迁移备份，旧 `.semantic-alignment/` JSON 记录已退出日常读取。`.loop-anything/`、旧 `.state-loop/` 和用户数据目录中的运行数据不属于源码发布内容。

本机平台身份按需保存在用户数据目录的 `identity.sqlite3`，独立于工作区数据库。它保存完整机器 UUID、显示名称及本机工作区路径登记；SQLite 事务保证并发首次读取取得同一身份，并区分正常移动与仍存在的副本。默认目录复用 paths.data_directory；测试或独立平台用户环境可显式设置绝对本地目录 `LOOP_ANYTHING_IDENTITY_DIR`。它应保留在本机，不放在共享 NAS 或随业务数据库复制；不同系统账户/身份目录视为独立平台环境，整份身份目录被克隆后的重复身份不靠硬件检测自动修正。

macOS 安装器默认使用 launchd 用户服务；测试或临时环境安装加 `--no-service`，避免注册真实登录项。`service` 命令只调用系统服务管理器；配置使用原生 plist。收到 SIGTERM 与 Ctrl+C 一样走平台退出清理。Windows/Linux 当前仍为前台启动。

平台安装将同一 Skill 资源放在环境的 `share/loop-anything/skills/` 下，供导出及唤醒引用；源码直接使用根目录 `skills/`。

执行生命周期的计算在 `runtime/transitions.py`：`decide_transition` 接收规则、当前阶段、事件、数据上下文与任务参数，返回规则选择及展开结果；`transition_effects` 接收校验结论与调用方提供的时间，返回要应用的状态字段。两者不读写数据库、读取时钟或派发任务。重试参数校验优先于通知错误，保持原错误回执。`TimelineRuntime.report_in_run` 在原事务内完成去重、契约校验、路由准备，再提交结果、应用状态与记录历史。不要缓存计算结果后脱离原事务写入；这些是内部函数，没有新增对外工具或状态覆盖协议。

Agent 的 Timeline 乐观提交在 `runtime/optimistic.py`：读取依据随既有 Agent 身份保存，业务修订不包含这些读取元数据。提交在 `Store.edit` 短事务中验证相关 Task／输入／最新记录／设置，失败整组回滚；明确历史记录保持固定版本，日志不影响决策版本。执行身份和 Task 子树资格仍保留，同 Task 及原生 CLI 会话的重复执行保护不依赖 Timeline 排他锁。finish 后尚未退出的恢复终端和远端执行沿原 worker_active／communication_state 保留进程保护；重启从现有终端记录恢复未知状态，确认停止后解除。批量修改和预览同样检查 affected Task 的读取依据。

Skill 客户端只在 `skills/loop-anything-platform/scripts/call.py` 维护；导出直接收集 Skill 目录，不另复制一套不同命名的源码。根目录旧 `examples/simulated_tasks.py` 仅为既有本地运行保留命令路径，不纳入发布。

## 验证

从源码根目录运行：

```sh
LOOP_ANYTHING_IDENTITY_DIR="$(mktemp -d)" python3 -m unittest discover -s tests
node --test tests/library.test.js tests/task-history.test.js
```

浏览器验收需要本机已有 Chrome，以及 Node 可找到的 Playwright：

```sh
node tests/library-browser.cjs
node tests/visual-browser.cjs
node tests/web-agent-browser.cjs
```

它使用隔离的临时数据库。普通测试使用模拟结果或本地命令，不调用真实模型。真实 Agent 场景需另外明确模型、环境和业务边界。

浏览器及手动多实例验收也应设置临时 `LOOP_ANYTHING_IDENTITY_DIR`，避免测试工作区登记到日常身份目录。模拟不同机器时分别使用不同身份目录；同一目录中的不同数据库模拟同机不同工作区。

## 构建

构建环境需要 setuptools、wheel 和 pip：

```sh
python3 scripts/build_distribution.py
```

输出写入被忽略的 `dist/`：安装 ZIP、wheel，以及独立静态 `agent-entry/`。安装包包含当前安装器、源码、Skills 和文档；不包含运行数据或历史实验。

GitHub 源码入口使用根目录 `README.md`；安装 ZIP 和 wheel 作为 Release 附件发布，不提交到源码仓库。单独托管静态入口时，保留 `agent-entry/` 与安装 ZIP 的相对位置。

## 发布前

检查实际拟提交清单与文档链接，验证从安装包在源码目录之外安装和启动。发布时由维护者确定仓库、许可证和版本说明，再上传源码与构建附件。当前源码尚未附带开源许可证，不能把准备好的文件视为已经授予某种许可证。

0.2 之前的数据库和 Loop 包需要先转换字段；0.2 的单实现简写继续可用。历史数据不要用新建空库替代。
