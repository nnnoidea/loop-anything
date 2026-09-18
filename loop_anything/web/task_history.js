'use strict';
(function(root){
  const startTime=e=>Object.hasOwn(e,'started_at')?e.started_at:e.created_at;
  function rows(run){
    const executions=run.executions || [],byExecution=new Map(executions.map(e=>[e.id,e])),attempts=new Map();
    for(const e of executions){if(!attempts.has(e.task_id))attempts.set(e.task_id,[]);attempts.get(e.task_id).push(e);}
    const tasks=run.tasks || {},producers=new Map();
    for(const w of Object.values(tasks))for(const destination of Object.values(w.spec.outputs || {})){
      const key=destination.id+'@'+((destination.expected_revision || 0)+1);
      if(!['cancelled','stale'].includes(w.status))producers.set(key,w.id);
    }
    return Object.values(tasks).map((w,index)=>{
      const tries=[...(attempts.get(w.id) || [])].sort((a,b)=>a.created_at-b.created_at);
      const current=byExecution.get(w.execution_id),dependencies=new Set(w.spec.after || []);
      if(current){
        for(const source of Object.values(current.sources || {}))for(const ref of Array.isArray(source)?source:[source]){
          const producer=byExecution.get(ref.execution);if(producer)dependencies.add(producer.task_id);
        }
      }else for(const source of Object.values(w.spec.inputs || {})){
        for(const id of source.records || (source.record?[source.record]:[])){
          const versions=run.records?.[id] || [],record=source.revision?versions.find(r=>r.revision===source.revision):versions.at(-1);
          if(record){const producer=record.tasks || byExecution.get(record.producer)?.task_id;if(producer)dependencies.add(producer);}
          else {const producer=producers.get(id+'@'+(source.revision || 1));if(producer)dependencies.add(producer);}
        }
      }
      dependencies.delete(w.id);
      return {tasks:w,attempts:tries,legacyTime:tries.some(e=>!Object.hasOwn(e,'started_at')),started:tries.map(startTime).filter(t=>t!=null).sort((a,b)=>a-b)[0] ?? null,completed:current?.completed_at ?? null,
        round:w.spec.round || null,dependencies:(run.task_dependencies?.[w.id] || [...dependencies]).filter(id=>tasks[id]),index};
    }).sort((a,b)=>(a.started===null)-(b.started===null) || (a.started ?? a.tasks.created_at ?? 0)-(b.started ?? b.tasks.created_at ?? 0) || a.index-b.index);
  }
  function groups(items){
    const result=new Map();
    for(const item of items){const key=item.round;if(!result.has(key))result.set(key,[]);result.get(key).push(item);}
    return [...result].map(([round,items])=>({round,items}));
  }
  const api={rows,groups,startTime};if(typeof module!=='undefined' && module.exports)module.exports=api;else root.TaskHistory=api;
})(typeof globalThis!=='undefined'?globalThis:this);
