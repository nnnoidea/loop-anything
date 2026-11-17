'use strict';
let workReadSerial=0;
const workEntryLabels={note:'记录',progress:'进展',decision:'决定',action:'执行',change:'目标 / 限制变更'};
const timelineGroupPages=new Map(),openTimelineGroups=new Set();
function timelineCards(items){
  return `<div class="timeline-cards">${items.map(t=>`<a class="timeline-card" href="${esc(routeHash({type:'timeline',id:t.id}))}" data-route-link><div class="timeline-card-top"><span class="timeline-mark" aria-hidden="true">◎</span><span class="row-arrow" aria-hidden="true">↗</span></div><h3>${esc(t.title||t.objective||t.id)}</h3><p>${esc(t.objective||'尚未记录目标')}</p><small>创建于 ${esc(runDate(t.created_at))}</small></a>`).join('')}</div>`;
}
async function showWorkLibrary(){
  const serial=++workReadSerial;
  $('timelines-list').innerHTML='<p class="empty-inline">正在读取 Timeline…</p>';
  const data=await platformCall('list_timelines',{limit:1});
  if(serial!==workReadSerial||page!=='timelines')return;
  $('timelines-list').innerHTML=data.groups.length?data.groups.map(g=>{
    const key=JSON.stringify(g.loop_id);
    return `<details class="timeline-group" data-timeline-group="${esc(key)}" ${openTimelineGroups.has(key)?'open':''}><summary><span class="timeline-group-icon" aria-hidden="true">${g.loop_id===null?'◎':'◇'}</span><span class="timeline-group-name"><strong>${esc(g.name)}</strong><small>${g.loop_id===null?'没有关联 Loop 的工作':esc(g.loop_id)}</small></span><span class="timeline-group-count">${g.count} 条 Timeline</span><span class="timeline-group-chevron" aria-hidden="true">›</span></summary><div class="timeline-group-body"></div></details>`;
  }).join(''):'<div class="work-empty"><span aria-hidden="true">◎</span><h3>从一件想做的事开始</h3><p>与 Agent 讨论目标，Timeline 会保存目标、限制和后续进度。</p></div>';
  await Promise.all([...$('timelines-list').querySelectorAll('[data-timeline-group][open]')].map(group=>loadTimelineGroup(group)));
}
async function loadTimelineGroup(element,offset){
  if(offset===undefined&&element.dataset.loading==='true')return;
  element.dataset.loading='true';
  const key=element.dataset.timelineGroup,loopId=JSON.parse(key);
  const previous=timelineGroupPages.get(key);
  offset??=previous?.offset||0;
  const request=Symbol('timeline-group');
  timelineGroupPages.set(key,{offset,request});
  const body=element.querySelector('.timeline-group-body');
  body.innerHTML='<p class="small muted">正在读取…</p>';
  try{
    const data=await platformCall('list_timelines',{...(loopId===null?{unbound:true}:{loop_id:loopId}),offset,limit:12});
    if(!element.isConnected||timelineGroupPages.get(key)?.request!==request)return;
    if(offset&&offset>=data.total)return loadTimelineGroup(element,data.total?Math.floor((data.total-1)/12)*12:0);
    element.dataset.loaded='true';
    body.innerHTML=timelineCards(data.timelines)+`<div class="timeline-group-pagination"><span>${data.total?`${offset+1}–${offset+data.timelines.length} / ${data.total}`:'暂无 Timeline'}</span><div><button data-timeline-page="${Math.max(0,offset-12)}" ${offset?'':'disabled'}>上一页</button><button data-timeline-page="${data.next_offset??offset}" ${data.next_offset===null?'disabled':''}>下一页</button></div></div>`;
  }catch(error){
    if(element.isConnected&&timelineGroupPages.get(key)?.request===request)body.innerHTML=`<p class="small monitor-warning">读取失败：${esc(error.message)}</p><button data-timeline-page="${offset}">重试</button>`;
  }finally{if(timelineGroupPages.get(key)?.request===request)element.dataset.loading='false';}
}
document.addEventListener('toggle',event=>{
  const group=event.target;
  if(!group.matches?.('[data-timeline-group]'))return;
  if(group.open){openTimelineGroups.add(group.dataset.timelineGroup);if(group.dataset.loaded!=='true')loadTimelineGroup(group);}
  else openTimelineGroups.delete(group.dataset.timelineGroup);
},true);
function businessStateCards(state,id){
  if(!state?.total)return '';
  const cards=state.records.map(r=>`<article class="work-entry"><strong>${esc(r.type)} · ${esc(r.id)}</strong><p>${esc(Object.values(r.summary||{}).map(v=>typeof v==='string'?v:JSON.stringify(v)).join(' · ')||'已保存业务记录')}</p><button data-business-timeline="${esc(id)}" data-business-type="${esc(r.type)}" data-business-id="${esc(r.id)}">查看记录</button><div class="business-record-detail"></div></article>`).join('');
  return `<section class="work-history"><h3>业务状态 <span>${state.total}</span></h3>${cards||'<p class="muted">尚未产生业务状态。</p>'}${state.complete?'':'<p class="small muted">当前显示前 '+state.records.length+' 条，完整记录可通过读取工具分页查询。</p>'}</section>`;
}
function savedResultsHTML(data,id){
  const records=data.results?.records||[];
  if(!data.timeline.import_source||!records.length)return '';
  return `<section class="work-history"><h3>已保存结果</h3>${records.map(r=>`<article class="work-entry"><strong>${esc(r.type||r.id)}</strong><p class="small muted">${esc(r.id)}</p><button data-work-result="${esc(r.id)}" data-result-timeline="${esc(id)}" data-result-revision="${r.revision}">查看结果</button><div class="business-record-detail"></div></article>`).join('')}${data.results.complete?'':'<p class="small muted">这里显示最近 50 份结果，下载文件包含全部记录。</p>'}</section>`;
}
function importSourceHTML(data){
  const source=data.timeline.import_source;
  if(!source)return '';
  return `<section class="timeline-portable"><div class="timeline-portable-heading"><span class="timeline-mark" aria-hidden="true">◎</span><div><strong>从已有进度继续</strong><p>让 Agent 读取这条 Timeline，选择本平台的相关 Loop 推进任务。</p></div></div><details><summary>导入来源</summary><p class="small muted">${esc(source.exported_at?'导出于 '+runDate(source.exported_at):'来自另一份 Timeline')}。已导入任务进度，外部文件仍保留为引用。</p></details></section>`;
}
async function showWorkTimeline(id,after=0){
  const serial=++workReadSerial;
  if(!after){$('timeline-title').textContent='Timeline';$('timeline-content').innerHTML='<p class="empty-inline">正在读取工作进度…</p>';}
  const data=await platformCall('read_work_timeline',{timeline_id:id,after});
  if(serial!==workReadSerial||page!=='timeline'||activeRoute.id!==id)return;
  $('timeline-title').textContent=data.timeline.title||'Timeline';
  const entries=data.entries.map(e=>`<article class="work-entry"><div class="work-entry-meta"><strong>${esc(workEntryLabels[e.kind]||e.kind)}</strong><time>${esc(runDate(e.at))}</time></div><p>${esc(e.text)}</p>${e.refs?.length?readerJSON('来源',e.refs):''}</article>`).join('');
  if(!after){
    $('timeline-content').innerHTML=`<div class="timeline-intent"><section><h3>目标</h3><p>${esc(data.timeline.objective||'尚未记录')}</p></section><section><h3>限制</h3><p>${esc(data.timeline.constraints||'尚未记录')}</p></section></div><p class="small muted timeline-edit-note">修改目标或限制，请告诉 Agent；复核结果由你决定。</p>${importSourceHTML(data)}<section class="timeline-linked"><h3>关联运行 <span>${data.runs.length}</span></h3>${data.runs.length?data.runs.map(r=>`<a class="timeline-run-link" href="${esc(routeHash({type:'run',id:r.id}))}" data-route-link><span>${esc(r.title)}</span>${badge(r.status)}<span class="row-arrow" aria-hidden="true">›</span></a>`).join(''):'<p class="muted">还没有关联运行，可以先记录和推进工作。</p>'}</section>${businessStateCards(data.business_state,id)}${savedResultsHTML(data,id)}<section class="work-history"><h3>工作经过</h3><div id="work-entries">${entries||'<p class="muted">还没有记录。</p>'}</div></section>`;
  }else{$('work-more')?.remove();$('work-entries').insertAdjacentHTML('beforeend',entries);}
  if(data.has_more)$('work-entries').insertAdjacentHTML('beforeend',`<button id="work-more" data-work-timeline="${esc(id)}" data-after="${data.cursor}">继续读取</button>`);
}
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.workResult){
    const data=await platformCall('read_work_result',{timeline_id:button.dataset.resultTimeline,id:button.dataset.workResult,revision:Number(button.dataset.resultRevision)});
    button.parentElement.querySelector('.business-record-detail').innerHTML=readerJSON('结果与来源',data.record);
  }
  if(button.dataset.businessTimeline){
    const data=await platformCall('read_business_state',{timeline_id:button.dataset.businessTimeline,type:button.dataset.businessType,id:button.dataset.businessId});
    button.parentElement.querySelector('.business-record-detail').innerHTML=readerJSON('记录与来源',data.records[0]||{});
  }
  if(button.dataset.timelinePage!==undefined)await loadTimelineGroup(button.closest('[data-timeline-group]'),Number(button.dataset.timelinePage));
  if(button.id==='timeline-import')openTimelineImport();
  if(button.id==='timeline-download')await downloadTimeline(button);
  if(button.id==='timeline-import-confirm')await importSelectedTimeline();
  if(button.id==='timelines-refresh')await showWorkLibrary();
  if(button.id==='timeline-refresh')await showWorkTimeline(activeRoute.id);
  if(button.dataset.workTimeline){
    if(button.id==='work-more')await showWorkTimeline(button.dataset.workTimeline,Number(button.dataset.after));
    else {if($('detail-dialog').open)$('detail-dialog').close();await navigateTo({type:'timeline',id:button.dataset.workTimeline});}
  }
}));

