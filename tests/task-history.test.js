const {test}=require('node:test');
const assert=require('node:assert/strict');
const history=require('../loop_anything/web/task_history.js');
test('history uses real start order, groups explicit rounds and follows actual record versions',()=>{
  const run={tasks:{late:{id:'late',created_at:1,status:'completed',execution_id:'late-e',spec:{node:'n',round:'第2轮',inputs:{x:{record:'r'}},outputs:{}}},early:{id:'early',created_at:2,status:'completed',execution_id:'early-e',spec:{node:'n',round:'第1轮',inputs:{},outputs:{x:{id:'r'}}}},pending:{id:'pending',created_at:0,status:'planned',spec:{node:'n',inputs:{x:{record:'r'}},outputs:{}}}},executions:[{id:'late-e',task_id:'late',created_at:5,started_at:20,completed_at:21,sources:{x:{record:'r',revision:1,execution:'early-e'}}},{id:'early-e',task_id:'early',created_at:10,started_at:11,completed_at:11,sources:{}}],records:{r:[{revision:1,tasks:'early',producer:'early-e'}]}};
  assert.equal(history.startTime({created_at:1,started_at:null}),null);
  assert.equal(history.startTime({created_at:1}),undefined);
  const before=JSON.stringify(run),rows=history.rows(run);
  assert.deepEqual(rows.map(r=>r.tasks.id),['early','late','pending']);
  assert.deepEqual(rows[1].dependencies,['early']);
  assert.deepEqual(rows[2].dependencies,['early']);
  assert.deepEqual(history.groups(rows).map(g=>g.round),['第1轮','第2轮',null]);
  assert.equal(JSON.stringify(run),before);
});

test('runtime relationships follow recorded creation and fallback evidence, not inferred failure edges',()=>{
 const run={tasks:{a:{id:'a',spec:{outputs:{}},origin:{},status:'fault'},b:{id:'b',spec:{outputs:{}},origin:{agent:'ea'},status:'planned'},f:{id:'f',spec:{outputs:{}},origin:{fallback:true,issues:[{task_id:'a'},{task_id:'a'},{task_id:'missing'}]},status:'ready'},other:{id:'other',spec:{outputs:{}},origin:{},status:'fault'}},executions:[{id:'ea',task_id:'a'}]};
 const items=Object.values(run.tasks).map(tasks=>({tasks,dependencies:[]}));
 const before=JSON.stringify(run),links=history.links(run,items);
 assert.deepEqual(links,[{from:'a',to:'b',kind:'planning'},{from:'a',to:'f',kind:'recovery'}]);
 assert.equal(JSON.stringify(run),before);
});

test('pending collection follows its pinned producer versions, including mixed revisions',()=>{
 const tasks={old:{id:'old',status:'completed',spec:{inputs:{},outputs:{result:{id:'shared'}}}},new:{id:'new',status:'completed',spec:{inputs:{},outputs:{result:{id:'shared',expected_revision:1}}}},other:{id:'other',status:'completed',spec:{inputs:{},outputs:{result:{id:'other',expected_revision:1}}}},review:{id:'review',status:'planned',spec:{inputs:{results:{records:['shared','other'],revisions:[1,2]}},outputs:{}}}};
 const run={tasks,records:{shared:[{revision:1,tasks:'old'},{revision:2,tasks:'new'}],other:[{revision:2,tasks:'other'}]},executions:[]};
 assert.deepEqual(history.rows(run).find(row=>row.tasks.id==='review').dependencies,['old','other']);
});
test('business graph folds only internal decisions into their source and preserves next work',()=>{
  const run={tasks:{a:{id:'a',spec:{node:'work',inputs:{},outputs:{}},origin:{}},d:{id:'d',spec:{node:'$flow_agent',inputs:{},outputs:{}},origin:{flow_agent:{task_id:'a'},execution:'ea'}},b:{id:'b',spec:{node:'work',inputs:{},outputs:{}},origin:{agent:'ed'}}},executions:[{id:'ea',task_id:'a'},{id:'ed',task_id:'d'}]};
  const graph=history.businessGraph(run);
  assert.deepEqual(graph.items.map(i=>i.tasks.id),['a','b']);
  assert.deepEqual(graph.links,[{from:'a',to:'b',kind:'planning'}]);
  assert.equal(history.rows(run).length,3);
});

test('round cards keep live, completed and cancelled tasks in the same row group',()=>{
  const items=[['previous','completed','第 1 轮'],['prepare','completed','第 2 轮'],['train','completed','第 2 轮'],
    ['predict','waiting','第 2 轮'],['failed','fault','第 1 轮'],['cancelled','cancelled','第 2 轮']]
    .map(([id,status,round])=>({tasks:{id,status},round,attempts:[]}));
  const links=[['previous','prepare','dependency'],['previous','train','dependency'],['prepare','train','dependency'],
    ['train','predict','dependency'],['failed','train','recovery'],['train','cancelled','dependency'],
    ['cancelled','predict','dependency']].map(([from,to,kind])=>({from,to,kind}));
  const graph={items,links};
  const collapsed=history.roundGraph(graph,new Set(),null,false);
  const card=collapsed.nodes.find(node=>node.id==='$round:第 2 轮');
  assert.equal(card.card.round,'第 2 轮');
  assert.deepEqual(card.card.members.map(i=>i.tasks.id),['prepare','train','predict','cancelled']);
  assert.equal(collapsed.nodes.filter(node=>node.item).length,0);
  assert.deepEqual(collapsed.links,[
    {from:'$round:第 1 轮',to:card.id,kind:'dependency',tasks:links.slice(0,2)},
    {from:'$round:第 1 轮',to:card.id,kind:'recovery',tasks:[links[4]]},
  ]);
  for(const expanded of [history.roundGraph(graph,new Set(['第 2 轮']),null,false),
    history.roundGraph(graph,new Set(),'cancelled',false),history.roundGraph(graph,new Set(),null,true)]){
    const round=expanded.nodes.find(node=>node.id===card.id).card;
    assert.equal(round.open,true);
    assert.deepEqual(round.members.map(item=>item.tasks.id),['prepare','train','predict','cancelled']);
    assert.deepEqual(round.links,[links[2],links[3],links[5],links[6]]);
    assert.deepEqual(expanded.links,collapsed.links);
  }
});

