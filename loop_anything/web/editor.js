'use strict';
// The editor produces the same public JSON consumed by the CLI and Engine.
let editor=null, savedDrafts=[], editSelection=null, connectFrom=null, dragState=null, editorSave=null, editorBusy=false, editorOperation=null;
const editorPage=document.createElement('section');editorPage.id='loop_definition-editor';editorPage.hidden=true;
editorPage.innerHTML=`<div class="page-heading editor-top"><div><div class="eyebrow">LOOP</div><h1>查看 Loop</h1><span class="saved-state" id="editor-save-status"></span></div><div class="toolbar"><button type="button" id="reader-agent">交给 Agent 修改</button><details class="editor-more"><summary>更多</summary><div class="editor-more-actions"><button id="editor-json">查看完整定义</button></div></details><button class="primary" id="editor-save">保存</button></div></div>
<div class="editor-layout"><div class="editor-left"><section class="panel"><div id="reader-summary" class="reader-summary"></div><details id="reader-light" class="reader-light"><summary>轻量修改 · 名称、描述与已有默认参数</summary><p class="small muted">只修改此草稿；点击保存后供新运行使用，已有 Run 保持原样。</p><label>Loop 名称<input id="bp-name"></label><label>简短描述<input id="bp-description"></label><div id="author-defaults"></div></details><div class="editor-help"><span id="editor-hint"></span></div><div class="editor-overview-summary" id="editor-overview-summary"></div><div class="editor-view-controls"><button type="button" data-editor-layer="flow">整体流程</button><button type="button" data-editor-layer="nodes">节点详情</button><button type="button" data-editor-layer="states">执行状态机</button><div class="canvas-tools" role="group" aria-label="画布视图"><button type="button" id="canvas-zoom-out" aria-label="缩小画布">−</button><button type="button" id="canvas-zoom-reset">100%</button><button type="button" id="canvas-zoom-in" aria-label="放大画布">＋</button><button type="button" id="canvas-fit">适应全部</button><button type="button" id="canvas-fullscreen">全屏</button></div></div><div id="editor-flow-overview" hidden></div><div id="editor-state-overview" hidden></div><div class="canvas-scroll"><div class="editor-canvas" id="editor-canvas"></div></div><div id="editor-edges-list" class="editor-edge-list"></div><div id="reader-documentation" class="reader-documentation"></div><div class="editor-report" id="editor-report"></div></section></div><aside class="panel editor-right"><div class="panel-heading"><h2 id="property-title">节点详情</h2><button type="button" id="expand-editor-detail" hidden>展开详情 ↗</button></div><div class="editor-properties" id="editor-properties"></div></aside></div>`;
document.querySelector('main').append(editorPage);
editorPage.querySelector('.editor-top').insertAdjacentHTML('beforebegin','<div class="run-navigation"><button id="editor-back">← 返回 Loop 库</button><span>阅读流程与详细配置；复杂修改由 Agent 完成。</span></div>');
const jsonDialog=document.createElement('dialog');jsonDialog.id='editor-json-dialog';jsonDialog.className='editor-json-modal';
jsonDialog.innerHTML=`<div class="dialog-heading"><h2>完整定义与节点实现 · 只读</h2><button class="close-dialog" aria-label="关闭">×</button></div><textarea id="editor-json-value" aria-label="完整 Loop 定义 JSON" readonly></textarea><div class="dialog-tasks"><button id="editor-export">下载 JSON</button></div>`;
document.body.append(jsonDialog);

