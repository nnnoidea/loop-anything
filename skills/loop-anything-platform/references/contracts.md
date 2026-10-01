# 参数契约和稳定任务引用

先调用 `read_capabilities`，确认运行服务支持 `conditional_contracts`、`task_refs`。字段以实时 `list` 工具 schema 为准；参考文档与服务不一致时先处理版本差异。

## 一份参数契约，多个入口共用

节点的 `parameter_schema` 声明公共参数，候选实现的 `parameter_schema` 声明候选要求。创建、预览、编辑、重试与执行检查使用同一套校验；同一参数对象必须同时满足两份契约。不会注入默认值、转换类型或过滤字段，实际命令的参数转换由实现负责。

支持的 JSON Schema 子集由 `read_capabilities.schema_keywords` 返回：

- `type`：object、array、string、number、integer、boolean、null，或这些类型的数组。
- `properties`、`required`、`additionalProperties`（布尔或子 schema）、`items`、`dependentRequired`。
- `oneOf`（恰好一个匹配）、`anyOf`、`allOf`、`not`、`if/then/else`。分支 schema 可不写 type。
- `enum`、`const`、数值上下界及 exclusiveMinimum/exclusiveMaximum、字符串长度与 pattern、数组长度和 uniqueItems、对象字段数量。
- `title`、`description`、`default`、`examples`、`format` 是描述性字段；default 如提供会校验其合法性，但不会自动填入运行参数。format 不证明文件存在或符合某种格式。保留已有 nonempty 扩展。
- 布尔 schema true/false 表示允许/拒绝所有值。未列出的关键字（包括 $ref、$defs、patternProperties）明确拒绝，不能依赖它们的语义。

例如，在 `set_implementation.parameter_schema` 中声明：

```json
{
  "type":"object",
  "properties":{
    "mode":{"enum":["existing","build"]},
    "source":{"type":"string","minLength":1},
    "preset":{"type":"string"},
    "template":{"type":"string"}
  },
  "required":["mode"],
  "if":{"properties":{"mode":{"const":"existing"}},"required":["mode"]},
  "then":{"required":["source"]},
  "else":{"oneOf":[{"required":["preset"]},{"required":["template"]}]},
  "additionalProperties":false
}
```

这会拒绝 existing 缺少 source、build 同时提供或均未提供 preset/template，以及任何未声明字段。条件中的 required 很重要：只有 properties 不会要求该字段存在。

创建 Task 前可调用：

```json
{"draft_id":"DRAFT_ID","node_id":"work","implementation_id":"local","parameters":{"mode":"build","preset":"small"}}
```

工具名为 `validate_parameters`；也可用安装后的 key 替代 draft_id。返回 `valid/errors/implementation_id`，不创建任务。它可以帮助 Agent 修正缺失字段，但业务上应选哪组参数仍须依据用户意图和作者 Skill。

## 稳定任务引用

在模板步骤上设置 `ref`，如 `"work:{item.id}"`。它是整个 Run 内唯一、由作者确定的引用名称，不是显示轮次或新调度实体；多轮循环应包含轮次，例如 `"{values.round}:work:{item.id}"`。

```json
{
  "node":"work", "each":"jobs", "inputs":{},
  "parameters":{"$":"item.params"}, "ref":"work:{item.id}"
}
```

汇总步骤直接引用业务项：

```json
{
  "node":"review", "ref":"review:{values.id}",
  "after_refs":{"$":"values.members"},
  "inputs":{"results":{"task_refs":{"$":"values.members"},"port":"result"}}
}
```

本批 values 可为 `{"id":"selected","members":["work:A","work:C"]}`。平台将 after_refs 解析为实际 Task IDs，将 task_refs 解析为对应的 result 记录列表，顺序与 members 一致。

- `task_ref` 读取一个任务的输出，`task_refs` 收集多个任务的同名输出端口；默认固定到各生产者声明的输出版本，避免后来覆盖同一 record 时读错结果。可显式提供 path/revision；显式 revision 优先。
- 普通 records 来源可配 revisions 数组，逐项指定版本，长度必须与 records 一致、每项为正整数，不能同时提供 revision。使用此字段需要 record_versions 能力；任务引用收集不同版本时也使用该表示。编辑器和任务关系图均保留这些版本。
- `after` 仍引用同模板步骤；`after_refs` 引用明确的任务名称。解析后都成为原有依赖，不增加新的任务组状态机。
- 同一 plan 内允许前向引用；同一次接受报告的所有 routes/each 批次也一起解析，规则顺序不影响结果。
- 单独 build_plan 或 add_task 可引用本次生成或 Run 内已存在的 Task；后续独立调用尚未创建的任务不可引用。需要跨规则前向引用时，将生成放在同一次报告的 routes 中。
- 缺失引用、重复名称、未知输出端口和依赖循环均拒绝整次提交。省略步骤不会留下可引用的占位 Task；消费者需显式复用有效输入或一起省略。
- 引用解析后固定为 Task/record 身份；取消某任务不会把名称重新绑定到另一个任务。替代工作应使用新 ref。
- `build_plan` 和 route 回执的 references 返回名称到 Task ID/输出记录的映射。运行中用只读 `resolve_refs` 查询，例如 `{"run_id":"RUN_ID","refs":["work:A"]}`；省略 refs 返回全部。附带 token 时遵守既有操作范围检查。

直接 `add_task` 也支持 ref、after_refs 和这些输入来源。已有 Run 的整组任务编辑使用 `edit_tasks(preview=true)`；原子编辑组按操作顺序执行，后项可引用前项生成的任务。

## 展开预览

`preview_plan` 对草稿或安装版本展开一个模板，不创建 Run，不启动命令：

```json
{"draft_id":"DRAFT_ID","name":"work","batch_key":"preview-1","values":{"jobs":[{"id":"A","params":{"mode":"build","preset":"small"}}]}}
```

返回 tasks、references、omitted，检查节点与有效候选参数和实际依赖。可传 steps、bindings、round；无已有 Run，因此不能引用真实 Run 的其他任务。模板是否符合业务预期可进一步用 [流程验收](testing.md) 验证。
