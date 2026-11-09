'use strict';
// Read-only Loop viewer. Drafts and installed versions share the same detail surface.
let editor=null, savedDrafts=[], editSelection=null;
const editorPage=document.createElement('section');editorPage.id='loop_definition-editor';editorPage.hidden=true;
editorPage.innerHTML=`<div class="run-navigation"><button id="editor-back">← 返回 Loop 库</button><span>流程、规则与文件 · 只读</span></div>
<div class="editor-layout"><div class="editor-left"><section class="panel"><header class="reader-summary"><div class="reader-heading"><div class="reader-identity"><h1 id="reader-title"></h1><small id="reader-version"></small></div><div class="toolbar reader-actions" role="group" aria-label="Loop 操作"><button type="button" id="reader-refresh">刷新</button><button type="button" id="reader-start" hidden>启动</button><details class="editor-more"><summary>更多</summary><div class="editor-more-actions"><button id="editor-json">查看完整定义</button><button id="reader-check">环境检查</button></div></details></div></div><p id="reader-description"></p></header><div class="editor-help"><span id="editor-hint"></span></div><div class="editor-overview-summary" id="editor-overview-summary"></div><div class="editor-view-controls"><strong class="flow-view-title">整体流程</strong><div class="canvas-tools" role="group" aria-label="画布视图"><button type="button" id="canvas-fullscreen">全屏</button></div></div><div id="editor-flow-overview"></div><div id="editor-edges-list" class="editor-edge-list"></div><div id="reader-documentation" class="reader-documentation"></div><div class="editor-report" id="editor-report"></div></section></div><aside class="panel editor-right" aria-label="节点信息与状态转移" tabindex="-1"><div class="editor-inspector-heading"><div class="panel-heading"><h2 id="property-title">节点详情</h2><button type="button" id="close-editor-detail" aria-label="关闭节点侧栏">×</button></div><div class="editor-detail-tabs" role="group" aria-label="节点查看方式"><button type="button" data-editor-detail="info" aria-pressed="true" aria-controls="editor-properties">节点信息</button><button type="button" data-editor-detail="states" aria-pressed="false" aria-controls="editor-node-states">状态转移</button></div></div><div class="editor-properties" id="editor-properties"></div><div id="editor-node-states" class="editor-properties" hidden></div></aside></div>`;
document.querySelector('main').append(editorPage);
const jsonDialog=document.createElement('dialog');jsonDialog.id='editor-json-dialog';jsonDialog.className='editor-json-modal';
jsonDialog.innerHTML=`<div class="dialog-heading"><h2>完整定义与节点实现 · 只读</h2><button class="close-dialog" aria-label="关闭">×</button></div><textarea id="editor-json-value" aria-label="完整 Loop 定义 JSON" readonly></textarea><div class="dialog-tasks"><button id="editor-export">下载 JSON</button></div>`;
document.body.append(jsonDialog);

