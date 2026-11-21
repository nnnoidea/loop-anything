const {withPlatform,assert}=require('./browser-platform.cjs');

withPlatform(async ({page,url})=>{
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const config=async()=>(await (await page.request.get(url+'/api/spaces')).json()).configuration;
  await page.goto(url);
  await page.locator('#settings-nav').click();
  const form=page.locator('#spaces-form');
  const pref=page.locator('#default-platform-form');
  assert(await form.isVisible());
  assert(!await pref.isVisible());
  assert.equal(await page.locator('#space-current').evaluate(el=>el.closest('button,a')),null);
  await form.getByRole('textbox',{name:'远端服务器地址'}).fill('https://example.test');
  await form.getByRole('button',{name:'保存地址'}).click();
  await page.getByText('远端服务器地址已保存',{exact:true}).waitFor();
  assert.equal((await config()).default_space,'auto');
  await page.locator('.settings-preference summary').click();
  await pref.locator('select').selectOption('team');
  await pref.getByRole('button').click();
  await page.getByText('启动偏好已保存',{exact:true}).waitFor();
  assert.equal((await config()).default_space,'team');
  assert.equal(page.url(),url+'/#settings/general');
  await form.locator('#space-team-url').fill('nas:///example/team');
  await form.locator('#space-team-web').fill('https://web.example.test');
  await form.getByRole('button').click();
  await page.getByText('远端服务器地址已保存',{exact:true}).waitFor();
  assert.equal((await config()).team_web_url,'https://web.example.test');
  await form.locator('#space-team-url').fill('');
  await form.getByRole('button').click();
  await page.getByText('远端地址已清除，新任务恢复自动选择',{exact:true}).waitFor();
  assert.equal((await config()).default_space,'auto');
  assert.equal((await config()).team_web_url,null);
  for(const [tab,selector] of [['connections','#communication-team'],['agents','#communication-agent-add'],['notifications','#notification-outlets']]){
    await page.locator('[data-settings-tab='+tab+']').click();
    await page.locator(selector).waitFor();
  }
  await page.locator('#communication-nav').click();
  assert.equal(await page.locator('#communication-page [data-comm-tab=connections]').count(),0);
  await page.getByRole('link',{name:'管理 Agent'}).click();
  await page.locator('#communication-agent-add').waitFor();
  await page.goBack();await page.locator('#communication-page h1').waitFor();
  await page.setViewportSize({width:390,height:780});
  await page.goto(url+'/#settings/general');
  await page.locator('#space-team-url').waitFor();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);
}).catch(error=>{console.error(error);process.exitCode=1;});