test('a recorded round stays foldable with a single task',()=>{
  const items=[{tasks:{id:'replacement-review',status:'cancelled'},round:'结果判读',attempts:[{observation_error:true}]},
    {tasks:{id:'score',status:'completed'},round:'对照实验',attempts:[]}];
  const {nodes}=history.roundGraph({items,links:[]},new Set(),null,false);
  assert.equal(nodes[0].card.round,'结果判读');
  assert.equal(nodes[0].card.open,false);
  assert.deepEqual(nodes[0].card.members,[items[0]]);
  assert.equal(nodes[1].card.round,'对照实验');
  assert.deepEqual(nodes[1].card.members,[items[1]]);
});

test('a recorded cross-round decision stays visible once, with all sources and scheduled rounds',()=>{
  const items=[['a1','甲'],['a2','甲'],['b1','乙'],['b2','乙'],['decision','甲'],
    ['c1','丙'],['c2','丙'],['d1','丁'],['d2','丁']]
    .map(([id,round])=>({tasks:{id,status:'completed'},round,attempts:[]}));
  const links=[['a2','decision','dependency'],['b2','decision','dependency'],
    ['decision','c1','planning'],['decision','d1','planning'],['c2','d2','dependency']]
    .map(([from,to,kind])=>({from,to,kind}));
  const graph=history.roundGraph({items,links},new Set(),null,false);
  const decision=graph.nodes.find(node=>node.handoff);
  assert.equal(decision.id,'decision');
  assert.equal(graph.nodes.filter(node=>node.handoff).length,1);
  assert(!graph.nodes.find(node=>node.id==='$round:甲').card.members.some(i=>i.tasks.id===decision.id));
  assert.deepEqual(graph.links.map(({from,to,kind})=>[from,to,kind]),[
    ['$round:甲','decision','dependency'],['$round:乙','decision','dependency'],
    ['decision','$round:丙','planning'],['decision','$round:丁','planning'],
    ['$round:丙','$round:丁','dependency'],
  ]);
});

test('untagged work stays in dependency groups on either side of a handoff',()=>{
  const items=['first','score','alternative','decision','prepare','result','unrelated']
    .map(id=>({tasks:{id,status:'completed'},round:null,attempts:[]}));
  const links=[{from:'first',to:'score',kind:'dependency'},{from:'score',to:'decision',kind:'dependency'},
    {from:'alternative',to:'decision',kind:'dependency'},
    {from:'decision',to:'prepare',kind:'dependency',arranged:true},{from:'prepare',to:'result',kind:'dependency'}];
  const graph=history.roundGraph({items,links},new Set(),null,false);
  assert.deepEqual(graph.nodes.filter(node=>node.card).map(node=>node.card.members.map(i=>i.tasks.id)),
    [['first','score'],['prepare','result']]);
  assert.deepEqual(graph.nodes.filter(node=>node.handoff).map(node=>node.id),['decision']);
  assert(graph.nodes.some(node=>node.id==='unrelated'&&node.item));
  assert(graph.links.some(link=>link.from==='decision'&&link.tasks[0].arranged));
});

test('a declared round keeps the source, parallel proposals and decision together',()=>{
  const items=[['evidence','第 1 轮'],['from-evidence','第 1 轮'],['from-model','第 1 轮'],
    ['decision','第 1 轮'],['experiment','第 2 轮']]
    .map(([id,round])=>({tasks:{id,status:'completed'},round,attempts:[]}));
  const links=[['evidence','from-evidence','planning'],['evidence','from-model','planning'],
    ['from-evidence','decision','dependency'],['from-model','decision','dependency'],
    ['decision','experiment','planning']].map(([from,to,kind])=>({from,to,kind}));
  const graph=history.roundGraph({items,links},new Set(['第 1 轮']),null,false);
  assert.deepEqual(graph.nodes[0].card.members,items.slice(0,4));
  assert.deepEqual(graph.nodes[0].card.links,links.slice(0,4));
  assert.deepEqual(graph.links,[{from:'$round:第 1 轮',to:'$round:第 2 轮',kind:'planning',tasks:[links[4]]}]);
});

test('rows keep recorded parallel inputs and outputs beside each other',()=>{
  const nodes=['a','unrelated','b','decision','c','d','review'].map(id=>({id}));
  const levels=new Map([['a',0],['unrelated',0],['b',0],['decision',1],['c',2],['d',2],['review',3]]);
  const links=[['a','decision','dependency'],['b','decision','dependency'],
    ['decision','c','planning'],['decision','d','planning'],['c','review','dependency'],
    ['d','review','dependency'],['unrelated','decision','recovery']]
    .map(([from,to,kind])=>({from,to,kind}));
  assert.deepEqual(history.parallelRows(nodes,links,levels),[
    ['a','b'],['decision'],['c','d'],['review'],['unrelated'],
  ]);
});
