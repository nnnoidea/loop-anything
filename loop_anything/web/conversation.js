'use strict';
// Web chat is a command client; business state always comes from the Run.
let preparationEdits=0, preparationRows=[], launchBindings={};
const conversationDrafts=new Map();
let conversation=null, preparationDirty=false, chatPollBusy=false, preparationSave=null;
const launchPage=document.createElement('section');launchPage.id='launch-page';launchPage.hidden=true;
launchPage.innerHTML='<div class="page-heading"><div><button id="preparation-back" class="back-link">← 返回 Loop</button><div class="eyebrow">PREPARE YOUR LOOP</div><h1>准备这次运行</h1><p class="muted">选好执行方式，与 Agent 讨论，再开始。</p></div><span id="preparation-saved" role="status"></span></div><div class="preparation-layout"><div class="panel preparation-main"><div id="preparation-flow"></div><div id="preparation-form"></div></div><div id="preparation-chat"></div></div>';
document.querySelector('main').append(launchPage);
$('preparation-form').append($('create-dialog'));
$('create-dialog').querySelector('h2').textContent='本次运行设置';
$('create-dialog').querySelector('.close-dialog').textContent='返回';
$('create-loop_definition').parentElement.hidden=true;
const chat=document.createElement('aside');chat.id='web-chat';chat.className='panel web-chat';
chat.innerHTML=`<div class="panel-heading"><div><h2>与 Agent 协作</h2><p class="small muted">在这里讨论、查看回复和调整后续工作。</p></div></div><details id="web-agent-config"><summary>网页使用的 Agent</summary><p class="small muted">命令在平台所在机器执行，配置保存在该平台，不随 Loop 分享。</p><label>沿用候选命令（保留网页提示词）<select id="web-agent-choice"><option value="">自定义命令</option></select></label><label>命令及参数（每行一项）<textarea id="web-agent-command" rows="3" placeholder="codex&#10;exec&#10;-"></textarea></label><label>工作目录（可选）<input id="web-agent-cwd"></label><label>超时秒数（留空不限时）<input id="web-agent-timeout" type="number" min="1"></label><div id="web-agent-prompt"></div><button id="save-web-agent" type="button">保存配置</button></details><div id="web-chat-messages" class="web-chat-messages" aria-live="polite"></div><div id="web-chat-status" role="status"></div><button id="recover-web-agent" hidden>已确认旧命令停止，恢复对话</button><div id="web-chat-notices"></div><form id="web-chat-form"><label id="web-chat-scope-label">本次修改范围<select id="web-chat-scope"><option value="">整个 Run</option></select></label><label for="web-chat-input" class="sr-only">给 Agent 的消息</label><textarea id="web-chat-input" rows="3" placeholder="告诉 Agent 你的目标，或询问当前进度…" required></textarea><div class="chat-compose-actions"><small>改动以工具提交结果为准</small><button class="primary" id="web-chat-send">发送</button></div></form>`;
$('preparation-chat').append(chat);
const runChat=document.createElement('div');runChat.id='run-chat-host';
const runColumns=document.createElement('div');runColumns.className='run-with-chat';
const processPanels=$('workspace').querySelector('.tasks-grid');processPanels.before(runColumns);runColumns.append(processPanels,runChat);
$('draft-cards').insertAdjacentHTML('afterend','<div id="preparation-cards"></div>');

