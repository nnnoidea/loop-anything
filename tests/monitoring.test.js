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
