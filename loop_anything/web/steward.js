'use strict';

function renderSteward(){
  let panel=$('run-steward');
  if(!panel){
    $('run-navigation').insertAdjacentHTML('afterend','<section id="run-steward" class="task-card" hidden></section>');
    panel=$('run-steward');
  }
  panel.hidden=!run.steward;
  if(!run.steward)return;
  const requests=Object.values(run.steward_requests||{});
  const waiting=requests.filter(r=>r.status==='waiting_user');
  const pending=requests.filter(r=>r.status==='pending');
  const processing=requests.filter(r=>r.status==='processing');
  const failed=requests.filter(r=>r.status==='failed');
  panel.innerHTML=`<div class="toolbar"><strong>Run 管家 · ${esc(run.steward.name)}</strong><button data-steward-requests>查看委托与交接</button></div><p class="small muted">${pending.length} 项待处理 · ${processing.length} 项处理中 · ${waiting.length} 项等待回复 · ${failed.length} 项失败 · 接管于 ${esc(new Date(run.steward.assigned_at*1000).toLocaleString())}</p>`;
}

document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button');
  if(!button||!run)return;
  if(button.hasAttribute('data-steward-requests')){
    $('detail-title').textContent='管家委托与交接';
    $('detail-content').innerHTML=Object.values(run.steward_requests||{}).map(r=>`<section class="result-section"><h3>${esc(r.message||r.operation)}</h3><p>${esc(r.id)} · ${esc(({pending:'待处理',processing:'处理中',failed:'处理失败',waiting_user:'等待回复',completed:'已完成',cancelled:'已撤回'})[r.status]||r.status)}</p>${r.task_id?`<button data-task-focus="${esc(r.task_id)}">查看处理过程</button>`:''}${r.error?`<p role="alert">${esc(r.error)}</p>`:''}${resultView(r.result??'等待处理结果')}${r.replies?.length?`<details><summary>补充信息</summary>${resultView(r.replies)}</details>`:''}</section>`).join('')+`<h3>交接记录</h3>${run.history.filter(h=>h.kind==='steward_changed').map(h=>`<p>${esc(new Date(h.at*1000).toLocaleString())} · ${esc(h.detail.previous||'首次指派')} → ${esc(h.detail.agent_id)}</p>`).join('')}`;
    $('detail-dialog').showModal();
  }else if(button.dataset.taskFocus && button.closest('#detail-dialog')){
    $('detail-dialog').close();
  }
}));
