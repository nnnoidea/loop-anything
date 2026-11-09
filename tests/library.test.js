'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({document:{createElement:()=>({}),querySelector:()=>({append(){}}),addEventListener(){}},esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),pretty:v=>JSON.stringify(v,null,2)});
context.$=()=>({addEventListener(){},parentElement:{after(){}}});
context.window={addEventListener(){}};
vm.runInContext(fs.readFileSync('loop_anything/web/library.js','utf8'),context);
vm.runInContext(fs.readFileSync('loop_anything/web/loop_graph.js','utf8'),context);
vm.runInContext(fs.readFileSync('loop_anything/web/navigation.js','utf8'),context);
function run(code){return vm.runInContext(code,context);}
test('routes round-trip versions, tabs, draft and Run identities with escaped keys',()=>{
  for(const route of [{type:'catalog'},{type:'loop',key:'版本@1/a <b>',tab:'prepare'},{type:'editor',id:'draft-1'},{type:'editor',id:'draft-1',node:'训练/一'},{type:'editor',id:'draft-1',node:'训练/一',implementation:'远端/a'},{type:'run',id:'run-1'}]){
    assert.deepEqual(JSON.parse(run(`JSON.stringify(parseRoute(routeHash(${JSON.stringify(route)})))`)),route);
  }
  assert.equal(run("parseRoute('#run-legacy').id"),'run-legacy');
  assert.equal(run("parseRoute('#loop/a').tab"),'overview');
});
test('implementations and local readiness are separate; prose is never inferred',()=>{
  assert.match(run("libraryCard({key:'x',loop_definition:{id:'x',version:'1',nodes:{a:{},b:{}}},implementations:{a:{kind:'agent'}}})"),/部分实现/);
  assert.match(run("checkHTML({checks:[{kind:'runtime',status:'unknown'}]})"),/未验证/);
  assert.doesNotMatch(run("checkHTML({checks:[{kind:'runtime',status:'unknown'}]})"),/保证运行成功。<\/strong>/);
});
test('all author text is escaped, including input source labels',()=>{
  const rendered=run("libraryCard({key:'<script>',loop_definition:{name:'<img onerror=x>',version:'1',guide:{purpose:'<script>x</script>'},nodes:{}},implementations:{}})");
  assert(!rendered.includes('<script>'));assert(rendered.includes('&lt;script&gt;'));
});
test('real commands marked simulated are still disclosed in v2',()=>{
  assert.match(run("executionLabel({kind:'agent',command:['run'],simulation:'example'},2)"),/仍执行命令/);
  assert.match(run("executionLabel({kind:'agent',command:['run'],simulation:'example'},1)"),/平台内置模拟/);
  assert.match(run("executionLabel({kind:'agent',simulation:'example'},2)"),/等待外部提交/);
});
test('execution and recovery descriptions follow dispatch and executor placement',()=>{
  const remote=run("executionLabel({kind:'agent',command:['codex'],executor:'worker-2'})");
  assert.match(remote,/执行端 worker-2/);assert.doesNotMatch(remote,/平台所在机器执行/);
  const named=run("executionLabel({kind:'agent',dispatch:{location:'group',agent_id:'papers'}})");
  assert.match(named,/团队具名 Agent papers/);assert.doesNotMatch(named,/未配置自动命令/);
  assert.match(run("executionLabel({kind:'agent',dispatch:{location:'local',agent_id:'papers'}})"),/本服务具名 Agent/);
  assert.match(run("executionLabel({kind:'command',command:['script']})"),/平台所在机器/);
  const fallback=run("fallbackSummary({loop_definition:{nodes:{repair:{}}},implementations:{repair:{kind:'agent',dispatch:{location:'group',agent_id:'papers'}}}},'repair')");
  assert.match(fallback,/接单后执行/);assert.doesNotMatch(fallback,/只能等待外部 Agent/);
});
test('task execution badge follows Task selection and then its dispatched snapshot',()=>{
  context.item={settings:{bindings:{work:'script'}},implementations:{work:{default:'script',options:{script:{kind:'command'},reason:{kind:'agent',agent_cli:'codex'}}}}};
  context.task={spec:{node:'work',implementation:'reason'}};
  assert.equal(run('taskImplementation(item,task).kind'),'agent');
  assert.equal(run('taskImplementation(item,task,{implementation:{kind:"external"}}).kind'),'external');
  context.task.spec.implementation=null;
  assert.equal(run('taskImplementation(item,task).kind'),'command');
  context.item.settings.bindings.work=null;
  assert.equal(run('taskImplementation(item,task)'),null);
});
test('Loop handbook and node Skill render their own body formats without mutation',()=>{
  run("var hand={name:'Loop 手册',instructions:'<b>启动与后续任务</b>'};var skill={name:'专业方法',content:'<b>证据分析</b>'}");
  const handbook=run("docView('Loop',hand)"),skill=run("docView('Skill',skill)");
  assert(handbook.includes('&lt;b&gt;启动与后续任务&lt;/b&gt;'));
  assert(skill.includes('<pre>&lt;b&gt;证据分析&lt;/b&gt;</pre>'));
  assert(!skill.includes('&quot;content&quot;'));
  assert.equal(run('hand.instructions'),'<b>启动与后续任务</b>');
  assert.equal(run('skill.content'),'<b>证据分析</b>');
});

