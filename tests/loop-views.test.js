'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ctx=vm.createContext({document:{addEventListener(){}},esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),pretty:v=>JSON.stringify(v,null,2),kindNames:{agent:'Agent',command:'脚本'},chosenImplementation:(item,id)=>item.implementations[id]});
for(const name of ['loop_graph','lifecycle'])vm.runInContext(fs.readFileSync(`loop_anything/web/${name}.js`,'utf8'),ctx);
const run=code=>vm.runInContext(code,ctx);
ctx.atob=atob;ctx.TextDecoder=TextDecoder;
test('authored overview displays saved UTF-8 HTML in an opaque sandbox without deriving routes',()=>{
  const html='<html><body><h1>研究流程</h1><script>parent.document.body.remove()</script></body></html>';
  ctx.item={assets:[{path:'docs/flow.html',base64:Buffer.from(html).toString('base64')}]};
  const before=JSON.stringify(ctx.item),rendered=run('overviewFlowHTML(item)');
  assert.match(rendered,/title="Loop 整体流程图"/);
  assert.match(rendered,/sandbox="allow-scripts"/);
  assert.doesNotMatch(rendered,/allow-same-origin|allow-top-navigation|<script>/);
  assert.match(rendered,/connect-src &#39;none&#39;/);
  assert.match(rendered,/研究流程/);
  assert.equal(JSON.stringify(ctx.item),before);
});
test('missing or corrupt diagram has an explicit empty/error view, not an inferred business graph',()=>{
  ctx.item={assets:[]};assert.match(run('overviewFlowHTML(item)'),/尚未绘制/);
  ctx.item.assets=[{path:'docs/flow.html',base64:'!!!'}];assert.match(run('overviewFlowHTML(item)'),/无法读取/);
});
test('full transition matrix preserves each condition, parameter update and notification rule',()=>{
  ctx.config={kind:'external',lifecycle:{initial:'waiting',transitions:[{from:'waiting',event:'failed',when:{path:'attempt',op:'lt',value:3},to:'retry',parameters:{batch:4},notify:[{message:'<check>',route:'chat',reply:{event:'answer',key:'q',schema:{type:'object'}}}]},{from:'waiting',event:'failed',when:{path:'attempt',op:'gte',value:3},to:'agent'}]}};
  const before=JSON.stringify(ctx.config),html=run('lifecycleMatrix(config,undefined,true)');
  assert.match(html,/class="lifecycle-matrix" open/);
  for(const field of ['判断条件','附加动作','&lt;check&gt;','batch','answer','gte','规则 2'])assert.ok(html.includes(field),field);
  assert.equal((html.match(/<tr class=/g)||[]).length,2);
  assert.equal(JSON.stringify(ctx.config),before);
});
test('state diagram separates normal self progress from failed monitoring and keeps custom events neutral',()=>{
  ctx.config={kind:'external',lifecycle:{initial:'waiting',transitions:[
    {from:'waiting',event:'progress',to:'waiting'},
    {from:'waiting',event:'check_error',to:'waiting'},
    {from:'waiting',event:'custom_error_named_but_unknown',to:'waiting'},
    {from:'waiting',event:'failed',to:'retry'},
    {from:'waiting',event:'failed',to:'agent'}
  ]}};
  const before=JSON.stringify(ctx.config),html=run('lifecycleDiagram(config)');
  assert.equal((html.match(/data-lifecycle-to="waiting"/g)||[]).length,3);
  for(const text of ['tone-normal','tone-failure','tone-other','tone-retry','tone-agent','停止检查，等待恢复监控','规则 5'])assert.ok(html.includes(text),text);
  assert.equal(JSON.stringify(ctx.config),before);
});
test('node state view separates incoming, outgoing and new self tasks without inventing transitions or changing the definition',()=>{
  ctx.item={loop_definition:{schema_version:2,entry:'a',fallback_node:'repair',nodes:{a:{label:'入口',plan_nodes:['b']},b:{label:'工作',plan_nodes:['b'],routes:[{id:'again',event:'completed',plan:'down',when:{eq:[1,1]}}]},c:{label:'下游'},repair:{}},plans:{down:{steps:{b:{node:'b'},c:{node:'c',after:['b']}}}}},implementations:{}};
  const before=JSON.stringify(ctx.item),html=run('nodeStateHTML(item,"b",config)');
  for(const text of ['转入本节点','从本节点转出','本节点内','入口 → 工作','工作 → 下游','工作 → repair','创建新 Task','可安排任务','事件创建任务','满足条件时','执行内转移矩阵'])assert.ok(html.includes(text),text);
  assert.equal(JSON.stringify(ctx.item),before);
  ctx.item.settings={fallback_node:null};
  assert.doesNotMatch(run('nodeStateHTML(item,"b",config)'),/工作 → repair/);
});

const reader=fs.readFileSync('loop_anything/web/authoring.js','utf8').split('const readerAgentDialog=')[0];
vm.runInContext(reader,ctx);
test('light defaults expose only existing declared scalars and preserve untouched complex values',()=>{
  ctx.valueField=(value,schema)=>`<input value="${value}" data-value-type="${schema.type}">`;
  ctx.lightBP={entry:'init',nodes:{init:{inputs:{count:{type:'integer'},flag:{type:'boolean'},rules:{type:'object'},union:{type:['string','null']}}}},defaults:{count:3,flag:false,rules:{when:{path:'x'},items:[1,2]},union:null,unknown:'keep'}};
  const html=run('lightDefaultsHTML(lightBP)');
  assert.equal((html.match(/data-light-default=/g)||[]).length,2);
  ctx.readValue=element=>element.result;
  ctx.lightRoot={querySelectorAll:()=>[{dataset:{lightDefault:'count'},querySelector:()=>({result:4})}]};
  run('collectLightDefaults(lightBP,lightRoot)');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.lightBP.defaults)),{count:4,flag:false,rules:{when:{path:'x'},items:[1,2]},union:null,unknown:'keep'});
});
test('implementation reading retains commands, prompt, contracts and all lifecycle details without edit forms',()=>{
  ctx.defaultImplementation=e=>e.default;ctx.promptDefaults={task:'default context'};
  ctx.implementation={kind:'agent',command:['codex','exec','{{prompt}}'],resume_command:['codex','resume','{{session_id}}'],prompt:'Business instructions',parameter_schema:{type:'object',properties:{x:{type:['string','null']}}},lifecycle:{initial:'running',transitions:[{from:'running',event:'failed',when:{path:'attempt',op:'lt',value:2},to:'retry',parameters:{batch:2}}]}};
  ctx.readerItem={loop_definition:{nodes:{n:{}}},implementations:{n:{default:'one'}},assets:[]};
  const before=JSON.stringify(ctx.implementation),html=run('readerCandidateHTML(readerItem,"n","one",implementation)');
  for(const content of ['codex','resume','Business instructions','完整实现配置','batch','判断条件','null'])assert.ok(html.includes(content),content);
  assert.doesNotMatch(html,/<input|<textarea|<select|data-candidate-command|data-transition-/);
  assert.equal(JSON.stringify(ctx.implementation),before);
});
