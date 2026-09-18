// A real local command chats through HTTP tools; no model, external account or user DB.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn,execFileSync}=require('node:child_process');
const {chromium}=require('playwright');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-web-agent-ui-')),db=path.join(root,'runs.db'),agent=path.join(root,'agent.py');
 const seed=`import sys,json
sys.path.insert(0,'tests')
from test_run_agent import definition
from test_web_agent import AGENT
from loop_anything.runtime.store import Store
bp,impl=definition();bp['name']='训练方案 · 网页协作验收'
bp['nodes']['init']['label']='确认训练目标';bp['nodes']['script']['label']='提交训练'
bp['defaults']={'request':'比较本地与远端的训练结果'}
bp['nodes']['init']['inputs']={'request':{'type':'string','nonempty':True}};bp['seed']['inputs']={'request':{'run':'request'}}
bp['guide']={'purpose':'先讨论目标和运行方式，再开始训练。','parameters':{'request':{'label':'训练目标'}}}
impl['script']={'default':'local','options':{n:{'kind':'command','command':[sys.executable,'-c','import json;print(json.dumps({"outputs":{"result":%r}}))'%n]} for n in ('local','remote')}}
open(sys.argv[2],'w').write(AGENT.replace("mode=sys.argv[1]", "mode='start' if c['start_requested'] else 'edit' if c['run_id'] else 'discuss'"))
print(Store(sys.argv[1]).publish(bp,impl)['key'])`;
 const key=execFileSync('python3',['-c',seed,db,agent],{encoding:'utf8',env:{...process.env,PYTHONPYCACHEPREFIX:path.join(root,'pycache')}}).trim();
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const server=spawn('python3',['-m','loop_anything','--db',db,'serve','--port',String(port)],{env:{...process.env,PYTHONUNBUFFERED:'1',PYTHONPYCACHEPREFIX:path.join(root,'pycache')},stdio:['ignore','pipe','pipe']});
 let browser;
 try{
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Server startup timeout')),10000);server.stdout.on('data',d=>{if(String(d).includes('workspace:')){clearTimeout(timer);resolve();}});server.on('exit',c=>{clearTimeout(timer);reject(new Error('Server exited '+c));});});
  browser=await chromium.launch({headless:true,channel:'chrome'});const page=await browser.newPage({viewport:{width:1720,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const url='http://127.0.0.1:'+port,get=async p=>(await (await page.request.get(url+'/api/'+p)).json());
  await page.goto(url+'/#loop_definitions');await page.locator('#catalog-cards [data-create]').click();
  await page.locator('#launch-page').waitFor({state:'visible'});
  const firstPrep=page.url();
  const originalCatalog=await get('catalog');
  await page.locator('#preparation-flow [data-map-node="script"]').click();
  const picker=page.locator('#preparation-flow [data-map-details="script"]');
  assert.equal(await picker.locator('[data-candidate]').count(),2);
  await picker.locator('[data-candidate="remote"] summary').click();
  assert((await picker.locator('[data-candidate="remote"] pre').innerText()).includes('remote'));
  await picker.locator('[data-candidate="remote"] [data-map-choice]').click();
  assert((await page.locator('#preparation-flow [data-map-node="script"]').innerText()).includes('remote'));
  assert.equal(await page.locator('#launch-bindings').count(),0);
  // Preserve inherited and deliberately unbound states as well as explicit selection.
  await picker.locator('[data-choice="null"]').click();
  assert((await page.locator('#preparation-flow [data-map-node="script"]').innerText()).includes('尚未选用'));
  await picker.locator('[data-choice=""]').click();
  assert((await page.locator('#preparation-flow [data-map-node="script"]').innerText()).includes('local'));
  await picker.locator('[data-candidate="remote"] [data-map-choice]').click();
  assert.deepEqual(await get('catalog'),originalCatalog);

  await page.locator('#create-title').fill('远端训练准备');
  await page.locator('#web-chat-input').fill('尚未发送的想法');
  await page.locator('#loop_definitions-nav').click();
  await page.locator('#catalog-cards [data-create]').click();
  await page.waitForURL(u=>u.hash.startsWith('#prepare/')&&u.href!==firstPrep);
  await page.locator('#launch-page').waitFor({state:'visible'});
  const secondPrep=page.url();assert.notEqual(firstPrep,secondPrep);
  await page.locator('#create-title').fill('另一个准备页');
  await page.locator(`#preparation-list a[href="${new URL(firstPrep).hash}"]`).click();
  await page.waitForFunction(()=>document.querySelector('#create-title').value==='远端训练准备');
  assert.equal(await page.locator('#web-chat-input').inputValue(),'尚未发送的想法');
  await page.reload();await page.locator('#launch-page').waitFor({state:'visible'});
  assert.equal(await page.locator('#preparation-list a').count(),2);
  assert.equal((await get('runs')).length,0);
  await page.locator('#web-agent-command').fill('python3\n'+agent);
  await page.locator('#web-chat-input').fill('训练使用远端实现，先讨论，不启动。');await page.locator('#web-chat-send').click();
  await page.locator('.chat-message.assistant').filter({hasText:'还没有启动'}).waitFor();
  assert.equal((await get('runs')).length,0);
  await page.waitForFunction(()=>document.querySelector('#preparation-flow [data-map-node="script"] .map-current-implementation').textContent.includes('remote'));
  const prepURL=page.url();await page.reload();await page.locator('.chat-message.assistant').filter({hasText:'还没有启动'}).waitFor();
  assert((await page.locator('#preparation-flow [data-map-node="script"] .map-current-implementation').innerText()).includes('remote'));
  assert.equal(await page.locator('#web-agent-command').inputValue(),'python3\n'+agent);
  await page.locator('#preparation-flow [data-map-node="script"]').click();
  await page.screenshot({path:path.join(root,'preparation-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
  await page.screenshot({path:path.join(root,'preparation-mobile.png'),fullPage:true});await page.setViewportSize({width:1720,height:1100});
  await page.locator('#launch-review').click();await page.locator('#launch-ack').check();await page.locator('#launch-start').click();
  await page.waitForURL(/#run\//);await page.locator('.chat-message.assistant').filter({hasText:'已启动并初始化'}).waitFor();
  const rows=await get('runs');assert.equal(rows.length,1);const id=rows[0].id;
  await page.waitForFunction(()=>document.querySelectorAll('#preparation-list a').length===1);
  await page.locator(`#preparation-list a[href="${new URL(secondPrep).hash}"]`).click();
  await page.waitForFunction(()=>document.querySelector('#create-title').value==='另一个准备页');
  await page.locator(`[data-run="${id}"]`).click();await page.waitForURL(/#run\//);await page.locator('#run-chat-host #web-chat-input').waitFor({state:'visible'});
  for(let i=0;i<100;i++){const r=await get('runs/'+id);if(r.executions.some(e=>e.outputs?.result==='remote'))break;await page.waitForTimeout(100);if(i===99)throw new Error('Remote candidate did not run');}
  await page.locator('#web-chat-input').fill('把当前指导修改为用户要求修改。');await page.locator('#web-chat-send').click();
  await page.locator('.chat-message.assistant').filter({hasText:'已修改本次运行'}).waitFor();assert.equal((await get('runs/'+id)).settings.guidance,'用户要求修改');
  assert.equal((await get('runs')).length,1);
  await page.waitForFunction(()=>/^\d+%$/.test(document.querySelector('#graph-scale')?.textContent));await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(root,'run-desktop.png'),fullPage:true});
  // Completed notice is derived from the same Run, including changes made outside this page.
  const tool=async(tool,arguments={})=>{const res=await page.request.post(url+'/api/tools',{headers:{'X-Loop-Anything':'workspace'},data:{tool,arguments}});const r=await res.json();assert(r.ok,JSON.stringify(r));return r;};
  const o=await tool('acquire_run',{run_id:id}),r=await tool('read_timeline',{run_id:id,token:o.token});
  await tool('change_settings',{run_id:id,token:o.token,revision:r.settings.revision,change:{termination_signal:'网页流程验收完成'}});await tool('finish',{run_id:id,token:o.token});
  await page.locator('#web-chat-notices').filter({hasText:'运行已完成'}).waitFor();
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));await page.screenshot({path:path.join(root,'run-mobile.png'),fullPage:true});
  await page.goto(prepURL);await page.waitForURL(/#run\//);assert.equal((await get('runs')).length,1);await page.goto(url+'/#loop/'+encodeURIComponent(key));await page.locator('#loop-detail [data-map-node="script"]').click();
  await page.locator('#loop-detail [data-map-details="script"] [data-candidate="remote"] [data-prepare-choice]').click();
  await page.waitForURL(/#prepare\//);await page.locator('#launch-page').waitFor({state:'visible'});
  assert((await page.locator('#preparation-flow [data-map-node="script"]').innerText()).includes('remote'));
  assert.equal((await get('runs')).length,1);assert.deepEqual(await get('catalog'),originalCatalog);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ok:true,database:db,screenshots:root,run_id:id,real_model_calls:0}));
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
