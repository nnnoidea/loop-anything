'use strict';
// The editor produces the same public JSON consumed by the CLI and Engine.
let editor=null, savedDrafts=[], editSelection=null, connectFrom=null, dragState=null, editorSave=null, editorBusy=false, editorOperation=null;
const editorPage=document.createElement('section');editorPage.id='loop_definition-editor';editorPage.hidden=true;
editorPage.innerHTML=`<div class="page-heading editor-top"><div><div class="eyebrow">LOOP EDITOR</div><h1>设计你的 Loop</h1><span class="saved-state" id="editor-save-status">未保存的草稿</span></div><div class="toolbar"><button id="editor-json">JSON</button><button class="primary" id="editor-publish">保存并使用</button></div></div>
<div class="editor-layout"><div class="editor-left"><section class="panel"><div class="editor-settings"><label>Loop 名称<input id="bp-name" placeholder="例如：每日质量巡检"></label><details class="editor-identity"><summary>标识与版本 · 自动管理</summary><label>Loop ID<input id="bp-id" placeholder="daily-quality"></label><label>Version<input id="bp-version" value="1"></label></details></div><div class="editor-meta-extra"><details><summary>描述与初始输入</summary><label>描述<input id="bp-description"></label><div class="editor-inline"><label>入口节点<select id="bp-entry"></select></label></div><div id="author-defaults"></div></details></div><div class="editor-help"><span id="editor-hint">拖动节点调整布局 · 点击节点编辑 · 点击「连线」选择下一节点</span><button id="add-node">＋ 添加节点</button></div><div class="canvas-scroll"><div class="editor-canvas" id="editor-canvas"></div></div><div id="editor-edges-list" class="editor-edge-list"></div><div class="editor-report" id="editor-report">可随时保存不完整的草稿。发布前检查输入来源、输出契约与节点实现。</div></section></div><aside class="panel editor-right"><div class="panel-heading"><h2 id="property-title">Loop 定义结构</h2><span class="revision">DRAFT</span></div><div class="editor-properties" id="editor-properties"></div></aside></div>`;
document.querySelector('main').append(editorPage);
editorPage.querySelector('.editor-top').insertAdjacentHTML('beforebegin','<div class="run-navigation"><button id="editor-back">← 返回 Loop 库</button><span>编辑此 Loop · 修改自动保存为草稿，保存并使用后供新运行采用；已有 Run 保持不变。</span></div>');
const guideAuthor=document.createElement('details');guideAuthor.className='guide-author';
guideAuthor.innerHTML='<summary>给使用者的说明 · 用途、边界与参数解释</summary><p class="editor-note">这些说明会显示在 Loop 详情和启动表单中。它们不是 Loop 操作手册或节点 Skill，也不会改变调度规则。</p><div id="guide-author-fields"></div>';
editorPage.querySelector('.editor-left .panel').append(guideAuthor);
const handbookAuthor=document.createElement('details');handbookAuthor.className='guide-author';
handbookAuthor.innerHTML='<summary>Loop 操作手册 · 启动与运行</summary><p class="editor-note">填写本 Loop 的业务用途、输入要求和结果说明。平台工具操作由平台 Skill 提供；业务方法直接放在对应节点 Skill。</p><label>手册名称<input id="handbook-name"></label><label>包内 Skill 入口（可选）<input id="handbook-path"></label><label>手册正文<textarea id="handbook-instructions" rows="12"></textarea></label>';
editorPage.querySelector('.editor-left .panel').append(handbookAuthor);

