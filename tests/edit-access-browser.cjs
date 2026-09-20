// Trusted internal sharing: one cookie, real HTTP writes and the existing Agent protocol.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn,execFileSync}=require('node:child_process'),{chromium}=require('playwright');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-edit-access-')),db=path.join(root,'runs.db'),password='test-internal-edit';
 const key=execFileSync('python3',['-c',`import sys
sys.path.insert(0,'tests')
from test_run_agent import definition
from loop_anything.runtime.store import Store
bp,impl=definition();print(Store(sys.argv[1]).publish(bp,impl)['key'])`,db],{encoding:'utf8'}).trim();
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const startServer=(allowSleep=false)=>spawn('python3',['-m','loop_anything','--db',db,'serve','--host','0.0.0.0','--port',String(port),...(allowSleep?['--allow-sleep']:[])],{env:{...process.env,LOOP_ANYTHING_EDIT_PASSWORD:password,PYTHONUNBUFFERED:'1'},stdio:['ignore','pipe','pipe']});
 let server=startServer(true);
 let browser;
 try{
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('startup timeout')),10000);server.stdout.on('data',d=>{if(String(d).includes('workspace:')){clearTimeout(timer);resolve();}});server.on('exit',c=>{clearTimeout(timer);reject(new Error('server exited '+c));});});
  browser=await chromium.launch({headless:true,channel:'chrome',args:['--host-resolver-rules=MAP loop.internal 127.0.0.1','--no-proxy-server']});
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:'+port,site='http://loop.internal:'+port;
  const headers={'X-Loop-Anything':'workspace'};
  const raw=async(route,data,extra={})=>{const response=await context.request.post(base+'/api/'+route,{headers:{...headers,...extra},data});return {status:response.status(),data:await response.json()};};
  const rpc=async(route,data)=>page.evaluate(async({route,data})=>{const r=await fetch('/api/'+route,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Loop-Anything':'workspace'},body:JSON.stringify(data)});return {status:r.status,data:await r.json()};},{route,data});
  await page.goto(site+'/#loop_definitions');await page.locator('#catalog-cards [data-loop]').first().waitFor();
  assert.equal(await page.evaluate(()=>isSecureContext),false);
  assert.equal((await rpc('edit-access')).data.unlocked,false);
  for(const route of ['platform/keep-awake','runs','drafts','publish','packages/install','conversations','conversations/missing/send','runs/missing/command','runs/missing/settings','runs/missing/event','runs/missing/tasks']){
   assert.equal((await raw(route,{})).status,403,route);
  }
  assert.equal((await raw('tools',{tool:'create_loop',arguments:{name:'blocked'}})).status,403);
  assert.equal((await raw('tools',{tool:'list_loops',arguments:{}})).status,200);
  assert.equal((await raw('edit-access',{action:'unlock',password:'wrong'})).status,403);
  assert.equal((await raw('edit-access',{action:'unlock',password},{Origin:'http://outside.invalid'})).status,400);
  await page.locator('#edit-access-button').click();await page.locator('#edit-password').fill(password);await page.locator('#edit-unlock-form button[type=submit]').click();await page.locator('#edit-unlock-dialog').waitFor({state:'hidden'});
  await page.waitForFunction(()=>!document.querySelector('#platform-power-switch').disabled);
  const waitPower=async enabled=>{for(let i=0;i<80;i++){const power=(await rpc('platform')).data.keep_awake;if(power.requested===enabled&&!power.updating)return power;await page.waitForTimeout(100);}throw new Error('Sleep setting did not settle');};
  await page.locator('#platform-power-switch').check();
  const on=await waitPower(true);assert(on.active||on.error,on);
  await page.waitForFunction(()=>!document.querySelector('#platform-power-switch').disabled);
  await page.screenshot({path:path.join(root,'power-enabled.png')});
  await page.locator('#platform-power-switch').uncheck();assert.equal((await waitPower(false)).active,false);
  assert.equal((await rpc('platform/keep-awake',{enabled:'false'})).status,400);
  const unlocked=(await rpc('edit-access')).data;assert(unlocked.unlocked);assert(Math.abs(unlocked.expires_at-Date.now()/1000-86400)<5);
  const cookie=(await context.cookies()).find(c=>c.name==='loop_edit');assert(cookie.httpOnly);assert.equal(cookie.sameSite,'Strict');
  await page.reload();await page.locator('#edit-access-button').filter({hasText:'锁定编辑'}).waitFor();assert.equal((await rpc('edit-access')).data.expires_at,unlocked.expires_at);
  const tab=await context.newPage();await tab.goto(site+'/#loop_definitions');await tab.locator('#edit-access-button').filter({hasText:'锁定编辑'}).waitFor();await tab.close();
  await page.locator('#new-loop_definition').click();await page.locator('#loop_definition-editor').waitFor({state:'visible'});await page.locator('#bp-name').fill('共享编辑验收');await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();
  const drafts=(await rpc('drafts')).data;assert(drafts.some(d=>d.loop_definition.name==='共享编辑验收'));
  // Start an existing operator; locking the browser must not interrupt it or Engine scripts.
  const started=await rpc('tools',{tool:'start_run',arguments:{key,title:'Shared run',authorization:'Test local execution'}});assert.equal(started.status,200);const owner=started.data;
  const tool=async(name,args={})=>raw('tools',{tool:name,arguments:{run_id:owner.run_id,token:owner.token,...args}});
  const info=(await tool('read_task',{task_id:owner.entry_task_id})).data;
  await page.locator('#edit-access-button').click();await page.locator('#edit-access-button').filter({hasText:'解锁编辑'}).waitFor();
  const lockedRun=(await rpc('runs/'+owner.run_id)).data;assert(!JSON.stringify(lockedRun).includes(owner.token));
  assert.equal((await rpc('tools',{tool:'complete_task',arguments:{run_id:owner.run_id,token:owner.token}})).status,403);
  const completed=await tool('complete_task',{task_id:owner.entry_task_id,task_version:info.task_version,envelope:{settings:{objective:'shared'},outputs:{result:'initialized'}}});assert.equal(completed.status,200,JSON.stringify(completed));
  const recorded=(await rpc('runs/'+owner.run_id)).data;const snapshot=(await rpc('runs/'+owner.run_id+'/snapshot/'+recorded.executions[0].id)).data;assert(!JSON.stringify(snapshot).includes(owner.token));
  assert.equal((await tool('add_task',{key:'script','node_id':'script',inputs:{}})).status,200);
  assert.equal((await tool('finish')).status,200);
  for(let i=0;i<80;i++){const r=(await rpc('runs/'+owner.run_id)).data;if(r.executions.some(e=>e.outputs?.result==='script-result'))break;if(i===79)throw new Error('Engine stopped when browser locked');await page.waitForTimeout(100);}
  // Leaving an untouched draft in read mode does not demand an unlock or write.
  await page.reload();await page.locator('#loop_definition-editor').waitFor({state:'visible'});await page.locator('#loop_definitions-nav').click();await page.locator('#catalog-page').waitFor({state:'visible'});assert.equal((await rpc('drafts')).data.find(d=>d.id===drafts[0].id).revision,drafts[0].revision);
  // Non-browser authors use the shared password; their existing scoped tokens keep working.
  assert.equal((await raw('tools',{tool:'create_loop',arguments:{name:'External author'}},{Authorization:'Basic '+Buffer.from(':'+password).toString('base64')})).status,200);
  assert.equal((await raw('tools',{tool:'create_loop',arguments:{name:'blocked again'}})).status,403);
  await page.goto(site+'/#run/'+owner.run_id);await page.locator('#workspace').waitFor({state:'visible'});await page.screenshot({path:path.join(root,'readonly.png'),fullPage:true});
  await page.locator('#edit-access-button').click();await page.locator('#edit-password').fill(password);await page.locator('#edit-unlock-form button[type=submit]').click();await page.locator('#edit-unlock-dialog').waitFor({state:'hidden'});
  await page.locator('#add-run-task').click();await page.locator('#task-edit-dialog').waitFor({state:'visible'});await page.locator('#task-edit-dialog .close-dialog').first().click();
  await page.screenshot({path:path.join(root,'unlocked.png'),fullPage:true});
  const chat=(await rpc('conversations',{key})).data;
  const command=`import json,sys,time
from urllib.request import Request,urlopen
c=json.loads(sys.stdin.read().split('Web context:'+chr(10),1)[1])
def call(name,args={}):
 req=Request(c['tool_url']+'/api/tools',data=json.dumps({'tool':name,'arguments':args}).encode(),headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})
 with urlopen(req) as res:return json.load(res)
time.sleep(.6)
p=call('read_preparation');r=call('change_preparation',{'revision':p['revision'],'change':{'title':'Agent finished after lock'}});assert r['ok'],r
print('done')`;
  const configured=(await rpc('conversations/'+chat.id+'/update',{revision:chat.revision,agent:{command:['python3','-c',command]}})).data;
  assert.equal((await rpc('conversations/'+chat.id+'/send',{revision:configured.revision,message:'Update preparation title'})).status,200);
  await page.locator('#edit-access-button').click();
  for(let i=0;i<100;i++){const d=(await rpc('conversations/'+chat.id)).data;if(!d.busy){assert.equal(d.launch.title,'Agent finished after lock',JSON.stringify(d.messages));break;}if(i===99)throw new Error('Web Agent did not finish');await page.waitForTimeout(100);}
  await context.clearCookies();assert.equal((await rpc('runs/'+owner.run_id+'/command',{action:'pause'})).status,403);
  await page.reload();await page.locator('#edit-access-button').filter({hasText:'解锁编辑'}).waitFor();await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('#edit-access-button').click();await page.screenshot({path:path.join(root,'unlock-mobile.png')});
  assert(await page.locator('#platform-power-switch').isDisabled());
  server.kill('SIGTERM');await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));
  server=startServer();
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('restart timeout')),10000);server.stdout.on('data',data=>{if(String(data).includes('workspace:')){clearTimeout(timer);resolve();}});server.on('exit',code=>{clearTimeout(timer);reject(new Error('restart exited '+code));});});
  const retained=(await rpc('platform')).data.keep_awake;assert.equal(retained.requested,false);assert.equal(retained.active,false);
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,screenshots:root,real_model_calls:0}));
 }finally{if(browser)await browser.close();server.kill('SIGINT');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
