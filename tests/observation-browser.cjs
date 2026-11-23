// An existing Run gains a live chart through the public HTTP tools.
const {withPlatform, assert}=require('./browser-platform.cjs');
const {randomUUID}=require('node:crypto');

withPlatform(async ({url,page,tool,api,startRun})=>{
  const {turn}=await startRun('研究概览验收');
  const owner=await tool('acquire_run',{run_id:turn.run_id});
  const code='import json,subprocess,sys;d=json.load(sys.stdin);args={"timeline_id":d["timeline_id"],"as_of":d["as_of"]["results"]};rows=json.loads(subprocess.check_output([sys.executable,d["platform_client"],"read_work_results","--arguments",json.dumps(args)]))["records"];v=[r for r in rows if r["value"]=="scored"];print(json.dumps({"summary":"已评分 · "+str(len(v)),"series":[{"label":"A","points":[[0,0],[1,len(v)]]},{"label":"B","points":[[0,3],[1,3]]}]}))';
  await tool('update_run_method',{run_id:turn.run_id,token:owner.token,observations:{'评分对照':{
    description:'展示已完成的评分',on:{kind:'result',node:'wait'},steps:[{kind:'command',command:['python3','-c',code]}]}}});
  await page.goto(url+'/#work/timelines/'+turn.timeline_id);
  const section=page.locator('#timeline-observations');
  await section.getByText('已评分 · 0',{exact:true}).waitFor();
  await api('runs/'+turn.run_id+'/event',{event_id:'done',name:'measurement',payload:{value:'scored',report:'report.md'}});
  await section.getByText('已评分 · 1',{exact:true}).waitFor();
  const chart=section.locator('.observation-chart'), svg=chart.locator('svg');
  const tooltip=chart.locator('.chart-tooltip'), reading=tooltip.locator('[data-chart-reading]');
  await svg.scrollIntoViewIfNeeded();
  const locations=[];
  for(const [label,value] of [['A','0'],['B','3']]){
    const point=svg.locator(`[data-chart-label="${label}"][data-chart-position="0"]`);
    const at=await point.evaluate(el=>{
      const screen=new DOMPoint(el.cx.baseVal.value,el.cy.baseVal.value).matrixTransform(el.ownerSVGElement.getScreenCTM());
      return {x:screen.x,y:screen.y};
    });
    locations.push(at);
    await page.mouse.move(at.x,at.y);
    await tooltip.waitFor({state:'visible'});
    assert.equal(await reading.textContent(),value);
    assert.equal(await svg.locator('[data-chart-point].active').count(),1);
    assert.equal(await chart.locator('[data-chart-legend].active').textContent(),'● '+label);
  }
  await page.mouse.move(locations[0].x,(locations[0].y+locations[1].y)/2);
  await tooltip.waitFor({state:'hidden'});
  await svg.press('Home'); assert.equal(await reading.textContent(),'3');
  await svg.press('ArrowRight'); assert.equal(await reading.textContent(),'0');
  await svg.press('Escape'); await tooltip.waitFor({state:'hidden'});
  await section.locator('summary').click();
  await section.getByRole('button',{name:'立即生成'}).click();
  await section.getByText('已评分 · 1',{exact:true}).waitFor();
  if(process.env.OBSERVATION_SCREENSHOT)await page.screenshot({path:process.env.OBSERVATION_SCREENSHOT});
}).catch(error=>{console.error(error);process.exitCode=1;});
