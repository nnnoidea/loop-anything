# 可选适配器：cc-connect

这是平台提供的第一个通知适配示例，实现[通用通知接口](notifications.md)。使用其他桥接或纯终端时无需安装 cc-connect。平台不替用户创建机器人、管理聊天会话或启动桥接。

## 使用前提

用户已安装并配置 [cc-connect](https://github.com/chenhg5/cc-connect)，目标渠道已连接。桥接接入的 Agent 和平台使用同一个平台实例；以下示例要求适配器、Python 和 cc-connect 命令在平台所在机器可访问。

实际渠道能力由桥接及其版本决定。飞书和微信的扫码、机器人配置、发送限制以桥接说明为准，不把接口适配完成当成真实渠道联调成功。

## 本机接入与 Bot 发现

先调用 `read_cc_connect`，读取本机接入配置、revision 和 `bots`。配置只在本机平台用户环境保存，多个工作区共用，不随 Loop 或 NAS 分享；Bot 凭据始终留在 cc-connect 配置文件中。

未配置时，确定正在运行的桥接实际使用的配置文件，再调用：

```json
{"revision":0,"connection":{"config_path":"/实际路径/config.toml","executable":"/实际路径/cc-connect"}}
```

工具名为 `configure_cc_connect`。executable 可省略，从 PATH 查找；平台不猜配置文件目录。数据目录读取配置的 `data_dir`；需要覆盖或配置用了相对路径时，显式传绝对 `data_dir`。配置未指定数据目录时，不加 `--data-dir`，由 cc-connect 自身决定默认值。读取配置不代表运行中的桥接已经加载它；配置改动需在桥接中生效。`connection={}` 清除本机接入配置。

`read_cc_connect.bots` 返回 project、platform、label、selectable 及歧义原因；不返回密钥。不需要自行读私密配置、写发送脚本或为每个 Bot 建出口。同一 project 内多个同类型 Bot 目前不能通过 cc-connect send 唯一选择，标记为不可选；可在 cc-connect 中分到不同 project。读取会刷新列表，不安装或启动 Bot，也不发送测试消息。

给具名 Agent 绑定时，从可选 Bot 复制引用：

```json
{"operation":"agent","agent_id":"papers","agent":{"notification_bot":{"project":"papers","platform":"feishu"},"notification_route":""}}
```

通过 `communication_config` 保存。`notification_bot=null` 取消映射。旧 `notification_route` 仍兼容；设置任一种映射时自动清除另一种，不可同时指定两个非空映射。更换 Bot 不修改 Agent 执行命令或会话。

## 自动跟随原聊天

飞书通知来源与 Agent 原生 session 分开保存；普通通知不需要 register_agent_session。自动续跑及登记方式见[入口 Agent 与 session 登记](communication.md#入口-agent-与-session-登记)。

飞书/Lark 入口 Agent 通过 `scripts/call.py request_assistance` 、`start_run` 或 `start_collaboration` 调用时，客户端只读取 `CC_PROJECT`、`CC_SESSION_KEY` 并随业务请求提交 `chat_context`。客户端不查找 cc-connect、不读取渠道配置、不查询飞书、不构造发送命令，也不单独注册会话。平台持久保存来源并复用同一会话绑定，发送适配器负责渠道检查与投递。无需先给通信群组配置固定接收群。显式 `notification_route`、`conversation_id` 或发送命令优先；子请求可选 `notification_route=workspace`，此选择在来源平台和追问中保留。

- 私聊：入口 Bot 回复原私聊。
- 群聊：请求由入口 Bot 提示；具名 Agent 的执行确认、结果优先由其对应 Bot 回复原群/原话题。没有映射、离线或发送前检查不通过时，由入口 Bot 代发。
- 具名 Agent 通过上面的 `notification_bot` 直接映射 Bot。接收位置由原会话提供，不需为该 Agent 预设固定群。兼容的其他适配器必须支持 `conversation` 输入和 `not_sent` 回执。
- 嵌套外援和追问继承原始会话，不将中转机器的聊天当新入口；无 Loop、本机具名 Agent 同样支持。
- 每条通知保存来源、选中 Bot、回退原因和送达回执。仅适配器明确返回 `delivered=false, not_sent=true`（从未调用发送）才能回退；CLI 已启动后失败、超时或平台重启一律不自动改投。远端已入队但失联也不会贸然切换。

### cc-connect 前提与核实范围

核对过本机 `v1.5.1-beta.1 / 80713167` 的[飞书实现](https://github.com/chenhg5/cc-connect/blob/80713167/platform/feishu/feishu.go)：`send --session feishu:群ID:root:根消息ID` 可在无会话缓存时重建回复目标；该版本会把 `thread:` 后面的值直接当消息 ID，不能直接用真实话题 ID 代替。**不要用 `relay send` 发通知，它会再次启动目标 Agent**。

该桥接开启话题隔离后，群消息优先用事件 RootId、缺失时用 MessageId 生成 `…:root:根消息ID`。call.py 传递完整 session_key，平台在接收业务请求时自动提取并保存群 ID 和根消息，无需单独注入根消息环境变量。

平台保留原 session_key 及入口提供的 chat_id、thread_id、thread_root；话题 ID 不一定存在。只有入口为 `feishu/lark:群ID:thread:话题ID` 时，适配器才需要以下转换：

1. 优先使用入口事件已经提供或之前回执保存的 `thread_root`；不要将话题 ID 填到这个字段，不要替换 ID 前缀。
2. 缺少根消息时，复用发送机 cc-connect 项目配置中的 Bot 凭据，通过[获取会话历史消息](https://open.feishu.cn/document/server-docs/im-v1/message/list)的 `container_id_type=thread` 查询原话题，核对返回的群和话题并取得根消息。没有可用结果或权限不足则记录通知失败，不阻断业务任务。
3. 调用原有 `cc-connect send --session 渠道:群ID:root:根消息ID`。回执分别记录原会话和 `delivery_session_key`；根消息信息写回会话绑定，供后续通知复用。

话题转换要求运行中的桥接配置 `thread_isolation=true`，且 `reply_to_trigger` 为 `true` 或省略。适配器读取同一配置，明确关闭或缺少话题隔离时不发送，避免已知的群时间线降级。配置改动需在 cc-connect 中生效；读取本地配置不能证明运行实例已经加载它。已有 `root:` 同样检查这些发送选项，然后原样发送，且不查询消息历史。普通私聊及未知会话格式沿用原样传递，不基于 ID 前缀猜测有效性。

**候选 Bot 的选择**仍只核实必要群聊、成员/发言权限；未知字段、配置或探测失败表示不能选用候选，平台回退入口 Bot。入口 Bot 不重复候选检查，但需要的话题解析仍会执行。

配置和密钥留在发送机，消息正文与凭据不会写入查询结果回执。读取 TOML 需要 Python 3.11+ 的 `tomllib` 或已有 `tomli`；适配器沿用可用解释器发现机制。Bot 查询群历史需要消息读取及 `im:message.group_msg` 权限；已经保存根消息时不查询飞书历史。

平台优先使用本机接入配置按入口 project 选发送方。尚未配置新接入的机器兼容已有 `channel=cc-connect`、identity=入口 project 的命令出口；多个不同命令仍报告歧义。两种配置都没有时，通知进入等待配置，业务继续。已经选定的通知保留当时的发送配置，重试不换 Bot。

业务 Run/外援不因通知失败而被阻断；发送结果以 cc-connect 的实际回执为准。

直连 HTTP/MCP 的客户端可在 request_assistance/start_run/start_collaboration 中直接传纯元数据，例如：

```json
{"chat_context":{"platform":"feishu","entry_project":"入口Bot的project","session_key":"feishu:oc_chat:root:om_root"}}
```

入口若已有完整事件，可额外传 `chat_id`、`thread_id`、`thread_root`（事件中的 `root_id`）；这些字段随来源持久保存。没有根消息时不要求 Agent 自己查飞书，发送适配器负责补齐。cc-connect 当前不会单独注入根消息环境变量。

chat_type 可选（p2p/group），未提供时保持 unknown，不从 session 格式推断；worker 不能用 chat_context 改写入口。

兼容旧客户端：可先用 `communication_config(operation=conversation, conversation=元数据, notification_command=本机argv)` 注册，取得 `conversation_id`，再传给 `request_assistance` / `start_run`；命令在可信工作区注册，无需Loop编辑解锁；远端 worker 限定入口不能登记任意命令。`start_run` 的普通 Timeline 通知自动复用该注册命令，无需再传一次。

源码核实与模拟多实例测试不等于真实 Bot 跨群/跨话题验收；真实 NAS 与飞书应用权限、实际送达仍在安装环境验收。

## 平台命名出口

直接 Agent Bot 映射和原聊天回复无需命名出口。只有固定接收位置（例如没有聊天来源时的群组通知）需要出口：先 `read_notification_channels` 取得 revision 和现有 channels，再 `set_notification_channels` 保留现有条目并添加：

```json
{"revision":0,"channels":{"research-updates":{"label":"研究通知","cc_connect":{"project":"research","platform":"feishu"},"destination":"飞书原始会话标识"}}}
```

不填 command、cwd、identity 或 channel；平台根据 Bot 引用解析。通用命令出口仍可使用原有契约。群组绑定规则见[群组通知优先级](communication.md#群组按机器绑定出口与通知优先级)。

Agent 可读取 Timeline 后调用 send_event 提交用户对询问的回复；本适配器只负责发送，不另外接管聊天入口。

## 生成当前聊天的发送命令

仅用于兼容已有的显式发送命令流程。新接入优先使用上述平台工具。

在目标聊天唤起的 Agent 中，从本 Skill 根目录执行：

```sh
python3 scripts/notify_cc_connect.py --print-command > notification-command.json
```

此操作不发送消息：读取 CC_PROJECT、CC_SESSION_KEY 和可选 CC_DATA_DIR，生成保存目标与本机路径的 JSON argv。可显式追加 --executable、--data-dir、--config；缺少项目、会话或可执行文件时会报错，不猜测目标。

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
