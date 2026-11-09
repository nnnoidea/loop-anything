'use strict';
let selectedTask=null,selectedAttempt=null,taskOrder='graph',taskSearch='',taskStatus='',taskEdit=null,taskChanges=new Map(),taskNumbers=new Map();
const taskTime=t=>t?new Date(t*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'尚未开始';
const taskLabel=t=>run.loop_definition.nodes[t.spec.node]?.label || t.spec.node;
function flowDecisions(t){return Object.values(run.tasks).filter(d=>d.origin?.flow_agent?.task_id===t.id);}
function flowDecisionButtons(t,compact=false){const decisions=flowDecisions(t);return (compact?decisions.slice(-1):decisions).map(d=>`<button class="flow-decision-link" data-task-focus="${esc(d.id)}">✦ 决策 · ${esc(labels[d.status]||d.status)}</button>`).join('');}
function flowDecisionDetails(t){
  const trigger=t.origin?.flow_agent,decisions=flowDecisions(t);
  return (trigger?`<section class="flow-decision-details"><h3>内置流程决策</h3><p>触发来源：<button class="text-button" data-task-focus="${esc(trigger.task_id)}">${esc(taskLabel(run.tasks[trigger.task_id]))}</button> · ${esc(trigger.event)}</p><details><summary>事件与证据引用</summary>${resultView(trigger)}</details></section>`:'')+(decisions.length?`<section class="flow-decision-details"><h3>后续推进 · ${decisions.length} 次决策</h3>${flowDecisionButtons(t)}<p class="small muted">打开决策可查看完整结果、执行记录与原会话。</p></section>`:'');
}
function taskSummary(item){if(item.tasks.status==='skipped')return '历史记录：已跳过，不再等待执行';if(item.tasks.status==='cancelled')return '已取消，不再等待执行';const e=item.attempts.at(-1);if(e?.child_run_id&&e.status==='waiting')return '子 Loop · '+(labels[e.child_status]||e.child_status||'等待中');if(e?.status==='waiting'&&['timer','event','approval'].includes(e.implementation.kind))return waitSummary(e.implementation);if(e?.observation_error)return '监控需要恢复 · 外部状态待确认';const values=Object.entries(e?.outputs || {});return values.slice(0,2).map(([k,v])=>`${k}：${typeof v==='object'?(Array.isArray(v)?v.length+' 项':'已保存'):String(v).slice(0,64)}`).join(' · ') || (e?.lifecycle_state?'当前阶段：'+lifecycleName(e.lifecycle_state):'');}
function taskCard(item){
  const t=item.tasks,order=taskNumbers.get(t.id),attempt=item.attempts.at(-1),agent=attempt?.implementation.kind==='agent',active=attempt?.worker_active||(run.agent_sessions||[]).some(o=>o.resume_execution===attempt?.id);
  return `<article class="process-task ${selectedTask===t.id?'picked':''}" data-status="${esc(t.status)}" data-task-focus="${esc(t.id)}" data-task-row="${esc(t.id)}"><button class="task-card-main" data-task-focus="${esc(t.id)}" aria-pressed="${selectedTask===t.id}" title="${esc(taskLabel(t)+' · '+t.id)}"><span class="task-card-top"><small class="task-number">${String(order).padStart(2,'0')}</small>${badge(t.status)}${taskChanges.has(t.id)?'<span data-change-mark>已调整</span>':''}</span><span class="task-name">${esc(taskLabel(t))}</span>${nodeAxesHTML(run,t.spec.node,taskImplementation(run,t,attempt),null)}<span class="task-summary">${esc(taskSummary(item)||(['fault','stale'].includes(t.status)?'查看失败详情 →':'等待结果'))}</span><small class="task-card-time">${esc([item.round,item.started===null&&['skipped','cancelled'].includes(t.status)?'未执行':taskTime(item.started),item.legacyTime?'历史派发时间':null].filter(Boolean).join(' · '))}</small></button><div class="task-card-actions"><button data-task-result="${esc(t.id)}">查看结果</button>${flowDecisionButtons(t,true)}${agent?`<button data-agent-session="${esc(attempt.id)}" ${['completed','terminated'].includes(run.status)&&!active?'disabled title="Run 已结束，可查看结果与会话记录"':''}>${active?'打开会话':'恢复会话'}</button>`:''}</div></article>`;
}
function taskDependencyGraph(items){
  const graph=TaskHistory.businessGraph(run,items);items=graph.items;
  if(!items.length)return '<p class="empty-inline">当前筛选仅包含流程决策，切换时间顺序可查看全部记录。</p>';
  const links=graph.links,parents=id=>links.filter(e=>e.to===id).map(e=>e.from);
  const ids=new Set(items.map(x=>x.tasks.id)),levels=new Map(),pending=new Map(items.map(x=>[x.tasks.id,x]));
  while(pending.size){let moved=false;for(const [id,item] of pending){const deps=parents(item.tasks.id).filter(x=>ids.has(x));if(deps.every(x=>levels.has(x))){levels.set(id,deps.length?1+Math.max(...deps.map(x=>levels.get(x))):0);pending.delete(id);moved=true;}}if(!moved){for(const id of pending.keys())levels.set(id,0);break;}}
  const columns=[],positions=new Map(),cardWidth=224,cardHeight=250,gap=28;
  for(const item of items)(columns[levels.get(item.tasks.id)]??=[]).push(item);
  const height=Math.max(1,...columns.map(c=>c.length))*(cardHeight+gap)+48;
  columns.forEach((column,col)=>column.forEach((item,row)=>positions.set(item.tasks.id,{x:28+col*320,y:40+(height-80-column.length*(cardHeight+gap)+gap)/2+row*(cardHeight+gap)})));
  // Align joins to their actual inputs, keeping stable order and room between cards.
  for(let col=1;col<columns.length;col++){
    const column=columns[col];let bottom=24;
    for(const item of column){const upstream=parents(item.tasks.id).map(id=>positions.get(id)).filter(Boolean),p=positions.get(item.tasks.id);if(upstream.length)p.y=upstream.reduce((sum,p)=>sum+p.y,0)/upstream.length;p.y=Math.max(bottom,p.y);bottom=p.y+cardHeight+gap;}
    let top=height-24-cardHeight;
    for(const item of [...column].reverse()){const p=positions.get(item.tasks.id);p.y=Math.min(top,p.y);top=p.y-cardHeight-gap;}
  }
  const width=columns.length*320-40;
  function edgePath(from,to){
    const a=positions.get(from),b=positions.get(to);let x=a.x+cardWidth,y=a.y+cardHeight/2,path=`M${x} ${y}`;
    const curve=(nx,ny)=>{const bend=(nx-x)/2;path+=` C${x+bend} ${y},${nx-bend} ${ny},${nx} ${ny}`;x=nx;y=ny;};
    // Long edges cross intermediate columns through free gaps, never through cards.
    for(let col=levels.get(from)+1;col<levels.get(to);col++){
      const obstacles=columns[col].map(item=>positions.get(item.tasks.id)),desired=(a.y+b.y+cardHeight)/2;
      const candidates=[desired,12,height-12,...obstacles.flatMap(p=>[p.y-12,p.y+cardHeight+12])];
      const lane=candidates.filter(v=>v>=12&&v<=height-12&&obstacles.every(p=>v<=p.y-8||v>=p.y+cardHeight+8)).sort((a,b)=>Math.abs(a-desired)-Math.abs(b-desired))[0];
      const left=28+col*320;curve(left-18,lane);x=left+cardWidth+18;path+=` L${x} ${lane}`;
    }
    curve(b.x,b.y+cardHeight/2);return path;
  }
  const paths=links.filter(e=>positions.has(e.from)&&positions.has(e.to)).map(e=>{const active=selectedTask===e.from||selectedTask===e.to;return `<path class="${e.kind} ${active?'related':''}" data-edge-kind="${e.kind}" data-edge-from="${esc(e.from)}" data-edge-to="${esc(e.to)}" d="${edgePath(e.from,e.to)}" marker-end="url(#task-arrow-${e.kind})"><title>${esc(e.kind==='recovery'?'这些异常触发了该兜底任务':e.kind==='planning'?'此任务执行时明确安排了后续任务':'真实结果或执行先后依赖')}</title></path>`;}).join('');

  return `<div class="graph-tools"><span>实际任务关系 <span class="muted">· 蓝色依赖 / 紫色安排 / 红色异常来源</span><small class="node-axis-legend">形状图标＝执行者 · 边框标记＝推进方式 · 状态徽标＝运行状态</small></span><div><button data-graph-zoom="out" aria-label="缩小依赖图">−</button><span id="graph-scale"></span><button data-graph-zoom="in" aria-label="放大依赖图">＋</button><button data-graph-zoom="fit">适应画布</button></div></div><div class="dependency-scroll"><div class="process-extent"><div class="process-canvas" style="width:${width}px;height:${height}px"><svg width="${width}" height="${height}" aria-hidden="true"><defs>${['dependency','planning','recovery'].map(kind=>`<marker id="task-arrow-${kind}" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" style="fill:${kind==='recovery'?'#bd705f':kind==='planning'?'#9564cf':'#7293bb'}"/></marker>`).join('')}</defs><g class="dependency-lines">${paths}</g></svg>${items.map(item=>{const p=positions.get(item.tasks.id);return `<div style="position:absolute;left:${p.x}px;top:${p.y}px;width:${cardWidth}px">${taskCard(item)}</div>`;}).join('')}</div></div></div>`;
}
let graphScale=null,graphRun=null;
function sizeTaskGraph(mode){
  const canvas=document.querySelector('.process-canvas'),scroll=canvas?.closest('.dependency-scroll');if(!canvas || !canvas.offsetWidth || !canvas.offsetHeight || scroll.clientWidth<=24 || scroll.clientHeight<=24)return;
  if(graphRun!==run.id){graphScale=null;graphRun=run.id;}
  const fit=Math.min(1,(scroll.clientWidth-24)/canvas.offsetWidth,(scroll.clientHeight-24)/canvas.offsetHeight);
  graphScale=mode==='fit'?fit:mode==='in'?Math.min(1.5,(graphScale||fit)+.15):mode==='out'?Math.max(.2,(graphScale||fit)-.15):graphScale??Math.max(.85,Math.min(1,(scroll.clientWidth-24)/canvas.offsetWidth));
  canvas.style.transform=`scale(${graphScale})`;canvas.parentElement.style.width=canvas.offsetWidth*graphScale+'px';canvas.parentElement.style.height=canvas.offsetHeight*graphScale+'px';
  $('graph-scale').textContent=Math.round(graphScale*100)+'%';
}
window.addEventListener('resize',()=>sizeTaskGraph());
function taskError(attempt){
  if(!attempt?.error)return '';
  const raw=String(attempt.error),legacy=!run.operator_protocol;
  const summary=attempt.failure_kind==='command_start'?'命令启动配置错误':attempt.failure_kind==='agent_command'?'Agent 命令异常':attempt.observation_error?'监控异常，外部工作状态未知':raw.includes('Agent exited without sealing')?'Agent 未成功提交结果就退出了。':raw.includes('Agent exited without calling finish')?'Agent 退出前未释放操作权。':'本次执行未能成功完成。';
  const advice=attempt.failure_kind?`请核对命令、目录及 Agent 信任/登录配置；这不是外部业务失败的证明。工作目录：${attempt.implementation.cwd||'平台进程工作目录'}`:attempt.observation_error?'检查已停止，保留原外部任务，不自动重提。':'查看原始错误，核对本次执行和工具回执。';
  const route=run.tasks[attempt.task_id]?.origin.fallback?'<p class="small muted">兜底 Agent 本次未完成；按现有恢复规则处理，连续失败三次后暂停并通知。</p>':'<div class="fallback-summary">'+fallbackSummary(run,run.settings.fallback_node,run.settings.bindings)+'</div>';
  return `<section class="task-error" role="note"><strong>${esc(summary)}</strong><p>${legacy?'这是旧版本运行保留的失败记录。':esc(advice)}</p><details><summary>原始错误与证据路径</summary><pre>${esc(raw)}</pre></details></section>${!legacy&&attempt.status==='fault'?route:''}`;
}
function resultWithSchema(value,schema={},attempt,port,parts=[]){
  if(schema.format==='file'&&typeof value==='string'&&attempt){const url=`/api/runs/${encodeURIComponent(run.id)}/artifact?execution=${encodeURIComponent(attempt.id)}&output=${encodeURIComponent(port)}&path=${encodeURIComponent(JSON.stringify(parts))}`;return `${/\.(png|jpe?g|gif|webp)$/i.test(value)?`<img class="result-image" src="${esc(url)}" alt="${esc(port)}" loading="lazy">`:''}<a class="button" href="${esc(url)}" target="_blank" rel="noopener">查看文件 · ${esc(value)}</a>`;}
  if(Array.isArray(value)){if(schema.items?.format==='file')return value.map((v,i)=>resultWithSchema(v,schema.items,attempt,port,[...parts,i])).join(' ');return resultView(value);}
  if(value && typeof value==='object')return `<dl class="result-fields">${Object.entries(value).map(([k,v])=>`<div><dt>${esc(schema.properties?.[k]?.title || k)}</dt><dd>${resultWithSchema(v,schema.properties?.[k] || {},attempt,port,[...parts,k])}</dd></div>`).join('')}</dl>`;
  return resultView(value);
}
function taskWaitReasons(task){
  if(['skipped','cancelled'].includes(task.status)||!task.wait_reasons?.length)return '';
  const text=r=>r.reason==='order_dependency'?`等待前置任务 ${(run.tasks[r.action]?taskLabel(run.tasks[r.action]):r.action)} 完成`:r.reason==='missing_record'?`输入 ${r.input} 等待结果 ${r.record}`:r.reason==='missing_implementation'?'尚未选用可执行的实现；请由运行 Agent 选择已有方案；补充 Loop 实现使用构建 Agent':r.reason==='invalid_parameters'?'参数不满足所选实现的要求；由运行 Agent 核对任务参数，完整契约可在节点详情查看':r.reason==='invalid_input'?`输入 ${r.input} 尚不可用`:r.reason==='retry_pending'?'等待同一任务的旧进程确认结束，再重试原任务':r.detail||r.reason;
  return `<div class="wait-reasons"><strong>当前等待原因</strong><ul>${task.wait_reasons.map(r=>`<li>${esc(text(r))}</li>`).join('')}</ul><details><summary>查看详细条件</summary>${resultView(task.wait_reasons)}</details></div>`;
}
function taskFlowHTML(item){
  const id=item.tasks.id,edges=TaskHistory.links(run),incoming=edges.filter(e=>e.to===id),outgoing=edges.filter(e=>e.from===id);
  const link=(e,target)=>`<li class="${e.kind}"><small>${e.kind==='recovery'?'异常来源':e.kind==='planning'?'明确安排':'执行依赖'}</small><button class="text-button" data-task-focus="${esc(target)}">${esc(taskLabel(run.tasks[target]))}</button>${badge(run.tasks[target].status)}</li>`;
  return `<section class="task-flow"><h3>任务关系与推进</h3>${incoming.length?`<h4>来源</h4><ul>${incoming.map(e=>link(e,e.from)).join('')}</ul>`:''}${outgoing.length?`<h4>后续与异常处理</h4><ul>${outgoing.map(e=>link(e,e.to)).join('')}</ul>`:''}${!incoming.length&&!outgoing.length?'<p class="small muted">暂无已记录的关联任务。</p>':''}${item.tasks.origin?.route_id?`<p class="small muted">事件触发：${esc(item.tasks.origin.route_id)} → ${item.tasks.origin.flow_agent?'内置流程 Agent':'模板 '+esc(item.tasks.origin.plan)} · 报告 ${esc(item.tasks.origin.report_id)}</p>`:''}${taskWaitReasons(item.tasks)}${item.tasks.origin?.fallback?`<details><summary>触发兜底时记录的问题</summary>${resultView(item.tasks.origin.issues||[])}</details>`:''}</section>`;
}
function taskRevisionText(value){return value==null?'修订未记录':'修订 '+value;}
function manualFlowHint(task,attempt){
  if(run.status!=='running'||run.identity_read_only||!task.origin?.flow_agent||attempt?.status!=='decision'||attempt.implementation.command?.length||attempt.implementation.dispatch||attempt.worker_active)return '';
  if((run.agent_sessions||[]).some(owner=>owner.execution_id===attempt.id||owner.resume_execution===attempt.id))return '';
  return `<div class="loop-notice"><strong>流程决策等待 Agent 接手</strong><p>此流程 Agent 尚未配置自动执行命令或具名委派。可以交给当前 Agent 处理这次决策，也可以请构建 Agent 补充后续运行的执行配置。</p><button data-flow-handoff="${esc(task.id)}">查看任务定位</button></div>`;
}
function taskDetails(item){
  if(!item)return '<p class="empty-inline">选择任务，查看结果或调整后续工作。</p>';
  const t=item.tasks,node=run.loop_definition.nodes[t.spec.node],attempt=item.attempts.find(e=>e.id===selectedAttempt)||item.attempts.at(-1),editable=!t.execution_id&&['planned','blocked','ready','held'].includes(t.status),ended=!run.operator_protocol||['completed','terminated'].includes(run.status);
  const edits=run.history.filter(h=>h.detail?.tasks===t.id&&(h.detail.before||h.kind==='planned'));
  return `<div class="task-detail-heading"><h2>${esc(taskLabel(t))}</h2>${badge(t.status)}</div><p class="task-detail-id">${esc(t.id)} · <span data-task-revision>${esc(taskRevisionText(t.revision))}</span></p><p class="small muted">所属任务：${t.parent_id?`<button class="text-button" data-task-focus="${esc(t.parent_id)}">${esc(taskLabel(run.tasks[t.parent_id]))}</button>`:'顶层安排'}</p><details class="task-instructions"><summary>任务说明</summary><p class="small muted">${esc(node.instructions)}</p></details><div class="toolbar"><button data-task-assistance="${esc(t.id)}">查看外援请求</button>${editable&&!ended?`<button data-task-cancel="${esc(t.id)}">取消任务</button>`:''}${(['fault','stale','cancelled','waiting_user','retrying'].includes(t.status)||attempt?.observation_error)&&!ended?`<button data-task-retry="${esc(t.id)}">${attempt?.observation_error?'恢复监控':'重试任务'}</button>`:''}</div>
  ${attempt?.status==='waiting'&&['timer','event','loop'].includes(attempt.implementation.kind)&&!ended?`<button data-task-cancel="${esc(t.id)}">取消等待</button>`:''}${t.assistance_wait?'<p class="small muted">正在等待外援回复；等待结束后继续当前任务。</p>':''}${attempt?.communication_state?`<p class="small muted">群组执行：${esc(communicationStates[attempt.communication_state]||attempt.communication_state)}</p>`:''}${flowDecisionDetails(t)}${manualFlowHint(t,attempt)}${taskFlowHTML(item)}<section class="task-execution"><h3>执行记录 · ${item.attempts.length} 次</h3><p class="small muted">重试记录在同一任务下；每次保留当时的参数、实现和状态变化。</p>${item.attempts.length?`<label>执行尝试<select id="task-attempt">${item.attempts.map(e=>`<option value="${esc(e.id)}" ${e.id===attempt?.id?'selected':''}>第 ${e.attempt} 次 · ${esc(taskRevisionText(e.task_revision))} · ${esc(labels[e.status]||e.status)} · ${taskTime(TaskHistory.startTime(e))}${Object.hasOwn(e,'started_at')?'':' · 历史派发时间'}</option>`).join('')}</select></label>`:''}${attempt?.implementation.kind==='agent'&&(attempt.implementation.command||attempt.communication_id)?`<button data-open-terminal="${esc(attempt.id)}">${attempt.implementation.terminal?'打开交互终端':'查看实时输出'}</button>`:''}${attempt?.implementation.kind==='agent'&&!ended?`<button data-agent-session="${esc(attempt.id)}">${attempt.worker_active?'打开会话':'恢复会话'}</button>`:''}${promptHistory(attempt)}${taskError(attempt)}<h3>结果</h3>${Object.entries(attempt?.outputs || {}).map(([port,v])=>`<section class="result-section"><h4>${esc(run.loop_definition.records[node.outputs[port]?.record_type]?.title || port)}</h4>${resultWithSchema(v,run.loop_definition.records[node.outputs[port]?.record_type] || {},attempt,port)}</section>`).join('') || (t.status==='skipped'?'<p class="muted">历史任务已跳过，没有提交结果。</p>':'<p class="muted">尚未提交结果</p>')}
  ${waitDetails(attempt)}${executionLifecycle(attempt)}<h3>输入与来源</h3>${Object.entries(attempt?.inputs || {}).map(([port,value])=>`<section><h4>${esc(node.inputs[port]?.title || port)}</h4>${resultView(value)}${sourceLinks(attempt.sources?.[port])}</section>`).join('') || resultView(t.spec.inputs)}
  <h3>当前前置任务</h3>${item.dependencies.map(id=>`<button class="text-button" data-task-focus="${esc(id)}">${esc(taskLabel(run.tasks[id]))}</button>`).join(' ')||'<span class="muted">无</span>'}
  <h3>${attempt?'所选执行的参数与实现':'当前任务的参数与实现'}</h3>${resultView(attempt?attempt.parameters||{}:t.spec.parameters||{})}<p>${esc(attempt?(attempt.implementation_id||'历史实现标识未记录'):(t.spec.implementation||'沿用运行默认实现'))}</p>
  ${attempt?.task_spec?`<details><summary>本次执行采用的任务安排 · ${esc(taskRevisionText(attempt.task_revision))}</summary>${resultView(attempt.task_spec)}</details>`:''}${attempt&&attempt.task_revision!==t.revision?`<details><summary>当前任务安排 · ${esc(taskRevisionText(t.revision))}</summary>${resultView(t.spec)}</details>`:''}
  </section><h3>安排与修改</h3>${edits.map(h=>`<details><summary>${esc(taskTime(h.at))} · ${esc(h.message)} · ${h.detail.before?esc(taskRevisionText(h.detail.before_revision))+' → ':''}${esc(taskRevisionText(h.detail.after_revision))}</summary>${h.detail.actor?`<p class="small muted">操作者：${esc(({user:'用户',interactive:'持权操作者',background:'后台 Agent',engine:'Engine'})[h.detail.actor.kind]||h.detail.actor.kind)}${h.detail.actor.execution_id?' · '+esc(h.detail.actor.execution_id):''}</p>`:''}${h.detail.before?`<p>修改前</p>${resultView(h.detail.before)}`:''}<p>修改后</p>${resultView(h.detail.after)}</details>`).join('')||'<p class="muted">没有额外修改记录</p>'}
  <details><summary>原始记录</summary><pre>${esc(pretty({task:t,execution:attempt}))}</pre></details>`;
}
function sourceLinks(source){return (Array.isArray(source)?source:[source]).filter(Boolean).map(s=>{const e=run.executions.find(e=>e.id===s.execution);return e?`<button class="text-button" data-source-execution="${esc(e.id)}">来自 ${esc(taskLabel(run.tasks[e.task_id]))} · v${esc(s.revision)}</button>`:`<small>${esc(s.run_input?'初始输入 '+s.run_input:s.settings?'设置 '+s.settings:'直接输入')}</small>`;}).join(' ');}
function renderTaskHistory(){
  requestAnimationFrame(()=>sizeTaskGraph());
  taskChanges=new Map(run.history.filter(h=>h.detail?.before&&h.detail?.tasks).map(h=>[h.detail.tasks,h]));
  const all=TaskHistory.rows(run),business=all.filter(i=>!i.tasks.origin?.flow_agent);taskNumbers=new Map((taskOrder==='graph'?business:all).map((item,index)=>[item.tasks.id,index+1]));if(!all.some(i=>i.tasks.id===selectedTask)){selectedTask=all.find(i=>['executing','fault','blocked','ready'].includes(i.tasks.status))?.tasks.id||all[0]?.tasks.id;selectedAttempt=null;}
  const items=all.filter(i=>(!filterNode||i.tasks.spec.node===filterNode)&&(!taskStatus||i.tasks.status===taskStatus)&&(!taskSearch||(taskLabel(i.tasks)+' '+i.tasks.id+' '+(i.round||'')).toLowerCase().includes(taskSearch.toLowerCase())));
  const groups=taskOrder==='round'?TaskHistory.groups(items):[{round:'已开始',items:items.filter(i=>i.started!==null)},{round:'尚未开始',items:items.filter(i=>i.started===null&&!['completed','skipped','cancelled','stale'].includes(i.tasks.status))},{round:'未执行且已结束',items:items.filter(i=>i.started===null&&['completed','skipped','cancelled','stale'].includes(i.tasks.status))}];
  return `<div class="task-heading"><div><h2>任务关系与推进 ${!run.operator_protocol?'<span class="history-label">历史运行 · 只读</span>':''}</h2><p class="muted small">${business.length} 项业务任务${all.length>business.length?' · '+(all.length-business.length)+' 次流程决策':''} · ${business.filter(i=>i.tasks.status==='completed').length} 已完成 · ${business.filter(i=>['fault','stale'].includes(i.tasks.status)).length} 失败 · ${business.filter(i=>i.started===null&&!['completed','skipped','cancelled','stale'].includes(i.tasks.status)).length} 尚未开始${all.some(i=>i.tasks.origin?.flow_agent&&['fault','stale'].includes(i.tasks.status))?' · 流程决策异常 '+all.filter(i=>i.tasks.origin?.flow_agent&&['fault','stale'].includes(i.tasks.status)).length:''}${all.some(i=>i.tasks.status==='skipped')?' · '+all.filter(i=>i.tasks.status==='skipped').length+' 已跳过':''}</p></div><div class="toolbar"></div></div><div class="process-controls"><div class="segmented">${[['graph','任务关系'],['time','时间顺序'],['round','按轮次']].map(([id,label])=>`<button data-task-order="${id}" class="${taskOrder===id?'selected':''}">${label}</button>`).join('')}</div><label class="task-search-label"><span class="sr-only">查找任务</span><input id="task-search" placeholder="查找任务…" type="search" value="${esc(taskSearch)}"></label><label class="task-status-label"><span class="sr-only">任务状态</span><select id="task-status"><option value="">全部状态</option>${[...new Set(all.map(i=>i.tasks.status))].map(s=>`<option value="${esc(s)}" ${taskStatus===s?'selected':''}>${esc(labels[s]||s)}</option>`).join('')}</select></label>${filterNode?'<button id="clear-task-filter">清除节点筛选</button>':''}</div>
  <div class="process-layout"><section class="process-body">${items.length?(taskOrder==='graph'?taskDependencyGraph(items):groups.map(g=>`<details class="task-group" open><summary>${esc(g.round || '未标注轮次')} · ${g.items.length}</summary><div class="process-list">${g.items.map(taskCard).join('')}</div></details>`).join('')):'<p class="empty-inline">没有符合条件的任务</p>'}</section><aside id="task-detail" class="task-detail">${taskDetails(all.find(i=>i.tasks.id===selectedTask))}</aside></div>${run.history.filter(h=>h.kind==='plan_built'&&h.detail?.omitted?.length).map(h=>`<details class="omitted-steps"><summary>未安排的步骤 · ${esc(h.detail.name)} · ${esc(taskTime(h.at))}</summary>${omittedStepsHTML(h.detail.omitted,h.detail.name)}</details>`).join('')}${run.history.filter(h=>h.kind==='route_fired').map(h=>`<details class="omitted-steps"><summary>事件触发 · ${esc(h.detail.route_id)} → ${esc(h.detail.flow_agent?'内置流程 Agent':h.detail.plan)} · ${h.detail.batches.reduce((n,b)=>n+b.task_ids.length,0)} 项任务</summary><p>来源：<button class="text-button" data-task-focus="${esc(h.detail.task_id)}">${esc(taskLabel(run.tasks[h.detail.task_id]))}</button> · ${esc(h.detail.event)}</p>${resultView(h.detail)}</details>`).join('')}${loopProgressHTML(run)}`;
}
const editDialog=document.createElement('dialog');editDialog.id='task-edit-dialog';editDialog.innerHTML='<div class="dialog-heading"><h2 id="task-edit-title"></h2><button class="close-dialog" aria-label="关闭">×</button></div><div id="task-edit-error" role="alert"></div><form id="task-edit-form"><div id="task-edit-fields"></div><div id="task-edit-review" hidden></div><div class="dialog-tasks"><button type="button" id="task-edit-back" hidden>返回修改</button><button type="button" class="close-dialog">取消</button><button type="submit" class="primary" id="task-edit-submit">预览修改</button></div></form>';document.body.append(editDialog);
function openTaskEdit(kind,id=null){
  if(!['cancel','retry'].includes(kind))return;
  if(!run.operator_protocol||['completed','terminated'].includes(run.status)){toast('这次运行仅供查看');return;}
  const monitorRetry=kind==='retry'&&run.executions.some(e=>e.id===run.tasks[id]?.execution_id&&e.observation_error);
  taskEdit={monitorRetry,kind,id,runId:run.id,revision:run.revision,key:randomKey(),changes:null};$('task-edit-error').textContent=(run.agent_sessions||[]).length?'Agent 正在处理工作；提交时检查版本，同一任务仍受重复执行保护。':'';
  $('task-edit-title').textContent=kind==='add'?'添加后续任务':kind==='batch'?'按模板安排工作':kind==='cancel'?'取消任务':kind==='retry'?(monitorRetry?'恢复监控':'重试任务'):'编辑后续工作';
  $('task-edit-fields').hidden=false;$('task-edit-review').hidden=true;$('task-edit-back').hidden=true;$('task-edit-submit').textContent='预览修改';
  $('task-edit-fields').innerHTML=`<p>${esc(taskLabel(run.tasks[id]))}</p><p>${kind==='retry'?(monitorRetry?'继续查询原来的外部任务，不会再次提交工作。':'按当前任务的实现和参数重试。'):'取消此任务，已发生的外部操作不会撤销。'}</p><label>原因<input id="task-edit-reason" required></label>`;
  editDialog.showModal();
}
function omittedStepsHTML(items,planName){return items.length?`<section class="omitted-summary"><h3>未安排 · 不创建任务</h3>${items.map(item=>`<p><strong>${esc(run.loop_definition.nodes[run.loop_definition.plans[item.plan||planName]?.steps[item.step]?.node]?.label||item.step)}</strong> · ${esc(({not_selected:'本次未选择',condition_false:'安排条件不满足',empty_items:'展开列表为空'})[item.reason]||item.reason)}</p>${item.when?`<details><summary>安排条件</summary><pre>${esc(pretty(item.when))}</pre></details>`:''}`).join('')}</section>`:'';}
function collectTaskEdit(){return [{tool:'change_task',arguments:{task_id:taskEdit.id,operation:taskEdit.kind,reason:$('task-edit-reason').value}}];}
document.addEventListener('click',event=>safely(async()=>{
  const el=event.target.closest('button');if(!el)return;const d=el.dataset;
  if(d.taskFocus||d.sourceExecution){selectedTask=d.taskFocus||run.executions.find(e=>e.id===d.sourceExecution)?.task_id;selectedAttempt=d.sourceExecution||null;const scroll=document.querySelector('.dependency-scroll'),position=scroll?{left:scroll.scrollLeft,top:scroll.scrollTop}:null;inspectSignature='';renderInspect();requestAnimationFrame(()=>{if(position)document.querySelector('.dependency-scroll')?.scrollTo(position);});}
  else if(d.graphZoom)sizeTaskGraph(d.graphZoom);
  else if(d.taskOrder){taskOrder=d.taskOrder;inspectSignature='';renderInspect();}
  else if(d.taskCancel)openTaskEdit('cancel',d.taskCancel);
  else if(d.taskRetry)openTaskEdit('retry',d.taskRetry);
  else if(el.id==='clear-task-filter'){filterNode=null;inspectSignature='';renderInspect();}
  else if(el.id==='task-edit-back'){taskEdit.changes=null;$('task-edit-fields').hidden=false;$('task-edit-review').hidden=true;$('task-edit-back').hidden=true;$('task-edit-submit').textContent='预览修改';}
}));
document.addEventListener('change',event=>{const el=event.target;
  if(el.id==='task-status'||el.id==='task-search'){taskStatus=$('task-status').value;taskSearch=$('task-search').value;inspectSignature='';renderInspect();}
  if(el.id==='task-attempt'){selectedAttempt=el.value;$('task-detail').innerHTML=taskDetails(TaskHistory.rows(run).find(i=>i.tasks.id===selectedTask));}
});
document.addEventListener('submit',event=>{
  if(event.target.id!=='task-edit-form')return;event.preventDefault();
  (async()=>{try{
    $('task-edit-error').textContent='';
    if(!taskEdit.changes){
      taskEdit.changes=collectTaskEdit();const preview=await api(`runs/${taskEdit.runId}/tasks`,{revision:taskEdit.revision,changes:taskEdit.changes,preview:true});const before=taskEdit.id?structuredClone(run.tasks[taskEdit.id].spec):null;
      const affected=new Set(taskEdit.id?[taskEdit.id]:[]),deps=run.task_dependencies||{};let size;do{size=affected.size;for(const [id,sources] of Object.entries(deps))if(sources.some(s=>affected.has(s)))affected.add(id);}while(size!==affected.size);
      $('task-edit-review').innerHTML=`${before?`<h3>原安排</h3>${resultView(before)}`:''}<h3>本次修改</h3>${preview.changes.map(c=>`<section class="result-section"><h4>${esc(run.loop_definition.nodes[c.after.spec.node].label||c.after.spec.node)} · ${c.before?'修改':'新增'} · ${esc(taskRevisionText(c.after.revision))}</h4>${resultView({parent_id:c.after.parent_id,...c.after.spec})}</section>`).join('') || (taskEdit.monitorRetry?'<p>恢复原外部任务的状态检查，不再次提交工作。</p>':preview.omitted?.length?'<p>本次不会创建任务。</p>':'<p>没有新的变化</p>')}${omittedStepsHTML(preview.omitted||[])}<h3>依赖关系关联的后续任务</h3><p>${[...affected].filter(id=>id!==taskEdit.id).map(id=>esc(taskLabel(run.tasks[id]))).join('、')||'无已知后续任务'}</p><p class="muted">只展示结构关联；已有结果是否失效由你决定。</p>`;
      $('task-edit-fields').hidden=true;$('task-edit-review').hidden=false;$('task-edit-back').hidden=false;$('task-edit-submit').textContent='应用修改';
    }else{
      await api(`runs/${taskEdit.runId}/tasks`,{revision:taskEdit.revision,changes:taskEdit.changes});editDialog.close();await refresh();toast('安排已更新');
    }
  }catch(e){$('task-edit-error').textContent=e.message;if(taskEdit?.changes){taskEdit.changes=null;$('task-edit-fields').hidden=false;$('task-edit-review').hidden=true;$('task-edit-back').hidden=true;$('task-edit-submit').textContent='重新核对并预览';const latest=await api('runs/'+taskEdit.runId);taskEdit.revision=latest.revision;if(run?.id===latest.id){run=latest;inspectSignature='';renderRun();}}}})();
});
