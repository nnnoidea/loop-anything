"""One factual responsibility map for live discovery and the exported authoring Skill."""
import copy
import json

# activation, platform responsibility, author responsibility, configuration, limits.
MECHANISMS = {
    'assistance_session_resume': ('configured/operator', '等待外援前检查原生 session 和准确恢复命令；回复或期限到达后恢复同一会话与 Task，携带结果和新操作凭据。', '配置托管 CLI 与 resume_command，登记真实 session；wait_assistance 成功后再 finish，远端还需完成执行请求。', ['wait_assistance','register_agent_session','implementations.*.resume_command'], '原机器/Agent/session 固定；缺失或恢复失败时明确阻塞，不新建对话。当前恢复使用 macOS/Linux 终端，CLI 自身的会话文件须保留。'),
    'group_notifications': ('configured/operator', '群组默认通知出口和发送机器；来源通过 NAS 持久交付通知，指定机器复用 cc-connect 等已有适配器投递并写回真实回执。', '在发送机器配置本地命名出口，再用 group_notifications 绑定群组；提供 cc-connect project 和聊天 session。', ['communication_config(operation=group_notifications)','platform notification channels'], '命令和凭据不写入 NAS；旧请求固定原绑定。离线保留待回执，不自动切换机器；未知送达须核实后显式重试。'),
    'timeline_storage': ('automatic', '持久化 Run、Task、执行尝试、版本化结果、事件和历史；正式写入使用同一数据库事务。', '定义业务结果 schema，并通过正式报告提交事实。', ['nodes.*.outputs','records','report_task.envelope'], '外部系统的副作用不属于本地事务；平台不会代替外部服务提供 exactly-once 提交。'),
    'task_scheduler': ('automatic', '检查输入与 after 依赖、暂停点、实现选择、并发额度和操作范围，派发就绪任务。', '声明任务、数据来源和依赖；需要后继自动生成时配置 routes。', ['plans.*.steps.*.inputs','plans.*.steps.*.after','settings.max_parallel','nodes.*.routes'], '依赖连线仅推进已有任务；默认不会推断缺失业务任务。'),
    'execution_recovery': ('automatic', '重启后恢复已持久化执行状态，保留重试和监控身份，暴露无法确认停止的进程与操作权。', '让外部提交和观察可恢复，核对未知外部副作用，必要时确认旧进程已停止。', ['implementations.*.observe','implementations.*.lifecycle','command'], '未知进程状态不会被当作安全完成；外部幂等和身份解析由适配器负责。'),
    'implementation_selection': ('declared', '按 Task 指定、Run binding、Loop 默认的顺序选择候选；校验节点和候选参数，保留执行快照。', '提供真实候选、参数契约与入口；在安排任务时确定自动阶段所需参数。', ['implementations','settings.bindings','Task.implementation','Task.parameters'], '平台不自动补默认参数、不生成业务命令、不修复执行环境。'),
    'workspace_inspection': ('automatic', '提供 Loop 结构、任务依赖、执行状态、结果、输入来源、历史、参数编辑、预览及文件结果展示。', '提供有意义的节点名称、schema title/description、明确的文件输出和业务结果。', ['nodes.*.label','records.*.title','records.*.description','records.*.format'], '现有工作台是操作界面；没有独立的脱敏团队只读看板。文件展示不证明产物有效。'),
    'agent_communication': ('configured/operator', '平台提供本机具名Agent目录、NAS群组收发、明确认领、进度结果、会话和等待恢复；通信不要求创建Loop。', '先配置已挂载的共享空间，用 communication_workspace(discover=true) 发现群组并显式加入；再配置具名 Agent 对应的本机 CLI/工作目录/恢复命令及开放群组，支持转交加入说明；Loop绑定群组，节点显式声明群组执行；外援由Agent按需请求。', ['communication_config','implementations.*.dispatch','request_assistance','wait_assistance'], '本地节点只由来源平台执行；群组不是业务Run副本；session不决定认领。失联不自动重跑。NAS实际环境需安装时检查，逐键远程PTY尚不承诺。'),
    'agent_resume': ('configured/operator', '每个任务直接查看对应尝试的结果；记录CLI原生ID，按用户请求恢复同一会话，签发新操作权并保持历史结果。', '提供CLI及恢复命令；让CLI输出或Agent报告真实ID。用户选择恢复目标和本次要求。', ['implementations.*.agent_cli','implementations.*.resume_command','register_agent_session','command argv {{session_id}}'], '不使用--last猜测，不扫描无关CLI历史。进程退出前同原生ID跨Run互斥；外部手动CLI进程由用户管理。旧任务没有原生ID时需明确补充；CLI本机记录丢失会恢复失败。恢复只适用于仍在运行或暂停的Run；原生CLI会话存储与模型访问由CLI负责。'),
    'agent_terminal': ('automatic/configured', '为后台 Agent 每次执行持久化实时输出；可选交互终端连接同一 CLI 进程，转发键盘和窗口尺寸，finish 后关闭会话。', '提供 CLI 命令、工作目录、登录与权限配置；交互命令用 {{prompt}} 或 {{prompt_file}} 接收任务上下文。', ['implementations.*.terminal','implementations.*.command','任务详情 → 执行终端'], '普通命令只读；交互终端当前支持 macOS/Linux。进程重启后只保留历史并按既有操作权恢复，不保证恢复 CLI 会话。终端访问需要编辑权限，结果仍须 report_task/finish；不要重复构建日志页。'),
    'host_service': ('configured', '在已安装主机持续运行服务，保存工作区；提供受支持系统的防休眠和 macOS 后台托管。', '安装并选择主机、数据库、端口与所需凭据；可按运行需求配置主机。', ['service CLI','platform keep-awake setting'], '远程计算平台、凭据、训练环境和跨机器部署由安装或业务适配负责。'),
    'authoring': ('operator', '保存同一草稿及 revision，校验定义，生成本机可用版本；运行固定在启动时版本。', '设计业务节点和方法，持续编辑已有草稿；需要分享时导出。', ['Loop.id/version','draft revision'], '保存草稿、保存可用版本、打包分享用途不同；不会自动迁移历史 Run。'),
    'parameter_contracts': ('automatic', '在正式任务写入及执行选择时校验嵌套输入输出与参数。', '声明真实契约，调用预校验工具定位缺失字段。', ['nodes.*.parameter_schema','implementations.*.parameter_schema','records'], '不解释领域含义，也不把 schema.default 注入参数。'),
    'conditional_contracts': ('declared', '执行条件必填、互斥与组合类型检查，对不支持的 schema 关键字报错。', '将确定性的参数要求声明在 schema 中。', ['parameter_schema.if/then/else','parameter_schema.oneOf','parameter_schema.dependentRequired'], '仅支持公布的 JSON Schema 子集；业务 CLI 参数投影仍由实现负责。'),
    'plans': ('declared', '生成 Task/输出身份，按 each 展开，按 collect 聚合，解析输入和 after，按 when/skip 省略步骤。', '定义稳定工作骨架、批次参数、输入映射和可选步骤。', ['plans.*.parameters','plans.*.steps','steps.*.each/when','inputs.*.from/collect'], '省略项不创建占位结果，消费者需明确复用来源；plan.when 作用于步骤，先于该步骤 each。'),
    'event_routes': ('declared', '接受节点事件后映射结果参数并展开计划，与结果写入一起提交；重复报告返回同一回执。', '声明 event、plan、values 和需要的 each/when/steps；节点只提交业务结果。', ['nodes.*.routes','report_task.report_id'], '仅由接受的生命周期报告触发；同一后继不要又在 helper 中主动生成。'),
    'task_refs': ('declared', '把业务 ref 解析为真实 Task/record 身份，支持同一报告各批次间前向引用。', '提供 Run 内唯一名称及明确的汇总成员；循环名称包含轮次。', ['steps.*.ref','steps.*.after_refs','inputs.*.task_ref/task_refs'], '引用缺失或重复会拒绝提交；没有自动推断成员的任务组调度器。'),
    'record_versions': ('automatic', '任务输出引用固定生产者版本，保存真实输入来源；汇总可读取不同版本的记录。', '通过 task_ref/task_refs 声明来源；需要覆盖版本时明确指定。', ['inputs.*.revision/revisions','resolve_refs'], '普通 record 来源未指定版本时沿用最新值语义；版本固定不校验远端文件内容。'),
    'task_edits': ('operator', '按 revision 和范围检查预览或原子应用有序任务编辑，失败时整组回滚。', '选择本次改动并检查预览。', ['edit_tasks.changes','edit_tasks.preview','Timeline.revision'], '独立工具调用不是跨调用事务；结果和后继一起提交可用 routes。'),
    'lifecycle': ('declared', '执行明确状态转移、同 Task 重试、停止异常观察、按配置进入兜底；记录未覆盖事件。', '外部适配器报告有限事实；声明转移、重试条件和业务修复方法。', ['implementations.*.lifecycle','implementations.*.command/observe','Loop.fallback_node'], '正常排队或耗时不会自动成为业务失败；重试次数与修复策略按明确配置执行。'),
    'waits': ('declared', '原生 timer/event/approval Task 表达等待；外部事件按名称和关联键匹配，状态持久化。', '声明等待时间、事件键或审批任务，以及收到结果后的 routes。', ['implementations.*.kind','implementations.*.wait','implementations.*.event'], '通知本身不暂停运行；等待需有明确 Task。聊天桥接和业务事件来源由适配器接入。'),
    'notifications': ('configured', '按出口排队投递、去重、保存回执；未配置出口显示等待配置，投递失败保留故障。', '配置实际发送命令/目标，声明通知内容和询问关联键。', ['platform notification channels','settings.notification_route','lifecycle.transitions.*.notify','notify.reply'], '本地通知区收录不代表外部送达；平台不会自行安装聊天机器人。'),
    'scopes': ('automatic', '按父子归属保护操作范围，允许不相交支线并行，维护获取和释放操作权。', '让任务归属对应真实责任，完成或明确等待后 finish；全局判断使用明确的全局节点。', ['Task.parent_id','Loop.global_agent_node','acquire_run/finish'], '依赖与归属含义不同；父 Agent 持有范围时，子 Agent 需等待释放。'),
    'run_control': ('operator', '提供暂停/恢复、任务编辑、用户请求与等待登记，Hooks 可在前后或状态转移时暂停/通知。', '按用户意图选择干预位置和动作。', ['settings.hooks','command','defer_task','resolve_request'], '自然语言授权由用户的 Agent 理解，平台执行显式操作与权限检查。'),
    'termination': ('declared', '按 completion_rule 或 termination_signal 将 Run 收口并停止剩余工作。', '声明可判定的终止条件，或将已确认的完成判断写入相应设置。', ['settings.completion_rule','settings.termination_signal'], '业务输出里的 satisfied/status、没有剩余任务或 finish 都不会自行结束 Run。'),
    'scenarios': ('operator', '用真实 Engine 在隔离库中推进作者提供的模拟报告，检查任务展开、依赖、去重和收口。', '给出代表性输入、模拟事实与可观察预期。', ['Loop.scenarios','test_loop','preview_plan'], '拦截命令/模型/通知投递，不能替代真实外部环境和模型行为验收。'),
    'packages': ('operator', '打包定义、候选和作者资源，检查能力要求并安装；工作区历史保留。', '附带实际使用的文件、声明依赖和能力要求，提供目标环境配置。', ['Loop.requires','package assets','export_loop'], '平台不自动补业务依赖；包安装不启动业务 Run。'),
    'author_skills': ('declared', '按 Loop/节点绑定返回作者方法及安装后的路径，保留包内相对结构。', '编写领域方法、所需证据、输入输出和完成标准。', ['Loop.handbook','nodes.*.skills','put_asset'], '绑定脚本资产不会自动把它注册成候选实现；业务方法不会由平台生成。'),
    'runtime_smoke': ('operator', '执行显式请求的真实最小 Agent 启动，并模拟生命周期矩阵的报告路径。', '按授权选择候选/用例，另行验证真实外部业务。', ['smoke_runtime'], '该检查可能调用模型；静态校验和模拟通过不代表目标环境已可用。'),
}