async function loadDraftCards(){
  savedDrafts=await api('drafts?include_archived='+String(!!$('show-archived-loops')?.checked));
  $('draft-cards').innerHTML=savedDrafts.length?`<section class="panel draft-list"><h2>草稿</h2>${savedDrafts.map(d=>`<div class="draft-row"><div>${esc(d.loop_definition.name || d.loop_definition.id || '未命名Loop 定义')}<small>${d.archived_at?'已归档 · ':''}revision ${d.revision} · ${new Date(d.updated_at*1000).toLocaleString('zh-CN')}</small></div><button data-open-draft="${esc(d.id)}">查看 Loop →</button></div>`).join('')}</section>`:'';
}
async function platformCall(tool,values={}){
  const result=await api('tools',{tool,arguments:values});
  if(!result.ok)throw new Error(result.error?.message || '操作失败');
  return result;
}
async function loadReader(id){
  const installed=catalog.find(item=>item.key===id);
  const isDraft=!installed&&id.startsWith('draft-');
  const result=await platformCall('read_loop',isDraft?{draft_id:id}:{key:id});
  const item=result.loop,packageKey=item.package_key||installed?.package_key;
  const content=packageKey?await api('packages/read',{key:packageKey}):null;
  return {...item,...(content?{assets:content.assets,checks:content.document.checks}:{}),installedKey:isDraft?undefined:id,routeId:id,returnTo:{type:'catalog'}};
}
function readerIdentity(item=editor){return item.installedKey?{key:item.installedKey}:{draft_id:item.id};}
function openEditor(){return navigateTo({type:'editor',id:registerEditor()},{capture:false});}
function populateMeta(){
  renderReaderSummary();$('reader-documentation').innerHTML=readerDocumentsHTML(editor)+(editor.installedKey?'<div id="reader-runs">'+relatedRunsHTML(editor.installedKey)+'</div>':'');
  $('reader-start').hidden=$('reader-check').hidden=!editor.installedKey;
  if($('loop-config-template'))$('loop-config-template').textContent=editor.installedKey?'运行配置文件':'运行配置模板';
}
function renderReaderSummary(){
  const b=editor.loop_definition;
  $('reader-title').textContent=b.name||b.id;
  $('reader-version').textContent=`${b.id} · 版本 ${b.version}${editor.installedKey?'':` · 草稿 r${editor.revision}`}`;
  $('reader-description').textContent=b.description||'';
  $('reader-description').hidden=!b.description;
}
function renderEditor(){
  renderReaderSummary();
  const b=editor.loop_definition;
  $('editor-overview-summary').innerHTML=`<span>${Object.keys(b.nodes).length} 个节点 · ${Object.values(b.nodes).reduce((n,v)=>n+Object.keys(v.inputs||{}).length,0)} 个输入端口</span><small>点击流程节点，在侧栏查看节点信息与状态转移。</small>`;
  $('editor-flow-overview').innerHTML=overviewFlowHTML(editor);
  $('editor-flow-overview').querySelector('iframe')?.addEventListener('load',syncOverviewSelection);
  $('editor-edges-list').innerHTML=readerPlansHTML(b);
  $('editor-hint').textContent='选择流程节点，查看职责、实现及状态规则；切换查看不会修改 Loop。';
  updateCanvasControls();
}
function syncOverviewSelection(){
  $('editor-flow-overview').querySelector('iframe')?.contentWindow.postMessage({type:'loop-node-selected',node:editSelection?.node||null},'*');
}
function renderEditorDetail(){
  editorPage.classList.toggle('has-node-detail',!!editSelection?.node);
  syncOverviewSelection();
  if(editor.validation)renderReport(editor.validation);
  else{$('editor-report').className='editor-report';$('editor-report').textContent='';}
}
function renderProperties(){
  renderAuthorProperties();renderEditorDetail();
  renderEditorNodeStates();setEditorDetailTab(editor.detailTab||'info');
}
function selectEditor(selection){return navigateTo({type:'editor',id:editor.routeId,...(selection.node?{node:selection.node}:{})});}
window.addEventListener('message',event=>{
  if(page!=='editor'||!editor)return;
  const id=overviewNodeMessage(event,$('editor-flow-overview').querySelector('iframe'),editor.loop_definition.nodes);
  if(id!==null)safely(()=>selectEditor({node:id}));
});
async function locateEditorIssue(path){
  const id=path[0]==='seed'?editor.loop_definition.entry:path[1];
  if(['nodes','implementations','seed'].includes(path[0])&&editor.loop_definition.nodes[id]){await navigateTo({type:'editor',id:editor.routeId,node:id});return;}
  if(path[0]==='plans'){await navigateTo({type:'editor',id:editor.routeId});$('editor-edges-list').scrollIntoView({block:'center'});return;}
  toast('完整定义中可查看此项，请将问题交给 Agent 修正。');
}
function renderReport(report){
  if(editor)editor.validation=report;
  const r=$('editor-report');r.className='editor-report '+(report.valid?'success':'failure');
  r.innerHTML=`<strong>${report.valid?'✓ 结构有效':'需要修正'}</strong>`+(report.issues?.length?report.issues.map(issue=>`<p>${esc(issue.message)} <button type="button" data-input-location="${esc(JSON.stringify(issue.path))}">查看位置</button></p>`).join(''):report.errors.map(x=>`<p>• ${esc(x)}</p>`).join(''))+((report.unbound_nodes || []).length?`<p>待绑定：${report.unbound_nodes.map(esc).join('、')}。仍可导出、分享和安装；不表示已具备运行条件。</p>`:'')+report.warnings.map(x=>`<p class="small">${esc(x)}</p>`).join('');
}
document.addEventListener('click',event=>safely(async()=>{
  const el=event.target.closest('button,[data-edit-edge]');if(!el)return;const d=el.dataset;
  if(d.editorNode){el.closest('dialog')?.close();if(d.editorDetail)editor.detailTab=d.editorDetail;await navigateTo({type:'editor',id:editor.routeId,node:d.editorNode,...(d.editorImplementation?{implementation:d.editorImplementation}:{})});return;}
  if(el.id==='close-editor-detail'){await selectEditor({});return;}
  if(d.inputLocation){await locateEditorIssue(JSON.parse(d.inputLocation));return;}
  if(d.openDraft){await navigateTo({type:'editor',id:d.openDraft});return;}
  switch(el.id){

    case 'reader-refresh':{const id=editor.routeId,tab=editor.detailTab;editor=await loadReader(id);editor.detailTab=tab;editorSessions.set(id,{editor,selection:editSelection});if(editSelection?.node&&!editor.loop_definition.nodes[editSelection.node])editSelection=null;populateMeta();renderEditor();renderProperties();break;}
    case 'reader-start':await openCreate(editor.installedKey);break;
    case 'reader-check':{el.closest('details').open=false;const report=await api('packages/smoke',{key:editor.installedKey});preflightCache.set(editor.installedKey,report);readerCheckDialog.innerHTML='<div class="dialog-heading"><h2>环境检查 · 只读</h2><button class="close-dialog">×</button></div>'+checkHTML(report);readerCheckDialog.showModal();break;}
    case 'editor-json':el.closest('details').open=false;$('editor-json-value').value=pretty({loop_definition:editor.loop_definition,implementations:editor.implementations});jsonDialog.showModal();break;
    case 'editor-export':{const content=$('editor-json-value').value;JSON.parse(content);const url=URL.createObjectURL(new Blob([content],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=(editor.loop_definition.id || 'loop_definition')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);break;}
  }
}));
function renderEditorNodeStates(){
  const id=editSelection?.node;
  $('editor-node-states').innerHTML=id?nodeStateInspectorHTML(editor,id,activeRoute.implementation):'';
}
function setEditorDetailTab(tab){
  if(!editor)return;
  tab=tab==='states'?'states':'info';editor.detailTab=tab;
  $('editor-properties').hidden=tab!=='info';$('editor-node-states').hidden=tab!=='states';
  editorPage.querySelectorAll('[data-editor-detail]').forEach(b=>{
    if(!b.dataset.editorNode)b.setAttribute('aria-pressed',String(b.dataset.editorDetail===tab));
  });
}
document.addEventListener('click',event=>{
  const b=event.target.closest('.editor-detail-tabs [data-editor-detail]');if(!b)return;
  setEditorDetailTab(b.dataset.editorDetail);editorPage.querySelector('.editor-right').scrollTop=0;
});

function updateCanvasControls(){
  $('canvas-fullscreen').textContent=document.fullscreenElement===editorPage?'退出全屏':'全屏';
  $('canvas-fullscreen').hidden=!document.fullscreenEnabled;
}
document.addEventListener('click',event=>{
  if(event.target.closest('#canvas-fullscreen'))safely(async()=>{if(document.fullscreenElement===editorPage)await document.exitFullscreen();else await editorPage.requestFullscreen();});
});
document.addEventListener('fullscreenchange',updateCanvasControls);

const readerCheckDialog=document.createElement("dialog");readerCheckDialog.className="editor-json-modal";document.body.append(readerCheckDialog);
