'use strict';
// Starting uses the configured Loop. There is no second web Agent or editable preparation state.
let pendingLaunch=null,launchBusy=false;
async function openCreate(key){
  if(!key){await navigateTo({type:'catalog'});return;}
  const item=catalog.find(c=>c.key===key);if(!item)throw new Error('找不到此 Loop');
  const config=item.package_key?await platformCall('read_loop_config',{key}):{config:{},path:null};
  if(config.error)throw new Error(config.error);
  pendingLaunch={key,title:(item.loop_definition.name||item.loop_definition.id)+' · '+new Date().toLocaleString('zh-CN')};
  $('launch-summary').innerHTML=`<h3>${esc(item.loop_definition.name||key)}</h3><p>按 Loop 与运行配置文件启动。启动参数、执行方案和外部服务由 Agent 或配置文件设置。</p>${config.path?`<p>配置文件：<code>${esc(config.path)}</code></p><button type="button" data-loop-config="${esc(key)}">查看运行配置</button>`:''}${readerJSON('启动输入',{...(item.loop_definition.defaults||{}),...(config.config.inputs||{})},true)}${readerJSON('本机运行配置',config.config)}`;
  $('launch-created-by').value=typeof localStorage!=='undefined'?(localStorage.getItem('loop-anything-user-name')||''):'';
  $('launch-error').textContent='';$('launch-start').disabled=false;$('create-dialog').showModal();
}
async function startConfiguredRun(){
  if(launchBusy||!pendingLaunch)return;
  launchBusy=true;$('launch-start').disabled=true;
  const author=($('launch-created-by').value||'').trim();
  if(typeof localStorage!=='undefined')localStorage.setItem('loop-anything-user-name',author);
  try{const created=await api('runs',{...pendingLaunch,...(author?{created_by:author}:{})});$('create-dialog').close();await selectRun(created.id);}
  catch(error){$('launch-error').textContent=error.message;}
  finally{launchBusy=false;$('launch-start').disabled=false;}
}
document.addEventListener('click',event=>{if(event.target.closest('#launch-start'))safely(startConfiguredRun);});
$('create-dialog').addEventListener('close',()=>{pendingLaunch=null;});
