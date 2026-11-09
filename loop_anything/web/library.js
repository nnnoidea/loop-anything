'use strict';
// Read-only discovery and explicit launch. Author prose is escaped, never executed.
const guideFields = {purpose:'它能帮你做什么',suitable_for:'适合什么情况',not_for:'不适合与能力边界',preparation:'你需要准备什么',results:'你会获得什么',lifecycle:'怎样持续运行、等待和结束',participation:'什么时候需要你参与',effects:'外部影响与注意事项'};
const kindNames = {agent:'Agent',command:'同步脚本',external:'异步任务',loop:'调用 Loop',event:'等待外部事件',approval:'等待用户确认',timer:'等待时间',mock:'平台内置模拟'};
const objectValue = value => value && typeof value==='object' && !Array.isArray(value) ? value : {};
function guideOf(bp){return objectValue(bp.guide);}
function implementationOptions(entry){return entry?.kind?{default:entry}:(entry?.options || {});}
function defaultImplementation(entry){return entry?.kind?'default':entry?.default;}
function chosenImplementation(item,node,bindings={}){
  const entry=item.implementations[node],id=Object.hasOwn(bindings,node)?bindings[node]:defaultImplementation(entry);
  return implementationOptions(entry)[id] || null;
}
function taskImplementation(item,task,attempt){
  if(attempt?.implementation)return attempt.implementation;
  const explicit=task.spec.implementation;
  return explicit!=null?implementationOptions(item.implementations[task.spec.node])[explicit]||null:
    chosenImplementation(item,task.spec.node,item.settings?.bindings||{});
}