const fallbackAuthor=document.createElement('details');fallbackAuthor.className='guide-author';
fallbackAuthor.innerHTML='<summary>Agent 兜底</summary><p class="editor-note">未覆盖状态进入所选节点，使用该节点的 Agent 实现和 Skill。留空关闭。</p><label>兜底节点<select id="bp-fallback"></select></label><button type="button" id="add-fallback-node">新增兜底节点</button>';
fallbackAuthor.insertAdjacentHTML('beforeend','<label>全局 Agent 节点（可选）<select id="bp-global-agent"></select></label>');
editorPage.querySelector('.editor-left .panel').append(fallbackAuthor);
const jsonDialog=document.createElement('dialog');jsonDialog.id='editor-json-dialog';jsonDialog.className='editor-json-modal';
jsonDialog.innerHTML=`<div class="dialog-heading"><h2>Loop 定义与节点实现</h2><button class="close-dialog" aria-label="关闭">×</button></div><p class="editor-note">可粘贴完整定义，或复制当前定义用于 CLI。这里的修改先进入草稿。</p><textarea id="editor-json-value" aria-label="完整Loop 定义 JSON"></textarea><div class="dialog-tasks"><button id="editor-export">下载 JSON</button><button id="editor-import" class="primary">应用 JSON 到草稿</button></div>`;
document.body.append(jsonDialog);

