'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('loop_anything/web/spaces.js','utf8');
function context(){
 const elements=new Map();
 const ctx=vm.createContext({document:{createElement:()=>({}),body:{append(){}}},window:{addEventListener(){}},esc:String,$:id=>{if(!elements.has(id))elements.set(id,{});return elements.get(id);}});
 vm.runInContext(source,ctx);return ctx;
}
test('automatic selection follows recorded addresses and an explicit preference wins',()=>{
 const ctx=context();
 for(const [local,team,preference,expected] of [[null,null,'auto',null],['http://127.0.0.1:8767',null,'auto','local'],[null,'https://team.example','auto','team'],['http://127.0.0.1:8767','https://team.example','auto','team'],['http://127.0.0.1:8767','https://team.example','local','local']]){
  ctx.config={local_url:local,team_url:team,default_space:preference};
  assert.equal(vm.runInContext('selectedSpace(config)',ctx),expected);
 }
});
test('platform settings configure addresses without links that navigate between pages',()=>{
 const ctx=context();
 for(const configuration of [null,{local_url:'http://127.0.0.1:8767',team_url:'https://team.example',team_web_url:null,default_space:'auto'}]){
  ctx.settings={configuration};
  const html=vm.runInContext('spaceSettings=settings;renderSpaces();spaceDialog.innerHTML',ctx);
  assert(!/<a\b|href=/.test(html));
  assert.equal(html.includes('id="spaces-form"'),configuration!==null);
  if(configuration){assert(html.includes('value="https://team.example"'));assert(html.includes('当前默认：团队平台'));}
 }
});
