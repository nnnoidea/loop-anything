 'use strict';
let lifecycleTemplates={};
const lifecycleNames={executing:'执行中',submitting:'提交中',waiting:'等待中',approval:'等待审批',completed:'完成',fault:'失败',retry:'重试原任务',agent:'交给 Agent'};
const lifecycleEvents={progress:'报告进度',submitted:'提交成功',completed:'提交完整结果',failed:'报告业务失败',process_error:'执行进程异常',check_error:'监控检查失败',timeout:'等待超时'};
const lifecycleSources={engine:'平台检测',script:'同步脚本 / 提交脚本',monitor:'附属监控',agent:'Agent',event:'外部事件',submission:'结果提交'};
function lifecycleOf(config){return config?.lifecycle || lifecycleTemplates[config?.kind];}
function lifecycleName(value){return lifecycleNames[value]||value;}
function lifecycleEventName(config,event){return event==='completed'&&config?.kind==='timer'?'计时到达':event==='completed'&&config?.kind==='event'?'收到匹配事件':lifecycleEvents[event]||event;}
function lifecycleDiagram(config,state){
  const def=lifecycleOf(config);if(!def)return '';
  const groups=new Map(),events=rows=>[...new Set(rows.map(r=>lifecycleEventName(config,r.event)))].join(' / ')+(rows.some(r=>r.when)?' · 按条件':'');
  for(const r of def.transitions){if(!groups.has(r.from))groups.set(r.from,new Map());const targets=groups.get(r.from);if(!targets.has(r.to))targets.set(r.to,[]);targets.get(r.to).push(r);}
  return `<div class="lifecycle-diagram" aria-label="一次执行的状态转移">${[...groups].map(([from,all])=>{
    const targets=[...all].filter(([to])=>to!==from),self=all.get(from);
    return `<div class="phase-group ${targets.length?'':'self-only'}" data-lifecycle-from="${esc(from)}"><div class="phase-source ${from===state?'current':''}"><strong>${esc(lifecycleName(from))}</strong>${from===def.initial?'<small>初始状态</small>':''}${from===state?'<small>当前阶段</small>':''}${self?`<small data-lifecycle-to="${esc(from)}">↺ ${esc(events(self))}${self.some(r=>r.notify?.length)?' · ◇ 通知':''}</small>`:''}</div>${targets.length?`<div class="phase-targets">${targets.map(([to,rows])=>`<div data-lifecycle-to="${esc(to)}" class="phase-target ${to===state?'current':''} ${to==='fault'?'failure':''}"><strong>${esc(lifecycleName(to))}</strong><small>${esc(events(rows))}</small>${rows.some(r=>r.notify?.length)?'<small>◇ 同时发送通知 / 询问</small>':''}${to==='retry'?'<small>同一任务的下一次执行</small>':''}${to==='completed'?'<small>结果可供下游使用</small>':''}</div>`).join('')}</div>`:''}</div>`;
  }).join('')}</div>`;
}
function lifecycleMatrix(config,state){
  const def=lifecycleOf(config);if(!def)return '<p class="muted">选择实现后查看执行规则。</p>';
  return `<section class="lifecycle"><h4>执行生命周期</h4><p class="small muted">描述这个实现的一次执行。完成后提交结果，已有下游任务再检查推进条件。</p>${lifecycleDiagram(config,state)}${def.transitions.some(r=>r.to==='retry')?`<div class="lifecycle-monitor"><strong>↻ 同一 Task 重试</strong><span>命中重试转移 → 等待进程结束与操作权 → ${esc(lifecycleName(def.initial))}（下一次执行）</span><small>Task ID 与下游引用不变；参数实际变化才增加修订号。</small></div>`:''}${def.transitions.some(r=>r.to==='agent')?'<p class="small muted">交给运行中已配置的兜底 Agent；未配置时保留问题等待用户处理。</p>':''}${config.kind==='timer'?'<p class="small muted">Engine 等待指定时刻，无需执行脚本；到时提交配置的输出。</p>':''}${def.transitions.some(r=>r.notify?.length)?'<p class="small">◇ 部分转移会发送通知或询问。</p>':''}${config.kind==='external'?'<div class="lifecycle-monitor"><strong>◉ 附属监控</strong><span>提交取得任务标识 → 按间隔检查 → 报告进展或结果</span><small>进入完成、失败、重试或交给 Agent 后停止本次监控。检查失败不代表外部工作失败；可明确转交 Agent，不自动重提。</small></div>':''}<details class="lifecycle-matrix"><summary>执行内转移矩阵 · ${def.transitions.length} 条规则</summary><p class="small muted">初始状态：${esc(lifecycleName(def.initial))}。仅按以下规则转移；未覆盖的事件保留为异常，按运行的兜底设置处理。</p><div class="matrix-scroll"><table><thead><tr><th>当前状态</th><th>事件 / 条件</th><th>下一状态</th></tr></thead><tbody>${def.transitions.map(r=>`<tr class="${r.from===state?'current':''}"><td>${esc(lifecycleName(r.from))}</td><td>${esc(lifecycleEventName(config,r.event))}${r.when?`<pre>${esc(pretty(r.when))}</pre>`:''}${r.event==='completed'?'<small>全部输出和节点约束校验通过</small>':''}</td><td>${esc(lifecycleName(r.to))}${r.to==='retry'?`<small>↻ ${esc(lifecycleName(def.initial))} · 新执行尝试</small>`:''}${r.notify?.length?`<small>◇ 通知：${r.notify.map(n=>esc(n.message)).join('；')}</small>`:''}${r.parameters?`<small>重试前修改参数（其余保留）</small><pre>${esc(pretty(r.parameters))}</pre>`:''}</td></tr>`).join('')}</tbody></table></div></details></section>`;
}
// Summaries and common controls are projections of the existing transition rows.
function executionResponsibilities(c){
  const work={command:['启动脚本，校验并保存提交的结果。','提供业务脚本，并调用报告工具提交结果；退出码 0 不等于任务完成。'],external:['提交后按约定间隔调用监控；执行结束后停止监控。','提供提交和检查脚本；检查外部工作，再报告进展、失败或完整结果。'],agent:['唤醒 Agent，校验并保存它提交的结果。','提供业务 prompt / Skill；Agent 使用工具提交结果，退出前释放操作权。'],timer:['持久保存到期时间，到时提交配置的输出；无需常驻脚本。','设置等待时长或时刻；节点有输出时，填写到时提交的内容。'],event:['等待名称和关联标识匹配的事件，校验回复并写入结果。','设置事件和输出要求，由用户、脚本或 Agent 提交事件；业务观测仍由作者提供。'],approval:['保留审批等待，收到审批操作后推进。','说明需要谁审批、判断什么。审批等待与通知发送分别配置。']}[c.kind];
  if(!work)return '';
  return `<div class="execution-responsibilities"><div><strong>平台已负责</strong><p>${esc(work[0])}</p><small>记录执行和状态变化；已有下游任务仍需满足各自的输入与推进条件。</small></div><div><strong>作者需要提供</strong><p>${esc(work[1])}</p><small>通知、重试与转交 Agent 是否生效，以本实现和运行的实际配置为准。</small></div></div>`;
}
function transitionChoices(r){
  // Conditional or parameter-changing rules stay explicit; never flatten them to a preset.
  if(r.when||r.parameters)return [];
  const choices=r.event==='check_error'?[r.from,'agent']:['failed','process_error','timeout'].includes(r.event)?['fault','retry','agent']:[];
  return choices.includes(r.to)?choices:[];
}
function transitionOutcome(r){
  if(r.event==='check_error'&&r.to===r.from)return '停止检查，等待恢复监控';
  return ({completed:'完成并提交结果',fault:'记为失败，保留问题',retry:'重试当前任务',agent:'转交兜底 Agent'})[r.to]||(r.to===r.from?'保持当前阶段':lifecycleName(r.to));
}
function executionRulesSummary(c,editable=false){
  const def=lifecycleOf(c);if(!def)return '<p class="small muted">选择实现后查看执行行为。</p>';
  const rows=def.transitions.map((r,index)=>({r,index})).filter(({r})=>r.event!=='progress'||r.to!==r.from||r.when||r.notify?.length);
  return `<div class="execution-rules-summary"><p class="small muted">开始于「${esc(lifecycleName(def.initial))}」。以下行为来自当前实现的转移规则；通知仅在对应转移被接受时发送。</p>${rows.map(({r,index})=>{const choices=editable?transitionChoices(r):[];return `<div class="behavior-row"><div><strong>${esc(lifecycleEventName(c,r.event))}</strong><small>${esc(lifecycleName(r.from))}${r.when?' · 满足自定义条件时':''}</small></div><div>${choices.length?`<select data-behavior-target="${index}" aria-label="${esc(lifecycleName(r.from)+' · '+lifecycleEventName(c,r.event)+'的处理方式')}">${choices.map(to=>`<option value="${esc(to)}" ${r.to===to?'selected':''}>${esc(transitionOutcome({...r,to}))}</option>`).join('')}</select>`:`<strong>${esc(transitionOutcome(r))}</strong>`}${r.parameters?'<small>重试前按规则修改参数；保留当前任务与下游引用</small>':''}${r.to==='retry'&&!r.when?'<small class="behavior-caution">未设置重试次数条件；每次命中都会重试</small>':''}${r.to==='agent'?'<small>仅在运行启用兜底后自动唤醒，否则等待用户处理</small>':''}${r.notify?.length?`<small>◇ ${r.notify.map(n=>esc(n.message)).join('；')}</small>`:'<small>未配置此时通知</small>'}</div>${editable?`<button type="button" data-behavior-rule="${index}">${r.when||r.parameters?'查看条件与通知':'设置通知 / 详情'}</button>`:''}</div>`;}).join('')}<p class="small muted">${def.transitions.some(r=>r.to==='retry')?'重试沿用同一个 Task，下游引用不变。':'当前没有自动重试规则。'} 未覆盖的状态或事件保留为异常，按运行的兜底设置处理。</p></div>`;
}
function transitionTitle(r){return `${esc(lifecycleName(r.from)||'新规则')} → ${esc(lifecycleName(r.to)||'目标状态')}<small>${esc(lifecycleEvents[r.event]||r.event||'待填写事件')}${r.when?' · 按条件':''}</small>`;}
function transitionRow(r={from:'',event:'',to:''}){return `<details class="transition-row" ${!r.from||!r.event?'open':''}><summary>${transitionTitle(r)}</summary><div class="transition-fields"><details class="transition-identifiers" ${!r.from||!r.event?'open':''}><summary>状态与事件标识（高级）</summary><label>当前状态<input data-transition-from value="${esc(r.from)}"></label><label>事件<input data-transition-event value="${esc(r.event)}"></label><label>下一状态<input data-transition-to value="${esc(r.to)}"></label><button type="button" data-transition-remove>删除这条规则</button></details><details><summary>可选条件</summary><textarea data-transition-when rows="3" placeholder="确定性表达式 JSON；可留空">${r.when?esc(pretty(r.when)):''}</textarea></details><details><summary>重试时改参（可选）</summary><textarea data-transition-parameters rows="3" placeholder="仅 retry：参数对象，列出的顶层字段替换，其余保留">${r.parameters?esc(pretty(r.parameters)):''}</textarea></details><details class="transition-notifications" ${r.notify?.length?'open':''}><summary>发生此次转移时通知${r.notify?.length?' · '+r.notify.length:''}</summary><p class="small muted">内容可用 {outputs.name}、{parameters.name} 等已有引用。</p><div data-transition-notices>${(r.notify||[]).map(n=>`<div class="transition-notice">${noticeFields(n,true)}<button type="button" data-remove-transition-notice>移除通知</button></div>`).join('')}</div><button type="button" data-add-transition-notice>＋ 通知 / 询问</button></details></div></details>`;}
function lifecycleEditor(c){const d=lifecycleOf(c);return `<div data-lifecycle-editor><h3>平台如何处理这一步</h3>${executionResponsibilities(c)}<h4>完成、失败与通知</h4><div data-behavior-summary>${executionRulesSummary(c,true)}</div><details class="lifecycle-visual"><summary>查看完整执行过程 · 状态图与矩阵</summary>${lifecycleMatrix(c)}</details><details class="lifecycle-edit"><summary>高级：自定义状态与转移条件</summary><p class="small muted">与上方共用同一份规则。普通执行不需要重新设计；仅特殊业务状态、有限重试或按条件改参时修改。retry 重试原任务，agent 转交已配置的兜底。条件可读 attempt（第几次执行，从 1 开始）；同一事件的条件必须恰好命中一行。</p><label>初始状态<input data-lifecycle-initial value="${esc(d?.initial||'')}"></label><div data-transition-rows>${(d?.transitions||[]).map(transitionRow).join('')}</div><button type="button" data-transition-add>＋ 转移规则</button><button type="button" data-lifecycle-reset>重新填入此执行方式的初始模板</button></details></div>`;}

