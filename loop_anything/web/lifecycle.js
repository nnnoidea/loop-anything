 'use strict';
let lifecycleTemplates={};
const lifecycleNames={executing:'执行中',submitting:'提交中',waiting:'等待中',approval:'等待审批',completed:'完成',fault:'失败',retry:'重试原任务',agent:'交给 Agent'};
const lifecycleEvents={progress:'报告进度',submitted:'提交成功',completed:'提交完整结果',failed:'报告业务失败',process_error:'执行进程异常',check_error:'监控检查失败',timeout:'等待超时'};
const lifecycleSources={engine:'平台检测',script:'同步脚本 / 提交脚本',monitor:'附属监控',agent:'Agent',event:'外部事件',submission:'结果提交'};
function lifecycleOf(config){return config?.lifecycle || lifecycleTemplates[config?.kind];}
function lifecycleName(value){return lifecycleNames[value]||value;}
function lifecycleEventName(config,event){return event==='completed'&&config?.kind==='timer'?'计时到达':event==='completed'&&config?.kind==='event'?'收到匹配事件':lifecycleEvents[event]||event;}
function lifecycleReporter(config,rule){
  if(['process_error','timeout','check_error'].includes(rule.event))return '平台检测';
  if(config.kind==='external')return rule.from==='submitting'?'提交脚本报告':rule.from==='waiting'?'监控脚本报告':'执行 / 监控脚本报告';
  return ({agent:'Agent 报告',command:'脚本报告',timer:'平台计时',event:'平台接收外部事件',approval:'用户确认',loop:'平台检查子 Loop',mock:'平台模拟'})[config.kind]||'执行者报告';
}
// Roles describe the configured execution contract, never guesses from business state names.
function executionRole(config,phase){
  if(!config)return {kind:'unknown',label:'未选用实现'};
  const roles={agent:['agent','Agent'],command:['script','脚本'],external:['external',phase==='submitting'?'提交脚本':phase==='waiting'?'外部任务 / 检查脚本':'脚本 / 外部任务'],timer:['platform','平台计时'],event:['platform','平台等待事件'],approval:['human','用户确认'],loop:['platform','平台调用子 Loop'],mock:['platform','平台模拟']};
  const [kind,label]=roles[config.kind]||['unknown','未声明'];
  return {kind,label,detail:config.dispatch?.agent_id||config.executor||config.agent_cli||''};
}
function stateExecutionRole(config,state,context={},rule){
  if(state==='completed')return {kind:'idle',label:'本任务已结束',detail:'不再执行本任务；后续任务按转出关系和运行条件推进。'};
  if(state==='fault')return {kind:'idle',label:'异常待处理',detail:'本次执行停止；是否启动兜底由运行配置决定。'};
  if(state==='agent')return Object.hasOwn(context,'fallback')&&!context.fallback?{kind:'idle',label:'等待处理',detail:'未启用兜底 Agent。'}:{kind:'agent',label:'兜底 Agent',detail:context.fallback?'由“'+context.fallback+'”接手；自动启动仍需实现就绪。':'接手方由本次运行的兜底配置决定。'};
  if(state==='retry'){const role=executionRole(config,lifecycleOf(config)?.initial);return {...role,label:role.label+'重试',detail:'平台等待旧执行释放后，按同一实现重试。'};}
  if(rule?.event==='check_error'&&rule.from===state)return {kind:'external',label:'外部任务 / 检查暂停',detail:'外部结果仍未确认，等待恢复监控。'};
  return executionRole(config,state);
}
function stateRoleHTML(role){
  const symbol=({agent:'✦',script:'⌘',external:'↗',machine:'◇',platform:'◷',human:'人',idle:'—',unknown:'?',mixed:'…'})[role.kind]||'?';
  return `<span class="state-role role-${esc(role.kind)}" data-role-kind="${esc(role.kind)}" title="${esc(role.detail||role.label)}"><i aria-hidden="true">${symbol}</i><span>${esc(role.label)}</span></span>`;
}
function transitionRolesHTML(current,decision,target,labels=['当前执行','转移判断','转入后']){
  return `<div class="transition-roles" aria-label="执行与判断职责">${[current,decision,target].map((role,i)=>`<div data-role-slot="${['current','decision','target'][i]}"><small>${esc(labels[i])}</small>${stateRoleHTML(role)}</div>`).join('')}</div>`;
}
// Only classify explicit built-in semantics; custom events stay neutral.
const transitionTones={normal:'正常推进',failure:'失败处理',retry:'重试',agent:'Agent 处理',other:'自定义转移'};
function transitionTone(r){
  if(r.to==='retry')return 'retry';
  if(r.to==='agent')return 'agent';
  if(r.to==='fault'||['failed','process_error','check_error','timeout'].includes(r.event))return 'failure';
  if(['progress','submitted','completed'].includes(r.event))return 'normal';
  return 'other';
}
function transitionLegend(rules){return `<div class="transition-legend" aria-label="转移颜色说明">${Object.entries(transitionTones).filter(([tone])=>!rules||rules.some(r=>transitionTone(r)===tone)).map(([tone,label])=>`<span class="transition-tag tone-${tone}" data-lifecycle-tone="${tone}">${label}</span>`).join('')}</div>`;}
function hasTransitionCondition(rule){return Object.hasOwn(rule,'when');}
// Display the runtime's small expression vocabulary; never evaluate it or infer a business rule.
function conditionText(expr){
  if(expr===null||typeof expr!=='object')return JSON.stringify(expr);
  if(Array.isArray(expr))return JSON.stringify(expr);
  const keys=Object.keys(expr);
  if(keys.length===1&&keys[0]==='path'){
    if(typeof expr.path==='string')return expr.path==='attempt'?'执行次数（从 1 开始）':expr.path;
    if(Array.isArray(expr.path)&&expr.path.every(k=>typeof k==='string'||Number.isInteger(k)))return '字段 '+JSON.stringify(expr.path);
    return null;
  }
  if(keys.length!==2||!keys.includes('op')||!keys.includes('args')||!Array.isArray(expr.args))return null;
  const arity={eq:2,le:2,ge:2,add:2,len:1,and:null,or:null};
  if(!Object.hasOwn(arity,expr.op)||!expr.args.length||(arity[expr.op]!==null&&expr.args.length!==arity[expr.op]))return null;
  const args=expr.args.map(conditionText);if(args.some(v=>v==null))return null;
  if(expr.op==='len')return '长度（'+args[0]+'）';
  const op={eq:'＝',le:'≤',ge:'≥',add:'＋',and:' 且 ',or:' 或 '}[expr.op];
  return '('+args.join(op)+')';
}
function transitionConditionHTML(rule){
  if(!hasTransitionCondition(rule))return '收到上述事件后适用；平台未另加判断条件。';
  const text=rule.when===true?'始终成立':rule.when===false?'始终不成立':conditionText(rule.when);
  return text==null?`<span>原始条件（未翻译）：</span><pre>${esc(pretty(rule.when))}</pre>`:`<span>${esc(text)}${typeof rule.when==='boolean'?'':'；结果须为 true'}</span><details class="condition-source"><summary>原始条件</summary><pre>${esc(pretty(rule.when))}</pre></details>`;
}
function transitionTaskAction(config,rule,context={}){
  const task=context.taskLabel?'“'+context.taskLabel+'”任务':'当前任务';
  if(rule.event==='check_error'&&rule.to===rule.from)return '停止检查，等待恢复监控；保留'+task+'，外部工作的结果尚未确认。';
  if(rule.to==='retry')return '等待旧进程与执行身份释放后，重试'+task+'（同一 Task 的下一次执行），从“'+lifecycleName(lifecycleOf(config).initial)+'”重新开始。';
  if(rule.to==='agent'){
    const recipient=Object.hasOwn(context,'fallback')?(context.fallback?'由兜底节点“'+context.fallback+'”处理；本次运行需启用兜底且实现可执行。':'当前未配置兜底 Agent，等待用户处理。'):'由本次运行配置的兜底 Agent 处理；未配置时等待用户处理。';
    return task+'记为异常，'+recipient;
  }
  if(rule.to==='completed')return '平台校验并保存'+task+'的结果，当前任务完成。';
  if(rule.to==='fault')return task+'记为失败并保留原因；后续按本次 Run 的异常处理配置处理。';
  if(rule.to===rule.from)return '记录这次报告，'+task+'继续保持“'+lifecycleName(rule.from)+'”。';
  if(rule.to==='waiting'&&config.kind==='external'&&rule.event==='submitted')return '登记外部任务标识，'+task+'等待结果，由平台按约定间隔调用监控。';
  return task+'进入“'+lifecycleName(rule.to)+'”阶段。';
}
function transitionActionsHTML(rule){
  return `${rule.parameters?`<details class="transition-extra"><summary>重试时更新参数</summary><pre>${esc(pretty(rule.parameters))}</pre></details>`:''}${rule.notify?.length?`<details class="transition-extra"><summary>同时发送通知 / 询问 · ${rule.notify.length}</summary><pre>${esc(pretty(rule.notify))}</pre></details>`:''}`;
}
function lifecycleDiagram(config,state,context={}){
  const def=lifecycleOf(config);if(!def)return '';
  const groups=new Map(),targets=new Map();let pairCount=0;
  def.transitions.forEach((rule,index)=>{
    if(!groups.has(rule.from))groups.set(rule.from,new Map());
    const destinations=groups.get(rule.from);
    if(!destinations.has(rule.to)){destinations.set(rule.to,[]);pairCount++;}
    destinations.get(rule.to).push({rule,index:index+1});
    targets.set(rule.to,(targets.get(rule.to)||0)+1);
  });
  const fallbackLink=context.fallbackNode?`<button type="button" class="rule-task-link" data-editor-node="${esc(context.fallbackNode)}" data-editor-detail="info">查看“${esc(context.fallback)}”的职责 →</button>`:'';
  return `<div class="lifecycle-browser" data-lifecycle-browser data-total-rules="${def.transitions.length}"><div class="lifecycle-view-controls" data-editor-view-only><label>目标状态<select data-lifecycle-target-filter aria-label="筛选目标状态"><option value="">全部目标</option>${[...targets].map(([to,count])=>`<option value="${esc(to)}">${esc(lifecycleName(to))} · ${count} 条</option>`).join('')}</select></label><small data-lifecycle-match-count>显示 ${def.transitions.length} / ${def.transitions.length} 条规则 · ${pairCount} 组</small></div>${transitionLegend(def.transitions)}<div class="lifecycle-diagram rule-details" aria-label="按起始和目标状态聚合的规则">${[...groups].map(([from,destinations])=>`
    <div class="phase-group" data-lifecycle-from="${esc(from)}"><div class="phase-source ${from===state?'current':''}"><strong>起始状态：${esc(lifecycleName(from))}</strong><code>${esc(from)}</code>${from===def.initial?'<small>初始状态</small>':''}${from===state?'<small>当前执行所在状态</small>':''}</div>
    <div class="phase-targets">${[...destinations].map(([to,rows])=>{
      const tones=[...new Set(rows.map(({rule})=>transitionTone(rule)))],tone=tones.length===1?tones[0]:'other';
      const actions=rows.map(({rule})=>transitionTaskAction(config,rule,context)),commonAction=actions.every(action=>action===actions[0]);
      const commonCondition=rows.every(({rule})=>!hasTransitionCondition(rule));
      const commonCompletion=rows.every(({rule})=>rule.event==='completed');
      const targetRoles=rows.map(({rule})=>stateExecutionRole(config,to,context,rule)),sameTarget=targetRoles.every(role=>JSON.stringify(role)===JSON.stringify(targetRoles[0]));
      return `<article data-lifecycle-to="${esc(to)}" data-lifecycle-group-to="${esc(to)}" data-rule-count="${rows.length}" data-rule-tones="${tones.join(',')}" class="phase-target tone-${tone}"><div class="rule-heading"><span>${tones.map(t=>`<span class="transition-tag tone-${t}">${transitionTones[t]}</span>`).join(' ')}</span><small>${rows.length} 条触发规则</small></div><strong>${esc(lifecycleName(from))} → ${esc(lifecycleName(to))}${to===from?'（保持）':''}</strong>${transitionRolesHTML(stateExecutionRole(config,from,context),{kind:'machine',label:'状态机',detail:'匹配报告事件并检查规则条件。'},sameTarget?targetRoles[0]:{kind:'mixed',label:'见各条规则'})}${commonAction?`<details class="transition-common-action"><summary>处理结果</summary><p>${esc(actions[0])}</p>${to==='agent'?fallbackLink:''}</details>`:''}${commonCondition?`<p class="transition-common-condition">以下事件未配置平台附加条件。${commonCompletion?'全部输出契约和节点约束仍需校验通过。':''}</p>`:''}<div class="transition-triggers">${rows.map(({rule:r,index},rowIndex)=>{
        const label=lifecycleEventName(config,r.event);
        return `<section class="transition-trigger" data-rule-index="${index}"><div class="trigger-heading"><strong>规则 ${index}</strong>${tones.length>1?`<span class="transition-tag tone-${transitionTone(r)}">${transitionTones[transitionTone(r)]}</span>`:''}</div><dl class="rule-explanation"><dt>触发事件</dt><dd>${label!==r.event?esc(label):'收到自定义报告'}<code>${esc(r.event)}</code><small class="rule-reporter">${esc(lifecycleReporter(config,r))}</small></dd>${!commonCondition?`<dt>附加条件</dt><dd>${transitionConditionHTML(r)}</dd>`:''}${r.event==='completed'&&!(commonCondition&&commonCompletion)?'<dt>结果校验</dt><dd>全部输出契约和节点约束校验通过。</dd>':''}${!commonAction?`<dt>处理结果</dt><dd>${esc(actions[rowIndex])}${to==='agent'?fallbackLink:''}</dd>`:''}</dl>${!sameTarget?`<div class="rule-target-role"><small>转入后</small>${stateRoleHTML(targetRoles[rowIndex])}</div>`:''}${transitionActionsHTML(r)}<details class="rule-source"><summary>完整规则</summary><pre>${esc(pretty(r))}</pre></details></section>`;
      }).join('')}</div></article>`;
    }).join('')}</div></div>`).join('')}</div></div>`;
}
function filterLifecycleTargets(root,target){
  let count=0,groups=0;const tones=new Set();
  root.querySelectorAll('[data-lifecycle-group-to]').forEach(group=>{
    group.hidden=!!target&&group.dataset.lifecycleGroupTo!==target;
    if(!group.hidden){groups++;count+=Number(group.dataset.ruleCount);for(const tone of group.dataset.ruleTones.split(','))tones.add(tone);}
  });
  root.querySelectorAll('[data-lifecycle-tone]').forEach(badge=>badge.hidden=!tones.has(badge.dataset.lifecycleTone));
  root.querySelectorAll('[data-lifecycle-from]').forEach(phase=>{
    phase.hidden=![...phase.querySelectorAll('[data-lifecycle-group-to]')].some(group=>!group.hidden);
  });
  root.querySelector('[data-lifecycle-match-count]').textContent=`显示 ${count} / ${root.dataset.totalRules} 条规则 · ${groups} 组`;
  const lifecycle=root.closest('.lifecycle');
  if(lifecycle){
    lifecycle.querySelectorAll('[data-lifecycle-row-to]').forEach(row=>row.hidden=!!target&&row.dataset.lifecycleRowTo!==target);
    lifecycle.querySelectorAll('[data-lifecycle-extra-target]').forEach(el=>el.hidden=!!target&&el.dataset.lifecycleExtraTarget!==target);
    const summary=lifecycle.querySelector('[data-lifecycle-matrix-count]');
    if(summary)summary.textContent=target?`${count} / ${root.dataset.totalRules}`:root.dataset.totalRules;
  }
}
document.addEventListener('change',event=>{
  if(event.target.matches('[data-lifecycle-target-filter]'))filterLifecycleTargets(event.target.closest('[data-lifecycle-browser]'),event.target.value);
});
function lifecycleMatrix(config,state,expanded=false,context={}){
  const def=lifecycleOf(config);if(!def)return '<p class="muted">选择实现后查看执行规则。</p>';
  return `<section class="lifecycle"><h4>执行状态规则</h4><p class="small muted">执行者报告事件，平台检查条件并更新状态。</p>${lifecycleDiagram(config,state,context)}${def.transitions.some(r=>r.to==='retry')?`<div class="lifecycle-monitor" data-lifecycle-extra-target="retry"><strong>↻ 同一 Task 重试</strong><span>命中重试转移 → 等待同一任务的旧进程与执行身份释放 → ${esc(lifecycleName(def.initial))}（下一次执行）</span><small>Task ID 与下游引用不变；参数实际变化才增加修订号。</small></div>`:''}${def.transitions.some(r=>r.to==='agent')?'<p class="small muted" data-lifecycle-extra-target="agent">交给运行中已配置的兜底 Agent；未配置时保留问题等待用户处理。</p>':''}${config.kind==='timer'?'<p class="small muted">Engine 等待指定时刻，无需执行脚本；到时提交配置的输出。</p>':''}${def.transitions.some(r=>r.notify?.length)?'<p class="small">◇ 部分转移会发送通知或询问。</p>':''}${config.kind==='external'?'<div class="lifecycle-monitor"><strong>◉ 附属监控</strong><span>提交取得任务标识 → 按间隔检查 → 报告进展或结果</span><small>进入完成、失败、重试或交给 Agent 后停止本次监控。检查失败不代表外部工作失败；可明确转交 Agent，不自动重提。</small></div>':''}<details class="lifecycle-matrix" ${expanded?'open':''}><summary>执行状态转移矩阵 · <span data-lifecycle-matrix-count>${def.transitions.length}</span> 条规则</summary><p class="small muted">初始状态：${esc(lifecycleName(def.initial))}。仅按以下规则转移；未覆盖的事件保留为异常，按运行的兜底设置处理。</p><div class="matrix-scroll"><table><thead><tr><th>当前状态</th><th>报告事件</th><th>判断条件</th><th>下一状态</th><th>附加动作</th></tr></thead><tbody>${def.transitions.map((r,index)=>`<tr class="tone-${transitionTone(r)} ${r.from===state?'current':''}" data-lifecycle-row-to="${esc(r.to)}"><td><span class="transition-tag tone-${transitionTone(r)}">${transitionTones[transitionTone(r)]}</span><small>规则 ${index+1}</small>${esc(lifecycleName(r.from))}<code>${esc(r.from)}</code>${stateRoleHTML(stateExecutionRole(config,r.from,context))}</td><td>${esc(lifecycleEventName(config,r.event))}<code>${esc(r.event)}</code></td><td>${stateRoleHTML({kind:'machine',label:'状态机'})}${transitionConditionHTML(r)}${r.event==='completed'?'<small>全部输出和节点约束校验通过</small>':''}</td><td>${esc(lifecycleName(r.to))}<code>${esc(r.to)}</code>${stateRoleHTML(stateExecutionRole(config,r.to,context,r))}${r.to==='retry'?`<small>下一次执行从 ${esc(lifecycleName(def.initial))} 开始</small>`:''}</td><td>${r.parameters?`<strong>重试参数更新</strong><pre>${esc(pretty(r.parameters))}</pre>`:''}${r.notify?.length?`<strong>通知 / 询问</strong><pre>${esc(pretty(r.notify))}</pre>`:''}${!r.parameters&&!r.notify?.length?'—':''}</td></tr>`).join('')}</tbody></table></div></details></section>`;
}
// Summaries and common controls are projections of the existing transition rows.
function executionResponsibilities(c){
  const work={loop:['创建关联的子 Run，等待其完成并校验写回映射结果。','提供目标 Loop、输入和结果映射；父子 Run 各自暂停和终止。'],command:['启动脚本，校验并保存提交的结果。','提供业务脚本，并调用报告工具提交结果；退出码 0 不等于任务完成。'],external:['提交后按约定间隔调用监控；执行结束后停止监控。','提供提交和检查脚本；检查外部工作，再报告进展、失败或完整结果。'],agent:['唤醒 Agent，校验并保存它提交的结果。','提供业务 prompt / Skill；Agent 使用工具提交结果，退出前释放操作权。'],timer:['持久保存到期时间，到时提交配置的输出；无需常驻脚本。','设置等待时长或时刻；节点有输出时，填写到时提交的内容。'],event:['等待名称和关联标识匹配的事件，校验回复并写入结果。','设置事件和输出要求，由用户、脚本或 Agent 提交事件；业务观测仍由作者提供。'],approval:['保留审批等待，收到审批操作后推进。','说明需要谁审批、判断什么。审批等待与通知发送分别配置。']}[c.kind];
  if(!work)return '';
  return `<div class="execution-responsibilities"><div><strong>平台已负责</strong><p>${esc(work[0])}</p><small>记录执行和状态变化；已有下游任务仍需满足各自的输入与推进条件。</small></div><div><strong>作者需要提供</strong><p>${esc(work[1])}</p><small>通知、重试与转交 Agent 是否生效，以本实现和运行的实际配置为准。</small></div></div>`;
}
function transitionOutcome(r){
  if(r.event==='check_error'&&r.to===r.from)return '停止检查，等待恢复监控';
  return ({completed:'完成并提交结果',fault:'记为失败，保留问题',retry:'重试当前任务',agent:'转交兜底 Agent'})[r.to]||(r.to===r.from?'保持当前阶段':lifecycleName(r.to));
}
function executionRulesSummary(c){
  const def=lifecycleOf(c);if(!def)return '<p class="small muted">选择实现后查看执行行为。</p>';
  const rows=def.transitions.map((r,index)=>({r,index})).filter(({r})=>r.event!=='progress'||r.to!==r.from||hasTransitionCondition(r)||r.notify?.length);
  return `<div class="execution-rules-summary"><p class="small muted">开始于「${esc(lifecycleName(def.initial))}」。以下行为来自当前实现的转移规则；通知仅在对应转移被接受时发送。</p>${rows.map(({r,index})=>{return `<div class="behavior-row"><div><strong>${esc(lifecycleEventName(c,r.event))}</strong><small>${esc(lifecycleName(r.from))}${hasTransitionCondition(r)?' · 满足自定义条件时':''}</small></div><div><strong>${esc(transitionOutcome(r))}</strong>${r.parameters?'<small>重试前按规则修改参数；保留当前任务与下游引用</small>':''}${r.to==='retry'&&!hasTransitionCondition(r)?'<small class="behavior-caution">未设置重试次数条件；每次命中都会重试</small>':''}${r.to==='agent'?'<small>仅在运行启用兜底后自动唤醒，否则等待用户处理</small>':''}${r.notify?.length?`<small>◇ ${r.notify.map(n=>esc(n.message)).join('；')}</small>`:'<small>未配置此时通知</small>'}</div></div>`;}).join('')}<p class="small muted">${def.transitions.some(r=>r.to==='retry')?'重试沿用同一个 Task，下游引用不变。':'当前没有自动重试规则。'} 未覆盖的状态或事件保留为异常，按运行的兜底设置处理。</p></div>`;
}
function executionLifecycle(attempt){
  if(!attempt)return '';
  const history=run.history.filter(h=>h.execution===attempt.id&&['transition','observation','monitor_retry','process_error','recovery','retry_applied','retry_blocked','stale_monitor_report','monitor_skipped','command_start','agent_command'].includes(h.kind));
  return `<section class="execution-lifecycle">${attempt.implementation?.lifecycle?lifecycleMatrix(attempt.implementation,attempt.lifecycle_state):'<p class="small muted">此历史执行未保存生命周期规则。</p>'}${attempt.retry?`<div class="lifecycle-monitor"><strong>${esc(({pending:'等待重试：进程退出或操作权尚未就绪',applied:'重试已应用到原 Task',blocked:'自动重试已阻止',superseded:'此次重试已被后续操作替代'})[attempt.retry.status]||attempt.retry.status)}</strong>${attempt.retry.error?`<span>${esc(attempt.retry.error)}</span>`:''}<details><summary>已确定的重试参数</summary><pre>${esc(pretty(attempt.retry.parameters))}</pre></details></div>`:''}${attempt.implementation.kind==='external'&&['completed','fault','retry','agent'].includes(attempt.lifecycle_state)?'<p class="small">本次监控已停止；在途返回仅作为滞后记录保留。</p>':''}${attempt.observation_error?`<p class="task-error"><strong>监控需要恢复</strong><br>${esc(attempt.observation_error)}<br>外部工作状态尚未确认。</p>`:''}${attempt.child_run_id?`<p class="small">调用的 Loop：<a href="#run/${encodeURIComponent(attempt.child_run_id)}">${esc(attempt.child_run_id)}</a> · ${esc(labels[attempt.child_status]||attempt.child_status||'等待中')}</p><p class="small muted">这是最近观察到的子 Run 状态。暂停父 Run 或取消此处等待不会终止子 Run；需要停止子工作时，打开上方子 Run 单独操作。</p>`:''}${attempt.external_id&&!attempt.child_run_id?`<p class="small">外部任务：<code>${esc(attempt.external_id)}</code>${attempt.status==='waiting'&&!attempt.observation_error?` · 下次检查 ${esc(taskTime(attempt.wake_at))}`:''}</p>`:''}<details class="transition-history" ${attempt.observation_error||attempt.status==='fault'?'open':''}><summary>状态变化与检查记录 · ${history.length}</summary>${history.length?`<ol>${history.map(h=>{const d=h.detail||{};return `<li class="${d.accepted===false||h.kind==='process_error'?'issue':''}"><time>${esc(taskTime(h.at))}</time><strong>${h.kind==='transition'?esc((d.from?lifecycleName(d.from)+' → ':'')+lifecycleName(d.to)):esc(h.kind==='observation'?'开始检查':h.kind==='monitor_retry'?'恢复监控':h.kind==='recovery'?'平台恢复执行':h.kind==='retry_applied'?'同一 Task 已安排重试':h.kind==='retry_blocked'?'自动重试已阻止':h.kind==='stale_monitor_report'?'滞后监控报告 · 已忽略':h.kind==='monitor_skipped'?'已取消过期监控调用':h.kind==='command_start'?'命令启动配置错误':h.kind==='agent_command'?'Agent 命令异常':'进程异常')}</strong><span>${esc(lifecycleEvents[d.event]||h.message)}${d.source?' · '+esc(lifecycleSources[d.source]||d.source):''}${d.accepted===false?' · 转移未接受，等待处理':''}${d.attempt?' · 第 '+esc(d.attempt)+' 次执行':''}</span>${d.rule?`<details><summary>实际命中的转移</summary><pre>${esc(pretty(d.rule))}</pre></details>`:''}${d.detail&&Object.keys(d.detail).length?`<details><summary>报告详情</summary><pre>${esc(pretty(d.detail))}</pre></details>`:''}${h.kind==='stale_monitor_report'?'<small>仅记录证据，未改变任务、结果或失败次数。</small>':''}${d.result_preserved?'<small>已提交的结果保留</small>':''}</li>`;}).join('')}</ol>`:'<p class="muted">历史执行未记录生命周期事件。</p>'}</details></section>`;
}
