// Inspect domain results in the Run and download the associated portable progress.
const {withPlatform, assert} = require('./browser-platform.cjs');

withPlatform(async ({url, page, startRun, api}) => {
  for (const [title, value] of [['研究任务', 'A 组召回率 0.82'], ['差旅任务', '杭州，铁路 580 元']]) {
    const {turn, task} = await startRun(title);
    await api('runs/' + turn.run_id + '/event', {
      event_id: 'received', name: 'measurement', payload: {value, report: 'report.md'}
    });
    await page.goto(url + '/#work/timelines/' + turn.timeline_id);
    await page.locator('#timeline-content .timeline-run-link').click();
    await page.locator('[data-task-row="' + task + '"]').click();
    const output = page.locator('#task-detail .node-result');
    await output.getByText(value, {exact: true}).waitFor();
    const file = output.getByRole('link', {name: /report\.md/});
    const href = await file.getAttribute('href');
    const result = await page.request.get(new URL(href, url).href);
    assert(result.ok());
    assert.equal(await result.text(), 'Ready');
    await page.goBack();
    await page.locator('#timeline-content .timeline-run-link').waitFor();
    assert((await page.locator('.timeline-intent').innerText()).includes(title));
    const download = page.waitForEvent('download');
    await page.locator('#timeline-download').click();
    const chunks = [];
    for await (const chunk of await (await download).createReadStream()) chunks.push(chunk);
    const progress = JSON.parse(Buffer.concat(chunks));
    assert.equal(progress.timeline.objective, title);
    assert(progress.results.some(record => record.value === value));
    assert(!Object.hasOwn(progress, 'tasks'));

    const run = await api('runs/' + turn.run_id);
    if (!['completed','terminated'].includes(run.status)) {
      await api('runs/' + turn.run_id + '/command', {action: 'terminate'});
    }
    await page.locator('.timeline-run-link').click();
    page.once('dialog', dialog => dialog.accept());
    await page.locator('.run-menu>summary').click();
    await page.locator('#delete-run').click();
    await page.waitForURL('**/#work/runs');
    await page.goto(url + '/#work/timelines/' + turn.timeline_id);
    const record = progress.results.find(item => item.value === value);
    const open = page.locator('[data-work-result="' + record.id + '"]');
    await open.click();
    const detail = open.locator('..').locator('.business-record-detail');
    await detail.locator('summary').click();
    assert((await detail.innerText()).includes(value));
    assert.equal(await page.locator('.timeline-run-link').count(), 0);
  }
}).catch(error => {console.error(error); process.exitCode = 1;});
