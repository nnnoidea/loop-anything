'use strict';

const assignmentStates={queued:'待启动',running:'执行中',idle:'等待条件',needs_input:'等你确认',completed:'已完成',stopped:'已停止',failed:'需要处理',unknown:'执行状态待核实'};
const stepStates={pending:'待执行',active:'进行中',waiting:'等待中',needs_input:'等你确认',done:'已完成',skipped:'已跳过',stopped:'已停止'};
const planAgentLabels={starting:'Agent 启动中',running:'Agent 运行中',idle:'Agent 未运行',unknown:'Agent 状态待核实'};
const stepTimeFormat=new Intl.DateTimeFormat('zh-CN',{
  month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'
});
let assignmentSerial=0,assignmentSignature='',assignmentLastRead=0,assignmentRequest='',reviewScope=null,previewSerial=0;

function assignmentStatus(state,labels=assignmentStates){
  return `<span class="assignment-state" data-state="${esc(state)}">${esc(labels[state]||state)}</span>`;
}
function planExcerpt(text,limit){
  const line=String(text??'').split(/\r?\n/).map(line=>line.trim()).find(Boolean)||'';
  return line.length>limit?line.slice(0,limit-1).trimEnd()+'…':line;
}
function planTitle(item){
  return planExcerpt(item.title.trimStart().replace(/^#{1,6}[ \t]+/,''),72)||'托管规划';
}
function stepCompletionTime(step){
  if(step.status!=='done'||!Number.isFinite(step.completed_at))return '';
  const date=new Date(step.completed_at*1000);
  return `<time class="plan-step-time" datetime="${date.toISOString()}" title="${esc('平台记录完成时间 · '+runDate(step.completed_at)+' · 本地时间')}">${esc(stepTimeFormat.format(date))}</time>`;
}
function replyButton(item){
  if(item.state==='unknown')return item.can_recover?`<button data-recover-assignment="${esc(item.id)}">确认停止并继续</button>`:'<span class="muted small">原进程仍在运行</span>';
  if(item.can_follow_up)return `<button class="primary" data-assignment-reply="${esc(item.id)}" data-send-instruction>发送指令</button>`;
  return ['failed','needs_input'].includes(item.state)?`<button data-assignment-reply="${esc(item.id)}">${item.state==='needs_input'?'补充说明':'重新交给 Agent'}</button>`:'';
}
function planMarkup(items){
  if(!items.length)return '<div class="assignment-empty"><h2>还没有托管规划</h2></div>';
  const chosen=items.find(item=>item.id===activeRoute.id)||items[0];
  const steps=chosen.steps.filter(s=>s&&typeof s.title==='string');
  const status=item=>item.state==='idle'&&item.wait_errors?.length
    ?assignmentStatus('blocked',{blocked:'等待受阻'}):assignmentStatus(item.state);
  const list=items.length>1?`<nav class="plans-list" aria-label="已有规划">${items.map(item=>
    `<a class="plan-option" ${chosen.id===item.id?'aria-current="page"':''} href="${esc(routeHash({type:'plans',id:item.id}))}" data-route-link>
      <strong>${esc(planTitle(item))}</strong>${status(item)}
    </a>`).join('')}</nav>`:'';
  const waitMessages=chosen.state==='idle'?chosen.wait_messages||[]:[];
  const current=chosen.state==='stopped'?null:
    steps.find(s=>s.status==='active'||s.status==='needs_input')||steps.find(s=>s.status==='waiting');
  const focus=waitMessages[0]||(chosen.state==='needs_input'||chosen.state==='completed'?chosen.summary:'');
  const focusText=planExcerpt(focus,160);
  const showWaitDetails=waitMessages.length>1||(waitMessages.length===1&&waitMessages[0]!==focusText);
  const done=steps.filter(s=>s.status==='done'||s.status==='skipped').length;
  const hasStepDetails=step=>step.note||typeof step.run_id==='string';
  const stepMarkup=(step,index)=>{
    const state=chosen.state==='stopped'&&['waiting','active','needs_input'].includes(step.status)?'stopped':step.status;
    return `<li data-step="${esc(state)}"${step===current?' aria-current="step"':''}>
    <span class="plan-step-marker" aria-hidden="true">${step.status==='done'?'✓':''}</span>
    <div class="plan-step-content"><div class="plan-step-heading">
      <strong>${esc(step.title)}</strong><div class="plan-step-meta">${stepCompletionTime(step)}${assignmentStatus(state,stepStates)}</div>
    </div>${hasStepDetails(step)?`<details class="plan-disclosure" data-plan-disclosure="${esc('step:'+index+':'+step.title)}">
      <summary>详情<span class="sr-only"> · ${esc(step.title)}</span></summary>
      ${step.note?`<p>${esc(step.note)}</p>`:''}
      ${typeof step.run_id==='string'?navLink({type:'run',id:step.run_id,task:step.task_id},step.task_id?'查看节点 →':'查看 Run →'):''}
    </details>`:''}</div>
  </li>`;
  };
  return `<div class="plans-layout${list?' has-plan-list':''}">
    <article class="assignment-detail" data-plan-id="${esc(chosen.id)}">
      <header class="plan-heading"><h2>${esc(planTitle(chosen))}</h2>
        <div class="plan-meta">${status(chosen)}
          ${planAgentLabels[chosen.agent_state]?`<span class="plan-agent-state" data-agent-state="${esc(chosen.agent_state)}">${planAgentLabels[chosen.agent_state]}</span>`:''}
          <span>${esc(chosen.model)}</span>
        </div>
      </header>
      ${focusText?`<p class="plan-focus" data-state="${esc(chosen.state)}">${esc(focusText)}</p>`:''}
      ${chosen.wait_errors?.length&&chosen.state==='idle'?chosen.wait_errors.map(w=>`<p class="assignment-error">${esc(w.error)}</p>`).join(''):''}
      ${chosen.error?`<p class="assignment-error">${esc(chosen.error)}</p>`:''}
      ${steps.length?`<div class="plan-progress"><h3>执行步骤</h3><span>${done} / ${steps.length} 已处理</span></div>
        <ol class="plan-steps">${steps.map(stepMarkup).join('')}</ol>`:
        chosen.state==='running'||chosen.state==='queued'?'<p class="plan-preparing">正在准备执行步骤…</p>':''}
      <footer><details class="plan-disclosure plan-instructions" data-plan-disclosure="instructions">
        <summary>规划详情</summary>
        <h3>原始指令</h3><p>${esc(chosen.title)}</p>
        ${showWaitDetails?`<h3>全部等待条件</h3><ul>${waitMessages.map(message=>`<li>${esc(message)}</li>`).join('')}</ul>`:''}
        ${chosen.summary?`<h3>最近进展</h3><p>${esc(chosen.summary)}</p>`:''}
      </details><div class="plan-actions">${replyButton(chosen)}
        ${chosen.can_stop?`<button data-stop-plan="${esc(chosen.id)}">停止规划</button>`:''}
        ${navLink({type:'timeline',id:chosen.timeline_id},'查看 Timeline →')}</div></footer>
    </article>${list}
  </div>`;
}
function reviewMarkup(items){
  if(!items.length)return '<div class="assignment-empty"><h3>还没有回顾报告</h3><p>选择一个 Loop 和时间范围，查看运行情况、耗时和反复出现的问题。</p></div>';
  const latest=new Map(),sessions=new Map(),reports=new Map();
  for(const item of items){
    const key=item.scope.loop_id;
    if(!latest.has(key))latest.set(key,item);
    if(item.id&&!sessions.has(key))sessions.set(key,item);
    if(item.reported_at!=null&&(!reports.has(key)||item.reported_at>reports.get(key).reported_at))reports.set(key,item);
  }
  return [...latest].map(([id,recent])=>{
    const session=sessions.get(id);
    const item=session&&['queued','running','needs_input','unknown'].includes(session.state)?session:recent;
    const report=reports.get(id);
    const reportLink=report?.report_url
      ?`<a href="${esc(report.report_url)}" target="_blank" rel="noopener noreferrer">查看报告 →</a>`
      :report?navLink({type:'timeline',id:report.timeline_id},'查看回顾记录 →'):'';
    return `<article class="review-row"><div><header><h3>${esc(item.title)}</h3>${assignmentStatus(item.state)}</header>
      <small class="muted">${esc(runDate(item.reported_at??item.at))}${item.count==null?'':' · '+esc(item.count)+' 个 Run'}</small>
      ${item.error?`<p class="assignment-error">${esc(item.error)}</p>`:''}</div>
      <footer>${reportLink}${replyButton(item)}<button data-review-loop="${esc(id)}">发起回顾</button></footer></article>`;
  }).join('');
}
async function refreshAssignments(force=false){
  const plan=page==='plans',type=page;
  if(!force&&Date.now()-assignmentLastRead<2500)return;
  assignmentLastRead=Date.now();
  const serial=++assignmentSerial;
  const data=await api('assignments/'+(plan?'plan':'review'));
  if(serial!==assignmentSerial||page!==type)return;
  const html=plan?planMarkup(data.items):reviewMarkup(data.items);
  if(force||html!==assignmentSignature){
    const container=$(plan?'plan-items':'review-items');
    const previous=plan?container.querySelector('[data-plan-id]'):null;
    const open=new Set(previous?[...previous.querySelectorAll('details[open]')].map(detail=>detail.dataset.planDisclosure):[]);
    const focused=previous?.contains(document.activeElement)?document.activeElement.closest('summary')?.parentElement:null;
    container.innerHTML=html;
    const current=previous&&container.querySelector('[data-plan-id]');
    if(current&&current.dataset.planId===previous.dataset.planId){
      for(const detail of current.querySelectorAll('details[data-plan-disclosure]')){
        detail.open=open.has(detail.dataset.planDisclosure);
        if(detail.dataset.planDisclosure===focused?.dataset.planDisclosure)detail.firstElementChild.focus({preventScroll:true});
      }
    }
  }
  assignmentSignature=html;
}
function formError(text){
  const error=$('assignment-form').querySelector('[role=alert]');
  error.textContent=text;error.hidden=!text;
}
function openAssignment(kind,preselect='',sendInstruction=false){
  const form=$('assignment-form'),dialog=$('assignment-dialog');
  assignmentRequest=randomKey();reviewScope=null;previewSerial++;form.dataset.kind=kind;formError('');
  const submit=form.querySelector('[type=submit]');
  const model='<label>模型<input name="model" required list="assignment-models" value="gpt-6.1-sol" maxlength="100"></label><datalist id="assignment-models"><option>gpt-6.1-sol</option><option>gpt-6.2-sol</option></datalist>';
  if(kind==='plan'){
    $('assignment-heading').textContent='新建规划';submit.textContent='开始托管';submit.disabled=false;
    $('assignment-fields').innerHTML='<label>想安排什么？<textarea name="text" required rows="4" placeholder="等这次评测结束，如果分数超过基线，就安排下一轮实验。"></textarea></label>'+model;
  }else if(kind==='reply'){
    form.dataset.session=preselect;
    form.dataset.replyAction=sendInstruction?'instruct':'reply';
    $('assignment-heading').textContent=sendInstruction?'给原 Agent 发送指令':'交给 Agent 继续';
    submit.textContent=sendInstruction?'发送':'提交';submit.disabled=false;
    $('assignment-fields').innerHTML=`<label>${sendInstruction?'指令':'补充说明'}<textarea name="text" rows="4" required autofocus></textarea></label>`;
  }else{
    const versions=catalog.filter(item=>item.key&&!item.archived_at);
    $('assignment-heading').textContent='发起回顾';submit.textContent='开始回顾';submit.disabled=true;
    $('assignment-fields').innerHTML=`<label>Loop<select name="key" required>${versions.map(item=>`<option value="${esc(item.key)}" data-loop-id="${esc(item.loop_definition.id)}">${esc(item.loop_definition.name||item.loop_definition.id)} · ${esc(item.loop_definition.version)}</option>`).join('')}</select></label>
      <div class="assignment-pair"><label>检查版本<select name="version"><option value="one">所选版本</option><option value="all">所有版本</option></select></label>
      <label>Run 创建时间<select name="days"><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="0">全部时间</option><option value="custom">自选日期</option></select></label></div>
      <div id="review-dates" hidden><div class="assignment-pair"><label>起始日期<input name="begin" type="date"></label><label>结束日期<input name="end" type="date"></label></div></div>
      <p class="muted" id="review-count" role="status"></p>`;
    const option=[...form.elements.key.options].find(o=>o.dataset.loopId===preselect);
    if(option)form.elements.key.value=option.value;
    previewReview();
  }
  dialog.showModal();
}
async function previewReview(){
  const serial=++previewSerial,form=$('assignment-form'),option=form.elements.key.selectedOptions[0];
  const submit=form.querySelector('[type=submit]');submit.disabled=true;reviewScope=null;formError('');
  if(!option){$('review-count').textContent='请先安装要回顾的 Loop。';return;}
  const custom=form.elements.days.value==='custom',days=Number(form.elements.days.value);
  $('review-dates').hidden=!custom;
  let end=Date.now()/1000,start=days?end-days*86400:null;
  if(custom){
    start=dateBound(form.elements.begin.value);end=dateBound(form.elements.end.value,true);
    if(end===null||start===null||start>=end){$('review-count').textContent='请选择完整的起止日期。';return;}
    end=Math.min(end,Date.now()/1000);
  }
  const args={loop_id:option.dataset.loopId,archived:'include',created_to:end,...(start===null?{}:{created_from:start}),
    ...(form.elements.version.value==='one'?{loop_key:option.value}:{})};
  $('review-count').textContent='正在计算范围…';
  try{
    const data=await platformCall('list_runs',{...args,view:'revisions',limit:1});
    if(serial!==previewSerial)return;
    $('review-count').textContent=`本次将检查 ${data.total} 个 Run`;submit.disabled=data.total===0;
    reviewScope={loop_key:option.value,this_version:Boolean(args.loop_key),created_to:end,...(start===null?{}:{created_from:start})};
  }catch(error){if(serial===previewSerial)formError(error.message);}
}
$('new-plan').onclick=()=>openAssignment('plan');
$('new-review').onclick=()=>openAssignment('review');
$('assignment-form').onchange=e=>{if(['key','days','version','begin','end'].includes(e.target.name))previewReview();};
$('assignment-form').onsubmit=async event=>{
  event.preventDefault();
  const form=event.currentTarget,kind=form.dataset.kind,submit=form.querySelector('[type=submit]');
  if(submit.disabled)return;
  submit.disabled=true;formError('');
  try{
    let result;
    if(kind==='reply')result=await api('assignments/'+encodeURIComponent(form.dataset.session)+'/'+form.dataset.replyAction,{text:form.elements.text.value});
    else result=await api('assignments',{kind,request_id:assignmentRequest,
      ...(kind==='plan'?{text:form.elements.text.value,model:form.elements.model.value.trim()}:reviewScope)});
    $('assignment-dialog').close();
    if(kind==='plan')await navigateTo({type:'plans',id:result.id});
    else await refreshAssignments(true);
  }catch(error){formError(error.message);}
  finally{submit.disabled=false;}
};
document.addEventListener('click',event=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.dataset.recoverAssignment&&confirm('已确认原 Agent 进程停止？平台将读取已有进度并继续这次安排。')){
    b.disabled=true;
    safely(async()=>{try{await api('assignments/'+encodeURIComponent(b.dataset.recoverAssignment)+'/reply',{confirmed_stopped:true,text:''});await refreshAssignments(true);}finally{b.disabled=false;}});
  }
  if(b.dataset.reviewLoop)openAssignment('review',b.dataset.reviewLoop);
  if(b.dataset.assignmentReply)openAssignment('reply',b.dataset.assignmentReply,b.hasAttribute('data-send-instruction'));
  if(b.dataset.stopPlan&&confirm('停止后，这条规划的等待将取消。已启动的 Run 继续按自身安排运行。')){
    b.disabled=true;
    safely(async()=>{try{
      await api('assignments/'+encodeURIComponent(b.dataset.stopPlan)+'/stop',{});
      await refreshAssignments(true);
    }finally{b.disabled=false;}});
  }
  if(b.matches('#assignment-dialog .close-dialog'))$('assignment-dialog').close();
});