async function loadDraftCards(){
  savedDrafts=await api('drafts');
  $('draft-cards').innerHTML=savedDrafts.length?`<section class="panel draft-list"><h2>草稿</h2>${savedDrafts.map(d=>`<div class="draft-row"><div>${esc(d.loop_definition.name || d.loop_definition.id || '未命名Loop 定义')}<small>revision ${d.revision} · ${new Date(d.updated_at*1000).toLocaleString('zh-CN')}</small></div><button data-open-draft="${esc(d.id)}">查看 Loop →</button></div>`).join('')}</section>`:'';
}
async function platformCall(tool,values={}){
  const result=await api('tools',{tool,arguments:values});
  if(!result.ok)throw new Error(result.error?.message || '操作失败');
  return result;
}
async function newLoopDefinition(source=null,versionOnly=false){
  if(source && source.loop_definition.schema_version!==2)throw new Error('历史 Loop 定义仅供查看');
  if(page==='editor')await saveEditor();
  if(source&&versionOnly){
    const drafts=await api('drafts');
    const reusable=drafts.find(d=>d.loop_definition.id===source.loop_definition.id&&!catalog.some(c=>c.loop_definition.id===d.loop_definition.id&&c.loop_definition.version===d.loop_definition.version));
    if(reusable){editor={...reusable,dirty:false};await openEditor();return true;}
  }
  if(source&&versionOnly){const status=await api('edit-access?loop_id='+encodeURIComponent(source.loop_definition.id));if(!status.unlocked){await navigateTo({type:'loop',key:source.key});toast('请先解锁这个 Loop 的编辑口令');return false;}}
  const result=source?await platformCall('copy_loop',{key:source.key,new_version:versionOnly}):await platformCall('create_loop',{name:'我的新 Loop'});
  const loaded=(await platformCall('read_loop',{draft_id:result.draft_id})).loop;
  editor={...loaded,dirty:false};
  await openEditor();
}
async function editWithTool(tool,values){
  if(editorLocked())throw new Error('请先解锁这个 Loop 的编辑口令');
  if(editorOperation)await editorOperation;
  const operation=performEditorEdit(tool,values);editorOperation=operation;
  try{return await operation;}finally{if(editorOperation===operation)editorOperation=null;}
}
async function performEditorEdit(tool,values){
  clearTimeout(dirty.timer);editorBusy=true;editorPage.inert=true;
  try{
    await saveEditor();
    const result=await platformCall(tool,{draft_id:editor.id,revision:editor.revision,...values});
    const loaded=(await platformCall('read_loop',{draft_id:result.draft_id})).loop;
    Object.assign(editor,loaded,{dirty:false});
    populateMeta();renderEditor();renderProperties();renderReport(result.validation);saveState();
  }finally{editorBusy=false;editorPage.inert=false;}
}

