const {test}=require('node:test');
const assert=require('node:assert/strict');
const history=require('../loop_anything/web/task_history.js');
test('history uses real start order, groups explicit rounds and follows actual record versions',()=>{
  const run={tasks:{late:{id:'late',created_at:1,status:'completed',execution_id:'late-e',spec:{node:'n',round:'第2轮',inputs:{x:{record:'r'}},outputs:{}}},early:{id:'early',created_at:2,status:'completed',execution_id:'early-e',spec:{node:'n',round:'第1轮',inputs:{},outputs:{x:{id:'r'}}}},pending:{id:'pending',created_at:0,status:'planned',spec:{node:'n',inputs:{x:{record:'r'}},outputs:{}}}},executions:[{id:'late-e',task_id:'late',created_at:5,started_at:20,completed_at:21,sources:{x:{record:'r',revision:1,execution:'early-e'}}},{id:'early-e',task_id:'early',created_at:10,started_at:11,completed_at:11,sources:{}}],records:{r:[{revision:1,tasks:'early',producer:'early-e'}]}};
  assert.equal(history.startTime({created_at:1,started_at:null}),null);
  assert.equal(history.startTime({created_at:1}),1);
  const before=JSON.stringify(run),rows=history.rows(run);
  assert.deepEqual(rows.map(r=>r.tasks.id),['early','late','pending']);
  assert.deepEqual(rows[1].dependencies,['early']);
  assert.deepEqual(rows[2].dependencies,['early']);
  assert.deepEqual(history.groups(rows).map(g=>g.round),['第1轮','第2轮',null]);
  assert.equal(JSON.stringify(run),before);
});
