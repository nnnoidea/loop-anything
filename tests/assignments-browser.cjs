// Exercise the web forms, real client, scheduler, wake and Timeline storage.
// The fixture CLI supplies deterministic Agent turns without using a model account.
const {withPlatform,assert}=require('./browser-platform.cjs');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'planning-agent-'));
fs.writeFileSync(path.join(dir,'codex'),`#!/usr/bin/env python3
import json,sys,subprocess
a=json.loads(sys.stdin.read().strip().splitlines()[-1])
print(json.dumps({'type':'thread.started','thread_id':'12000000-0000-4000-8000-000000000001'}),flush=True)
def call(tool,**args):
    proc=subprocess.run([sys.executable,a['platform_client'],tool,'--arguments',json.dumps(args)],text=True,capture_output=True)
    if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
    return json.loads(proc.stdout)
def append(key,text,refs):
    return call('append_timeline',timeline_id=a['timeline_id'],kind='progress',key=key,text=text,refs=refs)
task=a['assignment']
if task['kind']=='review':
    runs=call('list_runs',**a['scope'],view='revisions')['runs']
    facts=call('query_run_facts',source='runs',run_ids=[r['id'] for r in runs],group_by=['status'])
    append(task['report_key'],'本次检查了 '+str(len(runs))+' 个 Run。',[])
elif task['objective']=='等待用户选择':
    if task.get('reply'):
        assert 'resume' in sys.argv
        append('consented','已收到决定',[{'steps':[{'title':'记录决定','status':'done','note':task['reply']}]}])
    else:
        append('ask','请确认后续安排',[{'steps':[{'title':'记录决定','status':'needs_input','note':'请确认后续安排'}]}])
elif a['waits']:
    assert 'resume' in sys.argv
    call('acknowledge_wait',session_id=a['session_id'],session_token=a['session_token'],wait_id=a['waits'][0]['id'])
    append('done','条件已满足',[{'steps':[{'title':'确定范围','status':'done'},{'title':'等待暂停','status':'done','note':'已收到暂停信号'}]}])
else:
    assert sys.argv[sys.argv.index('--model')+1]=='gpt-6.2-sol'
    run=call('list_runs')['runs'][0]['id']
    call('wait_for',session_id=a['session_id'],session_token=a['session_token'],timeline_id=a['timeline_id'],key='pause',
         sources={'r':{'kind':'run','id':run}},condition={'op':'eq','args':[{'path':'r.status'},'paused']},message='等待测试 Run 暂停')
    append('plan','等待测试 Run 暂停',[{'steps':[{'title':'确定范围','status':'done'},{'title':'等待暂停','status':'waiting','note':'等待用户暂停 Run'}]}])
`,{mode:0o755});
process.env.PATH=dir+path.delimiter+process.env.PATH;
withPlatform(async({page,api,url,startRun})=>{
  const {turn}=await startRun('规划页面验收');
  await page.goto(url+'/#plans');
  await page.getByRole('button',{name:'新建规划',exact:true}).click();
  await page.getByLabel('想安排什么？').fill('等测试 Run 暂停，再整理结果。');
  await page.getByLabel('模型',{exact:true}).fill('gpt-6.2-sol');
  await page.getByRole('button',{name:'开始托管'}).click();
  const plan=page.locator('.assignment-detail');
  await plan.getByText('等待用户暂停 Run').waitFor({timeout:25000});
  assert.equal(await plan.locator('li[data-step=done]').count(),1);
  await page.reload();
  await plan.getByText('等待用户暂停 Run').waitFor();
  if(process.env.ASSIGNMENT_SCREENSHOTS)await page.screenshot({path:path.join(process.env.ASSIGNMENT_SCREENSHOTS,'plan.png')});
  await api('runs/'+turn.run_id+'/command',{action:'pause'});
  await plan.getByText('已收到暂停信号').waitFor({timeout:25000});
  assert.equal(await plan.locator('li[data-step=done]').count(),2);
  await page.getByRole('button',{name:'新建规划',exact:true}).click();
  await page.getByLabel('想安排什么？').fill('等待用户选择');
  await page.getByRole('button',{name:'开始托管'}).click();
  await page.getByRole('button',{name:'补充说明'}).click({timeout:20000});
  await page.getByLabel('补充说明',{exact:true}).fill('已确认');
  await page.getByRole('button',{name:'提交',exact:true}).click();
  await plan.getByText('已确认',{exact:true}).waitFor({timeout:20000});
  await page.locator('#loop_definitions-nav').click();
  await page.getByRole('link',{name:'RSI for loop',exact:true}).click();
  await page.getByRole('button',{name:'发起回顾',exact:true}).first().click();
  await page.getByText('本次将检查 1 个 Run').waitFor();
  await page.getByRole('button',{name:'开始回顾'}).click();
  await page.locator('.review-row').getByText('本次检查了 1 个 Run。').waitFor({timeout:20000});
  if(process.env.ASSIGNMENT_SCREENSHOTS)await page.screenshot({path:path.join(process.env.ASSIGNMENT_SCREENSHOTS,'rsi.png')});
  await page.getByRole('link',{name:/查看报告/}).click();
  await page.locator('#work-focus').getByText('本次检查了 1 个 Run。').waitFor();
  const reportURL=page.url();
  await page.goto(url+'/#rsi');
  await page.locator('.review-row [data-review-loop]').click();
  await page.getByText('本次将检查 1 个 Run').waitFor();
  await page.getByRole('button',{name:'开始回顾'}).click();
  await page.waitForFunction(async()=>{
    const data=await (await fetch('/api/assignments/review')).json();
    return data.items.length===2 && data.items.every(x=>x.state==='completed') && data.items[0].timeline_id===data.items[1].timeline_id;
  },null,{timeout:20000});
  await page.setViewportSize({width:390,height:800});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  if(process.env.ASSIGNMENT_SCREENSHOTS)await page.screenshot({path:path.join(process.env.ASSIGNMENT_SCREENSHOTS,'mobile.png')});
  await page.getByRole('link',{name:/查看报告/}).click();
  assert.equal(page.url(),reportURL);
  await page.goto(url+'/#loop_definitions');
  await page.locator('.catalog-card [data-loop],.catalog-card[data-loop]').first().click();
  await page.getByRole('link',{name:/查看此 Loop 的 Run/}).click();
  await page.locator('#run-list [data-run="'+turn.run_id+'"]').waitFor();
  assert.equal(await page.locator('#runs-loop').inputValue(),'browser');
  console.log('Plan launch, selected model, step display, wait/resume, RSI scope and report, filtered Runs passed.');
}).catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>fs.rmSync(dir,{recursive:true,force:true}));
