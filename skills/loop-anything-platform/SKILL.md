---
name: loop-anything-platform
description: 使用已安装的 Loop Anything 构建与分享 Loop，启动 Run 并用工具操作 Timeline、任务和运行设置。业务方法按任务读取节点绑定的作者 Skill。
metadata:
  provider: loop-anything-platform
---

# Loop Anything 平台

本 Skill 只教通用的平台与工具使用。具体 Loop 的用途和输入要求见作者说明；作者 Skill 直接绑定在节点上，处理任务时用 read_task 读取对应内容。它们随 Loop 包交付，无需另外安装一层作者 Skill。

## 按当前任务读取

- 创建、编辑、验证或分享 Loop：读取 [build.md](references/build.md)。
- 从任意入口继续已有 Run、启动 Run、处理节点任务或修改 Timeline：读取 [run.md](references/run.md)。已经有 Run 和操作令牌时直接使用运行说明，不重新创建 Run。

- 配置通知出口或接入现有聊天桥接：读取 [notifications.md](references/notifications.md)。

只读取当前任务需要的操作说明。

## 调用工具

本 Skill 是安装到 Agent 的完整操作手册，包含调用脚本和本地平台连接地址。所有构建 Loop、启动 Run 和修改 Timeline 的操作，都从这里调用，无需查找平台源码或内部模块。

在本 Skill 根目录运行；在其他工作目录时，使用该脚本的绝对路径：

```sh
python3 scripts/call.py check
python3 scripts/call.py list
python3 scripts/call.py TOOL --arguments @参数.json
```

脚本仅使用 Python 标准库，可用本机兼容的 Python 3.9 或以上，不依赖安装平台时的 Python 路径。Windows 可使用 `py -3`。

`connection.json` 保存平台地址；非默认地址或唤醒 prompt 提供了实际 `platform_url` 时，加 `--url 实际地址`。源码、安装资源和导出的 Skill 使用同一份脚本。

首次使用先检查连接，再读取工具目录。参数可用 JSON 或 `@UTF8文件`；沿用工具返回的 ID、修订号和令牌。具体 Loop 的 key 从 `list_loops` 取得。连接检查不调用模型或创建业务 Run。

每次调用检查返回的 `ok`；失败时脚本退出码为 2。安排后续任务不等于完成当前任务，文字回复也不是提交回执。运行任务按 run.md 中的提交与退出步骤执行。

继续工作先用 list_runs 找到已有运行，再只读 read_timeline；编辑时才 acquire_run。微信、飞书、终端共用同一平台和 Timeline，切换入口不会新建 Run 或改变通知目标。
