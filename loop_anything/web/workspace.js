'use strict';
let selectedTask=null,taskOrder='graph',taskSearch='',taskStatus='',taskRound='',taskEdit=null,taskChanges=new Set(),taskNumbers=new Map();
const expandedRounds=new Set(),mobileTaskGraph=window.matchMedia('(max-width:650px)'),inlineTaskDetail=window.matchMedia('(max-width:960px)');
const roundStateKey=id=>'loop-anything.open-rounds.'+id;
function restoreRounds(id){
  expandedRounds.clear();
  try{
    const stored=JSON.parse(sessionStorage.getItem(roundStateKey(id))||'[]');
    if(Array.isArray(stored))for(const round of stored)if(typeof round==='string')expandedRounds.add(round);
  }catch{}
}
function rememberRounds(){
  try{sessionStorage.setItem(roundStateKey(run.id),JSON.stringify([...expandedRounds]));}catch{}
}
function syncRunTaskRoute(){
  if(page!=='runs'||activeRoute.type!=='run'||activeRoute.id!==run.id)return;
  const route={type:'run',id:run.id,...(selectedTask?{task:selectedTask}:{})};
  if(routeHash(route)===routeHash(activeRoute))return;
  activeRoute=route;
  history.replaceState(null,'',routeHash(route));
}
const taskTime=t=>t?new Date(t*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'尚未开始';
const taskLabel=t=>run.loop_definition.nodes[t.spec.node]?.label || t.spec.node;
function flowDecisions(t){return Object.values(run.tasks).filter(d=>d.origin?.flow_agent?.task_id===t.id);}
function flowDecisionButtons(t,compact=false){const decisions=flowDecisions(t);return (compact?decisions.slice(-1):decisions).map(d=>`<button class="flow-decision-link" data-task-focus="${esc(d.id)}">✦ 决策 · ${esc(labels[d.status]||d.status)}</button>`).join('');}
const readingNumber=new Intl.NumberFormat('zh-CN',{maximumSignificantDigits:7});
function readingValue(value){
  return typeof value==='number'?readingNumber.format(value):typeof value==='boolean'?(value?'是':'否'):value;
}
function readingText(r){return r.label+' '+readingValue(r.value)+(r.unit?' '+r.unit:'');}
function taskStatusLabel(item){
  const attempt=item.attempts.at(-1);
  if(item.tasks.status==='waiting' && attempt?.implementation?.kind==='external' && !attempt.observation_error &&
      String(attempt.activity_progress?.external_status).toUpperCase()==='RUNNING')return '外部运行中';
  return labels[item.tasks.status]||item.tasks.status;
}
function taskBadge(item){return `<span class="badge ${esc(item.tasks.status)}">${esc(taskStatusLabel(item))}</span>`;}
function taskReadout(item,attempt=item.attempts.at(-1)){
  const fields=run.loop_definition.nodes[item.tasks.spec.node]?.readout;
  return attempt?.output_readout?.length?attempt.output_readout:TaskHistory.readings(fields,attempt?.activity_progress);
}
function taskSummary(item){
  const t=item.tasks,e=item.attempts.at(-1);
  if(t.status==='cancelled')return t.cancellation_reason||'未记录具体原因';
  if(e?.observation_error)return '采集异常，外部任务状态待确认';
  if(['fault','stale'].includes(t.status))return taskFailureText(t,e);
  const facts=taskReadout(item);
  if(facts[0]?.source==='outputs')return readingText(facts[0]);
  if(facts.length)return (t.status==='completed'?'最后回报 · ':'')+facts.map(readingText).join(' · ');
  if(e?.child_run_id&&e.status==='waiting')return '子 Loop · '+(labels[e.child_status]||e.child_status||'等待中');
  if(e?.status==='waiting'&&['timer','event','approval'].includes(e.implementation.kind))return waitSummary(e.implementation);
  if(t.wait_reasons?.length)return waitReasonText(t.wait_reasons[0]);
  return '';
}
function taskFailureText(task,attempt){
  return attempt?.failure_summary||task?.failure_summary||(task?.status==='stale'?'执行状态需要核实。':'本次执行失败，可请 Agent 核对。');
}
function runProgressHTML(value){
  if(value.superseded_by){
    const latest=value.timeline?.active_run_id;
    const next=latest?{type:'run',id:latest}:{type:'timeline',id:value.timeline_id};
    const label=!latest?'查看所属 Timeline':latest===value.superseded_by?'查看接续 Run':'查看最新 Run';
    return `<section class="progress-focus" data-tone="quiet"><div class="focus-label">历史 Run · 已接续</div>
      <h2>这次运行已由后续 Run 接着推进</h2>
      <a class="progress-link" href="${esc(routeHash(next))}" data-route-link>${label} →</a></section>`;
  }
  const rows=TaskHistory.rows(value);
  const ended=['completed','terminated','continued'].includes(value.status);
  const final=new Set(['completed','skipped','cancelled']);
  const pending=rows.filter(item=>!final.has(item.tasks.status));
  const priorities=['waiting_user','approval','fault','stale','unresolved','executing','waiting','decision','retrying','ready','blocked','planned'];
  const rank=item=>{
    if(item.attempts.at(-1)?.observation_error)return 2;
    if(item.attempts.at(-1)?.status==='approval')return 1;
    if(item.tasks.status==='held')return 1;
    const i=priorities.indexOf(item.tasks.status);return i<0?priorities.length:i;
  };
  const completed=rows.filter(i=>i.tasks.status==='completed').sort((a,b)=>(b.completed||0)-(a.completed||0));
  let focus=pending.sort((a,b)=>rank(a)-rank(b));
  if(ended || !pending.length)focus=completed.slice(0,1);
  const primary=focus[0];
  const caption=value.status==='paused'?'运行已暂停':ended?'运行已结束':!pending.length?'执行进度':
      rank(primary)<=4?'需要关注':taskStatusLabel(primary)==='外部运行中'?'外部运行中':primary.tasks.status==='waiting'?'当前等待':'当前执行';
  const title=primary?taskLabel(primary.tasks):ended?'没有已完成的节点':rows.length?'已安排的节点均已结束':'尚未安排任务';
  function detail(item){
    const t=item.tasks,e=item.attempts.at(-1);
    if(e?.observation_error)return '采集异常，外部任务状态待确认';
    if(t.status==='waiting_user')return value.task_dispositions?.[t.id]?.reason || '等待用户处理';
    if(e?.status==='approval')return '等待用户确认';
    if(t.status==='held')return '执行前已暂停，可到通知与控制查看放行条件。';
    if(['fault','stale'].includes(t.status))return taskFailureText(t,e);
    return t.wait_reasons?.length?waitReasonText(t.wait_reasons[0]):taskSummary(item) || labels[t.status] || t.status;
  }
  const link=(item,text)=>`<a class="progress-link" data-route-link href="${esc(routeHash({type:'run',id:value.id,task:item.tasks.id}))}">${esc(text)} ↗</a>`;
  const more=focus.slice(1);
  const next=!ended && primary?pending.filter(i=>i.dependencies.includes(primary.tasks.id)):[];
  const repairs=more.filter(i=>i.tasks.status==='executing' && i.tasks.origin?.fallback &&
    i.tasks.origin.issues?.some(issue=>issue.task_id===primary?.tasks.id));
  const alongside=more.filter(i=>!next.includes(i)&&!repairs.includes(i));
  const parallel=new Map();
  for(const item of alongside){
    const key=JSON.stringify([item.tasks.spec.node,taskStatusLabel(item)]);
    if(!parallel.has(key))parallel.set(key,[]);
    parallel.get(key).push(item);
  }
  const sideRows=[...parallel.values()].map(group=>{
    const i=group[0],t=i.tasks;
    return group.length===1?`<li>${link(i,[taskLabel(t),i.round,t.spec.ref].filter(Boolean).join(' · '))}${taskBadge(i)}</li>`:
      `<li><button class="progress-link" data-focus-group="${esc(t.spec.node)}" data-focus-round="${esc(i.round||'')}">${esc(taskLabel(t))} · ${group.length} 项${esc(taskStatusLabel(i))} →</button></li>`;
  }).join('');
  const failed=primary?.tasks.status==='fault';
  const recentResult=completed.find(i=>i!==primary&&taskReadout(i).some(f=>f.source==='outputs'));
  const nextNames=next.slice(0,2).map(i=>link(i,taskLabel(i.tasks))).join(' · ');


  return `<section class="progress-focus" data-tone="${ended||value.status==='paused'?'quiet':primary&&rank(primary)<=4?'attention':'live'}">
    <div class="focus-label">${failed && repairs.length && !ended && value.status!=='paused'?'正在处理异常':caption}<time>${value.last_activity_at?'最近变化 '+esc(taskTime(value.last_activity_at)):''}</time></div>
    <h2>${esc(title)}${failed?'失败':''}</h2>${primary && (primary.round||primary.tasks.spec.ref)?`<small>${esc([primary.round,primary.tasks.spec.ref].filter(Boolean).join(' · '))}</small>`:''}${primary?`<p>${ended||!pending.length?'最近完成 · ':''}${esc(detail(primary))}</p>${link(primary,'查看节点详情')}`:''}
    ${repairs.length?`<p>正在处理 · ${repairs.map(i=>link(i,taskLabel(i.tasks))).join(' · ')}</p>`:''}
    ${next.length?`<div class="next-work">后续已安排 · ${nextNames}${next.length>2?' 等 '+next.length+' 项':''}</div>`:''}
    ${parallel.size&&parallel.size<=2?`<ul class="also-working">${sideRows}</ul>`:alongside.length?`<details class="parallel-work"><summary>其他待推进任务 · ${alongside.length}</summary><ul>${sideRows}</ul></details>`:''}
    ${recentResult?`<div class="next-work">最近结果 · ${link(recentResult,[recentResult.round,recentResult.tasks.spec.ref||taskLabel(recentResult.tasks)].filter(Boolean).join(' · '))}　${esc(taskSummary(recentResult))}</div>`:''}
    <footer>已完成 ${completed.length} / ${rows.length} 项已安排任务</footer></section>`;
}
function taskCard(item){
  const t=item.tasks,order=taskNumbers.get(t.id),attempt=item.attempts.at(-1),agent=attempt?.implementation.kind==='agent',active=attempt?.worker_active||(run.agent_sessions||[]).some(o=>o.resume_execution===attempt?.id);
  return `<article class="process-task ${selectedTask===t.id?'picked':''}" data-status="${esc(t.status)}" data-task-focus="${esc(t.id)}" data-task-row="${esc(t.id)}"><button class="task-card-main" data-task-focus="${esc(t.id)}" aria-pressed="${selectedTask===t.id}" title="${esc([taskLabel(t),t.spec.ref,t.id].filter(Boolean).join(' · '))}"><span class="task-card-top">${taskOrder==='time'?`<small class="task-number">${String(order).padStart(2,'0')}</small>`:''}${taskBadge(item)}${taskChanges.has(t.id)?'<span data-change-mark>已调整</span>':''}</span><span class="task-name">${esc(taskLabel(t))}</span>${t.spec.ref?`<small class="task-card-ref">${esc(t.spec.ref)}</small>`:''}<span class="task-summary">${esc(taskSummary(item))}</span><small class="task-card-time">${esc([item.round,item.started===null&&['skipped','cancelled'].includes(t.status)?'未执行':taskTime(item.started)].filter(Boolean).join(' · '))}</small></button><div class="task-card-actions">${flowDecisionButtons(t,true)}${agent?`<button data-agent-session="${esc(attempt.id)}" ${['completed','terminated','continued'].includes(run.status)&&!active?'disabled title="Run 已结束，可查看结果与会话记录"':''}>${active?'打开会话':'恢复会话'}</button>`:''}</div></article>`;
}
const taskCardWidth=224,taskCardHeight=160,roundHeadingHeight=44;
let showTaskOrigins=false;
function roundHeading(card,filtered){
  const title=card.round||'未标注轮次';
  const cancelled=card.members.filter(item=>item.tasks.status==='cancelled').length;
  const completed=card.members.length-cancelled;
  const count=[completed&&`已完成 ${completed}`,cancelled&&`已取消 ${cancelled}`].filter(Boolean).join(' · ');
  const toggle=`data-round-toggle="${esc(card.round)}" aria-expanded="${card.open}"`;
  const heading=`<strong>${esc(title)}</strong><small>${count}</small>`;
  if(card.open)return filtered
    ?`<div class="round-heading">${heading}</div>`
    :`<button class="round-heading" ${toggle} aria-label="收起 ${esc(title)}">${heading}<span aria-hidden="true">收起 ⌃</span></button>`;
  const recent=card.members.findLast(item=>item.tasks.status==='completed'&&taskReadout(item).some(f=>f.source==='outputs'));
  return `<button class="round-card" ${toggle}>${heading}${recent?`<small>${esc(taskSummary(recent))}</small>`:''}<span class="round-action">展开节点 <span aria-hidden="true">⌄</span></span></button>`;
}

function layoutTaskGraph(nodes,links,mobile,insideRound=false){
  const margin=insideRound?19:30,gap=mobile?28:26,columnGap=insideRound?54:70;
  const parents=new Map(nodes.map(node=>[node.id,[]]));
  for(const {from,to,kind} of links)if(kind==='dependency')parents.get(to).push(from);
  const levels=new Map(),pending=new Set(parents.keys());
  while(pending.size){
    const ready=[...pending].filter(id=>parents.get(id).every(from=>levels.has(from)));
    // Contracting nodes into a round can create a cycle between groups.
    for(const id of ready.length?ready:[pending.values().next().value]){
      const previous=parents.get(id).filter(from=>levels.has(from));
      levels.set(id,Math.max(0,...previous.map(from=>levels.get(from)+1)));
      pending.delete(id);
    }
  }
  const columns=[],positions=new Map();
  for(const node of nodes)(columns[levels.get(node.id)]??=[]).push(node);
  const columnWidths=columns.map(column=>Math.max(...column.map(node=>node.width)));
  const width=2*margin+(mobile?Math.max(...columnWidths):columnWidths.reduce((sum,w)=>sum+w,0)+columnGap*(columns.length-1));
  let height;
  if(mobile){
    let y=margin;
    columns.flat().forEach(({id,width,height},order)=>{
      positions.set(id,{x:margin,y,width,height,order});
      y+=height+gap;
    });
    height=y-gap+margin;
  }else{
    const columnHeights=columns.map(column=>column.reduce((sum,node)=>sum+node.height+gap,-gap));
    height=2*margin+Math.max(...columnHeights);
    let x=margin;
    columns.forEach((column,col)=>{
      let natural=(height-columnHeights[col])/2;
      const preferred=new Map(column.map(({id,height:boxHeight})=>{
        const predecessors=parents.get(id).filter(from=>levels.get(from)<col).map(from=>positions.get(from));
        const center=predecessors.length?predecessors.reduce((sum,box)=>sum+box.y+box.height/2,0)/predecessors.length:natural+boxHeight/2;
        natural+=boxHeight+gap;
        return [id,center];
      }));
      column.sort((a,b)=>preferred.get(a.id)-preferred.get(b.id));
      let bottom=margin;
      for(const {id,width,height:boxHeight} of column){
        const y=Math.max(bottom,preferred.get(id)-boxHeight/2);
        positions.set(id,{x,y,width,height:boxHeight});
        bottom=y+boxHeight+gap;
      }
      let top=height-margin;
      for(let i=column.length-1;i>=0;i--){
        const box=positions.get(column[i].id);
        box.y=Math.min(box.y,top-box.height);
        top=box.y-gap;
      }
      x+=columnWidths[col]+columnGap;
    });
  }
  return {width,height,positions,levels,columns,columnWidths};
}

function taskEdgePath(layout,{from,to,kind},index,mobile,startOffset=0,endOffset=0){
  const {width,height,positions,levels,columns,columnWidths}=layout;
  const a=positions.get(from),b=positions.get(to),ay=a.y+a.height/2+startOffset,by=b.y+b.height/2+endOffset;
  const lane=6+(index%3)*5;
  if(mobile){
    if(b.order===a.order+1&&kind==='dependency'){
      const x=Math.min(a.width,b.width)/2+a.x;
      return `M${x} ${a.y+a.height} V${b.y}`;
    }
    const forward=a.order<b.order,ax=forward?a.x:a.x+a.width,bx=forward?b.x:b.x+b.width;
    const rail=forward?lane:width-lane,turn=Math.sign(by-ay)*12;
    return `M${ax} ${ay} Q${rail} ${ay},${rail} ${ay+turn} V${by-turn} Q${rail} ${by},${bx} ${by}`;
  }
  const first=levels.get(from),last=levels.get(to),ax=a.x+a.width,bx=b.x;
  if(first>=last)return `M${ax} ${ay} H${a.x+columnWidths[first]+lane} V${lane} H${bx-lane} V${by} H${bx}`;
  let x=a.x+columnWidths[first]+8,y=ay,path=`M${ax} ${ay} H${x}`;
  const curve=(nx,ny)=>{
    const bend=(nx-x)/2;
    path+=` C${x+bend} ${y},${nx-bend} ${ny},${nx} ${ny}`;
    x=nx;y=ny;
  };
  for(let col=first+1;col<last;col++){
    const obstacles=columns[col].map(node=>positions.get(node.id)),desired=(ay+by)/2;
    const candidates=[desired,lane,height-lane,...obstacles.flatMap(box=>[box.y-8,box.y+box.height+8])];
    const safe=candidates.filter(v=>v>=6&&v<=height-6&&obstacles.every(box=>v<=box.y-6||v>=box.y+box.height+6))
      .sort((a,b)=>Math.abs(a-desired)-Math.abs(b-desired))[0];
    const left=obstacles[0].x;
    curve(left-8,safe);
    x=left+columnWidths[col]+8;path+=` H${x}`;
  }
  curve(bx-8,by);
  return path+` H${bx}`;
}

const graphRelations={dependency:{label:'执行依赖',color:'#5277a4'},planning:{label:'任务安排',color:'#8960b7'},recovery:{label:'异常来源',color:'#b26353'}};
function taskEdgeOffsets(positions,links,endpoint,peer){
  const byNode=new Map(),offsets=new Map();
  for(const link of links){
    const id=link[endpoint];
    if(!byNode.has(id))byNode.set(id,[]);
    byNode.get(id).push(link);
  }
  const center=id=>{const box=positions.get(id);return box.y+box.height/2;};
  for(const [id,edges] of byNode){
    edges.sort((a,b)=>center(a[peer])-center(b[peer]));
    const spacing=Math.min(12,(positions.get(id).height-28)/Math.max(1,edges.length-1));
    edges.forEach((edge,i)=>offsets.set(edge,(i-(edges.length-1)/2)*spacing));
  }
  return offsets;
}
function taskGraphSVG(layout,links,mobile,markers=false){
  const related=link=>(link.tasks||[link]).some(({from,to})=>selectedTask===from||selectedTask===to);
  const offsetsFrom=mobile?null:taskEdgeOffsets(layout.positions,links,'from','to');
  const offsetsTo=mobile?null:taskEdgeOffsets(layout.positions,links,'to','from');
  const defs=markers?`<defs>${Object.entries(graphRelations).map(([kind,{color}])=>`<marker id="task-arrow-${kind}" markerWidth="7" markerHeight="7" refX="7" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="${color}"/></marker>`).join('')}</defs>`:'';
  const paths=links.map((link,index)=>({link,index,active:related(link)})).sort((a,b)=>Number(a.active)-Number(b.active)).map(({link,index,active})=>{
    const {from,to,kind,tasks}=link,count=tasks?.length??1;
    const path=taskEdgePath(layout,link,index,mobile,offsetsFrom?.get(link),offsetsTo?.get(link));
    return `<path class="${kind} ${active?'related':''}" data-edge-kind="${kind}" data-edge-from="${esc(from)}" data-edge-to="${esc(to)}" d="${path}" marker-end="url(#task-arrow-${kind})"><title>${count} 条${graphRelations[kind].label}</title></path>`;
  }).join('');
  return `<svg width="${layout.width}" height="${layout.height}" aria-hidden="true">${defs}<g class="dependency-lines${selectedTask?' has-related':''}">${paths}</g></svg>`;
}

function taskDependencyGraph(items,filtered){
  const business=TaskHistory.businessGraph(run,items);
  const graph=TaskHistory.roundGraph(business,expandedRounds,selectedTask,filtered);
  if(!graph.nodes.length)return '<p class="empty-inline">流程决策可在时间顺序中查看。</p>';
  const mobile=mobileTaskGraph.matches;
  const visibleLinks=links=>links.filter(link=>link.kind==='dependency'||showTaskOrigins);
  const links=visibleLinks(graph.links);
  const taskNode=item=>({id:item.tasks.id,item,width:taskCardWidth,height:taskCardHeight});
  const place=(box,content)=>`<div class="process-node" style="left:${box.x}px;top:${box.y}px;width:${box.width}px">${content}</div>`;
  const groups=graph.nodes.map(({id,item,card})=>{
    if(item)return {...taskNode(item),content:taskCard(item)};
    const heading=roundHeading(card,filtered);
    if(!card.open)return {id,width:taskCardWidth,height:132,content:heading};
    const children=card.members.map(taskNode),internal=visibleLinks(card.links);
    const body=layoutTaskGraph(children,internal,mobile,true);
    const cards=children.map(child=>place(body.positions.get(child.id),taskCard(child.item))).join('');
    const name=card.round||'未标注轮次';
    const content=`<section class="round-frame" data-round-frame="${esc(card.round)}" aria-label="${esc(name)}">${heading}<div class="round-body" style="height:${body.height}px">${taskGraphSVG(body,internal,mobile)}${cards}</div></section>`;
    return {id,width:body.width,height:body.height+roundHeadingHeight,content};
  });
  const layout=layoutTaskGraph(groups,links,mobile);
  const current=business.items.find(i=>i.tasks.status==='fault'||i.tasks.status!=='cancelled'&&i.attempts.at(-1)?.observation_error)
    ||business.items.find(i=>['executing','waiting','waiting_user','ready','blocked'].includes(i.tasks.status));
  const cards=groups.map(node=>place(layout.positions.get(node.id),node.content)).join('');
  const legend=showTaskOrigins?'蓝色执行依赖 · 紫色任务安排 · 红色异常来源':'蓝线表示执行依赖';
  return `<div class="graph-tools"><div class="graph-context"><span class="graph-legend">${legend}${graph.nodes.some(n=>n.card)?' · 轮次框对外连线已合并':''}</span><label class="graph-origin-toggle"><input id="graph-show-origins" type="checkbox" ${showTaskOrigins?'checked':''}> 显示安排和异常关系</label></div><div class="graph-actions">${current?`<button data-graph-current="${esc(current.tasks.id)}">定位当前</button>`:''}<button data-graph-zoom="out" aria-label="缩小依赖图">−</button><button id="graph-scale" data-graph-zoom="actual" aria-label="恢复实际大小"></button><button data-graph-zoom="in" aria-label="放大依赖图">＋</button><button data-graph-zoom="fit">${mobile?'适应宽度':'适应画布'}</button><button data-graph-expand>全屏查看</button></div></div><div class="dependency-scroll" data-graph-run="${esc(run.id)}" tabindex="0" aria-label="节点图画布"><div class="process-extent"><div class="process-canvas" style="width:${layout.width}px;height:${layout.height}px">${taskGraphSVG(layout,links,mobile,true)}${cards}</div></div></div>`;
}
let graphScale=null,graphRun=null;
function sizeTaskGraph(mode){
  const canvas=document.querySelector('.process-canvas'),scroll=canvas?.closest('.dependency-scroll');if(!canvas || !canvas.offsetWidth || !canvas.offsetHeight || scroll.clientWidth<=24 || scroll.clientHeight<=24)return;
  if(graphRun!==run.id){graphScale=null;graphRun=run.id;}
  const widthFit=Math.min(1,(scroll.clientWidth-24)/canvas.offsetWidth);
  const mobile=mobileTaskGraph.matches;
  const natural=mobile?widthFit:1;
  const fit=mobile?widthFit:Math.min(widthFit,(scroll.clientHeight-24)/canvas.offsetHeight);
  if(mode==='fit')graphScale=mobile?null:fit;
  else if(mode==='actual')graphScale=null;
  else if(mode==='in')graphScale=Math.min(1.5,(graphScale??natural)+.15);
  else if(mode==='out')graphScale=Math.max(mobile ? 0.6 : 0.2,(graphScale??natural)-.15);
  const scale=graphScale??natural;
  canvas.style.transform=`scale(${scale})`;
  canvas.parentElement.style.width=canvas.offsetWidth*scale+taskDetailOverlayWidth()+'px';
  canvas.parentElement.style.height=canvas.offsetHeight*scale+'px';
  $('graph-scale').textContent=Math.round(scale*100)+'%';
}
function graphElement(attribute,value){
  return document.querySelector(`.process-canvas [${attribute}="${CSS.escape(value)}"]`);
}
function taskDetailOverlayWidth(){
  const detail=$('task-detail');
  return detail&&!detail.hidden&&!inlineTaskDetail.matches?detail.offsetWidth:0;
}
function positionGraph(target,previous){
  const scroll=target?.closest('.dependency-scroll');
  if(!scroll)return;
  const viewport=scroll.getBoundingClientRect(),bounds=target.getBoundingClientRect();
  const offset=previous||{x:(viewport.width-taskDetailOverlayWidth()-bounds.width)/2,y:(viewport.height-bounds.height)/2};
  scroll.scrollBy(bounds.left-viewport.left-offset.x,bounds.top-viewport.top-offset.y);
}
function locateGraphTask(id){
  positionGraph(graphElement('data-task-row',id));
}
function taskIsInView(id,scroll){
  const card=id&&graphElement('data-task-row',id);
  if(!card||!scroll)return false;
  const bounds=card.getBoundingClientRect(),viewport=scroll.getBoundingClientRect();
  return bounds.left>=viewport.left&&bounds.right<=viewport.right-taskDetailOverlayWidth()&&
    bounds.top>=viewport.top&&bounds.bottom<=viewport.bottom;
}
let runGraphPageTop=0;
function setRunGraphExpanded(open,restoreFocus=true){
  const dialog=$('run-graph-dialog');
  if(dialog.open===open)return;
  const scroll=document.querySelector('.dependency-scroll');
  if(open&&!scroll)return;
  const scale=scroll&&graphScaleValue(scroll);
  const center=scroll&&{
    x:(scroll.scrollLeft+scroll.clientWidth/2)/scale,y:(scroll.scrollTop+scroll.clientHeight/2)/scale
  };
  const visibleTask=taskIsInView(selectedTask,scroll)?selectedTask:null;
  $('run-graph-title').textContent=run?.title||'运行过程';
  if(open){
    runGraphPageTop=window.scrollY;
    dialog.classList.remove('show-filters');
    dialog.querySelector('[data-graph-filters]').setAttribute('aria-expanded','false');
    $('run-graph-content').append($('inspect'));
    dialog.showModal();
  }else{
    $('run-inspect-home').append($('inspect'));
    dialog.close();
  }
  requestAnimationFrame(()=>{
    const canvasScroll=document.querySelector('.dependency-scroll');
    if(!canvasScroll)return;
    sizeTaskGraph();
    if(center){
      const updated=graphScaleValue(canvasScroll);
      canvasScroll.scrollTo(center.x*updated-canvasScroll.clientWidth/2,center.y*updated-canvasScroll.clientHeight/2);
    }
    if(visibleTask===selectedTask&&visibleTask&&!taskIsInView(visibleTask,canvasScroll))locateGraphTask(visibleTask);
    if(!open&&restoreFocus){
      window.scrollTo(0,runGraphPageTop);
      canvasScroll.closest('.process-body').querySelector('[data-graph-expand]')?.focus({preventScroll:true});
    }
  });
}
function graphScaleValue(scroll){
  const canvas=scroll.querySelector('.process-canvas');
  return canvas.getBoundingClientRect().width/canvas.offsetWidth||1;
}
$('run-graph-dialog').addEventListener('cancel',event=>{
  event.preventDefault();setRunGraphExpanded(false);
});
window.addEventListener('resize',()=>sizeTaskGraph());
mobileTaskGraph.addEventListener('change',()=>{
  graphScale=null;
  if(page==='runs'&&run){inspectSignature='';renderInspect();if(selectedTask)requestAnimationFrame(()=>locateGraphTask(selectedTask));}
});
function taskError(attempt,task){
  if(!attempt?.failure_summary&&!task?.failure_summary&&!['fault','stale'].includes(task?.status))return '';
  return `<section class="task-error" role="note"><strong>${esc(taskFailureText(task,attempt))}</strong></section>`;
}
function resultFileLink(file,attempt,label){
  const params=new URLSearchParams({execution:attempt.id,output:file.port,path:JSON.stringify(file.path)});
  const url=`/api/runs/${encodeURIComponent(run.id)}/artifact?${params}`;
  const name=label===file.name?file.name:label+' · '+file.name;
  return `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(name)}</a>`;
}
function resultAttempt(attempts,current){
  const hasResult=e=>e?.output_readout?.length||e?.has_result_content;
  return hasResult(current)?current:attempts.findLast(hasResult);
}
function readingsHTML(readings,className='node-facts'){
  return `<dl class="${className}">${readings.map(r=>`<div><dt>${esc(r.label)}</dt><dd>${esc(readingValue(r.value))}${r.unit?' '+esc(r.unit):''}</dd></div>`).join('')}</dl>`;
}
function taskResultHTML(attempt,current,pending){
  if(!attempt)return '';
  const readings=attempt.output_readout||[], fields=attempt.result_content||[];
  const texts=fields.filter(field=>field.text), files=fields.filter(field=>field.file);
  if(!readings.length&&!fields.length&&!pending)return '';
  return `<section class="node-result"><h3>${attempt===current?'结果':'上一次结果'}</h3>
    ${readings.length?readingsHTML(readings,'node-facts node-result-readings'):''}
    ${texts.map(f=>`<div class="node-result-text">${texts.length>1?`<h4>${esc(f.label)}</h4>`:''}<p>${esc(f.text)}</p></div>`).join('')}
    ${files.length?`<ul class="node-result-files">${files.map(f=>`<li>${resultFileLink(f.file,attempt,f.label)}</li>`).join('')}</ul>`:''}
    ${pending?'<p class="muted small" role="status">正在读取结果…</p>':''}</section>`;
}
function waitReasonText(r){
  return r.reason==='order_dependency'?`等待前置任务 ${(run.tasks[r.action]?taskLabel(run.tasks[r.action]):r.action)} 完成`:r.reason==='missing_record'?`输入 ${r.input} 等待结果 ${r.record}`:r.reason==='missing_implementation'?'尚未选用可执行的实现；请由运行 Agent 选择已有方案；补充 Loop 实现使用构建 Agent':r.reason==='invalid_parameters'?'参数不满足所选实现的要求；由运行 Agent 核对任务参数，完整契约可在节点详情查看':r.reason==='invalid_input'?`输入 ${r.input} 尚不可用`:r.reason==='retry_pending'?'等待同一任务的旧进程确认结束，再重试原任务':'等待所需输入或执行条件';
}
function taskWaitReasons(task){
  if(['skipped','cancelled'].includes(task.status)||!task.wait_reasons?.length)return '';
  return `<div class="wait-reasons"><strong>当前等待原因</strong><ul>${task.wait_reasons.map(r=>`<li>${esc(waitReasonText(r))}</li>`).join('')}</ul></div>`;
}
function needsReplyData(attempt){
  return Boolean(attempt&&(attempt.status==='approval'||attempt.status==='waiting'&&attempt.implementation.kind==='event'));
}
function taskNeedsDetail(id){
  const task=run.tasks[id];
  if(!task)return false;
  const attempts=run.executions.filter(e=>e.task_id===id);
  const attempt=attempts.find(e=>e.id===task.execution_id)||attempts.at(-1);
  return (task.status!=='cancelled'&&needsReplyData(attempt))||Boolean(resultAttempt(attempts,attempt)?.has_result_content);
}
function taskFlowHTML(item){
  const id=item.tasks.id,edges=TaskHistory.links(run),incoming=edges.filter(e=>e.to===id),outgoing=edges.filter(e=>e.from===id);
  const link=(edge,target)=>{
    const task=run.tasks[target],name=[taskLabel(task),task.spec.ref||task.spec.round].filter(Boolean).join(' · ');
    return `<li class="${edge.kind}"><small>${graphRelations[edge.kind].label}</small><button class="text-button" data-task-focus="${esc(target)}">${esc(name)}</button>${badge(task.status)}</li>`;
  };
  if(!incoming.length&&!outgoing.length)return '';
  return `<section class="task-flow"><h3>任务关系与推进</h3>${incoming.length?`<h4>来源</h4><ul>${incoming.map(e=>link(e,e.from)).join('')}</ul>`:''}${outgoing.length?`<h4>后续与异常处理</h4><ul>${outgoing.map(e=>link(e,e.to)).join('')}</ul>`:''}</section>`;
}
function childRunLink(attempt){
  if(!attempt?.child_run_id)return '';
  const href=routeHash({type:'run',id:attempt.child_run_id});
  return `<p><a data-route-link href="${esc(href)}">查看子 Run</a> · ${esc(labels[attempt.child_status]||attempt.child_status||'等待中')}</p>`;
}
function taskDetails(item,pending){
  const t=item.tasks,attempt=item.attempts.find(e=>e.id===t.execution_id)||item.attempts.at(-1);
  const ended=run.identity_read_only||['completed','terminated','continued'].includes(run.status);
  const editable=!t.execution_id&&['planned','blocked','ready','held'].includes(t.status);
  const cancelled=t.status==='cancelled';
  const cancellable=!cancelled&&(editable||attempt?.status==='waiting'&&['timer','event','loop'].includes(attempt.implementation.kind));
  const canRetry=['fault','stale','cancelled','waiting_user','retrying'].includes(t.status)||attempt?.observation_error;
  const result=resultAttempt(item.attempts,attempt),progress=TaskHistory.readings(run.loop_definition.nodes[t.spec.node]?.readout,attempt?.activity_progress);
  const agent=attempt?.implementation.kind==='agent';
  const actions=[
    !ended&&cancellable?`<button data-task-cancel="${esc(t.id)}">${editable?'取消任务':'取消等待'}</button>`:'',
    !ended&&canRetry?`<button data-task-retry="${esc(t.id)}">${attempt?.observation_error?'恢复监控':'重试任务'}</button>`:'',
    agent&&attempt.implementation.terminal?`<button data-open-terminal="${esc(attempt.id)}">打开交互终端</button>`:'',
    agent&&!ended?`<button data-agent-session="${esc(attempt.id)}">${attempt.worker_active?'打开会话':'恢复会话'}</button>`:'',
    `<button data-task-assistance="${esc(t.id)}">查看外援请求</button>`
  ].filter(Boolean);
  return `<div class="task-detail-heading"><h2>${esc(taskLabel(t))}</h2>${taskBadge(item)}</div>
    ${item.round||t.spec.ref?`<p class="small muted">${esc([item.round,t.spec.ref].filter(Boolean).join(' · '))}</p>`:''}
    ${cancelled?`<section class="task-cancellation"><h3>取消原因</h3><p>${esc(taskSummary(item))}</p></section>`:
      `${taskError(attempt,t)}${taskWaitReasons(t)}
       ${pending&&needsReplyData(attempt)?'<p class="small muted" role="status">正在读取等待条件…</p>':waitDetails(attempt)}
       ${t.assistance_wait?'<p class="small muted">正在等待外援回复。</p>':''}
       ${progress.length&&result!==attempt?readingsHTML(progress):''}`}
    ${childRunLink(attempt)}
    ${taskResultHTML(result,attempt,pending&&result?.has_result_content)}
    ${actions.length?`<div class="toolbar">${actions.join('')}</div>`:''}${taskFlowHTML(item)}`;
}
function renderTaskHistory(){
  if(run.superseded_by && !Object.keys(run.tasks).length)return '<p class="empty-inline">这次历史运行没有节点记录。</p>';
  const scroll=document.querySelector('.dependency-scroll'),detail=$('task-detail');
  const position=scroll?.dataset.graphRun===run.id?{left:scroll.scrollLeft,top:scroll.scrollTop}:null;
  const detailTop=detail?.dataset.task===selectedTask?detail.scrollTop:0;
  const focused=document.activeElement;
  const focusedRound=scroll?.contains(focused)?focused.dataset.roundToggle:undefined;
  const focusedTask=scroll?.contains(focused)&&focused.matches('.task-card-main')?focused.dataset.taskFocus:undefined;
  const focusedExpand=focused?.matches('[data-graph-expand]');
  requestAnimationFrame(()=>{
    sizeTaskGraph();
    if(position)document.querySelector('.dependency-scroll')?.scrollTo(position);
    else if(!selectedTask){
      const current=document.querySelector('[data-graph-current]');
      if(current)locateGraphTask(current.dataset.graphCurrent);
    }
    if(detailTop)$('task-detail')?.scrollTo(0,detailTop);
    if(focusedRound!==undefined)graphElement('data-round-toggle',focusedRound)?.focus({preventScroll:true});
    if(focusedTask)graphElement('data-task-row',focusedTask)?.querySelector('.task-card-main')?.focus({preventScroll:true});
    if(focusedExpand)document.querySelector('[data-graph-expand]')?.focus({preventScroll:true});
  });
  taskChanges=new Set(run.changed_tasks??run.history.filter(h=>h.detail?.before&&h.detail?.tasks).map(h=>h.detail.tasks));
  const all=TaskHistory.rows(run),business=all.filter(i=>!i.tasks.origin?.flow_agent);
  taskNumbers=new Map(all.map((item,index)=>[item.tasks.id,index+1]));
  const selected=all.find(i=>i.tasks.id===selectedTask);
  if(!selected)selectedTask=null;
  if(selected&&!selected.tasks.origin?.flow_agent&&TaskHistory.canFoldRoundTask(selected)&&!expandedRounds.has(selected.round||'')){
    expandedRounds.add(selected.round||'');rememberRounds();
  }
  const query=taskSearch.trim().toLowerCase();
  const visible=all.filter(i=>(!filterNode||i.tasks.spec.node===filterNode)&&(!taskStatus||i.tasks.status===taskStatus)&&
    (!taskRound||i.round===taskRound)&&(!query||[taskLabel(i.tasks),i.tasks.id,i.tasks.spec.ref,i.round].join(' ').toLowerCase().includes(query)));
  const rounds=[...new Set(all.map(i=>i.round).filter(Boolean))];
  const detailPending=selected&&taskNeedsDetail(selectedTask)&&run.workspace_view&&run.workspace_view.task!==selectedTask;
  const groups=[{round:'已开始',items:visible.filter(i=>i.started!==null)},{round:'尚未开始',items:visible.filter(i=>i.started===null&&!['completed','skipped','cancelled','stale'].includes(i.tasks.status))},{round:'未执行且已结束',items:visible.filter(i=>i.started===null&&['completed','skipped','cancelled','stale'].includes(i.tasks.status))}];
  const filtered=Boolean(filterNode||taskStatus||query);
  return `<div class="task-heading"><div><h2>节点进度</h2><p class="muted small">${business.length} 项任务${rounds.length?' · '+rounds.length+' 轮':''}${all.length>business.length?' · '+(all.length-business.length)+' 次流程决策':''}</p></div></div><div class="process-controls" id="run-process-controls"><div class="segmented">${[['graph','节点图'],['time','时间顺序']].map(([id,label])=>`<button data-task-order="${id}" class="${taskOrder===id?'selected':''}" aria-pressed="${taskOrder===id}">${label}</button>`).join('')}</div>${rounds.length?`<label class="task-round-filter"><select id="task-round" aria-label="筛选轮次"><option value="">全部轮次</option>${rounds.map(r=>'<option value="'+esc(r)+'" '+(r===taskRound?'selected':'')+'>'+esc(r)+'</option>').join('')}</select></label>`:''}<label class="task-search-label"><span class="sr-only">查找任务</span><input id="task-search" placeholder="查找任务…" type="search" value="${esc(taskSearch)}"></label><label class="task-status-label"><span class="sr-only">任务状态</span><select id="task-status"><option value="">全部状态</option>${[...new Set(all.map(i=>i.tasks.status))].map(s=>`<option value="${esc(s)}" ${taskStatus===s?'selected':''}>${esc(labels[s]||s)}</option>`).join('')}</select></label>${filterNode?'<button id="clear-task-filter">清除节点筛选</button>':''}</div>
  <div class="process-layout"><section class="process-body">${visible.length?(taskOrder==='graph'?taskDependencyGraph(visible,filtered):groups.filter(g=>g.items.length).map(g=>`<details class="task-group" open><summary>${g.round} · ${g.items.length}</summary><div class="process-list">${g.items.map(taskCard).join('')}</div></details>`).join('')):'<p class="empty-inline">没有符合条件的任务</p>'}</section><aside id="task-detail" class="task-detail" ${selected?`data-task="${esc(selectedTask)}"`:'hidden'}>${selected?`<button class="close-task-detail" data-close-task aria-label="关闭节点详情">×</button><div id="task-detail-body">${taskDetails(selected,detailPending)}</div>`:''}</aside></div>`;
}
const editDialog=document.createElement('dialog');editDialog.id='task-edit-dialog';editDialog.innerHTML='<div class="dialog-heading"><h2 id="task-edit-title"></h2><button class="close-dialog" aria-label="关闭">×</button></div><div id="task-edit-error" role="alert"></div><form id="task-edit-form"><div id="task-edit-fields"></div><div class="dialog-tasks"><button type="button" class="close-dialog">取消</button><button type="submit" class="primary" id="task-edit-submit">确认操作</button></div></form>';document.body.append(editDialog);
function openTaskEdit(kind,id=null){
  if(!['cancel','retry'].includes(kind))return;
  if(['completed','terminated','continued'].includes(run.status)){toast('这次运行仅供查看');return;}
  const monitorRetry=kind==='retry'&&run.executions.some(e=>e.id===run.tasks[id]?.execution_id&&e.observation_error);
  taskEdit={monitorRetry,kind,id,runId:run.id,key:randomKey()};$('task-edit-error').textContent=(run.agent_sessions||[]).length?'Agent 正在处理工作；提交时检查版本，同一任务仍受重复执行保护。':'';
  $('task-edit-title').textContent=kind==='cancel'?'取消任务':monitorRetry?'恢复监控':'重试任务';
  $('task-edit-submit').textContent='确认操作';
  $('task-edit-fields').innerHTML=`<p>${esc(taskLabel(run.tasks[id]))}</p><p>${kind==='retry'?(monitorRetry?'继续查询原来的外部任务，不会再次提交工作。':'按当前任务的实现和参数重试。'):'取消此任务，已发生的外部操作不会撤销。'}</p><label>备注（可选）<input id="task-edit-reason"></label>`;
  editDialog.showModal();
}
function collectTaskEdit(){return [{tool:'change_task',arguments:{task_id:taskEdit.id,operation:taskEdit.kind,reason:$('task-edit-reason').value.trim()||$('task-edit-title').textContent}}];}
document.addEventListener('click',event=>safely(async()=>{
  const el=event.target.closest('button');if(!el)return;const d=el.dataset;
  if(d.graphExpand!==undefined){setRunGraphExpanded(true);return;}
  if(d.graphExit!==undefined){setRunGraphExpanded(false);return;}
  if(d.graphFilters!==undefined){
    const open=$('run-graph-dialog').classList.toggle('show-filters');
    el.setAttribute('aria-expanded',String(open));
    sizeTaskGraph();
    return;
  }
  if(d.roundToggle!==undefined){
    const round=d.roundToggle,scroll=el.closest('.dependency-scroll').getBoundingClientRect(),rect=el.getBoundingClientRect();
    const offset={x:rect.left-scroll.left,y:rect.top-scroll.top};
    if(el.getAttribute('aria-expanded')==='true'){
      expandedRounds.delete(round);
      if(selectedTask&&el.closest('[data-round-frame]')?.contains(graphElement('data-task-row',selectedTask))){
        selectedTask=null;syncRunTaskRoute();
      }
    }else expandedRounds.add(round);
    rememberRounds();
    inspectSignature='';renderInspect();
    requestAnimationFrame(()=>positionGraph(graphElement('data-round-toggle',round),offset));
    return;
  }
  if(d.focusGroup){
    taskOrder='graph';activeTab='task-history';taskRound='';taskStatus='';taskSearch='';filterNode=d.focusGroup;selectedTask=null;
    syncRunTaskRoute();
    inspectSignature='';renderInspect();
    document.querySelector('.process-controls')?.scrollIntoView({block:'start'});return;
  }
  if(d.taskFocus){
    const id=d.taskFocus;
    if(!run.tasks[id])return;
    if(!el.closest('[data-task-row]')){filterNode=null;taskRound='';taskSearch='';taskStatus='';}
    selectedTask=id;syncRunTaskRoute();
    inspectSignature='';renderInspect();
    requestAnimationFrame(()=>{locateGraphTask(id);if(inlineTaskDetail.matches)$('task-detail')?.scrollIntoView({block:'start'});});
  }
  else if(d.graphCurrent){locateGraphTask(d.graphCurrent);graphElement('data-task-row',d.graphCurrent)?.querySelector('.task-card-main')?.focus({preventScroll:true});}
  else if(d.graphZoom)sizeTaskGraph(d.graphZoom);
  else if(d.taskOrder){taskOrder=d.taskOrder;inspectSignature='';renderInspect();if(selectedTask)requestAnimationFrame(()=>locateGraphTask(selectedTask));}
  else if(d.closeTask!==undefined){
    const id=selectedTask;selectedTask=null;syncRunTaskRoute();inspectSignature='';renderInspect();
    requestAnimationFrame(()=>{
      const card=document.querySelector(`.process-body [data-task-row="${CSS.escape(id)}"]`);
      positionGraph(card);
      const button=card?.querySelector('.task-card-main')||document.querySelector('.dependency-scroll');
      button?.focus({preventScroll:true});
      if(inlineTaskDetail.matches)document.querySelector('#run-graph-dialog[open] .graph-tools, #run-inspect-home .process-controls')?.scrollIntoView({block:'start'});
    });
  }
  else if(d.taskCancel)openTaskEdit('cancel',d.taskCancel);
  else if(d.taskRetry)openTaskEdit('retry',d.taskRetry);
  else if(el.id==='clear-task-filter'){filterNode=null;inspectSignature='';renderInspect();}
}));
document.addEventListener('change',event=>{const el=event.target;
  if(el.id==='graph-show-origins'){showTaskOrigins=el.checked;inspectSignature='';renderInspect();$('graph-show-origins')?.focus({preventScroll:true});}
  if(el.id==='task-status'||el.id==='task-search'){taskStatus=$('task-status').value;taskSearch=$('task-search').value;inspectSignature='';renderInspect();}
  if(el.id==='task-round'){taskRound=el.value;selectedTask=null;syncRunTaskRoute();inspectSignature='';renderInspect();}
});
document.addEventListener('submit',event=>{
  if(event.target.id!=='task-edit-form')return;event.preventDefault();
  (async()=>{try{
    $('task-edit-error').textContent='';
    await platformCall('submit_run_request',{request_id:taskEdit.key,run_id:taskEdit.runId,operation:'edit_tasks',message:$('task-edit-reason').value,arguments:{changes:collectTaskEdit()}});
    editDialog.close();await refresh();toast('任务已更新');
  }catch(e){$('task-edit-error').textContent=e.message;}})();
});