def authoring_context():
    return {
        'platform_handles': {
            'execution': '持久化 Timeline、依赖就绪判断、并发派发、操作范围、执行快照与重启恢复。',
            'composition': '参数契约、模板批量展开、条件省略、结果聚合、任务/输出身份和稳定引用。',
            'events': '按声明处理生命周期、报告去重、结果与后继原子提交、重试和已配置兜底。',
            'interaction': '原生等待、暂停点、通知回执、显式 Run 收口，以及结构/任务/结果/历史工作台、实时 Agent 输出、可选交互终端及原生会话恢复。',
        },
        'author_provides': ['业务意图与方法、需要交付的结果和允许的动作。', '节点契约、候选实现及真实外部接口适配。', '声明式依赖/路由/恢复策略、凭据与环境配置、验收预期。'],
        'construction_rule': '先将用户需求对应到这些机制，按 activation 和 configuration 配置使用。新增脚本前说明它承担的业务或外部接口职责；确有机制缺口时给出具体用例和缺失语义。节点数量按实际业务职责决定。',
        'details': {'tool':'read_capabilities','arguments':{},'reference':'references/platform-capabilities.md'},
    }


def mechanism_details(name):
    mode,platform,author,configuration,limits = MECHANISMS[name]
    return {'activation':mode,'platform_handles':platform,'author_provides':author,
            'configuration':list(configuration),'limits':limits}


