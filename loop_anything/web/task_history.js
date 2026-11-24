'use strict';
(function(root){
  const startTime=e=>e.started_at;
  function rows(run){
    const executions=run.executions || [],byExecution=new Map(executions.map(e=>[e.id,e])),attempts=new Map();
    for(const e of executions){if(!attempts.has(e.task_id))attempts.set(e.task_id,[]);attempts.get(e.task_id).push(e);}
    const tasks=run.tasks || {},producers=new Map();
    for(const w of Object.values(tasks))for(const destination of Object.values(w.spec.outputs || {})){
      const key=destination.id+'@'+((destination.expected_revision || 0)+1);
      if(!['cancelled','stale','skipped'].includes(w.status))producers.set(key,w.id);
    }
    return Object.values(tasks).map((w,index)=>{
      const tries=[...(attempts.get(w.id) || [])].sort((a,b)=>a.created_at-b.created_at);
      const current=byExecution.get(w.execution_id),dependencies=new Set(w.spec.after || []);
      if(current){
        for(const source of Object.values(current.sources || {}))for(const ref of Array.isArray(source)?source:[source]){
          const producer=byExecution.get(ref.execution);if(producer)dependencies.add(producer.task_id);
        }
      }else for(const source of Object.values(w.spec.inputs || {})){
        for(const [index,id] of (source.records || (source.record?[source.record]:[])).entries()){
          const revision=source.revisions?.[index]??source.revision;
          const versions=run.records?.[id] || [],record=revision?versions.find(r=>r.revision===revision):versions.at(-1);
          if(record){const producer=record.tasks || byExecution.get(record.producer)?.task_id;if(producer)dependencies.add(producer);}
          else {const producer=producers.get(id+'@'+(revision || 1));if(producer)dependencies.add(producer);}
        }
      }
      dependencies.delete(w.id);
      return {tasks:w,attempts:tries,started:tries.map(startTime).filter(t=>t!=null).sort((a,b)=>a-b)[0] ?? null,completed:current?.completed_at ?? null,
        round:w.spec.round || null,dependencies:(run.task_dependencies?.[w.id] || [...dependencies]).filter(id=>tasks[id]),index};
    }).sort((a,b)=>(a.started===null)-(b.started===null) || (a.started ?? a.tasks.created_at ?? 0)-(b.started ?? b.tasks.created_at ?? 0) || a.index-b.index);
  }
  function links(run,items=rows(run)){
    const result=[],seen=new Set(),byExecution=new Map((run.executions||[]).map(e=>[e.id,e.task_id]));
    const add=(from,to,kind,arranged=false)=>{
      const key=JSON.stringify([from,to,kind]);
      if(from&&from!==to&&run.tasks[from]&&run.tasks[to]&&!seen.has(key)){
        seen.add(key);result.push({from,to,kind,...(arranged?{arranged:true}:{})});
      }
    };
    for(const item of items){
      const task=item.tasks;
      const creator=byExecution.get(task.origin?.execution||task.origin?.agent);
      for(const id of item.dependencies)add(id,task.id,'dependency',id===creator);
      if(!item.dependencies.includes(creator))add(creator,task.id,'planning');
      if(task.origin?.fallback)for(const issue of task.origin.issues||[])add(issue.task_id,task.id,'recovery');
    }
    return result;
  }
  function groups(items){
    const result=new Map();
    for(const item of items){const key=item.round;if(!result.has(key))result.set(key,[]);result.get(key).push(item);}
    return [...result].map(([round,items])=>({round,items}));
  }
  function businessGraph(run,items=rows(run)){
    const source=id=>run.tasks[id]?.origin?.flow_agent?.task_id;
    const visible=items.filter(i=>!source(i.tasks.id)),ids=new Set(visible.map(i=>i.tasks.id));
    const resolve=id=>{const seen=new Set();while(source(id)&&!seen.has(id)){seen.add(id);id=source(id);}return id;};
    const seen=new Set(),mapped=[];
    for(const edge of links(run,rows(run))){
      const from=resolve(edge.from),to=resolve(edge.to),key=JSON.stringify([from,to,edge.kind]);
      if(from!==to&&ids.has(from)&&ids.has(to)&&!seen.has(key)){seen.add(key);mapped.push({...edge,from,to});}
    }
    return {items:visible,links:mapped};
  }
  function roundMembership(graph,handoffs=new Set()){
    const owners=new Map(),unlabelled=new Map();
    for(const {tasks,round} of graph.items){
      if(round)owners.set(tasks.id,'$round:'+round);
      else if(handoffs.has(tasks.id))owners.set(tasks.id,'$tasks:'+tasks.id);
      else unlabelled.set(tasks.id,[]);
    }
    // Untagged tasks share a group only when recorded dependencies connect them.
    for(const {from,to,kind} of graph.links){
      if(kind!=='dependency'||!unlabelled.has(from)||!unlabelled.has(to))continue;
      unlabelled.get(from).push(to);
      unlabelled.get(to).push(from);
    }
    for(const id of unlabelled.keys()){
      if(owners.has(id))continue;
      const group='$tasks:'+id,queue=[id];
      owners.set(id,group);
      for(const task of queue)for(const peer of unlabelled.get(task)){
        if(owners.has(peer))continue;
        owners.set(peer,group);
        queue.push(peer);
      }
    }
    return owners;
  }
  function roundGraph(graph,expanded,selected,filtered){
    const initial=roundMembership(graph),handoffs=new Set(),inputs=new Map(),forward=new Set();
    const rounds=new Map(graph.items.map(({tasks,round})=>[tasks.id,round]));
    const buckets=new Map(),owners=new Map();
    for(const {from,to,kind} of graph.links){
      if(kind==='dependency'){
        if(!inputs.has(to))inputs.set(to,[]);
        inputs.get(to).push(from);
        if(initial.get(from)!==initial.get(to))forward.add(from);
      }
    }
    for(const {from,to,kind,arranged} of graph.links){
      const group=initial.get(from);
      if(kind!=='planning'&&!arranged)continue;
      const crossGroup=group!==initial.get(to);
      if(rounds.get(from)){
        if(crossGroup)forward.add(from);
      }else if(crossGroup||group.startsWith('$tasks:')&&inputs.get(from)?.length>1)handoffs.add(from);
    }
    for(const item of graph.items){
      if(item.tasks.status==='cancelled')continue;
      const id=item.tasks.id,sources=inputs.get(id)||[];
      const round=rounds.get(id);
      if(round){
        const sourceRounds=new Set(sources.map(source=>rounds.get(source)).filter(Boolean));
        const external=sourceRounds.size-Number(sourceRounds.has(round));
        if(external>1||sourceRounds.size>1&&forward.has(id))handoffs.add(id);
        continue;
      }
      const origins=new Set(sources.map(source=>initial.get(source)));
      const external=origins.size-Number(origins.has(initial.get(id)));
      if(external>1||origins.size>1&&forward.has(id))handoffs.add(id);
    }
    const membership=roundMembership(graph,handoffs);
    for(const item of graph.items){
      if(handoffs.has(item.tasks.id))continue;
      const group=membership.get(item.tasks.id);
      if(!buckets.has(group))buckets.set(group,[]);
      buckets.get(group).push(item);
    }
    for(const [id,members] of buckets){
      const round=members[0].round||'',key=round||id;
      if(!round&&members.length===1&&members[0].tasks.status!=='cancelled')continue;
      const card={id,key,round,members,links:[],open:filtered||expanded.has(key)||members.some(i=>i.tasks.id===selected)};
      for(const item of members)owners.set(item.tasks.id,card);
    }
    const nodes=[];
    for(const item of graph.items){
      const id=item.tasks.id,card=owners.get(id);
      if(!card)nodes.push({id,item,...(handoffs.has(id)?{handoff:true}:{})});
      else if(card.members[0]===item)nodes.push({id:card.id,card});
    }
    const links=new Map();
    for(const link of graph.links){
      const source=owners.get(link.from),target=owners.get(link.to);
      if(source&&source===target){
        if(source.open)source.links.push(link);
        continue;
      }
      const from=source?.id??link.from,to=target?.id??link.to;
      const key=JSON.stringify([from,to,link.kind]);
      if(!links.has(key))links.set(key,{from,to,kind:link.kind,tasks:[]});
      links.get(key).tasks.push(link);
    }
    return {nodes,links:[...links.values()],membership};
  }
  function parallelRows(nodes,links,levels){
    const order=new Map(nodes.map((node,index)=>[node.id,index]));
    const peers=new Map(nodes.map(node=>[node.id,[]])),first=new Map();
    const join=(key,id)=>{
      const peer=first.get(key);
      if(peer===undefined)first.set(key,id);
      else if(peer!==id){peers.get(id).push(peer);peers.get(peer).push(id);}
    };
    for(const {from,to,kind} of links){
      const before=levels.get(from),after=levels.get(to);
      if(kind==='recovery'||before>=after)continue;
      // Slots at the same depth share a row when they meet at recorded work.
      join(JSON.stringify(['from',from,after]),to);
      join(JSON.stringify(['to',to,before]),from);
    }
    const visited=new Set(),rows=[];
    for(const {id} of nodes){
      if(visited.has(id))continue;
      visited.add(id);
      const row=[id];
      for(const task of row)for(const peer of peers.get(task)){
        if(visited.has(peer))continue;
        visited.add(peer);row.push(peer);
      }
      rows.push(row.sort((a,b)=>order.get(a)-order.get(b)));
    }
    const rowOf=new Map(),before=rows.map(()=>new Set()),after=rows.map(()=>new Set());
    rows.forEach((row,index)=>row.forEach(id=>rowOf.set(id,index)));
    for(const {from,to,kind} of links){
      if(kind==='recovery'||levels.get(from)>=levels.get(to))continue;
      const source=rowOf.get(from),target=rowOf.get(to);
      before[target].add(source);
      after[source].add(target);
    }
    const pending=new Set(rows.keys()),ordered=[];
    let previous=null;
    while(pending.size){
      const ready=[...pending].filter(index=>!before[index].size);
      const next=ready.find(index=>after[previous]?.has(index))??ready[0];
      pending.delete(next);
      ordered.push(rows[next]);
      for(const target of after[next])before[target].delete(next);
      previous=next;
    }
    return ordered;
  }
  function readings(fields, progress={}, outputs={}) {
    const scalar=v=>Number.isFinite(v)||typeof v==='boolean'||(typeof v==='string'&&v.trim().length>0);
    if(Array.isArray(fields) && fields.length){
      const sources={progress,outputs};
      return fields.flatMap(field=>{
        if(typeof field?.path!=='string'||!field.label)return [];
        const {path,label,unit}=field;
        const value=path.split('.').reduce((obj,key)=>obj && typeof obj==='object' && Object.hasOwn(obj,key)?obj[key]:undefined,sources);
        return scalar(value)?[{label,value,unit,source:path.split('.')[0]}]:[];
      });
    }
    // These are explicit progress reports. Arbitrary result ports may contain paths or internal IDs.
    const metrics=Object.entries(progress.metrics||{}), reported=progress.progress;
    if(reported && typeof reported==='object')metrics.push(...Object.entries(reported));
    else metrics.push(['进度',reported]);
    metrics.push(['阶段',progress.phase]);
    return metrics.filter(([,v])=>scalar(v)).map(([label,value])=>({label,value,source:'progress'}));
  }
  const api={rows,groups,startTime,links,businessGraph,roundGraph,parallelRows,readings};if(typeof module!=='undefined' && module.exports)module.exports=api;else root.TaskHistory=api;
})(typeof globalThis!=='undefined'?globalThis:this);
