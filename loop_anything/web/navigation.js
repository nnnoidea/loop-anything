'use strict';
// Routes identify assets, draft editors and individual Runs; never mutate runtime state.
let activeRoute={type:'home'}, navigationSerial=0;
const editorSessions=new Map(),runReturns=new Map();
function routeHash(route){
  if(route.type==='communication')return '#communication';
  if(route.type==='schedules')return '#schedules';
  if(route.type==='catalog')return '#loop_definitions';
  if(route.type==='loop')return '#loop/'+encodeURIComponent(route.key)+'/'+(route.tab || 'overview');
  if(route.type==='editor')return '#edit/'+encodeURIComponent(route.id)+(route.node?'/node/'+encodeURIComponent(route.node)+(route.implementation?'/implementation/'+encodeURIComponent(route.implementation):''):'');
  if(route.type==='prepare')return '#prepare/'+encodeURIComponent(route.id);
  if(route.type==='run')return '#run/'+encodeURIComponent(route.id);
  return '#';
}
function parseRoute(hash){
  const parts=hash.replace(/^#/,'').split('/');
  if(parts[0]==='communication')return {type:'communication'};
  if(parts[0]==='schedules')return {type:'schedules'};
  if(!parts[0])return {type:'home'};
  if(parts[0]==='loop_definitions')return {type:'catalog'};
  if(parts[0]==='loop')return {type:'loop',key:decodeURIComponent(parts[1] || ''),tab:['overview','flow','prepare'].includes(parts[2])?parts[2]:'overview'};
  if(parts[0]==='prepare')return {type:'prepare',id:decodeURIComponent(parts[1] || '')};
  if(parts[0]==='edit')return {type:'editor',id:decodeURIComponent(parts[1] || ''),...(parts[2]==='node'&&parts[3]?{node:decodeURIComponent(parts[3]),...(parts[4]==='implementation'&&parts[5]?{implementation:decodeURIComponent(parts[5])}:{})}:{})};
  return {type:'run',id:decodeURIComponent(parts[0]==='run'?parts[1]:parts[0])}; // old #run-... links
}
function rememberEditor(){
  if(page!=='editor' || !editor)return;
  editor.routeId ||= editor.id || 'session-'+randomKey();
  editorSessions.set(editor.routeId,{editor,selection:editSelection});
}
function registerEditor(){
  editor.routeId ||= editor.id || 'session-'+randomKey();
  editor.returnTo ||= activeRoute.type==='editor'?{type:'catalog'}:structuredClone(activeRoute.type==='home'?{type:'catalog'}:activeRoute);
  editorSessions.set(editor.routeId,{editor,selection:null});
  return editor.routeId;
}
async function navigateTo(route,{replace=false,external=false,capture=true}={}){
  if(route.type==='loop')route={type:'editor',id:route.key};
  const previous=activeRoute,serial=++navigationSerial;
  // Reading another node preserves the authored iframe and never writes the definition.
  if(capture&&page==='editor'&&route.type==='editor'&&route.id===previous.id&&route.id===editor?.routeId){
    if(route.node&&!Object.hasOwn(editor.loop_definition.nodes,route.node)){toast('节点已不存在，请重新选择。');if(external)history.replaceState(null,'',routeHash(previous));return false;}
    if(!external)history[replace?'replaceState':'pushState'](null,'',routeHash(route));
    activeRoute=structuredClone(route);editSelection=route.node?{node:route.node}:null;
    renderProperties();updateNavigationUI();
    const pane=editorPage.querySelector('.editor-right');pane.scrollTop=0;
    if(route.node&&window.matchMedia('(max-width: 1100px)').matches)pane.focus({preventScroll:true});
    return true;
  }
  if(capture&&page==='editor')rememberEditor();
  try{
    let session;
    if(route.type==='editor'){
      session=editorSessions.get(route.id);
      if(!session){session={editor:await loadReader(route.id),selection:null};editorSessions.set(route.id,session);}
    }
    if(route.type==='loop' && !catalog.some(c=>c.key===route.key))await loadCatalog();
    if(route.type==='loop' && !catalog.some(c=>c.key===route.key))throw new Error('找不到这个 Loop 版本，请返回 Loop 库。');
    const nextRun=route.type==='run'?await api('runs/'+route.id):null;
    if(serial!==navigationSerial)return false;
    if(document.fullscreenElement===editorPage&&routeHash(route)!==routeHash(previous))await document.exitFullscreen();
    if(!external)history[replace?'replaceState':'pushState'](null,'',routeHash(route));
    activeRoute=structuredClone(route);
    if(route.type==='communication'){page='communication';await renderCommunication();}
    else if(route.type==='schedules'){page='schedules';refreshSchedules();}
    else if(route.type==='catalog'){page='catalog';await loadCatalog();}
    else if(route.type==='loop'){await openLoop(route.key);}
    else if(route.type==='prepare'){page='catalog';await loadCatalog();toast('请重新从 Loop 页面启动；旧准备记录保留。');}
    else if(route.type==='editor'){
      editor=session.editor;if(route.node&&!Object.hasOwn(editor.loop_definition.nodes,route.node))throw new Error('节点已不存在，请返回草稿总览。');editSelection=route.node?{node:route.node}:null;page='editor';
      populateMeta();renderEditor();renderProperties();
    }else if(route.type==='run'){
      if(previous.type!=='run' && previous.type!=='home')runReturns.set(route.id,structuredClone(previous));
      selected=route.id;run=nextRun;settingsBase=null;filterNode=null;page='runs';renderRun();
    }else{page='runs';await refresh();}
    showPage();updateNavigationUI();window.scrollTo(0,0);if(page==='runs')requestAnimationFrame(()=>sizeTaskGraph());return true;
  }catch(error){
    if(serial!==navigationSerial)return false;
    if(external){activeRoute={type:'catalog'};history.replaceState(null,'','#loop_definitions');page='catalog';showPage();updateNavigationUI();}
    toast(error.message);return false;
  }
}
function navLink(route,label){return `<a href="${esc(routeHash(route))}" data-route-link>${esc(label)}</a>`;}
function relatedRunsHTML(key){return relatedRunRows(key);}

function updateNavigationUI(){
  $('run-list').querySelectorAll('[data-run]').forEach(b=>b.classList.toggle('chosen',page==='runs'&&b.dataset.run===selected));
  const crumbs=[navLink({type:'catalog'},'Loop 库')];
  if(page==='communication'){crumbs.push('Agent 通信');}
  else if(page==='schedules'){crumbs.push('定时任务');}
  else if(page==='editor' && editor){
    if(editor.installedKey&&$('reader-runs')){renderRelatedRuns(editor.installedKey);safely(()=>refreshRelatedRuns(editor.installedKey));}
    if(editor.returnTo?.type==='loop')crumbs.push(navLink(editor.returnTo,'来源 Loop'));
    crumbs.push(navLink({type:'editor',id:editor.routeId},(editor.loop_definition.name || '草稿')+' · 查看'));
    if(activeRoute.node)crumbs.push(navLink({type:'editor',id:editor.routeId,node:activeRoute.node},editor.loop_definition.nodes[activeRoute.node]?.label||activeRoute.node));
    if(activeRoute.implementation)crumbs.push(esc(activeRoute.implementation));
    $('editor-back').textContent=editor.returnTo?.type==='loop'?'← 返回 Loop '+(editor.returnTo.tab==='prepare'?'使用准备':'详情'):editor.returnTo?.type==='prepare'?'← 返回启动准备':'← 返回 Loop 库';
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
