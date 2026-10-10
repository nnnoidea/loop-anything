const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-communication-browser-')),db=path.join(root,'workspace.db');
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const python=process.env.PYTHON || 'python3';
 const server=spawn(python,['-m','loop_anything','--db',db,'serve','--port',String(port),'--allow-sleep'],{env:{...process.env,LOOP_ANYTHING_EDIT_PASSWORD:'communication-test',PYTHONPYCACHEPREFIX:'/tmp/loop-comm-pycache'},stdio:['ignore','pipe','pipe']});let browser,logs='';server.stderr.on('data',x=>logs+=x);
 try{
  await new Promise((r,j)=>{const t=setTimeout(()=>j(Error(logs)),10000);server.stdout.on('data',x=>{if(String(x).includes('workspace:')){clearTimeout(t);r();}});});
  browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1450,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(12000);
  const base='http://127.0.0.1:'+port;await page.goto(base);
  await page.locator('#edit-access-button').click();await page.locator('#edit-password').fill('communication-test');await page.locator('#edit-unlock-form button[type="submit"]').click();await page.locator('#edit-unlock-dialog').waitFor({state:'hidden'});
  await page.locator('#communication-nav').click();try{await page.locator('#communication-page h1').waitFor();}catch(e){console.error(await page.evaluate(()=>({toast:document.querySelector('#toast').textContent,html:document.querySelector('#communication-page')?.outerHTML,page:page,route:activeRoute})),errors,logs);throw e;}
  assert.equal(await page.locator('#communication-page h1').textContent(),'Agent 通信');
  await page.locator('#communication-agent-add').click();await page.locator('#communication-agent-form [name=name]').fill('本机论文助手');
  await page.locator('#communication-agent-form [name=description]').fill('只在本机调用，不需要群组');
  // Keep the Python split separator literal while preserving real newlines in the argv item.
  const command=[python,'-c',"import sys,json,urllib.request\nc=json.loads(sys.stdin.read().split(chr(10),1)[1])\nb={'tool':'communication_execute','arguments':{'request_id':c['request_id'],'token':c['token'],'tool':'complete','arguments':{'result':{'summary':'浏览器本机外援完成'}}}}\nr=urllib.request.Request(c['platform_url']+'/api/tools',data=json.dumps(b).encode(),headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})\nprint(urllib.request.urlopen(r).read().decode())"];
  await page.locator('#communication-agent-form [name=command]').fill(JSON.stringify(command));await page.locator('#communication-agent-form button.primary').click();await page.locator('#communication-dialog').waitFor({state:'hidden'});
  await page.waitForFunction(()=>document.querySelector('#communication-request [name=agent]')?.options.length===1);
  await page.locator('#communication-request [name=message]').fill('测试没有 Loop、没有 NAS 的本机外援');await page.locator('#communication-request button.primary').click();
  await page.waitForFunction(()=>document.querySelector('#comm-detail-state')?.textContent.includes('已完成'));
  assert((await page.locator('#comm-detail-result').textContent()).includes('浏览器本机外援完成'));
  const runs=await (await page.request.get(base+'/api/runs')).json();assert.equal(runs.length,0);
  await page.screenshot({path:path.join(root,'request.png'),fullPage:true});await page.locator('#communication-dialog [data-comm-close]').click();
  await page.locator('#communication-group [name=path]').fill(path.join(root,'nas'));await page.locator('#communication-group [name=name]').fill('验收群组');await page.locator('#communication-group [name=create]').check();await page.locator('#communication-group button').click();
  await page.waitForFunction(()=>document.querySelector('[data-comm-leave]'));
  const outletResponse=await page.request.post(base+'/api/tools',{data:{tool:'set_notification_channels',arguments:{revision:0,channels:{test:{label:'测试群出口',identity:'project-test',destination:'chat-test',command:[python,'-c','print(\'{"delivered":true}\')']}}}},headers:{'X-Loop-Anything':'workspace'}});
  assert((await outletResponse.json()).ok);
  await page.locator('[data-comm-notifications]').click();await page.locator('#comm-group-notifications [name=route]').selectOption('test');
  await page.locator('#comm-group-notifications [name=level]').selectOption('attention');
  await page.screenshot({path:path.join(root,'group-notification-binding.png'),fullPage:true});
  await page.locator('#comm-group-notifications button.primary').click();await page.locator('#communication-dialog').waitFor({state:'hidden'});
  await page.waitForFunction(()=>document.querySelector('#communication-page').textContent.includes('chat-test'));
  const workspace=await (await page.request.post(base+'/api/tools',{data:{tool:'communication_workspace',arguments:{}},headers:{'X-Loop-Anything':'workspace'}})).json();
  const group=Object.values(workspace.configuration.groups)[0];assert.equal(group.notification_binding.sender_instance,workspace.configuration.instance_id);assert.equal(group.notification_binding.level,'attention');
  assert.equal(workspace.notification_deliveries.length,0,'Saving a binding must not send a message');
  await page.screenshot({path:path.join(root,'groups.png'),fullPage:true});
  await page.locator('[data-comm-leave]').click();await page.waitForFunction(()=>document.querySelector('[data-comm-leave]')?.disabled);
  await page.setViewportSize({width:430,height:900});await page.screenshot({path:path.join(root,'mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,screenshots:root}));
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
