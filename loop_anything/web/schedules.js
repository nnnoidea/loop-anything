'use strict';

const scheduleLabels={registered:'已登记',waiting:'等待触发',checking:'检查条件中',running:'执行中',completed:'已完成',failed:'执行失败',stopped:'已停止',offline:'离线',unknown:'执行状态未知'};
const activeScheduleStates=['waiting','checking','running'];
const scheduleTime=value=>value ? new Date(value*1000).toLocaleString('zh-CN',{hour12:false}) : '—';
const pendingSchedules=new Set();
let scheduleSnapshot=null, scheduleReading=false;

function scheduleTrigger(definition){
  const repeats=!definition.at && (definition.repeat ?? !definition.conditional);
  const trigger=definition.at ? `指定时间 ${scheduleTime(Date.parse(definition.at)/1000)}` :
    `${definition.conditional?'每隔':'间隔'} ${definition.every} 秒${definition.conditional?'检查条件':''}`;
  return `${trigger} · ${repeats?'重复':'单次'}`;
}

function scheduleCard(task, open){
  const {id,definition,runtime,execution}=task;
  const active=activeScheduleStates.includes(runtime.status);
  const updated=active && runtime.definition_revision!==task.revision;
  const running=updated?runtime.schedule:definition;
  const occupied=execution && !['exited','error','stopped'].includes(execution.state);
  const blocked=!active && occupied;
  const result=runtime.last_result;
  return `<article class="catalog-card">
    <div class="library-card-top"><div><h2 class="card-title">${esc(running?.name ?? definition.name)}</h2>
      <p class="muted small">${running?esc(scheduleTrigger(running)):'当前实例使用早期配置，未记录触发方式。'}</p></div>
      <span class="badge ${esc(runtime.status)}">${esc(scheduleLabels[runtime.status] || runtime.status)}</span></div>
    ${running?.description?`<p class="card-description">${esc(running.description)}</p>`:''}
    ${runtime.status==='waiting'?`<p class="small muted">${running?.conditional?'下次检查':running?'下次执行':'下次触发'} ${scheduleTime(runtime.next_at)}</p>`:''}
    ${updated?`<p class="small muted">下次启动使用新配置 · ${esc(definition.name)} · ${esc(definition.receiver?'接单端，请通过 CLI 启动':scheduleTrigger(definition))}</p>`:''}
    ${runtime.error?`<p class="notice">${esc(runtime.error)}</p>`:''}
    ${occupied && !active?'<p class="small muted">上次执行待核实。请通过 CLI 查看进程状态。</p>':''}
    <div class="toolbar"><button ${active?'':'class="primary"'} data-schedule-id="${esc(id)}" data-schedule-action="${active?'stop':'start'}" ${blocked?'data-schedule-blocked':''} ${blocked || pendingSchedules.has(id)?'disabled':''}>${active?'停止':'启动'}</button></div>
    ${result?`<details data-schedule-result="${esc(id)}" ${open?'open':''}><summary>最近结果 · ${scheduleTime(result.at)}</summary>
      ${result.returncode!=null?`<p>退出码 ${esc(result.returncode)}</p>`:''}
      ${result.native_session?`<p class="small mono">Session ${esc(result.native_session.id)}</p>`:''}
      ${[result.stdout,result.stderr,result.output_tail,result.error].filter(Boolean).map(value=>`<pre>${esc(value)}</pre>`).join('')}</details>`:''}
    </article>`;
}

function scheduleButton(id){
  return $('schedules-list').querySelector(`button[data-schedule-id="${CSS.escape(id)}"]`);
}

async function refreshSchedules(){
  if(scheduleReading || page!=='schedules')return;
  scheduleReading=true;
  try{
    const data=await api('schedules');
    if(page!=='schedules')return;
    $('schedules-status').textContent='';
    $('schedules-status').hidden=true;
    if(JSON.stringify(data)===JSON.stringify(scheduleSnapshot))return;
    scheduleSnapshot=data;
    $('schedules-host').textContent=data.machine;
    $('schedules-directory').textContent=data.directory;
    const list=$('schedules-list');
    const open=new Set(Array.from(list.querySelectorAll('details[open]'),element=>element.dataset.scheduleResult));
    const focused=document.activeElement?.dataset.scheduleId;
    list.innerHTML=data.tasks.map(task=>scheduleCard(task,open.has(task.id))).join('') ||
      '<p class="empty-inline">还没有登记任务。请用 Agent 或 CLI 把任务登记到上面的目录。</p>';
    if(focused)scheduleButton(focused)?.focus({preventScroll:true});
  }catch(error){
    if(page==='schedules'){
      $('schedules-status').hidden=false;
      $('schedules-status').textContent='读取定时任务失败 · '+error.message;
    }
  }finally{scheduleReading=false;}
}

$('schedules-list').addEventListener('click',event=>{
  const button=event.target.closest('[data-schedule-action]');
  if(!button || pendingSchedules.has(button.dataset.scheduleId))return;
  const task=scheduleSnapshot?.tasks.find(item=>item.id===button.dataset.scheduleId);
  if(!task)return;
  safely(async()=>{
    const action=button.dataset.scheduleAction;
    pendingSchedules.add(task.id);
    button.disabled=true;
    try{
      await api(`schedules/${encodeURIComponent(task.id)}/${action}`,{revision:task.revision,owner:task.runtime.owner ?? null});
      toast(action==='start'?'定时任务已启动':'停止请求已提交');
    }catch(error){
      if(error.status===409)throw new Error('任务状态已变化，请查看刷新后的状态。');
      throw error;
    }finally{
      pendingSchedules.delete(task.id);
      const current=scheduleButton(task.id);
      if(current)current.disabled=current.hasAttribute('data-schedule-blocked');
      await refreshSchedules();
    }
  });
});