function launchItem(){return catalog.find(c=>c.key===conversation?.launch.key);}
function agentConfig(){
  const command=$('web-agent-command').value.split('\n').filter(x=>x.length),cwd=$('web-agent-cwd').value.trim(),timeout=$('web-agent-timeout').value;
  return {...readPrompt($('web-agent-prompt'),'web'),...(command.length?{command}:{}),...(cwd?{cwd}:{}),...(timeout?{timeout:Number(timeout)}:{})};
}
function launchValues(){return {title:$('create-title').value,inputs:collectLaunchInputs(false),authorization:$('create-authorization').value,bindings:structuredClone(launchBindings),fallback_node:$('launch-fallback').value,global_agent_node:$('launch-global-agent').value};}
async function ensureRunConversation(){
  if(!conversation?.id){conversation=await api('conversations',{run_id:run.id});}
}
async function savePreparation(){
  if(preparationSave)await preparationSave;
  if(!conversation || !preparationDirty)return;
  if(conversation.busy)throw new Error('Agent 正在处理，当前输入尚未保存。');
  const launch=page==='launch'?launchValues():undefined,agent=agentConfig();
  await ensureRunConversation();
  const id=conversation.id,revision=conversation.revision,edits=preparationEdits;
  preparationSave=api(`conversations/${id}/update`,{revision,launch,agent});
  try{const updated=await preparationSave;if(conversation?.id===id){conversation=updated;preparationDirty=edits!==preparationEdits;$('preparation-saved').textContent='已保存到本机';}}
  finally{preparationSave=null;}
  await loadPreparationCards();
}
async function openPreparation(key,bindings){
  await savePreparation();
  const doc=await api('conversations',{key});
  if(bindings)await api(`conversations/${doc.id}/update`,{revision:doc.revision,launch:{bindings}});
  await loadPreparationCards();await navigateTo({type:'prepare',id:doc.id});
}
function populateAgent(){
  const item=launchItem(),c=conversation.agent || {},options=[];
  for(const [node,entry] of Object.entries(item?.implementations || {}))for(const [id,b] of Object.entries(implementationOptions(entry)))if(b.kind==='agent'&&b.command&&!b.simulation)options.push({node,id,config:b});
  $('web-agent-choice').innerHTML='<option value="">自定义命令</option>'+options.map((o,i)=>`<option value="${i}">${esc(item.loop_definition.nodes[o.node]?.label || o.node)} · ${esc(o.id)}</option>`).join('');
  $('web-agent-choice')._options=options;
  $('web-agent-command').value=(c.command || []).join('\n');$('web-agent-cwd').value=c.cwd || '';$('web-agent-timeout').value=c.timeout || '';
  $('web-agent-prompt').innerHTML=promptEditor('web',c);
  $('web-agent-config').open=!c.command?.length;
  $('web-chat-input').value=conversationDrafts.get(conversation.id || conversation.run_id) || '';
  $('web-chat-scope').value='';
}
function populatePreparation(){
  const item=launchItem();if(!item)throw new Error('找不到所选 Loop 版本');
  $('create-loop_definition').innerHTML=`<option value="${esc(item.key)}">${esc(item.loop_definition.name)}</option>`;
  createChanged();const l=conversation.launch;
  $('create-title').value=l.title;$('create-inputs').value=pretty(l.inputs);renderLaunchFields(item);
  $('create-authorization').value=l.authorization;launchBindings=structuredClone(l.bindings);
  $('launch-fallback').value=l.fallback_node || '';$('launch-global-agent').value=l.global_agent_node || '';
  renderPreparationGraph();
  $('launch-start').textContent=conversation.agent?.command?.length?'让 Agent 初始化并启动':'按节点实现启动';
  $('preparation-saved').textContent='已保存到本机';
}
function renderPreparationGraph(){
  const item=launchItem(),old=$('preparation-flow').querySelector('.loop-map'),focus=old?.dataset.mapFocus || '',scroll=old?.querySelector('.loop-map-scroll'),position=scroll?{left:scroll.scrollLeft,top:scroll.scrollTop}:null;
  $('preparation-flow').innerHTML=`<div class="preparation-heading"><div><h2>${esc(item.loop_definition.name || item.key)}</h2><p class="small muted">v${esc(item.loop_definition.version)} · 点击节点查看和选择本次实现</p></div><button id="edit-prepared-loop" type="button">编辑 Loop 定义</button></div>${loopGraphHTML(item,{bindings:launchBindings,action:'prepare',fallbackNode:$('launch-fallback').value||null})}<details><summary>查看步骤关系与作者说明</summary>${flowHTML(item,false)}</details>`;
  const root=$('preparation-flow').querySelector('.loop-map');if(item.loop_definition.nodes[focus])focusLoopMap(root,focus);
  if(old?.classList.contains('expanded')){root.classList.add('expanded');root.querySelector('[data-map-expand]').checked=true;}
  if(position)root.querySelector('.loop-map-scroll').scrollTo(position);
  root.querySelectorAll('[data-map-choice]').forEach(b=>b.disabled=!!conversation.busy||launchBusy);
}
async function enterPreparation(id){
  const doc=await api('conversations/'+id);
  if(activeRoute.type!=='prepare'||activeRoute.id!==id)return false;
  conversation=doc;preparationDirty=false;
  if(conversation.run_id){await selectRun(conversation.run_id);return false;}
  page='launch';$('preparation-chat').append(chat);populatePreparation();populateAgent();renderConversation();
  if(!$('create-dialog').open)$('create-dialog').show();
  return true;
}
async function enterRunChat(id){
  const rows=await api('conversations'),found=rows.find(d=>d.run_id===id);
  const doc=found?await api('conversations/'+found.id):null;
  if(page!=='runs'||run?.id!==id)return;
  const item=catalog.find(c=>c.key===run.loop_key),node=run.settings.global_agent_node || run.settings.fallback_node || run.loop_definition.entry;
  const impl=chosenImplementation(item || run,node,run.settings.bindings) || {};
  conversation=doc || {id:null,run_id:id,launch:{key:run.loop_key},agent:impl.kind==='agent'&&!impl.simulation?Object.fromEntries(['command','cwd','timeout'].filter(k=>k in impl).map(k=>[k,impl[k]])):{},messages:[],busy:false};
  preparationDirty=false;$('run-chat-host').append(chat);populateAgent();renderConversation();
}
function renderConversation(){
  if(!conversation)return;
  const messages=conversation.messages || [],html=messages.map(m=>`<article class="chat-message ${m.role}"><strong>${m.role==='user'?'你':'Agent'}</strong><div>${esc(m.text || (m.status==='running'?'正在处理…':''))}</div>${promptHistory(m)}${m.error?`<p class="chat-error">${esc(m.error)}</p>`:''}</article>`).join('') || '<p class="chat-empty">先选好节点的执行方式，再与 Agent 讨论。你也可以直接使用表单启动。</p>';
  if($('web-chat-messages').innerHTML!==html){$('web-chat-messages').innerHTML=html;$('web-chat-messages').scrollTop=$('web-chat-messages').scrollHeight;}
  const busy=conversation.busy;$('web-chat-status').textContent=conversation.recovery_required?'旧命令状态待核实':busy?'Agent 正在处理；可以继续查看运行过程。':'';
  $('web-chat-send').disabled=busy;$('recover-web-agent').hidden=!conversation.recovery_required;
  $('web-agent-config').querySelectorAll('input,textarea,select,button').forEach(e=>e.disabled=busy);
  if(page==='launch'){
    $('create-form').querySelectorAll('input,textarea,select,button').forEach(e=>e.disabled=busy||launchBusy);
    $('preparation-flow').querySelectorAll('[data-map-choice]').forEach(e=>e.disabled=busy||launchBusy);
  }
  $('web-chat-scope-label').hidden=page!=='runs';
  if(page==='runs'&&run){
    const old=$('web-chat-scope').value;
    const options='<option value="">整个 Run</option>'+Object.values(run.tasks || {}).map(t=>`<option value="${esc(t.id)}">${esc(taskLabel(t))} · ${esc(t.id)}</option>`).join('');
    if($('web-chat-scope').innerHTML!==options){$('web-chat-scope').innerHTML=options;$('web-chat-scope').value=old;}
    const notices=(run.notifications || []).slice(-5).reverse();
    $('web-chat-notices').innerHTML=(run.status==='completed'?`<div class="chat-notice"><strong>运行已完成</strong><p>${esc(run.completion?.reason || '')}</p></div>`:run.status==='paused'?'<div class="chat-notice">运行已暂停，可查看原因后继续讨论。</div>':'')+notices.map(n=>`<div class="chat-notice"><strong>${esc(n.message)}</strong><small>${n.route==='workspace'?'已记录到工作台':esc(labels[n.status] || n.status)}</small>${n.error?`<p class="chat-error">${esc(n.error)}</p>`:''}</div>`).join('');
  }else $('web-chat-notices').innerHTML='';
}
async function sendWebMessage(message,start=false){
  await savePreparation();await ensureRunConversation();
  const id=conversation.id;
  const sent=await api(`conversations/${id}/send`,{revision:conversation.revision,message,start,scope_task:page==='runs'?$('web-chat-scope').value || null:null});
  conversationDrafts.delete(id);
  if(conversation?.id!==id)return;
  conversation=sent;$('web-chat-input').value='';renderConversation();
}
async function pollConversation(){
  if(chatPollBusy||preparationSave||!['launch','runs'].includes(page)||!conversation?.id)return;
  chatPollBusy=true;const id=conversation.id;
  try{
    const current=await api('conversations/'+id);if(conversation?.id!==id||current.revision<conversation.revision)return;
    if(page==='launch'&&current.run_id){conversation=current;preparationDirty=false;await selectRun(current.run_id);return;}
    if(!preparationDirty){const changed=conversation.revision!==current.revision;conversation=current;if(changed&&page==='launch')populatePreparation();}
    else{conversation.messages=current.messages;conversation.busy=current.busy;conversation.recovery_required=current.recovery_required;}
    renderConversation();
  }catch(e){$('web-chat-status').textContent=e.message;}
  finally{chatPollBusy=false;}
}
async function loadPreparationCards(){
  preparationRows=(await api('conversations')).filter(d=>!d.run_id);renderPreparationNav();
  $('preparation-cards').innerHTML=preparationRows.map(d=>`<div class="panel preparation-card"><div><strong>${esc(d.title)}</strong><small>准备中 · 尚未启动</small></div>${navLink({type:'prepare',id:d.id},'继续准备 →')}</div>`).join('');
}
function renderPreparationNav(){
  $('preparation-heading').hidden=!preparationRows.length;
  const html=preparationRows.map(d=>`<a class="run-item ${activeRoute.type==='prepare'&&activeRoute.id===d.id?'chosen':''}" data-route-link href="${esc(routeHash({type:'prepare',id:d.id}))}" title="${esc(d.title)}"><strong>${esc(d.title)}</strong><small>准备中 · 尚未启动</small></a>`).join('');
  if($('preparation-list').innerHTML!==html)$('preparation-list').innerHTML=html;
}
function markPreparationDirty(){
  preparationEdits++;preparationDirty=true;$('preparation-saved').textContent='尚未保存';
  clearTimeout(savePreparation.timer);savePreparation.timer=setTimeout(()=>savePreparation().catch(err=>{$('preparation-saved').textContent='尚未保存 · '+err.message;}),600);
}
document.addEventListener('input',e=>{if(e.target.closest('#create-form,#web-agent-config')&&conversation)markPreparationDirty();});
$('web-agent-choice').addEventListener('change',()=>{const b=$('web-agent-choice')._options?.[$('web-agent-choice').value]?.config;if(!b)return;$('web-agent-command').value=b.command.join('\n');$('web-agent-cwd').value=b.cwd||'';$('web-agent-timeout').value=b.timeout||'';preparationEdits++;preparationDirty=true;});
$('web-chat-form').addEventListener('submit',e=>{e.preventDefault();safely(()=>sendWebMessage($('web-chat-input').value));});
document.addEventListener('click',e=>safely(async()=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.id==='preparation-back'){await savePreparation();await openLoop(conversation.launch.key);}
  if(b.id==='save-web-agent'){await savePreparation();toast('Agent 配置已保存');}
  if(b.id==='recover-web-agent'&&confirm('请先在平台所在机器核实旧 Agent 命令已停止。确认停止后才恢复。')){conversation=await api(`conversations/${conversation.id}/recover`,{confirmed_stopped:true});renderConversation();}
  if(b.id==='edit-prepared-loop'){await savePreparation();await newLoopDefinition(launchItem(),true);}
  if(b.dataset.mapChoice){
    if(page!=='launch'||conversation.busy||launchBusy)throw new Error('正在处理，请稍后再修改实现。');
    if(b.dataset.choice==='')delete launchBindings[b.dataset.mapChoice];else launchBindings={...launchBindings,[b.dataset.mapChoice]:JSON.parse(b.dataset.choice)};
    launchEpoch++;pendingLaunch=null;$('launch-confirm').hidden=true;$('launch-edit').hidden=false;$('launch-ack').checked=false;
    renderPreparationGraph();markPreparationDirty();
  }
  if(b.dataset.prepareChoice){const bindings=b.dataset.choice===''?{}:{[b.dataset.prepareChoice]:JSON.parse(b.dataset.choice)};await openPreparation(b.dataset.loopKey,bindings);}

}));
window.addEventListener('beforeunload',e=>{if(preparationDirty){e.preventDefault();e.returnValue='';}});
setInterval(pollConversation,1000);

document.addEventListener('change',event=>{if(event.target.id==='launch-fallback'&&page==='launch')renderPreparationGraph();});