function openEditor(){
  if(editor.loop_definition.schema_version!==2)throw new Error('历史Loop 定义仅供查看');
  const id=registerEditor();
  return navigateTo({type:'editor',id},{capture:false});
}
function populateMeta(){
  const b=editor.loop_definition;
  if(!b.plans?.[authorPlan])authorPlan=Object.keys(b.plans||{})[0]||'default';
  $('bp-name').value=b.name||'';$('bp-description').value=b.description||'';delete $('bp-name').dataset.lightChanged;delete $('bp-description').dataset.lightChanged;
  $('author-defaults').innerHTML=lightDefaultsHTML(b);
  renderReaderSummary();
  $('reader-documentation').innerHTML=readerDocumentsHTML(editor);
}
function renderReaderSummary(){
  const b=editor.loop_definition;
  $('reader-summary').innerHTML=`<h2>${esc(b.name||b.id)}</h2><p>${esc(b.description||'尚未填写简介')}</p><small>${esc(b.id)} · 版本 ${esc(b.version)}</small>`;
}
function collectMeta(){
  const b=editor.loop_definition;
  if($('bp-name').dataset.lightChanged)b.name=$('bp-name').value;
  if($('bp-description').dataset.lightChanged)b.description=$('bp-description').value;
  collectLightDefaults(b,$('author-defaults'));
}
function saveState(){ $('editor-save-status').innerHTML=editor.dirty?'正在保存草稿…':editor.savedRevision===editor.revision?`已保存 · ${navLink({type:'loop',key:editor.savedKey,tab:'overview'},'查看 Loop')}`:`草稿已保存 · revision ${editor.revision}`; }
function dirty(){
  delete editor.validation;editor.dirty=true;editor.edits=(editor.edits||0)+1;saveState();
  $('editor-report').className='editor-report';$('editor-report').textContent='修改自动保留为草稿；点击保存时检查并更新可用版本。';
  clearTimeout(dirty.timer);const target=editor;
  dirty.timer=setTimeout(()=>{if(page==='editor'&&editor===target&&!editorBusy)saveEditor().catch(e=>{$('editor-save-status').textContent='尚未保存 · '+e.message;});},650);
}
function editorColumns(){return Math.max(1,Math.min(5,Math.floor((($('editor-canvas').parentElement.clientWidth||900)-90)/250)));}
function ensurePositions(){editor.viewPositions=Object.fromEntries(loopNodePositions({...editor.loop_definition,layout:editor.viewPositions||editor.loop_definition.layout},{rowGap:420,maxColumns:editorColumns()}));}
function renderEditor(){
  renderReaderSummary();
  const b=editor.loop_definition;ensurePositions();const canvas=$('editor-canvas');canvas.style.zoom=editor.canvasZoom||1;updateCanvasControls();
  const positions=Object.values(editor.viewPositions);
  canvas.style.width=Math.max(750,...positions.map(p=>(Number(p.x)||0)+225))+'px';
  canvas.style.height=Math.max(500,...positions.map(p=>(Number(p.y)||0)+185))+'px';
  canvas.innerHTML=Object.entries(b.nodes).map(([id,n])=>{
    const p=editor.viewPositions[id],kind=chosenImplementation(editor,id)?.kind || '未选用';
    return `<article class="editor-node ${editSelection?.node===id?'picked':''} ${connectFrom?'connect-target':''}" data-editor-card="${esc(id)}" style="left:${p.x}px;top:${p.y}px"><div class="editor-node-head" data-drag-node="${esc(id)}" role="button" tabindex="0" aria-label="查看节点 ${esc(n.label || id)}"><span class="node-icon">${kind==='agent'?'✧':['event','timer','approval'].includes(kind)?'◷':'▤'}</span>${esc(n.label || id)}</div><div class="editor-node-id">${esc(id)}</div><p class="editor-node-purpose" title="${esc(n.instructions)}">${esc(n.instructions)}</p>${nodeSignalsHTML(editor,id,chosenImplementation(editor,id))}${editorNodeIssues(id)}${authorPortButtons(id,n)}${editorNodeImplementations(id)}<div class="editor-node-footer"><span>${b.entry===id?'入口 · ':b.fallback_node===id?'兜底 · ':''}${esc(kindNames[kind]||kind)}</span><button data-editor-node="${esc(id)}">查看详情 ↗</button></div></article>`;
  }).join('') || '<div class="canvas-empty"><div class="empty-mark">◇</div><h2>从第一个业务步骤开始</h2><p>请让 Agent 根据你的目标构建节点与流程。</p></div>';
  $('editor-overview-summary').innerHTML=`<span>${Object.keys(b.nodes).length} 个节点 · ${Object.values(b.nodes).reduce((n,v)=>n+Object.keys(v.inputs||{}).length,0)} 个输入端口</span><small>节点配置、整体流程与执行规则分开查看。</small>`;
  $('editor-flow-overview').innerHTML=overviewFlowHTML(editor,editorPage.querySelector('.editor-left').clientWidth);renderEditorStateOverview();
  $('editor-edges-list').innerHTML=readerPlansHTML(b);
  setEditorLayer(editor.viewLayer||'flow');applyEditorLock();

}

function sizeEditorCanvas(){
  const canvas=$('editor-canvas');canvas.querySelector('svg')?.remove();if(canvas.parentElement.hidden||!canvas.offsetWidth)return;
  canvas.style.width=Math.max(canvas.parentElement.clientWidth/(editor.canvasZoom||1),750,...[...canvas.querySelectorAll('.editor-node')].map(card=>card.offsetLeft+card.offsetWidth+70))+'px';
  canvas.style.height=Math.max(500,...[...canvas.querySelectorAll('.editor-node')].map(card=>card.offsetTop+card.offsetHeight+70))+'px';
}

