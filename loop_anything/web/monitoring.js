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
// Labels such as "queue A · total" share a row when several resources report
// the same measures. Other label formats keep their original reading order.
function metricMatrix(metrics) {
  const rows = new Map(), columns = new Set();
  for (const metric of metrics) {
    const label = metric.label || metric.key, split = label.lastIndexOf(' · ');
    if (split < 1) return null;
    const name = label.slice(0, split), column = label.slice(split + 3);
    if (!rows.has(name)) rows.set(name, new Map());
    const row = rows.get(name);
    if (!column || row.has(column)) return null;
    row.set(column, metric);
    columns.add(column);
  }
  if (rows.size < 2 || !Array.from(rows.values()).every(row => row.size === columns.size)) return null;
  return {rows, columns: [...columns]};
}

const monitorViews = {auto:'默认视图',stat:'数值卡',table:'数据表',bars:'条形对比',trend:'历史趋势'};
const monitorPreferences = new Map();
function monitorPreference(id) {
  if (!monitorPreferences.has(id)) {
    let saved;
    try { saved = JSON.parse(localStorage.getItem('monitor-view:' + id)); } catch {}
    monitorPreferences.set(id, saved || {});
  }
  return monitorPreferences.get(id);
}
function monitorPicker(field, label, options, selected) {
  return `<select data-monitor-choice="${field}" aria-label="${esc(label)}">${options.map(([key,name]) =>
    `<option value="${esc(key)}"${key===selected?' selected':''}>${esc(name)}</option>`).join('')}</select>`;
}
function metricNumber(m, metric) {
  const value = m.data_state === 'fresh' ? monitorValue(m.sample?.data, metric.key) : null;
  return Number.isFinite(value) ? value : null;
}
function monitorBars(m, entries) {
  const units = new Map();
  for (const [label, metric] of entries) {
    const unit = metric.unit || '';
    if (!units.has(unit)) units.set(unit, []);
    units.get(unit).push({label, value:metricNumber(m, metric)});
  }
  return Array.from(units, ([unit, items]) => {
    const valid = items.map(item => item.value).filter(Number.isFinite);
    const min = Math.min(0,...valid), max = Math.max(0,...valid);
    // Normalize before subtraction so a signed range can span both extremes.
    const scale = Math.max(-min,max) || 1, span = (max/scale - min/scale) || 1;
    const zero = -min/scale/span * 100;
    return `<div class="comparison-bars">${units.size>1?`<h4>${esc(unit||'无单位')}</h4>`:''}${
      items.map(({label,value}) => {
        const width = Math.abs((value ?? 0)/scale)/span * 100;
        const left = value < 0 ? zero - width : zero;
        return `<div class="comparison-row"><span>${esc(label)}</span><b>${value===null?'—':esc(value)+' <small>'+esc(unit)+'</small>'}</b><div class="comparison-track" aria-hidden="true"><i style="left:${left}%;width:${width}%"></i></div></div>`;
      }).join('')
    }</div>`;
  }).join('');
}
function monitorReadings(m, preference = {}) {
  const metrics = monitorMetrics(m);
  if (!metrics.length) return `<p class="monitor-no-values">${m.data_state==='fresh'?'已收到观测结果，查看详情':'尚无有效观测值'}</p>`;
  const matrix = metricMatrix(metrics);
  const view = preference.view && preference.view !== 'auto' ? preference.view :
    m.display || (matrix || metrics.length > 4 ? 'table' : 'stat');
  function reading(metric) {
    const value = metricNumber(m,metric);
    if (value===null) return '<span class="muted">—</span>';
    return esc(value) + (metric.unit ? ` <small>${esc(metric.unit)}</small>` : '');
  }
  if (view==='trend') {
    const metric = metrics.find(item => item.key===preference.metric) || metrics[0];
    return (metrics.length>1?monitorPicker('metric','趋势指标',metrics.map(item=>[item.key,item.label||item.key]),metric.key):'') +
      `<div class="monitor-history" data-trend-metric="${esc(metric.key)}">正在读取趋势…</div>`;
  }
  if (view==='bars') {
    if (!matrix) return monitorBars(m,metrics.map(item=>[item.label||item.key,item]));
    const field = matrix.columns.includes(preference.column) ? preference.column : matrix.columns[0];
    return (matrix.columns.length>1?monitorPicker('column','比较指标',matrix.columns.map(c=>[c,c]),field):'') +
      monitorBars(m,Array.from(matrix.rows,([name,row])=>[name,row.get(field)]));
  }
  if (view==='stat') return '<dl class="monitor-values">' + metrics.map(metric =>
    `<div><dt>${esc(metric.label || metric.key)}</dt><dd>${reading(metric)}</dd></div>`
  ).join('') + '</dl>';
  if (!matrix) return `<div class="metric-matrix"><table aria-label="${esc(m.name)}指标"><thead><tr><th scope="col">指标</th><th scope="col">当前值</th></tr></thead><tbody>${metrics.map(metric=>
    `<tr><th scope="row">${esc(metric.label||metric.key)}</th><td>${reading(metric)}</td></tr>`).join('')}</tbody></table></div>`;
  const {rows, columns} = matrix;
  return `<div class="metric-matrix"><table aria-label="${esc(m.name)}指标"><thead><tr><th scope="col">对象</th>${columns.map(c => `<th scope="col">${esc(c)}</th>`).join('')}</tr></thead><tbody>${
    Array.from(rows, ([name, row]) => `<tr><th scope="row">${esc(name)}</th>${columns.map(c => `<td>${reading(row.get(c))}</td>`).join('')}</tr>`).join('')
  }</tbody></table></div>`;
}

