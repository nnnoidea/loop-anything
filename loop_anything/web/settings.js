'use strict';
// Record-driven workspace. No domain-specific approval or event handling.
Object.assign(labels,{waiting_user:'等待用户',planned:'已规划',held:'暂停待放行',stale:'已失效',delivered:'已送达',sending:'发送中',pending:'待发送'});
const v2Fields=document.createElement('div');v2Fields.id='v2-fields';v2Fields.hidden=true;
v2Fields.innerHTML='<label>用户授权<textarea id="authorization" rows="3" placeholder="允许 Agent 自行处理什么，哪些操作需要确认"></textarea></label><label>Objective<textarea id="objective" rows="2"></textarea></label><details><summary>Requirements · JSON</summary><textarea id="requirements" class="code" rows="3"></textarea></details>';
v2Fields.insertAdjacentHTML('beforeend','<details><summary>终态规则与信号</summary><p class="small muted">Engine 按规则或信号进入终态；空任务列表不表示完成。</p><label>机械终态规则 · JSON<textarea id="completion-rule" class="code" rows="4"></textarea></label><label>终止信号 · 原因<textarea id="termination-signal" rows="2"></textarea></label></details>');
v2Fields.insertAdjacentHTML('beforeend','<details><summary>Run 默认实现 · Binding</summary><p class="small muted">改选只影响后续尚未派发且未单独指定实现的任务。</p><div id="run-bindings"></div></details>');
v2Fields.insertAdjacentHTML('beforeend','<label>Agent 兜底节点<select id="run-fallback"></select></label><p class="small muted">留空关闭自动兜底。已启动的 Agent 按原操作权结束。</p>');
v2Fields.insertAdjacentHTML('beforeend','<label>全局 Agent 节点（留空默认兜底）<select id="run-global-agent"></select></label>');
$('settings-form').prepend(v2Fields);
for(const [id,label] of [['records','结果记录'],['task-history','运行过程'],['hooks','Hooks'],['tasks','任务与问题']]){
  const button=document.createElement('button');button.dataset.tab=id;button.textContent=label;button.className='v2-tab';button.hidden=true;
  document.querySelector('.tabs').append(button);
}
function renderTimelineSettings(){
  document.querySelectorAll('.v2-tab').forEach(b=>b.hidden=false);
  $('v2-fields').hidden=false;
  for(const owner of run.agent_sessions || [])$('attention').innerHTML+=`<div class="notice">${owner.kind==='interactive'?'你的 Agent':'后台 Agent'} · ${owner.scope_task?esc(run.loop_definition.nodes[run.tasks[owner.scope_task]?.spec.node]?.label || owner.scope_task)+'（'+esc(owner.scope_task)+'）支线':'全局'}正在处理工作${owner.recovery_required?' · 旧进程状态需人工核实':''}。</div>`;
  const held=Object.values(run.tasks).filter(w=>w.status==='held');
  if(held.length)$('attention').innerHTML+=`<div class="notice">${held.length} 项工作已被执行前暂停拦截。到 Hooks 查看并放行。</div>`;
  if(run.diagnostics.length)$('attention').innerHTML+=`<div class="notice">${run.diagnostics.length} 项依赖诊断：${run.diagnostics.map(d=>esc(d.kind)).join('、')}。到任务与问题查看缺少什么。</div>`;
}
function renderV2Inspect(tab){
  if(tab==='tasks'){const tasks=run.agent_tasks || {items:[],waiting:[]};return manualAgentTasks()+`<div class="task-card"><h2>当前任务与异常 · ${tasks.items.length}</h2><p>脚本按最新状态列出事项；如何处理由 Agent 根据用户授权判断。</p><pre>${esc(pretty(tasks.items))}</pre><h3>正常等待 / 等待用户 · ${tasks.waiting.length}</h3><pre>${esc(pretty(tasks.waiting))}</pre></div>`;}
  if(tab==='records')return `<div class="task-card"><h2>结果记录</h2><p>只有正式完整提交的输出才会出现在这里。按记录身份保存版本、生产者和读取来源。</p></div>`+Object.entries(run.records).map(([id,versions])=>
    `<details class="task-card"><summary>${esc(id)} · ${esc(versions.at(-1).type)} · v${versions.length}</summary>${versions.slice().reverse().map(r=>`<p>v${r.revision} · <button data-exec="${esc(r.producer)}">查看生产执行</button></p><pre>${esc(pretty(r))}</pre>`).join('')}</details>`).join('');
  if(tab==='task-history')return renderTaskHistory();
  const ended=!run.operator_protocol || ['completed','terminated'].includes(run.status);
  return `<div class="task-card"><h2>Hooks</h2><p>不修改Loop 定义。暂停在派发前拦截，通知独立送达；已派发的执行不会被追溯暂停。</p>
    <form id="hook-form"><label>目标节点<select id="hook-node">${Object.entries(run.loop_definition.nodes).map(([id,n])=>`<option value="${esc(id)}">${esc(n.label || id)}</option>`).join('')}</select></label>
    <label>动作<select id="hook-action"><option value="pause">执行前暂停</option><option value="notify-before">执行前通知</option><option value="notify-after">完成后通知</option></select></label>
    <label>频率<select id="hook-frequency"><option value="once">仅下一次</option><option value="always">后续每次</option></select></label>
    <label>显示或发送<select id="hook-route"><option value="workspace">仅在网页显示</option><option value="user">通过已配置出口发送</option></select></label><label>通知内容<input id="hook-message" placeholder="通过用户配置的通知命令发送"></label><button class="primary" ${ended?'disabled':''}>添加 Hook</button></form></div>`+
    run.settings.hooks.map(h=>`<div class="task-card"><strong>${esc(h.id)}</strong> · ${esc(h.action)} / ${esc(h.phase)} / ${esc(h.frequency)}<p>${esc(pretty(h.target))}</p><button data-toggle-hook="${esc(h.id)}" ${ended?'disabled':''}>${h.enabled===false?'启用':'停用'}</button></div>`).join('')+
    run.hook_firings.filter(f=>f.status==='held').map(f=>`<div class="task-card">${esc(f.tasks)} · 暂停中 <button class="primary" data-release-gate="${esc(f.id)}" ${ended?'disabled':''}>放行本次工作</button></div>`).join('')+
    '<div class="task-card"><h2>通知收件箱 / 送达回执</h2><p>这里保留通知状态与回执；实际发送使用用户配置的命令，未配置或发送失败会明确显示。</p></div>'+
    run.notifications.map(n=>`<details class="task-card"><summary>${esc(n.message)} ${badge(n.status)}</summary><pre>${esc(pretty(n))}</pre>${n.status==='fault'?`<button data-retry-notification="${esc(n.id)}">重试通知</button>`:''}</details>`).join('');
}
function sampleSchema(schema){
  if(schema.enum)return schema.enum[0];
  if(schema.type==='object')return Object.fromEntries(Object.entries(schema.properties || {}).map(([k,v])=>[k,sampleSchema(v)]));
  return {string:'',number:0,boolean:false,array:[]}[schema.type];
}
function outputTemplate(e){
  const node=run.loop_definition.nodes[e.node];
  return Object.fromEntries(Object.entries(node.outputs).map(([k,v])=>[k,sampleSchema(run.loop_definition.records[v.record_type])]));
}
function v2Task(e){
  const node=run.loop_definition.nodes[e.node],envelope={outputs:outputTemplate(e)};
  if(node.initialize_timeline)envelope.settings={objective:'',requirements:[],constraints:{},guidance:''};
  return `<div class="task-card"><h2>${esc(nodeLabel(e.node))} ${badge(e.status)}</h2><p>${esc(node.instructions)}</p><details><summary>结果约束</summary><pre>${esc(pretty(node.assertions || []))}</pre></details><a target="_blank" href="/api/runs/${esc(run.id)}/snapshot/${esc(e.id)}">读取完整 Programmable Timeline 与操作手册</a><details><summary>本次输入</summary><pre>${esc(pretty(e.inputs))}</pre></details><p>提交完整结果 JSON；确认节点中的布尔值请按你的决定修改。</p><textarea class="code" rows="12" id="result-${esc(e.id)}">${esc(drafts[e.id] || pretty(envelope))}</textarea><button class="primary" data-result="${esc(e.id)}">提交结果</button></div>`;
}
document.addEventListener('submit',event=>{
  if(event.target.id!=='hook-form')return;event.preventDefault();
  safely(async()=>{
    const action=$('hook-action').value;
    const hook={id:crypto.randomUUID(),action:action==='pause'?'pause':'notify',phase:action==='notify-after'?'after':'before',frequency:$('hook-frequency').value,target:{node:$('hook-node').value},message:$('hook-message').value,route:$('hook-route').value};
    await api(`runs/${run.id}/settings`,{revision:run.settings.revision,change:{hooks:[...run.settings.hooks,hook]}});settingsBase=null;await refresh();toast('Hook 已添加');
  });
});
document.addEventListener('click',event=>safely(async()=>{
  const d=event.target.closest('button')?.dataset;if(!d || !run)return;
  if(d.releaseGate)await api(`runs/${run.id}/command`,{action:'release_gate',hook_firing:d.releaseGate});
  else if(d.retryNotification)await api(`runs/${run.id}/command`,{action:'retry_notification',notification_id:d.retryNotification});
  else if(d.toggleHook){await api(`runs/${run.id}/settings`,{revision:run.settings.revision,change:{hooks:run.settings.hooks.map(h=>h.id===d.toggleHook?{...h,enabled:h.enabled===false}:h)}});settingsBase=null;}
  else return;
  await refresh();
}));

