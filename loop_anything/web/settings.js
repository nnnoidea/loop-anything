'use strict';
// Record-driven workspace. No domain-specific approval or event handling.
Object.assign(labels,{waiting_user:'等待用户',planned:'已规划',held:'暂停待放行',stale:'已失效',delivered:'已送达',sending:'发送中',pending:'待发送'});
for(const [id,label] of [['records','结果记录'],['task-history','运行过程'],['hooks','通知与控制'],['tasks','任务与问题']]){
  const button=document.createElement('button');button.dataset.tab=id;button.textContent=label;button.className='v2-tab';button.hidden=true;
  document.querySelector('.tabs').append(button);
}
function renderTimelineSettings(){
  document.querySelectorAll('.v2-tab').forEach(b=>b.hidden=false);
  if(run.agent_sessions?.some(owner=>owner.recovery_required))$('attention').innerHTML+='<div class="notice">有 Agent 的进程状态需要核实。<button data-tab="tasks">查看任务与问题</button></div>';
  const held=Object.values(run.tasks).filter(w=>w.status==='held');
  if(held.length)$('attention').innerHTML+=`<div class="notice">${held.length} 项工作已被执行前暂停拦截。到「通知与控制」查看并放行。</div>`;
  if(run.diagnostics.length || run.agent_tasks?.items?.length)$('attention').innerHTML+='<button class="text-button run-issues" data-tab="tasks">查看任务与问题 →</button>';

  $('attention').innerHTML+=runIdleHint(run);
}
function runIdleHint(value){
  const tasks=Object.values(value.tasks||{});
  if(value.status!=='running'||value.identity_read_only||!tasks.length||value.settings.completion_rule!=null||value.settings.termination_signal||(value.agent_sessions||[]).length||(value.diagnostics||[]).length||(value.agent_tasks?.items||[]).length||!tasks.every(t=>['completed','skipped','cancelled'].includes(t.status)))return '';
  return '<div class="notice">已安排的任务均已结束；当前没有自动结束规则，Run 仍保持运行。需要继续时让 Agent 安排后续任务；目标已达成时让 Agent 明确结束条件。</div>';
}
function renderV2Inspect(tab){
  if(tab==='tasks'){
    const tasks=run.agent_tasks||{items:[],waiting:[]};
    const problemText=d=>({
      order_dependency_gap:'前置任务尚未完成',upstream_fault:'前置任务执行失败',dependency_gap:'缺少所需的结果',
      skipped_dependency:'前置任务已跳过',dependency_cycle:'任务之间循环等待',missing_implementation:'尚未选择执行方式',
      budget_exhausted:'任务预算已用尽',observation_error:'外部采集异常',invalid_input:'输入不可用',
      invalid_completion_rule:'结束条件不可用'
    })[d.kind]||'需要核对运行记录';
    const row=i=>{
      const task=run.tasks[i.task_id], reason=i.reason;
      const text=Array.isArray(reason)?reason.map(waitReasonText).join(' · '):reason&&typeof reason==='object'?problemText(reason):
        i.kind==='waiting'&&task?(labels[task.status]||task.status):typeof reason==='string'?failureSummary(reason):'等待处理';
      const name=task?taskLabel(task):i.notification_id?'通知':i.kind==='request'?'用户请求':'运行问题';
      const target=task?`<a class="progress-link" href="${esc(routeHash({type:'run',id:run.id,task:task.id}))}" data-route-link>${esc(name)}</a>`:esc(name);
      return `<li>${target} · ${esc(text)}</li>`;
    };
    return `<div class="task-card"><h2>当前任务与异常 · ${tasks.items.length}</h2>${tasks.items.length?`<ul>${tasks.items.map(row).join('')}</ul>`:'<p>暂无待处理事项。</p>'}
      ${tasks.waiting.length?`<details><summary>等待中的事项 · ${tasks.waiting.length}</summary><ul>${tasks.waiting.map(row).join('')}</ul></details>`:''}
      ${readerJSON('原始任务与诊断',{待处理:tasks.items,等待:tasks.waiting,诊断:run.diagnostics,操作者:tasks.owners||[]})}</div>`;
  }
  if(tab==='records')return `<div class="task-card"><h2>结果记录</h2><p>只有正式完整提交的输出才会出现在这里。按记录身份保存版本、生产者和读取来源。</p></div>`+Object.entries(run.records).map(([id,versions])=>
    `<details class="task-card"><summary>${esc(id)} · ${esc(versions.at(-1).type)} · v${versions.length}</summary>${versions.slice().reverse().map(r=>`<p>v${r.revision} · <button data-exec="${esc(r.producer)}">查看生产执行</button></p><pre>${esc(pretty(r))}</pre>`).join('')}</details>`).join('');
  if(tab==='task-history')return renderTaskHistory();
  const ended=['completed','terminated'].includes(run.status);
  return noticeScheduleHTML(run,run.settings.bindings||{})+run.settings.hooks.map(h=>`<details class="task-card"><summary>${esc(h.id)} · ${h.enabled===false?'已停用':'已启用'}</summary><pre>${esc(pretty(h))}</pre></details>`).join('')+run.hook_firings.filter(f=>f.status==='held').map(f=>`<div class="task-card">${esc(f.tasks)} · 暂停中 <button class="primary" data-release-gate="${esc(f.id)}" ${ended?'disabled':''}>放行本次工作</button></div>`).join('')+notificationCards();

}
document.addEventListener('click',event=>safely(async()=>{
  const d=event.target.closest('button')?.dataset;if(!d||!run)return;
  if(d.releaseGate)await api(`runs/${run.id}/command`,{action:'release_gate',hook_firing:d.releaseGate});
  else if(d.retryNotification)await api(`runs/${run.id}/command`,{action:'retry_notification',notification_id:d.retryNotification});
  else return;
  await refresh();
}));