PATTERNS = {
    'shared_space_onboarding': {
        'use_when':'各机器独立安装后，首次寻找共同群组并开放具名 Agent。',
        'capabilities':['agent_communication'],
        'configuration':['communication_config(operation=space,path=本机已挂载目录) 保存共享空间并检查本机读写；各机路径可以不同，核对返回 space_id。',
                         'communication_workspace(discover=true) 返回各空间群组及读取错误；发现不自动加入。创建用 operation=group、space_id、create=true、name；加入用 space_id、relative_path、group_id。',
                         '用 operation=agent 显式配置本机 CLI、cwd、resume_command，并选择 groups；加入群组不自动开放任何 Agent，也可只调用别人。',
                         'communication_workspace(group_id=...) 返回不含本机命令、凭据和挂载路径的加入说明；communication_status 查看开放成员，再绑定 Loop 或普通对话。'],
        'author_provides':'共享 NAS 的访问方式与本机挂载路径、群组用途、本机允许启动的 Agent 命令；NAS 权限负责准入。',
        'verification':['communication_workspace','communication_status','communication_config']},
    'group_cc_connect_delivery': {
        'use_when':'A 发起、B 执行，但只有 C 安装了 cc-connect，需要向同一飞书群通知协作进展。',
        'capabilities':['group_notifications','agent_communication','notifications'],
        'configuration':['在 C 配置命名通知出口，使用平台 cc_connect_command 和明确的 project / 聊天 session。',
                         'C 调用 communication_config operation=group_notifications，选择 group_id、notification_route 和 notification_level；已有绑定需带当前 binding_id。',
                         'A 通过 communication_status 看到绑定后发出请求，省略 notification_route 即沿用群组；平台负责排队、去重、投递及回执。'],
        'author_provides':'指定群组、发送机器和实际聊天目标；业务 Agent 无需编写 NAS 通知队列或自行调用 cc-connect。',
        'verification':['communication_status','read_assistance','communication_workspace']},
    'named_agent_assistance': {
        'use_when': '当前节点或普通对话需要临时外援；外援可在本机，也可在明确选定的 NAS 群组中。',
        'capabilities': ['agent_communication', 'agent_terminal', 'assistance_session_resume'],
        'configuration': [
            'communication_status 发现显式开放的本机目录和获准群组，使用 agent_id 与必要的 instance_id 消歧。',
            'request_assistance 返回持久请求及读取凭据；本机调用不要求 NAS，无 Loop 调用不创建业务 Run。',
            '平台托管节点先记录原生 session 和恢复配置，再使用 wait_assistance 持久等待并 finish；回复或期限到达后在原机器恢复同一个 CLI session，以新凭据和外援结果继续同一个 Task；不可恢复时明确阻塞，不新建会话。',
            '外援通过限定客户端 read_context 按需读取关联上下文，通过 complete 提交协助结果；不取得原节点写权限。'],
        'author_provides': '具体问题、需分享的上下文、结果要求和不可用时的业务判断；机器所有者配置具名 CLI 与开放范围。',
        'verification': ['communication_config', 'read_assistance']},
    'group_agent_node': {
        'use_when': '某个正式 Agent 节点需要在其他机器完成。',
        'capabilities': ['agent_communication', 'implementation_selection', 'lifecycle'],
        'configuration': [
            '保持 kind=agent，设置 dispatch.location=group 和 agent_id 或 capability；绑定 Run 群组。',
            '成员申请承接，来源确认后启动；来源平台继续拥有业务 Run。其他本地节点不发布到群组。',
            '通过限定 platform_client/URL 使用 read_task、report_task 和 finish，沿用原结果契约与操作范围。'],
        'author_provides': '节点业务契约、成员选择；执行端提供 CLI、环境和可访问的产物。',
        'verification': ['communication_config', 'read_assistance']},
    'result_to_batch_and_review': {
        'use_when':'源节点给出多组已确定参数，每项工作执行后汇总本批结果。',
        'capabilities':['event_routes','plans','task_refs','task_scheduler','scopes'],
        'prerequisites':'源节点输出 jobs 数组，每项有 id 和 params；work 输出 result；review 输入 results 数组。作者补齐真实实现与业务参数契约。',
        'source_routes':[{'id':'dispatch','event':'completed','plan':'work_and_review','values':{'jobs':{'$':'outputs.jobs'}}}],
        'plan':{'parameters':{'type':'object','properties':{'jobs':{'type':'array'}},'required':['jobs']},'steps':{
            'work':{'node':'work','each':'jobs','inputs':{},'parameters':{'$':'item.params'},'ref':'work:{item.id}'},
            'review':{'node':'review','inputs':{'results':{'from':'work','port':'result','collect':True}},'after':['work'],'ref':'review:batch'}}},
        'execution':'源节点报告 completed 并提交 jobs 后，平台创建工作和汇总任务；依赖就绪时调度。源 Agent 提交后 finish 释放范围。循环使用时给 ref 加轮次。',
        'verification':['preview_plan','test_loop'],
    },
    'external_job': {
        'use_when':'外部系统提交后需要持续查询，结束后消费结果。',
        'capabilities':['implementation_selection','lifecycle','execution_recovery','event_routes'],
        'configuration':['同一 external 候选的 command 提交，observe 查询；报告 submitted 时保存 external_id。',
                         'observer 报告 progress/completed 或已声明失败事件；lifecycle 定义 retry/agent 等处理。',
                         '完成事件可通过 routes 生成后继，输入/after 让消费者等待结果。'],
        'author_provides':'外部 API、执行身份、状态翻译、产物检查与提交幂等策略。',
        'verification':['smoke_runtime','test_loop'],
    },
    'question_then_continue': {
        'use_when':'发送问题，等待对应回复，再生成后续工作。',
        'capabilities':['notifications','waits','event_routes'],
        'configuration':['notify.reply 声明问题的 event/key/schema。', '创建 event Task 等待同一 event/key；收到的 payload 对应节点输出。', '该节点的 completed route 使用回复参数展开后继。'],
        'author_provides':'提问内容、通知出口、外部回复桥接和回复后的业务处理。',
        'verification':['test_loop'],
    },
}


