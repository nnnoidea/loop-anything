'use strict';
// Record-driven workspace. No domain-specific approval or event handling.
Object.assign(labels,{waiting_user:'等待用户',planned:'已规划',held:'暂停待放行',stale:'已失效',delivered:'已送达',sending:'发送中',pending:'待发送'});
for(const [id,label] of [['records','结果记录'],['task-history','运行过程'],['hooks','通知与控制'],['tasks','任务与问题']]){
  const button=document.createElement('button');button.dataset.tab=id;button.textContent=label;button.className='v2-tab';button.hidden=true;
  document.querySelector('.tabs').append(button);
}
function renderTimelineSettings(){
  document.querySelectorAll('.v2-tab').forEach(b=>b.hidden=false);
  for(const owner of run.agent_sessions || [])$('attention').innerHTML+=`<div class="notice">${owner.kind==='interactive'?'你的 Agent':'后台 Agent'} · ${owner.scope_task?esc(run.loop_definition.nodes[run.tasks[owner.scope_task]?.spec.node]?.label || owner.scope_task)+'（'+esc(owner.scope_task)+'）支线':'全局'}正在处理工作${owner.recovery_required?' · 旧进程状态需人工核实':''}。</div>`;
  const held=Object.values(run.tasks).filter(w=>w.status==='held');
  if(held.length)$('attention').innerHTML+=`<div class="notice">${held.length} 项工作已被执行前暂停拦截。到「通知与控制」查看并放行。</div>`;
  if(run.diagnostics.length)$('attention').innerHTML+=`<div class="notice">${run.diagnostics.length} 项依赖诊断：${run.diagnostics.map(d=>esc(d.kind)).join('、')}。到任务与问题查看缺少什么。</div>`;
  $('attention').innerHTML+=runIdleHint(run);
}
function runIdleHint(value){
  const tasks=Object.values(value.tasks||{});
  if(value.status!=='running'||value.identity_read_only||!tasks.length||value.settings.completion_rule!=null||value.settings.termination_signal||(value.agent_sessions||[]).length||(value.diagnostics||[]).length||(value.agent_tasks?.items||[]).length||!tasks.every(t=>['completed','skipped','cancelled'].includes(t.status)))return '';
  return '<div class="notice">已安排的任务均已结束；当前没有自动结束规则，Run 仍保持运行。需要继续时让 Agent 安排后续任务；目标已达成时让 Agent 明确结束条件。</div>';
}
function renderV2Inspect(tab){
  if(tab==='tasks'){const tasks=run.agent_tasks || {items:[],waiting:[]};return `<div class="task-card"><h2>当前任务与异常 · ${tasks.items.length}</h2><p>脚本按最新状态列出事项；如何处理由 Agent 根据用户授权判断。</p><pre>${esc(pretty(tasks.items))}</pre><h3>正常等待 / 等待用户 · ${tasks.waiting.length}</h3><pre>${esc(pretty(tasks.waiting))}</pre></div>`;}
  if(tab==='records')return `<div class="task-card"><h2>结果记录</h2><p>只有正式完整提交的输出才会出现在这里。按记录身份保存版本、生产者和读取来源。</p></div>`+Object.entries(run.records).map(([id,versions])=>
    `<details class="task-card"><summary>${esc(id)} · ${esc(versions.at(-1).type)} · v${versions.length}</summary>${versions.slice().reverse().map(r=>`<p>v${r.revision} · <button data-exec="${esc(r.producer)}">查看生产执行</button></p><pre>${esc(pretty(r))}</pre>`).join('')}</details>`).join('');
  if(tab==='task-history')return renderTaskHistory();
  const ended=!run.operator_protocol || ['completed','terminated'].includes(run.status);
  return noticeScheduleHTML(run,run.settings.bindings||{})+run.settings.hooks.map(h=>`<details class="task-card"><summary>${esc(h.id)} · ${h.enabled===false?'已停用':'已启用'}</summary><pre>${esc(pretty(h))}</pre></details>`).join('')+run.hook_firings.filter(f=>f.status==='held').map(f=>`<div class="task-card">${esc(f.tasks)} · 暂停中 <button class="primary" data-release-gate="${esc(f.id)}" ${ended?'disabled':''}>放行本次工作</button></div>`).join('')+notificationCards();

}
document.addEventListener('click',event=>safely(async()=>{
  const d=event.target.closest('button')?.dataset;if(!d||!run)return;
  if(d.releaseGate)await api(`runs/${run.id}/command`,{action:'release_gate',hook_firing:d.releaseGate});
  else if(d.retryNotification)await api(`runs/${run.id}/command`,{action:'retry_notification',notification_id:d.retryNotification});
  else return;
  await refresh();
}));
