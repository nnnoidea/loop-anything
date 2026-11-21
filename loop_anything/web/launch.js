'use strict';
// The Agent performing startup owns the Run; the browser has no Agent session to bind.
let pendingLaunch=null,launchBusy=false;
async function openCreate(key){
  if(!key){await navigateTo({type:'catalog'});return;}
  const item=catalog.find(c=>c.key===key);if(!item)throw new Error('找不到此 Loop');
  const config=item.package_key?await platformCall('read_loop_config',{key}):{config:{},path:null};
  pendingLaunch={key};
  $('launch-summary').innerHTML=`<h3>${esc(item.loop_definition.name||key)}</h3><p>将启动要求交给当前 Agent，随后可在运行页查看进度。</p><p>可以使用新的 Timeline，或在意外中断后使用已有 Timeline 接续工作。</p><pre id="launch-instruction">${esc('请使用平台 Skill 启动 Loop '+key+'。先读取运行配置；沿用用户目标、限制和已记录的工作进度。')}</pre>${config.path?`<p>配置文件：<code>${esc(config.path)}</code></p>`:''}${readerJSON('启动输入',{...(item.loop_definition.defaults||{}),...(config.config.inputs||{})},true)}`;
  const author=$('launch-created-by');(author.closest?.('label')||author).hidden=true;
  $('launch-error').textContent='';
  $('launch-start').textContent='复制启动要求';$('launch-start').disabled=false;
  $('create-dialog').showModal();
}
async function startConfiguredRun(){
  if(!pendingLaunch)return;
  const text=$('launch-instruction').textContent;
  if(navigator.clipboard){await navigator.clipboard.writeText(text);toast('已复制，可交给当前 Agent。');}
  else {const range=document.createRange();range.selectNodeContents($('launch-instruction'));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);}
}
document.addEventListener('click',event=>{if(event.target.closest('#launch-start'))safely(startConfiguredRun);});
$('create-dialog').addEventListener('close',()=>{pendingLaunch=null;});