def patterns_for(capability=None):
    return copy.deepcopy({key:value for key,value in PATTERNS.items() if capability is None or capability in value['capabilities']})


def render_guide():
    from loop_anything.capabilities import CAPABILITIES
    lines=['# 平台已承担的能力与作者分工', '',
           '由平台能力定义生成；运行服务的 read_capabilities 为实际可用能力依据。可传 capability 按需读取详细机制与组合示例。', '',
           '构建时先将需求对应到下列机制，再设计业务节点和实现。activation=automatic 表示平台自动执行；declared/configured 需要作者声明或使用者配置；operator 需要显式操作。', '']
    for name in CAPABILITIES:
        row=mechanism_details(name)
        lines += ['## '+name, '', '- 生效方式：'+row['activation'], '- 平台承担：'+row['platform_handles'],
                  '- 作者提供：'+row['author_provides'], '- 配置入口：'+ '、'.join('`'+s+'`' for s in row['configuration']),
                  '- 边界：'+row['limits'], '- 工具入口：'+('、'.join(CAPABILITIES[name][1]) or '由运行平台提供，无须单独调用'),
                  '- 详细说明：['+CAPABILITIES[name][2]+']('+CAPABILITIES[name][2].removeprefix('references/')+')', '']
    lines += ['## 常见组合', '']
    for name,value in PATTERNS.items():
        lines += ['### '+name, '',value['use_when'], '', '```json', json.dumps(value,ensure_ascii=False,indent=2),'```','']
    return '\n'.join(lines)