function editorNodeIssues(id){
  const gaps=nodeInputRows(editor.loop_definition,id).filter(r=>r.missing),issues=(editor.validation?.issues||[]).filter(i=>['nodes','implementations'].includes(i.path?.[0])&&i.path[1]===id);
  return gaps.length||issues.length?`<button type="button" class="node-config-gap" data-editor-node="${esc(id)}">${gaps.length?gaps.length+' 个输入待连接':esc(issues[0].message)}</button>`:'';
}
function editorNodeImplementations(id){
  const entry=editor.implementations[id],options=implementationOptions(entry),chosen=defaultImplementation(entry);
  return `<div class="editor-node-implementations"><small>实现方案 · ${Object.keys(options).length}${chosen?'':' · 尚未选用'}</small><div>${Object.entries(options).map(([key,c])=>`<button type="button" class="${key===chosen?'chosen':''}" data-editor-node="${esc(id)}" data-editor-implementation="${esc(key)}" title="${esc(executionLabel(c))} · 查看执行方式、处理规则与通知">${esc(c.label||key)}${key===chosen?'<small>默认</small>':''} ↗</button>`).join('')||`<button type="button" data-editor-node="${esc(id)}">查看待补充信息</button>`}</div></div>`;
}

function renderEditorDetail(){
  const route=activeRoute,node=route.node&&editor.loop_definition.nodes[route.node],implementation=route.implementation;
  editorPage.classList.toggle('editor-detail-page',!!node);editorPage.classList.toggle('editor-implementation-page',!!node&&!!implementation);
  $('expand-editor-detail').hidden=!!node||!editSelection?.node;
  editorPage.querySelector('.editor-top h1').textContent=node?(node.label||route.node)+(implementation?' · '+implementation:''):'查看 Loop';
  editorPage.querySelector('.editor-top .eyebrow').textContent=implementation?'实现详情':node?'节点详情':'LOOP';
  $('editor-detail-path')?.remove();
  const report=$('editor-report');(node?editorPage.querySelector('.editor-right .panel-heading'):$('reader-documentation')).after(report);
  if(editor.validation)renderReport(editor.validation);else{report.className='editor-report';report.textContent='查看与切换方案不会修改定义。轻量修改保存后供新运行使用。';}
  if(node){const base={type:'editor',id:editor.routeId};editorPage.querySelector('.editor-layout').insertAdjacentHTML('beforebegin',`<div id="editor-detail-path">${navLink(base,'← 返回 Loop')}<span>/</span>${navLink({...base,node:route.node},node.label||route.node)}${implementation?'<span>/</span><strong>'+esc(implementation)+'</strong>':''}</div>`);}
}
function renderProperties(){renderAuthorProperties();renderEditorDetail();applyEditorLock();}
function collectAll(){if(editorLocked())return;collectMeta();}
function selectEditor(selection){if(activeRoute.node&&selection.node!==activeRoute.node){safely(async()=>{if(await navigateTo({type:'editor',id:editor.routeId,...(selection.node?{node:selection.node}:{})})&&selection.edge)selectEditor(selection);});return;}collectAll();editSelection=selection;connectFrom=null;renderEditor();renderProperties();}
async function saveEditor(){
  clearTimeout(dirty.timer);const target=editor;
  if(editorSave)await editorSave;
  if(editor!==target)throw new Error('编辑页面已切换，请重新读取当前草稿。');
  if(target.id&&!target.dirty)return;
  collectAll();const edits=target.edits||0;
  const payload=structuredClone({id:target.id,revision:target.revision,loop_definition:target.loop_definition,implementations:target.implementations,assets:target.assets||[],checks:target.checks||{}});
  const saving=api('drafts',payload);editorSave=saving;
  try{
    const result=await saving;Object.assign(target,{id:result.id,revision:result.revision,dirty:(target.edits||0)!==edits});
    if(editor===target&&page==='editor'){const route=parseRoute(location.hash);if(route.type==='editor'&&route.id===target.routeId)savedEditorRoute();saveState();}
    if(!target.dirty){target.loop_definition.records=result.loop_definition.records;if(editor===target&&page==='editor'){const report=await platformCall('validate_loop',{draft_id:target.id});if(editor===target&&page==='editor'&&!target.dirty&&target.revision===result.revision){renderReport(report);renderEditor();}}}
    return result;
  }finally{if(editorSave===saving)editorSave=null;}
}
async function saveLoop(){
  if(editorBusy)return;editorBusy=true;editorPage.inert=true;
  try{
    await saveEditor();const report=await platformCall('validate_loop',{draft_id:editor.id});renderReport(report);if(!report.valid)return;
    const result=await platformCall('publish_loop',{draft_id:editor.id,revision:editor.revision,auto_version:true});
    editor.revision=result.revision;editor.loop_definition.version=result.version;editor.dirty=false;
    editor.savedRevision=result.revision;editor.savedKey=result.key;
    if(editor.returnTo?.type==='loop')editor.returnTo.key=result.key;
    await loadCatalog();saveState();updateNavigationUI();toast('已保存，新运行将使用此版本。');
  }finally{editorBusy=false;editorPage.inert=false;}
}

