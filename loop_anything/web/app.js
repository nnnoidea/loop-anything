'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = value => JSON.stringify(value, null, 2);

function nodePurposeHTML(node){
  const description=typeof node?.description==='string'?node.description.trim():'';
  if(!description)return '';
  return `<section class="node-purpose"><h3>职责与目的</h3><p>${esc(description)}</p></section>`;
}
// getRandomValues also works on ordinary HTTP inside the team network.
const randomKey = () => Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
const labels = {planned:'已安排',waiting_user:'等待用户',stale:'待核实',continued:'已接续',waiting_configuration:'等待配置',skipped:'已跳过',running:'运行中',ready:'待执行',executing:'执行中',waiting:'等待中',completed:'已完成',paused:'已暂停',terminated:'已终止',cancelled:'已取消',fault:'执行失败',retrying:'等待重试',blocked:'输入未就绪',decision:'等待 Agent',approval:'等待确认',unresolved:'转移待决策'};
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
let progressSignature = '', listSignature = '', inspectSignature = '';
let runHistoryOffset=0, runViewRequest=null, runViewFailure=null;
const runViewTimeout=25000;
const time = t => new Date(t * 1000).toLocaleTimeString('zh-CN', {hour12:false});
const nodeLabel = id => run?.loop_definition.nodes[id]?.label || id;
async function api(url, data, {signal} = {}) {
  const request = data === undefined ? {signal} : {signal,method:'POST',headers:{'Content-Type':'application/json','X-Loop-Anything':'workspace'},body:JSON.stringify(data)};
  const response = await fetch('/api/' + url, request);
  if (!response.ok){
    const result=await response.json().catch(()=>null);
    const error=new Error(result?.error?.message || result?.error || `请求失败（HTTP ${response.status}）`);
    error.status=response.status;
    throw error;
  }
  return response.json();
}
function dismissToast(message){
  if(toast.current!==message)return;
  $('toast').style.display='none';
  toast.current=null;
}
function toast(message,timeout=5500){
  const notice=Symbol();
  toast.current=notice;
  $('toast').textContent=message;
  $('toast').style.display='block';
  clearTimeout(toast.timer);
  if(timeout)toast.timer=setTimeout(()=>dismissToast(notice),timeout);
  return notice;
}
async function safely(fn) { try { await fn(); } catch (error) { toast(error.message); } }
function runWorkspacePath(id,{tab='task-history',task='',offset=0}={}){
  const query=new URLSearchParams({view:'workspace',tab});
  if(task)query.set('task',task);
  if(offset)query.set('offset',offset);
  return 'runs/'+encodeURIComponent(id)+'?'+query;
}
function visibleRunView(){
  return {tab:activeTab,task:activeTab==='task-history'&&taskNeedsDetail(selectedTask)?selectedTask:'',
    offset:activeTab==='activity'?runHistoryOffset:0};
}
async function fetchRunView(path,controller){
  let timedOut=false;
  const timeout=setTimeout(()=>{timedOut=true;controller.abort();},runViewTimeout);
  try{
    return await api(path,undefined,{signal:controller.signal});
  }catch(error){
    if(timedOut)throw new DOMException('读取运行详情超时。','TimeoutError');
    throw error;
  }finally{
    clearTimeout(timeout);
  }
}
function refreshRunWorkspace(){
  if(page!=='runs'||!selected||pendingRunNavigation)return;
  const id=selected,serial=navigationSerial,path=runWorkspacePath(id,visibleRunView());
  if(runViewRequest?.path===path&&runViewRequest.serial===serial&&!runViewRequest.controller.signal.aborted)return runViewRequest.promise;
  runViewRequest?.controller.abort();
  const controller=new AbortController();
  const request={path,serial,controller};
  const current=()=>runViewRequest===request&&serial===navigationSerial&&page==='runs'&&selected===id&&path===runWorkspacePath(id,visibleRunView());
  request.promise=fetchRunView(path,controller).then(value=>{
    if(!current())return;
    runViewFailure=null;
    run=value;renderRun();
  }).catch(async error=>{
    if(!current()||controller.signal.aborted&&error.name!=='TimeoutError')return;
    if(error.status===404){
      run=null;selected=null;await navigateTo({type:'run-list'});return;
    }
    runViewFailure={path,serial,message:error.message};
    renderInspect();
  })
    .finally(()=>{if(runViewRequest===request)runViewRequest=null;});
  runViewRequest=request;
  return request.promise;
}
function showPage() {
  $('settings-page').hidden=page!=='settings';
  $('monitoring-page').hidden=page!=='monitors';
  $('schedules-page').hidden=page!=='schedules';
  $('resources-page').hidden=page!=='resources';
  if($('communication-page'))$('communication-page').hidden=page!=='communication';
  $('workspace').hidden = page !== 'runs' || !run;
  $('runs-page').hidden=page!=='run-list';
  $('timelines-page').hidden=page!=='timelines';
  $('timeline-page').hidden=page!=='timeline';
  const inWork=['timelines','timeline','run-list','runs','monitors','schedules'].includes(page);
  $('workbench-header').hidden=!inWork;
  $('workbench-header').classList.toggle('workbench-detail',page==='timeline'||page==='runs');
  $('workbench-nav').classList.toggle('active',inWork);
  const tab=page==='timeline'?'timelines':['runs','run-list'].includes(page)?'runs':page;
  document.querySelectorAll('[data-work-tab]').forEach(el=>{el.classList.toggle('active',el.dataset.workTab===tab);if(el.dataset.workTab===tab)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  $('plans-page').hidden=page!=='plans';$('plans-nav').classList.toggle('active',page==='plans');
  $('rsi-page').hidden=page!=='rsi';$('loop-parent').hidden=!['catalog','rsi'].includes(page);
  document.querySelectorAll('[data-loop-tab]').forEach(el=>el.classList.toggle('active',el.dataset.loopTab===page));
  $('catalog-page').hidden = page !== 'catalog';
  if($('loop_definition-editor'))$('loop_definition-editor').hidden=page!=='editor';
  if($('loop-detail'))$('loop-detail').hidden=page!=='loop';
  $('loop_definitions-nav').classList.toggle('active', ['catalog','editor','loop','rsi'].includes(page));
  if(typeof updateNavigationUI==='function')updateNavigationUI();

}
async function refresh() {
  if(page==='plans'||page==='rsi')safely(()=>refreshAssignments());
  if(page==='timeline')safely(refreshObservations);
  if(page==='timelines')safely(()=>showWorkLibrary(true));
  if(page==='monitors')refreshMonitoring();
  if(page==='schedules')refreshSchedules();
  if (loading) return;
  loading = true;
  try {
    if(page==='run-list'||page==='communication')await refreshRunLibrary();
    $('engine-status').textContent = '平台已连接';
    if(selected&&page==='runs')await refreshRunWorkspace();
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
  const simulation = run.simulation ?? Object.values(run.implementations).some(entry => Object.values(implementationOptions(entry)).some(b => b.kind === 'mock' || b.simulation));
  $('simulation-label').hidden = !simulation;
  const ended = run.identity_read_only || ['completed','terminated','continued'].includes(run.status);
  $('pause-run').textContent = run.status === 'paused' ? '▷ 恢复' : 'Ⅱ 暂停';
  $('pause-run').hidden = $('stop-run').hidden = Boolean(run.superseded_by);
  $('pause-run').disabled = $('stop-run').disabled = ended;
  const progress=runProgressHTML(run);
  if(progressSignature!==progress){
    const opened=$('run-progress').querySelector('details')?.open && $('run-progress').dataset.run===run.id;
    $('run-progress').innerHTML=progress;progressSignature=progress;$('run-progress').dataset.run=run.id;
    if(opened && $('run-progress').querySelector('details'))$('run-progress').querySelector('details').open=true;
  }
  renderTimelineSettings();
  if (!['TEXTAREA','INPUT','SELECT'].includes(document.activeElement?.tagName) || !document.activeElement.closest('#inspect')) renderInspect();
  loadSettings();
}
function loadSettings(){
  $('run-settings-readonly').innerHTML=`${['running','paused'].includes(run.status)&&!run.superseded_by?'<label><input type="checkbox" id="follow-loop-updates" '+(run.follow_loop_updates?'checked':'')+'> 跟随此 Loop 后续发布的版本</label>':''}<p>目标和限制属于独立 Timeline；修改后由 Agent 检查并向用户汇报。</p>${run.timeline_id?'<button data-work-timeline="'+esc(run.timeline_id)+'">查看 Timeline 与进度</button>':''}${run.settings.objective?`<h3>目标</h3><p>${esc(run.settings.objective)}</p>`:''}${run.settings.constraints?`<h3>限制</h3><p>${esc(run.settings.constraints)}</p>`:''}`;
}
function runViewErrorHTML(message){
  return `<div class="notice run-view-error" role="alert"><span>${esc(message)}</span><button data-retry-run-view>重试</button></div>`;
}
function renderInspect() {
  const wanted=visibleRunView();
  const path=runWorkspacePath(run.id,wanted);
  if(runViewRequest&&(runViewRequest.path!==path||runViewRequest.serial!==navigationSerial))runViewRequest.controller.abort();
  const error=runViewFailure?.path===path&&runViewFailure.serial===navigationSerial?runViewFailure.message:'';
  const ready=!run.workspace_view||Object.keys(wanted).every(key=>run.workspace_view[key]===wanted[key]);
  const signature = pretty([run.id,filterNode,wanted,ready,error,run.executions,run.history,run.history_total,run.changed_tasks,run.settings.revision,run.tasks,run.agent_sessions,run.task_dependencies,run.agent_tasks,run.task_dispositions,run.notifications,run.events,run.hook_firings,run.controls_available]);
  if(inspectSignature===signature)return;inspectSignature=signature;
  const issues=runAttentionItems(run);
  $('run-task-count').textContent=issues.length||'';
  document.querySelectorAll('.run-tabs [data-tab]').forEach(el=>{
    const selected=el.dataset.tab===activeTab;
    el.classList.toggle('selected',selected);
    el.setAttribute('aria-pressed',String(selected));
    if(el.dataset.tab==='tasks')el.hidden=!selected&&!issues.length;
    if(el.dataset.tab==='hooks')el.hidden=!selected&&!run.controls_available;
  });
  const detailError=!ready&&wanted.task?error:'';
  const content=!ready&&activeTab!=='task-history'
    ?(error?'':'<p class="empty-inline" role="status">正在读取…</p>')
    :renderRunPanel(activeTab,issues,detailError);
  $('inspect').innerHTML=(error&&!detailError?runViewErrorHTML(error):'')+content;
  if(!ready&&!error)safely(refreshRunWorkspace);
}

document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button'); if(!button)return;
  if(button.classList.contains('close-dialog')){button.closest('dialog').close();return;}
  const d=button.dataset;
  if(d.run){await selectRun(d.run);return;}
  if(d.node){filterNode=d.node;activeTab='task-history';inspectSignature='';renderInspect();return;}
  if(d.tab){activeTab=d.tab;renderInspect();if(button.closest('#attention'))document.querySelector('.run-tabs').scrollIntoView({block:'start'});return;}
  if(d.retryRunView!==undefined){runViewFailure=null;renderInspect();await refreshRunWorkspace();return;}
  if(d.historyOffset!==undefined){runHistoryOffset=Number(d.historyOffset);renderInspect();return;}
  if(d.validate){const c=catalog.find(x=>x.key===d.validate);const r=await api('validate',c);toast(r.valid?'验证通过 · '+r.warnings.join('；'):r.errors.join('；'));return;}
  const runId=run?.id;
  switch(button.id){
    case 'loop_definitions-nav':await navigateTo({type:'catalog'});break;
    case 'clear-filter':filterNode=null;renderInspect();break;
    case 'node-contract':$('detail-title').textContent=nodeLabel(filterNode)+' · Contract';$('detail-content').innerHTML=`<pre>${esc(pretty(run.loop_definition.nodes[filterNode]))}</pre>`;$('detail-dialog').showModal();break;
    case 'pause-run':await api(`runs/${runId}/command`,{action:run.status==='paused'?'resume':'pause'});await refresh();break;
    case 'stop-run':if(confirm('终止后不会再推进。外部已发生的操作不会被撤销。是否终止？')){await api(`runs/${runId}/command`,{action:'terminate'});await refresh();}break;

  }
}));
document.addEventListener('input',e=>{if(e.target.id.startsWith('result-'))drafts[e.target.id.slice(7)]=e.target.value;if(e.target.id.startsWith('event-'))drafts[e.target.id.slice(6)]=e.target.value;});

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

document.addEventListener('change',event=>{
  if(event.target.id!=='follow-loop-updates'||!run)return;
  const checkbox=event.target,follow=checkbox.checked,id=run.id;
  checkbox.disabled=true;
  safely(async()=>{
    try{await platformCall('submit_run_request',{operation:'follow_loop_updates',request_id:randomKey(),run_id:id,arguments:{follow}});}
    catch(error){checkbox.checked=!follow;throw error;}
    finally{checkbox.disabled=false;await refresh();}
  });
});