function readLifecycle(row){return {initial:row.querySelector('[data-lifecycle-initial]').value.trim(),transitions:[...row.querySelectorAll('.transition-row')].map(el=>{const r=Object.fromEntries(['from','event','to'].map(k=>[k,el.querySelector('[data-transition-'+k+']').value.trim()])),when=el.querySelector('[data-transition-when]').value.trim();if(when)r.when=JSON.parse(when);const parameters=el.querySelector('[data-transition-parameters]').value.trim();if(parameters)r.parameters=JSON.parse(parameters);const notices=[...el.querySelectorAll('.transition-notice')].map(readNotice);if(notices.length)r.notify=notices;return r;})};}
function executionLifecycle(attempt){
  if(!attempt)return '';
  const history=run.history.filter(h=>h.execution===attempt.id&&['transition','observation','monitor_retry','process_error','recovery','retry_applied','retry_blocked','stale_monitor_report','monitor_skipped','command_start','agent_command'].includes(h.kind));
  return `<section class="execution-lifecycle">${attempt.implementation?.lifecycle?lifecycleMatrix(attempt.implementation,attempt.lifecycle_state):'<p class="small muted">此历史执行未保存生命周期规则。</p>'}${attempt.retry?`<div class="lifecycle-monitor"><strong>${esc(({pending:'等待重试：进程退出或操作权尚未就绪',applied:'重试已应用到原 Task',blocked:'自动重试已阻止',superseded:'此次重试已被后续操作替代'})[attempt.retry.status]||attempt.retry.status)}</strong>${attempt.retry.error?`<span>${esc(attempt.retry.error)}</span>`:''}<details><summary>已确定的重试参数</summary><pre>${esc(pretty(attempt.retry.parameters))}</pre></details></div>`:''}${attempt.implementation.kind==='external'&&['completed','fault','retry','agent'].includes(attempt.lifecycle_state)?'<p class="small">本次监控已停止；在途返回仅作为滞后记录保留。</p>':''}${attempt.observation_error?`<p class="task-error"><strong>监控需要恢复</strong><br>${esc(attempt.observation_error)}<br>外部工作状态尚未确认。</p>`:''}${attempt.external_id?`<p class="small">外部任务：<code>${esc(attempt.external_id)}</code>${attempt.status==='waiting'&&!attempt.observation_error?` · 下次检查 ${esc(taskTime(attempt.wake_at))}`:''}</p>`:''}<details class="transition-history" ${attempt.observation_error||attempt.status==='fault'?'open':''}><summary>状态变化与检查记录 · ${history.length}</summary>${history.length?`<ol>${history.map(h=>{const d=h.detail||{};return `<li class="${d.accepted===false||h.kind==='process_error'?'issue':''}"><time>${esc(taskTime(h.at))}</time><strong>${h.kind==='transition'?esc((d.from?lifecycleName(d.from)+' → ':'')+lifecycleName(d.to)):esc(h.kind==='observation'?'开始检查':h.kind==='monitor_retry'?'恢复监控':h.kind==='recovery'?'平台恢复执行':h.kind==='retry_applied'?'同一 Task 已安排重试':h.kind==='retry_blocked'?'自动重试已阻止':h.kind==='stale_monitor_report'?'滞后监控报告 · 已忽略':h.kind==='monitor_skipped'?'已取消过期监控调用':h.kind==='command_start'?'命令启动配置错误':h.kind==='agent_command'?'Agent 命令异常':'进程异常')}</strong><span>${esc(lifecycleEvents[d.event]||h.message)}${d.source?' · '+esc(lifecycleSources[d.source]||d.source):''}${d.accepted===false?' · 转移未接受，等待处理':''}${d.attempt?' · 第 '+esc(d.attempt)+' 次执行':''}</span>${d.rule?`<details><summary>实际命中的转移</summary><pre>${esc(pretty(d.rule))}</pre></details>`:''}${d.detail&&Object.keys(d.detail).length?`<details><summary>报告详情</summary><pre>${esc(pretty(d.detail))}</pre></details>`:''}${h.kind==='stale_monitor_report'?'<small>仅记录证据，未改变任务、结果或失败次数。</small>':''}${d.result_preserved?'<small>已提交的结果保留</small>':''}</li>`;}).join('')}</ol>`:'<p class="muted">历史执行未记录生命周期事件。</p>'}</details></section>`;
}
document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;const row=button.closest('.author-candidate');if(!row)return;
  if(button.hasAttribute('data-transition-remove'))button.closest('.transition-row').remove();
  else if(button.hasAttribute('data-transition-add'))row.querySelector('[data-transition-rows]').insertAdjacentHTML('beforeend',transitionRow());
  else if(button.hasAttribute('data-lifecycle-reset')){const kind=row.querySelector('[data-candidate-kind]').value;row.querySelector('[data-lifecycle-editor]').outerHTML=lifecycleEditor({kind});}
  else return;refreshLifecycle(row);dirty();
});

