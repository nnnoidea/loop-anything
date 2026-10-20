---
name: loop-anything-platform
description: 用于将已有 Skill 转成 Loop，以及构建、编辑、测试调试和运行 Loop / 工作流，编排多步骤或多轮持续任务，查询进度与结果、暂停或恢复已有运行，以及等待训练等外部结果后继续。配置接单机器、具名 Agent 或团队连接时也使用本 Skill。单独给远端或本机具名 Agent 派任务、求助、查询结果与追问，使用独立的 loop-anything-dispatch Skill；Loop 节点同样复用它，并保留已有运行身份与等待恢复。先发现已有能力、Loop 和运行再复用或构建；无需工作流或协作的一次性问答和本地修改可直接完成。
metadata:
  provider: loop-anything-platform
---

# Loop Anything

## 选择入口

| 当前需要 | 先做什么 | 按需读取 |
|---|---|---|
| 构建、编辑、测试或调试 Loop / 工作流 | 先查已有 Loop 和平台能力，按构建手册复用、编辑并验证；需要执行时再启动 Run | [构建](references/build.md)、[验收](references/testing.md)、[运行](references/run.md) |
| 将已有 Skill 转成 Loop | 流程 Agent 完整读取 Loop 说明处理不确定推进，确定动作和等待交给平台，保留运行记录 | [流程 Agent](references/flow-agent.md) |
| 多轮工作、依赖步骤、等待训练或其他外部结果后继续 | 查 `list_loops`、`list_runs`，复用已有工作；确需新流程再构建 | [构建](references/build.md)、[运行](references/run.md) |
| 跟远端 Agent 通信、求助、发布任务，或请本机具名 Agent 帮忙 | 使用独立 `loop-anything-dispatch` Skill；托管节点沿用限定入口和运行身份 | [通信](references/communication.md) |
| 独立会话需要等待外援后自动续跑 | `start_collaboration` 接入真实原 session/当前 Agent PID/恢复命令，或启动本机具名协调 Agent；再使用 `wait_assistance` | [通信](references/communication.md#独立协作内置-loop) |
| 看进度、取结果、继续之前的工作 | 用已有 Run/请求 ID 查状态；有任务令牌就沿用，不重复创建 | [运行](references/run.md)、[通信](references/communication.md) |
| 首次建立多机协作 | `communication_config(operation=team,link=...)` 接入团队；先询问用户主要任务，再配置本机接单 Agent | [组网](references/communication.md#首次组网共享空间--群组--具名-agent) |

普通飞书/终端入口没有 `execution_id` 是正常的；不要遍历其他 Run 寻找登记目标。求援、原会话续跑与已有执行登记的区别见[入口 Agent 与 session 登记](references/communication.md#入口-agent-与-session-登记)。

## 主动提出适合目标的构建建议

讨论新 Loop 或调整方案时，结合用户目标，从[特性与构建思路](references/platform-capabilities.md#特性如何改变-loop-的组织方式)中挑出会实际改变流程组织的能力，主动提出具体建议，并说明对当前目标有什么帮助；无需等用户先问平台有哪些功能。

把建议融入方案讨论。例如“持续跑实验”可建议拆开方案制定、训练等待和结果分析，让平台监控训练，再根据结果展开下一轮。已有方案合适时直接继续；用户已作出的选择继续有效。不要逐项宣读特性、为展示能力增加节点，或把这段指导变成必经检查、打分、审批及额外确认步骤。遇到实际能力缺口就说明边界。

当用户目标涉及多种专业职责、不同阶段的操作说明或很长的手册时，主动建议怎样组织 Loop 与节点的 Skill／说明：整体目标和共享规则放在 Loop 层，各节点按职责保留自己的方法、工具用法和输入输出要求，执行时按需读取，减少无关上下文和指令干扰。例如研究 Loop 可共享实验目标，把训练操作与结果评价分别放到对应节点。已有说明简短清楚时无需拆分；不强制每个节点新建 Skill，不复制共享规则，不仅为缩短文件而增加节点，也不承诺拆分能完全消除上下文漂移。

首次构建完整流程、或修改节点／分支／循环／任务生成逻辑后，一并更新给用户看的整体流程图。图中必须逐一展示 Loop 定义里的每一个节点，包括初始化、按需分支和异常兜底；不能省略节点，也不能用“实验流水线”等汇总框替代多个真实节点。用[流程图工具与模板](references/flow-diagram.md)编写真实业务关系，保存前逐项核对节点清单并预览；图大时调整布局、分组或滚动。无需手写页面、启动额外 Agent，或把绘图变成保存与运行的强制门槛。

## 连接并发现

通过工具调用和结构化回执操作平台。若唤醒上下文提供 `tool_url`，先按[限定工具入口](references/scoped-entry.md)调用；否则在本 Skill 目录执行，其他目录使用脚本绝对路径：

```sh
python3 scripts/call.py check
python3 scripts/call.py read_capabilities --arguments '{"capability":"authoring"}'
```

按任务选择 capability，如 `authoring`、`task_scheduler`、`agent_communication`；通过 `list` 读取实际工具 schema，再用 `scripts/call.py TOOL --arguments @参数.json` 调用。连接地址在 `connection.json`，可用 `--url` 覆盖。连接失败先诊断，不另建平台或 Run。安装、更新与连接方式见[连接说明](references/connection.md)。以运行服务的能力为准，检查回执的 `ok`、`accepted`。Timeline 修改在提交时检查版本：托管身份自动记录读取依据，无持续 token 的修改携带读取返回的 `basis`；冲突后重新判断，见[运行](references/run.md#思考不占用提交检查版本)。

## 使用原则

- 向群组开放 Agent 前，由用户确认主要任务和开放范围，再设置 `task_confirmed=true`；已有明确回答可复用，Agent 自拟说明不等于用户确认。字段见[通信配置](references/communication.md#配置平台所有者)。
- 先查平台已有能力，再决定业务脚本需要做什么；平台已提供调度、持久化、通信、等待恢复和结果查看。
- 当前身份直接读取唤醒上下文或 `communication_status` 的 `self`，包含 machine_id、machine_name、workspace_id；它标识所连接的平台，寻址规则见[当前身份](references/communication.md#当前连接的是谁)。
- 通知接入先 `read_cc_connect` 发现本机 Bots，缺配置用 `configure_cc_connect`；具名 Agent 直接绑定 `notification_bot`，固定目的地再配置命名出口，无需自建发送脚本。
- cc-connect 飞书入口用 `call.py` 自动携带通知来源，Agent 无需自行查询消息或拼接发送命令；通知直接交给 cc-connect，不补飞书凭据、不作群成员/权限/话题预检；Bot 映射、根消息与显式出口规则见[原聊天通知](references/cc-connect.md#自动跟随原聊天)。
- 外援 pending/offered 是等待接单，不是无人可用；不得因几秒未回应就取消、重建或缩短接单期限。使用平台挂起或保留请求等通知；用户明确撤回仍可取消。
- 查询外援默认只读状态与结果。只有排错才请求日志，并沿返回游标按需读取；不反复携带完整日志、通知历史或旧请求。
- 在已有授权范围内执行；发现能力不代表用户授权新建任务、发送通知或启动任意远端工作。
- 恢复工作使用记录的原 session 与当前操作凭据，不能猜测最近会话；具体方法由 `read_task` 返回的作者 Skill 提供。

编辑草稿查[字段与资源](references/build-reference.md)，组合机制查[能力地图](references/platform-capabilities.md)，参数与引用查[契约](references/contracts.md)，验收查[测试](references/testing.md)，通知查[通知配置](references/notifications.md)，查看和恢复 CLI 查[执行终端](references/terminal.md)。只读当前任务需要的部分。
