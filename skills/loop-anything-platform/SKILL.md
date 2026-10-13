---
name: loop-anything-platform
description: 用于构建、编辑、测试调试和运行 Loop / 工作流，编排多步骤或多轮持续任务，查询进度与结果、暂停或恢复已有运行，以及等待训练等外部结果后继续。用户要跟远端或其他机器上的 Agent 通信、向本机或远端具名 Agent 求助、给 Agent 发布或委派任务、让另一台机器执行工作、查询协作结果或配置多机协作时，也应优先使用本 Skill。无需用户提到 Loop Anything；一次性远端求助或没有现成 Loop 同样触发。先发现平台已有能力、Loop、运行和成员，再按需复用或构建；无需工作流或协作的一次性问答和本地修改可直接完成。
metadata:
  provider: loop-anything-platform
---

# Loop Anything

## 选择入口

| 当前需要 | 先做什么 | 按需读取 |
|---|---|---|
| 构建、编辑、测试或调试 Loop / 工作流 | 先查已有 Loop 和平台能力，按构建手册复用、编辑并验证；需要执行时再启动 Run | [构建](references/build.md)、[验收](references/testing.md)、[运行](references/run.md) |
| 多轮工作、依赖步骤、等待训练或其他外部结果后继续 | 查 `list_loops`、`list_runs`，复用已有工作；确需新流程再构建 | [构建](references/build.md)、[运行](references/run.md) |
| 跟远端 Agent 通信、求助、发布任务，或请本机具名 Agent 帮忙 | `communication_status` 发现可调用成员，再 `request_assistance`；无需先登记自己的 session 或成为接单成员 | [通信](references/communication.md) |
| 独立会话需要等待外援后自动续跑 | `start_collaboration` 接入真实原 session/当前 Agent PID/恢复命令，或启动本机具名协调 Agent；再使用 `wait_assistance` | [通信](references/communication.md#独立协作内置-loop) |
| 看进度、取结果、继续之前的工作 | 用已有 Run/请求 ID 查状态；有任务令牌就沿用，不重复创建 | [运行](references/run.md)、[通信](references/communication.md) |
| 首次建立多机协作 | 配置共享空间，加入群组；先询问用户主要任务，再确认具名 Agent 的说明和开放范围 | [组网](references/communication.md#首次组网共享空间--群组--具名-agent) |

普通飞书/终端入口没有 `execution_id` 是正常的；不要遍历其他 Run 寻找登记目标。求援、原会话续跑与已有执行登记的区别见[入口 Agent 与 session 登记](references/communication.md#入口-agent-与-session-登记)。

## 连接并发现

在本 Skill 目录执行，其他目录使用脚本绝对路径：

```sh
python3 scripts/call.py check
python3 scripts/call.py read_capabilities --arguments '{"capability":"authoring"}'
```

按任务选择 capability，如 `authoring`、`task_scheduler`、`agent_communication`；通过 `list` 读取实际工具 schema，再用 `scripts/call.py TOOL --arguments @参数.json` 调用。连接地址在 `connection.json`，可用 `--url` 覆盖。连接失败先诊断，不另建平台或 Run。安装、更新与编辑口令见[连接说明](references/connection.md)；日常运行和通信无需全局解锁。以运行服务的能力为准，检查回执的 `ok`、`accepted`。

## 使用原则

- 向群组开放 Agent 前，由用户确认主要任务和开放范围，再设置 `task_confirmed=true`；已有明确回答可复用，Agent 自拟说明不等于用户确认。字段见[通信配置](references/communication.md#配置平台所有者)。
- 先查平台已有能力，再决定业务脚本需要做什么；平台已提供调度、持久化、通信、等待恢复和结果查看。
- cc-connect 飞书入口用 `call.py` 自动携带通知来源，Agent 无需自行查询消息或拼接发送命令；Bot 映射、根消息与显式出口规则见[原聊天通知](references/cc-connect.md#自动跟随原聊天)。
- 外援 pending/offered 是等待接单，不是无人可用；不得因几秒未回应就取消、重建或缩短接单期限。使用平台挂起或保留请求等通知；用户明确撤回仍可取消。
- 查询外援默认只读状态与结果。只有排错才请求日志，并沿返回游标按需读取；不反复携带完整日志、通知历史或旧请求。
- 在已有授权范围内执行；发现能力不代表用户授权新建任务、发送通知或启动任意远端工作。
- 恢复工作使用记录的原 session 与当前操作凭据，不能猜测最近会话；具体方法由 `read_task` 返回的作者 Skill 提供。

编辑草稿查[字段与资源](references/build-reference.md)，组合机制查[能力地图](references/platform-capabilities.md)，参数与引用查[契约](references/contracts.md)，验收查[测试](references/testing.md)，通知查[通知配置](references/notifications.md)，查看和恢复 CLI 查[执行终端](references/terminal.md)。只读当前任务需要的部分。
