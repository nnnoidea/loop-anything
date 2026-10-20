# 从 Skill 开始，用流程 Agent 推进

适用于用户已有一份操作 Skill，或下一步需要根据结果临场判断的 Loop。它是一种现有机制的组合：**普通 Agent 节点在决策点被唤醒，按自然语言业务规则安排工作，再退出**。纯状态机流程无需增加它，也不需要另建常驻控制器。

Timeline 统一保存状态与记录，确定性状态机负责按规则计算转移。流程 Agent 仍通过下述任务工具提交业务安排与结果，沿用同一写入机制；两种推进方式共用已有状态，不另存一份流程进度。

## 初次构建

Loop handbook 是流程 Agent 的完整依据，保存整体目标、约束、推进规则和结束条件；流程 Agent 直接完整读取，不再另写一份重复的流程节点 Skill。具体工作节点按职责保留自己的专业方法，流程 Agent 需要了解时也可以读取。保留原 Skill 的业务方法与限制，无需先穷举全部分支。

- 已确定的输入、动作和转移用脚本、plan、routes 或 lifecycle。
- 不确定的下一步由流程 Agent 读取结果后选择。可以先让大部分业务推进由它决定，后续再固化。
- 训练等长任务用 external 的短 observe 查询；有回调用 event，定时等待用 timer。等待时不保留一个持续轮询的 Agent。

`read_capabilities(capability="flow_agent")` 返回 `flow_agent_decision` 可改用示例，包含 put_node 节点字段、源节点 routes 和 plan。这些通过正常构建工具保存；Agent 候选继续使用 `set_implementation(kind="agent", command=实际CLI)`，需要远端执行时使用已有群组 dispatch，由承接机器配置 CLI。没有专用模型配置或新的运行协议。既未配置 command 也未配置 dispatch 的 Agent 任务只会停在 decision，不能称为已接好自动执行。

## 何时唤醒

选能观察到的决策点：某任务完成、某批结果齐备、收到用户回复或某个自定义事件。

- 某节点完成：其 `completed` route 展开一个含流程 Agent 的 plan，把来源 Task、事件和结果引用传给它。
- 一批结果齐备：预先安排流程任务，通过 `after` 和 `collect` 等待准确的成员；这期间没有 Agent 进程。
- 某次特定状态转移：route 的 `event` 配合 `when` 中的 `transition.from/to` 选择触发。该事件必须先被实现的 lifecycle 接受；同一 report_id 重试不再创建任务。
- 非终态事件：使用 `detail`、`parameters` 或已有记录传递证据，不能读取尚未提交的 `outputs`。不要把每次 progress 都接到流程 Agent，除非确实需要每次判断。

自然语言推进规则保存在 Loop handbook；本次目标与指导使用已有 settings。**增加一句规则不会凭空产生唤醒事件**：构建 Agent 要同时把它绑定到合适的决策点。例如“连续两轮改善很小就调整方法”可在每轮结果汇总后判断。Loop 定义修改用于后续新 Run，已有 Run 使用版本快照；当前 Run 的指导可由有全局范围的操作者通过 `change_settings` 修改，需新增动作时再用任务工具安排。

流程节点默认只操作自己与后代任务。要统一调整其他支线、修改全局设置或决定 Run 收口，显式 `set_loop(global_agent_node="flow_agent")`；这赋予全局操作范围，不自动创建或反复唤醒它。需要全局协调时用这个已有机制，正常业务判断不要挂到故障 fallback 上。流程 Agent 思考不独占 Timeline；依赖满足后，后代任务可在它 finish 前启动。读取依据在提交时校验；有冲突则重新判断。

## 一次决策如何交接

流程 Agent 先完整读取唤醒上下文或 `read_timeline` 返回的 Loop handbook；若说明绑定文件，则读取其入口文件。再用 `read_task` 读取输入、触发原因和 routes，按需读取当前 settings、相关任务与结果。判断后的工作用 `build_plan`、`add_task` 或 `edit_tasks` 安排；复用稳定 key，重入时先核对已有安排，不因会话中断重建同一批工作。

把**选择、业务理由和证据引用**作为普通输出提交，例如 `decision`；它用于解释业务选择，无需记录模型内部推理。已有 routes 时，输出供路由映射的参数即可，避免再手动创建同一批任务。结果提交与命中的 routes 原子生效；独立的 build_plan/edit_tasks 与结果提交是不同事务，需要按已保存任务继续。

安排下一轮判断时，明确其输入与依赖，或让工作节点的完成 route 创建它。然后 `report_task(event="completed")` 提交当前节点所有输出，检查 accepted，再 `finish` 并退出。流程 Agent 的自然语言回复不代替业务结果。目标达成时用 change_settings 写入平台 completion_rule 或 termination_signal（全局范围，revision 取 read_timeline.settings.revision）；finish 只释放操作权，不代表整个 Run 结束。

## 保留运行记录

已有 Timeline 保存任务安排与来源、执行输入、状态转移、路由和版本化结果。流程 Agent 将选择、业务理由和相关结果引用随正常输出提交，便于还原当时为何这样推进；记录只在聊天中不算交付。读取继续使用已有 read_run、read_task 和 read_record。后续分析和优化方式以后再扩展，当前不增加专用证据工具或强制优化流程。
