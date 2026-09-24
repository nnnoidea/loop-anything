# 可选适配器：cc-connect

这是平台提供的第一个通知适配示例，实现[通用通知接口](notifications.md)。使用其他桥接或纯终端时无需安装 cc-connect。平台不替用户创建机器人、管理聊天会话或启动桥接。

## 使用前提

用户已安装并配置 [cc-connect](https://github.com/chenhg5/cc-connect)，目标渠道已连接。桥接接入的 Agent 和平台使用同一个平台实例；以下示例要求适配器、Python 和 cc-connect 命令在平台所在机器可访问。

实际渠道能力由桥接及其版本决定。飞书和微信的扫码、机器人配置、发送限制以桥接说明为准，不把接口适配完成当成真实渠道联调成功。

## 平台命名出口

平台「通知出口」选择 cc-connect，发送身份填已配置的 project，接收位置填 session。也可用 read_notification_channels 返回的 cc_connect_command 配合 set_notification_channels 保存同样配置。适配器从通知的 outlet.identity / destination 读取实际目标；命令中的旧 project/session 仅在未提供这些字段时使用。命令可追加 --executable 和 --data-dir 指定既有安装位置。

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
