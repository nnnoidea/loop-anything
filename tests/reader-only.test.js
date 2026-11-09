'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

test('installed Loop reading loads existing assets and never creates or changes a draft',async()=>{
  const calls=[],loop={key:'pkg-one',package_key:'pkg-one',loop_definition:{nodes:{}},implementations:{}},assets=[{path:'docs/flow.html',base64:'Zmxvdw=='}];
  const ctx=vm.createContext({catalog:[loop],platformCall:async(tool,args)=>{calls.push([tool,args]);return {loop};},api:async(path,args)=>{calls.push([path,args]);return {document:{checks:{}},assets};}});
  const source=fs.readFileSync('loop_anything/web/editor.js','utf8');
  vm.runInContext(source.slice(source.indexOf('async function loadReader('),source.indexOf('function readerIdentity(')),ctx);
  const value=await vm.runInContext('loadReader("pkg-one")',ctx);
  assert.equal(value.installedKey,'pkg-one');assert.equal(value.assets,assets);
  assert.deepEqual(calls.map(c=>c[0]),['read_loop','packages/read']);
  assert.equal(loop.routeId,undefined);assert.equal(loop.installedKey,undefined);
});

test('node introduction is authored for users while full execution guidance stays expandable',()=>{
  const fields=new Map(),node={label:'Prepare',description:'准备本轮工作。',instructions:'完整 <执行指令>',inputs:{},outputs:{},skills:[{name:'Method',content:'完整方法'}]};
  const field=id=>{if(!fields.has(id))fields.set(id,{});return fields.get(id);};
  const ctx=vm.createContext({$:field,editor:{loop_definition:{nodes:{init:node}},implementations:{}},
    editSelection:{node:'init'},activeRoute:{},implementationOptions:()=>({}),loopRelationships:()=>[],nodeFlowHTML:()=>'',
    esc:value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;'),pretty:value=>JSON.stringify(value)});
  const source=fs.readFileSync('loop_anything/web/authoring.js','utf8');
  vm.runInContext(source.slice(0,source.indexOf('const taskContextDialog')),ctx);
  vm.runInContext('renderAuthorProperties()',ctx);
  const html=field('editor-properties').innerHTML;
  assert.match(html,/节点用途/);assert.match(html,/准备本轮工作。/);
  assert.doesNotMatch(html.split('<h3>执行说明与 Skill</h3>')[0],/执行指令/);
  assert.match(html,/<details class="reader-detail" ><summary>给执行者的说明<\/summary><pre>完整 &lt;执行指令&gt;<\/pre>/);
  assert.match(html,/完整方法/);assert.match(html,/完整节点定义/);
  delete node.description;
  vm.runInContext('renderAuthorProperties()',ctx);
  assert.doesNotMatch(field('editor-properties').innerHTML,/节点用途|尚未填写/);
  assert.match(field('editor-properties').innerHTML,/完整 &lt;执行指令&gt;/);
});

test('viewing startup is read-only; one explicit click starts a configured Run without a web conversation',async()=>{
  const fields=new Map(),calls=[];let resolveStart;
  const field=id=>{if(!fields.has(id))fields.set(id,{innerHTML:'',textContent:'',disabled:false,addEventListener(){},showModal(){},close(){}});return fields.get(id);};
  const ctx=vm.createContext({catalog:[{key:'pkg-one',package_key:'pkg-one',loop_definition:{id:'one',name:'One',defaults:{n:1}}}],$:field,esc:String,readerJSON:(_,value)=>JSON.stringify(value),document:{addEventListener(){}},platformCall:async(name)=>{calls.push(name);return {path:'/config.json',config:{inputs:{n:2}}};},api:(name,payload)=>{calls.push([name,JSON.parse(JSON.stringify(payload))]);return new Promise(resolve=>resolveStart=resolve);},selectRun:async id=>calls.push(['selected',id])});
  vm.runInContext(fs.readFileSync('loop_anything/web/launch.js','utf8'),ctx);
  await vm.runInContext('openCreate("pkg-one")',ctx);
  assert.deepEqual(calls,['read_loop_config']);assert.match(field('launch-summary').innerHTML,/"n":2/);
  assert.doesNotMatch(field('launch-summary').innerHTML,/<input|<textarea|<select|conversation/);
  const first=vm.runInContext('startConfiguredRun()',ctx);await vm.runInContext('startConfiguredRun()',ctx);
  assert.equal(calls.filter(c=>Array.isArray(c)&&c[0]==='runs').length,1);
  assert.deepEqual(Object.keys(calls[1][1]).sort(),['key','title']);
  resolveStart({id:'run-one'});await first;
  assert.deepEqual(calls.at(-1),['selected','run-one']);
});
