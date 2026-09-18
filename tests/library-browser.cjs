// Isolated end-to-end acceptance. Never connects to the user's runtime database.
// Requires playwright + a local Chrome installation; no browser downloads.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const {spawn,execFileSync}=require('node:child_process');
const {chromium}=require('playwright');

(async()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-library-ui-'));
  const database=path.join(root,'runs.sqlite3');
  const seed=`import sys,json,copy
sys.path.insert(0,'tests')
from test_packages import document
from loop_anything.runtime.store import Store
from loop_anything.packaging.packages import make_archive,install
s=Store(sys.argv[1]);keys=[]
for count in (0,1,2):
 d=document();b=d['loop_definition'];b['name']='用户测试 Loop '+str(count)
 b['defaults']={'request':'比较两种方案','budget':3,'enabled':False,'settings':{'region':'local'}}
 b['nodes']['initialize']['inputs']={'request':{'type':'string','nonempty':True},'budget':{'type':'integer','minimum':1},'enabled':{'type':'boolean'},'settings':{'type':'object'}}
 b['seed']['inputs']={k:{'run':k} for k in b['defaults']}
 b['nodes']['initialize']['plan_nodes']=['finish']
 b['nodes']['initialize']['skills']=[{'name':'author-method','content':'Author initialization method.'}]
 b['guide']={'purpose':'<script>不可执行的作者说明</script>','results':'一份比较结果','effects':'测试仅等待人工提交，不调用模型。','parameters':{'request':{'label':'本次目标','description':'写出希望比较什么'},'budget':{'label':'实验次数','description':'至少一次'}}}
 d['implementations']={n:{'kind':'agent'} for n in list(b['nodes'])[:count]}
 if count==2:d['implementations']['initialize']={'default':'primary','options':{'primary':{'kind':'agent'},'secondary':{'kind':'agent'}}}
 raw=make_archive(d);keys.append(install(s,raw)['key'])
 if count==2:open(sys.argv[2],'wb').write(raw)
print(json.dumps(keys))`;
  const packageFile=path.join(root,'complete.loop.zip');
  const keys=JSON.parse(execFileSync('python3',['-c',seed,database,packageFile],{encoding:'utf8'}));
  const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
  const server=spawn('python3',['-m','loop_anything','--db',database,'serve','--port',String(port)],{env:{...process.env,PYTHONUNBUFFERED:'1',PYTHONPYCACHEPREFIX:path.join(root,'pycache')},stdio:['ignore','pipe','pipe']});
  let browser;
  try{
    await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Server startup timeout')),10000);server.stdout.on('data',data=>{if(String(data).includes('workspace:')){clearTimeout(timer);resolve();}});server.on('exit',code=>{clearTimeout(timer);reject(new Error('Server exited '+code));});});
    browser=await chromium.launch({headless:true,channel:'chrome'});
    const page=await browser.newPage({viewport:{width:1440,height:1080}}),errors=[],writes=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.method()==='POST' && !['validate','packages/smoke','packages/read','packages/export'].some(s=>r.url().endsWith('/api/'+s)))writes.push(r.url());});
    const url='http://127.0.0.1:'+port;
    const runCount=async()=>(await (await page.request.get(url+'/api/runs')).json()).length;
    const waitRun=async(id,predicate)=>{for(let i=0;i<100;i++){const state=await (await page.request.get(url+'/api/runs/'+id)).json();if(predicate(state))return state;await page.waitForTimeout(100);}throw new Error('Run state timed out: '+id);};
    await page.goto(url+'/#loop_definitions');
    await page.locator('[data-loop]').first().waitFor();
    await page.screenshot({path:path.join(root,'library.png'),fullPage:true});
    assert.equal(await runCount(),0);
    await page.locator(`[data-loop="${keys[2]}"]`).first().click();
    await page.locator('#loop-detail').waitFor({state:'visible'});
    assert((await page.locator('#loop-detail').innerText()).includes('<script>不可执行的作者说明</script>'));
    assert.equal(await page.locator('#loop-detail script').count(),0);
    const downloadEvent=page.waitForEvent('download');await page.locator('#download-loop-package').click();
    const download=await downloadEvent;assert(download.suggestedFilename().endsWith('.loop.zip'));
    const chunks=[];for await(const chunk of await download.createReadStream())chunks.push(chunk);
    const loopZip=path.join(root,'downloaded.loop.zip');fs.writeFileSync(loopZip,Buffer.concat(chunks));
    const document=JSON.parse(execFileSync('python3',['-c',`import sys,zipfile
print(zipfile.ZipFile(sys.argv[1]).read('loop.json').decode())`,loopZip],{encoding:'utf8'}));
    assert.equal(document.loop_definition.handbook.instructions,'Initialize intent, write result, finish after result.');
    assert.deepEqual(document.loop_definition.nodes.initialize.skills,[{name:'author-method',content:'Author initialization method.'}]);
    const skillZip=path.join(root,'skills.zip');fs.writeFileSync(skillZip,await (await page.request.get(url+'/api/skills')).body());
    execFileSync('python3',['-c',`import sys,zipfile
z=zipfile.ZipFile(sys.argv[1]);z.extractall(sys.argv[2])
assert [n for n in z.namelist() if n.endswith('/SKILL.md')]==['platform/loop-anything-platform/SKILL.md']`,skillZip,path.join(root,'skills')]);
    const toolClient=path.join(root,'skills','platform','loop-anything-platform','scripts','call.py');
    const catalog=JSON.parse(execFileSync('python3',[toolClient,'list'],{encoding:'utf8'}));assert(catalog.tools.some(t=>t.name==='put_node'));assert(catalog.tools.some(t=>t.name==='start_run'));
    assert.equal(await runCount(),0);assert.deepEqual(writes,[]);
    await page.screenshot({path:path.join(root,'overview.png'),fullPage:true});
    await page.locator('[data-loop-tab="flow"]').click();
    await page.locator('.step-card > summary').filter({hasText:'initialize'}).click();
    await page.locator('[data-loop-tab="prepare"]').click();
    await page.locator('#loop-check').click();
    await page.locator('#loop-check-result .check-row').first().waitFor();
    assert((await page.locator('#loop-check-result').innerText()).includes('未验证'));
    assert.equal(await runCount(),0);assert.deepEqual(writes,[]);
    await page.screenshot({path:path.join(root,'preparation.png'),fullPage:true});
    // Missing unused implementations no longer block launch review.
    await page.locator('#library-back').click();
    await page.locator(`[data-loop="${keys[1]}"]`).first().click();
    await page.locator('#loop-detail [data-create]').click();
    await page.locator('#launch-review').click();
    await page.locator('#launch-confirm').waitFor({state:'visible'});
    await page.locator('#preparation-back').click();
    assert.equal(await runCount(),0);
    // A changed preflight result after review still blocks final dispatch.
    await page.locator('#library-back').click();
    await page.locator(`[data-loop="${keys[2]}"]`).first().click();
    await page.locator('#loop-detail [data-create]').click();
    await page.locator('#launch-review').click();
    await page.locator('#launch-confirm').waitFor({state:'visible'});
    await page.route('**/api/packages/smoke',route=>route.fulfill({json:{checks:[{kind:'asset',status:'fail',target:'changed-package-file'}]}}));
    await page.locator('#launch-ack').check();await page.locator('#launch-start').click();
    await page.locator('#create-dialog').waitFor({state:'hidden'});
    assert.equal(await runCount(),0);
    await page.unroute('**/api/packages/smoke');
    // Full package: typed values, JSON round-trip, back/cancel, explicit launch.
    await page.locator('#library-back').click();
    await page.locator(`[data-loop="${keys[2]}"]`).first().click();
    await page.locator('#loop-detail [data-create]').click();
    await page.getByLabel(/本次目标/).fill('用户的实际目标');
    await page.getByLabel(/实验次数/).fill('0');
    await page.locator('#launch-review').click();
    await page.locator('#launch-error').filter({hasText:'不能小于'}).waitFor();
    await page.getByLabel(/实验次数/).fill('4');
    await page.locator('#launch-mode').click();
    let values=JSON.parse(await page.locator('#create-inputs').inputValue());
    assert.equal(values.budget,4);assert.equal(values.enabled,false);
    values.settings={region:'changed'};values.extra=['kept'];
    await page.locator('#create-inputs').fill(JSON.stringify(values));
    await page.locator('#launch-mode').click();
    await page.locator('#launch-review').click();
    await page.locator('#launch-confirm').waitFor({state:'visible'});
    assert.equal(await runCount(),0);
    await page.locator('#launch-start').click();assert.equal(await runCount(),0);
    await page.locator('#launch-back').click();
    assert.equal(await page.getByLabel(/本次目标/).inputValue(),'用户的实际目标');
    await page.locator('#preparation-flow [data-map-node="initialize"]').click();
    await page.locator('#preparation-flow [data-map-details="initialize"] [data-candidate="secondary"] [data-map-choice]').click();
    const authorization='允许处理本测试的故障，不允许访问外部服务';
    await page.locator('#create-authorization').fill(authorization);
    await page.locator('#launch-review').click();
    await page.locator('#launch-confirm').waitFor({state:'visible'});
    await page.screenshot({path:path.join(root,'launch-confirm.png'),fullPage:true});
    await page.locator('#launch-ack').check();
    await page.locator('#launch-start').click();
    await page.locator('#create-dialog').waitFor({state:'hidden'});
    const runs=await (await page.request.get(url+'/api/runs')).json();assert.equal(runs.length,1);
    const run=await (await page.request.get(url+'/api/runs/'+runs[0].id)).json();
    assert.equal(run.settings.authorization,authorization);
    assert.equal(run.settings.bindings.initialize,'secondary');
    const owned=await waitRun(run.id,s=>Boolean(s.agent_sessions?.[0]));
    const denied=await page.request.post(url+'/api/runs/'+run.id+'/agent',{headers:{'X-Loop-Anything':'workspace'},data:{operation:'acquire'}});
    assert.equal(denied.status(),409);
    const deniedWrite=await page.request.post(url+'/api/runs/'+run.id+'/settings',{headers:{'X-Loop-Anything':'workspace'},data:{revision:owned.settings.revision,change:{authorization:'unexpected change'}}});
    assert.equal(deniedWrite.status(),409);
    const afterDenied=await (await page.request.get(url+'/api/runs/'+run.id)).json();assert.equal(afterDenied.settings.authorization,authorization);
    const todo=await (await page.request.get(url+'/api/runs/'+run.id+'/tasks')).json();assert(todo.waiting.some(t=>t.task_id==='first'));
    await page.locator('[data-tab="decisions"]').click();
    await page.locator('[data-read-agent-task="first"]').click();
    await page.locator('#manual-first').fill(JSON.stringify({settings:{objective:'人工初始化'},outputs:{result:'已提交的人工结果'}}));
    await page.locator('[data-complete-agent-task="first"]').click();
    await waitRun(run.id,s=>s.tasks.first.status==='completed');
    await page.locator('[data-finish-agent]').click();
    const manualRun=await waitRun(run.id,s=>!s.agent_sessions.length);
    assert.equal(manualRun.records[manualRun.tasks.first.spec.outputs.result.id][0].value,'已提交的人工结果');
    assert.equal(run.inputs.request,'用户的实际目标');assert.equal(run.inputs.budget,4);assert.equal(run.inputs.enabled,false);assert.deepEqual(run.inputs.extra,['kept']);assert.deepEqual(run.inputs.settings,{region:'changed'});
    assert.equal(writes.filter(u=>/\/api\/conversations\/[^/]+\/start$/.test(u)).length,1);
    // Author descriptions are editable without JSON and survive save/reopen.
    await page.locator('#loop_definitions-nav').click();
    await page.locator(`[data-loop="${keys[2]}"]`).first().click();
    await page.locator('[data-loop-tab="prepare"]').click();
    await page.locator('[data-setup-node="initialize"]').first().click();
    await page.locator('#loop_definition-editor').waitFor({state:'visible'});
    assert((await page.locator('#property-title').innerText()).includes('initialize'));
    await page.locator('.guide-author > summary').filter({hasText:'给使用者的说明'}).click();
    await page.locator('[data-guide="purpose"]').fill('修改后的用户说明');
    const unsavedURL=page.url();
    assert(unsavedURL.includes('#edit/'));
    await page.locator('#editor-back').click();
    await page.locator('#loop-detail').waitFor({state:'visible'});
    assert.equal(await page.locator('[data-loop-tab="prepare"]').getAttribute('aria-pressed'),'true');
    await page.goBack();await page.locator('#loop_definition-editor').waitFor({state:'visible'});
    assert.equal(await page.locator('[data-guide="purpose"]').inputValue(),'修改后的用户说明');
    await page.goForward();await page.locator('#loop-detail').waitFor({state:'visible'});
    await page.goBack();await page.locator('#loop_definition-editor').waitFor({state:'visible'});
    await page.locator('.guide-author > summary').filter({hasText:'Loop 操作手册'}).click();
    await page.locator('#handbook-instructions').fill('启动前：与用户讨论。节点执行：读写状态，安排后续任务。');
    await page.locator('#editor-save-status').filter({hasText:'已保存'}).waitFor();
    const drafts=await (await page.request.get(url+'/api/drafts')).json();assert.equal(drafts[0].loop_definition.guide.purpose,'修改后的用户说明');
    assert(page.url().includes('#edit/'+drafts[0].id));
    await page.reload();await page.locator('#loop_definition-editor').waitFor({state:'visible'});
    assert.equal(await page.locator('[data-guide="purpose"]').inputValue(),'修改后的用户说明');
    assert.equal(drafts[0].loop_definition.handbook.instructions,'启动前：与用户讨论。节点执行：读写状态，安排后续任务。');
    assert.equal((await (await page.request.get(url+'/api/catalog')).json()).find(c=>c.key===keys[2]).loop_definition.guide.purpose,'<script>不可执行的作者说明</script>');
    // Import does not start; successful installation lands on preparation.
    await page.locator('#loop_definitions-nav').click();await page.locator('#import-loop-package').click();
    await page.locator('#package-upload').setInputFiles(packageFile);
    await page.waitForFunction(()=>!document.getElementById('package-install').disabled);
    await page.locator('#package-install').click();await page.locator('#package-dialog').waitFor({state:'hidden'});
    assert.equal(await page.locator('[data-loop-tab="prepare"]').getAttribute('aria-pressed'),'true');assert.equal(await runCount(),1);
    await page.locator('[data-loop-tab="overview"]').click();
    await page.locator('#loop-runs a').click();await page.locator('#workspace').waitFor({state:'visible'});
    assert((await page.locator('#run-navigation').innerText()).includes('实际使用的 Loop 版本'));
    await page.locator('#run-navigation a').last().click();await page.locator('#loop-detail').waitFor({state:'visible'});
    assert(page.url().includes(encodeURIComponent(keys[2])));
    await page.goBack();await page.locator('#workspace').waitFor({state:'visible'});
    await page.goForward();await page.locator('#loop-detail').waitFor({state:'visible'});
    await page.locator('[data-loop-tab="prepare"]').click();
    // Build a batch through the public Timeline tool, then inspect the actual Run.
    const skipDefinition=JSON.parse(execFileSync('python3',['-c',"import sys,json;sys.path.insert(0,'tests');from test_packages import document;print(json.dumps(document()))"],{encoding:'utf8'}));
    const sb=skipDefinition.loop_definition;sb.id='ui-omit';sb.name='本轮省略验收';sb.nodes.initialize.plan_nodes=['prepare','finish'];
    sb.nodes.prepare={instructions:'Optional preparation',inputs:{},outputs:{result:{record_type:'text'}}};
    sb.plans={round:{parameters:{type:'object'},steps:{
      prepare:{node:'prepare',inputs:{}},
      finish:{node:'finish',after:['prepare'],inputs:{value:{from:'prepare',port:'result'}}}}}};
    skipDefinition.implementations=Object.fromEntries(Object.keys(sb.nodes).map(n=>[n,{kind:'agent'}]));
    const headers={'X-Loop-Anything':'workspace'};
    const published=await (await page.request.post(url+'/api/publish',{headers,data:skipDefinition})).json();
    const started=await (await page.request.post(url+'/api/tools',{headers,data:{tool:'start_run',arguments:{key:published.key,title:'UI omit',authorization:'Complete this local UI test'}}})).json();
    assert(started.ok,JSON.stringify(started));const created={id:started.run_id};
    assert(created.id,JSON.stringify(created));
    let state=await waitRun(created.id,s=>Boolean(s.agent_sessions?.[0])),init={task_id:sb.seed.id,token:state.agent_sessions[0].token};
    assert.equal(state.executions.length,0); // The user's Agent owns initialization; no background call.
    const tool=async(name,args)=>{const response=await page.request.post(url+'/api/tools',{headers,data:{tool:name,arguments:{...args,run_id:created.id,token:init.token}}});const result=await response.json();assert(response.ok(),JSON.stringify(result));return result;};
    await tool('build_plan',{name:'round',key:'round-1',round:'第1轮',values:{},steps:{prepare:{skip:true},finish:{inputs:{value:{record:'result'}}}}});
    const initialTask=await tool('read_task',{task_id:init.task_id});
    await tool('complete_task',{task_id:init.task_id,task_version:initialTask.task_version,envelope:{settings:{objective:'Reuse existing record',completion_rule:{op:'ge',args:[{path:['completed','finish']},1]}},outputs:{result:'existing dataset'}}});
    state=await waitRun(created.id,s=>Object.values(s.tasks).some(w=>w.spec.node==='finish' && w.status==='ready'));
    assert.equal(Object.keys(state.tasks).length,2);
    assert(!Object.values(state.tasks).some(w=>w.spec.node==='prepare'));
    const finish=Object.values(state.tasks).find(w=>w.spec.node==='finish');
    const finishTask=await tool('read_task',{task_id:finish.id});assert.equal(finishTask.inputs.value,'existing dataset');
    await page.goto(url+'/#run/'+created.id);await page.locator('#workspace').waitFor({state:'visible'});
    await page.locator('[data-tab="task-history"]').click();
    assert.equal(await page.locator('[data-task-row]').count(),2);
    await page.locator('[data-task-order="round"]').click();
    assert((await page.locator('.task-group').allTextContents()).some(t=>t.includes('第1轮')));
    await page.locator('[data-task-order="graph"]').click();
    assert.equal(await page.locator('.dependency-scroll [data-task-focus]').count(),2);
    assert.equal(await page.locator('[data-skip-action]').count(),0);
    await page.locator('.graph-panel > summary').click();
    assert.equal(await page.locator('#graph [data-map-node]').count(),Object.keys(state.loop_definition.nodes).length);
    assert.equal(Object.keys((await waitRun(created.id,s=>s.tasks)).tasks).length,2);
    assert((await page.locator('#graph').innerText()).includes('未安排 Task'));
    await page.screenshot({path:path.join(root,'ui-omitted.png'),fullPage:true});
    assert.equal(state.executions.filter(e=>e.node===sb.entry).length,1);
    assert.equal(state.tasks[init.task_id].status,'completed');
    await tool('complete_task',{task_id:finish.id,task_version:finishTask.task_version,envelope:{outputs:{done:true}}});
    await tool('finish',{});
    const completed=await waitRun(created.id,s=>s.status==='completed' && !s.agent_sessions?.[0]);
    assert.equal(completed.history.filter(h=>h.kind==='agent_acquired' && h.detail.kind==='background').length,0);
    await page.locator('#run-navigation a').last().click();await page.locator('#loop-detail').waitFor({state:'visible'});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(root,'mobile.png'),fullPage:true});
    assert(await page.locator('#loop_definitions-nav').isVisible());
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    // The UI submitted and released the manual Agent earlier; reuse that Run for controls.
    await page.setViewportSize({width:1440,height:1080});
    await page.goto(url+'/#run/'+run.id);await page.locator('#workspace').waitFor({state:'visible'});
    let responseEvent=page.waitForResponse(r=>r.url().endsWith('/command'));
    await page.locator('#pause-run').click();assert((await responseEvent).ok());await waitRun(run.id,s=>s.status==='paused');
    await page.reload();await page.locator('[data-tab="hooks"]').click();
    responseEvent=page.waitForResponse(r=>r.url().endsWith('/settings'));
    await page.locator('#hook-form button').click();assert((await responseEvent).ok());
    assert.equal((await waitRun(run.id,s=>s.settings.hooks.length===1)).settings.hooks[0].action,'pause');
    responseEvent=page.waitForResponse(r=>r.url().endsWith('/command'));
    await page.locator('#pause-run').click();assert((await responseEvent).ok());await waitRun(run.id,s=>s.status==='running');
    page.once('dialog',d=>d.accept());responseEvent=page.waitForResponse(r=>r.url().endsWith('/command'));
    await page.locator('#stop-run').click();assert((await responseEvent).ok());await waitRun(run.id,s=>s.status==='terminated');
    // Fresh editor structures come from the same author tools.
    await page.locator('#loop_definitions-nav').click();await page.locator('#new-loop_definition').click();
    await page.locator('#loop_definition-editor').waitFor({state:'visible'});
    assert.equal(await page.locator('#handbook-instructions').inputValue(),'');
    await page.locator('#add-node').click();await page.locator('#property-title').filter({hasText:'node_1'}).waitFor();
    const authored=await (await page.request.get(url+'/api/drafts')).json();
    const fresh=authored.find(d=>d.loop_definition.nodes.node_1);assert(fresh);
    assert.equal(fresh.loop_definition.nodes.node_1.outputs.result.record_type,'node_1.result');
    // Configure a real fallback node, disable it for a launch, then explicitly enable it.
    await page.locator('.guide-author > summary').filter({hasText:'Agent 兜底'}).click();
    await page.locator('#add-fallback-node').click();
    await page.locator('#property-title').filter({hasText:'fallback'}).waitFor();
    assert.equal(await page.locator('#bp-fallback').inputValue(),'fallback');
    const candidates={default:'first',options:{first:{kind:'agent'},chosen:{kind:'agent'}}};
    await page.locator('#add-author-candidate').click();
    await page.locator('[data-candidate-id]').fill('chosen');
    await page.locator('#author-default').selectOption('chosen');
    await page.locator('.guide-author > summary').filter({hasText:'Loop 操作手册'}).click();
    await page.locator('#handbook-instructions').fill('Read current issues and use the selected fallback Agent.');
    await page.locator('#editor-publish').click();await page.locator('#launch-page').waitFor({state:'visible'});
    assert.equal(await page.locator('#launch-fallback').inputValue(),'fallback');
    await page.locator('#launch-fallback').selectOption('');
    await page.locator('#preparation-flow [data-map-node="fallback"]').click();
    await page.locator('#preparation-flow [data-map-details="fallback"] [data-candidate="chosen"] [data-map-choice]').click();
    await page.locator('#launch-field-0').fill('Explicit fallback browser test');
    await page.locator('#launch-review').click();await page.locator('#launch-confirm').waitFor({state:'visible'});
    await page.locator('#launch-ack').check();await page.locator('#launch-start').click();
    await page.locator('#workspace').waitFor({state:'visible'});
    const fallbackRuns=await (await page.request.get(url+'/api/runs')).json();
    const fallbackRun=fallbackRuns.find(r=>r.id!==run.id && r.id!==created.id);assert(fallbackRun);
    const disabled=await waitRun(fallbackRun.id,r=>r.tasks.initialize.status==='blocked');
    assert.equal(disabled.settings.fallback_node,null);assert.deepEqual(disabled.agent_sessions,[]);
    await page.locator('.settings-panel > summary').click();
    await page.locator('#run-fallback').selectOption('fallback');
    await page.locator('#settings-form button[type="submit"]').click();await page.locator('#apply-change').click();
    const enabled=await waitRun(fallbackRun.id,r=>r.agent_sessions?.length && r.executions.some(e=>e.node==='fallback'));
    const fallbackExecution=enabled.executions.find(e=>e.node==='fallback');
    assert.equal(fallbackExecution.implementation_id,'chosen');
    assert.equal(enabled.settings.fallback_node,'fallback');
    assert(enabled.tasks[fallbackExecution.task_id].origin.fallback);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,cases:['read-only overview/flow','escaped author prose','non-mutating preflight','partial launch review allowed','final preflight recheck','typed JSON round-trip','explicit launch only','guide draft persistence','explicit fallback node, launch override and Run Agent selection','import to preparation','mobile navigation','draft back/forward preservation','saved draft reload','version-to-run links','user Agent creates/initializes without background wakeup and omits a batch step'],screenshots:root},null,2));
  }finally{
    if(browser)await browser.close();server.kill('SIGINT');
    await new Promise(resolve=>{if(server.exitCode!==null)resolve();else server.once('exit',resolve);});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
