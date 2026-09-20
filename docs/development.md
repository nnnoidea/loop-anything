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
README.md            项目介绍与一次性平台安装说明
install.py           独立环境安装器
pyproject.toml       包元数据与 CLI 入口
```

`.local-history/` 保存本地历史资料，`.semantic-alignment/` 保存研发语义记录；它们均不提交。`.loop-anything/`、旧 `.state-loop/` 和用户数据目录中的运行数据不属于源码发布内容。

macOS 安装器默认使用 launchd 用户服务；测试或临时环境安装加 `--no-service`，避免注册真实登录项。`service` 命令只调用系统服务管理器；配置使用原生 plist。收到 SIGTERM 与 Ctrl+C 一样走平台退出清理。Windows/Linux 当前仍为前台启动。

平台安装将同一 Skill 资源放在环境的 `share/loop-anything/skills/` 下，供导出及唤醒引用；源码直接使用根目录 `skills/`。

Skill 客户端只在 `skills/loop-anything-platform/scripts/call.py` 维护；导出直接收集 Skill 目录，不另复制一套不同命名的源码。根目录旧 `examples/simulated_tasks.py` 仅为既有本地运行保留命令路径，不纳入发布。

## 验证

从源码根目录运行：

```sh
python3 -m unittest discover -s tests
node --test tests/library.test.js tests/task-history.test.js
```

浏览器验收需要本机已有 Chrome，以及 Node 可找到的 Playwright：

```sh
node tests/library-browser.cjs
node tests/visual-browser.cjs
node tests/web-agent-browser.cjs
node tests/edit-access-browser.cjs
```

它使用隔离的临时数据库。普通测试使用模拟结果或本地命令，不调用真实模型。真实 Agent 场景需另外明确模型、环境和业务边界。

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
