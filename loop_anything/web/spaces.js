'use strict';
let spaceSettings=null;
const spaceDialog=document.createElement('dialog');spaceDialog.id='spaces-dialog';document.body.append(spaceDialog);
function selectedSpace(config){return config.default_space==='auto'?(config.team_url?'team':config.local_url?'local':null):config.default_space;}
async function readSpaces(){
  spaceSettings=await api('spaces');
  $('space-current').textContent=spaceSettings.space==='team'?'团队平台':'本地平台';
  $('space-switch').title=spaceSettings.space==='team'?'当前页面管理团队平台的任务':'设置平台地址和新任务默认运行平台';
}
function renderSpaces(){
  const c=spaceSettings.configuration;
  if(!c){
    spaceDialog.innerHTML=`<div class="dialog-heading"><h2>当前是团队页面</h2><button class="close-dialog" aria-label="关闭">×</button></div><p>本页面管理团队平台的运行与记录。本地平台有独立的页面和任务。</p><p class="small muted">个人地址和默认运行平台，请在本机的 Loop Anything 页面中设置。修改默认值不会改变本页面或已有任务。</p>`;
    return;
  }
  const selected=selectedSpace(c);
  spaceDialog.innerHTML=`<div class="dialog-heading"><h2>平台地址与默认选择</h2><button class="close-dialog" aria-label="关闭">×</button></div>
    <p class="small muted">当前是本地页面。本地页面和团队页面分别管理各自平台上的运行与记录，填写团队地址不会切换页面。</p>
    <form id="spaces-form">
      <p class="space-local-address">本地平台地址 <code>${esc(c.local_url||'未记录')}</code></p>
      <label for="space-team-url">团队平台地址</label><input id="space-team-url" value="${esc(c.team_url||'')}" placeholder="https://team.example 或 nas:///挂载目录">
      <details class="space-advanced" ${c.team_url?.startsWith('nas:')||c.team_web_url?'open':''}><summary>NAS 连接选项</summary><label for="space-team-web">团队网页地址</label><input id="space-team-web" value="${esc(c.team_web_url||'')}" placeholder="https://team.example"><p class="small muted">通过 NAS 调用工具时，启动器使用此地址打开团队页面。</p></details>
      <label for="space-default">新任务默认在哪个平台运行</label><select id="space-default"><option value="auto" ${c.default_space==='auto'?'selected':''}>自动选择（都有地址时优先团队）</option><option value="local" ${c.default_space==='local'?'selected':''}>本地平台运行</option><option value="team" ${c.default_space==='team'?'selected':''}>团队平台运行</option></select>
      <p class="space-selection">当前默认：${selected==='team'?'团队平台':selected==='local'?'本地平台':'尚未配置地址'}</p>
      <p class="small muted">用于 Agent／命令行未指定平台的新操作，启动器也按此选择打开的页面。当前网页和已有任务不变。</p>
      <p class="small muted">自动选择只使用已记录的地址；两个都有时优先团队。连接失败不会改投另一个平台。</p>
      <p id="space-save-error" role="status"></p><button class="primary" type="submit">保存个人设置</button>
    </form>`;
  $('spaces-form').onsubmit=async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;
    try{
      const teamURL=$('space-team-url').value.trim(),webURL=$('space-team-web').value.trim();
      spaceSettings=await api('spaces',{revision:c.revision,change:{team_url:teamURL||null,team_web_url:webURL||null,default_space:$('space-default').value}});
      renderSpaces();toast('已保存默认运行平台；当前页面和已有任务不变。');
    }catch(error){$('space-save-error').textContent=error.message;button.disabled=false;}
  };
}
$('space-switch').onclick=()=>safely(async()=>{await readSpaces();renderSpaces();spaceDialog.showModal();});
window.addEventListener('DOMContentLoaded',()=>safely(readSpaces));
