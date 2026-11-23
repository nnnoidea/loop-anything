'use strict';
// Read-only Loop viewer. Drafts and installed versions share the same detail surface.
let editor=null, savedDrafts=[], editSelection=null;
const editorPage=document.createElement('section');editorPage.id='loop_definition-editor';editorPage.hidden=true;
editorPage.innerHTML=`
<div class="editor-layout">
  <div class="editor-left">
    <section class="panel">
      <header class="reader-summary">
        <div class="reader-heading">
          <h1 id="reader-title"></h1>
          <button type="button" id="open-loop-model-settings" class="reader-model-action" aria-label="模型设置" aria-describedby="reader-default-model" hidden>
            <span>模型设置</span><small id="reader-default-model"></small>
          </button>
        </div>
        <p id="reader-description"></p>
      </header>
      <section class="reader-flow" aria-labelledby="reader-flow-title">
        <div class="editor-view-controls" id="reader-flow-heading">
          <h2 id="reader-flow-title" class="flow-view-title">流程</h2>
          <div id="reader-flow-tools" class="reader-flow-tools" role="group" aria-label="流程图查看" hidden>
            <button type="button" id="reader-flow-zoom-out" aria-label="缩小流程图" title="缩小">−</button>
            <button type="button" id="reader-flow-zoom-reset" aria-label="恢复原始大小" title="恢复原始大小">100%</button>
            <button type="button" id="reader-flow-zoom-in" aria-label="放大流程图" title="放大">+</button>
            <button type="button" id="reader-flow-fullscreen">全屏</button>
          </div>
        </div>
        <div id="editor-flow-overview"></div>
      </section>
      <div id="reader-runs" class="reader-runs" hidden></div>
      <details id="reader-technical">
        <summary>技术资料</summary>
        <div class="reader-technical-body">
          <p id="reader-version" class="small muted"></p>
          <div class="toolbar reader-technical-actions">
            <button type="button" id="editor-json">查看完整定义</button>
            <button type="button" id="loop-config-template">运行配置文件</button>
            <button type="button" id="reader-check">环境检查</button>
            <button type="button" id="loop-package">下载与导入</button>
            <button type="button" id="reader-refresh">重新读取</button>
          </div>
          <div id="editor-edges-list" class="editor-edge-list"></div>
          <div id="reader-documentation" class="reader-documentation"></div>
          <div id="editor-report" class="editor-report"></div>
        </div>
      </details>
    </section>
  </div>
  <aside class="panel editor-right" aria-label="节点信息与状态转移" tabindex="-1">
    <div class="editor-inspector-heading">
      <div class="panel-heading"><h2 id="property-title">节点详情</h2><button type="button" id="close-editor-detail" aria-label="关闭节点侧栏">×</button></div>
      <div class="editor-detail-tabs" role="group" aria-label="节点查看方式">
        <button type="button" data-editor-detail="info" aria-pressed="true" aria-controls="editor-properties">节点信息</button>
        <button type="button" data-editor-detail="states" aria-pressed="false" aria-controls="editor-node-states">状态转移</button>
      </div>
    </div>
    <div class="editor-properties" id="editor-properties"></div>
    <div id="editor-node-states" class="editor-properties" hidden></div>
  </aside>
</div>`;
const editorHome=document.querySelector('main');
editorHome.append(editorPage);
const readerFlowDialog=document.createElement('dialog');
readerFlowDialog.id='reader-flow-dialog';
readerFlowDialog.setAttribute('aria-labelledby','reader-flow-title');
document.body.append(readerFlowDialog);
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
  const [content,models]=packageKey?await Promise.all([
    api('packages/read',{key:packageKey}),
    platformCall('read_loop_models',{key:id}).catch(error=>({error:error.message}))
  ]):[null,null];
  return {...item,...(content?{assets:content.assets,checks:content.document.checks}:{}),models,installedKey:isDraft?undefined:id,routeId:id,returnTo:{type:'catalog'}};
}
function readerIdentity(item=editor){return item.installedKey?{key:item.installedKey}:{draft_id:item.id};}
function openEditor(){return navigateTo({type:'editor',id:registerEditor()},{capture:false});}
function populateMeta(){
  renderReaderSummary();
  const technical=$('reader-technical');
  if(technical.dataset.loop!==editor.routeId)technical.open=false;
  technical.dataset.loop=editor.routeId;
  $('reader-documentation').innerHTML=readerDocumentsHTML(editor);
  $('reader-runs').hidden=$('reader-check').hidden=!editor.installedKey;
  if(!editor.installedKey){$('reader-runs').replaceChildren();delete $('reader-runs').dataset.signature;}
  $('loop-config-template').textContent=editor.installedKey?'运行配置文件':'运行配置模板';
}
function renderReaderSummary(){
  const b=editor.loop_definition;
  $('reader-title').textContent=b.name||b.id;
  $('reader-version').textContent=`${b.id} · 版本 ${b.version}${editor.installedKey?'':` · 草稿 r${editor.revision}`}`;
  const purpose=b.guide?.purpose||b.description||'';
  $('reader-description').textContent=purpose;
  $('reader-description').hidden=!purpose;
  renderLoopModelSummary(editor);
}
function renderEditor(){
  renderReaderSummary();
  const b=editor.loop_definition;
  const overview=$('editor-flow-overview');
  overview.innerHTML=overviewFlowHTML(editor);
  const frame=overview.querySelector('iframe');
  overview.classList.toggle('has-authored-flow',!!frame);
  $('reader-flow-title').textContent=frame?'流程':'节点';
  $('reader-flow-tools').hidden=!frame;
  if(frame){
    setReaderFlowHeight(frame,editor.overviewHeight||Number(frame.height));
    setReaderFlowZoom(editor.overviewZoom??1);
    frame.addEventListener('load',syncOverviewSelection);
  }
  $('editor-edges-list').innerHTML=readerPlansHTML(b);
}
function setReaderFlowHeight(frame,height){
  editor.overviewHeight=height;
  frame.height=height;
  frame.parentElement.style.setProperty('--flow-height',height+'px');
}
function readerFlowOffset(){
  const heading=$('reader-flow-heading').getBoundingClientRect();
  const flow=$('editor-flow-overview').getBoundingClientRect();
  return Math.max(0,heading.bottom-flow.top);
}
function setReaderFlowZoom(requested){
  const previous=editor.overviewZoom??1;
  const zoom=Math.max(.5,Math.min(2,requested));
  const offset=zoom===previous?0:readerFlowOffset();
  editor.overviewZoom=zoom;
  $('editor-flow-overview').style.setProperty('--flow-zoom',zoom);
  const reset=$('reader-flow-zoom-reset');
  reset.textContent=Math.round(zoom*100)+'%';
  reset.setAttribute('aria-label','恢复原始大小，当前 '+reset.textContent);
  $('reader-flow-zoom-out').disabled=zoom===.5;
  $('reader-flow-zoom-in').disabled=zoom===2;
  if(offset){
    const scroll=readerFlowDialog.open?readerFlowDialog:window;
    scroll.scrollBy({top:offset*(zoom/previous-1),behavior:'instant'});
  }
}
let readerFlowPageTop=0;
function setReaderFlowFullscreen(open,restorePosition=true){
  const button=$('reader-flow-fullscreen');
  if(open){
    const offset=readerFlowOffset();
    readerFlowPageTop=window.scrollY;
    button.textContent='退出全屏';
    readerFlowDialog.append(editorPage);
    readerFlowDialog.showModal();
    readerFlowDialog.scrollTop=offset;
    button.focus({preventScroll:true});
  }else{
    button.textContent='全屏';
    editorHome.append(editorPage);
    readerFlowDialog.close();
    if(!restorePosition)return;
    window.scrollTo({top:readerFlowPageTop,behavior:'instant'});
    button.focus({preventScroll:true});
  }
}
readerFlowDialog.addEventListener('cancel',event=>{
  event.preventDefault();
  setReaderFlowFullscreen(false);
});
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
function selectEditor(selection){
  editor.detailTab='info';
  return navigateTo({type:'editor',id:editor.routeId,...(selection.node?{node:selection.node}:{})});
}
window.addEventListener('message',event=>{
  if(page!=='editor'||!editor)return;
  const frame=$('editor-flow-overview').querySelector('iframe');
  const height=overviewHeightMessage(event,frame);
  if(height!==null){
    setReaderFlowHeight(frame,height);
    return;
  }
  const id=overviewNodeMessage(event,frame,editor.loop_definition.nodes);
  if(id!==null)safely(()=>selectEditor({node:id}));
});
async function locateEditorIssue(path){
  const id=path[0]==='seed'?editor.loop_definition.entry:path[1];
  if(['nodes','implementations','seed'].includes(path[0])&&editor.loop_definition.nodes[id]){await navigateTo({type:'editor',id:editor.routeId,node:id});return;}
  if(path[0]==='plans'){await navigateTo({type:'editor',id:editor.routeId});$('reader-technical').open=true;$('editor-edges-list').scrollIntoView({block:'center'});return;}
  toast('完整定义中可查看此项，请将问题交给 Agent 修正。');
}
function renderReport(report){
  if(editor)editor.validation=report;
  const r=$('editor-report');r.className='editor-report '+(report.valid?'success':'failure');
  r.innerHTML=`<strong>${report.valid?'✓ 结构有效':'需要修正'}</strong>`+(report.issues?.length?report.issues.map(issue=>`<p>${esc(issue.message)} <button type="button" data-input-location="${esc(JSON.stringify(issue.path))}">查看位置</button></p>`).join(''):report.errors.map(x=>`<p>• ${esc(x)}</p>`).join(''))+((report.unbound_nodes || []).length?`<p>待绑定：${report.unbound_nodes.map(esc).join('、')}。仍可导出、分享和安装；不表示已具备运行条件。</p>`:'')+report.warnings.map(x=>`<p class="small">${esc(x)}</p>`).join('');
}
document.addEventListener('click',event=>safely(async()=>{
  const el=event.target.closest('button,[data-edit-edge]');if(!el)return;const d=el.dataset;
  if(d.editorNode){el.closest('dialog')?.close();editor.detailTab=d.editorDetail||'info';await navigateTo({type:'editor',id:editor.routeId,node:d.editorNode,...(d.editorImplementation?{implementation:d.editorImplementation}:{})});return;}
  if(el.id==='close-editor-detail'){await selectEditor({});return;}
  if(d.inputLocation){await locateEditorIssue(JSON.parse(d.inputLocation));return;}
  if(d.openDraft){await navigateTo({type:'editor',id:d.openDraft});return;}
  switch(el.id){
    case 'reader-flow-zoom-out':setReaderFlowZoom(editor.overviewZoom-.25);break;
    case 'reader-flow-zoom-in':setReaderFlowZoom(editor.overviewZoom+.25);break;
    case 'reader-flow-zoom-reset':setReaderFlowZoom(1);break;
    case 'reader-flow-fullscreen':setReaderFlowFullscreen(!readerFlowDialog.open);break;
    case 'reader-refresh':{const id=editor.routeId,tab=editor.detailTab;editor=await loadReader(id);editor.detailTab=tab;editorSessions.set(id,{editor,selection:editSelection});if(editSelection?.node&&!editor.loop_definition.nodes[editSelection.node])editSelection=null;populateMeta();renderEditor();renderProperties();break;}
    case 'reader-check':{const report=await api('packages/smoke',{key:editor.installedKey});preflightCache.set(editor.installedKey,report);readerCheckDialog.innerHTML='<div class="dialog-heading"><h2>环境检查 · 只读</h2><button class="close-dialog">×</button></div>'+checkHTML(report);readerCheckDialog.showModal();break;}
    case 'editor-json':$('editor-json-value').value=pretty({loop_definition:editor.loop_definition,implementations:editor.implementations});jsonDialog.showModal();break;
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

const readerCheckDialog=document.createElement("dialog");readerCheckDialog.className="editor-json-modal";document.body.append(readerCheckDialog);
