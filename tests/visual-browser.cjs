// End-to-end visual contracts, two unrelated Loop datasets, isolated database.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn,execFileSync}=require('node:child_process');const {chromium}=require('playwright');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-visual-')),database=path.join(root,'runs.sqlite3');
 const seed=`import sys,json
from pathlib import Path
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.packaging.packages import make_archive,install
s=Store(sys.argv[1]);p=PlatformTools(s);engine=Engine(s);runs=[]
for ident,title,result in [('research','研究流程 · 模拟验收',{'方案':'A','指标':[{'名称':'质量','数值':0.82}]}),('trip','差旅流程 · 模拟验收',{'目的地':'杭州','行程':[{'交通':'铁路','价格':580}]})]:
 b={'schema_version':2,'id':ident,'name':title,'version':'1','entry':'initial','defaults':{},'handbook':{'instructions':'Local browser scenario, simulated results.'},'records':{'result':{'type':'object'},'file':{'type':'string','format':'file'},'text':{'type':'string'}},'nodes':{'initial':{'label':'初始信息','initialize_timeline':True,'inputs':{},'outputs':{'result':{'record_type':'result'},'report':{'record_type':'file'},'outside':{'record_type':'file'}},'instructions':'Record input'},'review':{'label':'检查结果','inputs':{'source':{'type':'object'}},'outputs':{'result':{'record_type':'text'}},'parameter_schema':{'type':'object','properties':{'limit':{'type':'integer','minimum':1,'default':2}},'required':['limit']},'instructions':'Check supplied result'}},'seed':{'id':'initial','node':'initial','inputs':{},'outputs':{k:{'id':'initial.'+k} for k in ['result','report','outside']}},'plans':{'next':{'parameters':{'type':'object','properties':{'limit':{'type':'integer','minimum':1},'source':{'type':'string','default':'initial.result'}},'required':['limit','source']},'steps':{'review':{'node':'review','inputs':{'source':{'record':{'$':'values.source'}}},'parameters':{'limit':{'$':'values.limit'}}}}}}}
 b['plans']['next']['parameters']['properties']['enabled']={'type':'boolean'}
 b['plans']['next']['parameters']['required'].append('enabled')
 b['plans']['next']['steps']['review']['when']={'path':'values.enabled'}
 command=['python3','-c','import json; print(json.dumps({"outputs":{"result":"Checked"}}))']
 key=install(s,make_archive({'loop_definition':b,'implementations':{'initial':{'kind':'agent'},'review':{'kind':'command','command':command}}},{'report.md':(('# '+title+'\\nReady').encode(),False)}))['key']
 a=p.call('start_run',{'key':key,'title':title,'authorization':'Simulated browser acceptance'})
 def tool(name,args):return p.call(name,dict(args,run_id=a['run_id'],token=a['token']))
 info=tool('read_task',{'task_id':'initial'})
 tool('complete_task',{'task_id':'initial','task_version':info['task_version'],'envelope':{'settings':{'objective':title},'outputs':{'result':result,'report':'report.md','outside':'../../not-authorized'}}})
 tool('finish',{})
 engine.command(a['run_id'],'pause')
 runs.append(a['run_id'])
engine.close();print(json.dumps(runs))`;
 const ids=JSON.parse(execFileSync('python3',['-c',seed,database],{encoding:'utf8'}));
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const server=spawn('python3',['-m','loop_anything','--db',database,'serve','--port',String(port)],{env:{...process.env,PYTHONUNBUFFERED:'1'},stdio:['ignore','pipe','pipe']});let browser;let logs='';server.stderr.on('data',x=>logs+=x);
 try{
  await new Promise((res,rej)=>{const t=setTimeout(()=>rej(new Error('Server timeout '+logs)),10000);server.stdout.on('data',d=>{if(String(d).includes('workspace:')){clearTimeout(t);res();}});});
  browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1560,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(12000);const base='http://127.0.0.1:'+port;
  const getRun=async id=>(await page.request.get(base+'/api/runs/'+id)).json();
  const waitRun=async(id,pred)=>{for(let i=0;i<70;i++){const r=await getRun(id);if(pred(r))return r;await page.waitForTimeout(120);}throw new Error('Run timeout '+id+' '+logs);};
  const apply=async()=>{await page.locator('#task-edit-submit').click();await page.locator('#task-edit-submit').filter({hasText:'应用修改'}).waitFor();const response=page.waitForResponse(r=>r.url().endsWith('/tasks')&&r.request().method()==='POST');await page.locator('#task-edit-submit').click();const res=await response;assert(res.ok(),await res.text());await page.locator('#task-edit-dialog').waitFor({state:'hidden'});};
  for(const [index,id] of ids.entries()){
   await page.goto(base+'/#run/'+id);await page.waitForFunction(id=>document.getElementById('run-id').textContent.includes(id),id);await page.locator('[data-task-row]').first().waitFor();const original=await getRun(id);
   await page.locator('.process-task[data-task-focus="initial"]').click();assert((await page.locator('#task-detail').innerText()).includes(index===0?'质量':'铁路'));
   const file=page.locator('#task-detail a').filter({hasText:'report.md'});const res=await page.request.get(base+await file.getAttribute('href'));assert(res.ok());assert((await res.text()).includes('Ready'));
   const bad=page.locator('#task-detail a').filter({hasText:'not-authorized'});assert.equal((await page.request.get(base+await bad.getAttribute('href'))).status(),404);
   await page.locator('#add-run-task').click();await page.locator('#task-inputs [data-source-mode]').selectOption('record');await page.locator('#task-inputs [data-source-record]').selectOption('initial.result');await page.locator('#task-parameters input[type="number"]').fill('3');await page.locator('#new-task-round').fill('第一组');await apply();
   let r=await getRun(id),task=Object.values(r.tasks).find(t=>t.spec.node==='review');assert(task);assert.equal(task.spec.parameters.limit,3);assert.equal(task.revision,1);
   await page.locator(`.process-task[data-task-focus="${task.id}"]`).click();await page.locator('[data-edit-task]').click();await page.locator('#task-parameters input[type="number"]').fill('5');await page.locator('#task-edit-reason').fill('调整后续参数');await apply();r=await getRun(id);assert.equal(r.tasks[task.id].spec.parameters.limit,5);assert.equal(r.tasks[task.id].revision,2);await page.locator('[data-task-revision]').filter({hasText:'修订 2'}).waitFor();assert.deepEqual(r.records,original.records);assert.deepEqual(r.executions,original.executions);
   await page.locator('[data-task-order="round"]').click();assert((await page.locator('.task-group').allTextContents()).some(t=>t.includes('第一组')));await page.locator('[data-task-order="graph"]').click();
   await page.screenshot({path:path.join(root,index===0?'research.png':'trip.png'),fullPage:true});
   const response=page.waitForResponse(r=>r.url().endsWith('/command'));await page.locator('#pause-run').click();assert((await response).ok());await waitRun(id,r=>r.tasks[task.id].status==='completed');
   await page.waitForTimeout(1600);await page.locator(`.process-task[data-task-focus="${task.id}"]`).click();assert((await page.locator('#task-detail').innerText()).includes('Checked'));await page.locator('[data-source-execution]').click();assert((await page.locator('#task-detail').innerText()).includes(index===0?'质量':'铁路'));
   // Add a whole batch through the same visible form and allow Engine to execute it.
   const beforeOmission=await getRun(id);
   await page.locator('#add-run-batch').click();await page.locator('#batch-values input[type="number"]').fill('4');
   await page.locator('#task-edit-submit').click();await page.locator('#task-edit-review .omitted-summary').waitFor();
   assert.deepEqual((await getRun(id)).tasks,beforeOmission.tasks,'Preview wrote a Task');
   await page.locator('#task-edit-dialog').screenshot({path:path.join(root,'omission-preview.png')});
   await page.locator('#task-edit-submit').click();await page.locator('#task-edit-dialog').waitFor({state:'hidden'});
   const omittedRun=await getRun(id);assert.deepEqual(omittedRun.tasks,beforeOmission.tasks);assert(omittedRun.history.some(h=>h.kind==='plan_built'&&h.detail.omitted[0]?.reason==='condition_false'));
   await page.locator('.omitted-steps > summary').click();await page.locator('.omitted-steps').screenshot({path:path.join(root,'omission-history.png')});
   await page.locator('#add-run-batch').click();await page.locator('#batch-values input[type="number"]').fill('4');await page.locator('#batch-values select[data-value-type="boolean"]').selectOption('true');await page.locator('#batch-round').fill('第二组');await apply();await waitRun(id,r=>Object.values(r.tasks).filter(t=>t.status==='completed').length===3);
  }
  // Updating the graph layout must preserve the selected node's detail layer.
  await page.locator('.graph-panel > summary').click();
  await page.locator('#graph [data-map-node="review"]').click();
  await page.locator('#graph [data-map-details="review"] [data-node-view="relations"]').click();
  await page.setViewportSize({width:1480,height:1000});
  await page.waitForTimeout(150);
  assert.equal(await page.locator('#graph [data-map-details="review"] [data-node-panel="relations"]').isVisible(),true,'Graph refresh lost the chosen detail layer');
  await page.setViewportSize({width:1560,height:1000});
  await page.locator('#graph [data-map-node="initial"]').click();
  assert.equal(await page.locator('#graph [data-map-details="initial"] [data-node-panel="execution"]').isVisible(),true);
  await page.goto(base+'/#run/'+ids[0]);await page.waitForFunction(id=>document.getElementById('run-id').textContent.includes(id),ids[0]);
  assert.equal(await page.locator('#graph [data-map-details]:not([hidden])').count(),0,'A different Run inherited the prior graph selection');
  const order=await page.evaluate(()=>{
    const form=document.createElement('div');form.innerHTML=sourceField('values',{records:['b','a']},{type:'array'},[{id:'a'},{id:'b'}]);document.body.append(form);
    const original=readSources(form).values.records;
    form.querySelectorAll('[data-value-up]')[1].click();const reordered=readSources(form).values.records;
    form.querySelectorAll('[data-value-remove]').forEach(b=>b.click());const empty=readSources(form).values.records;form.remove();
    return {original,reordered,empty};
  });assert.deepEqual(order,{original:['b','a'],reordered:['a','b'],empty:[]});
  // Reading and light edits preserve every complex rule and historical Run.
  const existing=await getRun(ids[0]);
  await page.goto(base+'/#loop/'+existing.loop_key+'/flow');await page.locator('[data-version-loop-definition]').first().click();
  await page.locator('#reader-light > summary').click();const before=(await (await page.request.get(base+'/api/drafts')).json())[0];
  await page.locator('#bp-description').fill('Readable overview');await page.waitForFunction(()=>!editor.dirty);
  const saved=(await (await page.request.get(base+'/api/drafts')).json()).find(d=>d.id===before.id);
  assert.deepEqual(saved.loop_definition,{...before.loop_definition,description:'Readable overview'});assert.deepEqual(saved.loop_definition.plans,before.loop_definition.plans);assert.deepEqual(saved.implementations,before.implementations);
  await page.locator('[data-editor-layer="nodes"]').click();assert.equal(await page.locator('#add-node').count(),0);assert.equal(await page.locator('[data-input-port]').count(),0);
  await page.locator('[data-editor-card="review"] [data-editor-implementation]').first().click();
  assert(await page.locator('.reader-candidate .lifecycle-matrix').isVisible());assert.equal(await page.locator('[data-candidate-command]').count(),0);
  assert.deepEqual((await getRun(ids[0])).loop_definition,existing.loop_definition);
  await page.screenshot({path:path.join(root,'read-only-implementation.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.goto(base+'/#run/'+ids[1]);await page.locator('[data-task-row]').first().waitFor();await page.screenshot({path:path.join(root,'mobile.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,runs:ids,screenshots:root,cases:['two different Loop outputs','explicit file results and path boundary','add/edit with historical records preserved','round grouping','script execution and input provenance','batch creation','read-only detailed implementation','light edit preserves complex definitions','no port editing','draft reload','mobile layout']},null,2));
 }catch(error){const p=browser?.contexts()[0]?.pages()[0];if(p){console.error('FAILED PAGE',p.url(),(await p.locator('body').innerText()).slice(-2600));await p.screenshot({path:path.join(root,'failure.png'),fullPage:true});}throw error;}finally{if(browser)await browser.close();server.kill('SIGINT');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1});