async function locateEditorIssue(path){
  const id=path[0]==='seed'?editor.loop_definition.entry:path[1];
  if(['nodes','implementations','seed'].includes(path[0])&&editor.loop_definition.nodes[id]){await navigateTo({type:'editor',id:editor.routeId,node:id});return;}
  if(path[0]==='plans'){await navigateTo({type:'editor',id:editor.routeId});setEditorLayer('flow');$('editor-edges-list').scrollIntoView({block:'center'});return;}
  toast('完整定义中可查看此项，请将问题交给 Agent 修正。');
}
function renderReport(report){
  if(editor)editor.validation=report;
  const r=$('editor-report');r.className='editor-report '+(report.valid?'success':'failure');
  r.innerHTML=`<strong>${report.valid?'✓ 结构有效':'需要修正'}</strong>`+(report.issues?.length?report.issues.map(issue=>`<p>${esc(issue.message)} <button type="button" data-input-location="${esc(JSON.stringify(issue.path))}">查看位置</button></p>`).join(''):report.errors.map(x=>`<p>• ${esc(x)}</p>`).join(''))+((report.unbound_nodes || []).length?`<p>待绑定：${report.unbound_nodes.map(esc).join('、')}。仍可导出、分享和安装；不表示已具备运行条件。</p>`:'')+report.warnings.map(x=>`<p class="small">${esc(x)}</p>`).join('');
}
document.addEventListener('click',event=>safely(async()=>{
  const el=event.target.closest('button,[data-edit-edge]');if(!el)return;const d=el.dataset;
  if(d.editorNode){await navigateTo({type:'editor',id:editor.routeId,node:d.editorNode,...(d.editorImplementation?{implementation:d.editorImplementation}:{})});return;}
  if(el.id==='expand-editor-detail'&&editSelection?.node){await navigateTo({type:'editor',id:editor.routeId,node:editSelection.node});return;}
  if(d.inputLocation){await locateEditorIssue(JSON.parse(d.inputLocation));return;}
  if(d.copyLoopDefinition || d.versionLoopDefinition){await newLoopDefinition(catalog.find(c=>c.key===(d.copyLoopDefinition || d.versionLoopDefinition)),!!d.versionLoopDefinition);return;}
  if(d.openDraft){if(page==='editor')await saveEditor();editor={...structuredClone(savedDrafts.find(x=>x.id===d.openDraft)),dirty:false};openEditor();return;}
  switch(el.id){

    case 'new-loop_definition':showReaderAgentHelp();break;
    case 'editor-save':await saveLoop();break;
    case 'editor-json':el.closest('details').open=false;collectAll();$('editor-json-value').value=pretty({loop_definition:editor.loop_definition,implementations:editor.implementations});jsonDialog.showModal();applyEditorLock();break;
    case 'editor-export':{const content=$('editor-json-value').value;JSON.parse(content);const url=URL.createObjectURL(new Blob([content],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=(editor.loop_definition.id || 'loop_definition')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);break;}
  }
}));
editorPage.addEventListener('submit',e=>{e.preventDefault();safely(async()=>{await saveEditor();renderEditor();});});
editorPage.addEventListener('input',event=>{if(editor&&!event.target.closest('[data-editor-view-only]'))dirty();});
editorPage.addEventListener('pointerdown',e=>{
  const head=e.target.closest('[data-drag-node]');if(!head || e.button!==0)return;
  const id=head.dataset.dragNode;
  try{collectAll();}catch(error){toast(error.message);return;}
  editSelection={node:id};renderProperties();
  editorPage.querySelectorAll('.editor-node').forEach(c=>c.classList.toggle('picked',c.dataset.editorCard===id));
  if(editorLocked())return;
  const p=editor.viewPositions[id];dragState={id,x:e.clientX,y:e.clientY,startX:p.x,startY:p.y,moved:false};head.setPointerCapture(e.pointerId);
});
editorPage.addEventListener('pointermove',e=>{
  if(!dragState)return;const d=dragState;
  if(Math.abs(e.clientX-d.x)+Math.abs(e.clientY-d.y)<4)return;
  d.moved=true;const p=editor.viewPositions[d.id];p.x=Math.max(10,Math.round(d.startX+(e.clientX-d.x)/(editor.canvasZoom||1)));p.y=Math.max(20,Math.round(d.startY+(e.clientY-d.y)/(editor.canvasZoom||1)));
  const card=[...editorPage.querySelectorAll('.editor-node')].find(c=>c.dataset.editorCard===d.id);card.style.left=p.x+'px';card.style.top=p.y+'px';sizeEditorCanvas();
});
function endDrag(){if(!dragState)return;const moved=dragState.moved;dragState=null;renderEditor();}
editorPage.addEventListener('pointerup',endDrag);editorPage.addEventListener('pointercancel',endDrag);
editorPage.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&document.fullscreenElement===editorPage)safely(()=>document.exitFullscreen());
  if(e.key==='Escape' && connectFrom){connectFrom=null;renderEditor();}
  if(e.key==='Enter' && e.target.dataset.dragNode)safely(async()=>{selectEditor({node:e.target.dataset.dragNode});});
});
window.addEventListener('beforeunload',e=>{if(editor?.dirty || [...editorSessions.values()].some(s=>s.editor.dirty)){e.preventDefault();e.returnValue='';}});

