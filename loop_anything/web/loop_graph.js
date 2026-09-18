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
function loopRelationships(bp){
  const edges=[];
  function add(from,to,kind,detail){
    if(!bp.nodes[from]||!bp.nodes[to])return;
    let edge=edges.find(e=>e.from===from&&e.to===to&&e.kind===kind);
    if(!edge){edge={from,to,kind,details:[]};edges.push(edge);}
    if(!edge.details.includes(detail))edge.details.push(detail);
  }
  for(const e of loop_definitionEdges(bp))add(e.from,e.to,'dependency',e.output?`${e.id} · ${e.output} → ${e.input}`:`${e.id || '规则'} · 先后依赖`);
  for(const [id,n] of Object.entries(bp.nodes))for(const target of n.plan_nodes || [])add(id,target,'planning','作者声明可安排；实际是否创建由执行时决定');
  const reaches=(from,to,skip,seen=new Set())=>from===to||(!seen.has(from)&&(seen.add(from),edges.some(e=>e!==skip&&e.from===from&&reaches(e.to,to,skip,seen))));
  for(const e of edges)e.repeats=e.kind==='planning'&&reaches(e.to,e.from,e);
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
  return `<section class="map-implementations"><h4>已有实现 · ${Object.keys(options).length}</h4><p class="small muted">${action==='prepare'?'选择仅用于本次运行，自动保存。':action==='run'?'这里是 Run 默认选择；已派发任务保留执行时的实现。':'这里展示 Loop 默认值；选择候选将进入本次运行准备。'}</p>${Object.entries(options).map(([key,b])=>`<article class="map-candidate ${key===selected?'chosen':''}" data-candidate="${esc(key)}"><div class="candidate-heading"><strong>${esc(b.label || key)}</strong>${key===selected?'<span class="badge completed">当前选用</span>':''}</div><p>${esc(executionLabel(b))}</p>${b.description?`<p>${esc(b.description)}</p>`:''}<small>${esc(key)}${key===defaultId?' · Loop 默认':''}</small><details><summary>查看命令与配置</summary><pre>${esc(pretty(b))}</pre></details>${button(JSON.stringify(key),key===selected?'保持此实现':'选用此实现')}</article>`).join('')||'<p class="muted">作者尚未提供实现。可在 Loop 定义中添加。</p>'}${action==='prepare'?`<div class="candidate-options">${button('',inherited?'✓ 沿用 Loop 默认':'恢复 Loop 默认')}${button('null',!inherited&&selected===null?'✓ 暂不选用':'暂不选用')}</div>`:''}${docView('节点 Skill（候选共用）',item.loop_definition.nodes[id].skills?.length?item.loop_definition.nodes[id].skills:null)}</section>`;
}
function loopNodePositions(bp){
  const ids=Object.keys(bp.nodes),edges=loopRelationships(bp),ordered=[],remaining=new Set(ids);
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
    if(e.from===e.to){d=`M ${a.x+40} ${a.y} C ${a.x+10} ${a.y-65},${a.x+185} ${a.y-65},${a.x+160} ${a.y}`;lx=a.x+100;ly=a.y-40;}
    else if(e.repeats){const lane=18+(i%3)*12;d=`M ${a.x} ${a.y+45} L ${lane} ${a.y+45} L ${lane} ${lane} L ${b.x+100} ${lane} L ${b.x+100} ${b.y}`;}
    else if(Math.abs(a.y-b.y)>160){const lane=24+(i%3)*12;d=`M ${a.x} ${a.y+45} C ${lane} ${a.y+45},${lane} ${b.y+45},${b.x} ${b.y+45}`;}
    else if(a.y===b.y){const forward=b.x>a.x,sx=forward?a.x+200:a.x,tx=forward?b.x:b.x+200;d=`M ${sx} ${a.y+45} C ${(sx+tx)/2} ${a.y+45},${(sx+tx)/2} ${b.y+45},${tx} ${b.y+45}`;}
    else {const down=b.y>a.y,sy=down?a.y+90:a.y,ty=down?b.y:b.y+90,mid=(sy+ty)/2+(e.kind==='planning'?12:0);d=`M ${a.x+100} ${sy} C ${a.x+100} ${mid},${b.x+100} ${mid},${b.x+100} ${ty}`;}
  return {d,lx,ly};
}
function loopGraphHTML(item,{bindings={},focus='',action='detail'}={}){
  const bp=item.loop_definition,edges=loopRelationships(bp),ids=Object.keys(bp.nodes);
  if(!ids.length)return '<p class="muted">还没有节点。</p>';
  const dependencyReach=(from,to,seen=new Set())=>from===to||(!seen.has(from)&&(seen.add(from),edges.some(e=>e.kind==='dependency'&&e.from===from&&dependencyReach(e.to,to,seen))));
  const redundant=e=>e.kind==='planning'&&edges.some(other=>other!==e&&other.kind==='planning'&&other.from===e.from&&other.to!==e.to&&dependencyReach(other.to,e.to)&&(!dependencyReach(e.to,other.to)||edges.indexOf(other)<edges.indexOf(e)));
  const positions=loopNodePositions(bp),ordered=[...positions.keys()],width=Math.max(400,...[...positions.values()].map(p=>p.x+260)),height=Math.max(320,...[...positions.values()].map(p=>p.y+190));
  const label=id=>bp.nodes[id].label || id;
  const uid='loop-map-'+(++loopGraphHTML.serial);
  const paths=edges.map((e,i)=>{
    const {d,lx,ly}=loopEdgePath(e,positions.get(e.from),positions.get(e.to),i);
    return `<g data-map-edge data-redundant="${redundant(e)}" data-from="${esc(e.from)}" data-to="${esc(e.to)}" class="map-edge ${e.kind} ${e.repeats?'repeats':''}"><title>${esc(label(e.from)+' → '+label(e.to)+' · '+e.details.join('；'))}</title><path d="${d}" marker-end="url(#${uid}-${e.kind})"/>${e.from===e.to?`<text x="${lx}" y="${ly}" text-anchor="middle">再次安排</text>`:''}</g>`;
  }).join('');
  const cards=ordered.map(id=>{const p=positions.get(id),n=bp.nodes[id],tasks=Object.values(item.tasks || {}).filter(t=>t.spec.node===id),attempts=(item.executions || []).filter(e=>e.node===id),kind=chosenImplementation(item,id,bindings)?.kind,repeat=edges.some(e=>e.from===id&&e.repeats);
    return `<button type="button" class="map-node" data-map-node="${esc(id)}" ${action==='run'?`data-node="${esc(id)}"`:''} style="left:${p.x}px;top:${p.y}px" aria-pressed="false"><small>${id===bp.entry?'入口':repeat?'↻ 可再次安排工作':kindNames[kind] || '待接入'}</small><strong>${esc(label(id))}</strong><span class="map-current-implementation" title="${esc(mapImplementationLabel(item,id,bindings))}">${esc(mapImplementationLabel(item,id,bindings))}</span>${action==='run'?`<span>${tasks.length?`${tasks.length} 项任务 · ${attempts.length} 次执行`:'未安排 Task'}</span>`:''}</button>`;
  }).join('');
  const details=ordered.map(id=>`<div data-map-details="${esc(id)}" hidden><div class="map-inspector-heading"><strong>${esc(label(id))}</strong><button type="button" data-map-close aria-label="关闭节点详情">×</button></div>${mapImplementations(item,id,bindings,action)}<details class="map-node-relations"><summary>节点关系</summary><ul>${edges.filter(e=>e.from===id||e.to===id).map(e=>`<li><span class="relation-kind ${e.kind}">${e.kind==='planning'?(e.repeats?'循环安排':'可安排'):'依赖'}</span> ${esc(label(e.from))} → ${esc(label(e.to))}<small>${esc(e.details.join('；'))}</small></li>`).join('')||'<li>没有声明固定连接；具体任务仍可在运行时按授权安排。</li>'}</ul>${chosenImplementation(item,id,bindings)?.kind==='agent'?'<p class="small muted">Agent 还可按授权与 Task 范围安排其他已声明节点；图中列出的是作者显式声明的关系。</p>':''}</details></div>`).join('');
  return `<section class="loop-map" data-map-focus="${esc(focus)}"><div class="loop-map-heading"><strong>Loop 节点关系</strong><label class="map-expand"><input type="checkbox" data-map-expand>全部安排连线</label></div><div class="map-legend"><span class="dependency">实线 · 数据 / 先后依赖</span><span class="planning">虚线 · 可安排新任务（按依赖链合并）</span><span class="repeat">↻ 回到已有节点，开启后续工作</span></div><div class="map-body"><div class="loop-map-scroll"><div class="loop-map-canvas" style="width:${width}px;height:${height}px"><svg width="${width}" height="${height}" aria-hidden="true"><defs>${['dependency','planning'].map(k=>`<marker id="${uid}-${k}" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="${k==='planning'?'#9564cf':'#7293bb'}"/></marker>`).join('')}</defs>${paths}</svg>${cards}</div></div><aside class="map-relations"><p data-map-help>选中节点查看完整声明并突出关联线。图中关系不保证每次都执行；每次循环会产生新的 Task，实际运行过程仍按任务展开。</p>${details}</aside></div></section>`;
}
loopGraphHTML.serial=0;
function focusLoopMap(root,id){
  root.dataset.mapFocus=id;root.classList.toggle('has-selection',!!id);
  const related=new Set([id]);
  root.querySelectorAll('[data-map-edge]').forEach(e=>{const linked=e.dataset.from===id||e.dataset.to===id;e.classList.toggle('dimmed',!!id&&!linked);e.classList.toggle('highlighted',!!id&&linked);if(linked){related.add(e.dataset.from);related.add(e.dataset.to);}});
  root.querySelectorAll('[data-map-node]').forEach(n=>{n.setAttribute('aria-pressed',String(n.dataset.mapNode===id));n.classList.toggle('dimmed',!!id&&!related.has(n.dataset.mapNode));});
  root.querySelectorAll('[data-map-details]').forEach(d=>d.hidden=d.dataset.mapDetails!==id);
  root.querySelector('[data-map-help]').hidden=!!id;
  const selected=[...root.querySelectorAll('[data-map-node]')].find(n=>n.dataset.mapNode===id),scroll=root.querySelector('.loop-map-scroll');
  if(selected&&scroll.clientWidth)scroll.scrollLeft=Math.max(0,selected.offsetLeft+selected.offsetWidth/2-scroll.clientWidth/2);
}
document.addEventListener('click',event=>{const node=event.target.closest('[data-map-node]');if(node)focusLoopMap(node.closest('.loop-map'),node.dataset.mapNode);if(event.target.closest('[data-map-close]'))focusLoopMap(event.target.closest('.loop-map'),'');});

document.addEventListener('change',event=>{if(event.target.matches('[data-map-expand]'))event.target.closest('.loop-map').classList.toggle('expanded',event.target.checked);});
