// Exercise the web forms, real client, scheduler, wake and Timeline storage.
// The fixture CLI supplies deterministic Agent turns without using a model account.
const {withPlatform,assert}=require('./browser-platform.cjs');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'planning-agent-'));
const sample=path.join(dir,'gpu.json');
const monitor=path.join(dir,'monitor.py');
fs.writeFileSync(monitor,'from pathlib import Path\nimport sys\nsample=Path(sys.argv[1])\nif not sample.exists(): sys.exit("采集失败")\nprint(sample.read_text())\n');
fs.writeFileSync(path.join(dir,'codex'),`#!/usr/bin/env python3
import json,sys,subprocess,datetime,time
from pathlib import Path
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
    call('append_timeline',timeline_id=a['timeline_id'],kind='progress',key=task['report_key'],text='本次检查了 '+str(len(runs))+' 个 Run。',review=task['review'],review_html='<!DOCTYPE html><html lang="zh-CN"><title>运行回顾</title><style>h1{color:rgb(12,34,56)}</style><h1>本次检查概览</h1><script>document.body.dataset.ran="yes"</script></html>')
elif task['objective']=='重启后接着做':
    if task.get('reply'):
        assert 'resume' in sys.argv and '12000000-0000-4000-8000-000000000001' in sys.argv
        old=call('read_work_timeline',timeline_id=a['timeline_id'])
        assert any(e['key']=='saved' for e in old['entries'])
        append('continued','已从保存的进度继续',[{'steps':[{'title':'核对结果','status':'done'}]}])
    else:
        append('saved','核对中',[{'steps':[{'title':'核对结果','status':'active'}]}])
        for _ in range(450):
            if (Path(sys.argv[0]).parent/'exit-original').exists():break
            time.sleep(.1)
elif task['objective']=='等待 GPU 样本':
    if a['waits']:
        wait=a['waits'][0]
        assert wait['evidence']['gpu']['data']['free']==8
        call('acknowledge_wait',session_id=a['session_id'],session_token=a['session_token'],wait_id=wait['id'])
        append('capacity','资源就绪',[{'steps':[{'title':'可用 GPU 已达 8 张','status':'done'}]}])
    else:
        here=Path(sys.argv[0]).parent
        m=call('start_monitor',request_id='gpu',interval=1,script={'command':[sys.executable,str(here/'monitor.py'),str(here/'gpu.json')]})['monitor']
        call('wait_for',timeline_id=a['timeline_id'],session_id=a['session_id'],session_token=a['session_token'],key='gpu',
             sources={'gpu':{'kind':'monitor','id':m['id']}},condition={'op':'ge','args':[{'path':'gpu.data.free'},8]},message='等待 8 张 GPU')
        append('wait','检查资源',[{'steps':[{'title':'检查 GPU 资源','status':'waiting'}]}])
elif task['objective']=='到点采集再继续':
    if a['waits']:
        wait=a['waits'][0]
        assert wait['evidence']['job']['last_result']['stdout'].strip()=='42'
        assert wait['evidence']['job']['status']=='completed'
        call('acknowledge_wait',session_id=a['session_id'],session_token=a['session_token'],wait_id=wait['id'])
        append('done','定时任务已交回结果',[{'steps':[{'title':'采集结果 42','status':'done'}]}])
    else:
        root=str(Path(a['platform_client']).resolve().parents[3])
        registry=a['schedule_directory']
        cli=[sys.executable,'-m','loop_anything','client','local','--root',registry]
        definition=Path.cwd()/'job.json'
        definition.write_text(json.dumps({'name':'定时采集','at':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=5)).isoformat(),'command':[sys.executable,'-c','print(42)']}))
        job=json.loads(subprocess.check_output(cli+['register',str(definition)],cwd=root))['id']
        subprocess.Popen(cli+['start',job],cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        call('wait_for',timeline_id=a['timeline_id'],session_id=a['session_id'],session_token=a['session_token'],key='at',
             sources={'job':{'kind':'schedule','id':job}},condition={'op':'eq','args':[{'path':'job.terminal'},True]},message='等定时采集')
        append('plan','等待定时任务',[{'steps':[{'title':'定时采集','status':'waiting'}]}])
elif task['objective']=='等待用户选择':
    if task.get('reply'):
        assert 'resume' in sys.argv
        append('consented','已收到决定',[{'steps':[{'title':'记录决定','status':'done','note':task['reply']}]}])
    else:
        append('ask','请确认后续安排',[{'steps':[{'title':'记录决定','status':'needs_input','note':'请确认后续安排'}]}])
elif task['objective']=='支持修改的规划':
    message=task.get('reply')
    if message:
        assert 'resume' in sys.argv and '12000000-0000-4000-8000-000000000001' in sys.argv
        pending=task['pending_waits']
        assert task['reply_after_stop']==(message=='从停止处继续')
        if message=='调整等待':
            assert len(pending)==1 and pending[0]['message']=='等原条件'
            call('cancel_wait',session_id=a['session_id'],session_token=a['session_token'],wait_id=pending[0]['id'])
        else:
            assert not pending and not a['waits']
        if message!='调整等待':
            append(message,message,[{'steps':[{'title':'改动已接收','status':'done'}]}])
    if not message or message=='调整等待':
        run=call('list_runs')['runs'][0]['id']
        call('wait_for',session_id=a['session_id'],session_token=a['session_token'],timeline_id=a['timeline_id'],
             key='revised' if message else 'original',
             sources={'r':{'kind':'run','id':run}},condition={'op':'eq','args':[{'path':'r.status'},'completed']},
             message='等新条件' if message else '等原条件')
        append('revised-wait' if message else 'original-wait','等待结果',[{'steps':[{'title':'等待结果','status':'waiting'}]}])
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
withPlatform(async({page,api,tool,url,startRun,restartAfterCrash})=>{
  const {turn}=await startRun('规划页面验收');
  await page.goto(url+'/#plans');
  await page.getByRole('button',{name:'新建规划',exact:true}).click();
  await page.getByLabel('想安排什么？').fill('等测试 Run 暂停，再整理结果。\n\n这段原始指令应按需展开。');
  await page.getByLabel('模型',{exact:true}).fill('gpt-6.2-sol');
  await page.getByRole('button',{name:'开始托管'}).click();
  const plan=page.locator('.assignment-detail');
  await plan.locator('.plan-focus').getByText('等待测试 Run 暂停').waitFor({timeout:25000});
  await plan.locator('header').getByText('Agent 未运行',{exact:true}).waitFor();
  const firstDone=plan.locator('li[data-step=done] time');
  await firstDone.waitFor();
  const firstTimestamp=await firstDone.getAttribute('datetime');
  assert(Number.isFinite(Date.parse(firstTimestamp)));
  assert.equal(await plan.locator('li[data-step=waiting] time').count(),0);
  assert.equal(await plan.getByRole('heading',{level:2}).textContent(),'等测试 Run 暂停，再整理结果。');
  assert.equal(await plan.getByText('这段原始指令应按需展开。',{exact:false}).isVisible(),false);
  const stepDetails=plan.locator('li[data-step=waiting] details');
  assert.equal(await plan.getByText('等待用户暂停 Run').isVisible(),false);
  await stepDetails.locator('summary').click();
  await plan.getByText('等待用户暂停 Run').waitFor();
  assert.equal(await plan.locator('li[data-step=done]').count(),1);
  await page.reload();
  await plan.locator('.plan-focus').getByText('等待测试 Run 暂停').waitFor();
  assert.equal(await stepDetails.evaluate(detail=>detail.open),false);
  await plan.getByText('规划详情',{exact:true}).click();
  await plan.getByText('这段原始指令应按需展开。',{exact:false}).waitFor();
  await plan.getByText('规划详情',{exact:true}).click();
  await stepDetails.locator('summary').click();
  await page.setViewportSize({width:390,height:800});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.setViewportSize({width:1280,height:850});
  if(process.env.ASSIGNMENT_SCREENSHOTS)await page.screenshot({path:path.join(process.env.ASSIGNMENT_SCREENSHOTS,'plan.png')});
  await api('runs/'+turn.run_id+'/command',{action:'pause'});
  await plan.getByText('已收到暂停信号').waitFor({timeout:25000});
  assert.equal(await plan.locator('li[data-step=done] details').evaluate(detail=>detail.open),true);
  assert.equal(await plan.locator('li[data-step=done]').count(),2);
  assert.equal(await plan.locator('li[data-step=done] time').first().getAttribute('datetime'),firstTimestamp);
  await page.getByRole('button',{name:'新建规划',exact:true}).click();
  await page.getByLabel('想安排什么？').fill('支持修改的规划');
  await page.getByRole('button',{name:'开始托管'}).click();
  await plan.locator('.plan-focus').getByText('等原条件',{exact:true}).waitFor({timeout:20000});
  const editablePlanURL=page.url();
  const editableTimeline=await plan.getByRole('link',{name:'查看 Timeline →'}).getAttribute('href');
  const sendInstruction=async text=>{
    await plan.getByRole('button',{name:'发送指令',exact:true}).click();
    await page.getByRole('textbox',{name:'指令',exact:true}).fill(text);
    await page.getByRole('button',{name:'发送',exact:true}).click();
  };
  const planId=editablePlanURL.split('/').at(-1);
  const forwardedStop=await page.request.post(url+'/api/assignments/'+planId+'/stop',{
    headers:{'X-Loop-Anything':'workspace','X-Forwarded-Host':'proxy.example'},data:{}
  });
  assert.equal(forwardedStop.status(),403);
  await page.setExtraHTTPHeaders({'X-Forwarded-Host':'proxy.example'});
  await page.reload();
  await plan.locator('.plan-focus').getByText('等原条件',{exact:true}).waitFor();
  assert.equal(await plan.getByRole('button',{name:'停止规划',exact:true}).count(),0);
  await sendInstruction('调整等待');
  await plan.locator('.plan-focus').getByText('等新条件',{exact:true}).waitFor({timeout:20000});
  await page.setExtraHTTPHeaders({});
  await page.reload();
  page.once('dialog',dialog=>dialog.accept());
  await plan.getByRole('button',{name:'停止规划',exact:true}).click();
  await plan.locator('header .assignment-state[data-state=stopped]').waitFor();
  assert.equal(await plan.locator('.plan-focus').count(),0);
  assert.equal(await plan.locator('li[data-step=stopped]').count(),1);
  await sendInstruction('从停止处继续');
  await plan.locator('.plan-focus').getByText('从停止处继续',{exact:true}).waitFor({timeout:20000});
  await sendInstruction('完成后补充');
  await plan.locator('.plan-focus').getByText('完成后补充',{exact:true}).waitFor({timeout:20000});
  assert.equal(page.url(),editablePlanURL);
  assert.equal(await plan.getByRole('link',{name:'查看 Timeline →'}).getAttribute('href'),editableTimeline);
  await page.getByRole('button',{name:'新建规划',exact:true}).click();
  await page.getByLabel('想安排什么？').fill('等待用户选择');
  await page.getByRole('button',{name:'开始托管'}).click();
  await page.getByRole('button',{name:'补充说明'}).click({timeout:20000});
  await page.getByLabel('补充说明',{exact:true}).fill('已确认');
  await page.getByRole('button',{name:'提交',exact:true}).click();
  await plan.getByRole('heading',{level:2,name:'等待用户选择'}).waitFor({timeout:20000});
  await plan.locator('li[data-step=done] details summary').click({timeout:20000});
  await plan.getByText('已确认',{exact:true}).waitFor();
  await page.getByRole('button',{name:'新建规划',exact:true}).click();
  await page.getByLabel('想安排什么？').fill('到点采集再继续');
  await page.getByRole('button',{name:'开始托管'}).click();
  await plan.locator('li[data-step=waiting]').getByText('定时采集',{exact:true}).waitFor();
  await plan.getByText('采集结果 42',{exact:true}).waitFor({timeout:25000});
  await page.getByRole('button',{name:'新建规划',exact:true}).click();
  await page.getByLabel('想安排什么？').fill('等待 GPU 样本');
  await page.getByRole('button',{name:'开始托管'}).click();
  await plan.getByText('等待受阻',{exact:true}).waitFor({timeout:20000});
  await plan.locator('.assignment-error').filter({hasText:'采集失败'}).waitFor();
  fs.writeFileSync(sample,JSON.stringify({free:4}));
  await plan.getByText('等待条件',{exact:true}).waitFor({timeout:15000});
  assert.equal(await plan.locator('.assignment-error').count(),0);
  fs.writeFileSync(sample,JSON.stringify({free:8,done:true}));
  await plan.getByText('可用 GPU 已达 8 张',{exact:true}).waitFor({timeout:15000});
  await page.getByRole('button',{name:'新建规划',exact:true}).click();
  await page.getByLabel('想安排什么？').fill('重启后接着做');
  await page.getByRole('button',{name:'开始托管'}).click();
  await plan.getByText('核对结果',{exact:true}).waitFor();
  await plan.locator('header').getByText('Agent 运行中',{exact:true}).waitFor();
  const original=await plan.getByRole('link',{name:'查看 Timeline →'}).getAttribute('href');
  await restartAfterCrash();
  await page.reload();
  await plan.getByText('原进程仍在运行').waitFor();
  fs.writeFileSync(path.join(dir,'exit-original'),'');
  const recover=plan.getByRole('button',{name:'确认停止并继续'});
  await recover.waitFor({timeout:15000});
  page.once('dialog',dialog=>dialog.accept());
  await recover.click();
  await plan.locator('li[data-step=done]').getByText('核对结果',{exact:true}).waitFor({timeout:20000});
  assert.equal(await plan.getByRole('link',{name:'查看 Timeline →'}).getAttribute('href'),original);
  await page.locator('#loop_definitions-nav').click();
  await page.getByRole('link',{name:'RSI for loop',exact:true}).click();
  await page.getByRole('button',{name:'发起回顾',exact:true}).first().click();
  await page.getByText('本次将检查 1 个 Run').waitFor();
  await page.getByRole('button',{name:'开始回顾'}).click();
  const reportLink=page.getByRole('link',{name:/查看报告/});
  await reportLink.waitFor({timeout:20000});
  assert.equal(await page.locator('.review-row').getByText('本次检查了 1 个 Run。').count(),0);
  if(process.env.ASSIGNMENT_SCREENSHOTS)await page.screenshot({path:path.join(process.env.ASSIGNMENT_SCREENSHOTS,'rsi.png')});
  const [reportPage]=await Promise.all([page.waitForEvent('popup'),reportLink.click()]);
  await reportPage.getByRole('heading',{name:'本次检查概览'}).waitFor();
  assert.equal(await reportPage.locator('h1').evaluate(el=>getComputedStyle(el).color),'rgb(12, 34, 56)');
  assert.equal(await reportPage.locator('body').getAttribute('data-ran'),null);
  const reportURL=reportPage.url();
  await reportPage.close();
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
  const timeline_id=new URL(reportURL).searchParams.get('timeline_id');
  const firstPath=reportURL.slice(url.length);
  await page.locator(`.review-row a[target="_blank"]:not([href=${JSON.stringify(firstPath)}])`).waitFor();
  const second=new URL(await reportLink.getAttribute('href'),url);
  assert.equal(second.searchParams.get('timeline_id'),timeline_id);
  assert.notEqual(second.href,reportURL);
  const old=await tool('append_timeline',{timeline_id,key:'old-report',kind:'progress',text:'先前的纯文本记录',review:{loop_id:'browser',run_count:1}});
  assert.equal(old.entry.text,'先前的纯文本记录');
  await page.reload();
  await page.getByRole('link',{name:/查看回顾记录/}).waitFor();
  const published=await tool('append_timeline',{timeline_id,key:'timed-report',kind:'progress',text:'定时回顾发现新问题',
    review:{loop_id:'browser',run_count:1},review_html:'<!DOCTYPE html><title>定时报告</title><h1>发现新问题</h1>'});
  assert.equal(published.entry?.text,'定时回顾发现新问题',JSON.stringify(published));
  await tool('append_timeline',{timeline_id,key:'discussion',kind:'note',text:'继续讨论'});
  assert.equal((await api('assignments/review')).items[0].report_url,published.report_url);
  await page.reload();
  const [timed]=await Promise.all([page.waitForEvent('popup'),reportLink.click()]);
  await timed.getByRole('heading',{name:'发现新问题'}).waitFor();
  await timed.close();
  await page.goto(url+'/#loop_definitions');
  await page.locator('.catalog-card [data-loop],.catalog-card[data-loop]').first().click();
  await page.getByRole('link',{name:/查看此 Loop 的 Run/}).click();
  await page.locator('#run-list [data-run="'+turn.run_id+'"]').waitFor();
  assert.equal(await page.locator('#runs-loop').inputValue(),'browser');
  console.log('Plan launch, model, monitor failure/recovery, schedule wake, recovery after server crash and RSI reports passed.');
}).catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>fs.rmSync(dir,{recursive:true,force:true}));
