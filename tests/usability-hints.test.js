'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ctx=vm.createContext({esc:v=>String(v??'').replaceAll('"','&quot;')});
function load(file,begin,end){const text=fs.readFileSync('loop_anything/web/'+file,'utf8');vm.runInContext(text.slice(text.indexOf(begin),text.indexOf(end,text.indexOf(begin))),ctx);}
load('settings.js','function runIdleHint(','function runTaskLink(');
load('communication.js','function groupNotificationSummary(','async function editGroupNotifications(');
const run=code=>vm.runInContext(code,ctx);
test('Run completion hint never mistakes waiting, active ownership or a configured rule for idle',()=>{
  ctx.value={status:'running',settings:{},tasks:{a:{status:'completed'}}};
  assert.match(run('runIdleHint(value)'),/没有自动结束规则/);
  for(const status of ['waiting','decision','fault','retrying']){
    ctx.value.tasks.a.status=status;assert.equal(run('runIdleHint(value)'),'');
  }
  ctx.value.tasks.a.status='completed';ctx.value.agent_sessions=[{}];assert.equal(run('runIdleHint(value)'),'');
  ctx.value.agent_sessions=[];ctx.value.settings.completion_rule={eq:[1,1]};assert.equal(run('runIdleHint(value)'),'');
  ctx.value.settings.completion_rule=false;assert.equal(run('runIdleHint(value)'),'');
  ctx.value.settings={};ctx.value.tasks={};assert.equal(run('runIdleHint(value)'),'');
});
test('pending Run issues describe recorded actions without showing Agent instructions',()=>{
  ctx.value={status:'running',tasks:{a:{id:'a',status:'decision',execution_id:'e'},b:{id:'b',status:'blocked'}},
    executions:[{id:'e',implementation:{kind:'agent'}}],agent_tasks:{items:[{kind:'task',task_id:'a',reason:'raw instructions'}]}};
  assert.equal(run('runAttentionItems(value).length'),1);
  assert.equal(run('runAttentionItems(value)[0].label'),'等待 Agent');
  assert.doesNotMatch(run('JSON.stringify(runAttentionItems(value))'),/raw instructions/);
  ctx.value.executions[0].worker_active=true;
  assert.equal(run('runAttentionItems(value).length'),0);
});
test('the pending list shows the recorded user action even for a deferred failure',()=>{
  const note='请确认第七轮预算上限。';
  ctx.value={status:'running',tasks:{a:{id:'a',status:'fault'}},executions:[],task_dispositions:{a:{reason:note}}};
  const [issue]=run('runAttentionItems(value)');
  assert.equal(issue.label,'等待用户处理');
  assert.equal(issue.note,note);
  assert.equal(issue.task_id,'a');
});
test('missing fixed notification bindings do not claim original-chat replies are unavailable',()=>{
  assert.match(run('groupNotificationSummary({})'),/原会话通知/);
  assert.doesNotMatch(run('groupNotificationSummary({})'),/通信仅保留平台记录/);
  assert.match(run("groupNotificationSummary({x:{enabled:true,sender_name:'机器',route:'通知'}})"),/无原聊天来源时/);
});
test('the Run summary only links to currently running nodes',()=>{
  load('workspace.js','function runningNodesHTML(','function taskCard(');
  const nodes={},tasks={},executions=[];
  for(const [id,status,attempt] of [
    ['local','executing',{}],
    ['live-agent','decision',{worker_active:'worker'}],
    ['prediction','waiting',{implementation:{kind:'external'},activity_progress:{external_status:'STARTED'}}],
    ['child','waiting',{implementation:{kind:'loop'},child_status:'running'}],
    ['external-queued','waiting',{implementation:{kind:'external'},activity_progress:{external_status:'QUEUED'}}],
    ['external-poll','executing',{implementation:{kind:'external'},activity_progress:{classification:'resource_wait'}}],
    ['external-unknown','waiting',{implementation:{kind:'external'},activity_progress:{external_status:'RUNNING'},observation_error:true}],
    ['agent-idle','decision',{}],['event','waiting',{implementation:{kind:'event'}}],
    ['failure','fault',{}],['later','planned',{}],['done','completed',{}],
  ]){
    tasks[id]={id,status,execution_id:id,spec:{node:id}};
    nodes[id]={label:id};
    executions.push({id,...attempt});
  }
  Object.assign(ctx,{routeHash:r=>`#run/${r.id}/task/${r.task}`,value:{id:'r',status:'running',tasks,executions,loop_definition:{nodes}}});
  const markup=run('runningNodesHTML(value)');
  assert.deepEqual([...markup.matchAll(/href="#run\/r\/task\/([^"]+)"/g)].map(m=>m[1]),['local','live-agent','prediction','child']);
  assert.match(markup,/href="#run\/r\/task\/prediction"/);
  ctx.value.status='completed';
  assert.equal(run('runningNodesHTML(value)'),'');
});
