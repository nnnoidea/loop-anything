'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ctx=vm.createContext({esc:v=>String(v??'').replaceAll('"','&quot;')});
function load(file,begin,end){const text=fs.readFileSync('loop_anything/web/'+file,'utf8');vm.runInContext(text.slice(text.indexOf(begin),text.indexOf(end,text.indexOf(begin))),ctx);}
load('settings.js','function runIdleHint(','function renderV2Inspect(');
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
test('missing fixed notification bindings do not claim original-chat replies are unavailable',()=>{
  assert.match(run('groupNotificationSummary({})'),/原会话通知/);
  assert.doesNotMatch(run('groupNotificationSummary({})'),/通信仅保留平台记录/);
  assert.match(run("groupNotificationSummary({x:{enabled:true,sender_name:'机器',route:'通知'}})"),/无原聊天来源时/);
});
