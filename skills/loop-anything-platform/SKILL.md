---
name: loop-anything-platform
description: 当任务需要多轮持续推进、等待外部结果后恢复、调用本机或远端具名 Agent、查询或继续已有任务、配置机器协作时，使用 Loop Anything。先发现已有资源与平台能力，再按需构建 Loop 或请求独立外援；简单一次性工作可直接完成。
metadata:
  provider: loop-anything-platform
---

# Loop Anything

把适合持久运行、恢复或跨机器执行的工作交给平台。一次性问答或文件修改通常直接完成；用户不必先说出平台名称。

## 选择入口

| 当前需要 | 先做什么 | 按需读取 |
|---|---|---|
| 多轮工作、依赖步骤、等待训练或其他外部结果后继续 | 查 `list_loops`、`list_runs`，复用已有工作；确需新流程再构建 | [构建](references/build.md)、[运行](references/run.md) |
| 请另一个专长或另一台机器上的 Agent 帮忙 | `communication_status` 发现可调用成员，再 `request_assistance`；无需先建 Loop | [通信](references/communication.md) |
| 看进度、取结果、继续之前的工作 | 用已有 Run/请求 ID 查状态；有任务令牌就沿用，不重复创建 | [运行](references/run.md)、[通信](references/communication.md) |
| 首次建立多机协作 | 配置共享空间，显式加入群组，选择开放的具名 Agent | [组网](references/communication.md#首次组网共享空间--群组--具名-agent) |

## 连接并发现

在本 Skill 目录执行，其他目录使用脚本绝对路径：

```sh
python3 scripts/call.py check
python3 scripts/call.py read_capabilities --arguments '{"capability":"agent_communication"}'
```

按任务替换 capability；通过 `list` 读取实际工具 schema，再用 `scripts/call.py TOOL --arguments @参数.json` 调用。连接地址在 `connection.json`，也可用 `--url` 覆盖。连接失败先诊断，不新建另一个平台或 Run。安装、更新、编辑口令与调用细节见[连接说明](references/connection.md)。日常运行和通信无需全局解锁；仅修改受保护 Loop 时提供该 Loop 口令，平台自动处理普通操作标识。以运行服务的能力和 schema 为准；检查每次返回的 `ok`、`accepted`。

## 使用原则

- 先查平台已有能力，再决定业务脚本需要做什么；平台已提供调度、持久化、通信、等待恢复和结果查看。
- 从 cc-connect 飞书聊天发起时，用 `scripts/call.py` 随请求传递原会话标识，由平台保存、适配器核实并投递；确认与结果沿原聊天/话题返回。具名 Agent 的 Bot 映射及话题前提见 [cc-connect](references/cc-connect.md#自动跟随原聊天)。显式 `notification_route` 可覆盖。
- 查询外援默认只读状态与结果。只有排错才请求日志，并沿返回游标按需读取；不反复携带完整日志、通知历史或旧请求。
- 在已有授权范围内执行；发现能力不代表用户授权新建任务、发送通知或启动任意远端工作。
- 恢复工作使用记录的原 session 与当前操作凭据，不能猜测最近会话；具体方法由 `read_task` 返回的作者 Skill 提供。

编辑草稿查[字段与资源](references/build-reference.md)，组合机制查[能力地图](references/platform-capabilities.md)，参数与引用查[契约](references/contracts.md)，验收查[测试](references/testing.md)，通知查[通知配置](references/notifications.md)，查看和恢复 CLI 查[执行终端](references/terminal.md)。只读当前任务需要的部分。
