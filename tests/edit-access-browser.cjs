// Per-Loop password UI and trusted daily operations through real HTTP.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn,execFileSync}=require('node:child_process'),{chromium}=require('playwright');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-edit-access-')),db=path.join(root,'runs.db'),python=process.env.PYTHON||'python3',password='test-loop-edit';
 const fixture=JSON.parse(execFileSync(python,['-c',`import json,sys
sys.path.insert(0,'tests')
from test_run_agent import definition
from loop_anything.runtime.store import Store
from loop_anything.interfaces.platform_tools import PlatformTools
s=Store(sys.argv[1]);bp,impl=definition();key=s.publish(bp,impl)['key'];t=PlatformTools(s)
a=t.call('copy_loop',{'key':key,'new_version':True});b=t.call('copy_loop',{'key':key})
print(json.dumps({'key':key,'a':a,'b':b,'loop_id':bp['id']}))`,db],{encoding:'utf8'}));
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 let server,browser,logs='';
 const start=async()=>{server=spawn(python,['-m','loop_anything','--db',db,'serve','--host','0.0.0.0','--port',String(port),'--allow-sleep'],{env:{...process.env,PYTHONUNBUFFERED:'1'},stdio:['ignore','pipe','pipe']});server.stderr.on('data',d=>logs+=d);await new Promise((r,j)=>{const timer=setTimeout(()=>j(Error('startup timeout '+logs)),10000);server.stdout.on('data',d=>{if(String(d).includes('workspace:')){clearTimeout(timer);r();}});server.on('exit',c=>{clearTimeout(timer);j(Error('server exit '+c+' '+logs));});});};
 const stop=async()=>{server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));};
 try{
  await start();browser=await chromium.launch({headless:true,channel:'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];page.setDefaultTimeout(12000);page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:'+port,headers={'X-Loop-Anything':'workspace'};
  const raw=async(route,data,extra={})=>{const r=await context.request.post(base+'/api/'+route,{headers:{...headers,...extra},data});return {status:r.status(),data:await r.json()};};
  const rpc=async(tool,args={})=>raw('tools',{tool,arguments:args});
  const status=async id=>(await context.request.get(base+'/api/edit-access?loop_id='+encodeURIComponent(id))).json();
  const openDraft=async id=>{await page.goto(base+'/#edit/'+id);await page.locator('#loop_definition-editor').waitFor({state:'visible'});await page.locator('#edit-access').waitFor({state:'visible'});};
  await openDraft(fixture.a.draft_id);
  await page.locator('#edit-access-button').filter({hasText:'设置编辑口令'}).click();await page.locator('#loop-password-new').fill(password);await page.locator('#loop-password-form button[type=submit]').click();await page.locator('#loop-password-dialog').waitFor({state:'hidden'});
  await page.locator('#edit-access-button').filter({hasText:'锁定此 Loop'}).waitFor();
  const unlocked=await status(fixture.loop_id);assert(unlocked.protected&&unlocked.unlocked);assert(Math.abs(unlocked.expires_at-Date.now()/1000-86400)<5);
  const cookie=(await context.cookies()).find(c=>c.name.startsWith('loop_edit_'));assert(cookie.httpOnly);assert.equal(cookie.sameSite,'Strict');
  await page.reload();await page.locator('#edit-access-button').filter({hasText:'锁定此 Loop'}).waitFor();assert.equal((await status(fixture.loop_id)).expires_at,unlocked.expires_at);
  await stop();await start();await page.reload();await page.locator('#edit-access-button').filter({hasText:'锁定此 Loop'}).waitFor();assert.equal((await status(fixture.loop_id)).expires_at,unlocked.expires_at);
  await page.locator('#edit-access-button').click();await page.locator('#edit-access-button').filter({hasText:'解锁此 Loop'}).waitFor();assert(await page.locator('#bp-name').isDisabled());
  // Selecting/rerendering a locked node must keep its controls read-only.
  await page.locator('[data-drag-node]').first().click();
  assert(await page.locator('#loop_definition-editor').evaluate(root=>[...root.querySelectorAll('input,textarea,select')].every(el=>el.id==='author-plan-select'||el.disabled)));
  const viewBefore=await page.evaluate(()=>JSON.stringify({definition:editor.loop_definition,dirty:editor.dirty}));
  const head=page.locator('[data-drag-node]').first(),box=await head.boundingBox();await page.mouse.move(box.x+10,box.y+10);await page.mouse.down();await page.mouse.move(box.x+70,box.y+60);await page.mouse.up();
  assert.equal(await page.evaluate(()=>JSON.stringify({definition:editor.loop_definition,dirty:editor.dirty})),viewBefore);
  await page.locator('.editor-more').click();await page.locator('#editor-json').click();assert(await page.locator('#editor-import').isDisabled());assert(await page.locator('#editor-json-value').evaluate(el=>el.readOnly));await page.locator('#editor-json-dialog .close-dialog').click();
  await page.locator('#loop_definition-editor [data-editor-implementation]:visible').first().click();await page.waitForFunction(()=>document.querySelector('#loop_definition-editor').classList.contains('editor-implementation-page'));
  assert(await page.locator('#author-candidates input').first().isDisabled());await page.locator('#editor-detail-path a').first().click();await page.waitForFunction(()=>!document.querySelector('#loop_definition-editor').classList.contains('editor-detail-page'));
  await page.locator('.editor-more summary').click();await page.locator('#loop-package').click();assert(await page.locator('#package-assets').isDisabled());
  const download=page.waitForEvent('download');await page.locator('#package-export').click();await download;assert.equal(await page.evaluate(()=>editor.dirty),false);await page.locator('#package-dialog .close-dialog').click();
  const blocked=await rpc('set_loop',{draft_id:fixture.a.draft_id,revision:fixture.a.revision,name:'blocked'});assert.equal(blocked.status,403);assert.equal(blocked.data.error.loop_id,fixture.loop_id);
  assert.equal((await rpc('copy_loop',{key:fixture.key,new_version:true})).status,403);
  assert.equal((await rpc('copy_loop',{key:fixture.key})).status,200);
  assert.equal((await raw('edit-access',{action:'unlock',loop_id:fixture.loop_id,password:'wrong'})).status,403);
  assert.equal((await raw('edit-access',{action:'unlock',loop_id:fixture.loop_id,password},{Origin:'http://outside.invalid'})).status,400);
  // Loading a protected package into a draft preserves the verifier without installing it.
  const exported=(await rpc('export_loop',{draft_id:fixture.a.draft_id})).data,archive=path.join(root,'protected.loop.zip');fs.writeFileSync(archive,Buffer.from(exported.base64,'base64'));
  await page.goto(base+'/#loop_definitions');await page.locator('#import-loop-package').click();await page.locator('#package-upload').setInputFiles(archive);await page.locator('#package-edit').waitFor({state:'visible'});await page.waitForFunction(()=>!document.querySelector('#package-edit').disabled);await page.locator('#package-edit').click();await page.locator('#package-dialog').waitFor({state:'hidden'});await page.locator('#edit-access-button').filter({hasText:'解锁此 Loop'}).waitFor();assert(await page.locator('#bp-name').isDisabled());
  // Lock A does not lock an unrelated draft or operational functions.
  await openDraft(fixture.b.draft_id);await page.locator('#edit-access-button').filter({hasText:'设置编辑口令'}).waitFor();assert(!await page.locator('#bp-name').isDisabled());
  assert.equal((await rpc('communication_config',{operation:'identity',name:'Trusted workspace'})).status,200);
  assert.equal((await rpc('communication_status')).status,200);
  assert.equal((await raw('platform/keep-awake',{enabled:false})).status,200);
  const started=await rpc('start_run',{key:fixture.key,title:'Protected Loop run',authorization:'Isolated test'});assert.equal(started.status,200);const runId=started.data.run_id;
  const task=(await rpc('read_task',{run_id:runId,task_id:started.data.entry_task_id})).data;
  const completed=await rpc('complete_task',{run_id:runId,task_id:started.data.entry_task_id,task_version:task.task_version,envelope:{settings:{objective:'public operation'},outputs:{result:'initialized'}}});assert.equal(completed.status,200);assert(completed.data.accepted);
  assert.equal((await rpc('finish',{run_id:runId})).status,200);
  const timeline=(await rpc('read_timeline',{run_id:runId})).data;
  assert.equal((await rpc('change_settings',{run_id:runId,revision:timeline.settings.revision,change:{guidance:'no password or manual handle'}})).status,200);
  const invalid=await rpc('change_settings',{run_id:runId,token:'old execution',revision:1,change:{guidance:'wrong'}});assert.equal(invalid.status,409);
  await page.goto(base+'/#run/'+runId);await page.locator('#workspace').waitFor({state:'visible'});assert(await page.locator('#edit-access').isHidden());
  // Change and clear protection through the Loop settings dialog.
  await openDraft(fixture.a.draft_id);await page.locator('#edit-access-button').filter({hasText:'解锁此 Loop'}).click();await page.locator('#edit-password').fill(password);await page.locator('#edit-unlock-form button[type=submit]').click();await page.locator('#edit-unlock-dialog').waitFor({state:'hidden'});
  await page.locator('#loop-password-settings').click();await page.locator('#loop-password-new').fill('replacement');await page.locator('#loop-password-form button[type=submit]').click();await page.locator('#loop-password-dialog').waitFor({state:'hidden'});
  await page.locator('#edit-access-button').filter({hasText:'锁定此 Loop'}).click();await page.locator('#edit-access-button').filter({hasText:'解锁此 Loop'}).waitFor();
  assert.equal((await raw('edit-access',{action:'unlock',loop_id:fixture.loop_id,password})).status,403);
  await page.locator('#loop-password-settings').click();await page.locator('#loop-password-form button[type=submit]').click();await page.locator('#loop-password-error').filter({hasText:'Unlock'}).waitFor();
  await page.locator('#loop-password-current').fill('replacement');await page.locator('#loop-password-form button[type=submit]').click();await page.locator('#loop-password-dialog').waitFor({state:'hidden'});await page.locator('#edit-access-button').filter({hasText:'设置编辑口令'}).waitFor();assert(!await page.locator('#bp-name').isDisabled());
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(root,'loop-password-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,screenshots:root,real_model_calls:0}));
 }finally{if(browser)await browser.close();if(server&&server.exitCode===null)await stop();}
})().catch(e=>{console.error(e);process.exitCode=1;});