function refreshLifecycle(row){try{
  const config={kind:row.querySelector('[data-candidate-kind]').value,lifecycle:readLifecycle(row)};
  row.querySelectorAll('.transition-row').forEach((el,i)=>el.querySelector(':scope > summary').innerHTML=transitionTitle(config.lifecycle.transitions[i]));
  row.querySelector('[data-lifecycle-editor] .lifecycle').outerHTML=lifecycleMatrix(config);
  row.querySelector('[data-behavior-summary]').innerHTML=executionRulesSummary(config,true);
  row.querySelectorAll('.phase-source,[data-lifecycle-to]').forEach(el=>{el.setAttribute('role','button');el.tabIndex=0;el.setAttribute('aria-label','编辑此状态的转移规则');});
}catch(error){/* Keep incomplete JSON editable. */}}
document.addEventListener('input',event=>{const root=event.target.closest('[data-lifecycle-editor]');if(root&&!event.target.matches('[data-behavior-target]'))refreshLifecycle(root.closest('.author-candidate'));});

function editDiagramTransition(target){
  const point=target.closest('[data-lifecycle-to],.phase-source'),candidate=point?.closest('.author-candidate');if(!candidate)return false;
  const group=point.closest('[data-lifecycle-from]'),from=group.dataset.lifecycleFrom,to=point.dataset.lifecycleTo;
  const rows=[...candidate.querySelectorAll('.transition-row')].filter(el=>el.querySelector('[data-transition-from]').value===from&&(to===undefined||el.querySelector('[data-transition-to]').value===to));
  candidate.querySelector('.lifecycle-edit').open=true;
  candidate.querySelectorAll('.transition-row').forEach(el=>el.classList.toggle('selected-transition',rows.includes(el)));
  rows.forEach(el=>{el.open=true;el.querySelector('.transition-identifiers').open=true;});
  if(rows.length){rows[0].scrollIntoView({block:'center'});rows[0].querySelector('[data-transition-event]').focus();}return true;
}
document.addEventListener('click',event=>editDiagramTransition(event.target));
document.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)&&editDiagramTransition(event.target))event.preventDefault();});

