# 构建预览与流程验收

使用运行服务的 `read_capabilities` 和 `list` 发现入口。验证分四层：

| 需要确认的事 | 入口 | 实际行为 |
| --- | --- | --- |
| 定义和契约结构正确 | validate_loop、validate_parameters | 静态校验，不运行命令 |
| 模板最终生成哪些任务 | preview_plan；已有 Run 用 edit_tasks preview | 展开真实参数、候选、引用、依赖，返回省略原因 |
| 整条路径按作者预期推进 | test_loop | 隔离数据库，真实 Engine，作者提供模拟报告和断言 |
| 外部环境和 Agent 启动可用 | smoke_runtime 及作者真实接入验收 | smoke_runtime 会启动实际 Agent 命令，可能调用模型；需按任务授权执行 |

流程验收不调用训练、下载、模型或通知发送命令。它不证明真实模型会遵循 Skill，也不验证远程身份、依赖或产物可用性。

## 保存和运行场景

用 `set_loop` 的 scenarios 数组保存到当前草稿，也随导出的 Loop 包交付；普通编辑保留这些场景。未传 scenarios 保留现值，传入整体替换。调用 `test_loop`，传 draft_id 或已安装 key 二选一；省略 scenarios 运行保存的场景，也可传临时 scenarios，覆盖仅作用于本次验收。

```json
{"draft_id":"DRAFT_ID"}
```

检查工具 `ok` 和结果 `passed`：ok=true 只表示工具调用完成，passed=false 表示验收发现问题。每项结果包含 error/failed_step、assertions、state、receipts 和 intercepted_calls。真实数据库、草稿和 Run 不受影响。

## 场景结构

每个场景包含 name、steps、assertions，可选 inputs（Run 初始输入）和 bindings（本次候选选择）。入口语义仍须在初始化的完成报告中给出，不能绕过初始化契约。

steps 按序执行，每步之前用真实 Engine tick 一次：

- 报告：选择 task_id、ref、node 三者之一，提供 report 对象。node 必须唯一匹配一个 Task；多任务使用 ref。可用 attempt 选择某次执行。
- report 使用统一生命周期字段 event、report_id、envelope、detail、external_id、poll_after；未写 report_id 时按步骤生成稳定 ID。
- `duplicate:true` 用同一执行和 report_id 再次提交，必须得到去重回执。
- accepted 默认 true；显式 false 用于检查未覆盖转移。expect_error 填预期错误文本片段，用于检查契约拒绝和整体回滚。
- `{"send_event":{"event_id":"reply-1","name":"reply","key":"question-1","payload":{"answer":"yes"}}}` 使用现有外部事件入口。
- `{"ticks":2}` 推进两次调度。使用真实时钟，不提供虚拟时间；长时间等待可直接提供声明的模拟生命周期报告，不能声称验证了实际等待时长。

Agent Task 完成报告后，验收器通过现有 finish 释放范围；自定义非完成事件继续保留范围。命令型候选的实际启动/观察调用被拦截，由场景报告代替。通知投递回执明确标记 simulated。

每次最多 20 个场景、每场景 200 步、每个 ticks 步 1–20 次。验收有 1000 Task 的执行保护；大型展开应先用小样本验证结构。

## 完整场景示例：A、C 汇总，B 独立执行

假设 Loop 具有以下声明（配置字段见 [参数与引用](contracts.md)）：

- initialize 输出 jobs、groups；完成时 routes 分别展开 work 和 review 两个模板。
- work 按 jobs 展开，Task ref 为 `work:{item.id}`，parameters 为 item.params，输出 result 数字。
- review 按 groups 每项展开，Task ref 为 `review:{values.id}`，输入 results 通过 task_refs 读取 values.members 指定任务的 result，after_refs 同样取 members，输出 done 布尔值。
- 两份模板都从同一初始化报告生成，因此 review 可引用该次报告生成的 work Tasks。

将下列对象放进 scenarios 数组：

```json
{
  "name":"选择性汇总与去重",
  "steps":[
    {
      "node":"initialize", "duplicate":true,
      "report":{
        "event":"completed", "report_id":"initial",
        "envelope":{
          "settings":{
            "objective":"汇总 A 和 C",
            "completion_rule":{"op":"and","args":[
              {"op":"eq","args":[{"path":"active_tasks"},0]},
              {"op":"eq","args":[{"path":["completed","review"]},1]}
            ]}
          },
          "outputs":{
            "jobs":[
              {"id":"A","params":{"value":0}},
              {"id":"B","params":{"value":1}},
              {"id":"C","params":{"value":2}}
            ],
            "groups":[{"id":"selected","members":["work:A","work:C"]}]
          }
        }
      }
    },
    {"ref":"work:A","report":{"event":"completed","envelope":{"outputs":{"result":0}}}},
    {"ref":"work:B","report":{"event":"completed","envelope":{"outputs":{"result":1}}}},
    {"ref":"work:C","report":{"event":"completed","envelope":{"outputs":{"result":2}}}},
    {"ref":"review:selected","report":{"event":"completed","envelope":{"outputs":{"done":true}}}}
  ],
  "assertions":[
    {"message":"Run 已收口","test":{"op":"eq","args":[{"path":"status"},"completed"]}},
    {"message":"没有重复生成","test":{"op":"eq","args":[{"path":"task_count"},5]}},
    {"message":"只汇总 A、C","test":{"op":"eq","args":[{"path":["by_ref","review:selected","resolved_inputs","results"]},[0,2]]}}
  ]
}
```

jobs.params 必须满足作者实际选择的候选契约；上例仅假设其接受 value。不要把示例参数强加给其他候选。

## 断言上下文

沿用平台确定性表达式 path/op/args，支持 eq/le/ge/add/len/and/or；path 可用数组，避免引用名含点号时被拆分。

- status、task_count、route_count。
- tasks：最终 Task 数组，含实际 spec、status、attempt、resolved_inputs 和 outputs_value。
- by_ref、by_id：同一 Task 数据按稳定引用或 Task ID 索引。
- counts：每个节点的 total、completed 和实际出现的各状态计数。没有出现的其他状态字段不存在。
- records：最新业务结果值，按 record ID 索引。

断言必须精确描述作者期望的行为。平台不会从自然语言说明猜测“正确结果”。参数错误、缺失引用、非预期转移与等待中的任务会保留在结果中，不能把测试没报异常当作 Loop 已完成。
