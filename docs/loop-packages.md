# 统一 Loop 包：分享、安装、smoke、运行

当前支持 v2 Loop 定义，扩展名 `.loop.zip`。普通包使用 `loop-anything-package/1`；使用事件路由、稳定引用、扩展契约、流程验收或显式 requires 的包自动使用 `loop-anything-package/2`，并保存所需 capability IDs。旧服务明确拒绝新格式，接收服务也会检查实际能力。
没有“Loop 定义包 / 半成品包 / 完整包”三种类型：同一格式允许零、部分、全部节点配置实现。
结构有效即可分享、安装；缺失绑定只在实际需要执行相应任务时报告，不会自动补成 Agent 或模拟实现。
历史 Run 保留；旧 v1 定义只读。原 CLI publish 复用相同包安装路径。

## 包内内容

根文件 `loop.json` 保存 loop_definition、可选 implementations、可选 checks、能力要求 requires 以及格式与资源清单。
手册和节点 Skill 如果已内嵌 loop_definition，会原样保留。其它脚本/文档/资源必须明确选择附带。
文件清单包含内容校验值和可执行标记；同一内容可重复安装，不覆盖已有文件。
内容不同的部分/完整实现可以并存，即使其 loop_definition.id/version 相同。

包内普通文件按相对路径保存。平台不收集 Run 数据库、历史日志或全局配置，不运行安装脚本。
目录穿越、绝对资源路径、符号链接、重复/大小写冲突、文件目录冲突、清单不匹配会被拒绝。
首版上限为 20 MiB（压缩包及展开内容）、256 个文件（包含清单），不用于搬运训练数据或模型权重。
`.git`、`.loop-anything`、`.codex`、`.ssh`、`.venv`、`__pycache__`、`.env`/`.env.*` 不可作为资源附带。
这不是完整的凭证扫描器：作者仍需检查 JSON、命令参数和其它文件，不要把密钥或个人数据写进包。
校验值只验证完整性，不证明作者可信；仅运行可信来源的实现。执行器没有新增隔离沙箱。

## 工作台

1. 在 Studio 中设计Loop 定义。通过候选实现表单选择执行方式；新节点不自动绑定 Agent。
2. 编辑自动保留草稿；点击“保存”统一校验并更新本机可用版本，保存后留在编辑页。版本号自动管理，相同内容重复保存不增加版本；已有 Run 保留原定义。
3. 需要管理随包文件或分享时，打开“更多 → 文件与打包”，选择资源并下载 `.loop.zip`。打包独立于日常保存，资源和 smoke 声明随草稿保存。
   选择 `scripts` 文件夹会保留 `scripts/task.py`；单选普通文件时文件放在包根目录。
   浏览器附带的新文件默认不设置可执行位，可用 `python3 scripts/task.py` / `bash scripts/task.sh` 启动；
   CLI 打包会保留所选文件的可执行位。
4. 接收方用目录页“导入 Loop 包”，先查看包内容；可载入草稿继续完善，或“安装（不启动）”。
5. 安装后查看 smoke。缺绑定也可以创建 Run；已有多个候选时直接在启动表单选择，无需复制 Loop。

复制已安装包时读取的是作者原始绑定和附带资源，不把接收机生成的工作目录带回新包。
原来的“下载 JSON”仍只是定义导出；需要携带资源时使用“Loop 包”。

## CLI

准备 `definition.json`，包含 `loop_definition` 和可选 `implementations`/`checks`。
例如 implementations 可只包含一个节点，未提供的节点保持未绑定：

```json
{
  "initialize": {
    "kind": "command",
    "command": ["python3", "scripts/initialize.py"]
  }
}
```

在安装了平台的环境中运行（以下使用与现有项目一致的模块入口）：

```sh
python3 -m loop_anything pack definition.json --include scripts --output example.loop.zip
python3 -m loop_anything --db ./state/runs.sqlite3 install example.loop.zip
python3 -m loop_anything --db ./state/runs.sqlite3 smoke <安装返回的key>
python3 -m loop_anything --db ./state/runs.sqlite3 run <安装返回的key> --port 8767
```

纯Loop 定义不传 `--include` 即可；可多次指定 `--include`。文件路径相对于 definition.json 所在目录。
pack 不覆盖已有输出。install 返回内容标识 `pkg-...` 和缺失绑定，不启动 Run。
`run` 持有单 Engine 锁，通过预检后创建 Run，并在前台启动现有本地平台服务。
不需要服务器桌面或浏览器；Run 完成后服务仍保持运行，Ctrl+C 停止服务但保留数据库。
需要长期后台运行时由使用者托管进程，本轮不安装系统服务或自动管理服务器。
若已有同库平台服务运行，通过其本地界面/API 创建 Run；不要再启动第二个 Engine。

## 路径与配置：解析约定不等于自动修复