document.addEventListener('click',event=>{const el=event.target.closest('[data-add-transition-notice],[data-remove-transition-notice]');if(!el)return;const row=el.closest('.author-candidate');if(el.hasAttribute('data-add-transition-notice'))el.previousElementSibling.insertAdjacentHTML('beforeend',`<div class="transition-notice">${noticeFields({message:''},true)}<button type="button" data-remove-transition-notice>移除通知</button></div>`);else el.closest('.transition-notice').remove();refreshLifecycle(row);dirty();});

document.addEventListener('change',event=>{
  const select=event.target.closest('[data-behavior-target]');if(!select)return;
  const candidate=select.closest('.author-candidate'),row=candidate.querySelectorAll('.transition-row')[Number(select.dataset.behaviorTarget)];
  row.querySelector('[data-transition-to]').value=select.value;refreshLifecycle(candidate);dirty();
});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-behavior-rule]');if(!button)return;
  const candidate=button.closest('.author-candidate'),row=candidate.querySelectorAll('.transition-row')[Number(button.dataset.behaviorRule)];
  candidate.querySelector('.lifecycle-edit').open=true;row.open=true;
  candidate.querySelectorAll('.transition-row').forEach(el=>el.classList.toggle('selected-transition',el===row));
  row.querySelector('.transition-notifications').open=true;
  row.scrollIntoView({block:'center'});row.querySelector('[data-add-transition-notice]').focus({preventScroll:true});
});
