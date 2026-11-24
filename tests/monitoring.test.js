const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const script=fs.readFileSync('loop_anything/web/monitoring.js','utf8');
const ctx=vm.createContext({document:{addEventListener(){}},esc:v=>String(v??'').replaceAll('<','&lt;'),Date,Intl,time:t=>String(t)});
vm.runInContext(fs.readFileSync('loop_anything/web/work.js','utf8'),ctx);
vm.runInContext(script,ctx);
test('monitor metrics preserve zero and do not invent units',()=>{
  ctx.m={metrics:[],sample:{data:{available:0,done:true,status:'running'}}};
  assert.equal(vm.runInContext('monitorMetrics(m).length',ctx),1);
  assert.equal(vm.runInContext('monitorMetrics(m)[0].unit',ctx),'');
  assert.equal(vm.runInContext("monitorValue(m.sample.data,'available')",ctx),0);
});
test('history gaps are not connected or changed to zero',()=>{
  ctx.samples=[{at:1,data:{n:0}},{at:2,data:null,error:'timeout'},{at:3,data:{n:8}}];
  const html=vm.runInContext("monitorTrend(samples,{key:'n',label:'count',unit:''})",ctx);
  assert.match(html,/M42.0 92.0 M512.0 27.0/);
  assert.doesNotMatch(html,/ L/);
  assert.match(html,/tabindex="0"/);
  assert.match(html,/data-chart-value="0"/);
  assert.match(html,/chart-tooltip/);
});
test('result charts expose the exact submitted readings to the interactive plot',()=>{
  ctx.series=[{label:'precision',points:[[1,.876543],[2,0]]},{label:'recall',points:[[1,.5]]}];
  const html=vm.runInContext('observationFigure(series)',ctx);
  assert.match(html,/data-chart-position="1" data-chart-value="0\.876543"/);
  assert.match(html,/data-chart-label="recall" data-chart-position="1"/);
});
test('monitoring run links reuse the existing route',()=>{
  assert.match(vm.runInContext("monitoringRunLink('run-one','One')",ctx),/href="#run\/run-one" data-route-link/);
});
test('monitor page does not contain a second Run graph or task details',()=>{
  assert.doesNotMatch(script,/taskDependencyGraph|renderGraph|read_task|read_run|task_history/);
});
test('related measurements share resource rows; ambiguous labels keep every metric',()=>{
  ctx.monitor={name:'容量',data_state:'fresh',sample:{data:{a:0,b:3,c:5,d:2}},metrics:[
    {key:'a',label:'west · 总量',unit:'张'}, {key:'b',label:'east · 空余',unit:'张'},
    {key:'c',label:'east · 总量',unit:'张'}, {key:'d',label:'west · 空余',unit:'张'}
  ]};
  const html=()=>vm.runInContext('monitorReadings(monitor)',ctx);
  assert.match(html(),/scope="row">west<\/th><td>0 <small>张<\/small><\/td><td>2 /);
  assert.match(html(),/scope="row">east<\/th><td>5 <small>张<\/small><\/td><td>3 /);
  ctx.monitor.data_state='stale';
  assert.equal(html().match(/>—<\/span>/g).length,4);
  ctx.monitor.metrics[3].label='west · 总量';
  assert.equal(html().match(/<dt>/g).length,4);
});
test('a script display is the default and each viewer can override it',()=>{
  ctx.monitor={name:'样例',display:'bars',data_state:'fresh',sample:{data:{net:-8,memory:0}},metrics:[
    {key:'net',unit:'MB/s'}, {key:'memory',unit:'GB'}
  ]};
  const html=vm.runInContext('monitorReadings(monitor)',ctx);
  assert.equal(html.match(/class="comparison-bars"/g).length,2);
  assert.match(html,/left:0%;width:100%/);
  assert.match(html,/>0 <small>GB/);
  assert.match(vm.runInContext("monitorReadings(monitor,{view:'table'})",ctx),/<td>-8 <small>MB\/s/);
  assert.match(vm.runInContext("monitorReadings(monitor,{view:'trend',metric:'memory'})",ctx),/data-trend-metric="memory"/);
});
test('sample-driven groups keep per-pool totals and queue rows together',()=>{
  const metrics=(pool,row,name)=>['总量','空余'].map((label,i)=>({key:[pool,row,i].join('.'),label:name+' · '+label,unit:'张'}));
  ctx.monitor={id:'gpu',name:'GPU',display:'table',metrics:[],data_state:'fresh',sample:{data:{
    private:{total:[8,0],queue:[8,0]},public:{total:[50,20],queue:[50,20]},
    metric_groups:[
      {label:'私有池',metrics:[...metrics('private','total','合计'),...metrics('private','queue','private-a')]},
      {label:'公有池',metrics:[...metrics('public','total','合计'),...metrics('public','queue','public-a')]},
    ],
  }}};
  ctx.localStorage={getItem:key=>key==='monitor-section:group:gpu:私有池'?'false':null};
  const html=vm.runInContext('monitorReadings(monitor)',ctx);
  assert.match(html,/data-monitor-section="group:gpu:私有池"><summary>/);
  assert.match(html,/data-monitor-section="group:gpu:公有池" open><summary>/);
  assert.match(html,/合计<\/th><td>8 <small>张<\/small><\/td><td>0 /);
  assert.match(html,/合计<\/th><td>50 <small>张<\/small><\/td><td>20 /);
  assert.match(vm.runInContext("monitorReadings(monitor,{view:'trend',metric:'public.total.1'})",ctx),/公有池 · 合计 · 空余/);
});
