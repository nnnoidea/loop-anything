'use strict';
// Definition relationships, not runtime Task dependencies or inferred business routes.
function loop_definitionEdges(bp){
  if(bp.schema_version!==2)return [...(bp.transitions || [])];
  return Object.entries(bp.plans || {}).flatMap(([name,plan])=>Object.entries(plan.steps).flatMap(([key,step])=>[
    ...(step.after || []).filter(k=>plan.steps[k]).map(k=>({id:name,from:plan.steps[k].node,to:step.node})),
    ...Object.entries(step.inputs || {}).flatMap(([port,source])=>{
      if(source.from && plan.steps[source.from])return [{id:name,from:plan.steps[source.from].node,to:step.node,output:source.port,input:port}];
      const seedPort=Object.entries(bp.seed?.outputs || {}).find(([,d])=>d.id===source.record)?.[0];
      return seedPort?[{id:name,from:bp.entry,to:step.node,output:seedPort,input:port}]:[];
    })
  ]));
}
function loopRelationships(bp,fallback=bp.fallback_node){
  const edges=[];
  function add(from,to,kind,detail){
    if(!Object.hasOwn(bp.nodes,from)||!Object.hasOwn(bp.nodes,to))return;
    let edge=edges.find(e=>e.from===from&&e.to===to&&e.kind===kind);
    if(!edge){edge={from,to,kind,details:[]};edges.push(edge);}
    if(!edge.details.includes(detail))edge.details.push(detail);
  }
  for(const e of loop_definitionEdges(bp))add(e.from,e.to,'dependency',e.output?`${e.id} · ${e.output} → ${e.input}`:`${e.id || '规则'} · 先后依赖`);
  for(const [id,n] of Object.entries(bp.nodes))for(const target of n.plan_nodes || [])add(id,target,'planning','作者声明可安排；实际是否创建由执行时决定');
  const reaches=(from,to,skip,seen=new Set())=>from===to||(!seen.has(from)&&(seen.add(from),edges.some(e=>e!==skip&&e.from===from&&reaches(e.to,to,skip,seen))));
  for(const e of edges)e.repeats=e.kind==='planning'&&reaches(e.to,e.from,e);
  if(typeof fallback==='string'&&Object.hasOwn(bp.nodes,fallback))for(const id of Object.keys(bp.nodes))if(id!==fallback)add(id,fallback,'recovery','失败或未覆盖情况仍未解决时，按操作权与运行限制进入已配置兜底；正常等待不触发');
  return edges;
}
function mapImplementationLabel(item,id,bindings){
  const chosen=Object.hasOwn(bindings,id)?bindings[id]:defaultImplementation(item.implementations[id]);
  const config=implementationOptions(item.implementations[id])[chosen];
  return config?`${config.label || chosen} · ${kindNames[config.kind] || config.kind}`:'尚未选用实现';
}
function mapImplementations(item,id,bindings,action){
  const entry=item.implementations[id],options=implementationOptions(entry),defaultId=defaultImplementation(entry);
  const inherited=!Object.hasOwn(bindings,id),selected=inherited?defaultId:bindings[id];
  const button=(value,text)=>action==='prepare'?`<button type="button" data-map-choice="${esc(id)}" data-choice="${esc(value)}">${text}</button>`:action==='detail'&&item.key?`<button type="button" data-prepare-choice="${esc(id)}" data-choice="${esc(value)}" data-loop-key="${esc(item.key)}">用此实现准备运行</button>`:'';
  return `<section class="map-implementations"><h4>已有实现 · ${Object.keys(options).length}</h4><p class="small muted">${action==='prepare'?'选择仅用于本次运行，自动保存。':action==='run'?'这里是 Run 默认选择；已派发任务保留执行时的实现。':'这里展示 Loop 默认值；选择候选将进入本次运行准备。'}</p>${Object.entries(options).sort(([a],[b])=>Number(b===selected)-Number(a===selected)).map(([key,b])=>`<article class="map-candidate ${key===selected?'chosen':''}" data-candidate="${esc(key)}"><div class="candidate-heading"><strong>${esc(b.label || key)}</strong>${key===selected?'<span class="badge completed">当前选用</span>':''}</div><p>${esc(executionLabel(b))}</p>${b.description?`<p>${esc(b.description)}</p>`:''}<small>${esc(key)}${key===defaultId?' · Loop 默认':''}</small><details class="candidate-execution" ${key===selected?'open':''}><summary>查看阶段与转移</summary>${lifecycleMatrix(b)}</details><details><summary>查看命令与配置</summary><pre>${esc(pretty(b.kind==='agent'&&typeof promptDefaults!=='undefined'?{...b,prompt:b.prompt??promptDefaults.task}:b))}</pre></details>${button(JSON.stringify(key),key===selected?'保持此实现':'选用此实现')}</article>`).join('')||'<p class="muted">作者尚未提供实现。可在 Loop 定义中添加。</p>'}${action==='prepare'?`<div class="candidate-options">${button('',inherited?'✓ 沿用 Loop 默认':'恢复 Loop 默认')}${button('null',!inherited&&selected===null?'✓ 暂不选用':'暂不选用')}</div>`:''}${docView('节点 Skill（候选共用）',item.loop_definition.nodes[id].skills?.length?item.loop_definition.nodes[id].skills:null)}</section>`;
}
function loopNodePositions(bp){
  const ids=Object.keys(bp.nodes),edges=loopRelationships(bp).filter(e=>e.kind!=='recovery'),ordered=[],remaining=new Set(ids);
  while(remaining.size){
    const ready=[...remaining].filter(id=>!edges.some(e=>e.kind==='dependency'&&e.to===id&&e.from!==id&&remaining.has(e.from)));
    const priority=id=>(edges.some(e=>e.from===ordered.at(-1)&&e.to===id)?100:0)+edges.filter(e=>e.from===id&&remaining.has(e.to)).length;
    ready.sort((a,b)=>priority(b)-priority(a));
    const id=remaining.has(bp.entry)?bp.entry:ready[0]||[...remaining][0];
    ordered.push(id);remaining.delete(id);
  }
  const positions=new Map(),columns=Math.min(3,ids.length);
  const occupied=Object.values(bp.layout||{}).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));
  ordered.forEach((id,i)=>{
    const saved=bp.layout?.[id];if(saved&&Number.isFinite(saved.x)&&Number.isFinite(saved.y)){positions.set(id,{x:saved.x,y:saved.y});return;}
    let p;do{const row=Math.floor(i/columns),col=row%2?columns-1-i%columns:i%columns;p={x:60+col*250,y:85+row*210};i++;}while(occupied.some(o=>Math.abs(o.x-p.x)<210&&Math.abs(o.y-p.y)<180));
    positions.set(id,p);occupied.push(p);
  });
  return positions;
}
function loopEdgePath(e,a,b,i=0){
  let d,lx,ly;
    if(e.kind==='recovery'){const ay=a.y+(a.height||126),by=b.y+(b.height||126),lane=Math.max(ay,by)+39+(i%3)*10;d=`M ${a.x+160} ${ay} C ${a.x+160} ${lane},${b.x+160} ${lane},${b.x+160} ${by}`;lx=(a.x+b.x)/2+160;ly=lane-8;}
    else if(e.from===e.to){d=`M ${a.x+40} ${a.y} C ${a.x+10} ${a.y-65},${a.x+185} ${a.y-65},${a.x+160} ${a.y}`;lx=a.x+100;ly=a.y-40;}
    else if(e.repeats){const lane=18+(i%3)*12;d=`M ${a.x} ${a.y+45} L ${lane} ${a.y+45} L ${lane} ${lane} L ${b.x+100} ${lane} L ${b.x+100} ${b.y}`;}
    else if(Math.abs(a.y-b.y)>160){const lane=24+(i%3)*12;d=`M ${a.x} ${a.y+45} C ${lane} ${a.y+45},${lane} ${b.y+45},${b.x} ${b.y+45}`;}
    else if(a.y===b.y){const forward=b.x>a.x,sx=forward?a.x+200:a.x,tx=forward?b.x:b.x+200;d=`M ${sx} ${a.y+45} C ${(sx+tx)/2} ${a.y+45},${(sx+tx)/2} ${b.y+45},${tx} ${b.y+45}`;}
    else {const down=b.y>a.y,sy=down?a.y+90:a.y,ty=down?b.y:b.y+90,mid=(sy+ty)/2+(e.kind==='planning'?12:0);d=`M ${a.x+100} ${sy} C ${a.x+100} ${mid},${b.x+100} ${mid},${b.x+100} ${ty}`;}
  return {d,lx,ly};
}
function effectiveFallback(item,override){
  if(override!==undefined)return override;
  return item.settings&&Object.hasOwn(item.settings,'fallback_node')?item.settings.fallback_node:item.loop_definition.fallback_node;
}
function relationshipText(edge){
  if(edge.kind==='recovery')return ['异常仍未解决','兜底任务待执行','需启用兜底、实现就绪，并等待操作范围可用'];
  if(edge.kind==='planning')return ['按授权安排后续工作','新增任务 → 等待输入','表示可以安排，不会仅因上游完成而自动创建'];
  return ['前置完成 / 所需结果已提交','已有下游任务 → 输入齐备后就绪','下游必须已安排，且全部输入、暂停点及执行条件满足'];
}
function nodeInputRows(bp,id){
  const node=bp.nodes[id],contexts=id===bp.entry?[{step:bp.seed,plan:null,key:null}]:Object.entries(bp.plans||{}).flatMap(([plan,p])=>Object.entries(p.steps||{}).filter(([,s])=>s.node===id).map(([key,step])=>({plan,key,step})));
  return contexts.flatMap(c=>Object.keys(node.inputs||{}).map(port=>{
    const source=c.step?.inputs?.[port],keys=source&&typeof source==='object'?Object.keys(source).filter(k=>['from','record','records','run','settings','literal','$'].includes(k)):[];
    let missing=keys.length!==1,text=missing?'尚未指定来源':sourceText(source);
    if(source&&Object.hasOwn(source,'from')){const upstream=bp.plans[c.plan]?.steps?.[source.from],n=bp.nodes[upstream?.node];missing=!n||!Object.hasOwn(n.outputs||{},source.port);text=missing?'上游步骤或输出已不存在':`${n.label||upstream.node} / ${source.port}${source.collect?'（汇总）':''}`;}
    return {...c,port,missing,text};
  }));
}
function nodeInputsHTML(bp,id,editable=false){
  const rows=nodeInputRows(bp,id);if(!Object.keys(bp.nodes[id].inputs||{}).length)return '';
  return `<section class="node-input-sources"><h4>输入从哪里来</h4>${rows.length?rows.map(row=>`<div class="input-source ${row.missing?'input-gap':''}"><strong>${esc(row.port)}</strong><span>${esc(row.text)}</span><small>${esc(row.plan?row.plan+' / '+row.key:'入口输入')}</small>${editable?`<button type="button" data-input-location="${esc(JSON.stringify(row.plan?['plans',row.plan,'steps',row.key,'inputs',row.port]:['nodes',id,'inputs',row.port]))}">定位输入</button>`:''}</div>`).join(''):'<p class="small muted">尚未加入构建模板；创建具体任务时需提供这些输入。</p>'}</section>`;
}
function nodeFlowHTML(bp,id,edges,editable=false){
  const related=edges.filter(e=>e.from===id||e.to===id),label=n=>bp.nodes[n]?.label||n;
  return `<section class="node-flow"><h4>任务关系与推进</h4>${related.length?related.map(e=>{const [from,to,condition]=relationshipText(e);return `<div class="flow-relation ${e.kind}" data-related-from="${esc(e.from)}" data-related-to="${esc(e.to)}" data-related-kind="${esc(e.kind)}"><strong>${esc(label(e.from))} → ${esc(label(e.to))}</strong><span>${esc(from)} → ${esc(to)}</span><small>${esc(condition)}</small><small>${esc(e.details.join('；'))}</small></div>`;}).join(''):'<p class="small muted">未声明固定关联；具体工作按运行中明确安排的任务推进。</p>'}${nodeInputsHTML(bp,id,editable)}</section>`;
}
function loopProgressHTML(item,fallbackOverride,bindings=item.settings?.bindings||{}){
  const bp=item.loop_definition,fallback=effectiveFallback(item,fallbackOverride),configured=typeof fallback==='string'&&Object.hasOwn(bp.nodes,fallback),edges=loopRelationships(bp,fallback),label=id=>bp.nodes[id]?.label||id;
  const failures=Math.max(item.agent_failures||0,...Object.values(item.tasks||{}).map(t=>t.agent_failures||0));
  const notice=(item.notifications||[]).filter(n=>n.id.startsWith('agent-failure')).at(-1),noticeLabel={pending:'待发送',sending:'发送中',delivered:'已送达',fault:'发送失败'};
  const sender=item.settings?.notification_command?.length||item.implementations?.$notifications?.command?.length;
  return `<details class="loop-progress"><summary>推进条件与异常处理</summary><div class="flow-track normal"><span>任务已安排</span><b>→</b><span>等待输入 / 前置任务</span><b>→</b><span>就绪，等待执行条件</span><b>→</b><span>执行并报告结果</span><b>→</b><span>已有下游任务重新检查就绪条件</span></div><p class="small muted">正常依赖尚未就绪则等待；缺失来源等无法推进的情况会列为异常。暂停点未放行、操作权冲突或并发名额不足时暂不派发。创建下一轮任务仍需 Agent 或脚本明确安排。</p><div class="flow-track recovery"><span>执行内恢复后仍未解决的异常 / 明确转交 Agent</span><b>→</b><span>${configured?'兜底：'+esc(label(fallback)):'异常待处理 · 未启用自动兜底'}</span><b>→</b><span>问题处理后，恢复受影响的工作</span></div>${configured?`<div class="flow-track retry"><span>Agent 退出，异常仍存在</span><b>↻</b><span>按权限与限额再唤醒兜底</span><b>→</b><span>连续失败 3 次仍异常：暂停</span><b>→</b><span>尝试通知用户</span></div><p class="small muted">其他正常支线可继续推进。首次失败计入三次；支线交给兜底后沿用失败链。旧进程未确认停止或存在操作权冲突时等待处理，不并发接管。${item.tasks?` 当前失败计数：${failures}。`:''}</p>`:'<p class="small muted">问题保留在 Timeline，等待用户或已有授权 Agent 处理；不会自动选择其他 Agent。</p>'}<div class="flow-notice"><span>通知出口：${sender?'已配置':'未配置'}</span>${notice?`<strong class="${notice.status==='fault'?'issue':''}">最近失败暂停通知：${esc(noticeLabel[notice.status]||notice.status)}</strong>`:''}</div><details class="loop-transition-table"><summary>任务关系说明 · ${edges.length} 条关系</summary><div class="matrix-scroll"><table><thead><tr><th>来源 → 目标</th><th>触发与目标状态</th><th>条件</th></tr></thead><tbody>${edges.map(e=>{const [from,to,condition]=relationshipText(e);return `<tr><td>${esc(label(e.from))} → ${esc(label(e.to))}</td><td>${esc(from)} → ${esc(to)}</td><td>${esc(condition)}<small>${esc(e.details.join('；'))}</small></td></tr>`;}).join('')||'<tr><td colspan="3">尚未声明节点关系。</td></tr>'}</tbody></table></div></details><p class="small muted">运行结束：Timeline 的完成条件成立，或收到终止信号，由 Engine 进入终态；没有待执行任务本身不代表完成。</p></details>`;
}
function loopGraphHTML(item,{bindings={},focus='',action='detail',fallbackNode}={}){
  const bp=item.loop_definition,fallback=effectiveFallback(item,fallbackNode),edges=loopRelationships(bp,fallback),ids=Object.keys(bp.nodes);
  if(!ids.length)return '<p class="muted">还没有节点。</p>';
  const dependencyReach=(from,to,seen=new Set())=>from===to||(!seen.has(from)&&(seen.add(from),edges.some(e=>e.kind==='dependency'&&e.from===from&&dependencyReach(e.to,to,seen))));
  const redundant=e=>e.kind==='planning'&&edges.some(other=>other!==e&&other.kind==='planning'&&other.from===e.from&&other.to!==e.to&&dependencyReach(other.to,e.to)&&(!dependencyReach(e.to,other.to)||edges.indexOf(other)<edges.indexOf(e)));
  const positions=loopNodePositions(bp),ordered=[...positions.keys()],width=Math.max(400,...[...positions.values()].map(p=>p.x+260)),height=Math.max(320,...[...positions.values()].map(p=>p.y+190));
  const label=id=>bp.nodes[id].label || id;
  const uid='loop-map-'+(++loopGraphHTML.serial);
  const paths=edges.map((e,i)=>{
    const {d,lx,ly}=loopEdgePath(e,positions.get(e.from),positions.get(e.to),i);
    return `<g data-map-edge role="button" tabindex="0" aria-label="${esc(label(e.from)+' → '+label(e.to)+'：查看推进条件')}" data-redundant="${redundant(e)}" data-from="${esc(e.from)}" data-to="${esc(e.to)}" class="map-edge ${e.kind} ${e.repeats?'repeats':''}"><title>${esc(label(e.from)+' → '+label(e.to)+' · '+e.details.join('；'))}</title><path d="${d}" marker-end="url(#${uid}-${e.kind})"/><path class="map-edge-hit" d="${d}"/>${e.from===e.to?`<text x="${lx}" y="${ly}" text-anchor="middle">再次安排</text>`:e.kind==='recovery'?`<text class="edge-caption" x="${lx}" y="${ly}" text-anchor="middle">异常仍未解决</text>`:''}</g>`;
  }).join('');
  const cards=ordered.map(id=>{const p=positions.get(id),n=bp.nodes[id],tasks=Object.values(item.tasks || {}).filter(t=>t.spec.node===id),attempts=(item.executions || []).filter(e=>e.node===id),kind=chosenImplementation(item,id,bindings)?.kind,repeat=edges.some(e=>e.from===id&&e.repeats);
    return `<button type="button" class="map-node" data-map-node="${esc(id)}" ${action==='run'?`data-node="${esc(id)}"`:''} style="left:${p.x}px;top:${p.y}px" aria-pressed="false"><small>${id===fallback?'异常兜底':id===bp.entry?'入口':repeat?'↻ 可再次安排工作':kindNames[kind] || '待接入'}</small><strong>${esc(label(id))}</strong><span class="map-current-implementation" title="${esc(mapImplementationLabel(item,id,bindings))}">${esc(mapImplementationLabel(item,id,bindings))}</span>${action==='run'?`<span>${tasks.length?`${tasks.length} 项任务 · ${attempts.length} 次执行`:'未安排 Task'}</span>`:''}</button>`;
  }).join('');
  const details=ordered.map(id=>`<div data-map-details="${esc(id)}" hidden><div class="map-inspector-heading"><strong>${esc(label(id))}</strong><button type="button" data-map-close aria-label="关闭节点详情">×</button></div><div class="node-view-switch" aria-label="节点详情视图"><button type="button" data-node-view="relations">任务关系</button><button type="button" data-node-view="execution">实现与生命周期</button></div><div data-node-panel="relations">${nodeFlowHTML(bp,id,edges)}</div><div data-node-panel="execution">${mapImplementations(item,id,bindings,action)}</div></div>`).join('');
  return `<section class="loop-map" data-map-focus="${esc(focus)}"><div class="loop-map-heading"><div><strong>任务关系与推进</strong><p class="small muted">先看任务如何衔接；选中节点后查看实现内部的执行过程。</p></div><label class="map-expand"><input type="checkbox" data-map-expand>全部安排连线</label></div><div class="map-legend"><span class="dependency">实线 · 数据 / 先后依赖</span><span class="planning">虚线 · 可安排新任务（按依赖链合并）</span><span class="repeat">↻ 回到已有节点，开启后续工作</span><span class="recovery">红色虚线 · 未解决异常 → 已配置兜底</span></div><div class="map-body"><div class="loop-map-scroll"><div class="loop-map-canvas" style="width:${width}px;height:${height}px"><svg width="${width}" height="${height}"><defs>${['dependency','planning','recovery'].map(k=>`<marker id="${uid}-${k}" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="${k==='recovery'?'#bd705f':k==='planning'?'#9564cf':'#7293bb'}"/></marker>`).join('')}</defs>${paths}</svg>${cards}</div></div><aside class="map-relations"><p data-map-help>点击连线查看推进条件，选中节点查看输入来源和候选实现。循环安排创建新 Task；重试保留同一 Task，在执行记录中查看。</p>${details}</aside></div>${loopProgressHTML(item,fallback,bindings)}</section>`;
}
loopGraphHTML.serial=0;
function focusLoopMap(root,id,view='execution'){
  root.dataset.mapFocus=id;root.classList.toggle('has-selection',!!id);
  const related=new Set([id]);
  root.querySelectorAll('[data-map-edge]').forEach(e=>{const linked=e.dataset.from===id||e.dataset.to===id;e.classList.toggle('dimmed',!!id&&!linked);e.classList.toggle('highlighted',!!id&&linked);if(linked){related.add(e.dataset.from);related.add(e.dataset.to);}});
  root.querySelectorAll('[data-map-node]').forEach(n=>{n.setAttribute('aria-pressed',String(n.dataset.mapNode===id));n.classList.toggle('dimmed',!!id&&!related.has(n.dataset.mapNode));});
  root.querySelectorAll('[data-map-details]').forEach(d=>{d.hidden=d.dataset.mapDetails!==id;if(!d.hidden)selectNodeView(d,view);});
  root.querySelector('.map-relations').scrollTop=0;
  root.querySelector('[data-map-help]').hidden=!!id;
  const selected=[...root.querySelectorAll('[data-map-node]')].find(n=>n.dataset.mapNode===id),scroll=root.querySelector('.loop-map-scroll');
  if(selected&&scroll.clientWidth)scroll.scrollLeft=Math.max(0,selected.offsetLeft+selected.offsetWidth/2-scroll.clientWidth/2);
}
function selectNodeView(detail,view){
  detail.closest('.loop-map').dataset.mapView=view;
  detail.querySelectorAll('[data-node-panel]').forEach(el=>el.hidden=el.dataset.nodePanel!==view);
  detail.querySelectorAll('[data-node-view]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.nodeView===view)));
}
function focusMapRelation(edge){
  const root=edge.closest('.loop-map');focusLoopMap(root,edge.dataset.to,'relations');
  const detail=[...root.querySelectorAll('[data-map-details]:not([hidden]) .flow-relation')].find(el=>el.dataset.relatedFrom===edge.dataset.from&&el.dataset.relatedTo===edge.dataset.to&&edge.classList.contains(el.dataset.relatedKind));
  root.querySelectorAll('.selected-relation').forEach(el=>el.classList.remove('selected-relation'));
  if(detail){detail.classList.add('selected-relation');detail.scrollIntoView({block:'nearest'});}
}
document.addEventListener('keydown',event=>{const edge=event.target.closest('[data-map-edge]');if(edge&&['Enter',' '].includes(event.key)){event.preventDefault();focusMapRelation(edge);}});
document.addEventListener('click',event=>{const view=event.target.closest('[data-node-view]');if(view)selectNodeView(view.closest('[data-map-details]'),view.dataset.nodeView);const edge=event.target.closest('[data-map-edge]');if(edge)focusMapRelation(edge);const node=event.target.closest('[data-map-node]');if(node)focusLoopMap(node.closest('.loop-map'),node.dataset.mapNode);if(event.target.closest('[data-map-close]'))focusLoopMap(event.target.closest('.loop-map'),'');});

document.addEventListener('change',event=>{if(event.target.matches('[data-map-expand]'))event.target.closest('.loop-map').classList.toggle('expanded',event.target.checked);});
