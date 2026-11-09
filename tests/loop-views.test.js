'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ctx=vm.createContext({location:{origin:'http://127.0.0.1:8769'},document:{addEventListener(){}},esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),pretty:v=>JSON.stringify(v,null,2),kindNames:{agent:'Agent',command:'脚本'},chosenImplementation:(item,id)=>item.implementations[id]});
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
  assert.equal((html.match(/data-lifecycle-to="waiting"/g)||[]).length,1);
  assert.equal((html.match(/data-rule-index=/g)||[]).length,5);
  const progress=html.split('data-rule-index="1"')[1].split('data-rule-index="2"')[0];
  const failedCheck=html.split('data-rule-index="2"')[1].split('data-rule-index="3"')[0];
  assert.doesNotMatch(progress,/停止检查/);assert.match(failedCheck,/停止检查/);
  for(const text of ['tone-normal','tone-failure','tone-other','tone-retry','tone-agent','停止检查，等待恢复监控','规则 5'])assert.ok(html.includes(text),text);
  assert.equal(JSON.stringify(ctx.config),before);
});
test('node state view separates incoming, outgoing and new self tasks without inventing transitions or changing the definition',()=>{
  ctx.item={loop_definition:{schema_version:2,entry:'a',fallback_node:'repair',nodes:{a:{label:'入口',plan_nodes:['b']},b:{label:'工作',plan_nodes:['b'],routes:[{id:'again',event:'completed',plan:'down',when:{eq:[1,1]}}]},c:{label:'下游'},repair:{}},plans:{down:{steps:{b:{node:'b'},c:{node:'c',after:['b']}}}}},implementations:{}};
  const before=JSON.stringify(ctx.item),html=run('nodeStateHTML(item,"b",config)');
  for(const text of ['转入本节点','从本节点转出','执行状态','入口 → 工作','工作 → 下游','工作 → repair','创建新 Task','可安排任务','事件创建任务','满足条件时','执行状态转移矩阵'])assert.ok(html.includes(text),text);
  assert.equal(JSON.stringify(ctx.item),before);
  ctx.item.settings={fallback_node:null};
  assert.doesNotMatch(run('nodeStateHTML(item,"b",config)'),/工作 → repair/);
});

