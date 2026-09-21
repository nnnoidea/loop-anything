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
  for(const route of [{type:'catalog'},{type:'loop',key:'版本@1/a <b>',tab:'prepare'},{type:'editor',id:'draft-1'},{type:'run',id:'run-1'}]){
    assert.deepEqual(JSON.parse(run(`JSON.stringify(parseRoute(routeHash(${JSON.stringify(route)})))`)),route);
  }
  assert.equal(run("parseRoute('#run-legacy').id"),'run-legacy');
  assert.equal(run("parseRoute('#loop/a').tab"),'overview');
});
test('implementations and local readiness are separate; prose is never inferred',()=>{
  assert.match(run("libraryCard({key:'x',loop_definition:{id:'x',version:'1',nodes:{a:{},b:{}}},implementations:{a:{kind:'agent'}}})"),/部分实现/);
  assert.match(run("overviewHTML({loop_definition:{nodes:{},id:'x'},implementations:{}})"),/作者尚未提供/);
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
test('typed form values preserve false, zero, strings and structures',()=>{
  assert.equal(run("parseField('false','boolean','x')"),false);
  assert.equal(run("parseField('0','integer','x')"),0);
  assert.equal(run("parseField('001','string','x')"),'001');
  assert.equal(run("JSON.stringify(parseField('[1,2]','array','x'))"),'[1,2]');
  assert.throws(()=>run("parseField('1.5','integer','x')"));
  assert.throws(()=>run("parseField('null','object','x')"));
});
test('launch preview validates seed contracts and includes effective defaults',()=>{
  run("var bp={schema_version:2,entry:'init',defaults:{n:3,flag:false},nodes:{init:{inputs:{value:{type:'integer',minimum:1}}}},seed:{inputs:{value:{run:'n'}}}}");
  assert.equal(run("JSON.stringify(effectiveLaunchInputs(bp,{}))"),'{"n":3,"flag":false}');
  assert.throws(()=>run("effectiveLaunchInputs(bp,{n:0})"));
  assert.throws(()=>run("effectiveLaunchInputs(bp,{n:'3'})"));
  assert.throws(()=>run("validateInput({},{type:'object',required:['x']},'object')"));
  assert.throws(()=>run("validateInput([1,1],{type:'array',uniqueItems:true},'list')"));
});
test('nested run parameters remain objects, not flattened or guessed',()=>{
  run("var nested={schema_version:2,entry:'init',defaults:{settings:{count:2}},nodes:{init:{inputs:{n:{type:'integer'}}}},seed:{inputs:{n:{run:'settings.count'}}},guide:{parameters:{settings:{label:'设置'}}}}");
  assert.equal(run("launchFields(nested,nested.defaults)[0].type"),'object');
  assert.equal(run("launchFields(nested,nested.defaults)[0].label"),'设置');
  assert.equal(run("effectiveLaunchInputs(nested,{settings:{count:4}}).settings.count"),4);
  assert.throws(()=>run("effectiveLaunchInputs(nested,{settings:{}})"));
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
