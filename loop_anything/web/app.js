'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = value => JSON.stringify(value, null, 2);
// getRandomValues also works on ordinary HTTP inside the team network.
const randomKey = () => Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
const labels = {waiting_configuration:'等待配置',skipped:'已跳过',running:'运行中',ready:'待执行',executing:'执行中',waiting:'等待中',completed:'已完成',paused:'已暂停',terminated:'已终止',cancelled:'已取消',fault:'执行失败',retrying:'等待重试',blocked:'输入未就绪',decision:'等待 Agent',approval:'等待确认',unresolved:'转移待决策'};
const badge = status => `<span class="badge ${esc(status)}">${esc(labels[status] || status)}</span>`;
let catalog = [], runs = [], run = null, selected = null, filterNode = null, activeTab = 'task-history', page = 'runs', settingsBase = null, pendingChange = null, loading = false;
const drafts = {};
let powerPending=false,lastPower=null;
function renderPower(power){
  lastPower=power;
  $('platform-power').className='platform-power '+(power.active?'protected':'unprotected');
  $('platform-power-status').textContent=power.updating?(power.requested?'正在启用防休眠保护…':'正在关闭防休眠保护…'):power.error?'防休眠设置未生效 · '+power.error:power.active?'平台运行中 · 已启用防休眠保护':'平台运行中 · 当前允许系统休眠';
  $('platform-power-switch').checked=power.requested;
  $('platform-power-switch').disabled=powerPending||power.updating||!power.controllable;
  $('platform-power-switch').title='作用于平台所在机器；选择会保留，重启后仍有效';
}
$('platform-power-switch').onchange=()=>safely(async()=>{
  const enabled=$('platform-power-switch').checked;powerPending=true;$('platform-power-switch').disabled=true;
  try{renderPower(await api('platform/keep-awake',{enabled}));}
  finally{powerPending=false;await refresh();}
});
let promptDefaults={};
function promptHistory(record){return record&&Object.hasOwn(record,'prompt_text')?`<details class="prompt-history"><summary>本次唤醒提示词</summary><p class="small muted">实际发送记录 · 平台令牌已遮蔽</p><pre>${esc(record.prompt_text)}</pre></details>`:'';}
let listSignature = '', graphSignature = '', inspectSignature = '';
const time = t => new Date(t * 1000).toLocaleTimeString('zh-CN', {hour12:false});
const nodeLabel = id => run?.loop_definition.nodes[id]?.label || id;
async function api(url, data) {
  const response = await fetch('/api/' + url, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Loop-Anything':'workspace'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok){const error=new Error(result.error?.message || result.error || '请求失败');error.status=response.status;throw error;}
  return result;
}
function toast(message) { $('toast').textContent = message; $('toast').style.display = 'block'; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').style.display = 'none', 5500); }
async function safely(fn) { try { await fn(); } catch (error) { toast(error.message); } }
function showPage() {
  $('schedules-page').hidden=page!=='schedules';
  $('schedules-nav').classList.toggle('active',page==='schedules');
  if($('communication-page'))$('communication-page').hidden=page!=='communication';
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
  if(page==='schedules')refreshSchedules();
  if (loading) return;
  loading = true;
  try {
    await refreshRunLibrary();
    $('engine-status').textContent = 'Engine connected';
    if (!selected && runs.length) selected = runs[0].id;
    if (selected && page==='runs') { const id=selected;try{const current=await api('runs/' + id);if(page==='runs' && selected===id){run=current;renderRun();}}catch(error){if(error.status===404&&selected===id){run=null;selected=null;}else throw error;} }
    const platform=await api('platform'),power=platform.keep_awake;
    if(!$('platform-version'))document.querySelector('.topbar').insertAdjacentHTML('beforeend','<small id="platform-version" class="muted"></small>');
    document.querySelector('.brand .version').textContent=platform.service?platform.service.version:'';
    $('platform-version').textContent=platform.service?`v${platform.service.version} · ${platform.service.build}${platform.service.restart_required?' · 源码已更新，服务需重启':''}`:'服务未提供版本信息';
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
  renderRunOutlet();
  $('run-key').textContent = (run.loop_definition.name || run.loop_definition.id) + ' · v' + run.loop_definition.version;
  $('run-status').innerHTML = badge(run.status)+(run.identity_read_only?' · 只读历史副本，不接管原执行':'');
  $('run-id').textContent = run.id+' · '+(run.created_by||'未署名')+(run.archived_at?' · 已归档':'');
  if($('archive-run'))$('archive-run').textContent=run.archived_at?'取消归档':'归档';
  const simulation = Object.values(run.implementations).some(entry => Object.values(implementationOptions(entry)).some(b => b.kind === 'mock' || b.simulation));
  $('simulation-label').hidden = !simulation;
  const ended = run.identity_read_only || run.schema_version!==2 || !run.operator_protocol || ['completed','terminated'].includes(run.status);
  $('pause-run').textContent = run.status === 'paused' ? '▷ 恢复' : 'Ⅱ 暂停';
  $('pause-run').disabled = $('stop-run').disabled = ended;
  const counts = {};
  run.executions.forEach(e => counts[e.status] = (counts[e.status] || 0) + 1);
  $('metrics').innerHTML = [['执行记录',run.executions.length,'total'],['已提交结果',counts.completed || 0,'committed'],['等待 / 执行中',(counts.waiting || 0) + (counts.executing || 0),'active'],['Agent 调用',run.executions.filter(e => e.implementation.kind === 'agent').length,'on demand']].map(([title,n,unit])=>`<div class="metric"><div><label>${title}</label><div><small>${unit}</small></div></div><b>${n}</b></div>`).join('');
  const tasks = run.schema_version===2 ? (run.agent_tasks?.items || []) : [];
  $('attention').innerHTML = tasks.length ? `<div class="notice">当前 ${tasks.length} 项节点任务或异常，请在「任务与问题」查看。</div>` : '';

  if(run.schema_version===2)renderTimelineSettings();
  else {document.querySelectorAll('.v2-tab').forEach(b=>b.hidden=true);if(['records','task-history','hooks','tasks'].includes(activeTab))activeTab='executions';}
  document.querySelector('[data-tab="executions"]').hidden=run.schema_version===2;
  renderGraph();
  if (!['TEXTAREA','INPUT','SELECT'].includes(document.activeElement?.tagName) || !document.activeElement.closest('#inspect')) renderInspect();
  loadSettings();
}
function renderGraph() {
  const signature = pretty([run.id,filterNode,run.settings,run.executions,Object.values(run.tasks || {}).map(w=>[w.id,w.status]),[],$('graph').clientWidth]);
  if(graphSignature===signature)return;graphSignature=signature;
  const old=$('graph').querySelector('.loop-map'),keep=old?.dataset.runId===run.id&&old.dataset.filterNode===(filterNode||'');
  const focus=keep?old.dataset.mapFocus:filterNode,view=keep?old.dataset.mapView:'execution',layer=keep?old.dataset.graphLayer:'relations';
  $('graph').innerHTML=loopGraphHTML(run,{bindings:run.settings.bindings || {},focus:focus || '',action:'run'});
  const root=$('graph').querySelector('.loop-map');
  if(root){setGraphLayer(root,layer);root.dataset.runId=run.id;root.dataset.filterNode=filterNode||'';if(focus&&Object.hasOwn(run.loop_definition.nodes,focus))focusLoopMap(root,focus,view);}
  $('graph-caption').textContent='循环关系来自 Loop 定义；上方运行过程保留每一项实际任务、结果与历次执行。';
}
function loadSettings(){
  $('run-settings-readonly').innerHTML=`<p>目标、约束与后续安排由运行 Agent 更新；Loop 定义修改使用独立的构建 Agent 或源文件。</p>${readerJSON('目标与要求',{intent:run.settings.intent,objective:run.settings.objective,requirements:run.settings.requirements,guidance:run.settings.guidance},true)}${readerJSON('完整运行配置',run.settings)}`;
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
    const waiting = run.executions.filter(e=>e.status==='waiting' && e.implementation.kind==='event');
    content += waiting.map(e=>`<div class="task-card"><h2>等待 ${esc(e.implementation.event)}</h2>${waitDetails(e)}</div>`).join('');
    if(!content) content = '<div class="empty-inline">当前无需决策。Engine 会在到达决策节点时创建任务。</div>';
  }
  $('inspect').innerHTML = content;
}
function task(e) {
  return `<div class="task-card"><h2>${esc(nodeLabel(e.node))}</h2>${waitDetails(e)}${readerJSON('输入',e.inputs,true)}${readerJSON('结果与执行记录',e)}</div>`;
}

function details(id) {
  const e = run.executions.find(x=>x.id===id); if(!e)return;
  $('detail-title').textContent=nodeLabel(e.node)+' · '+e.id;
  const origin=run.tasks?.[e.task_id]?.origin;
  const cause=origin?.fallback?'进入兜底节点':origin?.entry?'入口任务':origin?.route_id?'事件触发 · '+origin.route_id:origin?.agent?'Agent 安排':origin?.execution?'脚本安排':origin?.user?'用户安排':'历史记录';
  $('detail-content').innerHTML=`${badge(e.status)} <span class="mono">attempt ${e.attempt} · settings r${e.settings_revision}</span>${e.error?`<pre>${esc(e.error)}</pre>`:''}${promptHistory(e)}<div class="detail-section"><h3>创建原因</h3><p class="small">${esc(cause)} · ${esc(e.task_id || '')}</p></div><div class="detail-grid"><div><h3>Resolved inputs</h3><pre>${esc(pretty(e.inputs))}</pre></div><div><h3>Committed outputs</h3><pre>${esc(pretty(e.outputs || null))}</pre></div></div><div class="detail-section"><h3>Input provenance</h3><pre>${esc(pretty(e.sources))}</pre></div><div class="detail-section"><h3>Handler / external task</h3><pre>${esc(pretty({implementation:e.implementation,external_id:e.external_id,wake_at:e.wake_at?new Date(e.wake_at*1000).toLocaleString():undefined}))}</pre></div>${run.tasks?.[e.task_id]?.execution_id===e.id && ['fault','blocked'].includes(e.status)&&!e.routed?`<button data-retry="${esc(e.id)}">重试此执行</button><p class="field-note">先检查外部任务是否已经产生副作用，避免重复提交。</p>`:''}`;
  if(!$('detail-dialog').open)$('detail-dialog').showModal();
}
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button,[data-exec]'); if(!button)return;
  if(button.classList.contains('close-dialog')){button.closest('dialog').close();return;}
  const d=button.dataset;
  if(d.run){await selectRun(d.run);return;}
  if(d.node){filterNode=d.node;activeTab=run.schema_version===2?'task-history':'executions';inspectSignature='';renderGraph();renderInspect();return;}
  if(d.tab){activeTab=d.tab;renderInspect();return;}
  if(d.exec){if(run.schema_version===2){selectedTask=run.executions.find(e=>e.id===d.exec)?.task_id;selectedAttempt=d.exec;activeTab='task-history';inspectSignature='';renderInspect();}else details(d.exec);return;}
  if(d.create){await openCreate(d.create);return;}
  if(d.validate){const c=catalog.find(x=>x.key===d.validate);const r=await api('validate',c);toast(r.valid?'验证通过 · '+r.warnings.join('；'):r.errors.join('；'));return;}
  const runId=run?.id;
  if(d.retry){await api(`runs/${runId}/command`,{action:'retry',execution_id:d.retry});$('detail-dialog').close();await refresh();return;}
  switch(button.id){
    case 'new-run':await openCreate();break;
    case 'empty-create':await navigateTo({type:'catalog'});break;
    case 'loop_definitions-nav':await navigateTo({type:'catalog'});break;
    case 'clear-filter':filterNode=null;renderGraph();renderInspect();break;
    case 'node-contract':$('detail-title').textContent=nodeLabel(filterNode)+' · Contract';$('detail-content').innerHTML=`<pre>${esc(pretty(run.loop_definition.nodes[filterNode]))}</pre>`;$('detail-dialog').showModal();break;
    case 'pause-run':await api(`runs/${runId}/command`,{action:run.status==='paused'?'resume':'pause'});await refresh();break;
    case 'stop-run':if(confirm('终止后不会再推进。外部已发生的操作不会被撤销。是否终止？')){await api(`runs/${runId}/command`,{action:'terminate'});await refresh();}break;

  }
}));
document.addEventListener('keydown',e=>{if(e.key==='Enter' && e.target.matches('tr[data-exec]'))details(e.target.dataset.exec);});
document.addEventListener('input',e=>{if(e.target.id.startsWith('result-'))drafts[e.target.id.slice(7)]=e.target.value;if(e.target.id.startsWith('event-'))drafts[e.target.id.slice(6)]=e.target.value;});
window.addEventListener('resize',()=>{if(run && page==='runs')renderGraph();});
async function loadCatalog(){
  [catalog,promptDefaults,lifecycleTemplates]=await Promise.all([api('catalog?include_archived='+String(!!$('show-archived-loops')?.checked)),api('agent-prompts'),api('lifecycles')]);
  $('catalog-cards').innerHTML=catalog.map(libraryCard).join('') || '<p class="empty-inline">还没有 Loop。可以导入 .loop.zip，或通过构建 Agent 添加。</p>';
  if(typeof loadDraftCards==='function')await loadDraftCards();
}
window.addEventListener('DOMContentLoaded',()=>safely(async()=>{
  await loadCatalog();
  await navigateTo(parseRoute(location.hash),{replace:true});
  await refresh();setInterval(refresh,1500);
}));
