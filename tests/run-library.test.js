'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync('loop_anything/web/run_library.js','utf8');
function context(extra={}){
  return vm.createContext({Date,URLSearchParams,selected:null,labels:{running:'运行中'},
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
  assert.deepEqual(calls.map(c=>c[0]),['read_loop','packages/read']);
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

test('Loop-related pagination stays on the selected page when auto-refreshing',async()=>{
  const offsets=[];let now=10000;
  const Clock=class extends Date {static now(){return now;}};
  const ctx=context({Date:Clock,page:'runs',api:async url=>{
    const offset=Number(new URL('http://local/'+url).searchParams.get('offset'));offsets.push(offset);
    return {runs:[],total:60,offset,next_offset:offset+20<60?offset+20:null};
  }});
  vm.runInContext(code.slice(0,code.indexOf('let runFilterTimer')),ctx);
  await vm.runInContext('refreshRelatedRuns("loop",20,true)',ctx);
  now+=6000;await vm.runInContext('refreshRelatedRuns("loop")',ctx);
  assert.deepEqual(offsets,[20,20]);
});

test('related history groups people, preserves disclosure on refresh and handles empty pages',()=>{
  const group={dataset:{relatedPerson:'tdh'},open:false};let writes=0;
  const container={dataset:{},querySelectorAll:()=>[group],set innerHTML(value){this.html=value;writes++;group.open=true;}};
  const ctx=context({$:()=>container,routeHash:r=>'#run/'+encodeURIComponent(r.id),badge:s=>'<span>'+s+'</span>'});
  vm.runInContext(code.slice(0,code.indexOf('let runFilterTimer')),ctx);
  ctx.data={runs:[{id:'r/1',title:'<unsafe>',status:'paused',created_by:'tdh',created_at:10,last_activity_at:20},
    {id:'two',title:'Child',status:'paused',created_by:'',parent_run_id:'r/1',archived_at:30}],groups:[{created_by:'tdh',count:9}],total:11,offset:0,next_offset:2};
  vm.runInContext('relatedRunPages.set("loop",{data}); renderRelatedRuns("loop")',ctx);
  assert.match(container.html,/data-related-person="tdh"/);assert.match(container.html,/未署名/);
  assert.match(container.html,/本页 1 \/ 共 9/);assert.match(container.html,/#run\/r%2F1/);
  assert.match(container.html,/&lt;unsafe>/);assert.doesNotMatch(container.html,/<unsafe>/);
  assert.match(container.html,/子 Run/);assert.match(container.html,/已归档/);assert.match(container.html,/最近活跃/);
  assert.equal(group.open,false);
  vm.runInContext('renderRelatedRuns("loop")',ctx);assert.equal(writes,1);
  ctx.data={runs:[],groups:[],total:0,offset:0,next_offset:null};
  vm.runInContext('relatedRunPages.set("loop",{data}); renderRelatedRuns("loop")',ctx);
  assert.match(container.html,/还没有运行记录/);assert.doesNotMatch(container.html,/data-related-page/);
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
  assert.deepEqual(offsets,[30,0]);assert.equal(field('runs-page').textContent,'1–2 / 2');
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