async function loadDraftCards(){
  savedDrafts=await api('drafts');
  $('draft-cards').innerHTML=savedDrafts.length?`<section class="panel draft-list"><h2>草稿</h2>${savedDrafts.map(d=>`<div class="draft-row"><div>${esc(d.loop_definition.name || d.loop_definition.id || '未命名Loop 定义')}<small>revision ${d.revision} · ${new Date(d.updated_at*1000).toLocaleString('zh-CN')}</small></div><button data-open-draft="${esc(d.id)}">继续编辑 →</button></div>`).join('')}</section>`:'';
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
  const result=source?await platformCall('copy_loop',{key:source.key,new_version:versionOnly}):await platformCall('create_loop',{name:'我的新 Loop'});
  const loaded=(await platformCall('read_loop',{draft_id:result.draft_id})).loop;
  editor={...loaded,dirty:false};
  await openEditor();
}
async function editWithTool(tool,values){
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
    Object.assign(editor,loaded,{dirty:false});editor.loop_definition.layout ||= {};
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
  b.plans ||= {};
  if(!b.plans[authorPlan])authorPlan=Object.keys(b.plans)[0]||'default';
  $('bp-name').value=b.name || '';$('bp-id').value=b.id || '';$('bp-version').value=b.version || '1';
  $('bp-description').value=b.description || '';$('author-defaults').innerHTML=valueField(b.defaults || {},{type:'object',properties:b.nodes[b.entry]?.inputs || {}},'初始输入默认值');
  updateEntryOptions();
  $('bp-fallback').innerHTML=fallbackOptions(b,b.fallback_node);$('bp-global-agent').innerHTML=globalAgentOptions(b,b.global_agent_node);
  renderGuideAuthor();
  $('handbook-path').value=b.handbook?.path || '';$('handbook-name').value=b.handbook?.name || '';$('handbook-instructions').value=b.handbook?.instructions || '';
}
function updateEntryOptions(){
  const b=editor.loop_definition;
  $('bp-entry').innerHTML='<option value="">请选择入口</option>'+Object.entries(b.nodes).map(([id,n])=>`<option value="${esc(id)}">${esc(n.label || id)}</option>`).join('');
  $('bp-entry').value=b.entry || '';
}
function collectMeta(){
  const b=editor.loop_definition;
  const defaults=valueAt('author-defaults');
  if(!defaults || Array.isArray(defaults) || typeof defaults!=='object')throw new Error('初始输入默认值必须是 JSON 对象');
  Object.assign(b,{name:$('bp-name').value,id:$('bp-id').value.trim(),version:$('bp-version').value.trim(),description:$('bp-description').value,defaults,entry:$('bp-entry').value});
  b.fallback_node=$('bp-fallback').value || null;b.global_agent_node=$('bp-global-agent').value || null;
  collectGuideAuthor();
  const name=$('handbook-name').value,instructions=$('handbook-instructions').value;
  if(b.handbook || name || instructions)b.handbook={...b.handbook,name,instructions};if($('handbook-path').value.trim())b.handbook.path=$('handbook-path').value.trim();else if(b.handbook)delete b.handbook.path;
}
function renderGuideAuthor(){
  const b=editor.loop_definition,g=guideOf(b),params=launchFields(b,objectValue(b.defaults));
  $('guide-author-fields').innerHTML=Object.entries(guideFields).map(([k,label])=>`<label>${label}<textarea data-guide="${k}" rows="2">${esc(g[k] || '')}</textarea></label>`).join('')+'<h3>启动参数解释</h3><p class="editor-note">字段来自初始输入默认值和入口契约。新增参数请先编辑初始输入 / Seed；这里不定义类型或执行规则。</p>'+params.map((p,i)=>`<div data-guide-parameter="${i}" data-key="${esc(p.key)}"><p class="mono">${esc(p.key)}</p><label>显示名称<input data-parameter-label value="${esc(g.parameters?.[p.key]?.label || '')}" placeholder="${esc(p.key)}"></label><label>填写说明<textarea data-parameter-description rows="2">${esc(g.parameters?.[p.key]?.description || '')}</textarea></label></div>`).join('');
}
function collectGuideAuthor(){
  const g={...guideOf(editor.loop_definition)},parameters=Object.assign(Object.create(null),g.parameters || {});
  for(const el of guideAuthor.querySelectorAll('[data-guide]')){if(el.value)g[el.dataset.guide]=el.value;else delete g[el.dataset.guide];}
  for(const el of guideAuthor.querySelectorAll('[data-guide-parameter]')){const label=el.querySelector('[data-parameter-label]').value,description=el.querySelector('[data-parameter-description]').value;if(label || description)parameters[el.dataset.key]={label,description};else delete parameters[el.dataset.key];}
  if(Object.keys(parameters).length)g.parameters=parameters;else delete g.parameters;
  if(Object.keys(g).length)editor.loop_definition.guide=g;else delete editor.loop_definition.guide;
}
function saveState(){ $('editor-save-status').textContent=editor.dirty?'正在保存草稿…':`草稿已保存 · revision ${editor.revision}`; }
function dirty(){
  editor.dirty=true;editor.edits=(editor.edits||0)+1;saveState();
  $('editor-report').className='editor-report';$('editor-report').textContent='修改自动保存为草稿；保存并使用时统一检查。';
  clearTimeout(dirty.timer);const target=editor;
  dirty.timer=setTimeout(()=>{if(page==='editor'&&editor===target&&!editorBusy)saveEditor().catch(e=>{$('editor-save-status').textContent='尚未保存 · '+e.message;});},650);
}
function ensurePositions(){editor.loop_definition.layout=Object.fromEntries(loopNodePositions(editor.loop_definition));}
function renderEditor(){
  const b=editor.loop_definition;ensurePositions();const canvas=$('editor-canvas');
  const positions=Object.values(b.layout);
  canvas.style.width=Math.max(750,...positions.map(p=>(Number(p.x)||0)+225))+'px';
  canvas.style.height=Math.max(500,...positions.map(p=>(Number(p.y)||0)+185))+'px';
  canvas.innerHTML=Object.entries(b.nodes).map(([id,n])=>{
    const p=b.layout[id],kind=chosenImplementation(editor,id)?.kind || '未选用';
    return `<article class="editor-node ${editSelection?.node===id?'picked':''} ${connectFrom?'connect-target':''}" data-editor-card="${esc(id)}" style="left:${p.x}px;top:${p.y}px"><div class="editor-node-head" data-drag-node="${esc(id)}" role="button" tabindex="0" aria-label="编辑节点 ${esc(n.label || id)}"><span class="node-icon">${kind==='agent'?'✧':kind==='event'?'◷':'▤'}</span>${esc(n.label || id)}</div><div class="editor-node-id">${esc(id)}</div>${lifecycleStrip(chosenImplementation(editor,id,{}))}${authorPortButtons(id,n)}<div class="editor-node-footer"><span>${b.entry===id?'入口 · ':b.fallback_node===id?'兜底 · ':''}${esc(mapImplementationLabel(editor,id,{}))}</span><button data-connect-node="${esc(id)}" title="选择此节点后再点击目标节点">连线 ＋</button></div></article>`;
  }).join('') || '<div class="canvas-empty"><div class="empty-mark">◇</div><h2>从第一个业务步骤开始</h2><p>添加节点，声明输入与输出，再将它们连接起来。</p></div>';
  requestAnimationFrame(drawEditorEdges);
  if(b.schema_version===2){
    $('editor-edges-list').innerHTML=loopProgressHTML(editor)+'<h3>本轮构建模板</h3>'+Object.entries(b.plans || {}).map(([name,p])=>`<div class="edge-row"><button data-edit-edge="${esc(name)}">${esc(name)} · ${Object.keys(p.steps).length} 步</button></div>`).join('')+'<button id="editor-json">编辑构建模板、Seed 与完整 JSON</button>'+'<div id="unused-record-types">'+unusedRecordsHTML()+'</div>';
    $('editor-edges-list').insertAdjacentHTML('afterbegin',`<label>当前构建模板<select id="author-plan-select">${Object.keys(b.plans || {}).map(k=>`<option ${k===authorPlan?'selected':''}>${esc(k)}</option>`).join('')}</select></label><div class="row"><input id="new-plan-name" placeholder="新模板名称"><button type="button" id="new-author-plan">＋ 模板</button></div>`);
    $('editor-hint').textContent='实线是依赖，紫色虚线是后续安排；点节点修改循环、Skill 与实现。';return;
  }
}