let selectedTimelineImport=null,timelineImportSerial=0;
function openTimelineImport(){
  timelineImportSerial++;selectedTimelineImport=null;
  $('timeline-file').value='';$('timeline-file').disabled=false;$('timeline-import-preview').hidden=true;
  $('timeline-import-confirm').textContent='导入并打开';
  $('timeline-import-error').hidden=true;$('timeline-import-confirm').disabled=true;
  $('timeline-import-dialog').showModal();
}
async function selectTimelineFile(file){
  const serial=++timelineImportSerial;
  selectedTimelineImport=null;$('timeline-import-confirm').disabled=true;
  $('timeline-import-preview').hidden=true;$('timeline-import-error').hidden=true;
  if(!file)return;
  try{
    if(file.size>20*1024*1024)throw new Error('文件超过 20 MiB，请选择 Timeline 进度文件。');
    const document=JSON.parse(await file.text());
    if(serial!==timelineImportSerial)return;
    if(document.format!=='loop-anything-timeline'||!document.timeline||!Array.isArray(document.state)||!Array.isArray(document.results)||!Array.isArray(document.entries))throw new Error('请选择下载的 .timeline.json 进度文件。');
    const stateCount=new Set(document.state.map(r=>JSON.stringify([r.type,r.id]))).size;
    $('timeline-import-preview').innerHTML=`<strong>${esc(document.timeline.title||'未命名 Timeline')}</strong><p>${esc(document.timeline.objective||'尚未记录目标')}</p><div class="timeline-import-counts"><span>${stateCount} 条业务状态</span><span>${document.results.length} 份结果</span><span>${document.entries.length} 条工作经过</span></div>`;
    $('timeline-import-preview').hidden=false;
    selectedTimelineImport={document,request_id:randomKey()};
    $('timeline-import-confirm').disabled=false;
  }catch(error){
    if(serial!==timelineImportSerial)return;
    $('timeline-import-error').textContent=error instanceof SyntaxError?'文件不是有效的 JSON，请重新选择 Timeline 文件。':error.message;
    $('timeline-import-error').hidden=false;
  }
}
document.addEventListener('change',event=>{if(event.target.id==='timeline-file')selectTimelineFile(event.target.files[0]);});
async function importSelectedTimeline(){
  if(!selectedTimelineImport)return;
  const button=$('timeline-import-confirm'),file=$('timeline-file'),serial=timelineImportSerial;
  const selection=selectedTimelineImport;
  button.disabled=true;file.disabled=true;button.textContent='正在导入…';$('timeline-import-error').hidden=true;
  try{
    const result=await platformCall('import_timeline',selection);
    if(serial!==timelineImportSerial)return;
    $('timeline-import-dialog').close();selectedTimelineImport=null;timelineGroupPages.clear();
    await navigateTo({type:'timeline',id:result.timeline.id});
    toast('进度已导入，可以交给 Agent 继续');
  }catch(error){
    if(serial!==timelineImportSerial)return;
    $('timeline-import-error').textContent=error.message;$('timeline-import-error').hidden=false;
  }finally{if(serial===timelineImportSerial){file.disabled=false;button.disabled=!selectedTimelineImport;button.textContent='导入并打开';}}
}
async function downloadTimeline(button){
  const id=activeRoute.id;button.disabled=true;button.textContent='正在准备…';
  try{
    const result=await platformCall('export_timeline',{timeline_id:id});
    const url=URL.createObjectURL(new Blob([JSON.stringify(result.document)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download=result.filename;link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    toast('Timeline 已下载，外部文件保留为引用');
  }finally{button.disabled=false;button.textContent='下载 Timeline';}
}
