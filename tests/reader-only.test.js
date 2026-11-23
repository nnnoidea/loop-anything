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
    editSelection:{node:'init'},activeRoute:{},implementationOptions:entry=>entry||{},
    defaultImplementation:()=> 'manual',nodeSignalsHTML:()=>'',kindNames:{command:'脚本'},
    esc:value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;'),pretty:value=>JSON.stringify(value)});
  const app=fs.readFileSync('loop_anything/web/app.js','utf8');
  vm.runInContext(app.slice(app.indexOf('function nodePurposeHTML('),app.indexOf('const randomKey')),ctx);
  const source=fs.readFileSync('loop_anything/web/authoring.js','utf8');
  vm.runInContext(source,ctx);
  vm.runInContext('renderAuthorProperties()',ctx);
  const html=field('editor-properties').innerHTML;
  assert.ok(html.indexOf('职责与目的') < html.indexOf('输入契约'));
  assert.match(html,/准备本轮工作。/);
  assert.doesNotMatch(html.split('<h3>执行说明与 Skill</h3>')[0],/执行指令/);
  assert.match(html,/<details class="reader-detail" ><summary>给执行者的说明<\/summary><pre>完整 &lt;执行指令&gt;<\/pre>/);
  assert.match(html,/完整方法/);assert.match(html,/完整节点定义/);
  ctx.editor.implementations.init={manual:{kind:'command',label:'执行方案'}};
  ctx.activeRoute.implementation='manual';
  vm.runInContext('renderAuthorProperties()',ctx);
  assert.match(field('editor-properties').innerHTML,/职责与目的[\s\S]+准备本轮工作。/);
  assert.match(field('editor-properties').innerHTML,/执行方案/);
  delete ctx.activeRoute.implementation;
  delete ctx.editor.implementations.init;
  delete node.description;
  vm.runInContext('renderAuthorProperties()',ctx);
  assert.doesNotMatch(field('editor-properties').innerHTML,/职责与目的|尚未填写/);
  assert.match(field('editor-properties').innerHTML,/完整 &lt;执行指令&gt;/);
});

test('browser shows startup requirements without selecting or launching another Agent',async()=>{
  const fields=new Map(),calls=[],copies=[];
  const field=id=>{if(!fields.has(id))fields.set(id,{value:'',innerHTML:'',textContent:'',disabled:false,addEventListener(){},showModal(){},close(){}});return fields.get(id);};
  const ctx=vm.createContext({catalog:[{key:'pkg-one',package_key:'pkg-one',loop_definition:{id:'one',name:'One',defaults:{n:1}}}],$:field,esc:String,readerJSON:(_,value)=>JSON.stringify(value),document:{addEventListener(){}},
    navigator:{clipboard:{writeText:async text=>copies.push(text)}},toast(){},
    platformCall:async(name,payload)=>{calls.push(name);return {path:'/config.json',config:{inputs:{n:2}}};}});
  vm.runInContext(fs.readFileSync('loop_anything/web/launch.js','utf8'),ctx);
  await vm.runInContext('openCreate("pkg-one")',ctx);
  assert.deepEqual(calls,['read_loop_config']);
  assert.match(field('launch-summary').innerHTML,/"n":2/);
  assert.match(field('launch-summary').innerHTML,/当前 Agent/);
  field('launch-instruction').textContent='Start pkg-one in current session';
  await vm.runInContext('startConfiguredRun()',ctx);
  assert.deepEqual(copies,['Start pkg-one in current session']);
  assert.deepEqual(calls,['read_loop_config']);
});

test('package dialog uses the existing definition without a schema-number gate',()=>{
  const fields=new Map();let rendered=false,opened=false;
  const field=id=>{if(!fields.has(id))fields.set(id,{});return fields.get(id);};
  const editor={loop_definition:{schema_version:1,nodes:{}}};
  const ctx=vm.createContext({editor,$:field,uploadedPackage:{},renderPackageAssets(){rendered=true;},packageDialog:{showModal(){opened=true;}}});
  const code=fs.readFileSync('loop_anything/web/packages.js','utf8');
  vm.runInContext(code.slice(code.indexOf('function showPackage('),code.indexOf('function renderPackageAssets(')),ctx);
  vm.runInContext('showPackage(true)',ctx);
  assert.equal(rendered,true);assert.equal(opened,true);
  assert.equal(field('package-author').hidden,false);
  assert.equal(editor.loop_definition.schema_version,1);
});
