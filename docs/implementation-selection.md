# 候选实现与 Binding

节点描述职责和输入输出契约；Implementation 描述具体怎样执行；Binding 选择本次使用哪个实现。一个节点可以没有实现，也可以有多个实现和可选默认值。选择已有候选不需要复制或重新定义 Loop。

## 定义候选

`implementations` 仍按节点组织。多候选形式为：

```json
{
  "train": {
    "default": "local",
    "options": {
      "local": {"kind": "command", "command": ["python3", "train.py"]},
      "cluster": {"kind": "external", "command": ["python3", "submit.py"], "observe": ["python3", "poll.py"]}
    }
  }
}
```

`default` 可省略或为 null，不擅自挑第一个候选。原先单个 `{kind, command, ...}` 是一个名为 `default` 的默认候选的简写，现有 Loop 和历史运行继续可用。

作者调用 `set_implementation`，提供 draft_id、revision、node_id、implementation_id 和具体配置。`default:true` 设为 Loop 默认；`default:false` 清除该候选的默认地位；省略不改变默认。已存在的候选可只传 ID 和 default 来调整选择，不必重写命令。`unbind:true` 删除指定候选，并在必要时清除默认。未传 implementation_id 时使用简写候选 `default`，维持原调用方式。删除候选是编辑草稿，不修改已安装版本或在途 Run。

所有候选沿用节点的输入输出契约。`$notifications` 保留现有独立发送命令配置，本次不扩展通知插件。

## 使用时选择

选择优先级为：**任务指定 → Run 的节点选择 → Loop 默认**。

- `start_run` 可提供 `bindings:{"train":"cluster"}`，创建同一个 Loop 的 Run。CLI `create/run --bindings 文件.json` 接受相同映射。
- Run 中调用 `change_settings`，传当前 settings revision 和 `change:{"bindings":{"train":"cluster"}}`。此映射整体替换；省略节点沿用 Loop 默认，节点值 null 表示本次暂不选用。
- 构建任务时，`build_plan` 可提供 `steps.<step>.implementation`。省略时沿用模板或 Run 默认；空字符串表示撤销模板选择、使用 Run 默认。
- 修改未派发任务或重试失败任务时，`change_task` 可提供 `implementation`。空字符串恢复继承 Run 默认。重试前仍需确认上一次执行的副作用。
- `read_task` 返回候选配置、当前实际选择及 task_version。默认变化导致待执行任务选择变化时，需要重新读取，旧版本结果不能提交。

Loop 库展示候选和默认值，启动表单可直接选择；Timeline 设置可调整 Run 默认。任务级选择通过上述结构化工具操作。

## 执行与检查

Engine 只读取选择结果，不自行挑选或失败后自动换实现。每次派发保存 implementation_id 和完整配置；默认变化只影响后续未派发且未明确指定实现的任务。已经派发的脚本、Agent、审批和外部事件继续使用原配置，历史结果保持可追溯。

构建、分享、安装和创建 Run 不要求配齐所有节点。输入就绪、实际需要执行某项任务时，未选用实现会产生明确的 missing_implementation 问题，交由当前 Agent 或既有异常处理路径处理。

smoke 仍逐项报告所有候选的路径、命令及资源问题，不自动修复。候选未就绪不阻止创建 Run；包清单或随包资源损坏仍阻止使用。没有启动实际执行的候选不会因检查而被运行。

兜底也通过声明节点的候选实现选择 Agent。Loop 的 fallback_node 可留空关闭，Run 可覆盖该选择；没有兜底配置时，平台不会遍历其他节点寻找 Agent。