function drawEditorEdges(){
  const canvas=$('editor-canvas');canvas.querySelector('svg')?.remove();
  canvas.style.height=Math.max(500,...[...canvas.querySelectorAll('.editor-node')].map(card=>card.offsetTop+card.offsetHeight+70))+'px';
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.classList.add('editor-edges');
  svg.setAttribute('width',canvas.style.width);svg.setAttribute('height',canvas.style.height);
  svg.innerHTML='<defs><marker id="studio-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="#849bcc"/></marker><marker id="studio-plan-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="#9564cf"/></marker><marker id="studio-recovery-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="#bd705f"/></marker></defs>';
  for(const e of [...loop_definitionEdges(editor.loop_definition),...loopRelationships(editor.loop_definition).filter(e=>e.kind!=='dependency')]){
    const a=editor.loop_definition.layout[e.from],b=editor.loop_definition.layout[e.to];if(!a||!b)continue;
    const out=canvas.querySelector(`[data-port-node="${CSS.escape(e.from)}"][data-output-port="${CSS.escape(e.output||'')}"]`),input=canvas.querySelector(`[data-port-node="${CSS.escape(e.to)}"][data-input-port="${CSS.escape(e.input||'')}"]`);
    const box=canvas.getBoundingClientRect(),ob=out?.getBoundingClientRect(),ib=input?.getBoundingClientRect();
    const sx=ob?ob.right-box.left:a.x+200,sy=ob?ob.top+ob.height/2-box.top:a.y+65,tx=ib?ib.left-box.left:b.x,ty=ib?ib.top+ib.height/2-box.top:b.y+65;
    const bend=Math.max(65,Math.abs(tx-sx)/2);
    const d=e.kind==='recovery'?loopEdgePath(e,{...a,height:canvas.querySelector(`[data-editor-card="${CSS.escape(e.from)}"]`).offsetHeight},{...b,height:canvas.querySelector(`[data-editor-card="${CSS.escape(e.to)}"]`).offsetHeight}).d:e.kind==='planning'?loopEdgePath(e,a,b).d:e.from===e.to?`M ${sx} ${sy} C ${sx+90} ${sy-130}, ${a.x-90} ${sy-130}, ${tx} ${ty}`:`M ${sx} ${sy} C ${sx+bend} ${sy}, ${tx-bend} ${ty}, ${tx} ${ty}`;
    const line=document.createElementNS(ns,'path');line.setAttribute('d',d);line.setAttribute('class','edge'+(e.kind==='planning'?' planning':e.kind==='recovery'?' recovery':'')+(e.id&&editSelection?.edge===e.id?' edge-picked':''));line.setAttribute('marker-end',e.kind==='recovery'?'url(#studio-recovery-arrow)':e.kind==='planning'?'url(#studio-plan-arrow)':'url(#studio-arrow)');svg.appendChild(line);
    const hit=document.createElementNS(ns,'path');hit.setAttribute('d',d);hit.setAttribute('class','edge-hit');if(e.kind==='recovery'){const title=document.createElementNS(ns,'title');title.textContent='异常仍未解决时进入已配置兜底';line.appendChild(title);continue;}if(e.kind==='planning')hit.dataset.editPlanning=e.from;else hit.dataset.editEdge=e.id;svg.appendChild(hit);
  }
  canvas.prepend(svg);
}
function renderProperties(){renderAuthorProperties();}
function collectProperties(){collectAuthorProperties();}
function collectAll(){collectMeta();collectProperties();}
function selectEditor(selection){collectAll();editSelection=selection;connectFrom=null;renderEditor();renderProperties();}
async function addEdge(from,to){
  const b=editor.loop_definition;
  if(b.nodes[from].initialize_timeline || b.nodes[to].initialize_timeline)throw new Error('初始化入口不加入批次模板');
  collectAll();
  for(const node of [from,to]){
    const step=editor.loop_definition.plans?.[authorPlan]?.steps?.[node];
    if(!step)await ensureAuthorStep(node,node);
  }
  const target=editor.loop_definition.plans[authorPlan].steps[to];
  await editWithTool('put_step',{plan:authorPlan,step:to,node_id:target.node,after:[...new Set([...(target.after || []),from])]});
  editSelection={edge:authorPlan};connectFrom=null;renderEditor();renderProperties();
}

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
    if(!target.dirty){target.loop_definition.records=result.loop_definition.records;if(editor===target&&page==='editor'){const report=await platformCall('validate_loop',{draft_id:target.id});if(editor===target&&page==='editor'&&!target.dirty&&target.revision===result.revision){renderReport(report);$('unused-record-types').innerHTML=unusedRecordsHTML();}}}
    return result;
  }finally{if(editorSave===saving)editorSave=null;}
}
async function saveAndUseLoop(){
  if(editorBusy)return;editorBusy=true;editorPage.inert=true;
  try{
    await saveEditor();const report=await platformCall('validate_loop',{draft_id:editor.id});renderReport(report);if(!report.valid)return;
    const result=await platformCall('publish_loop',{draft_id:editor.id,revision:editor.revision,auto_version:true});
    editor.revision=result.revision;editor.loop_definition.version=result.version;$('bp-version').value=result.version;editor.dirty=false;
    await loadCatalog();await openPreparation(result.key);toast('已保存为可用版本，请核对本次运行设置。');
  }finally{editorBusy=false;editorPage.inert=false;}
}

