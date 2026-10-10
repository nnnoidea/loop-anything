---
name: loop-anything-platform
description: 使用已安装的 Loop Anything 构建与运行 Loop，操作 Timeline；发现并调用本机或 NAS 群组中的具名 Agent，支持无 Loop 的独立外援。业务方法按需读取节点 Skill。
metadata:
  provider: loop-anything-platform
---

# Loop Anything 平台

本 Skill 只教通用的平台与工具使用。具体 Loop 的用途和输入要求见作者说明；作者 Skill 直接绑定在节点上，处理任务时用 read_task 读取对应内容。它们随 Loop 包交付，无需另外安装一层作者 Skill。

## 按当前任务读取

- 本机具名 Agent、NAS 通信群组、远程节点或无 Loop 的独立外援：读取 [communication.md](references/communication.md)。先发现成员和调用范围，再发请求；普通 CLI 会话不会自动开放调用。
- 构建或迁入 Loop：先读 [build.md](references/build.md) 的分工与能力地图，结合构建回执的 authoring_context 选择机制，再接入业务实现；详细分工按需查 [platform-capabilities.md](references/platform-capabilities.md)。事件到模板的参数映射用节点 routes，平台自动生成 Task。
- 既有草稿的定向修改、字段与资源操作：按需查 [build-reference.md](references/build-reference.md)。
- 直接使用通用工具启动 Run 或修改 Timeline：按需读取 [run.md](references/run.md)。作者已提供封装脚本和说明时，运行时优先按作者入口操作，无需先读平台手册。已经有 Run 和令牌时，不重新创建 Run。

- 配置通知出口、发送通知/询问、提交回复或接入现有聊天桥接：读取 [notifications.md](references/notifications.md)。

- 条件参数契约、按业务标识引用任务和展开预览：读取 [contracts.md](references/contracts.md)。
- 保存可重复的构建验收场景、检验路由与收口：读取 [testing.md](references/testing.md)。

create_loop、copy_loop 和完整 read_loop 会主动返回 authoring_context，说明平台已经承担的职责和作者需要提供的内容。read_capabilities 的每项能力包含 activation、platform_handles、author_provides、configuration、limits，patterns 给出组合示例；可按 capability 定向读取。自动调度、持久化、恢复与原生查看等能力也在其中，不因缺少独立工具而遗漏。

只读取当前任务需要的操作说明。

## 调用工具

本 Skill 是安装到 Agent 的完整操作手册，包含调用脚本和本地平台连接地址。可直接调用通用工具，也可由作者的随包脚本封装同一接口，无需查找平台源码或内部模块。

在本 Skill 根目录运行；在其他工作目录时，使用该脚本的绝对路径：

```sh
python3 scripts/call.py check
python3 scripts/call.py list
python3 scripts/call.py read_capabilities
python3 scripts/call.py TOOL --arguments @参数.json
```

脚本仅使用 Python 标准库，可用本机兼容的 Python 3.9 或以上，不依赖安装平台时的 Python 路径。Windows 可使用 `py -3`。

`connection.json` 保存平台地址；非默认地址或唤醒 prompt 提供了实际 `platform_url` 时，加 `--url 实际地址`。源码、安装资源和导出的 Skill 使用同一份脚本。

内部共享平台可以直接读取。需要写入但收到 `edit_locked` 时，使用者须提供共享编辑口令，在调用脚本的环境中设置 `LOOP_ANYTHING_EDIT_PASSWORD`；客户端会自动携带，不要把口令写进 Loop 定义、Skill 或提示词。已有任务令牌继续按原权限使用。

首次使用先检查连接，再读取工具目录及其中的 instructions；read_capabilities 返回运行服务的版本、能力到工具的映射、文档入口和支持的 schema 关键字。服务报告 restart_required 时，源码与正在执行的版本不同；不能把磁盘上新增能力当成服务已可用。目录列出当前服务实际开放的机制和参数；手册提到但目录缺失的字段应核对服务版本，不绕过到数据库或内部模块补写。参数可用 JSON 或 `@UTF8文件`；沿用工具返回的 ID、修订号和令牌。具体 Loop 的 key 从 `list_loops` 取得。连接检查不调用模型或创建业务 Run。

每次调用检查返回的 `ok`，报告状态还须检查 `accepted`；失败时脚本退出码为 2。脚本与监控接入统一报告工具时，见 [run.md 的报告说明](references/run.md#统一报告事件与结果)，调用脚本随 Skill 提供。安排后续任务不等于完成当前任务，文字回复也不是提交回执。作者封装可代为提交与退出；直接调用工具时，按需查看 run.md 中对应操作。

继续工作先用 list_runs 找到已有运行，再只读 read_timeline；编辑时才 acquire_run。微信、飞书、终端共用同一平台和 Timeline，切换入口不会新建 Run 或改变通知目标。

后台 Agent 实时输出与可选 CLI 交互终端由平台提供，配置和限制见 [执行终端](references/terminal.md)。无需自建日志页或交互服务。

首次跨机器组网使用“Agent 通信”的共享空间与群组发现流程，见 [通信手册](references/communication.md#首次组网共享空间--群组--具名-agent)。平台已提供空间映射、群组发现、加入说明和成员目录，不要自建注册中心或扫描其他机器的 CLI/session。
