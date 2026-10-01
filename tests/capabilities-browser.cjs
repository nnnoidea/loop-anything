const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn,execFileSync}=require('node:child_process');const {chromium}=require('playwright');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-capabilities-')),db=path.join(root,'run.db');
 const seed=`import sys,json,sqlite3
sys.path.insert(0,'tests')
from test_authoring_capabilities import AuthoringCapabilitiesTests
case=AuthoringCapabilitiesTests();case.setUp()
case.edit('set_loop',scenarios=[case.scenario()])
case.edit('put_node',node_id='review',parameter_schema={'type':'object','properties':{'optional':{'type':['string','null']},'empty':{'type':'null'}},'additionalProperties':False})
with case.store.connection() as source:
 target=sqlite3.connect(sys.argv[1]);source.backup(target);target.close()
print(json.dumps({'draft_id':case.draft['draft_id']}));case.tearDown()`;
 const info=JSON.parse(execFileSync('python3',['-c',seed,db],{encoding:'utf8'}));
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const server=spawn('python3',['-m','loop_anything','--db',db,'serve','--port',String(port)],{env:{...process.env,PYTHONUNBUFFERED:'1'},stdio:['ignore','pipe','pipe']});let browser,logs='';server.stderr.on('data',x=>logs+=x);
 try{
  await new Promise((r,j)=>{const t=setTimeout(()=>j(Error(logs)),10000);server.stdout.on('data',x=>{if(String(x).includes('workspace:')){clearTimeout(t);r();}});});
  browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(12000);const base='http://127.0.0.1:'+port;
  // Reach the draft through the same route builder used by the catalog.
  await page.goto(base);await page.waitForFunction(()=>typeof routeHash==='function');
  await page.evaluate(id=>navigateTo({type:'editor',id}),info.draft_id);
  await page.locator('[data-drag-node="review"]').click();await page.locator('#author-label').fill('Review selected work');
  await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();
  const saved=(await (await page.request.get(base+'/api/drafts')).json()).find(d=>d.id===info.draft_id);
  assert.deepEqual(saved.loop_definition.nodes.review.parameter_schema.properties.optional.type,['string','null']);
  assert.equal(saved.loop_definition.nodes.review.parameter_schema.properties.empty.type,'null');
  assert.notEqual(saved.loop_definition.nodes.review.inputs.results.items?.type,'string','Saving an unconstrained array must not invent string item constraints');
  await page.locator('#author-plan-select').selectOption('review');await page.locator('[data-step-key="review"] > summary').click();
  assert.equal(await page.locator('[data-step-ref]').inputValue(),'review:{values.id}');
  await page.locator('[data-step-ref]').fill('review:{values.id}');
  await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();
  const plan=(await (await page.request.get(base+'/api/drafts')).json()).find(d=>d.id===info.draft_id).loop_definition.plans.review;
  assert.deepEqual(plan.steps.review.inputs.results,{task_refs:{$:'values.members'},port:'result'});
  assert.deepEqual(plan.steps.review.after_refs,{$:'values.members'});
  await page.locator('.editor-more > summary').click();await page.locator('#author-scenarios').click();
  await page.locator('#run-author-scenarios').click();await page.locator('#author-check-result h3').filter({hasText:'验收通过'}).waitFor();
  assert.equal((await (await page.request.get(base+'/api/runs')).json()).length,0);
  await page.locator('#author-check-dialog').screenshot({path:path.join(root,'scenario.png')});
  await page.locator('[data-close-author-check]').click();
  const pinned=await page.evaluate(()=>{const root=document.createElement('div');root.innerHTML=sourceField('result',{records:['a','b'],revisions:[1,2]},{type:'array'});return readSources(root).result;});
  assert.deepEqual(pinned,{records:['a','b'],revisions:[1,2]});
  // Public discovery is available without writer credentials.
  const catalog=await (await page.request.get(base+'/api/tools')).json();assert(catalog.service.version);assert(catalog.service.capabilities.includes('task_refs'));
  assert.equal(catalog.tools.filter(t=>t.name==='read_capabilities').length,1);
  const result=await (await page.request.post(base+'/api/tools',{headers:{'X-Loop-Anything':'workspace'},data:{tool:'read_capabilities',arguments:{capability:'scenarios'}}})).json();assert(result.ok&&result.guide.scenarios.tools.includes('test_loop'));
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,screenshots:root,cases:['union schema preservation','stable refs preservation','saved scenario real Engine acceptance','no real Run side effect','public discovery']},null,2));
 }catch(e){if(browser){const p=browser.contexts()[0]?.pages()[0];console.error((await p.locator('body').innerText()).slice(-1800));await p.screenshot({path:path.join(root,'failure.png'),fullPage:true});}throw e;}
 finally{if(browser)await browser.close();server.kill('SIGINT');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1});
