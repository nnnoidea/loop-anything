const {chromium}=require('playwright'),{spawn,execFileSync}=require('node:child_process'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
(async()=>{const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-notify-wait-ui-')),db=path.join(root,'runs.db');
const seed=`import sys,json
sys.path.insert(0,'tests')
from test_timeline_runtime import RuntimeTests,task_spec
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.interfaces.agent_tasks import RunTools
result=[]
for ident,title,kind in [('research','研究 · 等待确认','event'),('trip','出行 · 等待时间','timer')]:
 b=RuntimeTests();b.setUp();b.engine.close();b.store=Store(sys.argv[1]);b.engine=Engine(b.store)
 try:
  b.bp['id']=ident;b.bp['name']=title;b.bp['nodes']['produce']['label']='等待确认' if kind=='event' else '稍后继续'
  b.bp['nodes']['produce']['outputs']={'answer':{'record_type':'text'}} if kind=='event' else {}
  b.implementations['produce']={'kind':'event','event':'reply','wait':{'key':'request-1','timeout':3600}} if kind=='event' else {'kind':'timer','wait':{'seconds':3600}}
  b.initialize([task_spec('waiting','produce',{'source':{'record':'a'}},{'answer':'answer'} if kind=='event' else {})])
  result.append({'id':b.id,'key':b.read()['loop_key']})
 finally:b.tearDown()
print(json.dumps(result))`;
const runs=JSON.parse(execFileSync('/opt/homebrew/bin/python3.10',['-c',seed,db],{encoding:'utf8'}));const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base='http://127.0.0.1:'+port;
const server=spawn('/opt/homebrew/bin/python3.10',['-m','loop_anything','--db',db,'serve','--port',String(port),'--allow-sleep'],{env:{...process.env,PYTHONUNBUFFERED:'1'},stdio:['ignore','pipe','pipe']});let browser;
try{await new Promise((r,j)=>{const t=setTimeout(()=>j(new Error('startup')),10000);server.stdout.on('data',d=>{if(String(d).includes('workspace:')){clearTimeout(t);r();}});});browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1560,height:1080}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(15000);
await page.goto(base+'/#run/'+runs[0].id);await page.locator('[data-task-row="waiting"]').click();await page.locator('.wait-description').scrollIntoViewIfNeeded();await page.locator('#task-detail').screenshot({path:path.join(root,'event-wait.png')});
await page.locator('#notification-outlets').click();await page.locator('#add-outlet').click();await page.locator('[data-outlet-id]').fill('demo');await page.locator('[data-outlet-label]').fill('验收通知');await page.locator('[data-outlet-identity]').fill('demo-bot');await page.locator('[data-outlet-destination]').fill('demo-room');await page.locator('[data-outlet-command]').fill('/opt/homebrew/bin/python3.10\n-c\nimport json,sys; d=json.load(sys.stdin); print(json.dumps({"delivered":True,"reference":d["id"],"channel":d["outlet"]["destination"]}))');await page.locator('#save-outlets').click();await page.locator('#outlet-dialog').waitFor({state:'hidden'});
await page.reload();await page.locator('#notification-outlets').click();assert.equal(await page.locator('[data-outlet-destination]').inputValue(),'demo-room');await page.screenshot({path:path.join(root,'outlets.png')});await page.locator('#outlet-dialog .close-dialog').click();
await page.locator('[data-tab="hooks"]').click();await page.locator('#send-run-notice').click();await page.locator('#notice-dialog [data-notice-message]').fill('可以按当前预算继续吗？');await page.locator('#notice-dialog [data-notice-route]').selectOption('demo');await page.locator('#notice-dialog [data-notice-question]').check();await page.locator('#notice-dialog [data-reply-key]').fill('request-1');await page.screenshot({path:path.join(root,'question.png')});await page.locator('#send-notice-form [type=submit],#send-notice-form > button.primary').click();await page.locator('#notice-dialog').waitFor({state:'hidden'});
let recorded;for(let i=0;i<80;i++){recorded=await (await page.request.get(base+'/api/runs/'+runs[0].id)).json();if(recorded.notifications[0]?.status==='delivered')break;await page.waitForTimeout(100);}assert.equal(recorded.notifications[0].receipt.channel,'demo-room');assert.equal(recorded.tasks.waiting.status,'waiting');
await page.locator('[data-tab="decisions"]').click();await page.locator('#inspect [data-complete-wait="waiting"]').click();await page.locator('#event-reply-value input[type=text],#event-reply-value textarea').first().fill('同意，继续');await page.locator('#reply-notice-form > button.primary').click();await page.locator('#notice-dialog').waitFor({state:'hidden'});
for(let i=0;i<80;i++){recorded=await (await page.request.get(base+'/api/runs/'+runs[0].id)).json();if(recorded.tasks.waiting.status==='completed')break;await page.waitForTimeout(100);}assert.equal(recorded.records.answer[0].value,'同意，继续');assert.equal(recorded.events.length,1);await page.screenshot({path:path.join(root,'delivered.png'),fullPage:true});
await page.goto(base+'/#run/'+runs[1].id);await page.locator('[data-tab="task-history"]').click();await page.locator('[data-task-row="waiting"]').click();assert(await page.locator('.wait-description').isVisible());await page.locator('[data-task-cancel="waiting"]').click();await page.locator('#task-edit-reason').fill('取消等待验收');await page.locator('#task-edit-submit').click();await page.locator('#task-edit-submit').filter({hasText:'应用修改'}).click();await page.locator('#task-edit-dialog').waitFor({state:'hidden'});assert.equal((await (await page.request.get(base+'/api/runs/'+runs[1].id)).json()).tasks.waiting.status,'cancelled');
await page.goto(base+'/#loop/'+encodeURIComponent(runs[0].key)+'/flow');await page.locator('[data-version-loop-definition]').click();await page.locator('[data-add-wait="timer"]').click();await page.waitForURL(/implementation\/default$/);const candidate=page.locator('.author-candidate:not([hidden])');await candidate.locator('[data-wait-seconds]').fill('120');await candidate.locator('[data-behavior-rule="1"]').click();const transition=candidate.locator('.selected-transition');await transition.locator('[data-add-transition-notice]').click();await transition.locator('[data-notice-message]').fill('等待结束，可以继续');await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();await page.reload();await candidate.locator('[data-wait-seconds]').waitFor();assert.equal(await candidate.locator('[data-wait-seconds]').inputValue(),'120');const drafts=await (await page.request.get(base+'/api/drafts')).json(),draft=drafts.find(d=>d.loop_definition.id==='research');assert(draft);assert(draft.implementations.wait_1.options.default.lifecycle.transitions.some(r=>r.notify?.[0].message==='等待结束，可以继续'));
const rulesBefore=structuredClone(draft.implementations.wait_1.options.default.lifecycle.transitions);
// The common control edits the actual stored rule without changing sibling rules or notifications.
await candidate.locator('[data-behavior-target="2"]').selectOption('retry');
await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();await page.reload();await candidate.locator('[data-behavior-target="2"]').waitFor();
assert.equal(await candidate.locator('[data-behavior-target="2"]').inputValue(),'retry');
let saved=(await (await page.request.get(base+'/api/drafts')).json()).find(d=>d.id===draft.id);
const expected=structuredClone(rulesBefore);expected[2].to='retry';assert.deepEqual(saved.implementations.wait_1.options.default.lifecycle.transitions,expected);
await candidate.locator('[data-behavior-rule="2"]').click();
const custom=candidate.locator('.selected-transition');await custom.locator('details > summary').filter({hasText:'可选条件'}).click();
await custom.locator('[data-transition-when]').fill('{"op":"le","args":[{"path":"attempt"},2]}');
await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();await page.reload();await candidate.locator('[data-behavior-rule="2"]').waitFor();
// A conditional rule is kept explicit, never flattened by the simple dropdown.
assert.equal(await candidate.locator('[data-behavior-target="2"]').count(),0);
saved=(await (await page.request.get(base+'/api/drafts')).json()).find(d=>d.id===draft.id);assert.deepEqual(saved.implementations.wait_1.options.default.lifecycle.transitions[2].when,{op:'le',args:[{path:'attempt'},2]});
await candidate.locator('.candidate-machine').screenshot({path:path.join(root,'author-behavior.png')});
await page.setViewportSize({width:390,height:844});await candidate.locator('.candidate-machine').screenshot({path:path.join(root,'author-behavior-mobile.png')});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.setViewportSize({width:1560,height:1080});
await page.screenshot({path:path.join(root,'author-wait.png'),fullPage:true});
// Both graph layers use the saved candidate matrix, while the relation canvas retains the wait summary.
await page.locator('#editor-detail-path a').first().click();
await page.locator('[data-editor-card="wait_1"] .node-wait').waitFor();
assert((await page.locator('[data-editor-card="wait_1"] .node-wait').innerText()).includes('120'));
await page.locator('[data-editor-layer="states"]').click();
await page.locator('#editor-state-overview').waitFor({state:'visible'});
assert.equal(await page.locator('#editor-canvas').isVisible(),false);
assert(await page.locator('#editor-state-overview .node-notifies').isVisible());
assert((await page.locator('#editor-edges-list .notice-schedule').innerText()).includes('等待结束，可以继续'));
await page.waitForTimeout(200);await page.screenshot({path:path.join(root,'editor-states.png'),fullPage:true});
await page.locator('[data-editor-layer="relations"]').click();
assert.equal(await page.locator('#editor-state-overview').isVisible(),false);
await page.waitForTimeout(200);await page.screenshot({path:path.join(root,'editor-relations.png'),fullPage:true});
await page.locator('#editor-publish').click();await page.locator('#launch-page').waitFor({state:'visible'});
await page.locator('[data-focus-outlet="launch"]').click();
await page.locator('#launch-notification-route').selectOption('demo');
await page.locator('#preparation-saved').filter({hasText:'已保存'}).waitFor();
await page.reload();await page.locator('#preparation-flow .preparation-outlet').waitFor();
assert.equal(await page.locator('#launch-notification-route').inputValue(),'demo');
assert((await page.locator('#preparation-flow .preparation-outlet').innerText()).includes('验收通知'));
await page.locator('#preparation-flow [data-graph-layer="states"]').click();
assert.equal(await page.locator('#preparation-flow .map-body').isVisible(),false);
const shown=page.locator('#preparation-flow .execution-overview');assert(await shown.isVisible());
assert.equal(await shown.locator('.execution-overview-node').count(),Object.keys(draft.loop_definition.nodes).length);
await page.waitForTimeout(200);await page.screenshot({path:path.join(root,'prepare-states.png'),fullPage:true});
await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(root,'mobile.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,screenshots:root}));
}catch(e){if(browser){const p=browser.contexts()[0].pages()[0];console.error('PAGE',p.url(),(await p.locator('body').innerText()).slice(-3000));await p.screenshot({path:path.join(root,'failure.png'),fullPage:true});}throw e;}finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1});
