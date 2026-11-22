'use strict';
// Record-driven workspace. No domain-specific approval or event handling.
Object.assign(labels,{waiting_user:'等待用户',planned:'已规划',held:'暂停待放行',stale:'已失效',delivered:'已送达',sending:'发送中',pending:'待发送'});
function renderTimelineSettings(){ $('attention').innerHTML=runIdleHint(run); }
function runIdleHint(value){
  const tasks=Object.values(value.tasks||{});
  if(value.status!=='running'||value.identity_read_only||!tasks.length||value.settings.completion_rule!=null||value.settings.termination_signal||(value.agent_sessions||[]).length||(value.has_diagnostics||(value.diagnostics||[]).length)||(value.agent_tasks?.items||[]).length||!tasks.every(t=>['completed','skipped','cancelled'].includes(t.status)))return '';
  return '<div class="notice">已安排的任务均已结束；当前没有自动结束规则，Run 仍保持运行。需要继续时让 Agent 安排后续任务；目标已达成时让 Agent 明确结束条件。</div>';
}
const runIssueText={
  order_dependency_gap:'前置任务尚未完成',upstream_fault:'前置任务执行失败',dependency_gap:'缺少所需的结果',
  skipped_dependency:'前置任务已跳过',dependency_cycle:'任务之间循环等待',missing_implementation:'尚未选择执行方式',
  budget_exhausted:'任务预算已用尽',observation_error:'外部采集异常',invalid_input:'输入不可用',
  invalid_completion_rule:'结束条件不可用'
};
function runAttentionItems(value){
  if(value.superseded_by||['completed','terminated','continued'].includes(value.status))return [];
  const issues=new Map(),attempts=new Map(value.executions.map(e=>[e.id,e]));
  for(const t of Object.values(value.tasks)){
    const e=attempts.get(t.execution_id),status=t.status;
    const note=value.task_dispositions?.[t.id]?.reason;
    const waitingEvent=e?.status==='waiting'&&e.implementation.kind==='event';
    const label=note?'等待用户处理':e?.observation_error?'外部采集异常':status==='fault'?'节点执行失败':status==='held'?'等待放行':
      status==='waiting_user'||status==='approval'?'等待用户确认':status==='stale'?'执行状态需核实':
      status==='unresolved'?'等待处理异常':status==='decision'&&!e?.worker_active?'等待 Agent':waitingEvent?'等待事件':'';
    if(label)issues.set(t.id,{task_id:t.id,label,control:status==='held'&&!note,status,note});
  }
  for(const item of value.agent_tasks?.items||[]){
    const task=value.tasks[item.task_id],key=task?.id||item.id;
    if(issues.has(key))continue;
    if(item.kind==='task'&&(task?.status==='executing'||attempts.get(task?.execution_id)?.worker_active))continue;
    const label=item.kind==='request'?'用户请求':item.notification_id?'通知发送异常':item.kind==='task'?'等待 Agent':
      runIssueText[item.reason?.kind]||'运行状态需核实';
    issues.set(key,{task_id:task?.id,label,control:!!item.notification_id,note:item.kind==='request'?item.reason:''});
  }
  for(const item of value.agent_tasks?.waiting||[]){
    if(item.status==='waiting_configuration'&&item.notification_id)issues.set(item.id,{label:'通知出口待配置',control:true});
  }
  if(value.agent_sessions?.some(owner=>owner.recovery_required))issues.set('session',{label:'Agent 会话状态需核实',note:'可请 Agent 核对会话状态。'});
  return [...issues.values()];
}
function runTaskLink(id,label){
  return `<a href="${esc(routeHash({type:'run',id:run.id,task:id}))}" data-route-link>${esc(label)}</a>`;
}
function taskDisplayName(task){
  return [taskLabel(task),task.spec.ref||task.spec.round].filter(Boolean).join(' · ');
}
function runTaskIssues(issues){
  if(!issues.length)return '<p class="empty-inline">当前没有待处理事项。</p>';
  return `<ul class="run-issue-list">${issues.map(item=>{
    const task=run.tasks[item.task_id];
    return `<li><div><strong>${esc(item.label)}</strong>${task?`<p>${esc(taskDisplayName(task))}</p>`:''}${item.note?`<p>${esc(item.note)}</p>`:''}</div>
      ${item.control?'<button data-tab="hooks">查看通知与控制</button>':task?runTaskLink(task.id,'查看节点'):''}</li>`;
  }).join('')}</ul>`;
}

