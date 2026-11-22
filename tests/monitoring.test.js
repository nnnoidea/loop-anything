const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const script=fs.readFileSync('loop_anything/web/monitoring.js','utf8');
const ctx=vm.createContext({document:{addEventListener(){}},esc:v=>String(v??'').replaceAll('<','&lt;'),Date,Intl,time:t=>String(t)});
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
});
test('conditions stay readable and run links reuse existing route',()=>{
  assert.equal(vm.runInContext("monitorCondition({op:'ge',args:[{path:'gpu.available'},8]})",ctx),'gpu.available ≥ 8');
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
