 'use strict';
let lifecycleTemplates={};
const lifecycleNames={executing:'执行中',submitting:'提交中',waiting:'等待外部工作',approval:'等待审批',completed:'完成',fault:'失败'};
const lifecycleEvents={progress:'报告进度',submitted:'提交成功',completed:'提交完整结果',failed:'报告业务失败',process_error:'执行进程异常',check_error:'监控检查失败'};
const lifecycleSources={engine:'平台检测',script:'同步脚本 / 提交脚本',monitor:'附属监控',agent:'Agent',event:'外部事件',submission:'结果提交'};
function lifecycleOf(config){return config?.lifecycle || lifecycleTemplates[config?.kind];}
function lifecycleName(value){return lifecycleNames[value]||value;}
function lifecycleStrip(config,state){
  const def=lifecycleOf(config);if(!def)return '';
  const targets=[...new Set(def.transitions.map(r=>r.to))],states=[def.initial,...targets.filter(s=>s!==def.initial&&!['completed','fault'].includes(s)),...targets.filter(s=>['completed','fault'].includes(s))];
  return `<div class="lifecycle-strip" aria-label="执行阶段">${states.map(s=>`<span class="${s===state?'current':''} ${s==='fault'?'failure':''}">${esc(lifecycleName(s))}</span>`).join('<i>·</i>')}</div>`;
}
function lifecycleMatrix(config,state){
  const def=lifecycleOf(config);if(!def)return '<p class="muted">选择实现后查看执行规则。</p>';
  return `<section class="lifecycle"><h4>${config.kind==='external'?'异步执行 · 附属监控':'任务生命周期'}</h4>${lifecycleStrip(config,state)}${config.kind==='external'?'<div class="lifecycle-monitor"><strong>◉ 附属监控</strong><span>提交取得任务标识 → 按间隔检查 → 报告进展或结果</span><small>随本任务运行；检查失败保留外部状态，不重复提交工作。</small></div>':''}<details class="lifecycle-matrix"><summary>状态转移矩阵 · ${def.transitions.length} 条规则</summary><p class="small muted">初始状态：${esc(lifecycleName(def.initial))}。仅按以下规则转移；未覆盖的事件保留为异常，按运行的兜底设置处理。</p><div class="matrix-scroll"><table><thead><tr><th>当前状态</th><th>事件 / 条件</th><th>下一状态</th></tr></thead><tbody>${def.transitions.map(r=>`<tr class="${r.from===state?'current':''}"><td>${esc(lifecycleName(r.from))}</td><td>${esc(lifecycleEvents[r.event]||r.event)}${r.when?`<pre>${esc(pretty(r.when))}</pre>`:''}${r.event==='completed'?'<small>全部输出和节点约束校验通过</small>':''}</td><td>${esc(lifecycleName(r.to))}</td></tr>`).join('')}</tbody></table></div></details></section>`;
}
function transitionRow(r={from:'',event:'',to:''}){return `<div class="transition-row"><label>当前状态<input data-transition-from value="${esc(r.from)}"></label><label>事件<input data-transition-event value="${esc(r.event)}"></label><label>下一状态<input data-transition-to value="${esc(r.to)}"></label><button type="button" data-transition-remove aria-label="删除转移">×</button><details><summary>可选条件</summary><textarea data-transition-when rows="3" placeholder="确定性表达式 JSON；可留空">${r.when?esc(pretty(r.when)):''}</textarea></details></div>`;}
function lifecycleEditor(c){const d=lifecycleOf(c);return `<div data-lifecycle-editor>${lifecycleMatrix(c)}<details class="lifecycle-edit"><summary>编辑转移规则</summary><p class="small muted">这里的规则直接用于执行。可增加业务状态；状态和事件 ID 使用字母、数字、下划线或连字符。</p><label>初始状态<input data-lifecycle-initial value="${esc(d?.initial||'')}"></label><div data-transition-rows>${(d?.transitions||[]).map(transitionRow).join('')}</div><button type="button" data-transition-add>＋ 转移规则</button><button type="button" data-lifecycle-reset>重新填入此执行方式的初始模板</button></details></div>`;}
function readLifecycle(row){return {initial:row.querySelector('[data-lifecycle-initial]').value.trim(),transitions:[...row.querySelectorAll('.transition-row')].map(el=>{const r=Object.fromEntries(['from','event','to'].map(k=>[k,el.querySelector('[data-transition-'+k+']').value.trim()])),when=el.querySelector('[data-transition-when]').value.trim();if(when)r.when=JSON.parse(when);return r;})};}
function executionLifecycle(attempt){
  if(!attempt)return '';
  const history=run.history.filter(h=>h.execution===attempt.id&&['transition','observation','monitor_retry','process_error','recovery'].includes(h.kind));
  return `<section class="execution-lifecycle">${attempt.implementation?.lifecycle?lifecycleMatrix(attempt.implementation,attempt.lifecycle_state):'<p class="small muted">此历史执行未保存生命周期规则。</p>'}${attempt.observation_error?`<p class="task-error"><strong>监控需要恢复</strong><br>${esc(attempt.observation_error)}<br>外部工作状态尚未确认。</p>`:''}${attempt.external_id?`<p class="small">外部任务：<code>${esc(attempt.external_id)}</code>${attempt.status==='waiting'&&!attempt.observation_error?` · 下次检查 ${esc(taskTime(attempt.wake_at))}`:''}</p>`:''}<details class="transition-history" ${attempt.observation_error||attempt.status==='fault'?'open':''}><summary>状态变化与检查记录 · ${history.length}</summary>${history.length?`<ol>${history.map(h=>{const d=h.detail||{};return `<li class="${d.accepted===false||h.kind==='process_error'?'issue':''}"><time>${esc(taskTime(h.at))}</time><strong>${h.kind==='transition'?esc((d.from?lifecycleName(d.from)+' → ':'')+lifecycleName(d.to)):esc(h.kind==='observation'?'开始检查':h.kind==='monitor_retry'?'恢复监控':h.kind==='recovery'?'平台恢复执行':'进程异常')}</strong><span>${esc(lifecycleEvents[d.event]||h.message)}${d.source?' · '+esc(lifecycleSources[d.source]||d.source):''}${d.accepted===false?' · 未覆盖，等待处理':''}</span>${d.detail&&Object.keys(d.detail).length?`<details><summary>报告详情</summary><pre>${esc(pretty(d.detail))}</pre></details>`:''}${d.result_preserved?'<small>已提交的结果保留</small>':''}</li>`;}).join('')}</ol>`:'<p class="muted">历史执行未记录生命周期事件。</p>'}</details></section>`;
}
document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;const row=button.closest('.author-candidate');if(!row)return;
  if(button.hasAttribute('data-transition-remove'))button.closest('.transition-row').remove();
  else if(button.hasAttribute('data-transition-add'))row.querySelector('[data-transition-rows]').insertAdjacentHTML('beforeend',transitionRow());
  else if(button.hasAttribute('data-lifecycle-reset')){const kind=row.querySelector('[data-candidate-kind]').value;row.querySelector('[data-lifecycle-editor]').outerHTML=lifecycleEditor({kind});}
  else return;dirty();
});

document.addEventListener('input',event=>{const root=event.target.closest('[data-lifecycle-editor]');if(!root)return;try{const row=root.closest('.author-candidate'),config={kind:row.querySelector('[data-candidate-kind]').value,lifecycle:readLifecycle(row)};root.querySelector(':scope > .lifecycle').outerHTML=lifecycleMatrix(config);}catch(error){/* An incomplete condition remains an editable draft. */}});
