'use strict';

const assignmentStates={queued:'待启动',running:'执行中',idle:'等待条件',needs_input:'等你确认',completed:'已完成',failed:'需要处理',unknown:'执行状态待核实'};
const stepStates={pending:'待执行',active:'进行中',waiting:'等待中',needs_input:'等你确认',done:'已完成',skipped:'已跳过'};
let assignmentSerial=0,assignmentSignature='',assignmentLastRead=0,assignmentRequest='',reviewScope=null,previewSerial=0;

function assignmentStatus(state,labels=assignmentStates){
  return `<span class="assignment-state" data-state="${esc(state)}">${esc(labels[state]||state)}</span>`;
}
function assignmentLine(item){
  const current=item.steps.find(s=>s&&['active','waiting','needs_input'].includes(s.status));
  return current?[current.title,current.note].filter(Boolean).join(' · '):item.summary.split('\n')[0]||assignmentStates[item.state];
}
function replyButton(item){
  return ['failed','needs_input'].includes(item.state)?`<button data-assignment-reply="${esc(item.id)}">${item.state==='needs_input'?'补充说明':'重新交给 Agent'}</button>`:'';
}
function planMarkup(items){
  if(!items.length)return '<div class="assignment-empty"><h2>还没有托管规划</h2><p>例如，等评测结束后比较基线，分数提升就安排下一轮。</p></div>';
  const chosen=items.find(item=>item.id===activeRoute.id)||items[0];
  const steps=chosen.steps.filter(s=>s&&typeof s.title==='string');
  const list=items.map(item=>`<a class="plan-option ${chosen.id===item.id?'selected':''}" href="${esc(routeHash({type:'plans',id:item.id}))}" data-route-link><strong>${esc(item.title)}</strong><small>${esc(assignmentLine(item))}</small></a>`).join('');
  return `<div class="plans-layout"><nav class="plans-list" aria-label="已有规划">${list}</nav><article class="assignment-detail">
    <header>${assignmentStatus(chosen.state)}<span class="muted small">${esc(chosen.model)}</span></header>
    <h2>${esc(chosen.title)}</h2>
    ${steps.length?`<ol class="plan-steps">${steps.map(s=>`<li data-step="${esc(s.status)}"><div><strong>${esc(s.title)}</strong>${assignmentStatus(s.status,stepStates)}</div>${s.note?`<p>${esc(s.note)}</p>`:''}${typeof s.run_id==='string'?navLink({type:'run',id:s.run_id,task:s.task_id},'查看对应 Run →'):''}</li>`).join('')}</ol>`:`<p class="muted">${chosen.state==='running'||chosen.state==='queued'?'正在准备规划，Agent 提交步骤后会显示在这里。':'暂无已提交的步骤。'}</p>`}
    ${chosen.state==='needs_input'&&chosen.summary?`<p>${esc(chosen.summary)}</p>`:''}
    ${chosen.error?`<p class="assignment-error">${esc(chosen.error)}</p>`:''}
    <footer>${replyButton(chosen)}${navLink({type:'timeline',id:chosen.timeline_id},'查看 Timeline →')}</footer></article></div>`;
}
function reviewMarkup(items){
  if(!items.length)return '<div class="assignment-empty"><h3>还没有回顾报告</h3><p>选择一个 Loop 和时间范围，查看运行情况、耗时和反复出现的问题。</p></div>';
  const latest=new Map(),reports=new Map();
  for(const item of items){
    const key=item.scope.loop_id;
    if(!latest.has(key))latest.set(key,item);
    if(item.summary&&!reports.has(key))reports.set(key,item);
  }
  return [...latest].map(([id,item])=>{
    const report=reports.get(id);
    return `<article class="review-row"><div><header><h3>${esc(item.title)}</h3>${assignmentStatus(item.state)}</header>
      <small class="muted">${esc(runDate(item.at))} · 本次范围 ${esc(item.count)} 个 Run</small>
      ${report?`<p>${report.id===item.id?'':'上次回顾 · '}${esc(report.summary.split('\n')[0])}</p>`:''}${item.error?`<p class="assignment-error">${esc(item.error)}</p>`:''}</div>
      <footer>${report?navLink({type:'timeline',id:report.timeline_id},'查看报告 →'):''}${replyButton(item)}<button data-review-loop="${esc(id)}">发起回顾</button></footer></article>`;
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
  if(force||html!==assignmentSignature)$(plan?'plan-items':'review-items').innerHTML=html;
  assignmentSignature=html;
}
function formError(text){
  const error=$('assignment-form').querySelector('[role=alert]');
  error.textContent=text;error.hidden=!text;
}
function openAssignment(kind,preselect=''){
  const form=$('assignment-form'),dialog=$('assignment-dialog');
  assignmentRequest=randomKey();reviewScope=null;previewSerial++;form.dataset.kind=kind;formError('');
  const submit=form.querySelector('[type=submit]');
  const model='<label>模型<input name="model" required list="assignment-models" value="gpt-6.1-sol" maxlength="100"></label><datalist id="assignment-models"><option>gpt-6.1-sol</option><option>gpt-6.2-sol</option></datalist>';
  if(kind==='plan'){
    $('assignment-heading').textContent='新建规划';submit.textContent='开始托管';submit.disabled=false;
    $('assignment-fields').innerHTML='<label>想安排什么？<textarea name="text" required rows="4" placeholder="等这次评测结束，如果分数超过基线，就安排下一轮实验。"></textarea></label>'+model;
  }else if(kind==='reply'){
    form.dataset.session=preselect;$('assignment-heading').textContent='交给 Agent 继续';submit.textContent='提交';submit.disabled=false;
    $('assignment-fields').innerHTML='<label>补充说明<textarea name="text" rows="3" required></textarea></label>';
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
    if(kind==='reply')result=await api('assignments/'+encodeURIComponent(form.dataset.session)+'/reply',{text:form.elements.text.value});
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
  if(b.dataset.reviewLoop)openAssignment('review',b.dataset.reviewLoop);
  if(b.dataset.assignmentReply)openAssignment('reply',b.dataset.assignmentReply);
  if(b.matches('#assignment-dialog .close-dialog'))$('assignment-dialog').close();
});
