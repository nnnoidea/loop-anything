'use strict';
let selectedTask=null,taskOrder='graph',taskSearch='',taskStatus='',taskRound='',taskEdit=null,taskChanges=new Set(),taskNumbers=new Map();
const expandedRounds=new Set(),inlineTaskDetail=window.matchMedia('(max-width:960px)');
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
  const request=run.task_dispositions?.[t.id]?.reason;
  if(request)return request;
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
function runningNodesHTML(value){
  if(value.identity_read_only||value.superseded_by||!['running','paused'].includes(value.status))return '';
  const attempts=new Map(value.executions.map(attempt=>[attempt.id,attempt]));
  const active=Object.values(value.tasks).filter(task=>{
    const attempt=attempts.get(task.execution_id);
    const progress=attempt?.activity_progress;
    if(attempt?.implementation?.kind==='external'&&progress){
      return ['executing','waiting'].includes(task.status)&&!attempt.observation_error&&
        progress.classification!=='resource_wait'&&
        (['running','startup'].includes(progress.classification)||
          ['RUNNING','STARTED'].includes(String(progress.external_status).toUpperCase()));
    }
    if(task.status==='executing')return !attempt?.observation_error;
    if(task.status==='decision')return Boolean(attempt?.worker_active);
    return task.status==='waiting'&&attempt?.implementation?.kind==='loop'&&attempt.child_status==='running';
  });
  if(!active.length)return '';
  const name=task=>value.loop_definition.nodes[task.spec.node]?.label||task.spec.node;
  return `<h2>运行中的节点</h2><ul>${active.map(task=>{
    const label=name(task);
    const context=[...new Set([task.spec.round,task.spec.ref])].filter(part=>part&&part!==label).join(' · ');
    const route={type:'run',id:value.id,task:task.id};
    return `<li><a href="${esc(routeHash(route))}" data-route-link>
      <span>${esc(label)}${context?`<small>${esc(context)}</small>`:''}</span><span aria-hidden="true">↗</span>
    </a></li>`;
  }).join('')}</ul>`;
}
function taskCard(item){
  const t=item.tasks,order=taskNumbers.get(t.id),attempt=item.attempts.at(-1),agent=attempt?.implementation.kind==='agent',active=attempt?.worker_active||(run.agent_sessions||[]).some(o=>o.resume_execution===attempt?.id);
  return `<article class="process-task ${selectedTask===t.id?'picked':''}" data-status="${esc(t.status)}" data-task-focus="${esc(t.id)}" data-task-row="${esc(t.id)}"><button class="task-card-main" data-task-focus="${esc(t.id)}" aria-pressed="${selectedTask===t.id}" title="${esc([taskLabel(t),t.spec.ref,t.id].filter(Boolean).join(' · '))}"><span class="task-card-top">${taskOrder==='time'?`<small class="task-number">${String(order).padStart(2,'0')}</small>`:''}${taskBadge(item)}${taskChanges.has(t.id)?'<span data-change-mark>已调整</span>':''}</span><span class="task-name">${esc(taskLabel(t))}</span>${t.spec.ref?`<small class="task-card-ref">${esc(t.spec.ref)}</small>`:''}<span class="task-summary">${esc(taskSummary(item))}</span><small class="task-card-time">${esc([item.round,item.started===null&&['skipped','cancelled'].includes(t.status)?'未执行':taskTime(item.started)].filter(Boolean).join(' · '))}</small></button><div class="task-card-actions">${flowDecisionButtons(t,true)}${agent?`<button data-agent-session="${esc(attempt.id)}" ${['completed','terminated','continued'].includes(run.status)&&!active?'disabled title="Run 已结束，可查看结果与会话记录"':''}>${active?'打开会话':'恢复会话'}</button>`:''}</div></article>`;
}
const taskCardWidth=224,taskCardHeight=168,handoffCardHeight=136,roundHeadingHeight=44,graphReferenceHeight=34;
let showTaskOrigins=false;
const graphReferences=new Map();
function taskGroupTitle(card){
  if(card.round)return card.round;
  const ref=card.members.findLast(item=>item.tasks.spec.ref)?.tasks.spec.ref;
  return ref||[...new Set(card.members.map(item=>taskLabel(item.tasks)))].join(' · ');
}
function roundHeading(card,filtered){
  const title=taskGroupTitle(card);
  const counts=new Map();
  for(const item of card.members){
    const status=taskStatusLabel(item);
    counts.set(status,(counts.get(status)||0)+1);
  }
  const terminal=[labels.completed,labels.cancelled,labels.skipped];
  const count=[...counts].sort(([a],[b])=>Number(terminal.includes(a))-Number(terminal.includes(b)))
    .map(([status,number])=>`${status} ${number}`).join(' · ');
  const toggle=`data-round-toggle="${esc(card.key)}" aria-expanded="${card.open}"`;
  const heading=`<strong>${esc(title)}</strong><small title="${esc(count)}">${esc(count)}</small>`;
  if(card.open)return filtered
    ?`<div class="round-heading">${heading}</div>`
    :`<button class="round-heading" ${toggle} aria-label="收起 ${esc(title)}">${heading}<span aria-hidden="true">收起 ⌃</span></button>`;
  const recent=card.members.findLast(item=>item.tasks.status==='completed'&&taskReadout(item).some(f=>f.source==='outputs'));
  const current=card.members.find(item=>['fault','stale'].includes(item.tasks.status)||item.attempts.at(-1)?.observation_error)
    ||card.members.find(item=>['executing','waiting','approval','waiting_user','ready'].includes(item.tasks.status));
  const summary=current?[taskLabel(current.tasks),taskSummary(current)].filter(Boolean).join(' · '):recent&&taskSummary(recent);
  return `<button class="round-card" ${toggle}>${heading}${summary?`<small>${esc(summary)}</small>`:''}<span class="round-action">展开节点 <span aria-hidden="true">›</span></span></button>`;
}

