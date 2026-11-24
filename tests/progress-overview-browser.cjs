// Iterations reuse the same three nodes. Exercise the actual scheduler and its
// external monitor alongside a real subprocess failure, without contacting a cluster.
const {withPlatform,assert}=require('./browser-platform.cjs');
const {randomUUID}=require('node:crypto');
const path=require('node:path');

withPlatform(async({url,page,tool,api,startRun})=>{
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
  const runOwner=await tool('acquire_run',{run_id:run.run_id});
  try{
    await tool('update_run_method',{run_id:run.run_id,token:runOwner.token,observations:{'运行指标样例':{on:null,steps:[{kind:'command',
      command:report({series:[{label:'准确率',points:[[1,82],[2,87.5]]}]})}]}}});
  }finally{await tool('finish',{run_id:run.run_id,token:runOwner.token});}
  const changes=[];
  for(let round=1;round<=6;round++)for(const batch of ['A','B'])for(const node of Object.keys(nodes)){
    const ref=node+'-'+batch+'-'+round, args={ref,key:ref,node_id:node,inputs:{},round:'第 '+round+' 轮'};
    if(node==='train')args.after_refs=['prepare-'+batch+'-'+round];
    if(round<6&&node==='score')args.after_refs=['train-'+batch+'-'+round];
    if(round>1&&round<6&&node==='prepare')args.after_refs=['score-A-'+(round-1),'score-B-'+(round-1)];
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
  const workspaceURL=runURL+'?view=workspace&tab=task-history';
  const overview=await (await fetch(workspaceURL)).json();
  assert.equal(overview.id,run.run_id);
  assert.equal(Object.keys(overview.tasks).length,36);
  assert.equal(overview.history.length,0);
  assert.equal(Object.hasOwn(overview,'records'),false);
  assert.deepEqual(overview.loop_definition.records,{});
  assert(overview.executions.every(e=>!Object.hasOwn(e,'inputs')&&!Object.hasOwn(e,'task_spec')));
  assert(state.history.length>50);
  assert.equal((await fetch(runURL+'?view=workspace&tab=history')).status,404);
  await api('runs/'+run.run_id+'/command',{action:'pause'});
  await api('runs/'+run.run_id+'/command',{action:'resume'});
  const activity=await (await fetch(runURL+'?view=workspace&tab=activity')).json();
  assert(activity.history.some(h=>h.kind==='pause'));
  assert(activity.history.some(h=>h.kind==='resume'));
  assert(activity.history.every(h=>!Object.hasOwn(h,'detail')&&!['observation','dispatched','committed'].includes(h.kind)));
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
  await page.route(workspaceURL,route=>route.fulfill({status:502,contentType:'text/plain',body:'Gateway unavailable'}),{times:1});
  await currentLink.click();
  await page.locator('#toast').filter({hasText:/无法打开运行详情.*HTTP 502/}).waitFor();
  let release;
  const delay=new Promise(resolve=>{release=resolve;});
  let requests=0;
  await page.route(workspaceURL,async route=>{requests++;await delay;await route.continue();});
  try{
    await currentLink.click();
    await page.locator('#toast').filter({hasText:'正在打开运行详情…'}).waitFor();
    await currentLink.click();
    assert.equal(requests,1);
  }finally{release();}
  const hero=page.locator('#run-progress');
  await hero.getByRole('link',{name:/训练模型.*train-A-6/}).waitFor();
  await page.unroute(workspaceURL);
  assert.equal(await hero.getByRole('link').count(),2);
  assert(!/后续已安排|评估输出|找不到文件/.test(await hero.innerText()));
  assert.equal(await page.getByText('多轮实验 · 结果核对',{exact:true}).locator('visible=true').count(),1);
  await hero.getByRole('link',{name:/训练模型.*train-A-6/}).click();
  await page.locator('#task-detail').getByRole('heading',{name:'训练模型',exact:true}).waitFor();
  await page.getByRole('button',{name:'关闭节点详情'}).click();
  const graph=page.locator('.process-canvas');
  const toggles=graph.locator('[data-round-toggle]');
  assert.equal(await toggles.count(),6);
  assert.equal(await graph.locator('[data-task-row]').count(),0);
  const third=graph.locator('[data-round-toggle="第 3 轮"]');
  const rowOf=locator=>locator.evaluate(el=>el.closest('[data-graph-row]').dataset.graphRow);
  const thirdRow=await rowOf(third);
  const fourth=graph.locator('[data-round-toggle="第 4 轮"]');
  const fourthX=(await fourth.boundingBox()).x;
  await third.click();
  assert.equal(await third.getAttribute('aria-expanded'),'true');
  assert.equal(await graph.locator('[data-task-row]').count(),6);
  const frame=graph.getByRole('region',{name:'第 3 轮',exact:true});
  assert.equal(await rowOf(frame),thirdRow);
  assert(Math.abs((await fourth.boundingBox()).x-fourthX)<1);
  assert.equal(await frame.locator('[data-task-row]').count(),6);
  assert.equal(await frame.locator('[data-edge-kind="dependency"]').count(),4);
  const ready=frame.locator('[data-task-row]').filter({hasText:'prepare-A-3'});
  const score=frame.locator('[data-task-row]').filter({hasText:'score-A-3'});
  assert((await score.boundingBox()).x>(await ready.boundingBox()).x);
  const incoming=graph.locator('svg').first().locator('[data-edge-to="$round:第 3 轮"]');
  assert.equal(await incoming.count(),1);
  assert.equal(await incoming.locator('title').textContent(),'4 条执行依赖');
  assert((await graph.innerText()).includes('验证准确率 87.5 %'));
  assert(!(await graph.innerText()).includes('/scratch/'));
  const member=graph.locator('[data-task-row]').filter({hasText:'score-A-3'}).locator('.task-card-main');
  const memberId=await member.getAttribute('data-task-focus');
  const taskDetail=await (await fetch(workspaceURL+'&task='+encodeURIComponent(memberId))).json();
  assert.equal(taskDetail.history.length,0);
  const omitted=['inputs','outputs','sources','task_spec','prompt_text','parameters','error','stdout','stderr'];
  assert(taskDetail.executions.every(e=>omitted.every(key=>!Object.hasOwn(e,key))));
  assert(taskDetail.executions.some(e=>e.task_id===memberId&&e.output_readout.some(r=>r.value===87.5)));
  assert(!JSON.stringify(taskDetail).includes('/scratch/'));
  const cardRef=member.locator('.task-card-ref');
  await cardRef.scrollIntoViewIfNeeded();
  const textBounds=await cardRef.evaluate(el=>{
    const range=document.createRange();range.selectNodeContents(el);
    return range.getBoundingClientRect().toJSON();
  });
  const textY=textBounds.y+textBounds.height/2;
  await page.mouse.move(textBounds.left,textY);
  await page.mouse.down();
  await page.mouse.move(textBounds.right,textY,{steps:8});
  await page.mouse.up();
  assert.equal(await page.evaluate(()=>getSelection().toString()),'score-A-3');
  assert.equal(await page.locator('#task-detail').isVisible(),false);
  await member.click();
  await page.getByRole('heading',{name:'任务关系与推进'}).waitFor();
  assert(await page.locator('.task-flow').getByRole('button',{name:'训练模型 · train-A-3'}).isVisible());
  await page.locator('#task-detail .node-result').getByText('验证准确率',{exact:true}).waitFor();
  assert.match(await page.locator('#task-detail .node-result').innerText(),/87.5 %/);
  assert.equal(await page.locator('#inspect [data-task-result]').count(),0);
  const resultValue=page.locator('#task-detail .node-result-readings dd').first();
  await resultValue.evaluate(el=>{
    const selection=getSelection(),range=document.createRange();
    range.selectNodeContents(el);selection.removeAllRanges();selection.addRange(range);
  });
  const runWorkspaceRequest=requestURL=>requestURL.pathname===new URL(runURL).pathname&&
    requestURL.searchParams.get('view')==='workspace'&&requestURL.searchParams.get('tab')==='task-history';
  await page.route(runWorkspaceRequest,async route=>{
    const response=await route.fetch(),updated=await response.json();
    updated.created_by='刷新到达';
    const attempt=updated.executions.find(e=>e.task_id===memberId&&e.output_readout.some(r=>r.label==='验证准确率'));
    attempt.output_readout.find(r=>r.label==='验证准确率').value=88.5;
    await route.fulfill({json:updated});
  });
  await page.locator('#run-id').getByText('刷新到达',{exact:false}).waitFor();
  assert.equal(await page.evaluate(()=>getSelection().toString()),'87.5 %');
  await page.evaluate(()=>getSelection().removeAllRanges());
  await resultValue.getByText('88.5 %',{exact:true}).waitFor();
  await page.unroute(runWorkspaceRequest);
  await page.reload();
  await page.locator('#task-detail').getByRole('heading',{name:'评估输出',exact:true}).waitFor();
  assert.equal(await page.locator('#task-detail').getAttribute('data-task'),memberId);
  await page.getByRole('button',{name:'关闭节点详情'}).click();
  await page.reload();await third.waitFor();
  assert.equal(await third.getAttribute('aria-expanded'),'true');
  assert.equal(await page.locator('#task-detail').isVisible(),false);
  await third.click();
  assert.equal(await graph.locator('[data-task-row]').count(),0);
  assert.equal(await page.getByRole('button',{name:'关键变更',exact:true}).count(),0);
  assert.equal(await page.getByText('节点进度',{exact:true}).count(),0);
  await page.locator('.run-menu summary').click();
  await page.locator('.run-menu').getByRole('button',{name:'通知与控制',exact:true}).click();
  await page.locator('#inspect').getByText(/通知出口/).first().waitFor();
  assert.equal(await page.locator('#inspect pre').count(),0);
  await page.getByRole('button',{name:'运行过程',exact:true}).click();
  await page.locator('[data-graph-current]').click();
  await page.locator('#task-detail').getByText('找不到文件或目录 official_aggregate.json。',{exact:true}).waitFor();
  assert(!(await page.locator('#task-detail').innerText()).includes('Traceback'));
  const failedId=await page.locator('#task-detail').getAttribute('data-task');
  const failedView=await (await fetch(workspaceURL+'&task='+encodeURIComponent(failedId))).json();
  assert(!JSON.stringify(failedView).includes('Traceback'));
  assert((await (await fetch(runURL)).json()).executions.some(e=>e.task_id===failedId&&e.error?.includes('Traceback')));
  await page.locator('#task-round').selectOption('第 6 轮');
  assert.equal(await graph.locator('[data-task-row]').count(),0);
  assert.equal(await graph.locator('.round-card').count(),1);
  assert.match(await graph.locator('.round-card').innerText(),/执行失败 1/);
  await page.locator('#task-round').selectOption('');
  await page.locator('[data-task-order="time"]').click();
  await page.locator('.process-list [data-task-row]').nth(35).waitFor({state:'attached'});
  assert.equal(await page.locator('.process-list [data-task-row]').count(),36);
  await page.locator('[data-task-order="graph"]').click();
  const scored=await tool('start_run',{key,request_id:randomUUID(),title:'已保存评分',objective:'从监控读取已保存的曲线。'});
  const {token}=await tool('acquire_run',{run_id:scored.run_id});
  try{
    await tool('update_run_method',{run_id:scored.run_id,token,observations:{'评测结果':{on:null,steps:[{kind:'command',
      command:report({summary:'两次评测',series:[{label:'准确率',points:[[1,82],[2,87.5]]}]})}]}}});
  }finally{await tool('finish',{run_id:scored.run_id,token});}
  await tool('register_monitor',{script_id:'test-standing',revision:0,script:{description:'可用资源',command:report({count:8})}});
  await tool('start_monitor',{request_id:randomUUID(),script_id:'test-standing',interval:60,show_on_dashboard:true});
  await tool('start_monitor',{request_id:randomUUID(),script:{description:'内部巡检',command:report({count:4})},interval:60});
  await tool('start_monitor',{request_id:randomUUID(),run_id:run.run_id,script:{description:'试验资源用量',command:report({count:1})},
    interval:60,show_on_dashboard:true});
  for(const [name,width] of [['desktop',1280],['mobile',390]]){
    await page.setViewportSize({width,height:850});
    await page.goto(url+'/#run/'+run.run_id);await page.reload();await hero.getByRole('link',{name:/训练模型.*train-A-6/}).waitFor();await page.evaluate(()=>window.scrollTo(0,0));
    const metrics=page.locator('#run-metrics');
    await metrics.getByRole('heading',{name:'运行指标样例'}).waitFor();
    const activeBox=await hero.boundingBox(),metricsBox=await metrics.boundingBox();
    assert(metricsBox.y<(await page.locator('.run-tabs').boundingBox()).y);
    if(width===1280){
      assert(Math.abs(activeBox.y-metricsBox.y)<2);
      assert(metricsBox.x>=activeBox.x+activeBox.width);
    }else{
      assert(Math.abs(activeBox.x-metricsBox.x)<2);
      assert(metricsBox.y>=activeBox.y+activeBox.height);
    }
    if(process.env.PROGRESS_SCREENSHOTS){
      await page.screenshot({path:path.join(process.env.PROGRESS_SCREENSHOTS,name+'-run.png')});
      await page.locator('.dependency-scroll').screenshot({path:path.join(process.env.PROGRESS_SCREENSHOTS,name+'-nodes.png')});
    }
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.equal(await graph.locator('.round-card').count(),6);
    if(width===390){
      assert.equal(await page.locator('#graph-scale').innerText(),'100%');
      await page.getByRole('button',{name:'适应宽度'}).click();
      assert(await page.locator('.dependency-scroll').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    }
    const scroll=page.locator('.dependency-scroll');
    const zoom=page.locator('#graph-scale');
    await zoom.click();
    assert.equal(await zoom.innerText(),'100%');
    const original=(await graph.locator('.round-card').first().boundingBox()).width;
    await page.getByRole('button',{name:'放大依赖图',exact:true}).click();
    assert.equal(await zoom.innerText(),'125%');
    assert((await graph.locator('.round-card').first().boundingBox()).width>original*1.2);
    await page.getByRole('button',{name:'缩小依赖图',exact:true}).click();
    assert.equal(await zoom.innerText(),'100%');
    assert(await scroll.evaluate(el=>el.scrollHeight<=el.clientHeight+1));
    await scroll.evaluate(el=>window.scrollBy({top:el.getBoundingClientRect().top-100,behavior:'instant'}));
    const originalScroll=await page.evaluate(()=>scrollY);
    const canvasBox=await scroll.boundingBox();
    await page.mouse.move(canvasBox.x+40,Math.max(0,canvasBox.y)+32);
    await page.mouse.wheel(0,-150);
    const afterWheel=await page.evaluate(()=>new Promise(resolve=>{
      requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(scrollY)));
    }));
    assert(afterWheel<originalScroll);
    assert.equal(await scroll.evaluate(el=>el.scrollTop),0);
    await page.getByRole('button',{name:'全屏',exact:true}).scrollIntoViewIfNeeded();
    const beforeFullscreen=await page.evaluate(()=>scrollY);
    await page.getByRole('button',{name:'全屏',exact:true}).click();
    const full=page.locator('#run-graph-dialog[open]');
    await full.waitFor();
    const expanded=await full.boundingBox();
    assert.equal(expanded.width,width);
    assert.equal(expanded.height,850);
    assert(await full.locator('.dependency-scroll').evaluate(el=>el.scrollHeight<=el.clientHeight+1));
    const firstRound=full.locator('button[data-round-toggle="第 1 轮"]');
    await firstRound.click();
    await full.locator('[data-task-row] .task-card-main').first().click();
    await full.locator('#task-detail').waitFor();
    await full.getByRole('button',{name:'关闭节点详情',exact:true}).click();
    await firstRound.click();
    assert.equal(await page.locator('#run-process-controls').isVisible(),false);
    await page.getByRole('button',{name:'筛选',exact:true}).click();
    assert(await page.locator('#run-process-controls').isVisible());
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#run-graph-dialog').getAttribute('open'),null);
    assert(await page.locator('#run-inspect-home .dependency-scroll').isVisible());
    const restored=await page.evaluate(()=>new Promise(resolve=>{
      requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(scrollY)));
    }));
    assert(Math.abs(restored-beforeFullscreen)<=2,JSON.stringify({width,beforeFullscreen,restored}));
    await page.goto(url+'/#work/monitors');
    const savedChart=page.locator(`[data-result-monitor-run="${scored.run_id}"]`);
    await savedChart.getByText('评测结果',{exact:true}).waitFor();
    assert.equal(await savedChart.locator('.observation-chart circle').count(),2);
    assert.equal(await savedChart.getByRole('link',{name:'查看 Timeline'}).getAttribute('href'),'#work/timelines/'+scored.timeline_id);
    await page.locator('#monitoring-standing').getByRole('button',{name:'可用资源'}).waitFor();
    const runMonitors=page.locator('#monitoring-run-monitor-section');
    if(await runMonitors.getAttribute('open')===null)await runMonitors.locator('summary').click();
    await runMonitors.getByRole('button',{name:'试验资源用量'}).waitFor();
    assert.doesNotMatch(await page.locator('#monitoring-overview').innerText(),/内部巡检|7 \/ 10|验证损失|等待条件/);
    await page.getByRole('tab',{name:'脚本库'}).click();
    await page.locator('#monitoring-script-list').getByText('test-standing',{exact:true}).waitFor();
    assert.equal(await page.locator('#monitoring-script-list tbody tr').count(),1);
    await page.getByRole('tab',{name:'总览'}).click();
  }
  const cancelledRound='第 3 轮',singleRound='证据判读';
  const cancelNote='由绑定同一数据集与 checkpoint 的 32768 token 预测、官方评分及后续判读任务接替。';
  const cancelledTasks=[['old-score',cancelledRound,cancelNote],['old-review',singleRound,'取消任务']];
  const requestEdit=changes=>tool('submit_run_request',{run_id:run.run_id,request_id:randomUUID(),operation:'edit_tasks',arguments:{changes}});
  await requestEdit(cancelledTasks.map(([ref,round])=>({tool:'add_task',arguments:{ref,key:ref,node_id:'prepare',
    inputs:{},round,after_refs:['score-B-6']}})));
  const latest=await api('runs/'+run.run_id);
  const [cancelledId,singleId]=cancelledTasks.map(([ref])=>Object.values(latest.tasks).find(t=>t.spec.ref===ref).id);
  await requestEdit(cancelledTasks.map(([, , reason],i)=>({tool:'change_task',arguments:{task_id:[cancelledId,singleId][i],operation:'cancel',reason}})));
  for(const width of [1280,390]){
    await page.setViewportSize({width,height:850});
    const deepLink=url+'/#run/'+run.run_id+'/task/'+encodeURIComponent(cancelledId);
    await page.goto(deepLink);
    const mixed=graph.locator(`[data-round-frame="${cancelledRound}"]`);
    const cancelled=page.locator('#task-detail .task-cancellation');
    await mixed.getByText('已完成 6 · 已取消 1',{exact:true}).waitFor();
    await cancelled.getByRole('heading',{name:'取消原因'}).waitFor();
    assert(await cancelled.getByText(cancelNote,{exact:true}).isVisible());
    const cancelledCard=mixed.locator(`[data-task-row="${cancelledId}"]`);
    assert(await cancelledCard.getByText('已取消',{exact:true}).isVisible());
    assert(await cancelledCard.locator('.task-summary').evaluate(el=>{
      // Allow for wider Chinese glyphs than the browser test host's fallback font.
      el.style.letterSpacing='2px';
      const fits=el.scrollHeight<=el.clientHeight;
      el.style.removeProperty('letter-spacing');
      return fits;
    }));
    await mixed.getByRole('button',{name:'收起 '+cancelledRound,exact:true}).click();
    assert.equal(await page.locator('#task-detail').isVisible(),false);
    assert.equal(new URL(page.url()).hash,'#run/'+run.run_id);
    assert.equal(await graph.locator(`[data-round-toggle="${cancelledRound}"]`).getAttribute('aria-expanded'),'false');
    const single=graph.locator(`[data-round-toggle="${singleRound}"]`);
    await single.getByText('已取消 1',{exact:true}).waitFor();
    await single.click();
    await graph.locator(`[data-round-frame="${singleRound}"] [data-task-row="${singleId}"] .task-card-main`).click();
    await cancelled.getByText('未记录具体原因',{exact:true}).waitFor();
    await page.getByRole('button',{name:'关闭节点详情'}).click();
    await single.click();
    await page.locator('#task-status').selectOption('cancelled');
    assert.equal(await graph.locator('[data-task-row][data-status="cancelled"]').count(),2);
  }
  const waiting=await startRun('测试等待事件');
  await page.goto(url+'/#run/'+waiting.turn.run_id);
  await page.getByRole('button',{name:/待处理/}).click();
  const issue=page.locator('.run-issue-list li').filter({hasText:'等待事件'});
  await issue.getByRole('link',{name:'查看节点'}).click();
  await page.locator('#task-detail').getByRole('button',{name:'提交事件 / 回复'}).click();
  await page.getByRole('heading',{name:'提交等待的事件'}).waitFor();
  await page.keyboard.press('Escape');

  const {token:repairToken}=await tool('acquire_run',{run_id:run.run_id});
  const pending=await tool('next_tasks',{run_id:run.run_id,token:repairToken});
  const failure=pending.items.find(item=>item.task_id===failedId);
  const reason='请确认本轮预算上限，再重试评分。';
  await tool('defer_task',{run_id:run.run_id,token:repairToken,task_id:failure.id,reason});
  await tool('finish',{run_id:run.run_id,token:repairToken});
  await page.goto(url+'/#run/'+run.run_id);
  await page.getByRole('button',{name:/待处理/}).click();
  const deferred=page.locator('.run-issue-list li').filter({hasText:reason});
  await deferred.getByText('等待用户处理',{exact:true}).waitFor();
  await deferred.getByRole('link',{name:'查看节点'}).click();
  await page.locator('#task-detail .wait-description').getByText(reason,{exact:true}).waitFor();
  const activityAfterDeferral=await api('runs/'+run.run_id+'?view=workspace&tab=activity');
  assert(activityAfterDeferral.history.some(item=>item.note===reason&&item.task_id===failedId));
}).catch(error=>{console.error(error);process.exitCode=1;});
