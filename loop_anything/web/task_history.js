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
    const add=(from,to,kind)=>{const key=JSON.stringify([from,to,kind]);if(from&&from!==to&&run.tasks[from]&&run.tasks[to]&&!seen.has(key)){seen.add(key);result.push({from,to,kind});}};
    for(const item of items){
      const task=item.tasks;
      for(const id of item.dependencies)add(id,task.id,'dependency');
      const creator=byExecution.get(task.origin?.execution||task.origin?.agent);
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
  function roundGraph(graph,expanded,selected,filtered){
    const owners=new Map();
    for(const group of groups(graph.items)){
      const members=group.items.filter(item=>item.tasks.status==='completed'&&!item.attempts.at(-1)?.observation_error);
      if(members.length<2)continue;
      const round=group.round||'';
      const card={id:'$round:'+round,round,members,open:filtered||expanded.has(round)||members.some(i=>i.tasks.id===selected)};
      for(const item of members)owners.set(item.tasks.id,card);
    }
    const nodes=[];
    for(const item of graph.items){
      const id=item.tasks.id,card=owners.get(id),first=card?.members[0]===item;
      if(!card||card.open)nodes.push({id,item,card:first&&!filtered?card:null});
      else if(first)nodes.push({id:card.id,card});
    }
    const endpoint=id=>owners.get(id)?.open===false?owners.get(id).id:id;
    const links=new Map();
    for(const link of graph.links){
      const from=endpoint(link.from),to=endpoint(link.to);
      if(from!==to)links.set(JSON.stringify([from,to,link.kind]),{from,to,kind:link.kind});
    }
    return {nodes,links:[...links.values()]};
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
  const api={rows,groups,startTime,links,businessGraph,roundGraph,readings};if(typeof module!=='undefined' && module.exports)module.exports=api;else root.TaskHistory=api;
})(typeof globalThis!=='undefined'?globalThis:this);
