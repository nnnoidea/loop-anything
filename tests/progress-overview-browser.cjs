// Iterations reuse the same three nodes. Exercise the actual scheduler and its
// external monitor alongside a real subprocess failure, without contacting a cluster.
const {withPlatform,assert}=require('./browser-platform.cjs');
const {randomUUID}=require('node:crypto');
const path=require('node:path');

withPlatform(async({url,page,tool,api})=>{
  const nodes={prepare:'准备数据',train:'训练模型',score:'评估输出'};
  const bp={schema_version:2,id:'iterative-review',version:'1',name:'多轮评估',handbook:{instructions:'比较各轮结果。'},records:{},
    nodes:Object.fromEntries(Object.entries(nodes).map(([key,label])=>[key,{label,instructions:label,inputs:{},outputs:{}}]))};
  bp.records.metrics={type:'object'};
  bp.nodes.score.outputs={review:{record_type:'metrics'}};
  bp.nodes.score.readout=[{path:'outputs.review.accuracy',label:'验证准确率',unit:'%'},{path:'outputs.review.delta',label:'较基线提高',unit:'个百分点'}];
  bp.nodes.train.readout=[{path:'progress.progress',label:'验证批次'},{path:'progress.metrics.loss',label:'验证损失'}];
  const command=code=>['python3','-c',code];
  const report=obj=>command('print('+JSON.stringify(JSON.stringify(obj))+')');
  const done={kind:'command',command:report({event:'completed',envelope:{outputs:{}}})};
  const external={kind:'external',command:report({event:'submitted',external_id:'training-job',poll_after:.1}),
    observe:report({event:'progress',poll_after:120,detail:{external_status:'RUNNING',phase:'验证集评估',progress:'7 / 10',metrics:{loss:0.24}}})};
  const impl={prepare:{options:{done},default:'done'},train:{options:{done,watch:external},default:'done'},
    score:{options:{done:{kind:'command',command:report({event:'completed',envelope:{outputs:{review:{accuracy:87.5,delta:2.5,path:'/scratch/internal/results.json'}}}})},missing:{kind:'command',command:command("from pathlib import Path; Path('official_aggregate.json').read_text()")}},default:'done'}};
  const packed=await api('packages/export',{document:{loop_definition:bp,implementations:impl},assets:[]});
  const {key}=await api('packages/install',{base64:packed.base64});
  const old=await tool('start_run',{key,request_id:randomUUID(),title:'首批验证',objective:'比较 A、B 两组的准确率与基线，核对每轮验证结果。'});
  await api('runs/'+old.run_id+'/command',{action:'terminate'});
  const run=await tool('start_run',{key,timeline_id:old.timeline_id,request_id:randomUUID(),title:'多轮实验 · 结果核对'});
  const changes=[];
  for(let round=1;round<=6;round++)for(const batch of ['A','B'])for(const node of Object.keys(nodes)){
    const ref=node+'-'+batch+'-'+round, args={ref,key:ref,node_id:node,inputs:{},round:'第 '+round+' 轮'};
    if(round===6 && node==='train')args.implementation='watch';
    if(round===6 && batch==='B' && node==='score')args.implementation='missing';
    changes.push({tool:'add_task',arguments:args});
  }
  await tool('submit_run_request',{run_id:run.run_id,request_id:randomUUID(),operation:'edit_tasks',arguments:{changes}});
  let state, externalRows;
  const deadline=Date.now()+60000;
  do {
    state=await api('runs/'+run.run_id);
    externalRows=(await tool('read_monitor_dashboard',{})).external;
    if(Object.values(state.tasks).some(t=>t.status==='fault') && externalRows.length===2 && externalRows.every(e=>e.sampled_at))break;
    await new Promise(resolve=>setTimeout(resolve,250));
  }while(Date.now()<deadline);
  assert(externalRows.length===2 && externalRows.every(e=>e.metrics?.loss===0.24),'missing external readings');
  const app=await fetch(url+'/');
  assert.equal(app.headers.get('cache-control'),'no-cache');
  assert.match(await app.text(),/src="\/workspace\.js\?v=[a-f0-9]{16}"/);
  const runURL=url+'/api/runs/'+run.run_id;
  const encoded=await fetch(runURL,{headers:{'Accept-Encoding':'gzip'}});
  assert.equal(encoded.headers.get('content-encoding'),'gzip');
  assert.equal(encoded.headers.get('vary'),'Accept-Encoding');
  const plain=await fetch(runURL,{headers:{'Accept-Encoding':'gzip;q=0'}});
  assert.equal(plain.headers.get('content-encoding'),null);
  assert.equal((await plain.json()).id,(await encoded.json()).id);
  const portable=(await tool('export_timeline',{timeline_id:run.timeline_id})).document;
  const copied=(await tool('import_timeline',{document:portable,request_id:randomUUID()})).timeline;
  const copy=await tool('read_work_timeline',{timeline_id:copied.id});
  assert(copy.results.records.some(r=>r.summary?.includes('验证准确率 87.5 %')));
  await page.goto(url+'/#work/timelines/'+run.timeline_id);
  await page.locator('#work-focus').getByText(/验证准确率 87.5 %.*较基线提高 2.5 个百分点/).waitFor();
  const history=page.locator('#work-runs .loop-run-history');
  await history.getByText('多轮评估 · 1 次运行').waitFor();
  assert.equal(await history.locator('.timeline-run-link').isVisible(),false);
  await history.locator('summary').click();
  await history.getByRole('link',{name:/首批验证/}).waitFor();
  const currentLink=page.locator('#work-run-relation .timeline-run-link');
  await page.route(runURL,route=>route.fulfill({status:502,contentType:'text/plain',body:'Gateway unavailable'}),{times:1});
  await currentLink.click();
  await page.locator('#toast').filter({hasText:/无法打开运行详情.*HTTP 502/}).waitFor();
  let release;
  const delay=new Promise(resolve=>{release=resolve;});
  let requests=0;
  await page.route(runURL,async route=>{requests++;await delay;await route.continue();});
  try{
    await currentLink.click();
    await page.locator('#toast').filter({hasText:'正在打开运行详情…'}).waitFor();
    await currentLink.click();
    assert.equal(requests,1);
  }finally{release();}
  const hero=page.locator('#run-progress');
  await hero.getByText('找不到文件或目录 official_aggregate.json。',{exact:true}).waitFor();
  await page.unroute(runURL);
  assert(!(await hero.innerText()).includes('Traceback'));
  const graph=page.locator('.process-canvas');
  const toggles=graph.locator('[data-round-toggle]');
  assert.equal(await toggles.count(),6);
  assert.equal(await graph.locator('[data-task-row]').count(),3);
  const third=graph.locator('[data-round-toggle="第 3 轮"]');
  await third.click();
  assert.equal(await third.getAttribute('aria-expanded'),'true');
  assert.equal(await graph.locator('[data-task-row]').count(),9);
  assert((await graph.innerText()).includes('验证准确率 87.5 %'));
  assert(!(await graph.innerText()).includes('/scratch/'));
  const member=graph.locator('[data-task-row]').filter({hasText:'score-A-3'}).locator('.task-card-main');
  const memberId=await member.getAttribute('data-task-focus');
  await member.click();
  await page.reload();
  await page.locator('#task-detail').getByRole('heading',{name:'评估输出',exact:true}).waitFor();
  assert.equal(await page.locator('#task-detail').getAttribute('data-task'),memberId);
  await page.getByRole('button',{name:'关闭节点详情'}).click();
  await page.reload();await third.waitFor();
  assert.equal(await third.getAttribute('aria-expanded'),'true');
  assert.equal(await page.locator('#task-detail').isVisible(),false);
  await third.click();
  assert.equal(await graph.locator('[data-task-row]').count(),3);
  await graph.locator('[data-task-row]').filter({hasText:'score-B-6'}).locator('.task-card-main').click();
  await page.locator('#task-detail summary').filter({hasText:'原始错误与证据路径'}).click();
  assert((await page.locator('#task-detail').innerText()).includes('Traceback'));
  await page.locator('#task-round').selectOption('第 6 轮');
  assert.equal(await graph.locator('[data-task-row]').count(),3);
  assert.equal(await graph.locator('.round-card').count(),1);
  assert.equal(await graph.locator('[data-status="fault"]').count(),1);
  await page.locator('#task-round').selectOption('');
  await page.locator('[data-task-order="time"]').click();
  assert.equal(await page.locator('.process-list [data-task-row]').count(),36);
  await page.locator('[data-task-order="graph"]').click();
  for(const [name,width] of [['desktop',1280],['mobile',390]]){
    await page.setViewportSize({width,height:850});
    await page.goto(url+'/#run/'+run.run_id);await page.reload();await hero.getByText(/official_aggregate/).waitFor();await page.evaluate(()=>window.scrollTo(0,0));
    if(process.env.PROGRESS_SCREENSHOTS){
      await page.screenshot({path:path.join(process.env.PROGRESS_SCREENSHOTS,name+'-run.png')});
      await page.locator('.dependency-scroll').screenshot({path:path.join(process.env.PROGRESS_SCREENSHOTS,name+'-nodes.png')});
    }
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.equal(await graph.locator('.round-card').count(),6);
    if(width===390){
      await page.getByRole('button',{name:'适应宽度'}).click();
      assert(parseInt(await page.locator('#graph-scale').innerText(),10)>=85);
      assert(await page.locator('.dependency-scroll').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    }
    await page.goto(url+'/#work/monitors');
    const group=page.locator('.external-group');
    await group.getByText('训练模型',{exact:true}).waitFor();
    assert.equal(await group.count(),1);
    assert((await group.innerText()).includes('7 / 10'));
    assert((await group.innerText()).includes('验证损失') && (await group.innerText()).includes('0.24'));
    if(process.env.PROGRESS_SCREENSHOTS)await group.screenshot({path:path.join(process.env.PROGRESS_SCREENSHOTS,name+'-external.png')});
    assert.equal(await group.locator('.external-reading').count(),2);
    await group.locator('.external-reading a').last().click();
    await page.locator('#task-detail').getByRole('heading',{name:'训练模型',exact:true}).waitFor();
  }
}).catch(error=>{console.error(error);process.exitCode=1;});
