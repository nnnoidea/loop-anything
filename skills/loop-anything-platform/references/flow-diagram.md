# 给用户看的整体流程

首次形成完整 Loop，或修改节点、分支、循环和任务生成逻辑后，由当前构建 Agent 同步绘制／更新流程说明。结合真实定义、节点 Skill 和相关脚本写业务关系；没有证据的路线不要猜。普通参数修改无需重画，打开网页或每轮运行不启动绘图 Agent。这是构建指导，不是保存或运行的强制检查。

## 每个真实节点都必须可见

整体流程图必须覆盖 `read_loop` 返回的 `loop_definition.nodes` 中的每一个节点。初始化、研究规划、审计、各执行阶段、按需节点和异常兜底节点都要各自有可见图形与可辨认名称，不能因不在正常主路径而省略。分组可以保留，但不能用“实验流水线”“执行阶段”等汇总框替代组内真实节点；图外文字或节点清单也不能替代节点图形。

保存前将定义中的节点 ID、名称与图中节点逐项对照，确认无遗漏，尤其检查新增节点及原有分支。条件、结束标记等辅助图形应与真实节点区分；连线依据实际定义、Skill 和脚本，说明条件与回环，不能把按需安排画成必然执行。同一节点的多次 Task 或重试无需画成新的节点。

内容多时通过分组、调整方向、增大画布或滚动保持完整与可读，不能为适配窄屏删节点。补充局部图可以帮助解释，但不能替代覆盖全部节点的整体图。

## 工具与模板

平台 Skill 随包提供 Answer me with HTML 的离线渲染器（MIT），无须安装另一个 Skill、前端项目或绘图服务。生成需要 Node.js 20+；查看保存的图不需要 Node。以本 Skill 目录为当前目录，其他位置使用绝对路径：

```sh
# 复制模板到自己的工作目录，结合真实业务编辑它
cp assets/flow.md /tmp/my-loop-flow.md
python3 scripts/render_flow.py /tmp/my-loop-flow.md --output /tmp/my-loop-flow.html

# read_loop 取得当前 draft revision 后，渲染并保存到同一草稿
python3 scripts/render_flow.py /tmp/my-loop-flow.md --draft-id DRAFT_ID --revision REVISION
# 非默认平台可追加 --url http://127.0.0.1:8769
```

命令复用 `call.py` 的连接及 Loop 口令支持，通过现有 `put_asset` 依次保存 `docs/flow.md` 和 `docs/flow.html`，返回新 revision；不会发布版本、启动 Run 或改执行规则。两次写入不是事务：若冲突，错误说明停止在哪个文件，已成功写入的文件保留；重新读取草稿后核对再继续，不盲目覆盖新版本。只渲染时不连接平台。上游自动更新检查关闭，主题配置与用户全局配置隔离。

网页“整体流程”显示 `docs/flow.html`；`docs/flow.md` 保留可编辑源稿。通过 `read_loop(asset_path=...)` 可定向读取，`put_asset` 可直接更新或删除。文件随普通 Loop 包导入导出，不需要新协议。已有页面也可直接写入 `docs/flow.html`，但优先用随包模板和渲染器。无页面时显示待绘制提示，不自动猜测流程。展示位于隔离 iframe，不能访问平台 DOM/API 或外部网络；节点配置和真实状态矩阵仍在各自视图。

## 写法与可用组件

标题、说明、章节使用 Markdown；每个二级标题形成一个内容区。`template: doc` 适合纵向阅读，`sheet` 适合多个面板。流程用 `flow` 代码块，例如：

````markdown
```flow TB
(明确目标) -> 制定方案: 需要探索时
明确目标 -> 执行任务: 已有明确方案
制定方案 -> 执行任务: 提交本轮参数
执行任务 -> 分析结果: 本轮结果齐备
分析结果 -> 制定方案: 仍需下一轮
分析结果 -> (结束): 目标已达成
```
````

- `A -> B: 关系文字`：实线；`A --> B: 条件文字`：虚线；`A -> B & C`：分支。
- `(起点)`、`{条件}`、`[(数据)]`：不同形状；`group 分组名: A, B`：分组。
- `TB` 为纵向，`LR` 为横向。节点直接使用名称，不用 Mermaid 的 `id[名称]` 写法。
- 可用 sequence、timeline、tree、表格等补充解释；按需查询，不必把所有组件塞进流程图：

```sh
node scripts/vendor/answer-me-with-html/am.mjs list
node scripts/vendor/answer-me-with-html/am.mjs help flow
node scripts/vendor/answer-me-with-html/am.mjs help sequence
```

主图完整呈现所有真实节点，停止条件、异常处理和按需分支可加短说明辅助。端口清单、候选实现清单和详细状态矩阵仍在各自视图，不要求把它们变成流程节点。生成后预览实际页面，核实节点覆盖、文字、分支及窄屏可读性。