function monitorCard(m){
  const preference = monitorPreference(m.id);
  return `<article class="monitor-card" data-monitor-id="${esc(m.id)}"><header class="monitor-card-heading"><h3><button class="monitor-detail-button" data-monitor-detail="${esc(m.id)}">${esc(m.name)}</button></h3><span class="monitor-state" data-state="${esc(m.data_state)}">${esc(collectionNames[m.data_state] || m.data_state)}</span>${monitorPicker('view','监控视图',Object.entries(monitorViews),preference.view||'auto')}</header>
    <div class="monitor-readings">${monitorReadings(m,preference)}</div>
    <footer class="monitor-meta"><span>${esc(monitorNames[m.status]||m.status)} · 每 ${esc(m.interval)} 秒</span><span>最近采集 <time data-monitor-at="${m.sample?.at||''}">${esc(monitorAge(m.sample?.at))}</time></span>${m.run_id?monitoringRunLink(m.run_id):''}</footer>
    ${m.error?'<p class="monitor-warning small">采集失败，当前外部状态未知</p>':''}</article>`;
}
function refreshMonitorTrends() {
  if (page!=='monitors' || monitoringTab!=='overview') return;
  for (const chart of document.querySelectorAll('#monitoring-overview [data-trend-metric]')) {
    const id = chart.closest('[data-monitor-id]').dataset.monitorId;
    const m = monitoringData.monitors.find(item=>item.id===id);
    const metric = monitorMetrics(m).find(item=>item.key===chart.dataset.trendMetric);
    const stamp = [m.sample?.at, m.data_state, m.error && Math.floor(monitoringData.at/m.interval)].join('/');
    if (chart.dataset.stamp===stamp) continue;
    chart.dataset.stamp=stamp;
    platformCall('read_monitor_history',{monitor_id:id,metric:metric.key,limit:60}).then(({points})=>{
      if (chart.isConnected && chart.dataset.stamp===stamp)
        chart.innerHTML = monitorPlot(points,metric) || '暂无有效历史采样';
    }).catch(()=>{
      if (chart.dataset.stamp===stamp) {delete chart.dataset.stamp;chart.textContent='暂时无法读取历史采样';}
    });
  }
}
document.addEventListener('change',event=>{
  const select=event.target.closest('[data-monitor-choice]');
  if (!select) return;
  const card=select.closest('[data-monitor-id]'), id=card.dataset.monitorId;
  const pref=monitorPreference(id);
  pref[select.dataset.monitorChoice]=select.value;
  try {localStorage.setItem('monitor-view:'+id,JSON.stringify(pref));} catch {}
  const m=monitoringData.monitors.find(item=>item.id===id);
  card.querySelector('.monitor-readings').innerHTML=monitorReadings(m,pref);
  card.querySelector(`[data-monitor-choice="${select.dataset.monitorChoice}"]`)?.focus();
  refreshMonitorTrends();
});

function resultMonitorCard(chart){
  const timeline=routeHash({type:'timeline',id:chart.timeline_id});
  return `<article class="monitor-card result-monitor-card" data-result-monitor-run="${esc(chart.run_id)}">
    <header class="monitor-card-heading"><h3>${monitoringRunLink(chart.run_id,chart.run_title)}</h3>
    <a href="${esc(timeline)}" data-route-link>查看 Timeline</a></header>
    <p class="result-monitor-label">${esc(chart.name)}</p>
    ${chart.summary?`<p class="small muted">${esc(chart.summary)}</p>`:''}
    ${observationFigure(chart.series)}
    <small class="muted">更新于 ${esc(runDate(chart.at))}</small>
  </article>`;
}

