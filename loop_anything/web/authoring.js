'use strict';
// Read the real definition in full; only explicit lightweight actions write it.
let authorPlan='default',portConnection=null;
function readerJSON(title,value,open=false){return `<details class="reader-detail" ${open?'open':''}><summary>${esc(title)}</summary><pre>${esc(typeof value==='string'?value:pretty(value))}</pre></details>`;}
function lightDefaultsHTML(bp){
  const defaults=bp.defaults||{},schemas=bp.nodes[bp.entry]?.inputs||{};
  const fields=Object.entries(defaults).filter(([key,value])=>['string','number','boolean'].includes(typeof value)&&['string','number','integer','boolean'].includes(schemas[key]?.type));
  return fields.map(([key,value])=>`<label data-light-default="${esc(key)}">${esc(schemas[key].title||key)}${valueField(value,schemas[key],schemas[key].title||key)}${schemas[key].description?`<small>${esc(schemas[key].description)}</small>`:''}</label>`).join('')+(fields.length?'':'<p class="small muted">没有可直接调整的简单默认参数。本次运行的输入仍在启动准备中填写。</p>')+readerJSON('全部默认输入（只读）',defaults);
}
function collectLightDefaults(bp,root){
  for(const row of root.querySelectorAll('[data-light-default][data-light-changed]')){
    const key=row.dataset.lightDefault,value=readValue(row.querySelector('[data-value-type]'));
    if(['string','number','boolean'].includes(typeof value))bp.defaults={...(bp.defaults||{}),[key]:value};
  }
}
function readerAssetLink(path){return `<button type="button" data-open-scheme-asset="${esc(path)}">查看 ${esc(path)} ↗</button>`;}
function readerSkillsHTML(skills=[]){return skills.length?skills.map(skill=>`<details class="reader-detail"><summary>${esc(skill.name||skill.path||'业务说明')}</summary>${skill.content||skill.instructions?`<pre>${esc(skill.content||skill.instructions)}</pre>`:''}${skill.path?readerAssetLink(skill.path):''}${readerJSON('完整 Skill 声明',skill)}</details>`).join(''):'<p class="small muted">尚未绑定 Skill。</p>';}
function readerDocumentsHTML(item){
  const bp=item.loop_definition;
  return `<details class="reader-detail"><summary>Loop 手册、使用说明与包文件</summary>${readerSkillsHTML(bp.handbook?[bp.handbook]:[])}${docView('给使用者的说明',bp.guide)}<h4>包文件 · ${(item.assets||[]).length}</h4><div class="reader-files">${(item.assets||[]).map(a=>readerAssetLink(a.path)).join('')||'<p>未附带文件。</p>'}</div>${readerJSON('环境要求与检查声明',{requires:bp.requires||[],checks:item.checks||{}})}${readerJSON('已声明的验收场景',bp.scenarios||[])}</details><details class="reader-detail"><summary>全局安排与异常处理</summary>${fallbackSummary(item,bp.fallback_node)}${readerJSON('入口、兜底、全局 Agent 与限制',{entry:bp.entry,fallback_node:bp.fallback_node,global_agent_node:bp.global_agent_node,limits:bp.limits})}</details>`;
}
function readerPlansHTML(bp){return `<details class="reader-detail"><summary>任务生成模板与依赖 · ${Object.keys(bp.plans||{}).length} 个模板</summary><p class="small muted">查看实际条件、批量展开、输入来源及参数映射。修改这些规则请交给 Agent。</p>${Object.entries(bp.plans||{}).map(([id,plan])=>`<details class="reader-detail"><summary>${esc(id)} · ${Object.keys(plan.steps||{}).length} 步</summary>${readerJSON('模板参数契约',plan.parameters||{})}${Object.entries(plan.steps||{}).map(([key,step])=>readerJSON(key+' · '+(bp.nodes[step.node]?.label||step.node),step)).join('')}${readerJSON('完整模板',plan)}</details>`).join('')}</details>`;}
function authorPortButtons(id,node){return `<div class="reader-ports"><span>输入：${esc(Object.keys(node.inputs||{}).join('、')||'无')}</span><span>输出：${esc(Object.keys(node.outputs||{}).join('、')||'无')}</span></div>`;}
function readerCandidateHTML(item,nodeId,id,config){
  const current=defaultImplementation(item.implementations[nodeId])===id;
  const refs=[...new Set([...(config.command||[]),...(config.observe||[]),...(config.resume_command||[])].map(arg=>arg.replace(/^\.\//,'')))].filter(path=>(item.assets||[]).some(a=>a.path===path));
  return `<article class="reader-candidate"><h3>${esc(config.label||id)} <small>${esc(kindNames[config.kind]||config.kind)}${current?' · 默认方案':''}</small></h3><p>${esc(config.description||'尚未填写用途说明')}</p><p class="small muted">查看方案不改变选择。设为默认只影响保存后创建的新运行。</p>${!current?`<button type="button" data-reader-default="${esc(id)}" data-reader-default-node="${esc(nodeId)}">设为默认方案</button>`:''}${nodeSignalsHTML(item,nodeId,config)}${readerJSON('执行入口与监控',{command:config.command,observe:config.observe,cwd:config.cwd,timeout:config.timeout,dispatch:config.dispatch,agent_cli:config.agent_cli,terminal:config.terminal,resume_command:config.resume_command},true)}${config.kind==='agent'?readerJSON('唤醒 prompt · '+(config.prompt===undefined?'平台默认':'作者提供'),config.prompt??promptDefaults.task??'尚未加载默认提示词'):''}${readerJSON('任务参数契约',config.parameter_schema||{})}${config.wait||config.event?readerJSON('等待条件',{wait:config.wait,event:config.event},true):''}<h4>执行状态与完整转移矩阵</h4>${lifecycleMatrix(config,undefined,true)}${readerJSON('完整实现配置',config)}${refs.length?'<h4>引用的包文件</h4>'+refs.map(readerAssetLink).join(''):''}</article>`;
}
function renderAuthorProperties(){
  const root=$('editor-properties'),bp=editor.loop_definition,id=editSelection?.node,node=bp.nodes[id];
  if(!node){$('property-title').textContent='节点详情';root.innerHTML='<p>选择节点阅读职责、数据来源、契约、Skill 与实现。整体流程和完整执行规则分别在上方查看。</p>';return;}
  $('property-title').textContent=(node.label||id)+' · '+id;
  const options=implementationOptions(editor.implementations[id]),candidate=activeRoute.implementation;
  const ports=direction=>Object.entries(node[direction]||{}).map(([name,schema])=>readerJSON(name,direction==='outputs'?{...schema,schema:bp.records?.[schema.record_type]}:schema)).join('')||'<p class="small muted">无</p>';
  root.innerHTML=`<section class="reader-node"><h3>节点职责</h3><p class="reader-prose">${esc(node.instructions||'尚未填写')}</p>${candidate?'':`<h3>输入契约</h3>${ports('inputs')}<h3>输出契约</h3>${ports('outputs')}${readerJSON('节点参数契约',node.parameter_schema||{})}<details class="reader-detail"><summary>数据来源、去向与任务安排</summary>${nodeFlowHTML(bp,id,loopRelationships(bp))}${readerJSON('事件触发规则',node.routes||[])}${readerJSON('脚本主动安排范围',node.plan_nodes||[])}</details>`}<h3>节点 Skill 与业务说明</h3>${readerSkillsHTML(node.skills)}<h3>实现方案 · ${Object.keys(options).length}</h3>${candidate?(options[candidate]?readerCandidateHTML(editor,id,candidate,options[candidate]):'<p>该实现已不存在，请返回节点重新选择。</p>'):Object.entries(options).map(([key,value])=>`<div class="reader-candidate-summary"><strong>${esc(value.label||key)}</strong><p>${esc(value.description||executionLabel(value))}</p><small>${esc(kindNames[value.kind]||value.kind)}${defaultImplementation(editor.implementations[id])===key?' · 默认方案':''}</small><button type="button" data-editor-node="${esc(id)}" data-editor-implementation="${esc(key)}">查看完整方案 ↗</button></div>`).join('')||'<p>暂无实现，请由 Agent 补充。</p>'}${readerJSON('完整节点定义',node)}</section>`;
}
const readerAgentDialog=document.createElement('dialog');readerAgentDialog.className='reader-agent-dialog';document.body.append(readerAgentDialog);
function showReaderAgentHelp(){
  const target=page==='editor'&&editor?.id?`请用 Loop Anything 平台工具读取草稿 ${editor.id}（revision ${editor.revision}），结合现有节点、实现、Skill 和脚本修改。保留未涉及的配置，修改业务流程后同步更新流程图。具体需求：`:'请用 Loop Anything 平台 Skill，结合我的目标复用或构建 Loop。具体需求：';
  readerAgentDialog.innerHTML=`<div class="dialog-heading"><h2>交给你的 Agent</h2><button type="button" class="close-dialog" aria-label="关闭">×</button></div><p>将下面的定位信息和修改要求发给你正在使用的 Agent；这里不会自动启动另一个 Agent。</p><textarea aria-label="发给 Agent 的定位信息" readonly>${esc(target)}</textarea><a class="button" href="/api/skills" download="loop-anything-skills.zip">下载平台 Skill</a><button type="button" class="close-dialog">关闭</button>`;
  readerAgentDialog.showModal();
}
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.id==='reader-agent'){await saveEditor();showReaderAgentHelp();}
  if(button.dataset.readerDefault){await editWithTool('set_implementation',{node_id:button.dataset.readerDefaultNode,implementation_id:button.dataset.readerDefault,default:true});toast('默认方案已保留到草稿，保存后供新运行使用。');}
}));
editorPage.addEventListener('input',event=>{const row=event.target.closest('[data-light-default],#bp-name,#bp-description');if(row)row.dataset.lightChanged='true';});