function renderEditorStateOverview(){
  const ids=Object.keys(editor.loop_definition.nodes);
  if(!ids.includes(editor.stateNode))editor.stateNode=editSelection?.node||editor.loop_definition.entry||ids[0];
  const id=editor.stateNode,options=implementationOptions(editor.implementations[id]);
  if(!Object.hasOwn(options,editor.stateImplementation))editor.stateImplementation=defaultImplementation(editor.implementations[id])||Object.keys(options)[0];
  const selected=editor.stateImplementation,config=options[selected];
  $('editor-state-overview').innerHTML=`<div class="state-view-picker" data-editor-view-only><label>节点<select id="editor-state-node">${ids.map(key=>`<option value="${esc(key)}" ${key===id?'selected':''}>${esc(editor.loop_definition.nodes[key].label||key)}</option>`).join('')}</select></label><label>实现方案<select id="editor-state-implementation">${Object.entries(options).map(([key,value])=>`<option value="${esc(key)}" ${key===selected?'selected':''}>${esc(value.label||key)}</option>`).join('')}</select></label>${config?`<button type="button" data-editor-node="${esc(id)}" data-editor-implementation="${esc(selected)}">查看此实现 ↗</button>`:''}</div><p class="view-description">查看所选实现的一次执行：状态、报告事件、判断条件及处理动作。切换查看不会修改默认实现。</p>${config?nodeSignalsHTML(editor,id,config)+lifecycleMatrix(config,undefined,true):'<p class="muted">该节点尚未配置实现。</p>'}`;
}
function setEditorLayer(layer){
  if(!editor)return;
  if(layer==='relations')layer='nodes';
  editor.viewLayer=layer;editorPage.dataset.editorView=layer;
  editorPage.classList.toggle('editor-flow-editing',layer==='flow'&&!!editSelection?.edge);
  if(layer==='flow')$('editor-flow-overview').innerHTML=overviewFlowHTML(editor,editorPage.querySelector('.editor-left').clientWidth);
  editorPage.querySelectorAll('.canvas-tools button:not(#canvas-fullscreen)').forEach(b=>b.hidden=layer!=='nodes');
  $('editor-flow-overview').hidden=layer!=='flow';$('editor-state-overview').hidden=layer!=='states';
  $('editor-canvas').parentElement.hidden=layer!=='nodes';$('editor-edges-list').hidden=layer!=='flow';
  $('editor-hint').textContent={nodes:'选择节点查看职责、输入输出、Skill 和实现方案',flow:'概览主要步骤与分支；下方可查看任务模板与参数映射',states:'选择节点与实现，查看完整状态图和逐条转移规则'}[layer];
  editorPage.querySelectorAll('[data-editor-layer]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.editorLayer===layer)));
  requestAnimationFrame(sizeEditorCanvas);
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-editor-layer]');if(b){collectAll();connectFrom=null;portConnection=null;setEditorLayer(b.dataset.editorLayer);renderProperties();if(b.dataset.editorLayer==='states')renderEditorStateOverview();}});
document.addEventListener('change',e=>{
  if(!editor||!['editor-state-node','editor-state-implementation'].includes(e.target.id))return;
  if(e.target.id==='editor-state-node'){editor.stateNode=e.target.value;delete editor.stateImplementation;}
  else editor.stateImplementation=e.target.value;
  renderEditorStateOverview();
});

function updateCanvasControls(){
  const zoom=editor?.canvasZoom||1;
  $('canvas-zoom-reset').textContent=Math.round(zoom*100)+'%';
  $('canvas-zoom-out').disabled=zoom<=.1;$('canvas-zoom-in').disabled=zoom>=2;
  $('canvas-fullscreen').textContent=document.fullscreenElement===editorPage?'退出全屏':'全屏';
  $('canvas-fullscreen').hidden=!document.fullscreenEnabled;
}
function zoomEditorCanvas(value,center){
  if(!editor)return;const canvas=$('editor-canvas'),pane=canvas.parentElement,old=editor.canvasZoom||1;
  center ||= {x:(pane.scrollLeft+pane.clientWidth/2)/old,y:(pane.scrollTop+pane.clientHeight/2)/old};
  const zoom=Math.max(.1,Math.min(2,value));editor.canvasZoom=zoom;canvas.style.zoom=zoom;
  sizeEditorCanvas();updateCanvasControls();pane.scrollTo(center.x*zoom-pane.clientWidth/2,center.y*zoom-pane.clientHeight/2);
}
function fitEditorCanvas(){
  const canvas=$('editor-canvas'),pane=canvas.parentElement,cards=[...canvas.querySelectorAll('.editor-node')];if(!cards.length){zoomEditorCanvas(1);return;}
  const left=Math.min(...cards.map(c=>c.offsetLeft)),top=Math.min(...cards.map(c=>c.offsetTop)),right=Math.max(...cards.map(c=>c.offsetLeft+c.offsetWidth)),bottom=Math.max(...cards.map(c=>c.offsetTop+c.offsetHeight));
  zoomEditorCanvas(Math.min(1,(pane.clientWidth-48)/(right-left),(pane.clientHeight-48)/(bottom-top)),{x:(left+right)/2,y:(top+bottom)/2});
}
document.addEventListener('click',event=>{
  const button=event.target.closest('.canvas-tools button');if(!button)return;
  if(button.id==='canvas-fit')fitEditorCanvas();
  else if(button.id==='canvas-fullscreen')safely(async()=>{if(document.fullscreenElement===editorPage)await document.exitFullscreen();else await editorPage.requestFullscreen();});
  else zoomEditorCanvas(button.id==='canvas-zoom-reset'?1:Math.round(((editor.canvasZoom||1)+(button.id==='canvas-zoom-in' ? .1 : -.1))*100)/100);
});
document.addEventListener('fullscreenchange',()=>{updateCanvasControls();if(page==='editor')requestAnimationFrame(sizeEditorCanvas);});
