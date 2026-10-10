# 平台连接与工具调用


本 Skill 是安装到 Agent 的完整操作手册，包含调用脚本和本地平台连接地址。可直接调用通用工具，也可由作者的随包脚本封装同一接口，无需查找平台源码或内部模块。

在本 Skill 根目录运行；在其他工作目录时，使用该脚本的绝对路径：

```sh
python3 scripts/call.py check
python3 scripts/call.py list
python3 scripts/call.py read_capabilities
python3 scripts/call.py TOOL --arguments @参数.json
```

脚本仅使用 Python 标准库，可用本机兼容的 Python 3.9 或以上，不依赖安装平台时的 Python 路径。Windows 可使用 `py -3`。

`connection.json` 保存平台地址；非默认地址或唤醒 prompt 提供了实际 `platform_url` 时，加 `--url 实际地址`。源码、安装资源和导出的 Skill 使用同一份脚本。

可信工作区的查看、运行、通信、通知和终端操作不需要全局解锁。只有修改受保护 Loop 的定义、实现、手册或资源才会返回 `edit_locked` 和对应 loop_id；使用当前 Loop 的 `loop_password` 参数或环境变量 `LOOP_ANYTHING_LOOP_PASSWORD`（兼容旧名 `LOOP_ANYTHING_EDIT_PASSWORD`）。不要把明文口令写进 Loop 定义、Skill 或提示词。可用 `set_loop_password` 设置、修改或清除保护；导出导入携带校验信息，同一 Loop ID 的草稿和版本共用。

首次使用先检查连接，再读取工具目录及其中的 instructions；read_capabilities 返回运行服务的版本、能力到工具的映射、文档入口和支持的 schema 关键字。服务报告 restart_required 时，源码与正在执行的版本不同；不能把磁盘上新增能力当成服务已可用。目录列出当前服务实际开放的机制和参数；手册提到但目录缺失的字段应核对服务版本，不绕过到数据库或内部模块补写。参数可用 JSON 或 `@UTF8文件`；沿用工具返回的 ID、修订号和令牌。具体 Loop 的 key 从 `list_loops` 取得。连接检查不调用模型或创建业务 Run。

每次调用检查返回的 `ok`，报告状态还须检查 `accepted`；失败时脚本退出码为 2。脚本与监控接入统一报告工具时，见 [run.md 的报告说明](run.md#统一报告事件与结果)，调用脚本随 Skill 提供。安排后续任务不等于完成当前任务，文字回复也不是提交回执。作者封装可代为提交与退出；直接调用工具时，按需查看 run.md 中对应操作。

继续工作先用 list_runs 找到已有运行，再 read_timeline；普通工作区操作可不传 token，平台自动管理内部操作标识。平台唤醒的节点必须沿用 prompt 中的受限身份；显式传入错误或过期 token 不会自动放宽范围。微信、飞书、终端共用同一平台和 Timeline，切换入口不会新建 Run 或改变通知目标。


## 安装与更新入口

平台安装和升级时，使用当前平台 Python 导出 Skill：

```sh
"<平台 Python>" -m loop_anything skills --install-dir "<Agent Skill目录>" --url "<实际平台地址>"
# 更新已有平台 Skill，保留实际平台地址；其他个人文件不会删除
"<平台 Python>" -m loop_anything skills --install-dir "<Agent Skill目录>" --url "<实际平台地址>" --replace
```

平台升级和 Skill 更新是两个步骤。使用目标 Agent 支持的 Skill 目录，不猜测安装位置；更新后让 Agent 重新加载 Skill，再执行 check 验证运行服务。Skill 的新说明不代表旧服务已有对应能力；以实际工具 schema 为准。平台未安装时按发行包 README 或源码 README 安装。安装和只读发现不启动模型或创建 Run。