const reader=fs.readFileSync('loop_anything/web/authoring.js','utf8').split('const taskContextDialog=')[0];
vm.runInContext(reader,ctx);
test('implementation reading retains commands, prompt, contracts and all lifecycle details without edit forms',()=>{
  ctx.defaultImplementation=e=>e.default;ctx.promptDefaults={task:'default context'};
  ctx.implementation={kind:'agent',executor:'worker-demo',command:['codex','exec','{{prompt}}'],resume_command:['codex','resume','{{session_id}}'],prompt:'Business instructions',parameter_schema:{type:'object',properties:{x:{type:['string','null']}}},lifecycle:{initial:'running',transitions:[{from:'running',event:'failed',when:{path:'attempt',op:'lt',value:2},to:'retry',parameters:{batch:2}}]}};
  ctx.readerItem={loop_definition:{nodes:{n:{}}},implementations:{n:{default:'one'}},assets:[]};
  const before=JSON.stringify(ctx.implementation),html=run('readerCandidateHTML(readerItem,"n","one",implementation)');
  for(const content of ['worker-demo','codex','resume','Business instructions','完整实现配置','batch','查看状态转移与完整矩阵','null'])assert.ok(html.includes(content),content);
  assert.doesNotMatch(html,/<input|<textarea|<select|data-reader-default|data-candidate-command|data-transition-/);
  assert.equal(JSON.stringify(ctx.implementation),before);
});
test('Loop call details expose mappings and an encoded child Run link without an external polling time',()=>{
  ctx.defaultImplementation=e=>e.default;
  ctx.implementation={kind:'loop',loop:{key:'installed-child',inputs:{x:{$:'inputs.source'}},result:{outputs:{y:{$:'records.answer'}}}}};
  ctx.readerItem={loop_definition:{nodes:{n:{}}},implementations:{n:{default:'one'}},assets:[]};
  const html=run('readerCandidateHTML(readerItem,"n","one",implementation)');
  for(const text of ['调用的 Loop','installed-child','inputs.source','records.answer'])assert.ok(html.includes(text),text);
  ctx.run={history:[]};ctx.labels={completed:'已完成'};
  ctx.attempt={id:'e',implementation:ctx.implementation,child_run_id:'run-child<1>',child_status:'completed',external_id:'run-child<1>',status:'waiting'};
  const detail=run('executionLifecycle(attempt)');
  assert.match(detail,/取消此处等待不会终止子 Run/);
  assert.match(detail,/href="#run\/run-child%3C1%3E"/);assert.match(detail,/已完成/);
  assert.doesNotMatch(detail,/下次检查|外部任务/);
});
test('execution, advancement and status stay independent for script nodes with flow decisions',()=>{
  ctx.item={loop_definition:{schema_version:2,nodes:{work:{routes:[{id:'judge',event:'completed',flow_agent:true}]}},plans:{}},implementations:{}};
  const before=JSON.stringify(ctx.item),html=run('nodeAxesHTML(item,"work",{kind:"command",executor:"worker-A"},"等待中")');
  for(const text of ['executor-command','运行：脚本 · worker-A','advancement-agent','推进：流程 Agent','状态：等待中'])assert.ok(html.includes(text),text);
  assert.ok(run('nodeStateHTML(item,"work",{kind:"command"})').includes('内置流程 Agent'));
  ctx.item.loop_definition.nodes.work.routes=[];
  assert.match(run('nodeAxesHTML(item,"work",{kind:"agent"})'),/推进：未声明后续/);
  assert.equal(JSON.stringify({...ctx.item,loop_definition:{...ctx.item.loop_definition,nodes:{work:{routes:[{id:'judge',event:'completed',flow_agent:true}]}}}}),before);
});

test('generic role triplets separate the executor, state-machine decision and next handler',()=>{
  const role=(config,state,context={},rule)=>{ctx.roleConfig=config;ctx.roleState=state;ctx.roleContext=context;ctx.roleRule=rule;return JSON.parse(JSON.stringify(run('stateExecutionRole(roleConfig,roleState,roleContext,roleRule)')));};
  assert.equal(role({kind:'command'},'executing').kind,'script');
  assert.equal(role({kind:'agent'},'custom_business_state').kind,'agent');
  assert.equal(role({kind:'external'},'submitting').label,'提交脚本');
  assert.equal(role({kind:'external'},'waiting').label,'外部任务 / 检查脚本');
  assert.equal(role({kind:'external'},'arbitrary_agent_named_state').kind,'external');
  assert.equal(role({kind:'command'},'completed').kind,'idle');
  assert.equal(role({kind:'command'},'agent',{fallback:'修复'}).kind,'agent');
  assert.equal(role({kind:'command'},'agent',{fallback:null}).kind,'idle');
  assert.equal(role({kind:'agent',lifecycle:{initial:'executing'}},'retry').label,'Agent重试');
  assert.equal(role({kind:'external'},'waiting',{}, {from:'waiting',event:'check_error'}).label,'外部任务 / 检查暂停');
  ctx.roleConfig={kind:'command',lifecycle:{initial:'executing',transitions:[{from:'executing',event:'needs_help',to:'agent'}]}};
  const html=run('lifecycleDiagram(roleConfig,undefined,{fallback:"修复"})');
  assert.match(html,/data-role-slot="current"[\s\S]*?data-role-kind="script"/);
  assert.match(html,/data-role-slot="decision"[\s\S]*?data-role-kind="machine"/);
  assert.match(html,/data-role-slot="target"[\s\S]*?data-role-kind="agent"/);
  assert.doesNotMatch(html,/完成后会继续吗|completion-next/);
  const matrix=run('lifecycleMatrix(roleConfig)');
  assert.match(matrix.split('<tbody>')[1],/data-role-kind="machine"/);
});
test('flow decisions and node relationships use the same roles without guessing Agent choices',()=>{
  ctx.roleItem={loop_definition:{schema_version:2,nodes:{source:{routes:[{id:'ask',event:'completed',flow_agent:true,when:false}],plan_nodes:['target']},target:{}},plans:{p:{steps:{a:{node:'source'},b:{node:'target',after:['a']}}}}},implementations:{source:{kind:'command'},target:{kind:'agent'}}};
  const before=JSON.stringify(ctx.roleItem),html=run('nodeStateHTML(roleItem,"source",{kind:"command"})');
  assert.match(html,/来源执行[\s\S]*?data-role-kind="script"/);
  assert.match(html,/后续判断[\s\S]*?data-role-kind="agent"/);
  assert.match(html,/目标执行[\s\S]*?由 Agent 选择/);
  assert.match(html,/始终不成立/);
  assert.match(html,/入口由状态机匹配事件与条件/);
  assert.match(html,/脚本显式安排/);
  assert.match(html,/目标执行（默认）[\s\S]*?data-role-kind="agent"/);
  const info=run('nodeFlowHTML(roleItem,"source",loopRelationships(roleItem.loop_definition))');
  assert.match(info,/来源执行[\s\S]*?data-role-kind="script"/);
  assert.equal((info.match(/class="flow-route-role"/g)||[]).length,1);
  assert.equal(JSON.stringify(ctx.roleItem),before);
});