const runActivityLabels={created:'创建运行',completed:'运行结束',pause:'暂停运行',resume:'恢复运行',terminate:'终止运行',
  method_updated:'更新后续任务的 Loop 版本',settings:'修改运行配置',monitor_retry:'恢复外部监控',retry_applied:'自动安排重试',
  waiting_user:'等待用户处理',agent_failure_pause:'Agent 连续失败，运行暂停',gate:'任务在执行前暂停',
  release_gate:'放行任务',budget_exhausted:'任务预算已用尽',transition:'节点出现异常'};
const runTaskChangeLabels={update:'调整任务',cancel:'取消任务',retry:'重试任务'};
const runFailureLabels={external_rejected:'外部任务提交被拒',process_error:'执行进程出现异常',
  failed_requires_agent:'节点失败，需 Agent 处理',failed_retryable:'节点失败，可重试'};
function runActivityHTML(){
  if(!run.history.length)return '<p class="empty-inline">这一页没有关键变更。</p>';
  const rows=run.history.map(h=>{
    const title=h.kind==='agent_action_change'?runTaskChangeLabels[h.operation]||'修改任务':
      h.kind==='transition'?runFailureLabels[h.event]||runActivityLabels.transition:runActivityLabels[h.kind];
    const task=run.tasks[h.task_id];
    return `<li><time datetime="${new Date(h.at*1000).toISOString()}">${esc(taskTime(h.at))}</time><div><strong>${esc(title)}</strong>${task?`<div class="run-activity-task">${runTaskLink(task.id,taskDisplayName(task))}</div>`:''}${h.note?`<p>${esc(h.note)}</p>`:''}</div></li>`;
  }).join('');
  const end=runHistoryOffset+run.history.length;
  const pagination=run.history_total>50?`<div class="run-pagination"><button data-history-offset="${Math.max(0,runHistoryOffset-50)}" ${runHistoryOffset?'':'disabled'}>← 更新的记录</button><span>${runHistoryOffset+1}–${end} / ${run.history_total} 条</span><button data-history-offset="${end}" ${end<run.history_total?'':'disabled'}>更早的记录 →</button></div>`:'';
  return `<ol class="run-activity">${rows}</ol>${pagination}`;
}
function renderRunPanel(tab,issues,detailError){
  if(tab==='task-history')return renderTaskHistory(detailError);
  if(tab==='tasks')return runTaskIssues(issues);
  if(tab==='activity')return runActivityHTML();
  const ended=run.identity_read_only||['completed','terminated','continued'].includes(run.status);
  const held=run.hook_firings.filter(f=>f.status==='held').map(f=>{
    const task=run.tasks[f.tasks];
    return `<div class="task-card">等待放行${task?' · '+runTaskLink(task.id,taskDisplayName(task)):''} <button class="primary" data-release-gate="${esc(f.id)}" ${ended?'disabled':''}>放行本次工作</button></div>`;
  }).join('');
  return held+notificationCards()+noticeScheduleHTML(run,run.settings.bindings||{});
}
document.addEventListener('click',event=>safely(async()=>{
  const d=event.target.closest('button')?.dataset;if(!d||!run)return;
  if(d.releaseGate)await api(`runs/${run.id}/command`,{action:'release_gate',hook_firing:d.releaseGate});
  else if(d.retryNotification)await api(`runs/${run.id}/command`,{action:'retry_notification',notification_id:d.retryNotification});
  else return;
  await refresh();
}));
