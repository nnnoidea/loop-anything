// A browser submits the change; the session bound to the Run applies it.
const {withPlatform, assert} = require('./browser-platform.cjs');

withPlatform(async ({url, page, startRun, api, tool}) => {
  const {turn, session, task} = await startRun('核对委托');
  await page.goto(url + '/#run/' + turn.run_id);
  await page.locator('[data-task-row="' + task + '"]').click();
  await page.locator('[data-task-cancel="' + task + '"]').first().click();
  await page.locator('#task-edit-reason').fill('取消等待，检查已有结果');
  await page.locator('#task-edit-submit').click();
  await page.locator('#task-edit-dialog').waitFor({state: 'hidden'});

  const run = await api('runs/' + turn.run_id);
  const request = Object.values(run.steward_requests).find(item => item.operation === 'edit_tasks');
  assert(request);
  assert.notEqual(run.tasks[task].status, 'cancelled');
  const claimed = await tool('claim_run', {session_id: session.session_id, session_token: session.session_token, run_id: turn.run_id});
  assert.equal(claimed.task_id, request.task_id);
  const operate = (tool, args) => api('runs/' + turn.run_id + '/agent', {
    tool, token: claimed.token, arguments: args
  });
  await operate('edit_tasks', request.arguments);
  const decision = '已取消等待，保留已有结果';
  await operate('report_task', {
    task_id: claimed.task_id, event: 'completed', report_id: 'cancelled-wait',
    envelope: {outputs: {decision}}
  });
  await operate('finish', {});
  assert.equal((await api('runs/' + turn.run_id)).tasks[task].status, 'cancelled');
  await page.reload();
  await page.locator('[data-steward-requests]').click();
  await page.locator('#detail-content').getByText(decision, {exact: false}).first().waitFor();
}).catch(error => {console.error(error); process.exitCode = 1;});
