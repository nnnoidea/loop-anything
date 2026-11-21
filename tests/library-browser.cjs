// Read the author's package and prepare a launch in the calling Agent.
const {withPlatform, assert} = require('./browser-platform.cjs');

withPlatform(async ({url, page, key, api}) => {
  await page.goto(url + '/#loop_definitions');
  await page.locator('[data-loop="' + key + '"]').first().click();
  await page.locator('#reader-title').filter({hasText: '阅读与运行'}).waitFor();
  assert.equal(await page.locator('#reader-description').innerText(), '记录 <b>实验结果</b>');
  assert.equal(await page.locator('#reader-description b').count(), 0);
  await page.frameLocator('.authored-flow').locator('[data-loop-node="wait"]').click();
  await page.locator('#editor-properties .reader-prose').filter({hasText: '观察用户提交的结果'}).waitFor();
  await page.getByRole('button', {name: '状态转移', exact: true}).click();
  assert(await page.locator('#editor-node-states').isVisible());
  await page.locator('#close-editor-detail').click();

  await page.locator('.editor-more summary').click();
  await page.locator('#loop-package').click();
  const download = page.waitForEvent('download');
  await page.locator('#package-export').click();
  assert((await download).suggestedFilename().endsWith('.loop.zip'));
  await page.locator('#package-dialog .close-dialog').click();
  await page.locator('#reader-start').click();
  await page.locator('#create-dialog[open]').waitFor();
  assert((await page.locator('#launch-instruction').innerText()).includes(key));
  assert.equal(await page.locator('#launch-start').innerText(), '复制启动要求');
  assert.equal((await api('runs')).total, 0);
  await page.getByRole('button', {name: '取消', exact: true}).click();

  await page.locator('#editor-back').click();
  await page.locator('.catalog-card').first().waitFor();
  await page.setViewportSize({width: 420, height: 840});
  await page.locator('[data-loop="' + key + '"]').first().click();
  assert(await page.locator('#reader-start').isVisible());
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
}).catch(error => {console.error(error); process.exitCode = 1;});
