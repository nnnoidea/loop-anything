'use strict';
let runOffset=0,runNext=null,runTotal=0,runQuerySerial=0;
const knownPeople=new Set(), knownRunLoops=new Map(), relatedRunPages=new Map();
const runDate=value=>value?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):'—';
function dateBound(value,end=false){
  if(!value)return null;
  const date=new Date(value+'T00:00:00');if(end)date.setDate(date.getDate()+1);
  return date.getTime()/1000;
}
function runFilters(){
  const args={limit:30,offset:runOffset,sort:$('runs-sort').value,order:$('runs-order').value,archived:$('runs-archived').value};
  for(const [id,key] of [['query','query'],['status','status'],['loop','loop_id'],['kind','kind']])if($('runs-'+id).value)args[key]=$('runs-'+id).value;
  if($('runs-person').value!=='*')args.created_by=$('runs-person').value;
  for(const [id,key,end] of [['created-from','created_from',false],['created-to','created_to',true],['active-from','active_from',false],['active-to','active_to',true]]){
    const value=dateBound($('runs-'+id).value,end);if(value!==null)args[key]=value;
  }
  // Hierarchy is for ordinary browsing; an exact filter must not hide matching children.
  args.root_only=args.archived==='exclude'&&!['query','status','loop_id','kind','created_by','created_from','created_to','active_from','active_to'].some(key=>Object.hasOwn(args,key));
  return args;
}
function runSummaryHTML(row){
  return `<button class="run-item ${selected===row.id?'chosen':''}" data-run="${esc(row.id)}"><strong>${esc(row.title)}</strong><small>${esc(labels[row.status]||row.status)} · ${esc(row.loop_name||'Loop')}${row.archived_at?' · 已归档':''}</small><small>启动 ${esc(runDate(row.created_at))}</small><small>活跃 ${esc(runDate(row.last_activity_at))}</small>${row.parent_run_id?'<small>子 Run</small>':''}</button>${row.child_count?`<details class="run-children" data-run-children="${esc(row.id)}"><summary>子 Run · ${row.child_count}</summary><div class="run-child-list"></div></details>`:''}`;
}
function groupedRunsHTML(rows,groups=[]){
  const people=new Map();for(const row of rows){const name=row.created_by||'';if(!people.has(name))people.set(name,[]);people.get(name).push(row);}
  return [...people].map(([name,items])=>`<details class="run-person" data-run-person="${esc(name)}" open><summary>${esc(name||'未署名')} <span>本页 ${items.length} / 共 ${groups.find(g=>g.created_by===name)?.count??items.length}</span></summary>${items.map(runSummaryHTML).join('')}</details>`).join('')||'<p class="small muted">没有匹配的运行。</p>';
}
async function refreshRunLibrary(){
  const serial=++runQuerySerial,args=runFilters(),key=JSON.stringify(args);
  const result=await api('runs?'+new URLSearchParams(args));
  if(serial!==runQuerySerial||key!==JSON.stringify(runFilters()))return;
  if(runOffset&&runOffset>=result.total){runOffset=result.total?Math.floor((result.total-1)/args.limit)*args.limit:0;return refreshRunLibrary();}
  runs=result.runs;runNext=result.next_offset;runTotal=result.total;
  for(const group of result.groups)knownPeople.add(group.created_by);
  const person=$('runs-person'),chosen=person.value;
  const peopleHTML='<option value="*">全部人</option>'+[...knownPeople].sort().map(n=>`<option value="${esc(n)}">${esc(n||'未署名')}</option>`).join('');
  if(person.innerHTML!==peopleHTML){person.innerHTML=peopleHTML;person.value=chosen;}
  for(const item of catalog)knownRunLoops.set(item.loop_definition.id,item.loop_definition.name||item.loop_definition.id);
  for(const item of result.loops||[])if(item.loop_id)knownRunLoops.set(item.loop_id,item.name||item.loop_id);
  const selector=$('runs-loop'),loop=selector.value;
  const loopHTML='<option value="">全部 Loop</option>'+[...knownRunLoops].map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');
  if(selector.innerHTML!==loopHTML){selector.innerHTML=loopHTML;selector.value=loop;}
  const html=groupedRunsHTML(runs,result.groups);
  if(html!==listSignature){
    const closed=new Set([...$('run-list').querySelectorAll('.run-person:not([open])')].map(el=>el.dataset.runPerson));
    const children=new Map([...$('run-list').querySelectorAll('.run-children[open]')].map(el=>[el.dataset.runChildren,el.dataset.childOffset||'0']));
    $('run-list').innerHTML=html;listSignature=html;
    for(const el of $('run-list').querySelectorAll('.run-person'))if(closed.has(el.dataset.runPerson))el.open=false;
    for(const el of $('run-list').querySelectorAll('.run-children'))if(children.has(el.dataset.runChildren)){el.dataset.childOffset=children.get(el.dataset.runChildren);el.open=true;}
  }
  $('runs-page').textContent=result.total?`${runOffset+1}–${runOffset+runs.length} / ${result.total}`:'0 条';
  $('runs-prev').disabled=runOffset===0;$('runs-next').disabled=runNext===null;
  await Promise.all([...$('run-list').querySelectorAll('.run-children[open]')].map(element=>showRunChildren(element)));
}
async function showRunChildren(element,offset){
  if(offset===undefined&&element.dataset.childLoading==='true')return;
  offset??=Number(element.dataset.childOffset||0);
  const id=element.dataset.runChildren;
  const serial=Number(element.dataset.childRequest||0)+1;element.dataset.childRequest=String(serial);
  element.dataset.childOffset=String(offset);element.dataset.childLoading='true';
  try{
    const data=await api('runs?'+new URLSearchParams({parent_run_id:id,archived:'include',limit:20,offset}));
    if(!element.isConnected||element.dataset.childRequest!==String(serial))return;
    if(offset&&offset>=data.total)return showRunChildren(element,data.total?Math.floor((data.total-1)/20)*20:0);
    const container=element.querySelector('.run-child-list');
    const html=data.runs.map(runSummaryHTML).join('')+`<div class="run-pagination">${offset?`<button data-child-page="${Math.max(0,offset-20)}">上一页</button>`:''}<small>${data.total} 条</small>${data.next_offset!==null?`<button data-child-page="${data.next_offset}">下一页</button>`:''}</div>`;
    if(container.dataset.signature!==html){
      const expanded=new Map([...container.querySelectorAll('.run-children[open]')].map(el=>[el.dataset.runChildren,el.dataset.childOffset||'0']));
      container.innerHTML=html;container.dataset.signature=html;
      for(const child of container.querySelectorAll('.run-children'))if(expanded.has(child.dataset.runChildren)){child.dataset.childOffset=expanded.get(child.dataset.runChildren);child.open=true;}
    }
  }finally{if(element.dataset.childRequest===String(serial))element.dataset.childLoading='false';}
}
async function refreshRelatedRuns(key,offset,force=false){
  const old=relatedRunPages.get(key);
  offset??=old?.data?.offset||0;
  if(!force&&old&&(old.loading||Date.now()-old.at<5000))return;
  const request=Symbol('related-runs');relatedRunPages.set(key,{...old,loading:true,request});
  try{
    const data=await api('runs?'+new URLSearchParams({loop_key:key,archived:'include',limit:20,offset}));
    if(relatedRunPages.get(key)?.request!==request)return;
    if(offset&&offset>=data.total)return refreshRelatedRuns(key,data.total?Math.floor((data.total-1)/20)*20:0,true);
    relatedRunPages.set(key,{data,at:Date.now(),loading:false,request});
    if(page==='editor'&&editor?.installedKey===key)renderRelatedRuns(key);
  }catch(error){if(relatedRunPages.get(key)?.request===request)relatedRunPages.delete(key);throw error;}
}
function relatedRunRows(key){
  const data=relatedRunPages.get(key)?.data;
  if(!data)return '<p class="small muted">正在读取运行…</p>';
  const people=new Map();for(const row of data.runs){const name=row.created_by||'';if(!people.has(name))people.set(name,[]);people.get(name).push(row);}
  const shortDate=value=>value?new Date(value*1000).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'—';
  const groups=[...people].map(([name,items],index)=>`<details class="related-run-group" data-related-person="${esc(name)}" ${index===0?'open':''}><summary><span class="related-person-icon" aria-hidden="true">${esc(Array.from(name||'未')[0])}</span><strong>${esc(name||'未署名')}</strong><span class="related-person-count">本页 ${items.length} / 共 ${data.groups?.find(g=>g.created_by===name)?.count??items.length}</span><span class="related-chevron" aria-hidden="true">›</span></summary><div class="related-run-rows">${items.map(r=>`<a class="related-run-row" href="${esc(routeHash({type:'run',id:r.id}))}" data-route-link><span class="related-run-name"><strong>${esc(r.title)}</strong><small>启动 ${esc(shortDate(r.created_at))}${r.parent_run_id?' · 子 Run':''}${r.archived_at?' · 已归档':''}</small></span>${badge(r.status)}<span class="related-run-activity"><small>最近活跃</small><time title="${esc(runDate(r.last_activity_at))}">${esc(shortDate(r.last_activity_at))}</time></span><span class="related-row-arrow" aria-hidden="true">↗</span></a>`).join('')}</div></details>`).join('');
  return `<section class="related-runs"><header><div><h3>运行记录 <span>${data.total}</span></h3><p>这个版本 · 按发起人分组 · 最近活跃优先</p></div><span class="related-page-range">${data.total?`${data.offset+1}–${data.offset+data.runs.length} / ${data.total}`:'0 条'}</span></header>${groups||'<p class="related-runs-empty">还没有运行记录。启动后，可以在这里查看进展。</p>'}${data.offset||data.next_offset!==null?`<div class="run-pagination"><button data-related-key="${esc(key)}" data-related-page="${Math.max(0,data.offset-20)}" ${data.offset?'':'disabled'}>← 上一页</button><small>每页最多 20 条</small><button data-related-key="${esc(key)}" data-related-page="${data.next_offset??data.offset}" ${data.next_offset===null?'disabled':''}>下一页 →</button></div>`:''}</section>`;
}
function renderRelatedRuns(key){
  const container=$('reader-runs');if(!container)return;
  const html=relatedRunRows(key);if(container.dataset.signature===html)return;
  const groups=new Map([...container.querySelectorAll('[data-related-person]')].map(el=>[el.dataset.relatedPerson,el.open]));
  container.innerHTML=html;container.dataset.signature=html;
  for(const element of container.querySelectorAll('[data-related-person]'))if(groups.has(element.dataset.relatedPerson))element.open=groups.get(element.dataset.relatedPerson);
}
let runFilterTimer;
document.addEventListener('input',event=>{
  if(!event.target.closest('.run-filters'))return;
  clearTimeout(runFilterTimer);runOffset=0;++runQuerySerial;
  runFilterTimer=setTimeout(()=>safely(refreshRunLibrary),event.target.id==='runs-query'?250:0);
});
document.addEventListener('toggle',event=>{
  if(event.target.matches?.('[data-run-children]')&&event.target.open)safely(()=>showRunChildren(event.target));
},true);
document.addEventListener('change',event=>{if(event.target.id==='show-archived-loops')safely(loadCatalog);});
document.addEventListener('click',event=>safely(async()=>{
  const target=event.target.closest('button');if(!target)return;
  if(target.id==='runs-prev'||target.id==='runs-next'){runOffset=target.id==='runs-prev'?Math.max(0,runOffset-30):runNext??runOffset;await refreshRunLibrary();}
  if(target.dataset.childPage!==undefined)await showRunChildren(target.closest('[data-run-children]'),Number(target.dataset.childPage));
  if(target.dataset.relatedKey)await refreshRelatedRuns(target.dataset.relatedKey,Number(target.dataset.relatedPage),true);
  if(target.id==='archive-run'&&run){await platformCall('update_run',{run_id:run.id,metadata_revision:run.metadata_revision||0,archived:!run.archived_at});runOffset=0;await refresh();}
  if(target.id==='delete-run'&&run&&confirm('删除这次运行的记录和结果？这不会停止外部任务，原生 Agent 会话与外部产物会保留。')){
    await platformCall('delete_run',{run_id:run.id,metadata_revision:run.metadata_revision||0});run=null;selected=null;runOffset=0;await navigateTo({type:'home'});await refresh();
  }
  if(target.dataset.loopArchive){await platformCall('archive_loop',{key:target.dataset.loopArchive,archived:target.dataset.archived!=='true'});await loadCatalog();}
  if(target.dataset.loopDelete&&confirm('删除这个 Loop 版本？已有运行仍依赖它时，请使用归档。')){await platformCall('delete_loop',{key:target.dataset.loopDelete});await loadCatalog();}
}));

if(window.matchMedia('(max-width: 650px)').matches)$('run-browser').open=false;
