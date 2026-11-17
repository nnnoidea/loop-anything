// Isolated Chrome acceptance for delegated startup and steward replacement. No model calls.
const assert=require('node:assert/strict');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-steward-browser-'));
const setup="import json,os,sys\nfrom pathlib import Path\nfrom loop_anything.runtime.store import Store\nfrom loop_anything.runtime.engine import Engine\nfrom loop_anything.interfaces.platform_tools import PlatformTools\nroot=Path(sys.argv[1]);store=Store(root/'workspace.sqlite3');engine=Engine(store);tools=PlatformTools(store)\ncode=\"\"\"import json,sys\nfrom loop_anything.interfaces.agent_tasks import RunTools\nfrom loop_anything.runtime.store import Store\nc=json.loads(sys.stdin.read().split('Run context:'+chr(10),1)[1]);t=RunTools(Store(sys.argv[1]),c['run_id'],c['token'])\ndef complete(task, outputs, **envelope):\n i=t.call('read_task',{'task_id':task});t.call('report_task',{'task_id':task,'event':'completed','report_id':task,'envelope':dict(outputs=outputs,**envelope)})\nstate=t.call('read_timeline',{})\nif not t.call('read_run',{})['run']['initialized']:\n complete('initialize',{},settings={'objective':'Browser test'})\n t.call('read_timeline',{});t.call('add_task',{'key':'wait','node_id':'work','inputs':{}})\nif c['steward_request']['operation']=='edit_tasks':\n t.call('read_timeline',{});t.call('edit_tasks',c['steward_request']['arguments'])\ncomplete(c['task_id'],{'decision':{'answer':'Startup and management verified'}});t.call('finish',{})\n\"\"\"\nfor ident in ['first','second']:\n tools.call('communication_config',{'operation':'agent','agent_id':ident,'agent':{'name':ident,'description':'Browser test steward','local':True,'implementation':{'kind':'agent','cwd':str(Path.cwd()),'command':[sys.executable,'-c',code,store.filename]}}})\nd=tools.call('create_loop',{'name':'Browser steward workflow'})\nd=tools.call('set_loop',{'draft_id':d['draft_id'],'revision':d['revision'],'handbook':'Initialize and wait for results.'})\nd=tools.call('put_node',{'draft_id':d['draft_id'],'revision':d['revision'],'node_id':'work','instructions':'Wait for the user event','outputs':[]})\nd=tools.call('set_implementation',{'draft_id':d['draft_id'],'revision':d['revision'],'node_id':'work','kind':'event','event':'ready','wait':{'key':'ready'}})\nkey=tools.call('publish_loop',{'draft_id':d['draft_id'],'revision':d['revision']})['key'];print(key);engine.close()\n";
fs.writeFileSync(path.join(root,'setup.py'),setup);
const database=path.join(root,'workspace.sqlite3');
const env={...process.env,PYTHONPATH:process.cwd()+path.delimiter+(process.env.PYTHONPATH||''),PYTHONDONTWRITEBYTECODE:'1',LOOP_ANYTHING_IDENTITY_DIR:path.join(root,'identity')};
const args=['-m','loop_anything','--db',database,'serve','--port','0','--allow-sleep'];
const children=new Set();
function processStart(program,args){const child=spawn(program,args,{env,stdio:['ignore','pipe','pipe']});children.add(child);child.on('exit',()=>children.delete(child));child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');return child;}
async function until(check){for(let i=0;i<150;i++){const result=await check();if(result)return result;await new Promise(r=>setTimeout(r,100));}throw new Error('Timed out');}
async function startServer(){const child=processStart('python3',args);let output='';child.stdout.on('data',s=>output+=s);child.stderr.on('data',s=>output+=s);const url=await until(()=>{assert.equal(child.exitCode,null,output);return output.match(/Loop Anything workspace: (http:\/\/127\.0\.0\.1:\d+)/)?.[1];});return [child,url];}
function stop(child){if(child.exitCode!==null)return;return new Promise(resolve=>{child.once('exit',resolve);child.kill();});}
function register(id,definition){const file=path.join(root,id+'.json');fs.writeFileSync(file,JSON.stringify(definition));execFileSync('python3',['-m','loop_anything','client','local','--root',database+'.schedules','register',file,'--id',id],{env});}
(async()=>{
 const key=execFileSync('python3',[path.join(root,'setup.py'),root],{env}).toString().trim();
 const [server,url]=await startServer();
 const chrome=processStart(process.env.CHROME_BIN||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless','--no-first-run','--no-default-browser-check','--disable-background-networking','--remote-debugging-port=0',`--user-data-dir=${path.join(root,'chrome')}`]);
 let log='';chrome.stderr.on('data',s=>log+=s);
 const port=await until(()=>{assert.equal(chrome.exitCode,null,log);return log.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)/)?.[1];});
 const tabs=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
 const ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
 let seq=0;const pending=new Map(),exceptions=[];
 ws.addEventListener('message',({data})=>{const msg=JSON.parse(data);if(msg.id){const [ok,fail]=pending.get(msg.id);pending.delete(msg.id);msg.error?fail(new Error(msg.error.message)):ok(msg.result);}if(msg.method==='Runtime.exceptionThrown')exceptions.push(msg.params.exceptionDetails);});
 function send(method,params={}){return new Promise((resolve,reject)=>{const id=++seq;pending.set(id,[resolve,reject]);ws.send(JSON.stringify({id,method,params}));});}
 async function evaluate(expression){const reply=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(reply.exceptionDetails)throw new Error(JSON.stringify(reply.exceptionDetails));return reply.result.value;}
 await send('Runtime.enable');await send('Page.navigate',{url});
 await until(()=>evaluate(`document.readyState==='complete' && catalog.length>0`));
 await evaluate(`openCreate(${JSON.stringify(key)})`);
 await evaluate(`document.querySelector('#launch-start').click()`);
 await until(()=>evaluate(`document.querySelector('#launch-error').textContent.includes('请选择运行管家')`));
 assert.equal(await evaluate(`document.querySelector('#create-dialog').open`),true);
 await evaluate(`document.querySelector('#launch-steward').value='first';document.querySelector('#launch-start').click()`);
 await until(()=>evaluate(`!!document.querySelector('#run-steward') && !document.querySelector('#run-steward').hidden`));
 await until(()=>evaluate(`Object.values(run.steward_requests).some(r=>r.operation==='start'&&r.status==='completed')`));
 assert.ok(await evaluate(`document.querySelector('#run-steward').textContent.includes('first')`));
 await until(()=>evaluate(`Object.values(run.tasks).some(t=>t.spec.node==='work' && t.status==='waiting')`));
 await evaluate(`openTaskEdit('cancel',Object.values(run.tasks).find(t=>t.spec.node==='work').id)`);
 assert.equal(await evaluate(`document.querySelector('#task-edit-submit').textContent`),'提交给管家');
 await evaluate(`document.querySelector('#task-edit-reason').value='Stop the test wait';document.querySelector('#task-edit-submit').click()`);
 await until(()=>evaluate(`Object.values(run.tasks).some(t=>t.spec.node==='work' && t.status==='cancelled')`));
 assert(await evaluate(`Object.values(run.steward_requests).some(r=>r.operation==='edit_tasks')`));

 await evaluate(`document.querySelector('[data-steward-requests]').click()`);
 await until(()=>evaluate(`document.querySelector('#detail-dialog').open && document.querySelector('#detail-content').textContent.includes('Startup and management verified')`));
 await evaluate(`document.querySelector('#detail-dialog').close();document.querySelector('[data-steward-switch]').click()`);
 await until(()=>evaluate(`!!document.querySelector('#steward-select')`));
 await evaluate(`document.querySelector('#steward-select').value='second';document.querySelector('#steward-confirm').click()`);
 await until(()=>evaluate(`run.steward.agent_id==='second' && run.steward.generation===2`));
 await until(()=>evaluate(`Object.values(run.steward_requests).every(r=>r.status==='completed')`));
 assert.deepEqual(exceptions,[]);
 const screenshot=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(root,'steward.png'),Buffer.from(screenshot.data,'base64'));
 ws.close();await stop(server);await stop(chrome);
 console.log('Chrome passed managed startup, request results, fresh-session takeover and page rendering.');
 console.log(path.join(root,'steward.png'));
})().catch(e=>{console.error(e);process.exitCode=1;for(const child of children)child.kill();});
