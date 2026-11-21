// An existing Run gains a live chart through the public HTTP tools.
const {withPlatform, assert}=require('./browser-platform.cjs');
const {randomUUID}=require('node:crypto');

withPlatform(async ({url,page,tool,api,startRun})=>{
  const {turn,session}=await startRun('研究概览验收');
  await tool('submit_run_request',{run_id:turn.run_id,request_id:randomUUID(),operation:'message',message:'加入评分对照'});
  const owner=await tool('claim_run',{...session,run_id:turn.run_id});
  const code='import json,subprocess,sys;d=json.load(sys.stdin);args={"timeline_id":d["timeline_id"],"as_of":d["as_of"]["results"]};rows=json.loads(subprocess.check_output([sys.executable,d["platform_client"],"read_work_results","--arguments",json.dumps(args)]))["records"];v=[r for r in rows if r["value"]=="scored"];print(json.dumps({"summary":"已评分 · "+str(len(v)),"series":[{"label":"A","points":[[0,0],[1,len(v)]]}]}))';
  await tool('update_run_method',{run_id:turn.run_id,token:owner.token,observations:{'评分对照':{
    description:'展示已完成的评分',on:{kind:'result',node:'wait'},steps:[{kind:'command',command:['python3','-c',code]}]}}});
  await page.goto(url+'/#work/timelines/'+turn.timeline_id);
  const section=page.locator('#timeline-observations');
  await section.getByText('已评分 · 0',{exact:true}).waitFor();
  await api('runs/'+turn.run_id+'/event',{event_id:'done',name:'measurement',payload:{value:'scored',report:'report.md'}});
  await section.getByText('已评分 · 1',{exact:true}).waitFor();
  assert(await section.locator('svg').isVisible());
  await section.locator('summary').click();
  await section.getByRole('button',{name:'立即生成'}).click();
  await section.getByText('已评分 · 1',{exact:true}).waitFor();
  if(process.env.OBSERVATION_SCREENSHOT)await page.screenshot({path:process.env.OBSERVATION_SCREENSHOT});
}).catch(error=>{console.error(error);process.exitCode=1;});