let preflightCache=new Map();
function fallbackSummary(item,node,bindings={}){
  if(!node)return '<strong>未启用自动兜底</strong><p>未覆盖转移会保留为异常，不自动唤醒 Agent。</p>';
  const config=chosenImplementation(item,node,bindings),id=Object.hasOwn(bindings,node)?bindings[node]:defaultImplementation(item.implementations[node]),checks=preflightCache.get(item.key||item.loop_key)?.checks.filter(c=>c.node===node&&c.implementation===id)||[],cwd=checks.find(c=>c.kind==='cwd')?.target||config?.cwd||(item.package_key?'Loop 包目录（运行前检查可查看实际路径）':'平台进程工作目录');
  return `<strong>异常交给：${esc(item.loop_definition.nodes[node]?.label||node)}${id?' · '+esc(config?.label||id):''}</strong><p>${!config?'尚未选择实现，无法自动唤醒。':config.kind!=='agent'?'所选实现不是 Agent，请修正。':config.dispatch?esc(executionLabel(config))+'；接单后执行，原请求可在节点协作记录中查看。':!config.command?.length?'未配置 Agent 命令；只能等待外部 Agent 接管，不能自动唤醒。':esc(executionLabel(config))+'，遵守已有执行身份与失败次数限制。'}</p>${config?.command?.length?`<p>工作目录：<code>${esc(cwd)}</code></p><details><summary>查看实际命令</summary><pre>${esc(pretty(config.command))}</pre></details><p class="small muted">Agent 的目录信任、登录和模型权限需自行确认；平台不会切换目录或修改信任配置。</p>`:''}${checks.filter(c=>c.status==='fail').map(c=>`<p class="task-error">启动配置需修正：${esc(checkNames[c.kind]||c.kind)} · ${esc(c.target)}</p>`).join('')}`;
}
function implementationSummary(item){
  const names=Object.keys(item.loop_definition.nodes),bound=names.filter(n=>Object.keys(implementationOptions(item.implementations[n])).length);
  return {missing:names.filter(n=>!chosenImplementation(item,n)),text:!bound.length?'仅Loop 定义 · 待接入实现':bound.length===names.length?'实现已绑定 · 环境另行检查':`部分实现 · ${bound.length}/${names.length} 已绑定`};
}
function executionLabel(implementation,version=2){
  if(implementation && !implementation.kind){const id=defaultImplementation(implementation),count=Object.keys(implementationOptions(implementation)).length;return `${count} 个候选 · `+(id?`默认 ${id}：`+executionLabel(implementationOptions(implementation)[id],version):'尚未选择默认实现');}
  if(!implementation)return '未选用实现 · 可在使用时选择';
  const label=kindNames[implementation.kind] || implementation.kind;
  if(implementation.kind==='mock' || (version!==2 && implementation.simulation))return label+' · 平台内置模拟';
  if(implementation.dispatch)return label+' · 委派'+(implementation.dispatch.location==='local'?'本服务':'团队')+'具名 Agent '+implementation.dispatch.agent_id;
  if(implementation.command?.length)return label+' · '+(implementation.executor?'执行端 '+implementation.executor+' 执行命令':'在平台所在机器执行命令')+(implementation.simulation?'（作者标注为模拟，仍执行命令）':'');
  if(implementation.kind==='agent')return label+' · 等待外部提交，未配置自动命令';
  return label;
}
function libraryCard(item){
  const bp=item.loop_definition,guide=guideOf(bp),summary=implementationSummary(item);
  return `<article class="panel catalog-card"><div class="library-card-top"><span class="loop-mark">↻</span><span class="badge">版本 ${esc(bp.version)}${item.archived_at?' · 已归档':''}</span></div><h2><button class="card-title" data-loop="${esc(item.key)}">${esc(bp.name || bp.id)}</button></h2><p class="muted card-description">${esc(guide.purpose || bp.description || '作者尚未提供用途说明。可先查看流程与使用准备。')}</p><p class="implementation-level">${esc(summary.text)}</p><div class="card-actions"><button class="primary" data-create="${esc(item.key)}">启动</button><button data-loop="${esc(item.key)}">了解这个 Loop →</button><button data-loop-archive="${esc(item.key)}" data-archived="${!!item.archived_at}">${item.archived_at?'取消归档':'归档'}</button><button data-loop-delete="${esc(item.key)}">删除版本</button></div></article>`;
}
function prose(title,text){return `<section class="guide-block"><h3>${esc(title)}</h3><p class="${text?'':'muted'}">${esc(text || '作者尚未提供，请向作者确认。')}</p></section>`;}
function docView(title,doc){
  if(!doc)return prose(title,'');
  const docs=Array.isArray(doc)?doc:[doc];
  return `<details class="loop-document"><summary>${esc(title)} · ${docs.length} 份</summary>${docs.map(d=>`<h4>${esc(d.name || title)}</h4><pre>${esc(typeof d==='string'?d:d.instructions || d.content || pretty(d))}</pre>`).join('')}</details>`;
}
const checkNames={agent_probe:'Agent 启动',lifecycle_probe:'状态转移验证',external_probe:'外部业务验证',implementation:'节点实现',manifest:'包定义完整性',asset:'随包资源',cwd:'工作目录',executable:'执行程序',script:'入口脚本',path:'作者要求的路径',program:'作者要求的程序',env:'环境变量',manual_or_event:'外部输入',runtime:'运行时行为',agent_access:'Agent 信任与访问权限',structure:'Loop 定义结构',environment:'本机环境'};
function checkAdvice(c){
  if(['agent_probe','lifecycle_probe','external_probe'].includes(c.kind))return c.detail;
  if(c.status==='pass')return '本项静态检查通过；没有执行脚本或调用模型。';
  if(c.kind==='implementation')return '由 Agent 或运行配置选择已有候选；实际需要这个节点时才检查。没有候选时由作者添加实现。';
  if(c.kind==='env')return '请自行配置这个环境变量，然后重新检查；不会显示变量值。';
  if(['cwd','path'].includes(c.kind))return '核对路径和本机目录；平台不会创建或改写。';
  if(['executable','script','program'].includes(c.kind))return '核对程序、脚本和运行环境；平台不会安装依赖或修改命令。';
  if(['asset','manifest'].includes(c.kind))return '包文件缺失或已变化，请自行核对来源与文件，平台不会修复。';
  if(c.kind==='agent_access')return '请在实际执行机器的所列工作目录确认 Agent 已允许非交互运行、完成登录并可访问模型；平台不会修改信任设置。';
  if(c.kind==='manual_or_event')return '需要外部事件或用户/Agent 提交结果；确认已有对应的提供方。';
  return '模型权限、服务连通性、脚本依赖和业务效果需另行验证；静态检查无法证明。';
}
function checkHTML(report){
  if(!report)return '<div class="loop-notice">尚未检查本机环境。绑定完整不等于可以成功运行。</div>';
  const failed=report.checks.filter(c=>c.status==='fail').length;
  return `<div class="loop-notice ${failed?'check-failed':''}"><strong>${failed?`${failed} 项需要处理`:'Loop 包可创建运行'}</strong><p>${report.mode==='runtime'?'已检查 Agent 启动及模拟状态转移；外部业务仍需验收。':'只检查，不执行、不修复。未知项仍需自行确认，不保证运行成功。'}</p></div><div class="check-list">${report.checks.map(c=>`<div class="check-row"><span class="badge ${c.status==='fail'?'fault':c.status==='pass'?'completed':'waiting'}">${({pass:'已检查',fail:'需处理',unknown:'未验证'})[c.status] || '未验证'}</span><div><strong>${esc(checkNames[c.kind] || c.kind)}</strong> <span class="check-target">${esc(c.target || '')}</span><p>${esc(checkAdvice(c))}</p>${c.status==='fail' && c.node?`<button data-editor-node="${esc(c.node)}">查看实现配置</button>`:''}<details><summary>检查依据</summary><p>${esc(c.detail || '')}</p></details></div></div>`).join('')}</div>`;
}
const loopPage=document.createElement('section');loopPage.id='loop-detail';loopPage.hidden=true;document.querySelector('main').append(loopPage);
async function openLoop(key){return navigateTo({type:'editor',id:key});}
document.addEventListener('click',event=>{const key=event.target.closest('[data-loop]')?.dataset.loop;if(key)safely(()=>openLoop(key));});

function sourceText(source){
  if(source?.task_ref||source?.task_refs)return '任务引用 '+(source.task_ref||pretty(source.task_refs))+' / '+source.port;
  if(!source || typeof source!=='object')return '查看完整契约';
  if(Object.hasOwn(source,'run'))return '本次启动参数：'+source.run;
  if(Object.hasOwn(source,'settings'))return 'Programmable Timeline：'+source.settings;
  if(Object.hasOwn(source,'record'))return '共享记录：'+source.record;
  if(Object.hasOwn(source,'records'))return '共享记录集合：'+pretty(source.records);
  if(Object.hasOwn(source,'from'))return '上游输出：'+source.from+' / '+source.port;
  if(Object.hasOwn(source,'$'))return '参数化来源：'+source.$;
  if(source.literal&&typeof source.literal==='object'&&Object.hasOwn(source.literal,'$'))return '本批参数：'+source.literal.$;
  if(Object.hasOwn(source,'literal'))return '固定值：'+pretty(source.literal);
  return '由具体 Task 指定来源';
}
