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

工具名为 `configure_cc_connect`。executable 可省略，从 PATH 查找；平台不猜配置文件目录。数据目录读取配置的 `data_dir`；需要覆盖或配置用了相对路径时，显式传绝对 `data_dir`。接入时保存解析后的数据目录；配置未指定时，不加 `--data-dir`，由 cc-connect 自身决定默认值。读取配置不代表运行中的桥接已经加载它；配置改动需在桥接中生效。`connection={}` 清除本机接入配置。

`read_cc_connect.bots` 返回 project、platform、label、selectable 及歧义原因；不返回密钥。不需要自行读私密配置、写发送脚本或为每个 Bot 建出口。同一 project 内多个同类型 Bot 的发现列表提示歧义，界面不自动选择；工具接受用户明确填写的 project/platform，不再用配置可读性或目录成员资格阻止保存。实际发送选择由 cc-connect 处理。读取会刷新列表，不安装或启动 Bot，也不发送测试消息。

给具名 Agent 绑定时，从可选 Bot 复制引用：

```json
{"operation":"agent","agent_id":"papers","agent":{"notification_bot":{"project":"papers","platform":"feishu"},"notification_route":""}}
```

通过 `communication_config` 保存。`notification_bot=null` 取消映射。旧 `notification_route` 仍兼容；设置任一种映射时自动清除另一种，不可同时指定两个非空映射。更换 Bot 不修改 Agent 执行命令或会话。

## 自动跟随原聊天

`call.py` 随业务请求携带 `CC_PROJECT`、`CC_SESSION_KEY` 和可用的 chat_context。平台保存入口 Bot、原始会话、群/话题和真实根消息 ID；通知无需登记 Agent 原生 session，自动续跑另见[入口 Agent 与 session 登记](communication.md#入口-agent-与-session-登记)。

- 已知私聊由入口 Bot 回复；群聊/未知聊天的执行确认和结果优先使用具名 Agent 的 Bot 映射。未映射则入口 Bot 代发。
- 嵌套外援继承原聊天；显式 notification_route/conversation_id 可覆盖。通知位置不随当前 Agent 所在聊天变化。
- 发送适配器只调用 `cc-connect send`，不查群成员、权限、聊天类型或话题配置，不调用飞书 API，不读取 Bot 凭据，不要求 Loop 服务复制 cc-connect 的密钥环境。**不要用 `relay send` 发通知，它会再次启动目标 Agent。**
- 发送时不重读配置和 Bot 目录。配置文件只用于接入/发现；接入保存实际数据目录，后续使用选定的二进制和目录。变更桥接数据目录时更新本机接入配置。
- 已有 thread_root 且原标识是已知 thread 形式时，用该根消息构造 root 发送目标；已有 root 以及其他格式原样传递。缺根消息时直接传原 session_key，由 cc-connect 解释，不查询历史或让 Agent 另找密钥。话题 ID 不冒充根消息 ID。
- 实际投递、群权限和话题支持由运行中的 cc-connect 负责。Loop 保留原会话，不自行改投群时间线；桥接成功/失败按真实结果记录。缺二进制等明确未调用发送的情况可沿原规则回退，发送调用后的失败或超时不自动换 Bot 重发。

已核对的旧 cc-connect `v1.5.1-beta.1 / 80713167` 支持用 root 消息 ID 重建无缓存回复目标，但不能把真正的 thread ID 当消息 ID 使用。入口有根消息时必须随会话保留；缺失时由实际桥接处理并报告结果，Loop 不再实现第二套查询或预检。此处不声称任意桥接版本都能正确处理所有话题格式。

直连 HTTP/MCP 的客户端可以传纯元数据：

```json
{"chat_context":{"platform":"feishu","entry_project":"入口Bot的project","session_key":"feishu:oc_chat:root:om_root"}}
```

入口事件有 chat_id/thread_id/thread_root 时一并传递；chat_type 可选，缺失保持 unknown。worker 不能重写入口。普通 cc-connect root 会话由平台自动提取并保存根消息；不要求额外环境变量。

兼容旧客户端：`communication_config(operation=conversation, conversation=元数据, notification_command=本机argv)` 可注册 conversation_id。旧 `--config`、`--platform`、`--conversation` 参数仍可解析，但不再用于发送预检；自定义实例须显式提供实际 `--data-dir`，或改用机器级接入。

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
