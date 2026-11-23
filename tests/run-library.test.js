'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync('loop_anything/web/run_library.js','utf8');
function context(extra={}){
  return vm.createContext({Date,URLSearchParams,selected:null,labels:{running:'运行中'},badge:status=>`<span>${status}</span>`,
    esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    ...extra});
}
test('human groups render escaped summaries and explicit parent links without transcripts',()=>{
  const ctx=context();vm.runInContext(code.slice(0,code.indexOf('async function refreshRunLibrary')),ctx);
  ctx.rows=[{id:'one',title:'<unsafe>',created_by:'tdh',status:'running',created_at:10,last_activity_at:20,child_count:2},
    {id:'two',title:'Unsigned',created_by:'',status:'running',created_at:11,last_activity_at:21,child_count:0}];
  const html=vm.runInContext('groupedRunsHTML(rows,[{created_by:"tdh",count:90}])',ctx);
  assert.match(html,/data-run-person="tdh"/);assert.match(html,/本页 1 \/ 共 90/);assert.match(html,/未署名/);
  assert.match(html,/&lt;unsafe>/);assert.doesNotMatch(html,/<unsafe>/);
  assert.match(html,/data-run-children="one"/);assert.match(html,/子 Run · 2/);
});
test('filters preserve unsigned users, separate date ranges, and use exclusive next-day upper bounds',()=>{
  const fields={'runs-person':'','runs-sort':'last_activity_at','runs-order':'desc','runs-archived':'only',
    'runs-query':'compare','runs-status':'','runs-loop':'research','runs-kind':'workflow',
    'runs-created-from':'2026-11-01','runs-created-to':'2026-11-09','runs-active-from':'2026-11-08','runs-active-to':''};
  const ctx=context({$:id=>({value:fields[id]})});vm.runInContext(code.slice(0,code.indexOf('function runSummaryHTML')),ctx);
  const args=JSON.parse(JSON.stringify(vm.runInContext('runFilters()',ctx)));
  assert.equal(args.created_by,'');assert.equal(args.root_only,false);assert.equal(args.archived,'only');
  assert.equal(new Date(args.created_to*1000).getDate(),10);assert.ok(args.active_from>args.created_from);
  assert.equal(args.loop_id,'research');assert.equal(args.offset,0);assert.equal(args.limit,30);
});
test('archived Loop remains readable from its Run even when hidden from catalog',async()=>{
  const calls=[],loop={key:'pkg-archived',package_key:'pkg-archived',loop_definition:{nodes:{}},implementations:{}};
  const ctx=context({catalog:[],platformCall:async(name,args)=>{calls.push([name,args]);return {loop};},api:async(name,args)=>{calls.push([name,args]);return {document:{checks:{}},assets:[]};}});
  const editor=fs.readFileSync('loop_anything/web/editor.js','utf8');
  vm.runInContext(editor.slice(editor.indexOf('async function loadReader('),editor.indexOf('function readerIdentity(')),ctx);
  const result=await vm.runInContext('loadReader("pkg-archived")',ctx);
  assert.equal(calls[0][1].key,'pkg-archived');assert.equal(result.installedKey,'pkg-archived');
  assert.deepEqual(calls.map(c=>c[0]),['read_loop','packages/read','read_loop_models']);
});

test('specific Loop, status, person and date filters include matching children',()=>{
  const fields={'runs-person':'*','runs-sort':'last_activity_at','runs-order':'desc','runs-archived':'exclude',
    'runs-query':'','runs-status':'','runs-loop':'','runs-kind':'',
    'runs-created-from':'','runs-created-to':'','runs-active-from':'','runs-active-to':''};
  const ctx=context({$:id=>({value:fields[id]})});vm.runInContext(code.slice(0,code.indexOf('function runSummaryHTML')),ctx);
  assert.equal(vm.runInContext('runFilters().root_only',ctx),true);
  for(const [key,value] of [['runs-loop','child-loop'],['runs-status','running'],['runs-person','tdh'],['runs-created-from','2026-11-01'],['runs-archived','only']]){
    const before=fields[key];fields[key]=value;
    assert.equal(vm.runInContext('runFilters().root_only',ctx),false,key);
    fields[key]=before;
  }
});

test('a shrinking result set returns to a valid page and archived Loops remain filterable',async()=>{
  const values={'runs-person':'*','runs-sort':'last_activity_at','runs-order':'desc','runs-archived':'exclude','runs-query':'','runs-status':'','runs-loop':'','runs-kind':'','runs-created-from':'','runs-created-to':'','runs-active-from':'','runs-active-to':''};
  const fields=new Map(),offsets=[];
  const field=id=>{if(!fields.has(id))fields.set(id,{value:values[id]??'',innerHTML:'',textContent:'',querySelectorAll:()=>[]});return fields.get(id);};
  const ctx=context({$:field,catalog:[],runs:[],listSignature:'',api:async url=>{
    const offset=Number(new URL('http://local/'+url).searchParams.get('offset'));offsets.push(offset);
    return {total:2,offset,next_offset:null,groups:[{created_by:'tdh',count:2}],loops:[{loop_id:'archived-loop',name:'Archived project'}],
      runs:offset?[]:[{id:'one',title:'One',created_by:'tdh'},{id:'two',title:'Two',created_by:'tdh'}]};
  }});
  vm.runInContext(code.slice(0,code.indexOf('let runFilterTimer')),ctx);
  await vm.runInContext('runOffset=30; refreshRunLibrary()',ctx);
  assert.deepEqual(offsets,[30,0]);assert.equal(field('runs-page-number').textContent,'1–2 / 2');
  assert.match(field('runs-loop').innerHTML,/archived-loop/);
});

test('open child lists refresh their current page without cancelling pending navigation',async()=>{
  const offsets=[];let complete;
  const container={dataset:{},innerHTML:'',querySelectorAll:()=>[]};
  const element={isConnected:true,dataset:{runChildren:'parent'},querySelector:()=>container};
  const ctx=context({element,api:url=>{
    offsets.push(Number(new URL('http://local/'+url).searchParams.get('offset')));
    return new Promise(resolve=>complete=resolve);
  }});
  vm.runInContext(code.slice(0,code.indexOf('let runFilterTimer')),ctx);
  const pending=vm.runInContext('showRunChildren(element,20)',ctx);
  await vm.runInContext('showRunChildren(element)',ctx);
  assert.deepEqual(offsets,[20]);
  complete({runs:[{id:'child',title:'Finished child',status:'completed'}],total:21,next_offset:null});await pending;
  assert.match(container.innerHTML,/Finished child/);assert.equal(element.dataset.childOffset,'20');
  const refresh=vm.runInContext('showRunChildren(element)',ctx);
  complete({runs:[{id:'child',title:'Updated child',status:'completed'}],total:21,next_offset:null});await refresh;
  assert.deepEqual(offsets,[20,20]);assert.match(container.innerHTML,/Updated child/);
});
test('Run roles follow the Timeline selection across pause, completion and continuation',()=>{
  const ctx=context();vm.runInContext(code.slice(0,code.indexOf('async function refreshRunLibrary')),ctx);
  const html=(id,status)=>vm.runInContext('runSummaryHTML(row)',Object.assign(ctx,{row:{id,status,title:'核对',timeline_id:'work',active_run_id:'new'}}));
  assert.match(html('new','paused'),/当前 Run/);
  assert.match(html('new','completed'),/最近一次 Run/);
  assert.match(html('old','continued'),/历史 Run/);
});
