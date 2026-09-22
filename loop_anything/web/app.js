'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = value => JSON.stringify(value, null, 2);
// getRandomValues also works on ordinary HTTP inside the team network.
const randomKey = () => Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
const labels = {skipped:'已跳过',running:'运行中',ready:'待执行',executing:'执行中',waiting:'等待外部',completed:'已完成',paused:'已暂停',terminated:'已终止',cancelled:'已取消',fault:'执行失败',retrying:'等待重试',blocked:'输入未就绪',decision:'等待 Agent',approval:'等待确认',unresolved:'转移待决策'};
const badge = status => `<span class="badge ${esc(status)}">${esc(labels[status] || status)}</span>`;
let catalog = [], runs = [], run = null, selected = null, filterNode = null, activeTab = 'task-history', page = 'runs', settingsBase = null, pendingChange = null, loading = false;
const drafts = {};
let powerPending=false,lastPower=null;
function renderPower(power){
  lastPower=power;
  $('platform-power').className='platform-power '+(power.active?'protected':'unprotected');
  $('platform-power-status').textContent=power.updating?(power.requested?'正在启用防休眠保护…':'正在关闭防休眠保护…'):power.error?'防休眠设置未生效 · '+power.error:power.active?'平台运行中 · 已启用防休眠保护':'平台运行中 · 当前允许系统休眠';
  $('platform-power-switch').checked=power.requested;
  $('platform-power-switch').disabled=powerPending||power.updating||!power.controllable||!editAccess.unlocked;
  $('platform-power-switch').title=editAccess.unlocked?'作用于平台所在机器；选择会保留，重启后仍有效':'请先解锁编辑';
}
$('platform-power-switch').onchange=()=>safely(async()=>{
  const enabled=$('platform-power-switch').checked;powerPending=true;$('platform-power-switch').disabled=true;
  try{renderPower(await api('platform/keep-awake',{enabled}));}
  finally{powerPending=false;await refresh();}
});
let editAccess={protected:false,unlocked:true,expires_at:null};
function showEditAccess(status){
  editAccess=status;$('edit-access').hidden=!status.protected;
  if(lastPower)renderPower(lastPower);
  $('edit-access-state').textContent=status.unlocked?'可编辑 · '+new Date(status.expires_at*1000).toLocaleString()+' 到期':'只读';
  $('edit-access-button').textContent=status.unlocked?'锁定编辑':'解锁编辑';
  clearTimeout(showEditAccess.timer);
  if(status.expires_at)showEditAccess.timer=setTimeout(()=>showEditAccess({...status,unlocked:false,expires_at:null}),Math.max(0,status.expires_at*1000-Date.now()));
}
async function readEditAccess(){showEditAccess(await api('edit-access'));}
const unlockDialog=document.createElement('dialog');unlockDialog.id='edit-unlock-dialog';
unlockDialog.innerHTML='<form id="edit-unlock-form"><h2>解锁编辑</h2><p>输入共享口令，24 小时内可持续编辑。刷新和切换页面无需再次输入。</p><label>编辑口令<input id="edit-password" type="password" autocomplete="current-password" required></label><p id="edit-unlock-error" role="alert"></p><div class="dialog-tasks"><button type="button" id="edit-unlock-cancel">取消</button><button class="primary" type="submit">解锁 24 小时</button></div></form>';
document.body.append(unlockDialog);
$('edit-access-button').onclick=()=>safely(async()=>{
  if(editAccess.unlocked){showEditAccess(await api('edit-access',{action:'lock'}));await refresh();}
  else{$('edit-unlock-error').textContent='';unlockDialog.showModal();$('edit-password').focus();}
});
$('edit-unlock-cancel').onclick=()=>unlockDialog.close();
unlockDialog.addEventListener('close',()=>{$('edit-password').value='';});
$('edit-unlock-form').onsubmit=async event=>{
  event.preventDefault();
  try{showEditAccess(await api('edit-access',{action:'unlock',password:$('edit-password').value}));unlockDialog.close();await refresh();}
  catch(error){$('edit-unlock-error').textContent=error.message;}
};
window.addEventListener('focus',()=>readEditAccess().catch(()=>{}));
let promptDefaults={};
function promptEditor(mode,config){return `<details class="agent-prompt-editor" data-prompt-mode="${mode}"><summary>唤醒提示词</summary><p class="small muted">可以直接修改，或改用作者脚本。{{context}} 展开本次上下文；自定义内容完整替换默认提示词；清空会发送空内容。</p><label>发送给 Agent 的内容<textarea data-agent-prompt rows="8">${esc(config.prompt??promptDefaults[mode]??'')}</textarea></label><div class="prompt-actions"><button type="button" data-prompt-reset>恢复默认</button><button type="button" data-prompt-preview>预览发送内容</button></div></details>`;}
function readPrompt(root,mode){const text=root.querySelector('[data-agent-prompt]').value;return text===promptDefaults[mode]?{}:{prompt:text};}
function promptHistory(record){return record&&Object.hasOwn(record,'prompt_text')?`<details class="prompt-history"><summary>本次唤醒提示词</summary><p class="small muted">实际发送记录 · 平台令牌已遮蔽</p><pre>${esc(record.prompt_text)}</pre></details>`:'';}
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('[data-prompt-reset],[data-prompt-preview]');if(!button)return;
  const root=button.closest('[data-prompt-mode]'),field=root.querySelector('[data-agent-prompt]'),mode=root.dataset.promptMode;
  if(button.hasAttribute('data-prompt-reset')){field.value=promptDefaults[mode];field.dispatchEvent(new Event('input',{bubbles:true}));return;}
  let data;
  if(mode==='task'){collectAll();data={loop_definition:editor.loop_definition,node_id:editSelection.node};}
  else data={conversation_id:conversation.id,run_id:conversation.run_id,message:$('web-chat-input').value,launch:page==='launch'?launchValues():undefined,scope_task:$('web-chat-scope').value||null};
  const preview=await api('agent-prompts/preview',{...data,prompt:field.value});
  let dialog=$('prompt-preview');if(!dialog){dialog=document.createElement('dialog');dialog.id='prompt-preview';document.body.append(dialog);}
  dialog.innerHTML=`<h2>提示词预览</h2><p class="small muted">${esc(preview.notice)}</p><pre>${esc(preview.text)}</pre><button type="button">关闭</button>`;
  dialog.querySelector('button').onclick=()=>dialog.close();dialog.showModal();
}));
let listSignature = '', graphSignature = '', inspectSignature = '';
const time = t => new Date(t * 1000).toLocaleTimeString('zh-CN', {hour12:false});
const nodeLabel = id => run?.loop_definition.nodes[id]?.label || id;
async function api(url, data) {
  const response = await fetch('/api/' + url, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Loop-Anything':'workspace'},body:JSON.stringify(data)});
  const result = await response.json();
  if(result.code==='edit_locked')showEditAccess({protected:true,unlocked:false,expires_at:null});
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}
function toast(message) { $('toast').textContent = message; $('toast').style.display = 'block'; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').style.display = 'none', 5500); }
async function safely(fn) { try { await fn(); } catch (error) { toast(error.message); } }
function showPage() {
  if($('launch-page'))$('launch-page').hidden=page!=='launch';
  $('workspace').hidden = page !== 'runs' || !run;
  $('empty').hidden = page !== 'runs' || !!run;
  $('catalog-page').hidden = page !== 'catalog';
  if($('loop_definition-editor'))$('loop_definition-editor').hidden=page!=='editor';
  if($('loop-detail'))$('loop-detail').hidden=page!=='loop';
  $('loop_definitions-nav').classList.toggle('active', ['catalog','editor','loop'].includes(page));
  if(typeof updateNavigationUI==='function')updateNavigationUI();

}
async function refresh() {
  if (loading) return;
  loading = true;
  try {
    runs = await api('runs');
    await loadPreparationCards();
    $('engine-status').textContent = 'Engine connected';
    const listHTML = runs.map(r => `<button class="run-item ${page==='runs' && selected === r.id ? 'chosen' : ''}" data-run="${esc(r.id)}"><strong>${esc(r.title)}</strong><small>${esc(labels[r.status])} · ${r.executions.length} executions</small></button>`).join('');
    if(listSignature !== listHTML){$('run-list').innerHTML=listHTML;listSignature=listHTML;}
    if (!selected && runs.length) selected = runs[0].id;
    if (selected && page==='runs') { const id=selected,current=await api('runs/' + id);if(page==='runs' && selected===id){run=current;renderRun();} }
    const platform=await api('platform'),power=platform.keep_awake;
    renderPower(power);
    showPage();
  } catch (error) { $('engine-status').textContent = '连接中断 · 自动重连';$('platform-power').className='platform-power unprotected';$('platform-power-status').textContent='与平台连接中断 · 无法确认运行及防休眠状态';$('platform-power-switch').disabled=true; }
  finally { loading = false; }
}
async function selectRun(id) {
  await navigateTo({type:'run',id});
}
function renderRun() {
  updateNavigationUI();
  $('run-title').textContent = run.title;
  $('run-key').textContent = (run.loop_definition.name || run.loop_definition.id) + ' · v' + run.loop_definition.version;
  $('run-status').innerHTML = badge(run.status);
  $('run-id').textContent = run.id;
  const simulation = Object.values(run.implementations).some(entry => Object.values(implementationOptions(entry)).some(b => b.kind === 'mock' || b.simulation));
  $('simulation-label').hidden = !simulation;
  const ended = run.schema_version!==2 || !run.operator_protocol || ['completed','terminated'].includes(run.status);
  $('settings-form').querySelectorAll('input,textarea,select,button').forEach(el=>el.disabled=ended);
  $('pause-run').textContent = run.status === 'paused' ? '▷ 恢复' : 'Ⅱ 暂停';
  $('pause-run').disabled = $('stop-run').disabled = ended;
  const counts = {};
  run.executions.forEach(e => counts[e.status] = (counts[e.status] || 0) + 1);
  $('metrics').innerHTML = [['执行记录',run.executions.length,'total'],['已提交结果',counts.completed || 0,'committed'],['等待 / 执行中',(counts.waiting || 0) + (counts.executing || 0),'active'],['Agent 决策',run.executions.filter(e => e.implementation.kind === 'agent').length,'on demand']].map(([title,n,unit])=>`<div class="metric"><div><label>${title}</label><div><small>${unit}</small></div></div><b>${n}</b></div>`).join('');
  const tasks = run.schema_version===2 ? (run.agent_tasks?.items || []) : [];
  $('attention').innerHTML = tasks.length ? `<div class="notice">当前 ${tasks.length} 项节点任务或异常，请在「任务与异常」查看。</div>` : '';

  if(run.schema_version===2)renderTimelineSettings();
  else {document.querySelectorAll('.v2-tab').forEach(b=>b.hidden=true);$('v2-fields').hidden=true;if(['records','task-history','hooks','tasks'].includes(activeTab))activeTab='executions';}
  document.querySelector('[data-tab="executions"]').hidden=run.schema_version===2;
  renderGraph();
  if (!['TEXTAREA','INPUT','SELECT'].includes(document.activeElement?.tagName) || !document.activeElement.closest('#inspect')) renderInspect();
  if (!settingsBase || settingsBase.runId !== run.id || (run.schema_version===2 && run.initialized && !settingsBase.initialized)) loadSettings();
  if(typeof renderConversation==='function' && conversation?.run_id===run.id)renderConversation();
  $('settings-revision').textContent = 'rev ' + run.settings.revision + (settingsBase.revision !== run.settings.revision ? ' · 表单已过期' : '');
}
function renderGraph() {
  const signature = pretty([run.id,filterNode,run.settings.bindings,run.executions,Object.values(run.tasks || {}).map(w=>[w.id,w.status]),[],$('graph').clientWidth]);
  if(graphSignature===signature)return;graphSignature=signature;
  const old=$('graph').querySelector('.loop-map'),keep=old?.dataset.runId===run.id&&old.dataset.filterNode===(filterNode||'');
  const focus=keep?old.dataset.mapFocus:filterNode,view=keep?old.dataset.mapView:'execution';
  $('graph').innerHTML=loopGraphHTML(run,{bindings:run.settings.bindings || {},focus:focus || '',action:'run'});
  const root=$('graph').querySelector('.loop-map');
  if(root){root.dataset.runId=run.id;root.dataset.filterNode=filterNode||'';if(focus&&Object.hasOwn(run.loop_definition.nodes,focus))focusLoopMap(root,focus,view);}
  $('graph-caption').textContent='循环关系来自 Loop 定义；上方运行过程保留每一项实际任务、结果与历次执行。';
}
function loadSettings() {
  settingsBase = {runId:run.id,initialized:run.initialized,...structuredClone(run.settings)};
  $('intent').value = run.settings.intent;
  $('guidance').value = run.settings.guidance;
  $('parallel').value = run.settings.max_parallel;
  $('constraints').value = pretty(run.settings.constraints);
  if(run.schema_version===2){$('objective').value=run.settings.objective;$('authorization').value=run.settings.authorization || '';$('requirements').value=pretty(run.settings.requirements);$('completion-rule').value=pretty(run.settings.completion_rule ?? null);$('termination-signal').value=run.settings.termination_signal || '';$('run-bindings').innerHTML=bindingFields(run,run.settings.bindings || {});$('run-fallback').innerHTML=fallbackOptions(run.loop_definition,run.settings.fallback_node);$('run-global-agent').innerHTML=globalAgentOptions(run.loop_definition,run.settings.global_agent_node);}
}
function renderInspect() {
  const signature = pretty([run.id,filterNode,activeTab,run.executions,run.history,run.settings.revision,run.tasks,run.records,run.agent_sessions,run.task_dependencies]);
  if(inspectSignature===signature)return;inspectSignature=signature;
  document.querySelectorAll('[data-tab]').forEach(el=>el.classList.toggle('selected',el.dataset.tab===activeTab));
  let content='';
  if(run.schema_version===2 && ['records','task-history','hooks','tasks'].includes(activeTab)) {
    content=renderV2Inspect(activeTab);
  } else if(activeTab==='executions') {
    const executions = run.executions.filter(e=>!filterNode || e.node===filterNode).slice().reverse();
    if(filterNode) content += `<div class="filter-note">${esc(nodeLabel(filterNode))} · ${executions.length} 次执行 <button id="clear-filter">显示全部</button> <button id="node-contract">节点契约</button></div>`;
    content += `<table><thead><tr><th>节点 / 实例</th><th>状态</th><th>尝试</th><th>派发时间</th></tr></thead><tbody>${executions.map(e=>`<tr class="clickable" tabindex="0" data-exec="${esc(e.id)}"><td>${esc(nodeLabel(e.node))}<br><span class="mono">${esc(e.id)}</span></td><td>${badge(e.status)}</td><td class="mono">${e.attempt}</td><td class="mono">${time(e.created_at)}</td></tr>`).join('')}</tbody></table>`;
    if(!executions.length) content += '<div class="empty-inline">等待下一次 Engine tick 创建执行。</div>';
  } else if(activeTab==='history') {
    content = run.history.slice().reverse().map(h=>`<div class="timeline-row"><time>${time(h.at)}</time><div><span class="event-type">${esc(h.kind)}</span>${esc(h.message)}${h.detail?`<details><summary>查看记录</summary><pre>${esc(pretty(h.detail))}</pre></details>`:''}</div></div>`).join('');
  } else if(activeTab==='decisions') {
    content = run.executions.filter(e=>['approval','decision','unresolved'].includes(e.status) && !(run.schema_version===2 && e.implementation.kind==='agent')).map(e=>task(e)).join('');
    if(run.schema_version===2)content += manualAgentTasks();
    const waiting = run.executions.filter(e=>e.status==='waiting' && e.implementation.kind==='event');
    content += waiting.map(e=>`<div class="task-card"><h2>等待 ${esc(e.implementation.event)}</h2><p>提交符合节点输出契约的外部事件。</p><textarea id="event-${esc(e.id)}" class="code" rows="5">${esc(drafts[e.id] || '{}')}</textarea><button data-send-event="${esc(e.id)}">发送事件</button></div>`).join('');
    if(!content) content = '<div class="empty-inline">当前无需决策。Engine 会在到达决策节点时创建任务。</div>';
  }
  $('inspect').innerHTML = content;
}
function task(e) {
  return run.schema_version===2?v2Task(e):'<p>历史运行仅供查看。</p>';
}

function details(id) {
  const e = run.executions.find(x=>x.id===id); if(!e)return;
  $('detail-title').textContent=nodeLabel(e.node)+' · '+e.id;
  const origin=run.tasks?.[e.task_id]?.origin;
  const cause=origin?.fallback?'进入兜底节点':origin?.entry?'入口任务':origin?.agent?'Agent 安排':origin?.execution?'脚本安排':origin?.user?'用户安排':'历史记录';
  $('detail-content').innerHTML=`${badge(e.status)} <span class="mono">attempt ${e.attempt} · settings r${e.settings_revision}</span>${e.error?`<pre>${esc(e.error)}</pre>`:''}${promptHistory(e)}<div class="detail-section"><h3>创建原因</h3><p class="small">${esc(cause)} · ${esc(e.task_id || '')}</p></div><div class="detail-grid"><div><h3>Resolved inputs</h3><pre>${esc(pretty(e.inputs))}</pre></div><div><h3>Committed outputs</h3><pre>${esc(pretty(e.outputs || null))}</pre></div></div><div class="detail-section"><h3>Input provenance</h3><pre>${esc(pretty(e.sources))}</pre></div><div class="detail-section"><h3>Handler / external task</h3><pre>${esc(pretty({implementation:e.implementation,external_id:e.external_id,wake_at:e.wake_at?new Date(e.wake_at*1000).toLocaleString():undefined}))}</pre></div>${run.tasks?.[e.task_id]?.execution_id===e.id && ['fault','blocked'].includes(e.status)&&!e.routed?`<button data-retry="${esc(e.id)}">重试此执行</button><p class="field-note">先检查外部任务是否已经产生副作用，避免重复提交。</p>`:''}`;
  if(!$('detail-dialog').open)$('detail-dialog').showModal();
}
async function openCreate(key) {
  if(!catalog.length){await navigateTo({type:'catalog'});toast('先导入或新建一个 Loop。');return;}
  if(!key){await navigateTo({type:'catalog'});return;}
  await openPreparation(key);
}

function createChanged() {
  const item=catalog.find(c=>c.key===$('create-loop_definition').value); if(!item)return;
  $('create-description').textContent=item.loop_definition.description || '';
  $('create-title').value=(item.loop_definition.name || item.loop_definition.id)+' · '+new Date().toLocaleDateString('zh-CN');
  $('create-inputs').value=pretty(item.loop_definition.defaults || {});
  prepareLaunch(item);
}
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button,[data-exec]'); if(!button)return;
  if(button.classList.contains('close-dialog')){if(button.closest('#create-dialog')){await savePreparation();await openLoop(conversation.launch.key);}else button.closest('dialog').close();return;}
  const d=button.dataset;
  if(d.run){await selectRun(d.run);return;}
  if(d.node){filterNode=d.node;activeTab=run.schema_version===2?'task-history':'executions';inspectSignature='';renderGraph();renderInspect();return;}
  if(d.tab){activeTab=d.tab;renderInspect();return;}
  if(d.exec){if(run.schema_version===2){selectedTask=run.executions.find(e=>e.id===d.exec)?.task_id;selectedAttempt=d.exec;activeTab='task-history';inspectSignature='';renderInspect();}else details(d.exec);return;}
  if(d.create){await openCreate(d.create);return;}
  if(d.validate){const c=catalog.find(x=>x.key===d.validate);const r=await api('validate',c);toast(r.valid?'验证通过 · '+r.warnings.join('；'):r.errors.join('；'));return;}
  const runId=run?.id;
  if(d.retry){await api(`runs/${runId}/command`,{action:'retry',execution_id:d.retry});$('detail-dialog').close();await refresh();return;}
  if(d.result){
    const e=run.executions.find(x=>x.id===d.result);
    const payload={execution_id:e.id,token:e.token,envelope:JSON.parse($('result-'+e.id).value)};
    await api(`runs/${runId}/submit`,payload);toast('结果已提交');await refresh();return;
  }
  if(d.sendEvent){const e=run.executions.find(x=>x.id===d.sendEvent);await api(`runs/${runId}/event`,{event_id:randomKey(),name:e.implementation.event,key:e.parameters?.event_key,payload:JSON.parse($('event-'+e.id).value)});toast('事件已持久化');await refresh();return;}
  switch(button.id){
    case 'new-run':await openCreate();break;
    case 'empty-create':await navigateTo({type:'catalog'});break;
    case 'loop_definitions-nav':await navigateTo({type:'catalog'});break;
    case 'clear-filter':filterNode=null;renderGraph();renderInspect();break;
    case 'node-contract':$('detail-title').textContent=nodeLabel(filterNode)+' · Contract';$('detail-content').innerHTML=`<pre>${esc(pretty(run.loop_definition.nodes[filterNode]))}</pre>`;$('detail-dialog').showModal();break;
    case 'pause-run':await api(`runs/${runId}/command`,{action:run.status==='paused'?'resume':'pause'});await refresh();break;
    case 'stop-run':if(confirm('终止后不会再推进。外部已发生的操作不会被撤销。是否终止？')){await api(`runs/${runId}/command`,{action:'terminate'});await refresh();}break;
    case 'apply-change':await api(`runs/${pendingChange.runId}/settings`,{revision:pendingChange.revision,change:pendingChange.change});$('review-dialog').close();settingsBase=null;await refresh();toast('Programmable Timeline 已更新，后续工作按新要求继续');break;
  }
}));
document.addEventListener('keydown',e=>{if(e.key==='Enter' && e.target.matches('tr[data-exec]'))details(e.target.dataset.exec);});
document.addEventListener('input',e=>{if(e.target.id.startsWith('result-'))drafts[e.target.id.slice(7)]=e.target.value;if(e.target.id.startsWith('event-'))drafts[e.target.id.slice(6)]=e.target.value;});
window.addEventListener('resize',()=>{if(run && page==='runs')renderGraph();});
$('create-loop_definition').addEventListener('change',createChanged);
$('create-form').addEventListener('submit',e=>{e.preventDefault();safely(reviewLaunch);});
$('settings-form').addEventListener('submit',e=>{e.preventDefault();safely(async()=>{
  const change={intent:$('intent').value,guidance:$('guidance').value,max_parallel:Number($('parallel').value),constraints:JSON.parse($('constraints').value)};
  if(run.schema_version===2){change.objective=$('objective').value;change.authorization=$('authorization').value;change.requirements=JSON.parse($('requirements').value);change.completion_rule=JSON.parse($('completion-rule').value || 'null');change.termination_signal=$('termination-signal').value;change.bindings=readBindingFields($('run-bindings'));change.fallback_node=$('run-fallback').value || null;change.global_agent_node=$('run-global-agent').value || null;}
  pendingChange={runId:run.id,revision:settingsBase.revision,change};
  const diff=Object.keys(change).filter(k=>pretty(change[k])!==pretty(settingsBase[k]));
  if(!diff.length){toast('没有修改');return;}
  $('change-diff').innerHTML=diff.map(k=>`<h3>${esc(k)}</h3><div class="detail-grid"><div><span class="small muted">Before</span><pre>${esc(pretty(settingsBase[k]))}</pre></div><div><span class="small muted">After</span><pre>${esc(pretty(change[k]))}</pre></div></div>`).join('');
  $('review-dialog').showModal();
});});
async function loadCatalog(){
  [catalog,promptDefaults,lifecycleTemplates]=await Promise.all([api('catalog'),api('agent-prompts'),api('lifecycles')]);
  $('catalog-cards').innerHTML=catalog.map(libraryCard).join('') || '<p class="empty-inline">还没有 Loop。可以导入别人分享的 .loop.zip，或新建自己的Loop 定义。</p>';
  if(typeof loadDraftCards==='function')await loadDraftCards();
  if(typeof loadPreparationCards==='function')await loadPreparationCards();
}
window.addEventListener('DOMContentLoaded',()=>safely(async()=>{
  await readEditAccess();
  await loadCatalog();
  await navigateTo(parseRoute(location.hash),{replace:true});
  await refresh();setInterval(refresh,1500);
}));
