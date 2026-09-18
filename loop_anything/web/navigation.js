'use strict';
// Routes identify assets, draft editors and individual Runs; never mutate runtime state.
let activeRoute={type:'home'}, navigationSerial=0;
const editorSessions=new Map(),runReturns=new Map();
function routeHash(route){
  if(route.type==='catalog')return '#loop_definitions';
  if(route.type==='loop')return '#loop/'+encodeURIComponent(route.key)+'/'+(route.tab || 'overview');
  if(route.type==='editor')return '#edit/'+encodeURIComponent(route.id);
  if(route.type==='run')return '#run/'+encodeURIComponent(route.id);
  return '#';
}
function parseRoute(hash){
  const parts=hash.replace(/^#/,'').split('/');
  if(!parts[0])return {type:'home'};
  if(parts[0]==='loop_definitions')return {type:'catalog'};
  if(parts[0]==='loop')return {type:'loop',key:decodeURIComponent(parts[1] || ''),tab:['overview','flow','prepare'].includes(parts[2])?parts[2]:'overview'};
  if(parts[0]==='edit')return {type:'editor',id:decodeURIComponent(parts[1] || '')};
  return {type:'run',id:decodeURIComponent(parts[0]==='run'?parts[1]:parts[0])}; // old #run-... links
}
function rememberEditor(){
  if(page!=='editor' || !editor)return;
  collectAll();
  editor.routeId ||= editor.id || 'session-'+crypto.randomUUID();
  editorSessions.set(editor.routeId,{editor,selection:editSelection});
}
function registerEditor(){
  editor.routeId ||= editor.id || 'session-'+crypto.randomUUID();
  editor.returnTo ||= activeRoute.type==='editor'?{type:'catalog'}:structuredClone(activeRoute.type==='home'?{type:'catalog'}:activeRoute);
  editorSessions.set(editor.routeId,{editor,selection:null});
  return editor.routeId;
}
function savedEditorRoute(){
  if(page!=='editor' || !editor.id)return;
  const old=editor.routeId;editor.routeId=editor.id;
  editorSessions.set(editor.id,{editor,selection:editSelection});
  if(old)editorSessions.set(old,{editor,selection:editSelection});
  activeRoute={type:'editor',id:editor.id};history.replaceState(null,'',routeHash(activeRoute));updateNavigationUI();
}
async function navigateTo(route,{replace=false,external=false,capture=true}={}){
  const previous=activeRoute,serial=++navigationSerial;
  if(capture && page==='editor' && routeHash(route)!==routeHash(previous)){
    try{rememberEditor();}catch(error){if(external)history.replaceState(null,'',routeHash(previous));toast('草稿中有未应用的无效内容，请先修正；修改仍保留：'+error.message);return false;}
    // Keep the draft in memory on navigation. beforeunload protects reload/closing.
  }
  try{
    let session;
    if(route.type==='editor'){
      session=editorSessions.get(route.id);
      if(!session){const rows=await api('drafts'),draft=rows.find(d=>d.id===route.id);if(!draft)throw new Error('这份未保存草稿不在当前会话中；请从 Loop 库打开已保存草稿。');session={editor:{...draft,dirty:false,routeId:draft.id,returnTo:{type:'catalog'}},selection:null};editorSessions.set(route.id,session);}
    }
    if(route.type==='loop' && !catalog.some(c=>c.key===route.key))await loadCatalog();
    if(route.type==='loop' && !catalog.some(c=>c.key===route.key))throw new Error('找不到这个 Loop 版本，请返回 Loop 库。');
    const nextRun=route.type==='run'?await api('runs/'+route.id):null;
    if(serial!==navigationSerial)return false;
    if(!external)history[replace?'replaceState':'pushState'](null,'',routeHash(route));
    activeRoute=structuredClone(route);
    if(route.type==='catalog'){page='catalog';await loadCatalog();}
    else if(route.type==='loop'){page='loop';loopKey=route.key;loopTab=route.tab || 'overview';renderLoop();}
    else if(route.type==='editor'){
      editor=session.editor;editSelection=session.selection;connectFrom=null;page='editor';
      editor.loop_definition.layout ||= {};populateMeta();renderEditor();renderProperties();saveState();
    }else if(route.type==='run'){
      if(previous.type!=='run' && previous.type!=='home')runReturns.set(route.id,structuredClone(previous));
      selected=route.id;run=nextRun;settingsBase=null;filterNode=null;page='runs';renderRun();
    }else{page='runs';await refresh();}
    showPage();updateNavigationUI();window.scrollTo(0,0);return true;
  }catch(error){
    if(serial!==navigationSerial)return false;
    if(external){activeRoute={type:'catalog'};history.replaceState(null,'','#loop_definitions');page='catalog';showPage();updateNavigationUI();}
    toast(error.message);return false;
  }
}
function navLink(route,label){return `<a href="${esc(routeHash(route))}" data-route-link>${esc(label)}</a>`;}
function relatedRunsHTML(key){
  const rows=runs.filter(r=>r.loop_key===key);
  return `<h3>这个版本的运行 · ${rows.length}</h3><p class="small muted">每个 Run 有独立的目标、Timeline 和历史，修改Loop 定义不会改变已有运行。</p>${rows.map(r=>`<p>${navLink({type:'run',id:r.id},r.title)} ${badge(r.status)}</p>`).join('') || '<p class="muted">还没有运行。</p>'}`;
}
function updateNavigationUI(){
  const crumbs=[navLink({type:'catalog'},'Loop 库')];
  if(page==='loop'){
    crumbs.push(esc(currentLoop()?.loop_definition.name || loopKey));
    if($('loop-runs')){const content=relatedRunsHTML(loopKey);if($('loop-runs').innerHTML!==content)$('loop-runs').innerHTML=content;}
  }else if(page==='editor' && editor){
    if(editor.returnTo?.type==='loop')crumbs.push(navLink(editor.returnTo,'来源 Loop'));
    crumbs.push(esc(editor.loop_definition.name || '草稿')+' · 编辑副本');
    $('editor-back').textContent=editor.returnTo?.type==='loop'?'← 返回 Loop '+(editor.returnTo.tab==='prepare'?'使用准备':'详情'):'← 返回 Loop 库';
  }else if(page==='runs' && run){
    const c=catalog.find(c=>c.key===run.loop_key);
    const asset={type:'loop',key:run.loop_key,tab:'overview'};
    crumbs.push(navLink(asset,(c?.loop_definition.name || run.loop_definition.id)+' · v'+run.loop_definition.version));crumbs.push(esc(run.title));
    $('run-navigation').innerHTML=navLink(runReturns.get(run.id) || asset,'← 返回来源页面')+'<span>当前是一次运行</span>'+navLink(asset,'查看实际使用的 Loop 版本');
  }
  $('breadcrumbs').innerHTML=crumbs.join('<span> / </span>');
}
document.addEventListener('click',event=>{
  const link=event.target.closest('[data-route-link]');
  if(link && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button===0){event.preventDefault();safely(()=>navigateTo(parseRoute(link.hash)));}
  if(event.target.closest('#editor-back'))safely(()=>navigateTo(editor.returnTo || {type:'catalog'}));
});
window.addEventListener('hashchange',()=>safely(()=>navigateTo(parseRoute(location.hash),{external:true})));