test('definition relationships distinguish repeat planning from data dependencies without inventing routes',()=>{
  const bp={schema_version:2,entry:'start',nodes:{start:{plan_nodes:['work']},work:{},judge:{plan_nodes:['work','judge','end']},end:{},freeAgent:{}},plans:{batch:{steps:{work:{node:'work'},judge:{node:'judge',inputs:{value:{from:'work',port:'result'}}}}}}};
  const before=JSON.stringify(bp),edges=JSON.parse(run(`JSON.stringify(loopRelationships(${before}))`));
  assert(edges.some(e=>e.from==='work'&&e.to==='judge'&&e.kind==='dependency'&&!e.repeats));
  assert(edges.some(e=>e.from==='judge'&&e.to==='work'&&e.repeats));
  assert(edges.some(e=>e.from==='judge'&&e.to==='judge'&&e.repeats));
  assert(edges.some(e=>e.from==='judge'&&e.to==='end'&&!e.repeats));
  assert(!edges.some(e=>e.from==='end'||e.from==='freeAgent'));
  assert.equal(JSON.stringify(bp),before);
});

test('recovery relationships use explicit fallback and respect disabled overrides',()=>{
 const bp={schema_version:2,entry:'start',fallback_node:'recover',nodes:{start:{plan_nodes:['work']},work:{},recover:{}},plans:{}};
 const before=JSON.stringify(bp),get=value=>JSON.parse(run(`JSON.stringify(loopRelationships(${before}${value}))`));
 assert.deepEqual(get('').filter(e=>e.kind==='recovery').map(e=>[e.from,e.to]),[['start','recover'],['work','recover']]);
 assert(!get(',null').some(e=>e.kind==='recovery'));
 for(const fallback of [null,undefined,'toString']){
  const disabled={...bp,fallback_node:fallback,nodes:{start:{},null:{},undefined:{}}};
  assert(!JSON.parse(run(`JSON.stringify(loopRelationships(${JSON.stringify(disabled)}))`)).some(e=>e.kind==='recovery'));
 }
 assert(!get('').some(e=>e.repeats));
 assert.equal(JSON.stringify(bp),before);
});

test('declared input sources distinguish unbound ports, upstream outputs and intentional literals',()=>{
 const bp={"entry": "init", "seed": {"inputs": {}}, "nodes": {"init": {"inputs": {}}, "data": {"inputs": {}, "outputs": {"dataset": {}}}, "predict": {"inputs": {"dataset": {}, "checkpoint": {}, "zero": {}, "flag": {}}, "outputs": {}}}, "plans": {"experiment": {"steps": {"data": {"node": "data"}, "predict": {"node": "predict", "inputs": {"dataset": {"from": "data", "port": "dataset"}, "zero": {"literal": 0}, "flag": {"literal": false}}}}}}};
 const rows=JSON.parse(run(`JSON.stringify(nodeInputRows(${JSON.stringify(bp)},'predict'))`));
 assert.deepEqual(rows.filter(r=>r.missing).map(r=>r.port),['checkpoint']);
 assert.equal(rows[0].text,'data / dataset');
 delete bp.plans.experiment.steps.data;
 assert(JSON.parse(run(`JSON.stringify(nodeInputRows(${JSON.stringify(bp)},'predict'))`)).find(r=>r.port==='dataset').missing);
});

test('read-only node navigation keeps the overview and never calls an authoring API',async()=>{
  const inspector={scrollTop:10,focus(){}};
  context.editor={routeId:'draft-side',revision:3,loop_definition:{nodes:{work:{}}}};
  context.editorPage={querySelector:()=>inspector};context.page='editor';context.editSelection=null;
  context.history={pushState(){},replaceState(){}};context.structuredClone=structuredClone;
  context.window.matchMedia=()=>({matches:false});context.renderProperties=()=>{};context.updateNavigationUI=()=>{};
  context.saveEditor=()=>{throw Error('Reading must not save');};context.renderEditor=()=>{throw Error('Reading must not recreate iframe');};
  const before=JSON.stringify(context.editor);
  run("activeRoute={type:'editor',id:'draft-side'}");
  assert.equal(await run("navigateTo({type:'editor',id:'draft-side',node:'work',implementation:'one'})"),true);
  assert.equal(run('activeRoute.implementation'),'one');assert.equal(run('editSelection.node'),'work');
  assert.equal(await run("navigateTo({type:'editor',id:'draft-side'})"),true);
  assert.equal(run('editSelection'),null);assert.equal(JSON.stringify(context.editor),before);
});