// Manual submission is another client of the same Agent tools, never a node-only protocol.
const manualAgentReads=new Map();
function manualAgentTasks(){
  return (run.agent_sessions || []).map(owner=>{
    const wakeup=run.executions.find(e=>e.id===owner.execution_id);
    if(!wakeup || wakeup.implementation.command)return '';
    const items=(owner.tasks || []).filter(t=>t.kind==='task');
    const cards=items.map(t=>{
      const key=run.id+':'+t.task_id,info=manualAgentReads.get(key);
      const heading=`<div class="task-card"><h2>${esc(nodeLabel(t.node))}</h2>`;
      if(!info || info.token!==owner.token)return heading+`<button data-read-agent-task="${esc(t.task_id)}" data-operator-token="${esc(owner.token)}">读取当前任务</button></div>`;
      const node=run.loop_definition.nodes[t.node],envelope={outputs:outputTemplate({node:t.node,inputs:info.inputs,parameters:info.task.spec.parameters || {}})};
      if(node.initialize_timeline)envelope.settings={objective:'',requirements:[],constraints:{},guidance:''};
      return heading+`<pre>${esc(pretty(info.inputs))}</pre><textarea class="code" id="manual-${esc(t.task_id)}" rows="10">${esc(drafts[key] || pretty(envelope))}</textarea><button data-complete-agent-task="${esc(t.task_id)}" data-operator-token="${esc(owner.token)}">提交任务结果</button></div>`;
    }).join('');
    return cards+`<div class="task-card"><button data-finish-agent="${esc(owner.token)}">结束${owner.scope_task?'该支线':'全局'}的本次操作</button></div>`;
  }).join('');
}
document.addEventListener('input',event=>{
  if(event.target.id.startsWith('manual-'))drafts[run.id+':'+event.target.id.slice(7)]=event.target.value;
});
document.addEventListener('click',event=>safely(async()=>{
  const d=event.target.closest('button')?.dataset;
  if(!d || !run || (!d.readAgentTask && !d.completeAgentTask && !('finishAgent' in d)))return;
  const id=run.id,token=d.operatorToken || d.finishAgent;
  const call=async(tool,args)=>{const result=await api(`runs/${id}/agent`,{token,tool,arguments:args});return result;};
  if(d.readAgentTask){const info=await call('read_task',{task_id:d.readAgentTask});manualAgentReads.set(id+':'+d.readAgentTask,{...info,token});inspectSignature='';renderInspect();}
  else if(d.completeAgentTask){const key=id+':'+d.completeAgentTask,info=manualAgentReads.get(key);await call('complete_task',{task_id:d.completeAgentTask,task_version:info.task_version,envelope:JSON.parse($('manual-'+d.completeAgentTask).value)});manualAgentReads.delete(key);delete drafts[key];await refresh();}
  else {await call('finish',{});await refresh();}
}));