function unusedRecordsHTML(){
  const bp=editor.loop_definition,used=new Set(Object.values(bp.nodes).flatMap(n=>Object.values(n.outputs||{}).map(s=>s.record_type))),unused=Object.keys(bp.records||{}).filter(k=>!used.has(k));
  return unused.length?`<section class="unused-records"><h3>未引用的记录类型</h3><p class="small muted">这些类型没有节点输出引用。清理只影响此草稿。</p><ul>${unused.map(k=>`<li>${esc(k)}</li>`).join('')}</ul><button type="button" data-prune-records="${esc(JSON.stringify(unused))}">清理列出的类型</button></section>`:'';
}
function locateEditorIssue(path){
  if(path[0]==='plans'&&editor.loop_definition.plans[path[1]]){
    authorPlan=path[1];selectEditor({edge:path[1]});const step=$('editor-properties').querySelector(`[data-step-key="${CSS.escape(path[3]||'')}"]`);if(step){step.open=true;const field=path[4]==='inputs'?step.querySelector(`[data-source-name="${CSS.escape(path[5]||'')}"]`):step;(field||step).scrollIntoView({block:'center'});(field||step).querySelector('select,input,textarea')?.focus();}return;
  }
  const id=path[0]==='seed'?editor.loop_definition.entry:path[1];
  if(['nodes','implementations','seed'].includes(path[0])&&editor.loop_definition.nodes[id]){selectEditor({node:id});const field=[...$('editor-properties').querySelectorAll('[data-port-name]')].find(el=>el.value===path[3]);if(field){field.closest('details').open=true;field.scrollIntoView({block:'center'});field.focus();}else $('editor-properties').scrollIntoView({block:'start'});return;}
  const target=path[0]==='handbook'?$('handbook-instructions'):path[0]==='records'?document.querySelector('.unused-records'):$('bp-name');if(target){for(let p=target.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;target.scrollIntoView({block:'center'});target.focus();}
}
function renderReport(report){
  const r=$('editor-report');r.className='editor-report '+(report.valid?'success':'failure');
  r.innerHTML=`<strong>${report.valid?'✓ 结构有效':'需要修正'}</strong>`+(report.issues?.length?report.issues.map(issue=>`<p>${esc(issue.message)} <button type="button" data-input-location="${esc(JSON.stringify(issue.path))}">定位修正</button></p>`).join(''):report.errors.map(x=>`<p>• ${esc(x)}</p>`).join(''))+((report.unbound_nodes || []).length?`<p>待绑定：${report.unbound_nodes.map(esc).join('、')}。仍可导出、分享和安装；不表示已具备运行条件。</p>`:'')+report.warnings.map(x=>`<p class="small">${esc(x)}</p>`).join('');
}
document.addEventListener('click',event=>safely(async()=>{
  const el=event.target.closest('button,[data-edit-edge],[data-edit-planning]');if(!el)return;const d=el.dataset;
  if(d.inputLocation){locateEditorIssue(JSON.parse(d.inputLocation));return;}
  if(d.pruneRecords){await editWithTool('set_loop',{remove_records:JSON.parse(d.pruneRecords)});return;}
  if(d.copyLoopDefinition || d.versionLoopDefinition){await newLoopDefinition(catalog.find(c=>c.key===(d.copyLoopDefinition || d.versionLoopDefinition)),!!d.versionLoopDefinition);return;}
  if(d.openDraft){if(page==='editor')await saveEditor();editor={...structuredClone(savedDrafts.find(x=>x.id===d.openDraft)),dirty:false};openEditor();return;}
  if(d.editPlanning){selectEditor({node:d.editPlanning});$('author-plan-nodes')?.scrollIntoView({block:'nearest'});return;}
  if(d.editEdge){selectEditor({edge:d.editEdge});return;}
  if(d.connectNode){collectAll();connectFrom=d.connectNode;renderEditor();return;}
  switch(el.id){

    case 'new-loop_definition':if(editor?.dirty){await openEditor();toast('已返回未保存草稿；可先保存后再新建');}else await newLoopDefinition();break;
    case 'add-fallback-node':{collectAll();let id='fallback',i=1;while(Object.hasOwn(editor.loop_definition.nodes,id))id='fallback_'+i++;await editWithTool('put_node',{node_id:id,label:'Agent 兜底',instructions:'读取当前未覆盖状态，按用户授权用工具处理相关任务，再完成本节点。',inputs:[],outputs:[]});await editWithTool('set_loop',{fallback_node:id});editSelection={node:id};renderEditor();renderProperties();toast('已添加兜底节点，请选择它的 Agent 实现。');break;}
    case 'add-node':{collectAll();let i=1;while(Object.hasOwn(editor.loop_definition.nodes,'node_'+i))i++;const id='node_'+i;await editWithTool('put_node',{node_id:id,label:'新节点 '+i,instructions:'声明本节点的业务职责',inputs:[],outputs:[{name:'result',type:'string'}]});editSelection={node:id};renderEditor();renderProperties();break;}
    case 'editor-publish':await saveAndUseLoop();break;
    case 'editor-json':collectAll();$('editor-json-value').value=pretty({loop_definition:editor.loop_definition,implementations:editor.implementations});jsonDialog.showModal();break;
    case 'editor-import':{const value=JSON.parse($('editor-json-value').value);if(!value.loop_definition || !value.loop_definition.nodes || Array.isArray(value.loop_definition.nodes) || value.loop_definition.schema_version!==2)throw new Error('需要当前 loop_definition（含 nodes 和 plans）；implementations 可以省略');value.implementations ||= {};const report=await api('validate',{...value});if(!report.valid)throw new Error('JSON 未通过校验：'+report.errors.join('；'));editor.loop_definition=value.loop_definition;editor.implementations=value.implementations;editor.loop_definition.layout ||= {};editSelection=null;jsonDialog.close();populateMeta();dirty();renderEditor();renderProperties();break;}
    case 'editor-export':{const content=$('editor-json-value').value;JSON.parse(content);const url=URL.createObjectURL(new Blob([content],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=(editor.loop_definition.id || 'loop_definition')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);break;}
  }
}));
editorPage.addEventListener('submit',e=>{e.preventDefault();safely(async()=>{await saveEditor();renderEditor();});});
editorPage.addEventListener('input',()=>{if(editor)dirty();});
editorPage.addEventListener('change',e=>{if(e.target.id==='bp-defaults')safely(async()=>{collectMeta();renderGuideAuthor();});if(e.target.id==='bp-fallback')safely(async()=>{collectAll();renderEditor();renderProperties();});if(editor)dirty();});
editorPage.addEventListener('pointerdown',e=>{
  const head=e.target.closest('[data-drag-node]');if(!head || e.button!==0)return;
  const id=head.dataset.dragNode;
  if(connectFrom){safely(async()=>{collectAll();await addEdge(connectFrom,id);});return;}
  try{collectAll();}catch(error){toast(error.message);return;}
  editSelection={node:id};renderProperties();
  editorPage.querySelectorAll('.editor-node').forEach(c=>c.classList.toggle('picked',c.dataset.editorCard===id));
  const p=editor.loop_definition.layout[id];dragState={id,x:e.clientX,y:e.clientY,startX:p.x,startY:p.y,moved:false};head.setPointerCapture(e.pointerId);
});
editorPage.addEventListener('pointermove',e=>{
  if(!dragState)return;const d=dragState;
  if(Math.abs(e.clientX-d.x)+Math.abs(e.clientY-d.y)<4)return;
  d.moved=true;const p=editor.loop_definition.layout[d.id];p.x=Math.max(10,Math.round(d.startX+e.clientX-d.x));p.y=Math.max(20,Math.round(d.startY+e.clientY-d.y));
  const card=[...editorPage.querySelectorAll('.editor-node')].find(c=>c.dataset.editorCard===d.id);card.style.left=p.x+'px';card.style.top=p.y+'px';drawEditorEdges();
});
function endDrag(){if(!dragState)return;const moved=dragState.moved;dragState=null;if(moved)dirty();renderEditor();}
editorPage.addEventListener('pointerup',endDrag);editorPage.addEventListener('pointercancel',endDrag);
editorPage.addEventListener('keydown',e=>{
  if(e.key==='Escape' && connectFrom){connectFrom=null;renderEditor();}
  if(e.key==='Enter' && e.target.dataset.dragNode)safely(async()=>{if(connectFrom)await addEdge(connectFrom,e.target.dataset.dragNode);else selectEditor({node:e.target.dataset.dragNode});});
});
window.addEventListener('beforeunload',e=>{if(editor?.dirty || [...editorSessions.values()].some(s=>s.editor.dirty)){e.preventDefault();e.returnValue='';}});
