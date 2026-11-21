'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('loop_anything/web/spaces.js','utf8');
function fixture(config){
  const elements=new Map(),calls=[];
  function el(id){
    if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',querySelector:el,replaceChildren(){this.innerHTML='';}});
    return elements.get(id);
  }
  const ctx=vm.createContext({window:{addEventListener(){}},esc:String,$:el,config,toast(){},
    api:async(path,body)=>{calls.push(body);return {configuration:{...config,...body.change,revision:2}};}});
  vm.runInContext(source+';personalSettings(config)',ctx);
  return {el,calls};
}
test('remote address and launch preference are saved independently',async()=>{
  const {el,calls}=fixture({local_url:'http://localhost:8876',team_url:null,team_web_url:null,default_space:'local',revision:1});
  const event=id=>({currentTarget:el(id),preventDefault(){}});
  el('space-team-url').value='https://team.example';
  el('spaces-form').onsubmit(event('spaces-form'));await Promise.resolve();
  assert.deepEqual({...calls[0].change},{team_url:'https://team.example'});
  el('space-default').value='team';
  await el('default-platform-form').onsubmit(event('default-platform-form'));
  assert.deepEqual({...calls[1].change},{default_space:'team'});
});
test('personal controls belong only to the local settings page',()=>{
  assert.equal(fixture(null).el('settings-personal').innerHTML,'');
  const {el}=fixture({default_space:'auto',revision:1});
  assert(!el('settings-personal').innerHTML.match(/href=|<dialog/));
  assert(el('space-web-field').hidden);
  el('space-team-url').value='nas:///team';el('space-team-url').oninput();
  assert(!el('space-web-field').hidden);
});
