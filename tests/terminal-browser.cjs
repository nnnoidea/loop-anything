const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn,execFileSync}=require('node:child_process');const {chromium}=require('playwright');
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'loop-terminal-browser-')),db=path.join(root,'run.db');
 const seed=`import sys,json
from pathlib import Path
sys.path.insert(0,'tests')
from test_run_agent import definition
from loop_anything.runtime.store import Store
s=Store(sys.argv[1]);bp,impl=definition()
code="""import os,sys,json,time
from pathlib import Path
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
r=json.loads(Path(sys.argv[2]).read_text().split('Run context:'+chr(10),1)[1])
assert os.isatty(0)
import tty,termios
previous=termios.tcgetattr(0);tty.setraw(0);os.write(1,bytes([27])+b'[6n');assert os.read(0,64)==bytes([27])+b'[1;1R';termios.tcsetattr(0,termios.TCSANOW,previous)
print('READY: live terminal',flush=True)
print('<img src=x onerror=window.terminalXSS=true>',flush=True)
print(r['token'],flush=True)
answer=input()
print('RECEIVED: '+answer,flush=True)
t=RunTools(Store(sys.argv[1]),r['run_id'],r['token']);i=t.call('read_task',{'task_id':'init'})
t.call('register_agent_session',{'execution_id':r['execution_id'],'provider':'custom','session_id':'browser-native-123'})
t.call('complete_task',{'task_id':'init','task_version':i['task_version'],'envelope':{'settings':{'objective':'Browser terminal'},'outputs':{'result':answer}}})
t.call('finish',{})
time.sleep(60)
"""
resume_code="""import json,sys,time
from pathlib import Path
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
assert sys.argv[1]=='browser-native-123'
r=json.loads(Path(sys.argv[2]).read_text().split('Run context:'+chr(10),1)[1]);t=RunTools(Store(sys.argv[3]),r['run_id'],r['token'])
assert t.call('read_task',{'task_id':'init'})['task']['status']=='completed'
print('RESTORED browser-native-123',flush=True);input();t.call('finish',{});time.sleep(60)
"""
impl['init']={'kind':'agent','terminal':True,'agent_cli':'custom','resume_command':[sys.executable,'-u','-c',resume_code,'{{session_id}}','{{prompt_file}}',sys.argv[1]],'command':[sys.executable,'-u','-c',code,sys.argv[1],'{{prompt_file}}'],'cwd':str(Path.cwd())}
key=s.publish(bp,impl)['key'];run=s.create(key,'终端会话验收');draft=s.save_draft(bp,impl)
print(json.dumps({'run':run['id'],'draft':draft['id']}))`;
 const info=JSON.parse(execFileSync('python3',['-c',seed,db],{encoding:'utf8'}));
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const server=spawn('python3',['-m','loop_anything','--db',db,'serve','--port',String(port)],{env:{...process.env,PYTHONUNBUFFERED:'1',PYTHONPYCACHEPREFIX:'/tmp/loop-pycache',LOOP_ANYTHING_EDIT_PASSWORD:'terminal-test'},stdio:['ignore','pipe','pipe']});let browser,logs='';server.stderr.on('data',x=>logs+=x);
 try{
  await new Promise((r,j)=>{const t=setTimeout(()=>j(Error(logs)),10000);server.stdout.on('data',x=>{if(String(x).includes('workspace:')){clearTimeout(t);r();}});});
  browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1500,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(12000);const base='http://127.0.0.1:'+port;
  await page.goto(base+'/#run/'+info.run);await page.locator('.process-task[data-task-focus="init"]').click();await page.locator('[data-open-terminal]').waitFor();
  const current=await (await page.request.get(base+'/api/runs/'+info.run)).json(),eid=current.executions[0].id,url=base+`/api/runs/${info.run}/executions/${eid}/terminal`;
  assert.equal((await page.request.get(url)).status(),403);
  assert.equal((await page.request.post(url,{headers:{'X-Loop-Anything':'workspace'},data:{session_id:'missing',data:'no'}})).status(),403);
  await page.locator('#edit-access-button').click();await page.locator('#edit-password').fill('terminal-test');await page.locator('#edit-unlock-form button[type="submit"]').click();await page.locator('#edit-unlock-dialog').waitFor({state:'hidden'});
  await page.locator('[data-open-terminal]').click();await page.waitForFunction(()=>terminalView?.term.buffer.active.getLine(0)?.translateToString().includes('READY'));
  assert.equal(await page.evaluate(()=>window.terminalXSS),undefined);
  const first=await (await page.request.get(url)).json();assert(first.session.can_input);assert(!JSON.stringify(first.output).includes(current.executions[0].token));
  await page.locator('#terminal-dialog').screenshot({path:path.join(root,'terminal.png')});
  await page.locator('#terminal-close').click();const middle=await (await page.request.get(url)).json();assert.equal(middle.session.pid,first.session.pid);assert.equal(middle.session.state,'running');
  await page.reload();await page.locator('.process-task[data-task-focus="init"]').click();await page.locator('[data-open-terminal]').click();await page.waitForFunction(()=>terminalView?.canInput);
  await page.locator('#terminal-screen .xterm-helper-textarea').focus();await page.keyboard.insertText('浏览器补充要求');await page.keyboard.press('Enter');
  await page.waitForFunction(()=>document.getElementById('terminal-status').textContent.includes('退出码 0'));
  const final=await (await page.request.get(base+'/api/runs/'+info.run)).json();assert.equal(final.tasks.init.status,'completed');assert.equal(final.records['init.result'][0].value,'浏览器补充要求');assert.equal(final.agent_sessions.length,0);assert.equal(final.executions.length,1);
  const exited=await (await page.request.get(url)).json();assert(!exited.session.can_input);assert(exited.session.finished_by_tool);
  assert.equal((await page.request.post(url,{headers:{'X-Loop-Anything':'workspace'},data:{session_id:first.session.id,data:'late'}})).status(),409);
  await page.locator('#terminal-close').click();await page.locator('[data-open-terminal]').click();await page.waitForFunction(()=>terminalView?.cursor>0);assert((await page.evaluate(()=>{const b=terminalView.term.buffer.active;return Array.from({length:b.length},(_,i)=>b.getLine(i)?.translateToString()).join('\n');})).includes('RECEIVED: 浏览器补充要求'));
  await page.locator('#terminal-close').click();
  await page.locator('.process-task [data-task-result="init"]').click();await page.locator('#task-result-content').filter({hasText:'浏览器补充要求'}).waitFor();
  await page.locator('#task-result-dialog').screenshot({path:path.join(root,'task-result.png')});
  await page.locator('[data-result-resume]').click();await page.locator('#resume-agent-dialog').waitFor();
  assert.equal(await page.locator('#resume-agent-id').inputValue(),'browser-native-123');
  await page.locator('#resume-agent-message').fill('解释这次结果');await page.locator('#resume-agent-submit').click();
  await page.waitForFunction(()=>{const b=terminalView?.term.buffer.active;return b&&Array.from({length:b.length},(_,i)=>b.getLine(i)?.translateToString()).join('\n').includes('RESTORED browser-native-123');});
  await page.locator('#terminal-screen .xterm-helper-textarea').focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>document.getElementById('terminal-status').textContent.includes('退出码 0'));
  const resumed=await (await page.request.get(base+'/api/runs/'+info.run)).json();assert.deepEqual(resumed.records,final.records);assert.deepEqual(resumed.tasks,final.tasks);assert.equal(resumed.executions.length,1);assert.equal(resumed.agent_sessions.length,0);
  await page.locator('#terminal-close').click();
  await page.locator('.process-task [data-agent-session]').click();await page.locator('#resume-agent-id').fill('incorrect-native-id');await page.locator('#resume-agent-message').fill('Explain');await page.locator('#resume-agent-submit').click();
  await page.waitForFunction(()=>document.getElementById('terminal-status').textContent.includes('退出码 1'));await page.locator('#terminal-close').click();
  await page.locator('.process-task [data-agent-session]').click();assert.equal(await page.locator('#resume-agent-id').inputValue(),'incorrect-native-id');await page.locator('#resume-agent-id').fill('browser-native-123');await page.locator('#resume-agent-message').fill('Use the corrected native session');await page.locator('#resume-agent-submit').click();
  await page.waitForFunction(()=>terminalView?.canInput);await page.locator('#terminal-screen .xterm-helper-textarea').focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>document.getElementById('terminal-status').textContent.includes('退出码 0'));
  const correction=await (await page.request.get(base+'/api/runs/'+info.run)).json();assert.equal(correction.executions[0].native_session.id,'browser-native-123');assert.deepEqual(correction.tasks,final.tasks);assert.deepEqual(correction.records,final.records);
  assert((await (await page.request.get(url)).json()).sessions.some(s=>s.native_session?.id==='incorrect-native-id'));
  await page.locator('#terminal-close').click();
  const interrupted=`import sqlite3,json,time,sys
with sqlite3.connect(sys.argv[1]) as db:
 doc={'id':'audit-interrupted','run_id':sys.argv[2],'execution_id':sys.argv[3],'interactive':True,'state':'interrupted','created_at':time.time(),'cols':100,'rows':30,'error':'Interrupted fixture','native_session':{'provider':'custom','id':'browser-native-123'}}
 db.execute('INSERT INTO execution_sessions VALUES (?,?,?,?)',(doc['id'],doc['run_id'],doc['execution_id'],json.dumps(doc)))`;
  execFileSync('python3',['-c',interrupted,db,info.run,eid]);
  await page.locator('.process-task [data-agent-session]').click();await page.locator('#terminal-recover').waitFor({state:'visible'});await page.locator('#terminal-recover').click();await page.waitForFunction(()=>document.getElementById('terminal-status').textContent.includes('已确认停止'));
  assert.equal((await (await page.request.get(url)).json()).session.state,'released');assert.deepEqual((await (await page.request.get(base+'/api/runs/'+info.run)).json()).tasks,final.tasks);
  await page.locator('#terminal-close').click();
  await page.evaluate(id=>navigateTo({type:'editor',id}),info.draft);await page.locator('[data-drag-node="init"]').click();
  await page.locator('#author-label').fill('交互 Agent');await page.locator('#editor-save-status').filter({hasText:'草稿已保存'}).waitFor();
  const saved=(await (await page.request.get(base+'/api/drafts')).json()).find(d=>d.id===info.draft);assert(saved.implementations.init.options.default.terminal);assert.deepEqual(saved.implementations.init.options.default.command,current.executions[0].implementation.command);assert.deepEqual(saved.implementations.init.options.default.resume_command,current.executions[0].implementation.resume_command);
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,root,cases:['locked read/input','live ANSI terminal','same PID after close/reload','keyboard input','tool result and finish shutdown','replay and late-input rejection','editor config preservation','per-task result button','native session resume and immutable result','explicit interrupted-process recovery','correct failed native association with history preserved']},null,2));
 }catch(error){if(browser){const page=browser.contexts()[0]?.pages()[0];console.error((await page.locator('body').innerText()).slice(-1500));await page.screenshot({path:path.join(root,'failure.png'),fullPage:true});}console.error(logs.slice(-1500));throw error;}
 finally{if(browser)await browser.close();server.kill('SIGINT');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1});
