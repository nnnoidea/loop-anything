'use strict';
let selectedTask=null,selectedAttempt=null,taskOrder='graph',taskSearch='',taskStatus='',taskRound='',taskEdit=null,taskChanges=new Set(),taskNumbers=new Map();
const expandedRounds=new Set(),mobileTaskGraph=window.matchMedia('(max-width:650px)');
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
function flowDecisionDetails(t){
  const trigger=t.origin?.flow_agent,decisions=flowDecisions(t);
  return (trigger?`<section class="flow-decision-details"><h3>内置流程决策</h3><p>触发来源：<button class="text-button" data-task-focus="${esc(trigger.task_id)}">${esc(taskLabel(run.tasks[trigger.task_id]))}</button> · ${esc(trigger.event)}</p><details><summary>事件与证据引用</summary>${resultView(trigger)}</details></section>`:'')+(decisions.length?`<section class="flow-decision-details"><h3>后续推进 · ${decisions.length} 次决策</h3>${flowDecisionButtons(t)}<p class="small muted">打开决策可查看完整结果、执行记录与原会话。</p></section>`:'');
}
function readingText(r){return r.label+' '+r.value+(r.unit?' '+r.unit:'');}
function taskStatusLabel(item){
  const attempt=item.attempts.at(-1);
  if(item.tasks.status==='waiting' && attempt?.implementation?.kind==='external' && !attempt.observation_error &&
      String(attempt.activity_progress?.external_status).toUpperCase()==='RUNNING')return '外部运行中';
  return labels[item.tasks.status]||item.tasks.status;
}
function taskBadge(item){return `<span class="badge ${esc(item.tasks.status)}">${esc(taskStatusLabel(item))}</span>`;}
function taskReadout(item,attempt=item.attempts.at(-1)){
  const fields=run.loop_definition.nodes[item.tasks.spec.node]?.readout;
  const facts=TaskHistory.readings(fields,attempt?.activity_progress,attempt?.outputs);
  const results=attempt?.output_readout??facts.filter(f=>f.source==='outputs');
  return results.length?results:facts;
}
function taskSummary(item){
  const t=item.tasks,e=item.attempts.at(-1);
  if(e?.observation_error)return '采集异常，外部任务状态待确认';
  if(['fault','stale'].includes(t.status))return failureSummary(e?.error||t.budget_error);
  const facts=taskReadout(item);
  if(facts.length)return (t.status==='completed'&&facts[0].source==='progress'?'最后回报 · ':'')+facts.map(readingText).join(' · ');
  if(e?.child_run_id&&e.status==='waiting')return '子 Loop · '+(labels[e.child_status]||e.child_status||'等待中');
  if(e?.status==='waiting'&&['timer','event','approval'].includes(e.implementation.kind))return waitSummary(e.implementation);
  if(t.wait_reasons?.length)return waitReasonText(t.wait_reasons[0]);
  return '';
}
function failureSummary(error){
  if(!error)return '执行失败，可在节点详情查看原因。';
  const last=String(error).trim().split(/\r?\n/).filter(Boolean).at(-1)||'';
  const missing=last.match(/FileNotFoundError:.*No such file or directory:\s*['"]([^'"]+)['"]/);
  if(missing)return '找不到文件或目录 '+missing[1].split(/[\\/]/).filter(Boolean).at(-1).slice(0,100)+'。';
  if(/Traceback|\bFile ".*", line \d+/.test(last))return '执行脚本报错，完整错误在节点详情中。';
  const message=last.replace(/^Handler failed:\s*/,'').trim();
  return message.length>140?message.slice(0,139)+'…':message||'执行失败，请查看节点详情。';
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
    if(['fault','stale'].includes(t.status))return failureSummary(e?.error||t.budget_error);
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
  return `<article class="process-task ${selectedTask===t.id?'picked':''}" data-status="${esc(t.status)}" data-task-focus="${esc(t.id)}" data-task-row="${esc(t.id)}"><button class="task-card-main" data-task-focus="${esc(t.id)}" aria-pressed="${selectedTask===t.id}" title="${esc([taskLabel(t),t.spec.ref,t.id].filter(Boolean).join(' · '))}"><span class="task-card-top">${taskOrder==='time'?`<small class="task-number">${String(order).padStart(2,'0')}</small>`:''}${taskBadge(item)}${taskChanges.has(t.id)?'<span data-change-mark>已调整</span>':''}</span><span class="task-name">${esc(taskLabel(t))}</span>${t.spec.ref?`<small class="task-card-ref">${esc(t.spec.ref)}</small>`:''}<span class="task-summary">${esc(taskSummary(item))}</span><small class="task-card-time">${esc([item.round,item.started===null&&['skipped','cancelled'].includes(t.status)?'未执行':taskTime(item.started)].filter(Boolean).join(' · '))}</small></button><div class="task-card-actions"><button data-task-result="${esc(t.id)}">查看结果</button>${flowDecisionButtons(t,true)}${agent?`<button data-agent-session="${esc(attempt.id)}" ${['completed','terminated','continued'].includes(run.status)&&!active?'disabled title="Run 已结束，可查看结果与会话记录"':''}>${active?'打开会话':'恢复会话'}</button>`:''}</div></article>`;
}
function roundToggle(card){
  const round=card.round||'未标注轮次';
  const id=`data-round-toggle="${esc(card.round)}" aria-expanded="${card.open}"`;
  if(card.open)return `<button class="round-collapse" ${id} aria-label="收起 ${esc(round)} 已完成节点">⌃ 收起 ${esc(round)}</button>`;
  const recent=[...card.members].reverse().find(item=>taskReadout(item).some(f=>f.source==='outputs'));
  return `<button class="round-card" ${id}><strong>${esc(round)}</strong><span>${card.members.length} 个节点已完成</span>${recent?`<small>${esc(taskSummary(recent))}</small>`:''}<span class="round-action">展开已完成节点 <span aria-hidden="true">⌄</span></span></button>`;
}
function taskDependencyGraph(items,filtered){
  const business=TaskHistory.businessGraph(run,items);
  const {nodes,links}=TaskHistory.roundGraph(business,expandedRounds,selectedTask,filtered);
  if(!nodes.length)return '<p class="empty-inline">流程决策可在时间顺序中查看。</p>';
  const parents=new Map(nodes.map(node=>[node.id,[]]));
  for(const link of links)parents.get(link.to).push(link.from);
  const levels=new Map(),pending=new Set(parents.keys());
  while(pending.size){
    // A collapsed round may have both incoming and outgoing edges to another round.
    const ready=[...pending].filter(id=>parents.get(id).every(from=>levels.has(from)));
    for(const id of ready.length?ready:[pending.values().next().value]){
      levels.set(id,Math.max(0,...parents.get(id).filter(from=>levels.has(from)).map(from=>levels.get(from)+1)));
      pending.delete(id);
    }
  }
  const columns=[],positions=new Map(),cardWidth=224,cardHeight=168,gap=54,margin=44,columnStep=308;
  for(const node of nodes)(columns[levels.get(node.id)]??=[]).push(node);
  const mobile=mobileTaskGraph.matches;
  const height=2*margin+(mobile?nodes.length:Math.max(...columns.map(column=>column.length)))*(cardHeight+gap)-gap;
  const width=mobile?cardWidth+2*margin:cardWidth+2*margin+(columns.length-1)*columnStep;
  if(mobile){
    columns.flat().forEach((node,i)=>positions.set(node.id,{x:margin,y:margin+i*(cardHeight+gap)}));
  }else{
    columns.forEach((column,col)=>column.forEach((node,row)=>positions.set(node.id,{x:margin+col*columnStep,y:(height-column.length*(cardHeight+gap)+gap)/2+row*(cardHeight+gap)})));
    for(const column of columns.slice(1)){
      let bottom=margin;
      for(const {id} of column){
        const upstream=parents.get(id).filter(from=>levels.get(from)<levels.get(id)).map(from=>positions.get(from));
        const p=positions.get(id);
        if(upstream.length)p.y=upstream.reduce((sum,prior)=>sum+prior.y,0)/upstream.length;
        p.y=Math.max(bottom,p.y);bottom=p.y+cardHeight+gap;
      }
      let top=height-margin-cardHeight;
      for(const {id} of [...column].reverse()){
        const p=positions.get(id);p.y=Math.min(top,p.y);top=p.y-cardHeight-gap;
      }
    }
  }
  function edgePath({from,to,kind}){
    const a=positions.get(from),b=positions.get(to),ay=a.y+cardHeight/2,by=b.y+cardHeight/2;
    const lane={dependency:15,planning:23,recovery:31}[kind];
    if(mobile){
      const side=a.y<b.y?a.x:a.x+cardWidth,rail=a.y<b.y?lane:width-lane;
      return `M${side} ${ay} C${rail} ${ay},${rail} ${ay},${rail} ${ay+(by-ay)*.18} V${by-(by-ay)*.18} C${rail} ${by},${rail} ${by},${side} ${by}`;
    }
    const ax=a.x+cardWidth,bx=b.x;
    if(a.x>=b.x)return `M${ax} ${ay} H${ax+lane} V${lane} H${bx-lane} V${by} H${bx}`;
    let x=ax,y=ay,path=`M${x} ${y}`;
    const curve=(nx,ny)=>{const bend=(nx-x)/2;path+=` C${x+bend} ${y},${nx-bend} ${ny},${nx} ${ny}`;x=nx;y=ny;};
    for(let col=levels.get(from)+1;col<levels.get(to);col++){
      const obstacles=columns[col].map(node=>positions.get(node.id)),desired=(ay+by)/2;
      const candidates=[desired,12,height-12,...obstacles.flatMap(p=>[p.y-12,p.y+cardHeight+12])];
      const safe=candidates.filter(v=>v>=12&&v<=height-12&&obstacles.every(p=>v<=p.y-8||v>=p.y+cardHeight+8)).sort((a,b)=>Math.abs(a-desired)-Math.abs(b-desired))[0];
      const left=margin+col*columnStep;curve(left-12,safe);x=left+cardWidth+12;path+=` L${x} ${safe}`;
    }
    curve(bx,by);return path;
  }
  const related=link=>selectedTask===link.from||selectedTask===link.to;
  const paths=[...links].sort((a,b)=>Number(related(a))-Number(related(b))).map(link=>{
    const {from,to,kind}=link,active=related(link);
    return `<path class="${kind} ${active?'related':''}" data-edge-kind="${kind}" data-edge-from="${esc(from)}" data-edge-to="${esc(to)}" d="${edgePath(link)}" marker-end="url(#task-arrow-${kind})"></path>`;
  }).join('');
  const current=business.items.find(i=>i.tasks.status==='fault'||i.attempts.at(-1)?.observation_error)
    ||business.items.find(i=>['executing','waiting','waiting_user','ready','blocked'].includes(i.tasks.status));
  const cards=nodes.map(node=>{
    const {x,y}=positions.get(node.id);
    return `<div class="process-node" style="left:${x}px;top:${y}px;width:${cardWidth}px">${node.card?roundToggle(node.card):''}${node.item?taskCard(node.item):''}</div>`;
  }).join('');
  return `<div class="graph-tools"><span class="graph-legend">蓝色依赖 · 紫色安排 · 红色异常来源</span><div>${current?`<button data-graph-current="${esc(current.tasks.id)}">定位当前</button>`:''}<button data-graph-zoom="out" aria-label="缩小依赖图">−</button><button id="graph-scale" data-graph-zoom="actual" aria-label="恢复实际大小"></button><button data-graph-zoom="in" aria-label="放大依赖图">＋</button><button data-graph-zoom="fit">${mobile?'适应宽度':'适应画布'}</button></div></div><div class="dependency-scroll" data-graph-run="${esc(run.id)}" tabindex="0" aria-label="节点图画布"><div class="process-extent"><div class="process-canvas" style="width:${width}px;height:${height}px"><svg width="${width}" height="${height}" aria-hidden="true"><defs>${['dependency','planning','recovery'].map(kind=>`<marker id="task-arrow-${kind}" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" style="fill:${kind==='recovery'?'#bd705f':kind==='planning'?'#9564cf':'#7293bb'}"/></marker>`).join('')}</defs><g class="dependency-lines${links.some(related)?' has-related':''}">${paths}</g></svg>${cards}</div></div></div>`;
}
let graphScale=null,graphRun=null;
function sizeTaskGraph(mode){
  const canvas=document.querySelector('.process-canvas'),scroll=canvas?.closest('.dependency-scroll');if(!canvas || !canvas.offsetWidth || !canvas.offsetHeight || scroll.clientWidth<=24 || scroll.clientHeight<=24)return;
  if(graphRun!==run.id){graphScale=null;graphRun=run.id;}
  const widthFit=Math.min(1,(scroll.clientWidth-24)/canvas.offsetWidth);
  const mobile=mobileTaskGraph.matches;
  const natural=mobile?widthFit:1;
  const fit=mobile?widthFit:Math.min(widthFit,(scroll.clientHeight-24)/canvas.offsetHeight);
  if(mode==='fit')graphScale=fit;
  else if(mode==='actual')graphScale=natural;
  else if(mode==='in')graphScale=Math.min(1.5,(graphScale??natural)+.15);
  else if(mode==='out')graphScale=Math.max(mobile ? 0.6 : 0.2,(graphScale??natural)-.15);
  else graphScale??=natural;
  canvas.style.transform=`scale(${graphScale})`;canvas.parentElement.style.width=canvas.offsetWidth*graphScale+'px';canvas.parentElement.style.height=canvas.offsetHeight*graphScale+'px';
  $('graph-scale').textContent=Math.round(graphScale*100)+'%';
}
function graphElement(attribute,value){
  return document.querySelector(`.process-canvas [${attribute}="${CSS.escape(value)}"]`);
}
function positionGraph(target,previous){
  const scroll=target?.closest('.dependency-scroll');
  if(!scroll)return;
  const viewport=scroll.getBoundingClientRect(),bounds=target.getBoundingClientRect();
  const offset=previous||{x:(viewport.width-bounds.width)/2,y:(viewport.height-bounds.height)/2};
  scroll.scrollBy(bounds.left-viewport.left-offset.x,bounds.top-viewport.top-offset.y);
}
function locateGraphTask(id){
  positionGraph(graphElement('data-task-row',id));
}
window.addEventListener('resize',()=>sizeTaskGraph());
mobileTaskGraph.addEventListener('change',()=>{
  graphScale=null;
  if(page==='runs'&&run){inspectSignature='';renderInspect();if(selectedTask)requestAnimationFrame(()=>locateGraphTask(selectedTask));}
});
function taskError(attempt){
  if(!attempt?.error)return '';
  const raw=String(attempt.error);
  const summary=attempt.failure_kind==='command_start'?'命令启动配置错误':attempt.failure_kind==='agent_command'?'Agent 命令异常':attempt.observation_error?'监控异常，外部工作状态未知':raw.includes('Agent exited without sealing')?'Agent 未成功提交结果就退出了。':raw.includes('Agent exited without calling finish')?'Agent 退出前未释放操作权。':failureSummary(raw);
  return `<section class="task-error" role="note"><strong>${esc(summary)}</strong><details><summary>原始错误与证据路径</summary><pre>${esc(raw)}</pre></details></section>`;
}
function resultWithSchema(value,schema={},attempt,port,parts=[]){
  if(schema.format==='file'&&typeof value==='string'&&attempt){const url=`/api/runs/${encodeURIComponent(run.id)}/artifact?execution=${encodeURIComponent(attempt.id)}&output=${encodeURIComponent(port)}&path=${encodeURIComponent(JSON.stringify(parts))}`;return `${/\.(png|jpe?g|gif|webp)$/i.test(value)?`<img class="result-image" src="${esc(url)}" alt="${esc(port)}" loading="lazy">`:''}<a class="button" href="${esc(url)}" target="_blank" rel="noopener">查看文件 · ${esc(value)}</a>`;}
  if(Array.isArray(value)){if(schema.items?.format==='file')return value.map((v,i)=>resultWithSchema(v,schema.items,attempt,port,[...parts,i])).join(' ');return resultView(value);}
  if(value && typeof value==='object')return `<dl class="result-fields">${Object.entries(value).map(([k,v])=>`<div><dt>${esc(schema.properties?.[k]?.title || k)}</dt><dd>${resultWithSchema(v,schema.properties?.[k] || {},attempt,port,[...parts,k])}</dd></div>`).join('')}</dl>`;
  return resultView(value);
}
function waitReasonText(r){
  return r.reason==='order_dependency'?`等待前置任务 ${(run.tasks[r.action]?taskLabel(run.tasks[r.action]):r.action)} 完成`:r.reason==='missing_record'?`输入 ${r.input} 等待结果 ${r.record}`:r.reason==='missing_implementation'?'尚未选用可执行的实现；请由运行 Agent 选择已有方案；补充 Loop 实现使用构建 Agent':r.reason==='invalid_parameters'?'参数不满足所选实现的要求；由运行 Agent 核对任务参数，完整契约可在节点详情查看':r.reason==='invalid_input'?`输入 ${r.input} 尚不可用`:r.reason==='retry_pending'?'等待同一任务的旧进程确认结束，再重试原任务':r.detail||r.reason;
}
function taskWaitReasons(task){
  if(['skipped','cancelled'].includes(task.status)||!task.wait_reasons?.length)return '';
  return `<div class="wait-reasons"><strong>当前等待原因</strong><ul>${task.wait_reasons.map(r=>`<li>${esc(waitReasonText(r))}</li>`).join('')}</ul><details><summary>查看详细条件</summary>${resultView(task.wait_reasons)}</details></div>`;
}
function taskFlowHTML(item){
  const id=item.tasks.id,edges=TaskHistory.links(run),incoming=edges.filter(e=>e.to===id),outgoing=edges.filter(e=>e.from===id);
  const link=(e,target)=>`<li class="${e.kind}"><small>${e.kind==='recovery'?'异常来源':e.kind==='planning'?'明确安排':'执行依赖'}</small><button class="text-button" data-task-focus="${esc(target)}">${esc(taskLabel(run.tasks[target]))}</button>${badge(run.tasks[target].status)}</li>`;
  return `<section class="task-flow"><h3>任务关系与推进</h3>${incoming.length?`<h4>来源</h4><ul>${incoming.map(e=>link(e,e.from)).join('')}</ul>`:''}${outgoing.length?`<h4>后续与异常处理</h4><ul>${outgoing.map(e=>link(e,e.to)).join('')}</ul>`:''}${!incoming.length&&!outgoing.length?'<p class="small muted">暂无已记录的关联任务。</p>':''}${item.tasks.origin?.route_id?`<p class="small muted">事件触发：${esc(item.tasks.origin.route_id)} → ${item.tasks.origin.flow_agent?'内置流程 Agent':'模板 '+esc(item.tasks.origin.plan)} · 报告 ${esc(item.tasks.origin.report_id)}</p>`:''}${taskWaitReasons(item.tasks)}${item.tasks.origin?.fallback?`<details><summary>触发兜底时记录的问题</summary>${resultView(item.tasks.origin.issues||[])}</details>`:''}</section>`;
}
function taskRevisionText(value){return value==null?'修订未记录':'修订 '+value;}
function taskDetails(item){
  if(!item)return '<p class="empty-inline">选择任务，查看结果或调整后续工作。</p>';
  const t=item.tasks,attempt=item.attempts.find(e=>e.id===selectedAttempt)||item.attempts.at(-1),editable=run.status!=='continued'&&!t.execution_id&&['planned','blocked','ready','held'].includes(t.status),ended=['completed','terminated','continued'].includes(run.status);
  const facts=taskReadout(item,attempt);
  const edits=run.history.filter(h=>h.detail?.tasks===t.id&&(h.detail.before||h.kind==='planned'));
  return `<div class="task-detail-heading"><h2>${esc(taskLabel(t))}</h2>${taskBadge(item)}</div><p class="small muted">${esc([item.round,t.spec.ref].filter(Boolean).join(' · '))}</p>
    ${facts.length?`${attempt.status==='completed'&&facts[0].source==='progress'?'<small class="muted">最后一次进度回报</small>':''}<dl class="node-facts">${facts.map(f=>`<div><dt>${esc(f.label)}</dt><dd>${esc(f.value)} ${esc(f.unit||'')}</dd></div>`).join('')}</dl>`:''}
    ${taskError(attempt)}${taskWaitReasons(t)}<div class="toolbar">${item.attempts.some(e=>Object.keys(e.outputs||{}).length)?`<button data-task-result="${esc(t.id)}">查看结果</button>`: ''}<button data-task-assistance="${esc(t.id)}">查看外援请求</button>${editable&&!ended?`<button data-task-cancel="${esc(t.id)}">取消任务</button>`:''}${(['fault','stale','cancelled','waiting_user','retrying'].includes(t.status)||attempt?.observation_error)&&!ended?`<button data-task-retry="${esc(t.id)}">${attempt?.observation_error?'恢复监控':'重试任务'}</button>`:''}</div>
  ${attempt?.status==='waiting'&&['timer','event','loop'].includes(attempt.implementation.kind)&&!ended?`<button data-task-cancel="${esc(t.id)}">取消等待</button>`:''}${t.assistance_wait?'<p class="small muted">正在等待外援回复；等待结束后继续当前任务。</p>':''}${attempt?.communication_state?`<p class="small muted">群组执行：${esc(communicationStates[attempt.communication_state]||attempt.communication_state)}</p>`:''}<section class="task-execution"><h3>执行记录 · ${item.attempts.length} 次</h3>${item.attempts.length>1?`<label>执行尝试<select id="task-attempt">${item.attempts.map(e=>`<option value="${esc(e.id)}" ${e.id===attempt?.id?'selected':''}>第 ${e.attempt} 次 · ${esc(taskRevisionText(e.task_revision))} · ${esc(labels[e.status]||e.status)} · ${taskTime(TaskHistory.startTime(e))}${Object.hasOwn(e,'started_at')?'':' · 历史派发时间'}</option>`).join('')}</select></label>`:''}${attempt?.implementation.kind==='agent'&&(attempt.implementation.command||attempt.communication_id)?`<button data-open-terminal="${esc(attempt.id)}">${attempt.implementation.terminal?'打开交互终端':'查看实时输出'}</button>`:''}${attempt?.implementation.kind==='agent'&&!ended?`<button data-agent-session="${esc(attempt.id)}">${attempt.worker_active?'打开会话':'恢复会话'}</button>`:''}${waitDetails(attempt)}<details><summary>执行诊断与来源</summary><p class="task-detail-id">${esc(t.id)} · <span data-task-revision>${esc(taskRevisionText(t.revision))}</span></p>${executionLifecycle(attempt)}${promptHistory(attempt)}${flowDecisionDetails(t)}${taskFlowHTML(item)}<h3>输入与来源</h3>${Object.entries(attempt?.inputs || {}).map(([port,value])=>`<section><h4>${esc(run.loop_definition.nodes[t.spec.node].inputs[port]?.title || port)}</h4>${resultView(value)}${sourceLinks(attempt.sources?.[port])}</section>`).join('') || resultView(t.spec.inputs)}
  <h3>当前前置任务</h3>${item.dependencies.map(id=>`<button class="text-button" data-task-focus="${esc(id)}">${esc(taskLabel(run.tasks[id]))}</button>`).join(' ')||'<span class="muted">无</span>'}
  <h3>${attempt?'所选执行的参数与实现':'当前任务的参数与实现'}</h3>${resultView(attempt?attempt.parameters||{}:t.spec.parameters||{})}<p>${esc(attempt?(attempt.implementation_id||'历史实现标识未记录'):(t.spec.implementation||'沿用运行默认实现'))}</p>
  ${attempt?.task_spec?`<details><summary>本次执行采用的任务安排 · ${esc(taskRevisionText(attempt.task_revision))}</summary>${resultView(attempt.task_spec)}</details>`:''}${attempt&&attempt.task_revision!==t.revision?`<details><summary>当前任务安排 · ${esc(taskRevisionText(t.revision))}</summary>${resultView(t.spec)}</details>`:''}
  <h3>安排与修改</h3>${edits.map(h=>`<details><summary>${esc(taskTime(h.at))} · ${esc(h.message)} · ${h.detail.before?esc(taskRevisionText(h.detail.before_revision))+' → ':''}${esc(taskRevisionText(h.detail.after_revision))}</summary>${h.detail.actor?`<p class="small muted">操作者：${esc(({user:'用户',interactive:'持权操作者',background:'后台 Agent',engine:'Engine'})[h.detail.actor.kind]||h.detail.actor.kind)}${h.detail.actor.execution_id?' · '+esc(h.detail.actor.execution_id):''}</p>`:''}${h.detail.before?`<p>修改前</p>${resultView(h.detail.before)}`:''}<p>修改后</p>${resultView(h.detail.after)}</details>`).join('')||'<p class="muted">没有额外修改记录</p>'}
  <details><summary>原始记录</summary><pre>${esc(pretty({task:t,execution:attempt}))}</pre></details></details></section>`;
}
function sourceLinks(source){return (Array.isArray(source)?source:[source]).filter(Boolean).map(s=>{const e=run.executions.find(e=>e.id===s.execution);return e?`<button class="text-button" data-source-execution="${esc(e.id)}">来自 ${esc(taskLabel(run.tasks[e.task_id]))} · v${esc(s.revision)}</button>`:`<small>${esc(s.run_input?'初始输入 '+s.run_input:s.settings?'设置 '+s.settings:'直接输入')}</small>`;}).join(' ');}
function routeAuditHTML(){return `${run.history.filter(h=>h.kind==='plan_built'&&h.detail?.omitted?.length).map(h=>`<details class="omitted-steps"><summary>未安排的步骤 · ${esc(h.detail.name)} · ${esc(taskTime(h.at))}</summary>${omittedStepsHTML(h.detail.omitted,h.detail.name)}</details>`).join('')}${run.history.filter(h=>h.kind==='route_fired'||h.kind==='route_skipped').map(h=>`<details class="omitted-steps"><summary>${h.kind==='route_skipped'?'路由已跳过':'事件触发'} · ${esc(h.detail.route_id)} → ${esc(h.detail.flow_agent?'内置流程 Agent':h.detail.plan)} · ${h.detail.batches.reduce((n,b)=>n+b.task_ids.length,0)} 项任务</summary><p>来源：<button class="text-button" data-task-focus="${esc(h.detail.task_id)}">${esc(taskLabel(run.tasks[h.detail.task_id]))}</button> · ${esc(h.detail.event)}</p>${resultView(h.detail)}</details>`).join('')}`;}
document.addEventListener('toggle',event=>{
  const panel=event.target;
  if(panel.matches?.('.route-audit[open]') && panel.children.length===1 && panel.dataset.auditRun===run?.id){
    if(run.workspace_view&&!run.workspace_view.audit){
      panel.insertAdjacentHTML('beforeend','<p class="empty-inline" role="status">正在读取推进记录…</p>');
      safely(refreshRunWorkspace);
    }else panel.insertAdjacentHTML('beforeend',routeAuditHTML());
  }
},true);
function renderTaskHistory(){
  if(run.superseded_by && !Object.keys(run.tasks).length)return '<p class="empty-inline">这次历史运行没有节点记录。</p>';
  const scroll=document.querySelector('.dependency-scroll'),detail=$('task-detail');
  const position=scroll?.dataset.graphRun===run.id?{left:scroll.scrollLeft,top:scroll.scrollTop}:null;
  const detailTop=detail?.dataset.task===selectedTask?detail.scrollTop:0;
  const focused=document.activeElement;
  const focusedRound=scroll?.contains(focused)?focused.dataset.roundToggle:undefined;
  const focusedTask=scroll?.contains(focused)&&focused.matches('.task-card-main')?focused.dataset.taskFocus:undefined;
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
  });
  taskChanges=new Set(run.changed_tasks??run.history.filter(h=>h.detail?.before&&h.detail?.tasks).map(h=>h.detail.tasks));
  const all=TaskHistory.rows(run),business=all.filter(i=>!i.tasks.origin?.flow_agent);
  taskNumbers=new Map(all.map((item,index)=>[item.tasks.id,index+1]));
  const selected=all.find(i=>i.tasks.id===selectedTask);
  if(!selected){selectedTask=null;selectedAttempt=null;}
  if(selected?.tasks.status==='completed'&&!expandedRounds.has(selected.round||'')){
    expandedRounds.add(selected.round||'');rememberRounds();
  }
  const query=taskSearch.trim().toLowerCase();
  const visible=all.filter(i=>(!filterNode||i.tasks.spec.node===filterNode)&&(!taskStatus||i.tasks.status===taskStatus)&&
    (!taskRound||i.round===taskRound)&&(!query||[taskLabel(i.tasks),i.tasks.id,i.tasks.spec.ref,i.round].join(' ').toLowerCase().includes(query)));
  const rounds=[...new Set(all.map(i=>i.round).filter(Boolean))];
  const auditOpen=document.querySelector('.route-audit[open]')?.dataset.auditRun===run.id;
  const auditPending=auditOpen&&run.workspace_view&&!run.workspace_view.audit;
  const detailPending=selected&&run.workspace_view&&run.workspace_view.task!==selectedTask;
  const groups=[{round:'已开始',items:visible.filter(i=>i.started!==null)},{round:'尚未开始',items:visible.filter(i=>i.started===null&&!['completed','skipped','cancelled','stale'].includes(i.tasks.status))},{round:'未执行且已结束',items:visible.filter(i=>i.started===null&&['completed','skipped','cancelled','stale'].includes(i.tasks.status))}];
  const filtered=Boolean(filterNode||taskStatus||query);
  return `<div class="task-heading"><div><h2>节点进度</h2><p class="muted small">${business.length} 项任务${rounds.length?' · '+rounds.length+' 轮':''}${all.length>business.length?' · '+(all.length-business.length)+' 次流程决策':''}</p></div></div><div class="process-controls"><div class="segmented">${[['graph','节点图'],['time','时间顺序']].map(([id,label])=>`<button data-task-order="${id}" class="${taskOrder===id?'selected':''}" aria-pressed="${taskOrder===id}">${label}</button>`).join('')}</div>${rounds.length?`<label class="task-round-filter"><select id="task-round" aria-label="筛选轮次"><option value="">全部轮次</option>${rounds.map(r=>'<option value="'+esc(r)+'" '+(r===taskRound?'selected':'')+'>'+esc(r)+'</option>').join('')}</select></label>`:''}<label class="task-search-label"><span class="sr-only">查找任务</span><input id="task-search" placeholder="查找任务…" type="search" value="${esc(taskSearch)}"></label><label class="task-status-label"><span class="sr-only">任务状态</span><select id="task-status"><option value="">全部状态</option>${[...new Set(all.map(i=>i.tasks.status))].map(s=>`<option value="${esc(s)}" ${taskStatus===s?'selected':''}>${esc(labels[s]||s)}</option>`).join('')}</select></label>${filterNode?'<button id="clear-task-filter">清除节点筛选</button>':''}</div>
  <div class="process-layout ${selected?'':'process-only'}"><section class="process-body">${visible.length?(taskOrder==='graph'?taskDependencyGraph(visible,filtered):groups.filter(g=>g.items.length).map(g=>`<details class="task-group" open><summary>${g.round} · ${g.items.length}</summary><div class="process-list">${g.items.map(taskCard).join('')}</div></details>`).join('')):'<p class="empty-inline">没有符合条件的任务</p>'}</section><aside id="task-detail" class="task-detail" ${selected?`data-task="${esc(selectedTask)}"`:'hidden'}>${selected?`<button class="close-task-detail" data-close-task aria-label="关闭节点详情">×</button><div id="task-detail-body">${detailPending?'<p class="empty-inline" role="status">正在读取节点详情…</p>':taskDetails(selected)}</div>`:''}</aside></div><details class="route-audit" data-audit-run="${esc(run.id)}" ${auditOpen?'open':''}><summary>推进记录</summary>${auditOpen?(auditPending?'<p class="empty-inline" role="status">正在读取推进记录…</p>':routeAuditHTML()):''}</details>`;
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
function omittedStepsHTML(items,planName){return items.length?`<section class="omitted-summary"><h3>未安排 · 不创建任务</h3>${items.map(item=>`<p><strong>${esc(run.loop_definition.nodes[run.loop_definition.plans[item.plan||planName]?.steps[item.step]?.node]?.label||item.step)}</strong> · ${esc(({not_selected:'本次未选择',condition_false:'安排条件不满足',empty_items:'展开列表为空'})[item.reason]||item.reason)}</p>${item.when?`<details><summary>安排条件</summary><pre>${esc(pretty(item.when))}</pre></details>`:''}`).join('')}</section>`:'';}
function collectTaskEdit(){return [{tool:'change_task',arguments:{task_id:taskEdit.id,operation:taskEdit.kind,reason:$('task-edit-reason').value.trim()||$('task-edit-title').textContent}}];}
document.addEventListener('click',event=>safely(async()=>{
  const el=event.target.closest('button');if(!el)return;const d=el.dataset;
  if(d.roundToggle!==undefined){
    const round=d.roundToggle,scroll=el.closest('.dependency-scroll').getBoundingClientRect(),rect=el.getBoundingClientRect();
    const offset={x:rect.left-scroll.left,y:rect.top-scroll.top};
    if(el.getAttribute('aria-expanded')==='true'){
      expandedRounds.delete(round);
      const task=run.tasks[selectedTask];
      if(task?.status==='completed'&&(task.spec.round||'')===round){selectedTask=null;selectedAttempt=null;syncRunTaskRoute();}
    }else expandedRounds.add(round);
    rememberRounds();
    inspectSignature='';renderInspect();
    requestAnimationFrame(()=>positionGraph(graphElement('data-round-toggle',round),offset));
    return;
  }
  if(d.focusGroup){
    taskOrder='graph';activeTab='task-history';taskRound='';taskStatus='';taskSearch='';filterNode=d.focusGroup;selectedTask=null;selectedAttempt=null;
    syncRunTaskRoute();
    inspectSignature='';renderInspect();
    document.querySelector('.process-controls')?.scrollIntoView({block:'start'});return;
  }
  if(d.taskFocus||d.sourceExecution){
    const id=d.taskFocus||run.executions.find(e=>e.id===d.sourceExecution)?.task_id;
    if(!run.tasks[id])return;
    if(!el.closest('[data-task-row]')){filterNode=null;taskRound='';taskSearch='';taskStatus='';}
    selectedTask=id;selectedAttempt=d.sourceExecution||null;syncRunTaskRoute();
    inspectSignature='';renderInspect();
    requestAnimationFrame(()=>{locateGraphTask(id);if(window.matchMedia('(max-width:800px)').matches)$('task-detail')?.scrollIntoView({block:'start'});});
  }
  else if(d.graphCurrent){locateGraphTask(d.graphCurrent);graphElement('data-task-row',d.graphCurrent)?.querySelector('.task-card-main')?.focus({preventScroll:true});}
  else if(d.graphZoom)sizeTaskGraph(d.graphZoom);
  else if(d.taskOrder){taskOrder=d.taskOrder;inspectSignature='';renderInspect();if(selectedTask)requestAnimationFrame(()=>locateGraphTask(selectedTask));}
  else if(d.closeTask!==undefined){
    const id=selectedTask;selectedTask=null;selectedAttempt=null;syncRunTaskRoute();inspectSignature='';renderInspect();
    requestAnimationFrame(()=>{
      const card=document.querySelector(`.process-body [data-task-row="${CSS.escape(id)}"]`);
      positionGraph(card);
      const button=card?.querySelector('.task-card-main')||document.querySelector('.dependency-scroll');
      button?.focus({preventScroll:true});
      if(window.matchMedia('(max-width:800px)').matches)document.querySelector('.process-controls')?.scrollIntoView({block:'start'});
    });
  }
  else if(d.taskCancel)openTaskEdit('cancel',d.taskCancel);
  else if(d.taskRetry)openTaskEdit('retry',d.taskRetry);
  else if(el.id==='clear-task-filter'){filterNode=null;inspectSignature='';renderInspect();}
}));
document.addEventListener('change',event=>{const el=event.target;
  if(el.id==='task-status'||el.id==='task-search'){taskStatus=$('task-status').value;taskSearch=$('task-search').value;inspectSignature='';renderInspect();}
  if(el.id==='task-round'){taskRound=el.value;selectedTask=null;selectedAttempt=null;syncRunTaskRoute();inspectSignature='';renderInspect();}
  if(el.id==='task-attempt'){selectedAttempt=el.value;$('task-detail-body').innerHTML=taskDetails(TaskHistory.rows(run).find(i=>i.tasks.id===selectedTask));}
});
document.addEventListener('submit',event=>{
  if(event.target.id!=='task-edit-form')return;event.preventDefault();
  (async()=>{try{
    $('task-edit-error').textContent='';
    await platformCall('submit_run_request',{request_id:taskEdit.key,run_id:taskEdit.runId,operation:'edit_tasks',message:$('task-edit-reason').value,arguments:{changes:collectTaskEdit()}});
    editDialog.close();await refresh();toast('任务已更新');
  }catch(e){$('task-edit-error').textContent=e.message;}})();
});