test('overview selection accepts only the current sandbox and existing node IDs',()=>{
  const sender={};ctx.frame={contentWindow:sender};ctx.nodes={real:{}};
  for(const [source,data,expected] of [[sender,{type:'loop-node-select',node:'real'},'real'],[{}, {type:'loop-node-select',node:'real'},null],[sender,{type:'loop-node-select',node:'missing'},null],[sender,{type:'loop-node-select',node:'__proto__'},null],[sender,{type:'publish',node:'real'},null],[sender,null,null]]){
    ctx.event={source,data};assert.equal(run('overviewNodeMessage(event,frame,nodes)'),expected);
  }
});
test('sandbox bridge binds exact unique names or explicit IDs and ignores auxiliary or ambiguous shapes',()=>{
  const make=attrs=>({attrs:{...attrs},events:{},getAttribute(k){return this.attrs[k]??null;},setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,v){this.events[k]=v;},closest(){return null;}});
  const els=[make({'data-key':'训练'}),make({'data-key':'重复'}),make({'data-key':'结束'}),make({'data-loop-node':'b','data-key':'重复'}),make({'data-loop-node':'missing','data-key':'训练'})];
  const sent=[],parent={postMessage:msg=>sent.push(msg)},handlers={};
  const sandbox=vm.createContext({parent,document:{querySelectorAll:()=>els,currentScript:{dataset:{nodes:JSON.stringify([['a','训练'],['b','重复'],['c','重复']])}}},window:{addEventListener:(name,fn)=>handlers[name]=fn}});
  vm.runInContext(fs.readFileSync('loop_anything/web/flow_bridge.js','utf8'),sandbox);
  assert.equal(els[0].attrs['data-loop-node'],'a');assert.equal(els[0].attrs.tabindex,'0');
  for(const el of [els[1],els[2],els[4]])assert.equal(el.events.click,undefined);
  els[0].events.keydown({key:'Enter',preventDefault(){},stopPropagation(){}});
  els[3].events.click({preventDefault(){},stopPropagation(){}});
  assert.deepEqual(JSON.parse(JSON.stringify(sent)),[{type:'loop-node-select',node:'a'},{type:'loop-node-select',node:'b'}]);
  handlers.message({source:parent,data:{type:'loop-node-selected',node:'b'}});
  assert.equal(els[3].attrs['aria-pressed'],'true');assert.equal(els[0].attrs['aria-pressed'],'false');
  handlers.message({source:{},data:{type:'loop-node-selected',node:'a'}});assert.equal(els[0].attrs['aria-pressed'],'false');
});
test('overview uses only the trusted external bridge under the parent CSP, with escaped node metadata',()=>{
  const html=`<html data-theme="paper"><head><meta http-equiv="Content-Security-Policy" content="script-src 'sha256-OLD'"></head><body><p>Flow</p></body></html>`;
  ctx.item={loop_definition:{nodes:{'n"<':{label:'</script><script>alert(1)</script>'}}},assets:[{path:'docs/flow.html',base64:Buffer.from(html).toString('base64')}]};
  const rendered=run('overviewFlowHTML(item)');
  assert.match(rendered,/flow_bridge.js/);assert.doesNotMatch(rendered,/sha256-OLD|script-src &#39;unsafe-inline&#39;|<script>/);
  assert.match(rendered,/data-theme=&quot;paper&quot;/);assert.match(rendered,/data-nodes=/);
});


test('flow node inspector reads the selected candidate and complete rules without changing the default',()=>{
  ctx.implementationOptions=entry=>entry?.kind?{default:entry}:entry?.options||{};
  ctx.defaultImplementation=entry=>entry?.kind?'default':entry?.default;
  ctx.inspected={loop_definition:{schema_version:2,nodes:{a:{label:'前置',plan_nodes:['work']},work:{label:'工作',plan_nodes:['next']},next:{}},plans:{}},implementations:{work:{default:'standard',options:{standard:{kind:'command',lifecycle:{initial:'executing',transitions:[{from:'executing',event:'completed',to:'completed'}]}},remote:{kind:'external',lifecycle:{initial:'waiting',transitions:[{from:'waiting',event:'failed',when:{path:'attempt',op:'lt',value:3},to:'retry',parameters:{batch:9},notify:[{message:'need repair'}]}]}}}}}};
  const before=JSON.stringify(ctx.inspected),html=run('nodeStateInspectorHTML(inspected,"work","remote")');
  for(const value of ['规则对应方案：','<strong>remote</strong>','任务的执行规则','前置 → 工作','工作 → next','判断条件','附加动作','batch','need repair'])assert.ok(html.includes(value),value);
  assert.doesNotMatch(html,/id="editor-state-node"|id="editor-state-implementation"|实现配置 →|class="lifecycle-matrix" open/);
  assert.equal(JSON.stringify(ctx.inspected),before);
  const other=run('nodeStateInspectorHTML(inspected,"next")');
  assert.match(other,/尚未配置实现/);assert.match(other,/工作 → next/);assert.doesNotMatch(other,/need repair/);
});


test('shared endpoints group their action once while keeping each condition and side effect paired',()=>{
  ctx.ruleConfig={kind:'external',lifecycle:{initial:'waiting',transitions:[
    {from:'waiting',event:'retry_decided_by_script',when:{op:'le',args:[{path:'attempt'},2]},to:'retry',parameters:{batch:4}},
    {from:'waiting',event:'retry_decided_by_script',when:{op:'ge',args:[{path:'attempt'},3]},to:'retry',parameters:{batch:1},notify:[{message:'<check>'}]},
    {from:'waiting',event:'needs_help',to:'agent'}]}};
  const before=JSON.stringify(ctx.ruleConfig),html=run('lifecycleDiagram(ruleConfig,undefined,{taskLabel:"训练模型",fallback:"运行修复"})');
  assert.equal((html.match(/data-lifecycle-to="retry"/g)||[]).length,1);
  assert.equal((html.match(/重试“训练模型”任务/g)||[]).length,1);
  assert.equal((html.match(/data-rule-index=/g)||[]).length,3);
  for(const text of ['触发事件','附加条件','处理结果','执行次数（从 1 开始）≤2','执行次数（从 1 开始）≥3','重试“训练模型”任务','同一 Task 的下一次执行','兜底节点“运行修复”','batch','&lt;check&gt;','收到自定义报告'])assert.ok(html.includes(text),text);
  assert.ok(html.indexOf('≤2')<html.indexOf('规则 2'));
  assert.equal(JSON.stringify(ctx.ruleConfig),before);
  assert.match(run('transitionTaskAction(ruleConfig,ruleConfig.lifecycle.transitions[2],{taskLabel:"训练模型",fallback:null})'),/当前未配置兜底 Agent/);
});
test('false and unknown conditions remain explicit, and the legend includes only actual rule categories',()=>{
  assert.match(run('transitionConditionHTML({when:false})'),/始终不成立/);
  assert.doesNotMatch(run('transitionConditionHTML({when:false})'),/未另加判断条件/);
  assert.match(run('transitionConditionHTML({when:{op:"unknown",args:["<value>"]}})'),/unknown/);
  assert.match(run('transitionConditionHTML({when:{op:"unknown",args:["<value>"]}})'),/&lt;value&gt;/);
  assert.match(run('transitionConditionHTML({})'),/收到上述事件后/);
  const html=run('lifecycleDiagram({kind:"command",lifecycle:{initial:"executing",transitions:[{from:"executing",event:"completed",to:"completed"},{from:"executing",event:"failed",to:"fault"}]}})');
  const legend=html.split('<div class="lifecycle-diagram')[0];
  assert.doesNotMatch(legend,/重试|Agent 处理|自定义转移/);
});
test('scheduling another task at the same node is an outgoing relation, not an execution-state retry',()=>{
  ctx.sameNode={loop_definition:{schema_version:2,nodes:{work:{plan_nodes:['work']}},plans:{}},implementations:{}};
  const html=run('nodeStateHTML(sameNode,"work")');
  const internal=html.split('<section class="state-internal"')[1].split('<section class="state-direction"')[0];
  assert.doesNotMatch(internal,/创建新 Task/);
  assert.match(html,/转出关系 · 1/);assert.match(html,/再次安排同一节点，创建新 Task/);
});


test('target filtering gathers every source state and scopes the matrix, counts and legend to its own view',()=>{
  const groups=[['agent',2,'agent'],['retry',1,'retry'],['agent',1,'agent'],['fault',1,'failure'],['completed',1,'normal']].map(([to,count,tones])=>({dataset:{lifecycleGroupTo:to,ruleCount:String(count),ruleTones:tones},hidden:false}));
  const phases=[groups.slice(0,2),groups.slice(2,4),groups.slice(4)].map(items=>({hidden:false,querySelectorAll:()=>items}));
  const rows=['agent','agent','retry','agent','fault','completed'].map(to=>({dataset:{lifecycleRowTo:to},hidden:false}));
  const extras=['retry','agent'].map(to=>({dataset:{lifecycleExtraTarget:to},hidden:false}));
  const legend=['agent','retry','failure','normal'].map(tone=>({dataset:{lifecycleTone:tone},hidden:false}));
  const count={},matrixCount={};
  const matrix={querySelectorAll:selector=>selector==='[data-lifecycle-row-to]'?rows:extras,querySelector:()=>matrixCount};
  ctx.filterRoot={dataset:{totalRules:'6'},querySelectorAll:selector=>selector==='[data-lifecycle-group-to]'?groups:selector==='[data-lifecycle-tone]'?legend:phases,querySelector:()=>count,closest:()=>matrix};
  run('filterLifecycleTargets(filterRoot,"agent")');
  assert.deepEqual(groups.map(g=>g.hidden),[false,true,false,true,true]);
  assert.deepEqual(phases.map(p=>p.hidden),[false,false,true]);
  assert.equal(rows.filter(r=>!r.hidden).length,3);assert.equal(matrixCount.textContent,'3 / 6');
  assert.equal(count.textContent,'显示 3 / 6 条规则 · 2 组');
  assert.deepEqual(legend.filter(l=>!l.hidden).map(l=>l.dataset.lifecycleTone),['agent']);
  assert.deepEqual(extras.map(e=>e.hidden),[true,false]);
  run('filterLifecycleTargets(filterRoot,"")');
  assert.ok([...groups,...phases,...rows,...extras,...legend].every(e=>!e.hidden));
  assert.equal(matrixCount.textContent,'6');assert.equal(count.textContent,'显示 6 / 6 条规则 · 5 组');
});
