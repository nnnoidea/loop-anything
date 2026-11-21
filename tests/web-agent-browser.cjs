// Explicit browser controls apply directly to the selected task.
const {withPlatform, assert} = require('./browser-platform.cjs');

withPlatform(async ({url, page, startRun, api, tool}) => {
  const {turn, task} = await startRun('核对委托');
  await page.goto(url + '/#run/' + turn.run_id);
  await page.locator('[data-task-row="' + task + '"]').click();
  await page.locator('[data-task-cancel="' + task + '"]').first().click();
  await page.locator('#task-edit-reason').fill('取消等待，检查已有结果');
  await page.locator('#task-edit-submit').click();
  await page.locator('#task-edit-dialog').waitFor({state: 'hidden'});

  const run = await api('runs/' + turn.run_id);
  assert.equal(run.tasks[task].status,'cancelled');
  assert.equal(await page.locator('[data-steward-requests]').count(),0);
}).catch(error => {console.error(error); process.exitCode = 1;});
