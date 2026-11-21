'use strict';
const settingsLabels={general:'常规',connections:'团队连接',agents:'接单 Agent',notifications:'通知'};

async function readSpaces(){
  const spaceSettings=await api('spaces');
  $('space-current').textContent=spaceSettings.space==='team'?'团队平台':'本地平台';
  return spaceSettings.configuration;
}

function personalSettings(config){
  const root=$('settings-personal');
  if(!config){root.replaceChildren();return;}
  root.innerHTML=`<section class="settings-card"><h2 id="remote-address-label">远端服务器地址</h2>
    <form id="spaces-form">
    <div class="settings-input-row"><input id="space-team-url" aria-labelledby="remote-address-label" type="text" spellcheck="false" placeholder="https://team.example 或 nas:///挂载目录" value="${esc(config.team_url||'')}"><button class="primary">保存地址</button></div>
    <div id="space-web-field"><label for="space-team-web">团队网页地址（可选）</label><input id="space-team-web" placeholder="https://team.example" value="${esc(config.team_web_url||'')}"></div>
    <p class="settings-error" role="status"></p></form></section>
    <details class="settings-card settings-preference"><summary>Agent 与启动器偏好</summary>
    <form id="default-platform-form"><label for="space-default">新任务默认运行平台</label>
    <p class="small muted">供 Agent、命令行和下次打开启动器时使用。</p>
    <div class="settings-input-row"><select id="space-default"><option value="auto">自动（优先团队）</option><option value="local">本地平台</option><option value="team">团队平台</option></select><button>保存偏好</button></div>
    <p class="settings-error" role="status"></p></form></details>`;
  const address=$('space-team-url'),web=$('space-team-web'),preference=$('space-default');
  preference.value=config.default_space;
  function showWebField(){$('space-web-field').hidden=!(address.value.trim().startsWith('nas:')||web.value);}
  showWebField();address.oninput=showWebField;

  async function save(event,change,message){
    event.preventDefault();
    const form=event.currentTarget,button=form.querySelector('button'),error=form.querySelector('[role=status]');
    button.disabled=true;error.textContent='';
    try{
      const result=await api('spaces',{revision:config.revision,change});
      Object.assign(config,result.configuration);
      if('default_space' in change)preference.value=config.default_space;
      toast(message);
    }catch(e){error.textContent=e.message;}
    finally{button.disabled=false;}
  }
  $('spaces-form').onsubmit=event=>{
    const team=address.value.trim()||null;
    const change={team_url:team};
    if(!team && config.default_space==='team')change.default_space='auto';
    if(!team || !$('space-web-field').hidden)change.team_web_url=team?(web.value.trim()||null):null;
    save(event,change,team?'远端服务器地址已保存':change.default_space?'远端地址已清除，新任务恢复自动选择':'远端服务器地址已清除').then(()=>{
      if(!team && !config.team_url){web.value='';showWebField();}
    });
  };
  $('default-platform-form').onsubmit=event=>save(event,{default_space:preference.value},'启动偏好已保存');
}

async function renderSettings(tab){
  const route=activeRoute,content=$('settings-content');
  document.querySelectorAll('[data-settings-tab]').forEach(el=>{
    const current=el.dataset.settingsTab===tab;
    el.classList.toggle('active',current);
    if(current)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');
  });
  $('settings-general').hidden=tab!=='general';
  content.replaceChildren();
  if(tab==='general'){
    const config=await readSpaces();
    if(activeRoute===route)personalSettings(config);
  }else if(tab==='notifications'){
    const outlets=await loadNotificationChannels();
    if(activeRoute!==route)return;
    const names=Object.entries(outlets.channels).map(([id,c])=>c.label||id);
    content.innerHTML=`<section class="settings-card"><div class="settings-row"><h2>通知出口</h2><button id="notification-outlets">管理通知出口</button></div><p class="muted">当前出口：${esc(['平台通知区',...names].join('、'))}</p></section>`;
  }else{
    if(tab==='connections')await refreshRunLibrary();
    if(activeRoute===route)await renderCommunication();
  }
}
window.addEventListener('DOMContentLoaded',()=>safely(readSpaces));
