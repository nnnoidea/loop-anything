# 可选适配器：cc-connect

这是平台提供的第一个通知适配示例，实现[通用通知接口](notifications.md)。使用其他桥接或纯终端时无需安装 cc-connect。平台不替用户创建机器人、管理聊天会话或启动桥接。

## 使用前提

用户已安装并配置 [cc-connect](https://github.com/chenhg5/cc-connect)，目标渠道已连接。桥接接入的 Agent 和平台使用同一个平台实例；以下示例要求适配器、Python 和 cc-connect 命令在平台所在机器可访问。

实际渠道能力由桥接及其版本决定。飞书和微信的扫码、机器人配置、发送限制以桥接说明为准，不把接口适配完成当成真实渠道联调成功。

## 自动跟随原聊天

平台 0.6.1 起，飞书/Lark 入口 Agent 通过 `scripts/call.py request_assistance` 或 `start_run` 调用时，客户端只读取 `CC_PROJECT`、`CC_SESSION_KEY` 并随业务请求提交 `chat_context`。客户端不查找 cc-connect、不读取渠道配置、不查询飞书、不构造发送命令，也不单独注册会话。平台持久保存来源并复用同一会话绑定，发送适配器负责渠道检查与投递。无需先给通信群组配置固定接收群。显式 `notification_route`、`conversation_id` 或发送命令优先；子请求也可选择 `notification_route=workspace`，此选择在来源平台和追问中保留；平台内节点和嵌套外援沿用已保存来源。

- 私聊：入口 Bot 回复原私聊。
- 群聊：请求由入口 Bot 提示；具名 Agent 的执行确认、结果优先由其对应 Bot 回复原群/原话题。没有映射、离线或发送前检查不通过时，由入口 Bot 代发。
- `通信 → 具名 Agent → 编辑 → 对应 Bot 的通知出口`，或 `communication_config(operation=agent, agent={notification_route:出口ID})` 建立映射。不同 Agent 可映射不同 project。通知出口继续使用 cc-connect 适配器，identity 是该 Bot 的 project；接收位置在此路径由原会话覆盖，不取该出口预设的其他群。其他适配器必须明确支持 `conversation` 输入和 `not_sent` 回执后才能用于此映射。
- 嵌套外援和追问继承原始会话，不将中转机器的聊天当新入口；无 Loop、本机具名 Agent 同样支持。
- 每条通知保存来源、选中 Bot、回退原因和送达回执。仅适配器明确返回 `delivered=false, not_sent=true`（从未调用发送）才能回退；CLI 已启动后失败、超时或平台重启一律不自动改投。远端已入队但失联也不会贸然切换。

### cc-connect 前提与核实范围

核对过本机 `v1.5.1-beta.1 / 80713167` 的[飞书实现](https://github.com/chenhg5/cc-connect/blob/80713167/platform/feishu/feishu.go)和[relay 实现](https://github.com/chenhg5/cc-connect/blob/80713167/core/relay.go)：完整会话格式是 `feishu:chat_id:user_id`，话题是 `feishu:chat_id:root:message_id`（Lark 前缀为 `lark`）。`send --session` 重建回复位置；**不要用 `relay send` 发通知，它会再次启动目标 Agent**。

话题入口和目标 Bot 项目均需 `thread_isolation=true`、`reply_to_trigger=true`。话题群缺少 root ID、根消息不可读、配置禁止话题回复时，明确失败，不能发送到群主时间线。普通群里使用话题回复也应开启话题隔离，否则桥接环境没有足够信息恢复原话题。

发送适配器在发送机检查本机 cc-connect TOML（默认 `~/.cc-connect/config.toml`；自定义路径在发送机配置，在平台该 Bot 的通知出口命令中追加 `--config /绝对路径/config.toml`）。使用现有 Python 3.11+ 的 `tomllib`，或已安装的 `tomli`；适配器会寻找可用解释器，不安装依赖。命名 Bot 出口同样自动选择本机可用的 TOML 解释器；捕获会话的 Run 通知和具名 Bot 发送均提供至少 60 秒，覆盖预检与发送。

检查通过飞书只读接口确认聊天类型、Bot 在群、原根消息属于该群；因此应用需要获取群信息、判断是否在群、读取原消息的相应权限。群发言受限且无法证明目标 Bot 可发言时回退入口。密钥仅从发送机配置读取，不放入平台会话记录或 NAS。当前适配器面向 cc-connect 的自建飞书应用凭据；第三方商店应用需要对应授权适配。

配置应与正在运行的 bridge 一致。配置文件在 bridge 启动后修改时先重启 bridge，再使用话题通知；平台不会修改或重启 bridge。预检无法提供发送时刻的原子权限保证，真正发送后的错误保留原出口待核查。`chat_context` 不携带调用机器的命令、配置路径或凭据，可随请求提交到显式指定的平台；发送机须有对应入口 Bot 的适配配置。平台按 `channel=cc-connect` 和入口 project 的 identity 查找适配器。同一 Bot 的多个接收位置可共用相同 command/cwd，超时取较大值，接收位置使用原会话；多个不同适配器配置则记录 waiting_configuration，任务继续。修正配置后可显式重试未发送的通知；已选定发送配置不自动更换。没有对应配置时使用内置适配器和发送机默认配置。自定义 `--executable`、`--data-dir`、`--config` 在平台通知出口配置一次，客户端不再每次生成命令。缺命令、配置或预检失败仅影响通知回执，Run/外援仍可启动并完成；原群/话题不会静默改投，发送结果未知不换 Bot 重发。

直连 HTTP/MCP 的客户端可在 request_assistance/start_run 中直接传纯元数据，例如：

```json
{"chat_context":{"platform":"feishu","entry_project":"入口Bot的project","session_key":"feishu:oc_chat:root:om_root"}}
```

chat_type 可选（p2p/group），未提供时由发送适配器核实；平台保存适配器返回的已核实类型，未知类型的具名 Bot 候选必须通过预检，私聊只能由入口 Bot 发送。嵌套外援继承原来源；worker 不能用 chat_context 改写入口。

兼容旧客户端：可先用 `communication_config(operation=conversation, conversation=元数据, notification_command=本机argv)` 注册，取得 `conversation_id`，再传给 `request_assistance` / `start_run`；命令在可信工作区注册，无需Loop编辑解锁；远端 worker 限定入口不能登记任意命令。`start_run` 的普通 Timeline 通知自动复用该注册命令，无需再传一次。

源码核实与模拟多实例测试不等于真实 Bot 跨群/跨话题验收；真实 NAS 与飞书应用权限、实际送达仍在安装环境验收。

## 平台命名出口

平台「通知出口」选择 cc-connect，发送身份填已配置的 project，接收位置填 session。也可用 read_notification_channels 返回的 cc_connect_command 配合 set_notification_channels 保存同样配置。适配器从通知的 outlet.identity / destination 读取实际目标；命令中的旧 project/session 仅在未提供这些字段时使用。命令可追加 --executable 和 --data-dir 指定既有安装位置。

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