function externalMonitorGroups(items,showEmpty=true){
  const runs=new Map();
  for(const item of items){
    if(!runs.has(item.run_id))runs.set(item.run_id,new Map());
    const nodes=runs.get(item.run_id);
    if(!nodes.has(item.node))nodes.set(item.node,[]);
    nodes.get(item.node).push(item);
  }
  function state(e){
    if(['completed','cancelled','skipped','terminated','fault'].includes(e.status))return labels[e.status]||e.status;
    if(e.error)return '采集异常';
    const raw=e.business_status;
    return ({RUNNING:'运行中',PENDING:'等待中',QUEUED:'排队中',FAILED:'失败',SUCCEEDED:'成功',COMPLETED:'已完成'})[String(raw).toUpperCase()]||raw||labels[e.status]||e.status;
  }
  function sample(e){
    const facts=TaskHistory.readings(e.readout,e);
    const time=e.sampled_at;
    const link=routeHash({type:'run',id:e.run_id,task:e.task_id});
    const identity=[e.round,e.ref||e.external_id||e.task_id].filter(Boolean).join(' · ');
    const values=facts.map(f=>`<div><dt>${esc(f.label)}</dt><dd>${esc(f.value)}<small>${esc(f.unit||'')}</small></dd></div>`).join('');
    return `<div class="external-reading"><dl class="node-facts">${values}</dl><div><a href="${esc(link)}" data-route-link>${esc(identity)}</a><small>${esc(state(e))}${time?' · '+esc(runDate(time))+' 回报':''}</small></div></div>`;
  }
  let without=0;
  const cards=Array.from(runs,([id,nodes])=>{
    const sections=[];
    for(const [node,list] of nodes){
      const reported=list.filter(e=>TaskHistory.readings(e.readout,e).length);
      without+=list.length-reported.length;
      if(!reported.length)continue;
      reported.sort((a,b)=>(b.sampled_at||0)-(a.sampled_at||0));
      const first=reported[0],rest=reported.slice(3);
      sections.push(`<section><header><strong>${esc(first.label||node)}</strong></header>${reported.slice(0,3).map(sample).join('')}${rest.length?`<details data-external-group="${esc(JSON.stringify([id,node]))}"><summary>其他执行 · ${rest.length}</summary>${rest.map(sample).join('')}</details>`:''}</section>`);
    }
    const first=nodes.values().next().value[0];
    return sections.length?`<article class="monitor-card external-group"><h3>${monitoringRunLink(id,first.run_title)}</h3>${sections.join('')}</article>`:'';
  }).join('');
  return cards+(without&&showEmpty?`<small class="monitor-empty">${without} 项外部执行尚无指标回报</small>`:'');
}

