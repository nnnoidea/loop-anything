'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('loop_anything/web/work.js','utf8');
function context(extra={}){
  const fields=new Map();
  const field=id=>{if(!fields.has(id))fields.set(id,{innerHTML:'',textContent:'',querySelectorAll(){return [];},insertAdjacentHTML(_,value){this.innerHTML+=value;},remove(){fields.delete(id);}});return fields.get(id);};
  const ctx=vm.createContext({document:{addEventListener(){}},$:field,page:'timelines',activeRoute:{type:'timelines'},
    esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    runDate:v=>String(v),routeHash:r=>'#'+r.type+'/'+encodeURIComponent(r.id||''),badge:s=>`<span>${s}</span>`,readerJSON:()=>'',...extra});
  vm.runInContext(source,ctx);return {ctx,field};
}
test('Timeline groups show Loop counts and temporary work without eagerly rendering cards',async()=>{
  const {ctx,field}=context({platformCall:async()=>({groups:[{loop_id:'research',name:'<Research>',count:28},{loop_id:null,name:'临时工作',count:3}],timelines:[]})});
  await vm.runInContext('showWorkLibrary()',ctx);
  assert.match(field('timelines-list').innerHTML,/28 条 Timeline/);
  assert.match(field('timelines-list').innerHTML,/临时工作/);
  assert.match(field('timelines-list').innerHTML,/&lt;Research>/);
  assert.doesNotMatch(field('timelines-list').innerHTML,/class="timeline-card"/);
  ctx.platformCall=async()=>({groups:[],timelines:[]});await vm.runInContext('showWorkLibrary()',ctx);
  assert.match(field('timelines-list').innerHTML,/从一件想做的事开始/);
});
test('expanded group requests only its page and keeps escaped Timeline links',async()=>{
  const calls=[],body={innerHTML:''};
  const element={dataset:{timelineGroup:'null'},isConnected:true,querySelector:()=>body};
  const {ctx}=context({element,platformCall:async(name,args)=>{calls.push(args);return {total:25,timelines:[{id:'t1',title:'<script>unsafe</script>',objective:'Goal',created_at:1}],next_offset:24};}});
  await vm.runInContext('loadTimelineGroup(element,12)',ctx);
  assert.equal(calls[0].unbound,true);assert.equal(calls[0].offset,12);assert.equal(calls[0].limit,12);
  assert.equal(calls[0].loop_id,undefined);
  assert.match(body.innerHTML,/href="#timeline\/t1" data-route-link/);
  assert.match(body.innerHTML,/&lt;script>/);assert.doesNotMatch(body.innerHTML,/<script>/);
  assert.match(body.innerHTML,/data-timeline-page="24"/);
  element.dataset.timelineGroup='"research"';await vm.runInContext('loadTimelineGroup(element,0)',ctx);
  assert.equal(calls[1].loop_id,'research');assert.equal(calls[1].unbound,undefined);
});
test('late Timeline read cannot replace a newer page',async()=>{
  let resolve;const {ctx,field}=context({platformCall:()=>new Promise(r=>resolve=r)});
  const reading=vm.runInContext('showWorkLibrary()',ctx);
  ctx.page='monitors';field('timelines-list').innerHTML='new page';resolve({timelines:[]});await reading;
  assert.equal(field('timelines-list').innerHTML,'new page');
});
test('Timeline detail links to the existing Run and exposes continuation only when supplied',async()=>{
  const {ctx,field}=context({page:'timeline',activeRoute:{type:'timeline',id:'t1'},platformCall:async()=>({timeline:{title:'Work',objective:'Goal',constraints:'Limits'},runs:[{id:'run1',title:'Result',status:'paused'}],entries:[{at:1,kind:'progress',text:'My <progress>'}],has_more:true,cursor:100})});
  await vm.runInContext("showWorkTimeline('t1')",ctx);
  assert.match(field('timeline-content').innerHTML,/href="#run\/run1" data-route-link/);
  assert.match(field('timeline-content').innerHTML,/My &lt;progress>/);
  assert.match(field('work-entries').innerHTML,/data-after="100"/);
});
test('Timeline file preview escapes content and import retries keep the same request',async()=>{
  const calls=[],routes=[],document={format:'loop-anything-timeline',timeline:{title:'<Imported>',objective:'Continue research'},state:[],results:[],entries:[]};
  const {ctx,field}=context({randomKey:()=> 'same-request',file:{size:100,text:async()=>JSON.stringify(document)},
    navigateTo:async r=>routes.push(r),toast:()=>{},platformCall:async(name,args)=>{calls.push({name,args});if(calls.length===1)throw new Error('temporary failure');return {timeline:{id:'local-copy'}};}});
  field('timeline-import-dialog').close=()=>{};
  await vm.runInContext('selectTimelineFile(file)',ctx);
  assert.match(field('timeline-import-preview').innerHTML,/&lt;Imported>/);
  assert.equal(field('timeline-import-confirm').disabled,false);
  await vm.runInContext('importSelectedTimeline()',ctx);
  assert.equal(field('timeline-import-error').hidden,false);
  await vm.runInContext('importSelectedTimeline()',ctx);
  assert.equal(calls[0].args.request_id,calls[1].args.request_id);
  assert.equal(routes[0].id,'local-copy');
});
test('invalid files do not enable import; delayed file reads cannot overwrite a newer choice',async()=>{
  let resolve;const {ctx,field}=context({randomKey:()=> 'key',oldFile:{size:10,text:()=>new Promise(r=>resolve=r)},badFile:{size:10,text:async()=>'{broken'}});
  const pending=vm.runInContext('selectTimelineFile(oldFile)',ctx);
  await vm.runInContext('selectTimelineFile(badFile)',ctx);
  resolve(JSON.stringify({format:'loop-anything-timeline',timeline:{},state:[],results:[],entries:[]}));await pending;
  assert.equal(field('timeline-import-confirm').disabled,true);
  assert.equal(field('timeline-import-preview').hidden,true);
});
test('import source stays a progress notice without execution snapshots',()=>{
  const {ctx}=context();
  const html=vm.runInContext("importSourceHTML({timeline:{import_source:{exported_at:1}}})",ctx);
  assert.match(html,/Timeline/);assert.doesNotMatch(html,/#run\//);
  assert.doesNotMatch(html,/timeline-carried/);
});
test('imported saved results are readable through the Timeline without a source Run link',()=>{
  const {ctx}=context();
  const html=vm.runInContext("savedResultsHTML({timeline:{import_source:{}},results:{records:[{id:'a<1',type:'score',revision:2}],complete:true}},'local')",ctx);
  assert.match(html,/已保存结果/);assert.match(html,/data-result-timeline="local"/);assert.match(html,/data-work-result="a&lt;1"/);assert.doesNotMatch(html,/#run\//);
});