- 默认工作目录为包安装目录；作者声明的相对 cwd 基于该目录解析。
- argv 和绝对 cwd 原样保留，不替换 Python、Agent、数据目录、服务地址或模型。
- 原始 manifest/绑定不修改，解析后的 cwd 只作为本机节点实现。
- 不展开命令字符串里的 `~` 或 `${VAR}`，不猜测作者意图。命令仍为 argv，不自动调用 shell。
- 更改包内容后重新打包、安装；不要手工覆盖安装缓存。smoke 发现清单/资源变化只报错，不修复。
- 不迁移正在运行的 Programmable Timeline 或历史记录；包安装后开始的是新的 Run。

## smoke 的范围

可选声明示例：

```json
{
  "checks": {
    "paths": ["/srv/datasets/validation"],
    "programs": ["codex"],
    "env": ["TRAINING_API_TOKEN"]
  }
}
```

smoke 只读取文件和环境，检查：包清单/资源完整性、未绑定节点、cwd、执行程序、
显式脚本入口（argv 第二项为 .py/.sh/.js/.mjs）以及作者声明的 paths/programs/env。
环境变量仅报告是否存在，不返回值。smoke 不创建缺失目录或数据库，不执行任何 Handler、
模型探测、安装命令、网络请求或业务副作用，不修改参数或依赖。

结果包含 `package_valid`、`ready`、`unbound_nodes` 和逐项 pass/fail/unknown。
CLI 有明确失败时退出码为 2；无已知失败时为 0。unknown 不能当作验证成功。
任意命令参数语义、Python/JS 模块导入、模型授权、外部服务和业务结果均不在静态预检保证范围。
未配齐实现仍可创建 Run；实际需要执行任务时才报告缺失实现。
显式 event、approval 或无 command 的 agent 绑定可以保留，但会提示需要外部输入，并非无人值守可执行保证。

## Skill 交付

包中的作者说明和节点 Skill 保持原文。作者 Skill 直接保存在对应节点的 skills 中，可用 put_node 编辑；Agent 用 read_task 按需读取。Loop 详情导出同一种 .loop.zip，包含节点 Skill 与附件。平台 Skill 单独下载，只教通用工具操作，不再生成作者 Skill 封装或要求额外安装。

候选结构和选择工具见 [候选实现与 Binding](implementation-selection.md)。


## 可选运行级检查

在 Loop 的“使用准备 → 运行级检查”中显式执行，或使用 CLI：

```sh
python3 -m loop_anything --db ./state/runs.sqlite3 smoke-runtime <key> --timeout 30
python3 -m loop_anything --db ./state/runs.sqlite3 smoke-runtime <key> --node runtime_repair --implementation repair_agent
```

平台工具 `smoke_runtime` 接受相同的 key、node_id、implementation_id、timeout，以及可选 cases 数组。此工具会运行命令，网页需编辑授权；原有 `smoke` 继续只读。

- Agent 检查按已安装候选的原始 argv、实际 cwd 和当前进程环境发送最小响应请求，包含兜底候选；可能调用已配置模型。timeout 是每次检查的上限，候选更短的显式超时仍有效。平台不添加信任参数、替换模型或修复环境。
- external 检查在临时 Timeline 中使用真实的 report/retry 写入逻辑，覆盖已声明事件和 process_error/check_error，检查重复事件、原 Task 重试及重试后的观察失败。不会执行真实 submit/observe、发送外部通知或修改业务 Run；模拟输出契约为空，业务输出和服务连通性另行验收。
- 有条件分支或必填参数时，通过 `--cases cases.json` 提供代表性上下文。未提供所需上下文标记 unknown，不算验证通过。每个 case 指定 node、implementation、state、event，可提供 attempt、parameters、inputs、settings、detail 和 expected（预期目标状态）。例如：

```json
[{"node":"train","implementation":"remote","state":"waiting","event":"failed","attempt":3,"expected":"agent"}]
```

报告的 `ready` 表示没有已知失败；`verified` 只有全部检查均 pass 才为 true。unknown 和未覆盖的业务验收不会被标记成成功；CLI 有明确失败时退出码为 2。

## 构建验收与能力发现

`read_capabilities` 返回服务版本、启动时 build、磁盘 source_build、restart_required 和全部公开工具的能力分组。CLI list 与 HTTP 工具目录同样包含 service 信息；网页显示运行服务版本，后台/网页 Agent 上下文携带实际服务能力。源码更新不会自动升级已启动进程。

`preview_plan` 只展开和校验草稿，`test_loop` 在隔离数据库中运行作者提供的模拟报告和断言。场景保存在 loop_definition.scenarios 并随包交付，编辑器「更多 → 流程验收」可保存和运行。入口与详细示例见 [平台测试手册](../skills/loop-anything-platform/references/testing.md)。

能力发现还包括无需独立工具调用的调度、持久化、重启恢复、实现选择、原生查看和主机服务。create_loop/copy_loop/完整 read_loop 返回 authoring_context；read_capabilities 按机制说明 activation、平台职责、作者职责、配置、边界和组合示例。导出的 platform-capabilities.md 从同一份机制定义生成。