function taskGraphRanks(nodes,links,includePlanning=false){
  const parents=new Map(nodes.map(node=>[node.id,[]]));
  for(const {from,to,kind} of links)if(kind==='dependency'||includePlanning&&kind==='planning')parents.get(to).push(from);
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
  return {parents,levels};
}

function layoutTaskGraph(nodes,{parents,levels}){
  const margin=19,gap=26,columnGap=54;
  const columns=[],positions=new Map();
  for(const node of nodes)(columns[levels.get(node.id)]??=[]).push(node);
  const columnWidths=columns.map(column=>Math.max(...column.map(node=>node.width)));
  const width=2*margin+columnWidths.reduce((sum,w)=>sum+w,0)+columnGap*(columns.length-1);
  const columnHeights=columns.map(column=>column.reduce((sum,node)=>sum+node.height+gap,-gap));
  const height=2*margin+Math.max(...columnHeights);
  let x=margin;
  columns.forEach((column,col)=>{
    let natural=(height-columnHeights[col])/2;
    const preferred=new Map(column.map(({id,height:boxHeight})=>{
      const predecessors=parents.get(id).filter(from=>levels.get(from)<col).map(from=>positions.get(from));
      const center=predecessors.length?predecessors.reduce((sum,box)=>sum+box.y+box.anchor,0)/predecessors.length:natural+boxHeight/2;
      natural+=boxHeight+gap;
      return [id,center];
    }));
    column.sort((a,b)=>preferred.get(a.id)-preferred.get(b.id));
    let bottom=margin;
    for(const {id,width,height:boxHeight} of column){
      const anchor=boxHeight/2,y=Math.max(bottom,preferred.get(id)-anchor);
      positions.set(id,{x,y,width,height:boxHeight,anchor});
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
  return {width,height,positions,levels,columns,columnWidths};
}

function layoutTaskRows(rows,nodes){
  const margin=28,rowGap=58,cardGap=24,positions=new Map();
  let y=margin,width=0;
  const geometry=rows.map((row,index)=>{
    let x=margin,height=0;
    for(const id of row){
      const node=nodes.get(id);
      positions.set(id,{x,y,width:node.width,height:node.height,anchor:taskCardWidth/2,row:index,members:node.members});
      x+=node.width+cardGap;
      height=Math.max(height,node.height);
    }
    width=Math.max(width,x-cardGap+margin);
    const band={y,height,ids:row};
    y+=height+rowGap;
    return band;
  });
  return {width,height:y-rowGap+margin,positions,rows:geometry};
}

function rowEdgeAnchor(box,tasks,field){
  const first=tasks?.[0]?.[field],member=box.members?.get(first);
  return member&&tasks.every(edge=>edge[field]===first)?member.x+member.width/2:box.anchor;
}

function rowEdgePath(layout,{from,to,tasks},startOffset=0,endOffset=0){
  const source=layout.positions.get(from),target=layout.positions.get(to);
  const a=source.x+rowEdgeAnchor(source,tasks,'from')+startOffset;
  const b=target.x+rowEdgeAnchor(target,tasks,'to')+endOffset;
  const row=layout.rows[source.row],edge=row.y+row.height+10;
  const middle=(edge+target.y)/2;
  return `M${a} ${source.y+source.height} V${edge} C${a} ${middle},${b} ${middle},${b} ${target.y}`;
}

function taskEdgePath(layout,{from,to},index,startOffset=0,endOffset=0){
  const {height,positions,levels,columns,columnWidths}=layout;
  const a=positions.get(from),b=positions.get(to),ay=a.y+a.anchor+startOffset,by=b.y+b.anchor+endOffset;
  const lane=6+(index%3)*5;
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
function taskEdgeOffsets(positions,links,endpoint,peer,vertical){
  const byNode=new Map(),offsets=new Map();
  for(const link of links){
    const id=link[endpoint];
    if(!byNode.has(id))byNode.set(id,[]);
    byNode.get(id).push(link);
  }
  const center=id=>{const box=positions.get(id);return (vertical?box.x:box.y)+box.anchor;};
  for(const [id,edges] of byNode){
    edges.sort((a,b)=>center(a[peer])-center(b[peer]));
    const box=positions.get(id),span=vertical?box.width:box.height;
    const available=Math.max(0,2*Math.min(box.anchor,span-box.anchor)-16);
    const spacing=Math.min(12,available/Math.max(1,edges.length-1));
    edges.forEach((edge,i)=>offsets.set(edge,(i-(edges.length-1)/2)*spacing));
  }
  return offsets;
}
function taskGraphSVG(layout,links,vertical=false){
  const related=link=>(link.tasks||[link]).some(({from,to})=>selectedTask===from||selectedTask===to);
  const offsetsFrom=taskEdgeOffsets(layout.positions,links,'from','to',vertical);
  const offsetsTo=taskEdgeOffsets(layout.positions,links,'to','from',vertical);
  const defs=vertical?`<defs>${Object.entries(graphRelations).map(([kind,{color}])=>`<marker id="task-arrow-${kind}" markerWidth="7" markerHeight="7" refX="7" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="${color}"/></marker>`).join('')}</defs>`:'';
  const paths=links.map((link,index)=>({link,index,active:related(link)})).sort((a,b)=>Number(a.active)-Number(b.active)).map(({link,index,active})=>{
    const {from,to,kind,tasks}=link,count=tasks?.length??1;
    const start=offsetsFrom.get(link),end=offsetsTo.get(link);
    const path=vertical?rowEdgePath(layout,link,start,end):taskEdgePath(layout,link,index,start,end);
    return `<path class="${kind} ${active?'related':''}" data-edge-kind="${kind}" data-edge-from="${esc(from)}" data-edge-to="${esc(to)}" d="${path}" marker-end="url(#task-arrow-${kind})"><title>${count} 条${graphRelations[kind].label}</title></path>`;
  }).join('');
  return `<svg width="${layout.width}" height="${layout.height}" aria-hidden="true">${defs}<g class="dependency-lines${selectedTask?' has-related':''}">${paths}</g></svg>`;
}

function graphReferenceButton(node,links,membership){
  if(!links.length)return '';
  const relations=links.flatMap(link=>link.tasks);
  if(!node.handoff&&relations.length===1){
    const link=links[0],relation=relations[0],incoming=link.to===node.id;
    const task=run.tasks[incoming?relation.from:relation.to];
    const title=[incoming?'来源':'后续',task.spec.round||task.spec.ref||taskLabel(task)].join(' · ');
    return `<button class="graph-references" data-task-focus="${esc(task.id)}" title="${esc(title)}">${esc(title)} ↗</button>`;
  }
  const sources=new Set(relations.filter(link=>link.to===node.id&&link.kind==='dependency').map(link=>membership.get(link.from)));
  const plans=new Set(relations.filter(link=>link.from===node.id&&
    (link.kind==='planning'||link.arranged)).map(link=>membership.get(link.to)));
  const summary=node.handoff?[sources.size&&`来源 ${sources.size} 组`,plans.size&&`安排 ${plans.size} 组`].filter(Boolean).join(' · '):'';
  graphReferences.set(node.id,relations);
  return `<button class="graph-references" data-graph-references="${esc(node.id)}">${esc(summary||relations.length+' 条跨组关系')} ↗</button>`;
}
function openGraphReferences(id){
  const relations=graphReferences.get(id);
  if(!relations)return;
  const target=taskId=>{
    const task=run.tasks[taskId];
    const context=[task.spec.round,task.spec.ref].filter(Boolean).join(' · ');
    return `<button class="text-button" data-task-focus="${esc(task.id)}">${esc(taskLabel(task))}
      ${context?`<small>${esc(context)}</small>`:''}</button>`;
  };
  $('detail-title').textContent='跨组关系';
  $('detail-content').innerHTML=`<ul class="graph-reference-list">${relations.map(link=>
    `<li><small>${esc(graphRelations[link.kind].label)}${link.arranged?' · 任务安排':''}</small>
      <div>${target(link.from)}<span aria-hidden="true">→</span>${target(link.to)}</div></li>`).join('')}</ul>`;
  $('detail-dialog').showModal();
}

function taskDependencyGraph(items,filtered){
  const business=TaskHistory.businessGraph(run,items);
  const graph=TaskHistory.roundGraph(business,expandedRounds,selectedTask,filtered);
  if(!graph.nodes.length)return '<p class="empty-inline">流程决策可在时间顺序中查看。</p>';
  const links=graph.links.filter(link=>link.kind!=='recovery'||showTaskOrigins);
  const ranks=taskGraphRanks(graph.nodes,links,true),local=[];
  const rows=TaskHistory.parallelRows(graph.nodes,links,ranks.levels);
  const rowIndex=new Map();
  rows.forEach((row,index)=>row.forEach(id=>rowIndex.set(id,index)));
  const handoffs=new Set(graph.nodes.filter(node=>node.handoff).map(node=>node.id)),references=new Map();
  const refer=(id,link)=>{
    if(!references.has(id))references.set(id,new Set());
    references.get(id).add(link);
  };
  graphReferences.clear();
  for(const link of links){
    if(rowIndex.get(link.to)===rowIndex.get(link.from)+1&&ranks.levels.get(link.to)>ranks.levels.get(link.from))local.push(link);
    else refer(link.kind==='planning'?link.from:link.to,link);
    if(handoffs.has(link.from))refer(link.from,link);
    if(handoffs.has(link.to))refer(link.to,link);
  }
  const taskNode=item=>({id:item.tasks.id,item,width:taskCardWidth,height:taskCardHeight});
  const place=(box,content,handoff=false)=>`<div class="process-node${handoff?' graph-handoff':''}" style="left:${box.x}px;top:${box.y}px;width:${box.width}px">${content}</div>`;
  const groups=new Map(graph.nodes.map(node=>{
    const {id,item,card,handoff}=node;
    const reference=graphReferenceButton(node,[...(references.get(id)||[])],graph.membership);
    const extra=reference?graphReferenceHeight:0;
    if(item){
      const height=handoff?handoffCardHeight:taskCardHeight;
      return [id,{...taskNode(item),height:height+extra,handoff,content:taskCard(item)+reference}];
    }
    const heading=roundHeading(card,filtered);
    if(!card.open)return [id,{width:taskCardWidth,height:132+extra,content:heading+reference}];
    const children=card.members.map(taskNode),internal=card.links.filter(link=>link.kind==='dependency'||showTaskOrigins);
    const body=layoutTaskGraph(children,taskGraphRanks(children,card.links,true));
    const cards=children.map(child=>place(body.positions.get(child.id),taskCard(child.item))).join('');
    const content=`<section class="round-frame" data-round-frame="${esc(card.key)}" aria-label="${esc(taskGroupTitle(card))}">
      ${heading}${reference?'<div class="round-references">'+reference+'</div>':''}
      <div class="round-body" style="height:${body.height}px">${taskGraphSVG(body,internal)}${cards}</div></section>`;
    return [id,{width:body.width,height:body.height+roundHeadingHeight+extra,members:body.positions,content}];
  }));
  const layout=layoutTaskRows(rows,groups);
  const current=business.items.find(i=>i.tasks.status==='fault'||i.tasks.status!=='cancelled'&&i.attempts.at(-1)?.observation_error)
    ||business.items.find(i=>['executing','waiting','waiting_user','ready','blocked'].includes(i.tasks.status));
  const bands=layout.rows.map(({ids,y,height},index)=>`<div class="process-row" data-graph-row="${index}"
    style="top:${y-10}px;width:${layout.width-36}px;height:${height+20}px">${ids.map(id=>{
      const box=layout.positions.get(id),node=groups.get(id);
      return place({...box,x:box.x-18,y:10},node.content,node.handoff);
    }).join('')}</div>`).join('');
  const legend='蓝色依赖 · 紫色安排'+(showTaskOrigins?' · 红色异常来源':'');
  const zoom=graphRun===run.id?graphScale??1:1;
  return `<div class="run-task-graph">
    <div class="graph-tools">
      <div class="graph-context">
        <span class="graph-legend">${legend}</span>
        <label class="graph-origin-toggle"><input id="graph-show-origins" type="checkbox" ${showTaskOrigins?'checked':''}> 显示组内安排与异常关系</label>
        ${current?`<button data-graph-current="${esc(current.tasks.id)}">定位当前</button>`:''}
      </div>
      <div class="graph-actions" role="group" aria-label="节点图查看">
        <button data-graph-zoom="out" aria-label="缩小依赖图" title="缩小">−</button>
        <button id="graph-scale" data-graph-zoom="actual" aria-label="恢复实际大小" title="恢复原始大小">${Math.round(zoom*100)}%</button>
        <button data-graph-zoom="in" aria-label="放大依赖图" title="放大">+</button>
        <button data-graph-zoom="fit">适应宽度</button><button data-graph-expand>全屏</button>
      </div>
    </div>
    <div class="dependency-scroll" data-graph-run="${esc(run.id)}" tabindex="0" aria-label="节点图画布">
      <div class="process-extent" style="width:${layout.width*zoom}px;height:${layout.height*zoom}px">
        <div class="process-canvas" style="width:${layout.width}px;height:${layout.height}px;transform:scale(${zoom})">${taskGraphSVG(layout,local,true)}${bands}</div>
      </div>
    </div>
  </div>`;
}
let graphScale=null,graphRun=null;
function sizeTaskGraph(mode){
  const canvas=document.querySelector('.process-canvas'),scroll=canvas?.closest('.dependency-scroll');
  if(!run||!canvas||!canvas.offsetWidth||scroll.clientWidth<=24)return;
  if(graphRun!==run.id){graphScale=null;graphRun=run.id;}
  const style=getComputedStyle(scroll);
  const padding=parseFloat(style.paddingLeft)+parseFloat(style.paddingRight);
  const widthFit=Math.min(1,(scroll.clientWidth-padding)/canvas.offsetWidth);
  const previous=graphScale??1;
  const minimum=Math.min(.5,widthFit,previous);
  const anchor=mode?graphAnchor(scroll):null;
  if(mode==='fit')graphScale=widthFit;
  else if(mode==='actual')graphScale=1;
  else if(mode==='in')graphScale=Math.min(2,previous+.25);
  else if(mode==='out')graphScale=Math.max(minimum,previous-.25);
  const scale=graphScale??1;
  canvas.style.transform=`scale(${scale})`;
  canvas.parentElement.style.width=canvas.offsetWidth*scale+'px';
  canvas.parentElement.style.height=canvas.offsetHeight*scale+'px';
  scroll.closest('.process-layout').style.setProperty('--graph-toolbar-height',scroll.previousElementSibling.offsetHeight+'px');
  const percent=$('graph-scale');
  percent.textContent=Math.round(scale*100)+'%';
  percent.setAttribute('aria-label','恢复实际大小，当前 '+percent.textContent);
  scroll.parentElement.querySelector('[data-graph-zoom="out"]').disabled=scale<=minimum;
  scroll.parentElement.querySelector('[data-graph-zoom="in"]').disabled=scale>=2;
  if(anchor)restoreGraphAnchor(scroll,anchor);
}
function graphElement(attribute,value){
  return document.querySelector(`.process-canvas [${attribute}="${CSS.escape(value)}"]`);
}
function runGraphVerticalScroller(){
  return $('run-graph-dialog').open?$('run-graph-content'):window;
}
function graphViewport(scroll){
  const host=runGraphVerticalScroller();
  const view=host===window?{top:0,bottom:window.innerHeight}:host.getBoundingClientRect();
  const {left}=scroll.getBoundingClientRect();
  return {left,right:left+scroll.clientWidth,
    top:view.top+scroll.previousElementSibling.offsetHeight,bottom:view.bottom};
}
function positionGraph(target,previous,keepVertical=false){
  const scroll=target?.closest('.dependency-scroll');
  if(!scroll)return;
  const viewport=graphViewport(scroll),bounds=target.getBoundingClientRect();
  const point=previous||{x:Math.max(viewport.left,(viewport.left+viewport.right-bounds.width)/2),
    y:Math.max(viewport.top,(viewport.top+viewport.bottom-bounds.height)/2)};
  if(!keepVertical||bounds.left<viewport.left||bounds.right>viewport.right){
    scroll.scrollBy({left:bounds.left-point.x,behavior:'instant'});
  }
  if(!keepVertical)runGraphVerticalScroller().scrollBy({top:bounds.top-point.y,behavior:'instant'});
}
function locateGraphTask(id){
  positionGraph(graphElement('data-task-row',id));
}
let runTaskReturn=null;
function revealRunTask(id,keepPosition=false){
  if(!run||selectedTask!==id)return;
  const card=document.querySelector(`.process-body [data-task-row="${CSS.escape(id)}"]`);
  if(card?.closest('.dependency-scroll'))positionGraph(card,null,keepPosition);
  else card?.scrollIntoView({block:'nearest'});
  if(!inlineTaskDetail.matches)return;
  const host=runGraphVerticalScroller();
  runTaskReturn=card?{id,runId:run.id,host,top:host===window?window.scrollY:host.scrollTop}:null;
  const detail=$('task-detail');
  detail?.scrollIntoView({block:'start'});
  detail?.querySelector('[data-close-task]')?.focus({preventScroll:true});
}
function graphAnchor(scroll){
  const canvas=scroll.querySelector('.process-canvas'),view=graphViewport(scroll);
  const bounds=canvas.getBoundingClientRect(),scale=bounds.width/canvas.offsetWidth||1;
  return {x:((view.left+view.right)/2-bounds.left)/scale,y:Math.max(0,view.top-bounds.top)/scale};
}
function restoreGraphAnchor(scroll,anchor){
  const canvas=scroll.querySelector('.process-canvas'),view=graphViewport(scroll);
  const bounds=canvas.getBoundingClientRect(),scale=bounds.width/canvas.offsetWidth||1;
  scroll.scrollBy({left:bounds.left+anchor.x*scale-(view.left+view.right)/2,behavior:'instant'});
  if(anchor.y)runGraphVerticalScroller().scrollBy({top:bounds.top+anchor.y*scale-view.top,behavior:'instant'});
}
let runGraphPageTop=0,runGraphPageLeft=0;
function setRunGraphExpanded(open,restoreFocus=true){
  const dialog=$('run-graph-dialog');
  if(dialog.open===open)return;
  const scroll=document.querySelector('.dependency-scroll');
  if(open&&!scroll)return;
  const anchor=open?graphAnchor(scroll):null;
  const viewedRun=run?.id;
  if(open){
    runGraphPageTop=window.scrollY;
    runGraphPageLeft=scroll.scrollLeft;
    dialog.classList.remove('show-filters');
    dialog.querySelector('[data-graph-filters]').setAttribute('aria-expanded','false');
    $('run-graph-content').append($('inspect'));
    dialog.showModal();
    $('run-graph-content').scrollTop=0;
  }else{
    $('run-inspect-home').append($('inspect'));
    dialog.close();
    if(!restoreFocus)return;
  }
  requestAnimationFrame(()=>{
    if(run?.id!==viewedRun||dialog.open!==open)return;
    const canvasScroll=document.querySelector('.dependency-scroll');
    sizeTaskGraph();
    if(open){
      if(canvasScroll)restoreGraphAnchor(canvasScroll,anchor);
    }else{
      if(canvasScroll)canvasScroll.scrollLeft=runGraphPageLeft;
      window.scrollTo({top:runGraphPageTop,behavior:'instant'});
      const focus=document.querySelector('[data-graph-expand]')||document.querySelector('.process-controls .selected');
      focus?.focus({preventScroll:true});
    }
  });
}
$('run-graph-dialog').addEventListener('cancel',event=>{
  event.preventDefault();setRunGraphExpanded(false);
});
window.addEventListener('resize',()=>sizeTaskGraph());
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
function durationValue(seconds){
  const hours=Math.floor(seconds/3600),minutes=Math.floor(seconds/60)%60;
  if(hours)return `${hours} 小时 ${minutes} 分钟`;
  return minutes?`${minutes} 分 ${seconds%60} 秒`:`${seconds} 秒`;
}
function readingsHTML(readings,className='node-facts'){
  const value=r=>r.format==='duration'?durationValue(r.value):r.format==='percent'?new Intl.NumberFormat('zh-CN',{style:'percent',maximumFractionDigits:2}).format(r.value):readingValue(r.value);
  return `<dl class="${className}">${readings.map(r=>`<div><dt>${esc(r.label)}</dt><dd>${esc(value(r))}${r.unit?' '+esc(r.unit):''}</dd></div>`).join('')}</dl>`;
}
function nodeDetailsHTML(task,pending){
  const details=task.node_details;
  if(!details)return pending&&task.has_node_details?'<p class="muted small" role="status">正在读取节点信息…</p>':'';
  const sections=details.sections.map(({label,items,supplementary})=>{
    const content=items.length===1?`<p>${esc(items[0])}</p>`:`<ul>${items.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`;
    return supplementary
      ?`<details class="node-result-text" data-node-section="${esc(label)}"><summary>${esc(label)}</summary>${content}</details>`
      :`<div class="node-result-text"><h4>${esc(label)}</h4>${content}</div>`;
  }).join('');
  return `<section class="node-result node-business-details"><h3>${esc(details.title)}</h3>
    ${details.facts.length?readingsHTML(details.facts,'node-facts node-business-facts'):''}
    ${details.note?`<p class="small muted">${esc(details.note)}</p>`:''}
    ${sections}
  </section>`;
}
function taskResultHTML(attempt,current,pending,details){
  if(!attempt)return '';
  const readings=attempt.output_readout||[], fields=attempt.result_content||[];
  const shown=new Set(details?.sections.flatMap(section=>section.items)||[]);
  const texts=fields.filter(field=>field.text&&!shown.has(field.text)), files=fields.filter(field=>field.file);
  if(!readings.length&&!texts.length&&!files.length&&!pending)return '';
  return `<section class="node-result"><h3>${attempt!==current?'上一次结果':readings.length&&!texts.length?'结果指标':'结果'}</h3>
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
  return task.has_node_details||(task.status!=='cancelled'&&needsReplyData(attempt))||Boolean(resultAttempt(attempts,attempt)?.has_result_content);
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
function taskDetails(item,pending,detailError){
  const t=item.tasks,attempt=item.attempts.find(e=>e.id===t.execution_id)||item.attempts.at(-1);
  const ended=run.identity_read_only||['completed','terminated','continued'].includes(run.status);
  const editable=!t.execution_id&&['planned','blocked','ready','held'].includes(t.status);
  const cancelled=t.status==='cancelled';
  const request=run.task_dispositions?.[t.id]?.reason;
  const pendingReply=pending&&needsReplyData(attempt);
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
    ${item.round||t.spec.ref?`<p class="task-detail-reference small muted">${esc([item.round,t.spec.ref].filter(Boolean).join(' · '))}</p>`:''}
    ${nodePurposeHTML(run.loop_definition.nodes[t.spec.node])}
    ${attempt?.implementation.agent_model?`<p class="task-agent-model small muted">模型 <strong>${esc(attempt.implementation.agent_model)}</strong></p>`:''}
    ${request?`<div class="wait-description"><strong>等待用户处理</strong><p>${esc(request)}</p></div>`:''}
    ${detailError?runViewErrorHTML(detailError):''}
    ${cancelled?`<section class="task-cancellation"><h3>取消原因</h3><p>${esc(taskSummary(item))}</p></section>`:
      `${taskError(attempt,t)}${taskWaitReasons(t)}
       ${pendingReply?(detailError?'':'<p class="small muted" role="status">正在读取等待条件…</p>'):waitDetails(attempt)}
       ${t.assistance_wait?'<p class="small muted">正在等待外援回复。</p>':''}
       ${progress.length&&result!==attempt?readingsHTML(progress):''}`}
    ${childRunLink(attempt)}
    ${nodeDetailsHTML(t,pending&&!detailError)}
    ${taskResultHTML(result,attempt,pending&&!detailError&&!t.has_node_details&&result?.has_result_content,result===attempt&&t.node_details)}
    ${taskFlowHTML(item)}${actions.length?`<div class="toolbar">${actions.join('')}</div>`:''}`;
}
function renderTaskHistory(detailError){
  if(run.superseded_by && !Object.keys(run.tasks).length)return '<p class="empty-inline">这次历史运行没有节点记录。</p>';
  const scroll=document.querySelector('.dependency-scroll'),detail=$('task-detail');
  const viewedRun=run.id,host=runGraphVerticalScroller();
  const position=scroll?.dataset.graphRun===viewedRun?{left:scroll.scrollLeft,top:host===window?window.scrollY:host.scrollTop}:null;
  const sameDetail=detail?.dataset.run===run.id&&detail.dataset.task===selectedTask;
  const detailTop=sameDetail?detail.scrollTop:0;
  const openSections=new Set(sameDetail
    ?[...detail.querySelectorAll('[data-node-section][open]')].map(section=>section.dataset.nodeSection):[]);
  const focused=document.activeElement;
  const focusedRound=scroll?.contains(focused)?focused.dataset.roundToggle:undefined;
  const focusedTask=scroll?.contains(focused)&&focused.matches('.task-card-main')?focused.dataset.taskFocus:undefined;
  const focusedExpand=focused?.matches('[data-graph-expand]');
  const focusedZoom=focused?.dataset.graphZoom;
  requestAnimationFrame(()=>{
    if(run?.id!==viewedRun)return;
    sizeTaskGraph();
    const updated=document.querySelector('.dependency-scroll');
    if(position&&updated?.dataset.graphRun===viewedRun&&runGraphVerticalScroller()===host){
      updated.scrollLeft=position.left;
      host.scrollTo({top:position.top,behavior:'instant'});
    }
    const currentDetail=$('task-detail');
    if(currentDetail?.dataset.task===selectedTask){
      for(const section of currentDetail.querySelectorAll('[data-node-section]'))section.open=openSections.has(section.dataset.nodeSection);
      if(detailTop)currentDetail.scrollTo(0,detailTop);
    }
    if(focusedRound!==undefined)graphElement('data-round-toggle',focusedRound)?.focus({preventScroll:true});
    if(focusedTask)graphElement('data-task-row',focusedTask)?.querySelector('.task-card-main')?.focus({preventScroll:true});
    if(focusedExpand)document.querySelector('[data-graph-expand]')?.focus({preventScroll:true});
    if(focusedZoom)document.querySelector(`[data-graph-zoom="${CSS.escape(focusedZoom)}"]`)?.focus({preventScroll:true});
  });
  taskChanges=new Set(run.changed_tasks??run.history.filter(h=>h.detail?.before&&h.detail?.tasks).map(h=>h.detail.tasks));
  const all=TaskHistory.rows(run);
  taskNumbers=new Map(all.map((item,index)=>[item.tasks.id,index+1]));
  const selected=all.find(i=>i.tasks.id===selectedTask);
  if(!selected)selectedTask=null;
  const query=taskSearch.trim().toLowerCase();
  const visible=all.filter(i=>(!filterNode||i.tasks.spec.node===filterNode)&&(!taskStatus||i.tasks.status===taskStatus)&&
    (!taskRound||i.round===taskRound)&&(!query||[taskLabel(i.tasks),i.tasks.id,i.tasks.spec.ref,i.round].join(' ').toLowerCase().includes(query)));
  const rounds=[...new Set(all.map(i=>i.round).filter(Boolean))];
  const detailPending=selected&&taskNeedsDetail(selectedTask)&&run.workspace_view&&run.workspace_view.task!==selectedTask;
  const groups=[{round:'已开始',items:visible.filter(i=>i.started!==null)},{round:'尚未开始',items:visible.filter(i=>i.started===null&&!['completed','skipped','cancelled','stale'].includes(i.tasks.status))},{round:'未执行且已结束',items:visible.filter(i=>i.started===null&&['completed','skipped','cancelled','stale'].includes(i.tasks.status))}];
  const filtered=Boolean(filterNode||taskStatus||query);
  return `<div class="process-controls" id="run-process-controls"><div class="segmented">${[['graph','节点图'],['time','时间顺序']].map(([id,label])=>`<button data-task-order="${id}" class="${taskOrder===id?'selected':''}" aria-pressed="${taskOrder===id}">${label}</button>`).join('')}</div>${rounds.length?`<label class="task-round-filter"><select id="task-round" aria-label="筛选轮次"><option value="">全部轮次</option>${rounds.map(r=>'<option value="'+esc(r)+'" '+(r===taskRound?'selected':'')+'>'+esc(r)+'</option>').join('')}</select></label>`:''}<label class="task-search-label"><span class="sr-only">查找任务</span><input id="task-search" placeholder="查找任务…" type="search" value="${esc(taskSearch)}"></label><label class="task-status-label"><span class="sr-only">任务状态</span><select id="task-status"><option value="">全部状态</option>${[...new Set(all.map(i=>i.tasks.status))].map(s=>`<option value="${esc(s)}" ${taskStatus===s?'selected':''}>${esc(labels[s]||s)}</option>`).join('')}</select></label>${filterNode?'<button id="clear-task-filter">清除节点筛选</button>':''}</div>
  <div class="process-layout"><section class="process-body">${visible.length?(taskOrder==='graph'?taskDependencyGraph(visible,filtered):groups.filter(g=>g.items.length).map(g=>`<details class="task-group" open><summary>${g.round} · ${g.items.length}</summary><div class="process-list">${g.items.map(taskCard).join('')}</div></details>`).join('')):'<p class="empty-inline">没有符合条件的任务</p>'}</section><aside id="task-detail" class="task-detail" ${selected?`data-run="${esc(run.id)}" data-task="${esc(selectedTask)}"`:'hidden'}>${selected?`<button class="close-task-detail" data-close-task aria-label="关闭节点详情">×</button><div id="task-detail-body">${taskDetails(selected,detailPending,detailError)}</div>`:''}</aside></div>`;
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
let cardPointerStart=null;
document.addEventListener('pointerdown',event=>{
  const card=event.target.closest('button:is(.task-card-main,.round-card,.round-heading)');
  cardPointerStart=event.button===0&&card?{card,x:event.clientX,y:event.clientY}:null;
});
document.addEventListener('click',event=>safely(async()=>{
  const start=cardPointerStart;cardPointerStart=null;
  const el=event.target.closest('button');if(!el)return;const d=el.dataset;
  if(event.detail&&start?.card===el&&Math.hypot(event.clientX-start.x,event.clientY-start.y)>4&&hasTextSelection(el))return;
  if(d.graphExpand!==undefined){setRunGraphExpanded(true);return;}
  if(d.graphExit!==undefined){setRunGraphExpanded(false);return;}
  if(d.graphReferences!==undefined){openGraphReferences(d.graphReferences);return;}
  if(d.graphFilters!==undefined){
    const open=$('run-graph-dialog').classList.toggle('show-filters');
    el.setAttribute('aria-expanded',String(open));
    sizeTaskGraph();
    if(open)$('run-process-controls')?.scrollIntoView({block:'start'});
    return;
  }
  if(d.roundToggle!==undefined){
    const round=d.roundToggle,rect=el.getBoundingClientRect();
    const point={x:rect.left,y:rect.top};
    if(el.getAttribute('aria-expanded')==='true'){
      expandedRounds.delete(round);
      if(selectedTask&&el.closest('[data-round-frame]')?.contains(graphElement('data-task-row',selectedTask))){
        selectedTask=null;runTaskReturn=null;syncRunTaskRoute();
      }
    }else expandedRounds.add(round);
    rememberRounds();
    inspectSignature='';renderInspect();
    requestAnimationFrame(()=>positionGraph(graphElement('data-round-toggle',round),point));
    return;
  }
  if(d.taskFocus||d.graphCurrent){
    const id=d.taskFocus||d.graphCurrent;
    if(!run.tasks[id])return;
    const card=d.graphCurrent&&graphElement('data-task-row',id);
    if(card){locateGraphTask(id);card.querySelector('.task-card-main')?.focus({preventScroll:true});return;}
    if(el.closest('.graph-reference-list'))$('detail-dialog').close();
    const keepPosition=!!el.closest('.dependency-scroll');
    if(!el.closest('[data-task-row]')){filterNode=null;taskRound='';taskSearch='';taskStatus='';}
    selectedTask=id;syncRunTaskRoute();
    inspectSignature='';renderInspect();
    requestAnimationFrame(()=>revealRunTask(id,keepPosition));
  }
  else if(d.graphZoom)sizeTaskGraph(d.graphZoom);
  else if(d.taskOrder){taskOrder=d.taskOrder;inspectSignature='';renderInspect();if(selectedTask)requestAnimationFrame(()=>locateGraphTask(selectedTask));}
  else if(d.closeTask!==undefined){
    const id=selectedTask,position=runTaskReturn,runId=run.id;
    selectedTask=null;runTaskReturn=null;syncRunTaskRoute();inspectSignature='';renderInspect();
    requestAnimationFrame(()=>{
      if(run?.id!==runId)return;
      const card=document.querySelector(`.process-body [data-task-row="${CSS.escape(id)}"]`);
      const button=card?.querySelector('.task-card-main')||document.querySelector('.dependency-scroll');
      button?.focus({preventScroll:true});
      if(!inlineTaskDetail.matches)return;
      if(position?.id===id&&position.runId===run.id&&position.host===runGraphVerticalScroller()){
        position.host.scrollTo({top:position.top,behavior:'instant'});
      }else if(card?.closest('.dependency-scroll'))positionGraph(card);
      else card?.scrollIntoView({block:'nearest'});
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
