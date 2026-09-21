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
   let r=await getRun(id),task=Object.values(r.tasks).find(t=>t.spec.node==='review');assert(task);assert.equal(task.spec.parameters.limit,3);
   await page.locator(`.process-task[data-task-focus="${task.id}"]`).click();await page.locator('[data-edit-task]').click();await page.locator('#task-parameters input[type="number"]').fill('5');await page.locator('#task-edit-reason').fill('调整后续参数');await apply();r=await getRun(id);assert.equal(r.tasks[task.id].spec.parameters.limit,5);assert.deepEqual(r.records,original.records);assert.deepEqual(r.executions,original.executions);
   await page.locator('[data-task-order="round"]').click();assert((await page.locator('.task-group').allTextContents()).some(t=>t.includes('第一组')));await page.locator('[data-task-order="graph"]').click();
   await page.screenshot({path:path.join(root,index===0?'research.png':'trip.png'),fullPage:true});
   const response=page.waitForResponse(r=>r.url().endsWith('/command'));await page.locator('#pause-run').click();assert((await response).ok());await waitRun(id,r=>r.tasks[task.id].status==='completed');
   await page.waitForTimeout(1600);await page.locator(`.process-task[data-task-focus="${task.id}"]`).click();assert((await page.locator('#task-detail').innerText()).includes('Checked'));await page.locator('[data-source-execution]').click();assert((await page.locator('#task-detail').innerText()).includes(index===0?'质量':'铁路'));
   // Add a whole batch through the same visible form and allow Engine to execute it.
   await page.locator('#add-run-batch').click();await page.locator('#batch-values input[type="number"]').fill('4');await page.locator('#batch-round').fill('第二组');await apply();await waitRun(id,r=>Object.values(r.tasks).filter(t=>t.status==='completed').length===3);
  }
  const order=await page.evaluate(()=>{
    const form=document.createElement('div');form.innerHTML=sourceField('values',{records:['b','a']},{type:'array'},[{id:'a'},{id:'b'}]);document.body.append(form);
    const original=readSources(form).values.records;
    form.querySelectorAll('[data-value-up]')[1].click();const reordered=readSources(form).values.records;
    form.querySelectorAll('[data-value-remove]').forEach(b=>b.click());const empty=readSources(form).values.records;form.remove();
    return {original,reordered,empty};
  });assert.deepEqual(order,{original:['b','a'],reordered:['a','b'],empty:[]});
  // Editing an installed plan preserves runtime expressions and nested schemas.
  const existing=await getRun(ids[0]);
  await page.locator('#loop_definitions-nav').click();
  await page.locator(`[data-loop="${existing.loop_key}"]`).first().click();
  await page.locator('[data-version-loop-definition]').first().click();
  await page.locator('[data-edit-edge="next"]').click();
  await page.locator('#editor-save-status').filter({hasText:'已保存'}).waitFor();
  const copied=(await (await page.request.get(base+'/api/drafts')).json()).find(d=>d.loop_definition.plans.next);
  assert.deepEqual(copied.loop_definition.plans.next.steps.review.inputs,existing.loop_definition.plans.next.steps.review.inputs);
  assert.deepEqual(copied.loop_definition.plans.next.steps.review.parameters,existing.loop_definition.plans.next.steps.review.parameters);
  assert.equal(copied.loop_definition.id,existing.loop_definition.id);
  await page.locator('[data-drag-node="review"]').click();await page.locator('#author-label').fill('持续检查');
  await page.locator('[data-plan-node="review"]').check();
  await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();
  await page.reload();await page.locator('[data-drag-node="review"]').click();
  assert.equal(await page.locator('#author-label').inputValue(),'持续检查');assert(await page.locator('[data-plan-node="review"]').isChecked());
  await page.locator('.editor-edges .planning').first().waitFor({state:'attached'});
  await page.locator('#editor-publish').click();await page.locator('#launch-page').waitFor({state:'visible'});
  const versions=await (await page.request.get(base+'/api/catalog')).json();
  assert.equal(versions.filter(c=>c.loop_definition.id===existing.loop_definition.id).length,2);
  assert.equal((await (await page.request.get(base+'/api/runs')).json()).length,2);
  assert.deepEqual((await getRun(ids[0])).loop_definition,existing.loop_definition);

  // Author a Loop from native forms and connect actual output/input ports.
  await page.locator('#loop_definitions-nav').click();await page.locator('#new-loop_definition').click();await page.locator('#add-node').click();await page.locator('#author-label').waitFor();await page.locator('#author-label').fill('通用处理');await page.locator('#author-instructions').fill('处理输入并保存结果');
  await page.locator('[data-add-author-port="inputs"]').click();await page.locator('#author-inputs > details > summary').click();await page.locator('#author-inputs [data-port-name]').fill('source');
  await page.locator('#add-author-skill').click();await page.locator('[data-skill-name]').fill('method');await page.locator('[data-skill-content]').fill('Read source and return a result.');
  await page.locator('#add-author-candidate').click();await page.locator('[data-candidate-id]').fill('local');await page.locator('[data-candidate-kind]').selectOption('command');await page.locator('[data-candidate-command]').fill('python3\n-c\nimport json;print(json.dumps({"outputs":{"result":"ok"}}))');await page.locator('#author-default').selectOption('local');
  await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();
  await page.locator('[data-port-node="initialize"][data-output-port="result"]').click();await page.locator('[data-port-node="node_1"][data-input-port="source"]').click();await page.waitForTimeout(500);
  await page.locator('#editor-save-status').filter({hasText:'已保存'}).waitFor();
  let drafts=await (await page.request.get(base+'/api/drafts')).json();let d=drafts.find(d=>d.loop_definition.nodes.node_1);assert(d);assert.equal(d.loop_definition.plans.default.steps.node_1.inputs.source.record,d.loop_definition.seed.outputs.result.id);assert.equal(d.implementations.node_1.default,'local');assert.equal(d.loop_definition.nodes.node_1.skills[0].name,'method');
  await page.locator('#add-node').click();await page.locator('#property-title').filter({hasText:'node_2'}).waitFor();await page.locator('[data-add-author-port="inputs"]').click();await page.locator('#author-inputs > details > summary').click();await page.locator('#author-inputs [data-port-name]').fill('source');await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();
  await page.locator('[data-port-node="node_1"][data-output-port="result"]').click();await page.locator('[data-port-node="node_2"][data-input-port="source"]').click();await page.locator('#connect-port-form button[type="submit"]').click();await page.locator('#connection-dialog').waitFor({state:'hidden'});
  await page.locator('#editor-save-status').filter({hasText:'已保存'}).waitFor();drafts=await (await page.request.get(base+'/api/drafts')).json();d=drafts.find(d=>d.loop_definition.nodes.node_2);assert.deepEqual(d.loop_definition.plans.default.steps.node_2.inputs.source,{from:'node_1',port:'result'});
  await page.screenshot({path:path.join(root,'authoring.png'),fullPage:true});
  await page.reload();await page.locator('[data-drag-node="node_1"]').click();assert.equal(await page.locator('#author-label').inputValue(),'通用处理');
  await page.locator('#remove-author-node').click();await page.locator('#author-removal').waitFor();
  assert((await page.locator('#author-removal').innerText()).includes('node_2'));
  await page.locator('#confirm-author-removal').click();await page.locator('#author-removal').waitFor({state:'detached'});
  await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();
  drafts=await (await page.request.get(base+'/api/drafts')).json();d=drafts.find(d=>d.loop_definition.nodes.node_2);
  assert(!d.loop_definition.nodes.node_1);assert(!d.loop_definition.plans.default.steps.node_2.inputs.source);
  await page.locator('#editor-publish').click();await page.locator('#editor-report.failure').waitFor();
  await page.locator('[data-port-node="initialize"][data-output-port="result"]').click();await page.locator('[data-port-node="node_2"][data-input-port="source"]').click();
  await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();

  await page.waitForFunction(()=>!document.getElementById('loop_definition-editor').inert);
  await page.setViewportSize({width:390,height:844});await page.goto(base+'/#run/'+ids[1]);await page.locator('[data-task-row]').first().waitFor();await page.screenshot({path:path.join(root,'mobile.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,runs:ids,screenshots:root,cases:['two different Loop outputs','explicit file results and path boundary','add/edit with historical records preserved','round grouping','script execution and input provenance','batch creation','author ports/Skill/implementation without JSON','entry result connection','output to input connection','draft reload','mobile layout']},null,2));
 }catch(error){const p=browser?.contexts()[0]?.pages()[0];if(p){console.error('FAILED PAGE',p.url(),(await p.locator('body').innerText()).slice(-2600));await p.screenshot({path:path.join(root,'failure.png'),fullPage:true});}throw error;}finally{if(browser)await browser.close();server.kill('SIGINT');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1});
