'use strict';
let workReadSerial=0;
const workEntryLabels={note:'记录',progress:'进展',decision:'决定',action:'执行',change:'目标 / 限制变更',view:'工作概览',state:'业务状态',result:'已保存结果'};
const timelineGroupPages=new Map(),openTimelineGroups=new Set();
function timelineCards(items){
  return `<div class="progress-list">${items.map(t=>{
    const progress=t.progress, run=t.active_run;
    const timelineUrl=esc(routeHash({type:'timeline',id:t.id}));
    const runLink=run?`<a class="work-run-link" href="${esc(routeHash({type:'run',id:run.id}))}" data-route-link>${timelineRunLabel(run.status)} · ${esc(run.title||run.id)} ${badge(run.status)}</a>`:'暂无当前 Run';
    return `<article class="progress-list-row">
      <a class="work-title-link" href="${timelineUrl}" data-route-link><small>${esc(t.loop_name||'临时工作')}</small><h3>${esc(t.title||t.objective||t.id)}</h3>
      <p>${esc(progress?.text || (t.objective?'目标 · '+t.objective:'尚无进展记录'))}</p>
      ${t.user_action?`<strong class="work-action-note">等待你处理 · ${esc(t.user_action.label)}</strong>`:''}</a>
      <div class="list-meta">${runLink}<time>${esc(runDate(progress?.at||t.created_at))}</time></div></article>`;
  }).join('')}</div>`;
}
async function workbenchPage(args){
  const data=await platformCall('list_timelines',args);
  const ids=data.timelines?.map(t=>t.active_run_id).filter(Boolean)||[];
  if(ids.length){
    const {runs}=await platformCall('list_runs',{run_ids:ids,archived:'include',limit:ids.length});
    const byId=new Map(runs.map(r=>[r.id,r]));
    for(const item of data.timelines){
      const run=byId.get(item.active_run_id);
      item.user_action=run?.user_action;
      item.active_run=run;
    }
  }
  return data;
}
let libraryReadAt=0,libraryMarkup='';
async function showWorkLibrary(background=false){
  if(background && Date.now()-libraryReadAt<10000)return;
  libraryReadAt=Date.now();
  const serial=++workReadSerial;
  if(!background)$('timelines-list').innerHTML='<p class="empty-inline">正在读取 Timeline…</p>';
  const data=await workbenchPage({limit:4});
  if(serial!==workReadSerial||page!=='timelines')return;
  const html=data.groups.length?(data.timelines.length?timelineCards(data.timelines):'')+'<h3 class="work-section-title">按 Loop 浏览</h3>'+data.groups.map(g=>{
    const key=JSON.stringify(g.loop_id);
    return `<details class="timeline-group" data-timeline-group="${esc(key)}" ${openTimelineGroups.has(key)?'open':''}><summary><span class="timeline-group-icon" aria-hidden="true">${g.loop_id===null?'◎':'◇'}</span><span class="timeline-group-name"><strong>${esc(g.name)}</strong><small>${g.loop_id===null?'没有关联 Loop 的工作':esc(g.loop_id)}</small></span><span class="timeline-group-count">${g.count} 条 Timeline</span><span class="timeline-group-chevron" aria-hidden="true">›</span></summary><div class="timeline-group-body"></div></details>`;
  }).join(''):'<div class="work-empty"><span aria-hidden="true">◎</span><h3>从一件想做的事开始</h3><p>与 Agent 讨论目标，Timeline 会保存目标、限制和后续进度。</p></div>';
  if(background && html===libraryMarkup)return;
  $('timelines-list').innerHTML=html;libraryMarkup=html;
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
    const data=await workbenchPage({...(loopId===null?{unbound:true}:{loop_id:loopId}),offset,limit:12});
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
function sourceTaskLink(data,runId,taskId){
  if(!runId || !taskId || !data.runs?.some(r=>r.id===runId))return '';
  return `<a class="progress-link" href="${esc(routeHash({type:'run',id:runId,task:taskId}))}" data-route-link>查看来源节点 ↗</a>`;
}
function evidenceHTML(refs,id,data,sourceTimeline){
  if(!Array.isArray(refs)||!refs.length)return '';
  return refs.map(r=>{
    if(r.run_id && !r.deleted && sourceTimeline===id && !r.record && !r.type)
      return `<a class="progress-link" href="${esc(routeHash({type:'run',id:r.run_id,task:r.task_id}))}" data-route-link>${r.task_id?'查看来源节点':'查看来源 Run'} ↗</a>`;
    if(r.record && r.revision)return `<button class="progress-link" data-work-result="${esc(r.record)}" data-result-revision="${esc(r.revision)}" data-result-timeline="${esc(id)}">${refs.length===1?'查看结果':'结果 · '+esc(r.record)}</button>`;
    if(r.type && r.id && r.revision)return `<button class="progress-link" data-business-timeline="${esc(id)}" data-business-type="${esc(r.type)}" data-business-id="${esc(r.id)}" data-business-revision="${esc(r.revision)}">${esc(r.type)} · ${esc(r.id)}</button>`;
    if(data && r.run_id && r.task_id){
      const link=sourceTaskLink(data,r.run_id,r.task_id);if(link)return link;
    }
    return readerJSON('来源',r);
  }).join('')+'<div class="business-record-detail"></div>';
}
function stateSummaryText(record){
  const summary=record.summary||{};
  const value=Object.keys(summary).length===1 && Object.hasOwn(summary,'value')?summary.value:summary;
  if(value!==null && typeof value!=='object')return String(value);
  const fields=Object.entries(value||{}).filter(([,v])=>v!==null && typeof v!=='object');
  return fields.map(([k,v])=>k+' · '+v).join(' · ') || record.type+' · '+record.id;
}
function recentRecords(rows){
  const rest=rows.slice(3);
  return rows.slice(0,3).join('')+(rest.length?`<details class="work-archive"><summary>展开其余 ${rest.length} 条记录</summary>${rest.join('')}</details>`:'');
}
function businessStateCards(state,id,data){
  if(!state?.total)return '';
  const cards=state.records.map(r=>`<article class="work-entry"><strong>${esc(r.type)} · ${esc(r.id)}</strong><p>${esc(stateSummaryText(r))}</p><button data-business-timeline="${esc(id)}" data-business-type="${esc(r.type)}" data-business-id="${esc(r.id)}" data-business-revision="${esc(r.revision)}">查看记录</button> ${sourceTaskLink(data,r.run_id,r.task_id)}<div class="business-record-detail"></div></article>`);
  return `<section class="work-history"><h3>业务状态 <span>${state.total}</span></h3>${recentRecords(cards)}${state.complete?'':'<p class="small muted">当前显示前 '+state.records.length+' 条，完整记录可通过读取工具分页查询。</p>'}</section>`;
}
function savedResultsHTML(data,id){
  const featured=data.progress?.kind==='result'?data.progress.refs?.[0]:null;
  const records=(data.results?.records||[]).filter(r=>r.id!==featured?.record||r.revision!==featured?.revision);
  if(!records.length)return '';
  return `<section class="work-history"><h3>${featured?'此前结果':'已保存结果'}</h3>${recentRecords(records.map(r=>`<article class="work-entry"><div class="work-entry-meta"><strong>${esc(r.summary||r.type||'节点结果')}</strong><time>${esc(runDate(r.at))}</time></div><button data-work-result="${esc(r.id)}" data-result-timeline="${esc(id)}" data-result-revision="${r.revision}">查看结果</button> ${sourceTaskLink(data,r.source_run_id,r.task_id)}<div class="business-record-detail"></div></article>`))}${data.results.complete?'':'<p class="small muted">这里显示最近 50 份结果，下载文件包含全部记录。</p>'}</section>`;
}
function importSourceHTML(data){
  const source=data.timeline.import_source;
  if(!source)return '';
  return `<section class="timeline-portable"><div class="timeline-portable-heading"><span class="timeline-mark" aria-hidden="true">◎</span><div><strong>从已有进度继续</strong><p>让 Agent 读取这条 Timeline，选择本平台的相关 Loop 推进任务。</p></div></div><details><summary>导入来源</summary><p class="small muted">${esc(source.exported_at?'导出于 '+runDate(source.exported_at):'来自另一份 Timeline')}。已导入任务进度，外部文件仍保留为引用。</p></details></section>`;
}
function chartPoint(x,y,r,label,position,value,className=''){
  return `<circle class="${className}" cx="${x}" cy="${y}" r="${r}" data-chart-point data-chart-label="${esc(label)}" data-chart-position="${esc(position)}" data-chart-value="${esc(value)}"/>`;
}
function chartTooltip(showTime=false){
  return `<output class="chart-tooltip" aria-live="polite" hidden><span class="sr-only" data-chart-description></span><span data-chart-reading></span>${showTime?'<small data-chart-time aria-hidden="true"></small>':''}</output>`;
}
const chartSelections=new WeakMap();
let selectedChart=null;
function chartSelection(svg){
  if(!chartSelections.has(svg)){
    const legends=new Map([...svg.parentElement.querySelectorAll('[data-chart-legend]')].map(el=>[el.dataset.chartLegend,el]));
    const points=[...svg.querySelectorAll('[data-chart-point]')].map(element=>({element,
      x:element.cx.baseVal.value,y:element.cy.baseVal.value,legend:legends.get(element.parentElement.dataset.chartSeries)
    })).sort((a,b)=>a.x-b.x||a.y-b.y);
    chartSelections.set(svg,{points,index:-1});
  }
  return chartSelections.get(svg);
}
function chartSelect(svg,index){
  const figure=svg.parentElement,state=chartSelection(svg),tooltip=figure.querySelector('.chart-tooltip');
  if(index===state.index)return;
  const previous=state.points[state.index];
  previous?.element.classList.remove('active');previous?.legend?.classList.remove('active');
  state.index=index;
  if(index<0){
    if(selectedChart===svg)selectedChart=null;
    tooltip.hidden=true;return;
  }
  if(selectedChart&&selectedChart!==svg)chartSelect(selectedChart,-1);
  selectedChart=svg;
  const {x,y,element,legend}=state.points[index];
  element.classList.add('active');legend?.classList.add('active');
  const {chartLabel,chartPosition,chartValue}=element.dataset;
  tooltip.querySelector('[data-chart-description]').textContent=`${chartLabel}，${chartPosition}，`;
  tooltip.querySelector('[data-chart-reading]').textContent=chartValue;
  const time=tooltip.querySelector('[data-chart-time]');
  if(time)time.textContent=chartPosition;
  tooltip.hidden=false;
  const screen=new DOMPoint(x,y).matrixTransform(svg.getScreenCTM());
  const frame=figure.getBoundingClientRect(),width=tooltip.offsetWidth,height=tooltip.offsetHeight;
  const left=screen.x-frame.left-width/2,above=screen.y-frame.top-height-7;
  tooltip.style.left=Math.max(2,Math.min(left,frame.width-width-2))+'px';
  tooltip.style.top=(above>=0?above:screen.y-frame.top+7)+'px';
}
function chartPointer(event){
  if(event.type==='pointermove'&&event.pointerType==='touch')return;
  const svg=event.target.closest('svg[data-interactive-chart]');
  const matrix=svg?.getScreenCTM();
  if(!matrix)return;
  const {points,index}=chartSelection(svg);
  let nearest=-1,distance=(event.pointerType==='touch'?22:11)**2;
  for(const [i,{x,y}] of points.entries()){
    const dx=matrix.a*x+matrix.c*y+matrix.e-event.clientX;
    const dy=matrix.b*x+matrix.d*y+matrix.f-event.clientY;
    const squared=dx*dx+dy*dy;
    if(squared<distance||(squared===distance&&i===index)){nearest=i;distance=squared;}
  }
  if(event.type==='pointerdown'&&nearest>=0&&nearest===index){
    const {x,y}=points[index],samePoint=p=>p.x===x&&p.y===y;
    const next=points.findIndex((point,i)=>i>index&&samePoint(point));
    nearest=next<0?points.findIndex(samePoint):next;
  }
  chartSelect(svg,nearest);
}
document.addEventListener('pointermove',chartPointer);
document.addEventListener('pointerdown',event=>{
  if(selectedChart&&!selectedChart.contains(event.target))chartSelect(selectedChart,-1);
  chartPointer(event);
});
document.addEventListener('pointerout',event=>{
  const svg=event.target.closest('svg[data-interactive-chart]');
  if(svg&&!svg.contains(event.relatedTarget)&&!svg.matches(':focus-visible')&&event.pointerType!=='touch')chartSelect(svg,-1);
});
document.addEventListener('focusout',event=>{
  if(event.target.matches('svg[data-interactive-chart]'))chartSelect(event.target,-1);
});
document.addEventListener('keydown',event=>{
  const svg=event.target;
  if(!svg.matches('svg[data-interactive-chart]'))return;
  const {points,index}=chartSelection(svg),last=points.length-1;
  const next={ArrowLeft:Math.max(0,index-1),ArrowRight:Math.min(last,index+1),Home:0,End:last,Escape:-1};
  if(!Object.hasOwn(next,event.key))return;
  event.preventDefault();chartSelect(svg,next[event.key]);
});
function observationFigure(series){
  const lines=series.filter(s=>s.points.length);
  if(!lines.length)return '';
  let x0=Infinity,x1=-Infinity,y0=Infinity,y1=-Infinity;
  for(const line of lines)for(const [x,y] of line.points){
    x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y);
  }
  const x=v=>46+(x1===x0?.5:(v-x0)/(x1-x0))*490;
  const y=v=>108-(y1===y0?.5:(v-y0)/(y1-y0))*90;
  const colors=['#315ccb','#b96128','#21806c','#854aa4','#476883'];
  const marks=lines.map((line,i)=>{
    const color=colors[i%colors.length];
    const points=line.points.map(([a,b])=>x(a)+','+y(b)).join(' ');
    return '<g fill="'+color+'" data-chart-series="'+i+'"><polyline fill="none" stroke="'+color+'" stroke-width="2" points="'+points+'"/>'+
      line.points.map(([a,b])=>chartPoint(x(a),y(b),3,line.label,a,b)).join('')+'</g>';
  }).join('');
  const number=n=>esc(new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(n));
  return '<figure class="observation-chart interactive-chart"><svg viewBox="0 0 560 135" data-interactive-chart tabindex="0" role="group" aria-label="'+esc(lines.map(s=>s.label).join('、'))+'，使用方向键查看数据点"><path d="M46 12 V108 H536" fill="none" stroke="#b7c1ce"/><g fill="currentColor" font-size="10"><text x="2" y="22">'+number(y1)+'</text><text x="2" y="110">'+number(y0)+'</text><text x="46" y="126">'+number(x0)+'</text><text text-anchor="end" x="536" y="126">'+number(x1)+'</text></g>'+marks+'</svg>'+chartTooltip()+'<figcaption>'+
    lines.map((s,i)=>'<span data-chart-legend="'+i+'" style="color:'+colors[i%colors.length]+'">● '+esc(s.label)+'</span>').join(' · ')+'</figcaption></figure>';
}
function observationHTML(data,featured){
  if(!data||(!data.views.length&&!data.arrangements.length))return '';
  const views=new Map(data.views.map(v=>[v.name,v])),plans=new Map(data.arrangements.map(a=>[a.name,a]));
  const names=new Set([...(featured?[featured]:[]),...plans.keys(),...views.keys()]);
  const triggerLabels={result:'结果提交',state:'业务状态更新',task:'任务状态变化',run:'运行状态变化',current_run:'接续运行变化',run_deleted:'运行删除',monitor:'监控更新',signal:'指定事件发生'};
  return '<section class="work-history">'+(featured?'':'<h3>工作概览</h3>')+Array.from(names,name=>{
    const view=views.get(name),plan=plans.get(name);
    const status={pending:'等待生成',claimed:'等待生成',preparing:'正在生成',running:'正在生成',remote:'等待执行端',failed:'生成失败',unknown:'上次执行待核实'}[plan?.status];
    const lead=name===featured;
    return (lead?'<article class="progress-focus"><div class="focus-label">'+esc(name)+'<time>'+esc(runDate(view.at))+'</time></div>':'<article class="work-entry"><strong>'+esc(name)+'</strong>')+
      (status?'<p class="small">'+esc(status)+(plan.error?' · '+esc(plan.error):'')+'</p>':'')+
      (view?(view.view.summary?(lead?'<h3>':'<p>')+esc(view.view.summary)+(lead?'</h3>':'</p>'):'')+observationFigure(view.view.series||[])+(view.view.image_png?'<img class="observation-image" alt="'+esc(name)+'" src="data:image/png;base64,'+esc(view.view.image_png)+'">':'')+(lead?'':'<small class="muted">'+esc(runDate(view.at))+'</small>'):'')+
      (plan?'<details><summary>当前安排</summary><p>'+esc(plan.description||'')+'</p><p class="small muted">'+esc(plan.on?(triggerLabels[plan.on.kind]||plan.on.kind)+'时更新':plan.next_at?'定时生成':'手动生成')+
        (plan.next_at?' · 下次 '+esc(runDate(plan.next_at)):'')+'</p><button data-refresh-observation="'+esc(name)+'" data-observation-run="'+esc(plan.run_id)+'">立即生成</button></details>':'')+'</article>';
  }).join('')+'</section>';
}
function workEntryHTML(e,id,data){
  return `<article class="work-entry"><div class="work-entry-meta"><strong>${esc(workEntryLabels[e.kind]||e.kind)}</strong><time>${esc(runDate(e.at))}</time></div><p>${esc(e.text)}</p>${evidenceHTML(e.refs,id,data,e.source_timeline_id)}</article>`;
}
function timelineSections(data,id){
  const active=data.runs.find(r=>r.id===data.timeline.active_run_id);
  const titles=new Set(),duplicates=new Set();
  for(const r of data.runs){if(titles.has(r.title))duplicates.add(r.title);titles.add(r.title);}
  const runLink=r=>`<a class="timeline-run-link" href="${esc(routeHash({type:'run',id:r.id}))}" data-route-link><span>${esc(r.title||r.id)}${r.title&&duplicates.has(r.title)?` <code>${esc(r.id)}</code>`:''}</span>${badge(r.status)} <span aria-hidden="true">›</span></a>`;
  const others=data.runs.filter(r=>r!==active);
  const loopHistory=new Map();
  for(const r of others){
    if(!loopHistory.has(r.loop_id))loopHistory.set(r.loop_id,[]);
    loopHistory.get(r.loop_id).push(r);
  }
  const p=data.progress;
  const featured=p?.kind==='view' && data.observations?.views.some(v=>v.name===p.name)?p.name:null;
  const trail=(data.business_state?.records||[]).map(r=>({
    at:r.at,kind:'state',text:stateSummaryText(r),refs:[{type:r.type,id:r.id,revision:r.revision},...(r.refs||[])]
  })).concat((data.recent_entries||data.entries).filter(e=>['note','progress','decision'].includes(e.kind)&&e.actor!=='platform'))
    .sort((a,b)=>b.at-a.at).filter(e=>e.at!==p?.at || e.kind!==p?.kind).slice(0,4);
  return {
    'work-intent':`<div class="timeline-intent progress-intent"><p>${esc(data.timeline.objective||'尚未记录目标')}</p>${data.timeline.constraints?`<details><summary>工作限制</summary><p>${esc(data.timeline.constraints)}</p></details>`:''}</div>`,
    'work-run-relation':active?`<div class="run-relation"><strong>${timelineRunLabel(active.status)}</strong>${runLink(active)}</div>`:
      `<p class="empty-relation">${others.length?'暂无当前 Run':'本平台暂无关联 Run'}</p>`,
    'work-focus':featured?'':`<section class="progress-focus"><div class="focus-label">${esc(p?workEntryLabels[p.kind]:'当前进展')}${p?.at?`<time>${esc(runDate(p.at))}</time>`:''}</div>
      <h3>${esc(p?.text||'尚未提交业务进展')}</h3>${evidenceHTML(p?.refs,id,data,p?.source_timeline_id)}${p?.evidence?.length?`<details class="focus-evidence"><summary>判断依据 · ${p.evidence.length}</summary>${evidenceHTML(p.evidence,id,data)}</details>`:''}${sourceTaskLink(data,p?.run_id,p?.task_id)}
      </section>`,
    'timeline-observations':observationHTML(data.observations,featured),
    'work-trail':trail.length?`<section class="work-history progress-trail"><h3>近期工作脉络</h3>${trail.map(e=>workEntryHTML(e,id,data)).join('')}</section>`:'',
    'work-state':businessStateCards(data.business_state,id,data),
    'work-results':savedResultsHTML(data,id),
    'work-runs':others.length?`<section class="timeline-linked"><h3>历史 Run</h3>${[...loopHistory.values()].map(group=>`<details class="loop-run-history"><summary>${esc(group[0].loop_name||group[0].loop_id||'关联运行')} · ${group.length} 次运行</summary>${group.map(runLink).join('')}</details>`).join('')}</section>`:'',
    'work-source':importSourceHTML(data)
  };
}
let timelinePollAt=0,timelinePolling=false;
async function refreshObservations(force=false){
  const id=activeRoute.id,root=$('work-focus'),serial=workReadSerial;
  if(!root||timelinePolling||(!force&&Date.now()-timelinePollAt<5000))return;
  timelinePolling=true;timelinePollAt=Date.now();
  try{
    const data=await platformCall('read_work_timeline',{timeline_id:id,newest_first:true,limit:15});
    if(root!==$('work-focus')||page!=='timeline'||activeRoute.id!==id||serial!==workReadSerial)return;
    $('timeline-title').textContent=data.timeline.title||'Timeline';
    const archive=$('work-entries');
    if(archive && data.entries.length){
      const first=archive.latestSequence||0;
      const recent=data.entries.filter(e=>e.sequence>first);
      if(recent.length){
        if(!first || (data.has_more && recent.length===data.entries.length)){
          archive.innerHTML=data.entries.map(e=>workEntryHTML(e,id,data)).join('')+olderEntriesButton(data,id);
        }else archive.insertAdjacentHTML('afterbegin',recent.map(e=>workEntryHTML(e,id,data)).join(''));
        archive.latestSequence=data.entries[0].sequence;
      }
    }
    for(const [key,html] of Object.entries(timelineSections(data,id))){
      const section=$(key);
      if(section.lastMarkup!==html){
        const opened=[...section.querySelectorAll('details[open]')].map(el=>el.querySelector('summary')?.textContent);
        section.innerHTML=html;section.lastMarkup=html;
        for(const el of section.querySelectorAll('details'))if(opened.includes(el.querySelector('summary')?.textContent))el.open=true;
      }
    }
  }finally{timelinePolling=false;}
}
function olderEntriesButton(data,id){
  return data.has_more?`<button id="work-more" data-work-timeline="${esc(id)}" data-after="${data.cursor}">查看更早记录</button>`:'';
}
async function showWorkTimeline(id,after=0){
  const serial=++workReadSerial;
  if(!after){$('timeline-title').textContent='Timeline';$('timeline-content').innerHTML='<p class="empty-inline">正在读取工作进度…</p>';}
  const data=await platformCall('read_work_timeline',{timeline_id:id,after,newest_first:true,limit:15});
  if(serial!==workReadSerial||page!=='timeline'||activeRoute.id!==id)return;
  $('timeline-title').textContent=data.timeline.title||'Timeline';
  const entries=data.entries.map(e=>workEntryHTML(e,id,data)).join('');
  if(!after){
    const sections=timelineSections(data,id);
    $('timeline-content').innerHTML=Object.entries(sections).map(([key,html])=>`<div id="${key}">${html}</div>`).join('')+
      `<details class="work-archive"><summary>全部工作记录</summary><div id="work-entries">${entries||'<p class="muted">还没有记录。</p>'}</div></details>`;
    for(const [key,html] of Object.entries(sections))$(key).lastMarkup=html;
    $('work-entries').latestSequence=data.entries[0]?.sequence||0;
    timelinePollAt=Date.now();
  }else{$('work-more')?.remove();$('work-entries').insertAdjacentHTML('beforeend',entries);}
  if(data.has_more)$('work-entries').insertAdjacentHTML('beforeend',olderEntriesButton(data,id));
}
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.refreshObservation){
    await platformCall('submit_run_request',{run_id:button.dataset.observationRun,request_id:randomKey(),
      operation:'refresh_observation',arguments:{name:button.dataset.refreshObservation}});
    await refreshObservations(true);return;
  }
  if(button.dataset.workResult){
    const data=await platformCall('read_work_result',{timeline_id:button.dataset.resultTimeline,id:button.dataset.workResult,revision:Number(button.dataset.resultRevision)});
    button.parentElement.querySelector('.business-record-detail').innerHTML=resultView(data.record.value)+readerJSON('结果与来源',data.record);
  }
  if(button.dataset.businessTimeline){
    const data=await platformCall('read_business_state',{timeline_id:button.dataset.businessTimeline,type:button.dataset.businessType,id:button.dataset.businessId,...(button.dataset.businessRevision?{revision:Number(button.dataset.businessRevision)}:{})});
    button.parentElement.querySelector('.business-record-detail').innerHTML=resultView(data.records[0]?.value)+readerJSON('记录与来源',data.records[0]||{})+evidenceHTML(data.records[0]?.refs,button.dataset.businessTimeline);
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
    selectedTimelineImport={file,request_id:randomKey()};
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
    const response=await fetch('/api/timelines/import',{method:'POST',
      headers:{'Content-Type':'application/json','X-Loop-Anything':'workspace','X-Request-Id':selection.request_id},
      body:selection.file});
    if(!response.ok)throw new Error((await response.json()).error||'导入失败');
    const result=await response.json();
    if(serial!==timelineImportSerial)return;
    $('timeline-import-dialog').close();selectedTimelineImport=null;timelineGroupPages.clear();
    await navigateTo({type:'timeline',id:result.timeline_id});
    toast('进度已导入，可以交给 Agent 继续');
  }catch(error){
    if(serial!==timelineImportSerial)return;
    $('timeline-import-error').textContent=error.message;$('timeline-import-error').hidden=false;
  }finally{if(serial===timelineImportSerial){file.disabled=false;button.disabled=!selectedTimelineImport;button.textContent='导入并打开';}}
}
async function downloadTimeline(button){
  const id=activeRoute.id;button.disabled=true;button.textContent='正在准备…';
  try{
    const response=await fetch('/api/timelines/'+encodeURIComponent(id)+'/file');
    if(!response.ok)throw new Error((await response.json()).error||'下载失败');
    const url=URL.createObjectURL(await response.blob());
    const link=document.createElement('a');link.href=url;link.download=id+'.timeline.json';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    toast('Timeline 已下载，外部文件保留为引用');
  }finally{button.disabled=false;button.textContent='下载 Timeline';}
}
