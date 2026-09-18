'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = value => JSON.stringify(value, null, 2);
const labels = {skipped:'已跳过',running:'运行中',ready:'待执行',executing:'执行中',waiting:'等待外部',completed:'已完成',paused:'已暂停',terminated:'已终止',cancelled:'已取消',fault:'执行失败',blocked:'输入未就绪',decision:'等待 Agent',approval:'等待确认',unresolved:'转移待决策'};
const badge = status => `<span class="badge ${esc(status)}">${esc(labels[status] || status)}</span>`;
let catalog = [], runs = [], run = null, selected = null, filterNode = null, activeTab = 'task-history', page = 'runs', settingsBase = null, pendingChange = null, loading = false;
const drafts = {};
let listSignature = '', graphSignature = '', inspectSignature = '';
const time = t => new Date(t * 1000).toLocaleTimeString('zh-CN', {hour12:false});
const nodeLabel = id => run?.loop_definition.nodes[id]?.label || id;
async function api(url, data) {
  const response = await fetch('/api/' + url, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Loop-Anything':'workspace'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}
function toast(message) { $('toast').textContent = message; $('toast').style.display = 'block'; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').style.display = 'none', 5500); }
async function safely(fn) { try { await fn(); } catch (error) { toast(error.message); } }
function showPage() {
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
    $('engine-status').textContent = 'Engine connected';
    const listHTML = runs.map(r => `<button class="run-item ${selected === r.id ? 'chosen' : ''}" data-run="${esc(r.id)}"><strong>${esc(r.title)}</strong><small>${esc(labels[r.status])} · ${r.executions.length} executions</small></button>`).join('');
    if(listSignature !== listHTML){$('run-list').innerHTML=listHTML;listSignature=listHTML;}
    if (!selected && runs.length) selected = runs[0].id;
    if (selected && page==='runs') { const id=selected,current=await api('runs/' + id);if(page==='runs' && selected===id){run=current;renderRun();} }
    const platform=await api('platform'),power=platform.keep_awake;
    $('platform-power').className='platform-power '+(power.active?'protected':'unprotected');
    $('platform-power').textContent=power.active?'平台运行中 · 已启用防休眠保护':power.requested?'防休眠保护未生效 · '+(power.error || '请检查系统支持'):'平台运行中 · 当前允许系统休眠';
    showPage();
  } catch (error) { $('engine-status').textContent = '连接中断 · 自动重连';$('platform-power').className='platform-power unprotected';$('platform-power').textContent='与平台连接中断 · 无法确认运行及防休眠状态'; }
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
  $('settings-revision').textContent = 'rev ' + run.settings.revision + (settingsBase.revision !== run.settings.revision ? ' · 表单已过期' : '');
}
function renderGraph() {
  const signature = pretty([run.id,filterNode,run.executions,Object.values(run.tasks || {}).map(w=>[w.id,w.status]),[],$('graph').clientWidth]);
  if(graphSignature===signature)return;graphSignature=signature;
  $('graph').innerHTML = Object.entries(run.loop_definition.nodes).map(([id,node]) => {
    const executions = run.executions.filter(e=>e.node === id), live = executions.filter(e=>!['completed','cancelled'].includes(e.status));
    const latest = executions.at(-1);
    const implementation=chosenImplementation(run,id,run.settings.bindings || {}) || {};
    const kind = implementation.kind || '未选用';
    return `<button class="node ${live.length?'active-node':''} ${filterNode===id?'selected-node':''}" data-node="${esc(id)}"><div class="node-heading"><span class="node-icon">${kind==='agent'?'✧':kind==='event'?'◷':kind==='approval'?'✓':'▤'}</span>${esc(node.label || id)}</div><small>${esc(id)} · ${esc(kind)}${implementation.simulation ? ' / simulated' : ''}</small><div class="node-state">${latest?badge(latest.status):run.schema_version===2?(Object.values(run.tasks).some(w=>w.spec.node===id)?'已安排，尚未派发':'未安排 Task'):'尚未执行'} <span>${executions.length ? `${live.length} active / ${executions.length} total` : ''}</span></div></button>`;
  }).join('');
  let edges = loop_definitionEdges(run.loop_definition);
  $('graph-caption').innerHTML = '<div class="edge-list">' + edges.map(e=>`<span title="${esc(pretty(e))}">${esc(e.from)} → ${esc(e.to)}${e.each?' · fan-out':e.join?' · join':''}${e.when?' · '+esc(e.when.path)+'='+esc(e.when.equals):''}</span>`).join('')+'</div>';
  if(run.schema_version===2)$('graph-caption').insertAdjacentHTML('afterbegin','<p>图中是Loop 定义模板及其默认依赖，不代表本轮全部执行。实际安排与输入就绪状态请看 Tasks；Engine 不会补建省略的步骤。</p>');
  if(run.schema_version===2)$('graph-caption').insertAdjacentHTML('beforeend',`<p>未覆盖状态：${run.settings.fallback_node?'进入兜底节点 '+esc(nodeLabel(run.settings.fallback_node)):'保留问题，未启用 Agent 兜底'}</p>`);
  const cards = [...$('graph').querySelectorAll('.node')];
  const columns = getComputedStyle($('graph')).gridTemplateColumns.split(' ').length;
  cards.forEach((card,i)=>{card.style.gridRow=String(Math.floor(i/columns)+1);card.style.gridColumn=String(Math.floor(i/columns)%2 ? columns-i%columns : i%columns+1);});
  requestAnimationFrame(()=>drawEdges(edges));
}
function drawEdges(edges) {
  const graph=$('graph');if(!graph.offsetWidth)return;
  graph.querySelector('svg')?.remove();
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
  svg.classList.add('graph-edges');svg.setAttribute('width',graph.clientWidth);svg.setAttribute('height',graph.clientHeight);svg.setAttribute('aria-hidden','true');
  svg.innerHTML='<defs><marker id="edge-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="#9cadd0"/></marker></defs>';
  const cards=new Map([...graph.querySelectorAll('.node')].map(c=>[c.dataset.node,c]));
  for(const edge of edges){
    const a=cards.get(edge.from),b=cards.get(edge.to);if(!a||!b)continue;
    const ax=a.offsetLeft,ay=a.offsetTop,aw=a.offsetWidth,ah=a.offsetHeight,bx=b.offsetLeft,by=b.offsetTop,bw=b.offsetWidth,bh=b.offsetHeight;
    let d;
    if(a===b){d=`M ${ax+aw*.3} ${ay} C ${ax+aw*.3} ${ay-23}, ${ax+aw*.7} ${ay-23}, ${ax+aw*.7} ${ay}`;}
    else if(ay===by){const forward=bx>ax,sx=forward?ax+aw:ax,tx=forward?bx:bx+bw;d=`M ${sx} ${ay+ah/2} L ${tx} ${by+bh/2}`;}
    else if(ax===bx){const down=by>ay;d=`M ${ax+aw/2} ${down?ay+ah:ay} L ${bx+bw/2} ${down?by:by+bh}`;}
    else {const down=by>ay,sy=down?ay+ah:ay,ty=down?by:by+bh,my=(sy+ty)/2;d=`M ${ax+aw/2} ${sy} L ${ax+aw/2} ${my} L ${bx+bw/2} ${my} L ${bx+bw/2} ${ty}`;}
    const line=document.createElementNS(ns,'path');line.setAttribute('d',d);line.setAttribute('fill','none');line.setAttribute('stroke','#9cadd0');line.setAttribute('stroke-width','1.5');line.setAttribute('marker-end','url(#edge-arrow)');if(edge.join)line.setAttribute('stroke-dasharray','4 3');svg.appendChild(line);
  }
  graph.prepend(svg);
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
  $('detail-content').innerHTML=`${badge(e.status)} <span class="mono">attempt ${e.attempt} · settings r${e.settings_revision}</span>${e.error?`<pre>${esc(e.error)}</pre>`:''}<div class="detail-section"><h3>创建原因</h3><p class="small">${esc(cause)} · ${esc(e.task_id || '')}</p></div><div class="detail-grid"><div><h3>Resolved inputs</h3><pre>${esc(pretty(e.inputs))}</pre></div><div><h3>Committed outputs</h3><pre>${esc(pretty(e.outputs || null))}</pre></div></div><div class="detail-section"><h3>Input provenance</h3><pre>${esc(pretty(e.sources))}</pre></div><div class="detail-section"><h3>Handler / external task</h3><pre>${esc(pretty({implementation:e.implementation,external_id:e.external_id,wake_at:e.wake_at?new Date(e.wake_at*1000).toLocaleString():undefined}))}</pre></div>${run.tasks?.[e.task_id]?.execution_id===e.id && ['fault','blocked'].includes(e.status)&&!e.routed?`<button data-retry="${esc(e.id)}">重试此执行</button><p class="field-note">先检查外部任务是否已经产生副作用，避免重复提交。</p>`:''}`;
  if(!$('detail-dialog').open)$('detail-dialog').showModal();
}
function openCreate(key) {
  if(!catalog.length){navigateTo({type:'catalog'});toast('先导入一个 Loop，或新建 Loop。');return;}
  $('create-loop_definition').innerHTML=catalog.map(c=>`<option value="${esc(c.key)}">${esc(c.loop_definition.name || c.key)} · ${esc(c.key)}</option>`).join('');
  if(key)$('create-loop_definition').value=key;
  createChanged(); $('create-dialog').showModal();
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
  if(button.classList.contains('close-dialog')){button.closest('dialog').close();return;}
  const d=button.dataset;
  if(d.run){await selectRun(d.run);return;}
  if(d.node){filterNode=d.node;activeTab=run.schema_version===2?'task-history':'executions';inspectSignature='';renderGraph();renderInspect();return;}
  if(d.tab){activeTab=d.tab;renderInspect();return;}
  if(d.exec){if(run.schema_version===2){selectedTask=run.executions.find(e=>e.id===d.exec)?.task_id;selectedAttempt=d.exec;activeTab='task-history';inspectSignature='';renderInspect();}else details(d.exec);return;}
  if(d.create){openCreate(d.create);return;}
  if(d.validate){const c=catalog.find(x=>x.key===d.validate);const r=await api('validate',c);toast(r.valid?'验证通过 · '+r.warnings.join('；'):r.errors.join('；'));return;}
  const runId=run?.id;
  if(d.retry){await api(`runs/${runId}/command`,{action:'retry',execution_id:d.retry});$('detail-dialog').close();await refresh();return;}
  if(d.result){
    const e=run.executions.find(x=>x.id===d.result);
    const payload={execution_id:e.id,token:e.token,envelope:JSON.parse($('result-'+e.id).value)};
    await api(`runs/${runId}/submit`,payload);toast('结果已提交');await refresh();return;
  }
  if(d.sendEvent){const e=run.executions.find(x=>x.id===d.sendEvent);await api(`runs/${runId}/event`,{event_id:crypto.randomUUID(),name:e.implementation.event,key:e.parameters?.event_key,payload:JSON.parse($('event-'+e.id).value)});toast('事件已持久化');await refresh();return;}
  switch(button.id){
    case 'new-run':openCreate();break;
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
  catalog=await api('catalog');
  $('catalog-cards').innerHTML=catalog.map(libraryCard).join('') || '<p class="empty-inline">还没有 Loop。可以导入别人分享的 .loop.zip，或新建自己的Loop 定义。</p>';
  if(typeof loadDraftCards==='function')await loadDraftCards();
}
window.addEventListener('DOMContentLoaded',()=>safely(async()=>{
  await loadCatalog();
  await navigateTo(parseRoute(location.hash),{replace:true});
  await refresh();setInterval(refresh,1500);
}));
