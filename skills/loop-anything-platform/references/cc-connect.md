# 可选适配器：cc-connect

这是平台提供的第一个通知适配示例，实现[通用通知接口](notifications.md)。使用其他桥接或纯终端时无需安装 cc-connect。平台不替用户创建机器人、管理聊天会话或启动桥接。

## 使用前提

用户已安装并配置 [cc-connect](https://github.com/chenhg5/cc-connect)，目标渠道已连接。桥接接入的 Agent 和平台使用同一个平台实例；以下示例要求适配器、Python 和 cc-connect 命令在平台所在机器可访问。

实际渠道能力由桥接及其版本决定。飞书和微信的扫码、机器人配置、发送限制以桥接说明为准，不把接口适配完成当成真实渠道联调成功。

## 自动跟随原聊天

平台 0.6.1 起，飞书/Lark 入口 Agent 通过 `scripts/call.py request_assistance` 、`start_run` 或 `start_collaboration` 调用时，客户端只读取 `CC_PROJECT`、`CC_SESSION_KEY` 并随业务请求提交 `chat_context`。客户端不查找 cc-connect、不读取渠道配置、不查询飞书、不构造发送命令，也不单独注册会话。平台持久保存来源并复用同一会话绑定，发送适配器负责渠道检查与投递。无需先给通信群组配置固定接收群。显式 `notification_route`、`conversation_id` 或发送命令优先；子请求也可选择 `notification_route=workspace`，此选择在来源平台和追问中保留；平台内节点和嵌套外援沿用已保存来源。

- 私聊：入口 Bot 回复原私聊。
- 群聊：请求由入口 Bot 提示；具名 Agent 的执行确认、结果优先由其对应 Bot 回复原群/原话题。没有映射、离线或发送前检查不通过时，由入口 Bot 代发。
- `通信 → 具名 Agent → 编辑 → 对应 Bot 的通知出口`，或 `communication_config(operation=agent, agent={notification_route:出口ID})` 建立映射。不同 Agent 可映射不同 project。通知出口继续使用 cc-connect 适配器，identity 是该 Bot 的 project；接收位置在此路径由原会话覆盖，不取该出口预设的其他群。其他适配器必须明确支持 `conversation` 输入和 `not_sent` 回执后才能用于此映射。
- 嵌套外援和追问继承原始会话，不将中转机器的聊天当新入口；无 Loop、本机具名 Agent 同样支持。
- 每条通知保存来源、选中 Bot、回退原因和送达回执。仅适配器明确返回 `delivered=false, not_sent=true`（从未调用发送）才能回退；CLI 已启动后失败、超时或平台重启一律不自动改投。远端已入队但失联也不会贸然切换。

### cc-connect 前提与核实范围

核对过本机 `v1.5.1-beta.1 / 80713167` 的[飞书实现](https://github.com/chenhg5/cc-connect/blob/80713167/platform/feishu/feishu.go)：`send --session feishu:群ID:root:根消息ID` 可在无会话缓存时重建回复目标；该版本会把 `thread:` 后面的值直接当消息 ID，不能直接用真实话题 ID 代替。**不要用 `relay send` 发通知，它会再次启动目标 Agent**。

平台保留完整原 `session_key`，分别保存 `chat_id`、`thread_id` 和 `thread_root`（根消息 ID）。适配器在发送时处理明确的 `feishu/lark:群ID:thread:话题ID`：

1. 优先使用入口事件已经提供或之前回执保存的 `thread_root`；不要将话题 ID 填到这个字段，不要替换 ID 前缀。
2. 缺少根消息时，复用发送机 cc-connect 项目配置中的 Bot 凭据，通过[获取会话历史消息](https://open.feishu.cn/document/server-docs/im-v1/message/list)的 `container_id_type=thread` 查询原话题，核对返回的群和话题并取得根消息。没有可用结果或权限不足则记录通知失败，不阻断业务任务。
3. 调用原有 `cc-connect send --session 渠道:群ID:root:根消息ID`。回执分别记录原会话和 `delivery_session_key`；根消息信息写回会话绑定，供后续通知复用。

话题转换要求运行中的桥接配置 `thread_isolation=true`，且 `reply_to_trigger` 为 `true` 或省略。适配器读取同一配置，明确关闭或缺少话题隔离时不发送，避免已知的群时间线降级。配置改动需在 cc-connect 中生效；读取本地配置不能证明运行实例已经加载它。现有 `root:` 目标、普通私聊及未知会话格式沿用原样传递，不基于 ID 前缀猜测有效性。

**候选 Bot 的选择**仍只核实必要群聊、成员/发言权限；未知字段、配置或探测失败表示不能选用候选，平台回退入口 Bot。入口 Bot 不重复候选检查，但需要的话题解析仍会执行。任何发送已开始后的失败或超时均不自动换 Bot 重发。

配置和密钥留在发送机，消息正文与凭据不会写入查询结果回执。读取 TOML 需要 Python 3.11+ 的 `tomllib` 或已有 `tomli`；适配器沿用可用解释器发现机制。Bot 查询群历史需要消息读取及 `im:message.group_msg` 权限；已经保存根消息时不查询飞书历史。真实渠道投递仍需在安装环境验证。

平台按 `channel=cc-connect` 和入口 project 的 identity 查找本地适配器。同一 Bot 的多个接收位置可共用相同 command/cwd；接收位置始终使用原会话。多个不同适配器配置仍须显式选择，以免平台猜测发送命令。自定义 `--executable`、`--data-dir` 和用于话题解析和候选核实的 `--config` 在发送机配置一次；call.py 只传入口元数据。

一旦发送 CLI 已启动，失败或超时可能意味着结果未知，不能自动换 Bot 重发。业务 Run/外援不因通知失败而被阻断。最终成功或错误以 cc-connect 的实际回执为准。

直连 HTTP/MCP 的客户端可在 request_assistance/start_run/start_collaboration 中直接传纯元数据，例如：

```json
{"chat_context":{"platform":"feishu","entry_project":"入口Bot的project","session_key":"feishu:oc_chat:root:om_root"}}
```

入口若已有完整事件，可额外传 `chat_id`、`thread_id`、`thread_root`（事件中的 `root_id`）；这些字段随来源持久保存。没有根消息时不要求 Agent 自己查飞书，发送适配器负责补齐。cc-connect 当前不会单独注入根消息环境变量。

chat_type 可选（p2p/group），未提供时保持 unknown，不从 session 格式推断。只有选择其他 Bot 时才尝试核实群聊；无法确认就用入口 Bot。明确为私聊时只使用入口 Bot。嵌套外援继承原来源；worker 不能用 chat_context 改写入口。

兼容旧客户端：可先用 `communication_config(operation=conversation, conversation=元数据, notification_command=本机argv)` 注册，取得 `conversation_id`，再传给 `request_assistance` / `start_run`；命令在可信工作区注册，无需Loop编辑解锁；远端 worker 限定入口不能登记任意命令。`start_run` 的普通 Timeline 通知自动复用该注册命令，无需再传一次。

源码核实与模拟多实例测试不等于真实 Bot 跨群/跨话题验收；真实 NAS 与飞书应用权限、实际送达仍在安装环境验收。

## 平台命名出口

平台「通知出口」选择 cc-connect，发送身份填已配置的 project，接收位置填 session。也可用 read_notification_channels 返回的 cc_connect_command 配合 set_notification_channels 保存同样配置。适配器从通知的 outlet.identity / destination 读取实际目标；命令中的旧 project/session 仅在未提供这些字段时使用。命令可追加 --executable 和 --data-dir 指定既有安装位置。

### 接入自己的 cc-connect

使用现成二进制，无需修改或重编译 cc-connect。前提是项目、Bot 已配置并且桥接正在运行；安装一个二进制本身不会创建这些资源。

- 默认位置：适配器在 PATH 中查找 `cc-connect`，使用 `~/.cc-connect` 数据目录和 `~/.cc-connect/config.toml`。
- 非默认位置：在平台通知出口的发送命令中追加 `--executable /实际路径/cc-connect`、`--data-dir /实际数据目录`、`--config /实际配置文件`。这些是**发送机**的路径，必须与运行中的桥接实例一致；Windows 同样可指定 `.exe` 路径。
- 身份：出口的 `identity` 填自己的 cc-connect project 名。聊天入口的 project/session 由 `call.py` 随请求携带；固定出口则显式配置 destination。
- 话题：在运行桥接中启用上述话题回复配置；仅在缺根消息时需要历史读取权限。

在已由 cc-connect 注入会话环境的 Agent 内，可生成带自定义路径的命令（不发送消息）：

```sh
python3 scripts/notify_cc_connect.py --print-command \
  --executable /实际路径/cc-connect \
  --data-dir /实际数据目录 \
  --config /实际配置文件 > notification-command.json
```

多机器协作时，各机器可在“Agent 通信 → 群组 → 通知绑定”独立绑定本机出口。每条通知优先动作发生方，其次本次请求发起方；两者都未绑定则只保留平台记录，不交给任意第三台机器。选定后经 NAS 持久交付并写回回执，未知送达不自动切换。详见[群组通知优先级](communication.md#群组按机器绑定出口与通知优先级)。

消息中的询问可以在网页回复，或让当前聊天的 Agent 读取 Timeline 后调用 send_event；本适配器只负责发送，不另外接管聊天入口。

## 生成当前聊天的发送命令

在目标聊天唤起的 Agent 中，从本 Skill 根目录执行：

```sh
python3 scripts/notify_cc_connect.py --print-command > notification-command.json
```

它读取桥接提供的 CC_PROJECT、CC_SESSION_KEY 和可选 CC_DATA_DIR，生成普通 JSON argv 数组，保存明确的项目、会话、数据目录及可执行路径。该操作不发送消息。缺少项目、会话或 cc-connect 命令时会报错，不猜测目标。

然后通过通用工具配置本 Run：

```sh
python3 scripts/call.py start_run --notification-command @notification-command.json --arguments @启动参数.json
```

继续已有 Run 时，不新建 Run。取得全局操作权后，使用最新设置版本：

```sh
python3 scripts/call.py change_settings --notification-command @notification-command.json --arguments @修改参数.json
```

命令写入 Run 后，临时 JSON 文件不再是运行依赖；适配器脚本及执行路径仍需保留。命令绑定的是生成时的目标聊天，换聊天不自动更改它。仅在用户明确要求更换通知位置时重新配置。

## 发送行为

后台把通知交给 scripts/notify_cc_connect.py。适配器调用：

```text
cc-connect send --project 指定项目 --session 指定会话 --data-dir 指定目录 --stdin
```

正文包含 Run 名称/ID、通知内容、可用的任务状态及通知 ID。参数按 argv 传递，正文通过 stdin 传递。cc-connect 确认成功后返回 delivered=true；失败或超时返回失败，沿用平台的通知记录和重试方式。

适配器没有实现聊天入口、模型配置或会话同步。用户可以参考这个脚本，为其他桥接实现相同通知输入和回执。
