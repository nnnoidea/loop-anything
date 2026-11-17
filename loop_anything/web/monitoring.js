'use strict';
let monitoringData=null,monitoringBusy=false,monitoringLast=0,monitoringOffset=0,monitoringTab='overview',monitoringSignature='';
const monitorNames={running:'采集中',stopped:'已停止采集',completed:'采集结束',unknown:'执行待核实'};
const collectionNames={fresh:'有效',error:'采集失败',empty:'尚无数据',stale:'数据过期',unknown:'状态未知',stopped:'已停止'};
function monitorAge(at){if(!at)return '尚未采集';const n=Math.max(0,Math.floor(Date.now()/1000-at));return n<60?n+' 秒前':n<3600?Math.floor(n/60)+' 分钟前':new Date(at*1000).toLocaleString('zh-CN');}
function monitorValue(data,key){return key.split('.').reduce((v,k)=>v!=null&&Object.hasOwn(v,k)?v[k]:undefined,data);}
function monitorMetrics(m){
  if(m.metrics.length)return m.metrics;
  return Object.entries(m.sample?.data||{}).filter(([k,v])=>k!=='done'&&typeof v==='number').slice(0,3).map(([key])=>({key,label:key,unit:''}));
}
function monitoringRunLink(id,title){return `<a href="#run/${encodeURIComponent(id)}" data-route-link>${esc(title||id)}</a>`;}
function monitorCondition(expr){
  if(!expr||typeof expr!=='object')return typeof expr==='string'?expr:String(expr);
  if(expr.path)return Array.isArray(expr.path)?expr.path.join('.'):expr.path;
  const args=(expr.args||[]).map(monitorCondition),symbol={eq:'＝',ge:'≥',le:'≤',and:'且',or:'或',add:'＋'};
  return symbol[expr.op]?args.join(' '+symbol[expr.op]+' '):expr.op+'('+args.join(', ')+')';
}
function monitorCard(m){
  const valid=m.data_state==='fresh',metrics=monitorMetrics(m);
  const values=metrics.map(metric=>{const value=valid?monitorValue(m.sample?.data,metric.key):null;return `<div><span class="muted small">${esc(metric.label||metric.key)}</span><strong>${typeof value==='number'&&Number.isFinite(value)?esc(value):'—'} <small>${esc(metric.unit||'')}</small></strong></div>`;}).join('');
  return `<article class="monitor-card"><div class="monitor-card-heading"><button class="monitor-detail-button" data-monitor-detail="${esc(m.id)}">${esc(m.name)}</button><span class="monitor-state ${valid?'':'monitor-warning'}">${esc(collectionNames[m.data_state])}</span></div>
    <div class="monitor-values">${values||`<span class="muted">${valid?'已收到观测结果，查看详情':'尚无有效观测值'}</span>`}</div>
    <p class="small muted">${m.run_id?'Run 实例 · '+monitoringRunLink(m.run_id):'常态监控'} · ${esc(monitorNames[m.status]||m.status)}</p>
    <p class="small muted">最近成功采集：<span data-monitor-at="${m.sample?.at||''}">${esc(monitorAge(m.sample?.at))}</span> · 每 ${esc(m.interval)} 秒检查</p>
    ${m.error?`<p class="monitor-warning small">采集失败，当前外部状态未知</p>`:''}</article>`;
}
function renderMonitoring(){
  if(!monitoringData)return;
  const d=monitoringData;
  $('monitoring-overview').hidden=monitoringTab!=='overview';$('monitoring-scripts').hidden=monitoringTab!=='scripts';
  document.querySelectorAll('[data-monitor-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.monitorTab===monitoringTab);b.setAttribute('aria-selected',String(b.dataset.monitorTab===monitoringTab));});
  const signature=JSON.stringify([d.counts,d.runs,d.monitors,d.external,d.waits,d.scripts,monitoringOffset]);
  $('monitoring-updated').textContent='更新于 '+new Date(d.at*1000).toLocaleTimeString('zh-CN',{hour12:false});
  document.querySelectorAll('#monitoring-page [data-monitor-at]').forEach(e=>{e.textContent=monitorAge(Number(e.dataset.monitorAt));});
  if(signature===monitoringSignature)return;
  monitoringSignature=signature;
  $('monitoring-counts').innerHTML=[['running','运行中'],['paused','已暂停'],['completed','已完成'],['terminated','已终止']].map(([key,label])=>`<span>${label} <strong>${d.counts[key]||0}</strong></span>`).join('');
  $('monitoring-runs').innerHTML=d.runs.length?`<div class="monitor-table-wrap"><table class="monitor-table"><thead><tr><th>Run</th><th>状态</th><th>最近进展</th></tr></thead><tbody>${d.runs.map(r=>`<tr><td>${monitoringRunLink(r.id,r.title)}${r.attention_count?`<small class="monitor-warning">有 ${r.attention_count} 项需要查看</small>`:''}</td><td>${r.superseded_by?'已接续':badge(r.status)}</td><td><span data-monitor-at="${r.last_activity_at||''}">${esc(monitorAge(r.last_activity_at))}</span></td></tr>`).join('')}</tbody></table></div>`:'<p class="monitor-empty">还没有 Run。启动后会自动显示实际运行状态。</p>';
  $('monitoring-page-number').textContent=d.total_runs?`${d.offset+1}–${d.offset+d.runs.length} / ${d.total_runs}`:'0 条';
  $('monitoring-prev').disabled=d.offset===0;$('monitoring-next').disabled=d.offset+d.runs.length>=d.total_runs;
  $('monitoring-pagination').hidden=d.total_runs<=d.limit;
  $('monitoring-standing').innerHTML=d.monitors.filter(m=>!m.run_id).map(monitorCard).join('')||'<p class="monitor-empty">尚未接入常态监控。用户或团队可以注册自己的资源监控脚本。</p>';
  const instances=d.monitors.filter(m=>m.run_id).map(monitorCard).join('');
  const external=d.external.map(e=>`<article class="monitor-card"><div>${monitoringRunLink(e.run_id,e.run_title)} · ${esc(e.node)}</div><p class="small muted">Loop 自带监控 · 当前页 Run</p><p class="${e.error?'monitor-warning':''}">${e.error?'采集异常，外部状态待核实':esc(e.business_status||labels[e.status]||e.status)}</p><p class="small">进度与执行记录在对应 Run 中查看。</p></article>`).join('');
  $('monitoring-instances').innerHTML=instances+external||'<p class="monitor-empty">尚无 Run 监控实例。可在 Run 中使用自带脚本，或实例化已注册的脚本。</p>';
  $('monitoring-waits-title').textContent='等待条件 · '+d.waits.length;
  $('monitoring-waits').innerHTML=d.waits.map(w=>`<div class="monitor-wait"><div><strong>${esc(w.message||'等待条件满足后唤醒 Agent')}</strong> <span class="muted">${w.state==='ready'?'条件已满足，待会话处理':'等待中'}</span></div><p>${esc(monitorCondition(w.condition))}</p><p class="small">${Object.entries(w.sources).map(([name,s])=>s.kind==='monitor'?`<button class="monitor-detail-button" data-monitor-detail="${esc(s.id)}">${esc(name)} · 监控</button>`:monitoringRunLink(s.id,name)).join(' · ')} · <button data-work-timeline="${esc(w.timeline_id)}">查看 Timeline</button></p>${w.error?`<p class="monitor-warning small">当前无法判断：${esc(w.error)}</p>`:''}</div>`).join('')||'<p class="muted">当前没有待处理的条件等待。</p>';
  $('monitoring-script-list').innerHTML=d.scripts.length?`<div class="monitor-table-wrap"><table class="monitor-table"><thead><tr><th>脚本定义</th><th>版本</th><th>实例</th></tr></thead><tbody>${d.scripts.map(s=>`<tr><td>${esc(s.description||s.id)}<small>${esc(s.id)}</small></td><td>${s.revision}</td><td>${s.instances}</td></tr>`).join('')}</tbody></table></div>`:'<p class="monitor-empty">脚本库为空。这里不预置通用 GPU 或实验脚本，由用户或团队提供自己的实现。</p>';
}
async function refreshMonitoring(force=false){
  if(page!=='monitors'||monitoringBusy||(!force&&Date.now()-monitoringLast<5000))return;
  monitoringBusy=true;monitoringLast=Date.now();const requestedOffset=monitoringOffset;
  try{
    const data=await platformCall('read_monitor_dashboard',{offset:monitoringOffset,limit:20});
    if(page!=='monitors'||requestedOffset!==monitoringOffset)return;
    monitoringOffset=data.offset;monitoringData=data;$('monitoring-error').hidden=true;renderMonitoring();
  }catch(error){
    if(page==='monitors'){$('monitoring-error').hidden=false;$('monitoring-error').textContent='更新失败，以下为上次读取的数据：'+error.message;}
  }finally{monitoringBusy=false;if(page==='monitors'&&requestedOffset!==monitoringOffset)refreshMonitoring(true);}
}
function monitorTrend(samples,metric){
  const points=samples.map(s=>({at:s.at,value:!s.error?monitorValue(s.data,metric.key):null}));
  const good=points.filter(p=>typeof p.value==='number'&&Number.isFinite(p.value));
  if(!good.length)return '';
  const min=Math.min(...good.map(p=>p.value)),max=Math.max(...good.map(p=>p.value)),span=max-min||1;
  const first=points[0].at,last=points.at(-1).at;
  const tick=v=>new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:2}).format(v);
  const x=p=>42+(p.at-first)/(last-first||1)*470,y=p=>92-(p.value-min)/span*65;
  let path='',open=false;
  for(const p of points){if(typeof p.value!=='number'||!Number.isFinite(p.value)){open=false;continue;}path+=(open?' L':' M')+x(p).toFixed(1)+' '+y(p).toFixed(1);open=true;}
  return `<figure class="monitor-trend"><figcaption>${esc(metric.label||metric.key)}${metric.unit?'（'+esc(metric.unit)+'）':''}</figcaption><svg viewBox="0 0 560 126" role="img" aria-label="${esc(metric.label||metric.key)}历史观测，采集失败处断开"><path d="M42 97H512" class="monitor-axis" fill="none"/><path d="${path}" class="monitor-series" fill="none"/>${good.map(p=>`<circle cx="${x(p)}" cy="${y(p)}" r="2" class="monitor-point"><title>${esc(new Date(p.at*1000).toLocaleString())}：${esc(p.value)}</title></circle>`).join('')}<text x="35" y="29" text-anchor="end">${esc(tick(max))}</text><text x="35" y="94" text-anchor="end">${esc(tick(min))}</text><text x="42" y="118">${esc(time(first))}</text><text x="512" y="118" text-anchor="end">${esc(time(last))}</text></svg></figure>`;
}
async function openMonitorDetail(id){
  const [value,history]=await Promise.all([platformCall('read_monitor',{monitor_id:id}),platformCall('read_monitor_history',{monitor_id:id})]);
  const m=value.monitor,script=m.script.script,metrics=monitorMetrics({metrics:script.metrics||[],sample:m.sample});
  $('detail-title').textContent=script.description||m.script.id||'监控详情';
  $('detail-content').innerHTML=`<p>${m.run_id?'关联 '+monitoringRunLink(m.run_id):'常态监控'} · ${esc(monitorNames[m.status]||m.status)}</p><p class="small muted">来源：${esc(m.script.id?'平台注册 · '+m.script.id+' v'+m.script.revision:'自带脚本')} · 最近成功采集：${esc(monitorAge(m.sample?.at))}</p>${m.error?`<p class="monitor-warning">采集错误：${esc(m.error)}。这不代表实验失败。</p>`:''}${history.samples.length?metrics.map(metric=>monitorTrend(history.samples,metric)).join(''):'<p class="monitor-empty">尚无采样历史，接入脚本后开始记录。</p>'}<p class="small muted">最多保留最近 ${history.retention} 次采集；缺失与失败不会补成零。</p>${readerJSON('最近有效结果',m.sample)}${readerJSON('实例参数',m.parameters)}<button id="monitor-detail-stop" class="danger-quiet" ${m.status==='stopped'?'disabled':''}>停止后续采集</button><p class="small muted">只停止此监控实例，不终止实验，也不停止其他实例。</p>`;
  $('monitor-detail-stop').onclick=()=>safely(async()=>{await platformCall('stop_monitor',{monitor_id:id});await openMonitorDetail(id);await refreshMonitoring(true);});
  $('detail-content').querySelectorAll('[data-route-link]').forEach(link=>link.addEventListener('click',event=>{if(!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&event.button===0)$('detail-dialog').close();}));
  $('detail-dialog').showModal();
}
document.addEventListener('click',event=>safely(async()=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.id==='monitoring-refresh')await refreshMonitoring(true);
  if(b.dataset.monitorTab){monitoringTab=b.dataset.monitorTab;renderMonitoring();}
  if(b.dataset.monitorDetail)await openMonitorDetail(b.dataset.monitorDetail);
  if(b.id==='monitoring-prev'||b.id==='monitoring-next'){monitoringOffset=Math.max(0,monitoringOffset+(b.id==='monitoring-next'?20:-20));await refreshMonitoring(true);}
}));