function renderMonitoring(){
  if(!monitoringData)return;
  const d=monitoringData;
  $('monitoring-overview').hidden=monitoringTab!=='overview';$('monitoring-scripts').hidden=monitoringTab!=='scripts';
  document.querySelectorAll('[data-monitor-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.monitorTab===monitoringTab);b.setAttribute('aria-selected',String(b.dataset.monitorTab===monitoringTab));});
  const signature=JSON.stringify([d.counts,d.runs,d.monitors,d.result_charts,d.external,d.waits,d.scripts,monitoringOffset]);
  $('monitoring-updated').textContent='更新于 '+new Date(d.at*1000).toLocaleTimeString('zh-CN',{hour12:false});
  document.querySelectorAll('#monitoring-page [data-monitor-at]').forEach(e=>{e.textContent=monitorAge(Number(e.dataset.monitorAt));});
  if(signature===monitoringSignature){refreshMonitorTrends();return;}
  monitoringSignature=signature;
  $('monitoring-counts').innerHTML=[['running','运行中'],['paused','已暂停'],['completed','已完成'],['terminated','已终止']].map(([key,label])=>`<span data-status="${key}">${label} <strong>${d.counts[key]||0}</strong></span>`).join('');
  $('monitoring-runs').innerHTML=d.runs.length?`<div class="monitor-table-wrap"><table class="monitor-table"><thead><tr><th>Run</th><th>状态</th><th>最近进展</th></tr></thead><tbody>${d.runs.map(r=>`<tr><td>${monitoringRunLink(r.id,r.title)}${r.attention_count?`<small class="monitor-warning">有 ${r.attention_count} 项需要查看</small>`:''}</td><td>${r.superseded_by?'已接续':badge(r.status)}</td><td><span data-monitor-at="${r.last_activity_at||''}">${esc(monitorAge(r.last_activity_at))}</span></td></tr>`).join('')}</tbody></table></div>`:'<p class="monitor-empty">还没有 Run。启动后会自动显示实际运行状态。</p>';
  $('monitoring-page-number').textContent=d.total_runs?`${d.offset+1}–${d.offset+d.runs.length} / ${d.total_runs}`:'0 条';
  $('monitoring-prev').disabled=d.offset===0;$('monitoring-next').disabled=d.offset+d.runs.length>=d.total_runs;
  $('monitoring-pagination').hidden=d.total_runs<=d.limit;
  $('monitoring-standing').innerHTML=d.monitors.filter(m=>!m.run_id).map(monitorCard).join('')||'<p class="monitor-empty">尚未接入常态监控。用户或团队可以注册自己的资源监控脚本。</p>';
  const instances=d.monitors.filter(m=>m.run_id).map(monitorCard).join('');
  const results=(d.result_charts||[]).map(resultMonitorCard).join('');
  const instancesRoot=$('monitoring-instances');
  const opened=new Set([...instancesRoot.querySelectorAll('[data-external-group][open]')].map(el=>el.dataset.externalGroup));
  instancesRoot.innerHTML=results+instances+externalMonitorGroups(d.external,!results)||'<p class="monitor-empty">尚无 Run 监控实例。</p>';
  for(const el of instancesRoot.querySelectorAll('[data-external-group]'))el.open=opened.has(el.dataset.externalGroup);
  $('monitoring-waits-title').textContent='等待条件 · '+d.waits.length;
  $('monitoring-waits').innerHTML=d.waits.map(w=>`<div class="monitor-wait"><div><strong>${esc(w.message||'等待条件满足后唤醒 Agent')}</strong> <span class="muted">${w.state==='ready'?'条件已满足，待会话处理':'等待中'}</span></div><p>${esc(monitorCondition(w.condition))}</p><p class="small">${Object.entries(w.sources).map(([name,s])=>s.kind==='monitor'?`<button class="monitor-detail-button" data-monitor-detail="${esc(s.id)}">${esc(name)} · 监控</button>`:monitoringRunLink(s.id,name)).join(' · ')} · <button data-work-timeline="${esc(w.timeline_id)}">查看 Timeline</button></p>${w.error?`<p class="monitor-warning small">当前无法判断：${esc(w.error)}</p>`:''}</div>`).join('')||'<p class="muted">当前没有待处理的条件等待。</p>';
  $('monitoring-script-list').innerHTML=d.scripts.length?`<div class="monitor-table-wrap"><table class="monitor-table"><thead><tr><th>脚本定义</th><th>版本</th><th>实例</th></tr></thead><tbody>${d.scripts.map(s=>`<tr><td>${esc(s.description||s.id)}<small>${esc(s.id)}</small></td><td>${s.revision}</td><td>${s.instances}</td></tr>`).join('')}</tbody></table></div>`:'<p class="monitor-empty">脚本库为空。这里不预置通用 GPU 或实验脚本，由用户或团队提供自己的实现。</p>';
  refreshMonitorTrends();
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
  return monitorPlot(samples.map(s=>({at:s.at,value:!s.error?monitorValue(s.data,metric.key):null})),metric);
}
function monitorPlot(points,metric){
  const good=points.filter(p=>typeof p.value==='number'&&Number.isFinite(p.value));
  if(!good.length)return '';
  const min=Math.min(...good.map(p=>p.value)),max=Math.max(...good.map(p=>p.value)),span=max-min||1;
  const first=points[0].at,last=points.at(-1).at;
  const tick=v=>new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:2}).format(v);
  const x=p=>last===first?277:42+(p.at-first)/(last-first)*470,y=p=>min===max?60:92-(p.value-min)/span*65;
  let path='',open=false;
  for(const p of points){if(typeof p.value!=='number'||!Number.isFinite(p.value)){open=false;continue;}path+=(open?' L':' M')+x(p).toFixed(1)+' '+y(p).toFixed(1);open=true;}
  return `<figure class="monitor-trend"><figcaption>${esc(metric.label||metric.key)}${metric.unit?'（'+esc(metric.unit)+'）':''}</figcaption><svg viewBox="0 0 560 126" role="img" aria-label="${esc(metric.label||metric.key)}历史观测，采集失败处断开"><path d="M42 97H512" class="monitor-axis" fill="none"/><path d="${path}" class="monitor-series" fill="none"/>${good.map(p=>`<circle cx="${x(p)}" cy="${y(p)}" r="2" class="monitor-point"><title>${esc(new Date(p.at*1000).toLocaleString())}：${esc(p.value)}</title></circle>`).join('')}<text x="35" y="${min===max?63:29}" text-anchor="end">${esc(tick(max))}</text>${min===max?'':`<text x="35" y="94" text-anchor="end">${esc(tick(min))}</text>`}<text x="42" y="118">${esc(time(first))}</text><text x="512" y="118" text-anchor="end">${esc(time(last))}</text></svg></figure>`;
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
