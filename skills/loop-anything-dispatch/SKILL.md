---
name: loop-anything-dispatch
description: 跟远端或其他机器上的具名 Agent 通信、求助、发布或委派任务，查询完整协作结果及追问。只派单无需安装或启动 Loop Anything 平台；一个团队链接接入 NAS 或飞书多维表格。Loop 节点派单也使用本 Skill，沿用已有运行身份与等待恢复机制。接单、配置本机 Agent、构建和运行 Loop 使用 loop-anything-platform。
---

# 给 Agent 派任务

本目录的 `scripts/dispatch.py` 可单独使用，只需 Python 3.9+。接单机器安装并运行平台。默认立即返回请求 ID，发起 Agent 可以离开，接收端不需要发起方在线授权第二次。

## 普通会话

首次保存团队链接，之后不用重复提供。NAS 使用本机挂载目录，各机器路径可不同；飞书使用 Base 链接（含知识库 Base 链接也可以），复用本机已认证的 `lark-cli`，默认用户身份，`identity: "bot"` 可使用应用身份。链接本身不授予访问权限；认证问题沿用 lark-cli 的说明处理，无需复制其他进程的凭据。

```sh
python3 scripts/dispatch.py join --arguments '{"link":"团队 Base 链接或 NAS 目录"}'
python3 scripts/dispatch.py agents --arguments '{"name":"论文 Agent"}'
python3 scripts/dispatch.py submit --arguments '{"agent_name":"论文 Agent","message":"检索支持这个实验假设的论文，并说明证据与限制","context":{"hypothesis":"…"}}'
python3 scripts/dispatch.py read --arguments '{"request_id":"返回的请求 ID"}'
```

根据成员**主要任务说明**选择帮手；用户指定名称时也先查目录。submit 支持 agent_name，工具解析为真实 agent_id + instance_id；重名时使用目录返回的 ID 明确机器，两个 ID 都提供也不跳过目录。已离线但仍留在目录的成员可以排队，未知 ID 不会被猜测或直接发布。只配置团队链接不会把当前 Agent 公开为接单成员。发布失败或结果未知时，保留原 ID，使用相同 `request_id` 重试，不重复建任务。`pending` 表示尚未观察到接单；默认接单期限 300 秒，不能几秒没回应就取消重发。无需让 Agent 长轮询；可以稍后读结果，或由已托管的 Loop 等待。

文字回复通常直接放入 result，由 Base 保存并通过工具完整读取。文件交付**只有确认双方可读取同一 NAS 时才优先传共享路径**；不能把“大部分机器共享 NAS”当成本次接收方必然可访问。通过 `context` 或 `result` 传路径和用途；挂载点不同时补充共享目录标识及相对路径。平台原样传引用，不读取或上传路径指向的文件。保留完整产物，别用 summary 替代全文。对方无法访问 NAS 或明确需要云端副本时，可使用[飞书原生附件](references/artifacts.md)，复用现成命令。

`read` 返回完整业务结果；执行日志不会自动塞入上下文。Base 超过 90000 个 UTF-16 单位的**内联消息**由传输层自动用原生附件保存并完整读回，这是兜底，不要求把共享文件读进消息或每次上传。NAS 通信继续使用分片。消息超过 32 MiB 应传可访问的产物引用。大回答不想一次塞进上下文时，可给 `read` 加 `--output /绝对路径/result.json`，保存完整响应后按需读文件，内容不会被摘要或截断。

Base 保留请求和完整结果，已处理消息留在云端历史区，退出日常轮询；不逐条删除，也不要求日常通信有删除权限。用户可按需清理已处理历史，保留在途请求。`read` 直接读取团队结果，不自动缓存全文或发结果读回执；终态请求本机只留云端引用。需要离线结果时显式使用 `--output`。已有旧版缓存仍可读取；连接旧版接收平台时兼容原读回执协议。平台保留推进流程所需的状态、交付结果和 session 定位，原生会话中的完整过程无需再复制；查看已完成 Agent 的执行过程时恢复原 session。

## 等返回：轻量 wait

```sh
python3 scripts/dispatch.py wait --arguments '{"request_id":"返回的请求 ID","timeout":300}'
python3 scripts/dispatch.py wait --arguments '{"request_ids":["request-A","request-B"],"timeout":300}'
```

脚本自行查询，收到终态或等待超时才一次返回完整结果；多请求按各自 ID 返回，已完成的请求不反复读取。finished 表示全部请求已到终态（包含失败），timed_out 只表示本次等待到期，不取消、重发或重启任务；以后可继续 read/wait。Base 最快每 15 秒检查，NAS 默认每秒；timeout 默认 300 秒，与 submit 的 wait_seconds（接单期限）不同。按需设置 poll_interval 放慢检查。该工具占用当前 CLI 进程但不让模型持续轮询；调用它的终端工具需允许相应执行时长，或用后台命令会话等待。中断等待也不撤单。它同样支持 --output 保存完整结果，避免过长回答直接进入上下文。

平台托管的 Loop 节点优先使用 wait_assistance / finish，让 CLI 退出后恢复原 session；不要用轻量 wait 替换既有状态机等待。

追问：`control` 参数 `{"request_id":"…","action":"followup","message":"…"}`，默认复用记录的原 session；缺少 session 会明确提示，用户确需新会话时传 `resume:false`。取消用 `action:"cancel"`，交互输入用 `action:"input", message:"…"`。取消提交不代表进程已经结束。

飞书 cc-connect 入口自动携带 `CC_PROJECT` / `CC_SESSION_KEY`；调用方已有 `chat_context`（含真实 `thread_root`）时直接传入。接收平台按既有 Bot 映射和原会话规则通知，不做消息历史或权限预检。消息发送依靠接收平台配置的 cc-connect/通知出口，任务记录和结果不依赖通知成功。

## 已有 Loop 与本机 Agent

在提供 `tool_url` 的限定入口中沿用该地址（与平台 call.py 的 --url 相同）：

```sh
python3 scripts/dispatch.py submit --tool-url '已有的限定工具 URL' --arguments '{"location":"group","agent_id":"papers","message":"…"}'
```

平台登记请求与当前 Task 的关系，并调用相同派单实现；源 Run 仍由原平台维护。运行上下文已有原生工具时可直接调用同义的 `request_assistance` / `read_assistance`，无需额外 CLI 包装。不要绕过限定入口自行创建无关的独立请求。

普通后台节点若提供 platform_url / run_id / token，则用 `--platform-url` 和 `source:{run_id,task_id}`、token 登记请求；不要丢掉当前 Task 关联。

普通工作区、本机具名 Agent 可用 `--platform-url` 指向接单平台，`submit` 参数 `location:"local"`；本机调用不发布到远端团队。Loop 中需要外援结果才能继续时，使用平台 Skill 的 `wait_assistance` / `finish`，恢复真实原 session。只装派单 Skill 的普通聊天不会自动变成平台托管会话；自动恢复需先用 `start_collaboration` 接入现有会话。

Base 自动提供“Agent 目录”“请求与结果”和“机器心跳”视图；名称、职责、状态和回复可直接查看，协议 JSON 默认隐藏。目录与接单设置由接单机器发布，改职责通过该机器平台配置；是否在线由工具根据机器心跳计算。Agent 用 agents/read/wait 获取所需记录，不遍历或手动解析整张表。

配置文件默认在 `~/.config/loop-anything-dispatch`，可用 `--config-dir` 或 `LOOP_ANYTHING_DISPATCH_HOME` 指定。它保存团队连接、派单身份和已发布请求，重试、控制与追问沿用这些信息。接入不同团队可用不同配置目录。
