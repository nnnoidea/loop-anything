'use strict';
// Read-only discovery and explicit launch. Author prose is escaped, never executed.
const guideFields = {purpose:'它能帮你做什么',suitable_for:'适合什么情况',not_for:'不适合与能力边界',preparation:'你需要准备什么',results:'你会获得什么',lifecycle:'怎样持续运行、等待和结束',participation:'什么时候需要你参与',effects:'外部影响与注意事项'};
const kindNames = {agent:'Agent 决策',command:'同步脚本',external:'异步任务',event:'等待外部事件',approval:'等待用户确认',mock:'平台内置模拟'};
const objectValue = value => value && typeof value==='object' && !Array.isArray(value) ? value : {};
function guideOf(bp){return objectValue(bp.guide);}
function implementationOptions(entry){return entry?.kind?{default:entry}:(entry?.options || {});}
function defaultImplementation(entry){return entry?.kind?'default':entry?.default;}
function chosenImplementation(item,node,bindings={}){
  const entry=item.implementations[node],id=Object.hasOwn(bindings,node)?bindings[node]:defaultImplementation(entry);
  return implementationOptions(entry)[id] || null;
}
function bindingFields(item,bindings={}){
  return Object.entries(item.loop_definition.nodes).map(([node,n])=>{
    const entry=item.implementations[node],defaultId=defaultImplementation(entry),value=Object.hasOwn(bindings,node)?JSON.stringify(bindings[node]):'';
    const choices=[['',defaultId?'沿用 Loop 默认 · '+defaultId:'沿用 Loop · 尚无默认'],['null','暂不选用'],...Object.entries(implementationOptions(entry)).map(([id,config])=>[JSON.stringify(id),id+' · '+(kindNames[config.kind] || config.kind)])];
    return `<label>${esc(n.label || node)}<select data-binding-node="${esc(node)}">${choices.map(([v,label])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(label)}</option>`).join('')}</select></label>`;
  }).join('');
}
function fallbackOptions(bp,value){
  return '<option value="">不启用 Agent 兜底</option>'+Object.entries(bp.nodes).filter(([id,n])=>id!==bp.entry && !Object.keys(n.inputs || {}).length).map(([id,n])=>`<option value="${esc(id)}" ${value===id?'selected':''}>${esc(n.label || id)}</option>`).join('');
}
function readBindingFields(container){return Object.fromEntries([...container.querySelectorAll('[data-binding-node]')].filter(e=>e.value!=='').map(e=>[e.dataset.bindingNode,JSON.parse(e.value)]));}
function preventsStart(report){return report.checks.some(c=>c.status==='fail' && ['manifest','asset','structure'].includes(c.kind));}
function implementationSummary(item){
  const names=Object.keys(item.loop_definition.nodes),bound=names.filter(n=>Object.keys(implementationOptions(item.implementations[n])).length);
  return {missing:names.filter(n=>!chosenImplementation(item,n)),text:!bound.length?'仅Loop 定义 · 待接入实现':bound.length===names.length?'实现已绑定 · 环境另行检查':`部分实现 · ${bound.length}/${names.length} 已绑定`};
}
function executionLabel(implementation,version=2){
  if(implementation && !implementation.kind){const id=defaultImplementation(implementation),count=Object.keys(implementationOptions(implementation)).length;return `${count} 个候选 · `+(id?`默认 ${id}：`+executionLabel(implementationOptions(implementation)[id],version):'尚未选择默认实现');}
  if(!implementation)return '未选用实现 · 可在使用时选择';
  const label=kindNames[implementation.kind] || implementation.kind;
  if(implementation.kind==='mock' || (version!==2 && implementation.simulation))return label+' · 平台内置模拟';
  if(implementation.command)return label+' · 执行本机命令'+(implementation.simulation?'（作者标注为模拟，仍执行命令）':'');
  if(implementation.kind==='agent')return label+' · 等待外部提交，未配置自动命令';
  return label;
}
function libraryCard(item){
  const bp=item.loop_definition,guide=guideOf(bp),summary=implementationSummary(item);
  return `<article class="panel catalog-card"><div class="library-card-top"><span class="loop-mark">↻</span><span class="badge">版本 ${esc(bp.version)}</span></div><h2><button class="card-title" data-loop="${esc(item.key)}">${esc(bp.name || bp.id)}</button></h2><p class="muted card-description">${esc(guide.purpose || bp.description || '作者尚未提供用途说明。可先查看流程与使用准备。')}</p><p class="implementation-level">${esc(summary.text)}</p><div class="card-actions"><button class="primary" data-create="${esc(item.key)}">启动</button><button data-loop="${esc(item.key)}">了解这个 Loop →</button></div></article>`;
}
const loopPage=document.createElement('section');loopPage.id='loop-detail';loopPage.hidden=true;document.querySelector('main').append(loopPage);
const authorizationField=document.createElement('label');authorizationField.innerHTML='本次用户授权<textarea id="create-authorization" rows="3" placeholder="例如：可自行修复并继续实验，但不得增加预算"></textarea>';$('create-title').parentElement.after(authorizationField);
let loopKey=null,loopTab='overview',preflightCache=new Map(),pendingLaunch=null,launchMode='form',launchBusy=false,launchEpoch=0;
function currentLoop(){return catalog.find(c=>c.key===loopKey);}
async function openLoop(key,tab='overview'){
  await navigateTo({type:'loop',key,tab});
}
function prose(title,text){return `<section class="guide-block"><h3>${esc(title)}</h3><p class="${text?'':'muted'}">${esc(text || '作者尚未提供，请向作者确认。')}</p></section>`;}
function docView(title,doc){
  if(!doc)return prose(title,'');
  const docs=Array.isArray(doc)?doc:[doc];
  return `<details class="loop-document"><summary>${esc(title)} · ${docs.length} 份</summary>${docs.map(d=>`<h4>${esc(d.name || title)}</h4><pre>${esc(typeof d==='string'?d:d.instructions || d.content || pretty(d))}</pre>`).join('')}</details>`;
}
function loopHandbookHTML(bp,timelineGuide=''){
  return `<p class="small muted">作者说明介绍本 Loop 的用途和使用要求；作者 Skill 直接绑定到节点，处理任务时按需读取。平台说明教授通用工具操作。</p>${docView('作者提供 · Loop 业务说明',bp.handbook)}${timelineGuide?docView('平台提供 · Timeline 工具',timelineGuide):''}<button id="download-loop-package">下载 Loop 包（含节点 Skill）</button>`;
}
async function downloadLoopPackage(){
  const item=currentLoop();if(!item)return;
  const content=item.package_key?await api('packages/read',{key:item.package_key}):{document:{loop_definition:item.loop_definition,implementations:item.implementations},assets:[]};
  const result=await api('packages/export',content);
  downloadPackage(result.base64,item.loop_definition.id);
}
function overviewHTML(item){
  const bp=item.loop_definition,g=guideOf(bp);
  return `${loopGraphHTML(item)}<p class="source-note">以下为作者说明，不代表平台已验证业务效果。缺少说明时不会自动猜测。</p><div class="guide-grid">${Object.entries(guideFields).map(([k,title])=>prose(title,g[k] || (k==='purpose'?bp.description:''))).join('')}</div>${loopHandbookHTML(bp,item.timeline_guide)}<p>Agent 兜底：${bp.fallback_node?esc(bp.nodes[bp.fallback_node]?.label || bp.fallback_node):'未启用'}。可在启动时调整。</p><details><summary>高级 · Loop 定义与绑定（只读）</summary><pre>${esc(pretty(item))}</pre></details><section id="loop-runs"></section>`;
}
function sourceText(source){
  if(!source || typeof source!=='object')return '查看完整契约';
  if(Object.hasOwn(source,'run'))return '本次启动参数：'+source.run;
  if(Object.hasOwn(source,'settings'))return 'Programmable Timeline：'+source.settings;
  if(Object.hasOwn(source,'record'))return '共享记录：'+source.record;
  if(Object.hasOwn(source,'records'))return '共享记录集合：'+pretty(source.records);
  if(Object.hasOwn(source,'from'))return '节点输出：'+pretty(source.from);
  if(Object.hasOwn(source,'literal'))return '固定值：'+pretty(source.literal);
  return '由具体 Task 指定来源';
}
function flowHTML(item,showGraph=true){
  const bp=item.loop_definition;
  const rules=bp.schema_version===2?Object.entries(bp.plans || {}).map(([name,p])=>`<li><strong>${esc(name)}</strong> · ${Object.entries(p.steps).map(([k,s])=>esc(k)+(s.each?'（按列表展开）':'')).join('、')}<details><summary>查看参数、输入绑定与聚合</summary><pre>${esc(pretty(p))}</pre></details></li>`):(bp.transitions || []).map(r=>`<li>${esc(r.from)} → ${esc(r.to)}</li>`);
  return `${showGraph?loopGraphHTML(item):''}<div class="loop-notice">这里展示可用步骤模板，不是一次运行的固定路线。Agent 可在授权范围内规划具体 Task；Timeline 工具按模板构建本轮 Tasks；Engine 只推进已安排且输入就绪的工作。没有画出的动态计划，不代表不会发生。</div><h3>从「${esc(bp.nodes[bp.entry]?.label || bp.entry)}」开始</h3><p class="muted">展开一个步骤，了解它的职责和交接信息。</p><div class="step-grid">${Object.entries(bp.nodes).map(([id,node])=>`<details class="step-card"><summary><span>${esc(node.label || id)}</span><small>${esc(executionLabel(item.implementations[id],bp.schema_version))}</small></summary><p>${esc(node.description || node.instructions || '作者尚未说明本步骤职责。')}</p><h4>需要哪些信息</h4><ul>${Object.entries(node.inputs || {}).map(([name,spec])=>`<li><strong>${esc(name)}</strong> · ${esc(spec.type || '按来源读取')}<br>${esc(sourceText(bp.schema_version===2?(id===bp.entry?bp.seed?.inputs?.[name]:null):spec))}</li>`).join('') || '<li>未声明输入</li>'}</ul><h4>会写入哪些结果</h4><ul>${Object.entries(node.outputs || {}).map(([name,spec])=>`<li>${esc(name)} · ${esc(spec.record_type?'共享记录 '+spec.record_type:spec.type)}</li>`).join('') || '<li>未声明输出</li>'}</ul>${chosenImplementation(item,id)?.kind!=='agent' && node.plan_nodes?.length?`<p>脚本可新增的声明任务：${node.plan_nodes.map(n=>esc(bp.nodes[n]?.label || n)).join('、')}。是否规划取决于运行时决策。</p>`:''}<p class="muted">可能等待：输入未就绪、运行暂停，或本步骤所需的外部事件 / 用户结果。</p>${docView('节点专业 Skill',node.skills?.length?node.skills:null)}<details><summary>高级 · 完整节点契约</summary><pre>${esc(pretty(node))}</pre></details></details>`).join('')}</div><h3>本轮构建模板</h3><ul class="rule-list">${rules.join('') || '<li>未声明构建模板。作者可使用构建工具补充模板；运行时按 Timeline 规则或终止信号结束。</li>'}</ul>`;
}
const checkNames={implementation:'节点实现',manifest:'包定义完整性',asset:'随包资源',cwd:'工作目录',executable:'执行程序',script:'入口脚本',path:'作者要求的路径',program:'作者要求的程序',env:'环境变量',manual_or_event:'外部输入',runtime:'运行时行为',structure:'Loop 定义结构',environment:'本机环境'};
function checkAdvice(c){
  if(c.status==='pass')return '本项静态检查通过；没有执行脚本或调用模型。';
  if(c.kind==='implementation')return '启动或运行时可选择已有候选；实际需要这个节点时才检查。没有候选时由作者添加实现。';
  if(c.kind==='env')return '请自行配置这个环境变量，然后重新检查；不会显示变量值。';
  if(['cwd','path'].includes(c.kind))return '核对路径和本机目录；平台不会创建或改写。';
  if(['executable','script','program'].includes(c.kind))return '核对程序、脚本和运行环境；平台不会安装依赖或修改命令。';
  if(['asset','manifest'].includes(c.kind))return '包文件缺失或已变化，请自行核对来源与文件，平台不会修复。';
  if(c.kind==='manual_or_event')return '需要外部事件或用户/Agent 提交结果；确认已有对应的提供方。';
  return '模型权限、服务连通性、脚本依赖和业务效果需另行验证；静态检查无法证明。';
}
function checkHTML(report){
  if(!report)return '<div class="loop-notice">尚未检查本机环境。绑定完整不等于可以成功运行。</div>';
  const failed=report.checks.filter(c=>c.status==='fail').length;
  return `<div class="loop-notice ${failed?'check-failed':''}"><strong>${failed?`${failed} 项需要处理`:'Loop 包可创建运行'}</strong><p>只检查，不执行、不修复。未知项仍需自行确认，不保证运行成功。</p></div><div class="check-list">${report.checks.map(c=>`<div class="check-row"><span class="badge ${c.status==='fail'?'fault':c.status==='pass'?'completed':'waiting'}">${({pass:'已检查',fail:'需处理',unknown:'未验证'})[c.status] || '未验证'}</span><div><strong>${esc(checkNames[c.kind] || c.kind)}</strong> <span class="check-target">${esc(c.target || '')}</span><p>${esc(checkAdvice(c))}</p>${c.status==='fail' && c.node?`<button data-setup-node="${esc(c.node)}">定位到实现配置</button>`:''}<details><summary>检查依据</summary><p>${esc(c.detail || '')}</p></details></div></div>`).join('')}</div>`;
}
function preparationHTML(item){
  const bp=item.loop_definition,summary=implementationSummary(item);
  return `<h3>1 · 这个 Loop 带来了什么</h3><p>${esc(summary.text)}。未绑定也可以保存、分享和安装。</p><div class="check-list">${Object.entries(bp.nodes).map(([id,n])=>`<div class="check-row"><span class="badge ${item.implementations[id]?'':'waiting'}">${item.implementations[id]?'已绑定':'待接入'}</span><div><strong>${esc(n.label || id)}</strong><p>${esc(executionLabel(item.implementations[id],bp.schema_version))}</p>${item.implementations[id]?`<details><summary>查看当前实现（只读）</summary><pre>${esc(pretty(item.implementations[id]))}</pre></details>`:''}<button data-setup-node="${esc(id)}">${item.implementations[id]?'编辑候选实现':'添加候选实现'}</button></div></div>`).join('')}</div><p class="small muted">候选实现的编辑保存在 Loop 中；启动时可以直接改选已有候选，不需要复制 Loop。</p>${loopHandbookHTML(bp,item.timeline_guide)}<h3>2 · 这台机器是否准备好</h3><button id="loop-check">运行前检查</button><div id="loop-check-result" aria-live="polite">${checkHTML(preflightCache.get(item.key))}</div>`;
}
function renderLoop(){
  const item=currentLoop();if(!item)return;const bp=item.loop_definition;
  loopPage.innerHTML=`<div class="page-heading"><div><button id="library-back" class="back-link">← Loop 库</button><h1>${esc(bp.name || bp.id)}</h1><span class="muted">版本 ${esc(bp.version)} · ${esc(implementationSummary(item).text)}</span></div><div class="toolbar"><button data-copy-loop-definition="${esc(item.key)}">复制为另一个 Loop</button><button data-version-loop-definition="${esc(item.key)}">编辑 Loop</button><button class="primary" data-create="${esc(item.key)}">启动</button></div></div><div class="loop-content panel"><div class="tabs">${[['overview','概览'],['flow','流程与步骤'],['prepare','使用准备']].map(([k,label])=>`<button data-loop-tab="${k}" class="${loopTab===k?'selected':''}" aria-pressed="${loopTab===k}">${label}</button>`).join('')}</div><div class="loop-tab-body">${loopTab==='overview'?overviewHTML(item):loopTab==='flow'?flowHTML(item):preparationHTML(item)}</div></div>`;
}
async function preflight(item){
  let report;
  if(item.package_key)report=await api('packages/smoke',{key:item.package_key});
  else {
    const result=await api('validate',{loop_definition:item.loop_definition,implementations:item.implementations});
    report={checks:[...result.errors.map(detail=>({kind:'structure',status:'fail',target:'Loop 定义',detail})),...implementationSummary(item).missing.map(node=>({kind:'implementation',status:'fail',target:node,node})),{kind:'environment',status:'unknown',target:'旧版 / 非包资产',detail:'此资产没有安装包清单。仅检查结构，未检查路径、程序或外部服务。'}]};
  }
  if(item.loop_definition.schema_version!==2)report.checks.unshift({kind:'structure',status:'fail',target:'历史 v1 协议',detail:'旧Loop 定义仅供查看，不能启动；请发布 Timeline-based 新版本。'});
  preflightCache.set(item.key,report);return report;
}
// Labels are author metadata. Types come from contracts/defaults, not prose.
function launchFields(bp,values){
  const specs=new Map(), defaults=objectValue(bp.defaults), metadata=objectValue(guideOf(bp).parameters);
  for(const key of new Set([...Object.keys(defaults),...Object.keys(values),...Object.keys(metadata)]))specs.set(key,{key,required:false});
  const add=(source,schema)=>{if(typeof source?.run!=='string' || !source.run)return;const parts=source.run.split('.'),key=parts[0],old=specs.get(key)||{key};specs.set(key,{...old,required:true,...(parts.length===1?{schema}: {schema:{type:'object'}})});};
  if(bp.schema_version===2){
    for(const [port,source] of Object.entries(bp.seed?.inputs || {}))add(source,bp.nodes[bp.entry].inputs[port]);
  }else for(const node of Object.values(bp.nodes))for(const source of Object.values(node.inputs || {}))add(source,null);
  return [...specs.values()].map(s=>{const val=values[s.key] ?? defaults[s.key];const type=s.schema?.type || (val===null || val===undefined?'json':Array.isArray(val)?'array':typeof val);return {...s,type,label:metadata[s.key]?.label || s.key,description:metadata[s.key]?.description || '作者未提供参数解释；请结合操作手册填写。'};});
}
function parseField(text,type,label){
  if(type==='string')return text;
  let value;try{value=JSON.parse(text);}catch{throw new Error(label+'：请填写有效的 '+(type==='json'?'JSON':type)+' 值');}
  const valid=type==='json' || (type==='array'?Array.isArray(value):type==='object'?value!==null && typeof value==='object' && !Array.isArray(value):type==='integer'?Number.isInteger(value):typeof value===type);
  if(!valid || (typeof value==='number' && !Number.isFinite(value)))throw new Error(label+'：值的类型应为 '+type);
  return value;
}
function validateInput(value,schema,label){
  if(!schema)return;
  parseField(schema.type==='string'?value:JSON.stringify(value),schema.type,label);
  if(schema.type==='string' && typeof value!=='string')throw new Error(label+'：需要文本');
  if(schema.nonempty && (value==='' || value===false || value===0 || value==null || (typeof value==='object' && !Object.keys(value).length)))throw new Error(label+'：不能为空');
  if(schema.enum && !schema.enum.some(v=>pretty(v)===pretty(value)))throw new Error(label+'：请选择契约允许的值');
  if(['integer','number'].includes(schema.type)){
    if(schema.minimum!==undefined && value<schema.minimum)throw new Error(label+'：不能小于 '+schema.minimum);
    if(schema.maximum!==undefined && value>schema.maximum)throw new Error(label+'：不能大于 '+schema.maximum);
  }
  if(schema.type==='object'){
    for(const k of schema.required || [])if(!Object.hasOwn(value,k))throw new Error(label+'：缺少 '+k);
    if(schema.additionalProperties===false && Object.keys(value).some(k=>!Object.hasOwn(schema.properties || {},k)))throw new Error(label+'：包含未声明字段');
    for(const [k,s] of Object.entries(schema.properties || {}))if(Object.hasOwn(value,k))validateInput(value[k],s,label+'.'+k);
  }
  if(schema.type==='array'){
    if(value.length<(schema.minItems || 0) || value.length>(schema.maxItems ?? Infinity))throw new Error(label+'：数组长度不符合契约');
    if(schema.uniqueItems && new Set(value.map(pretty)).size!==value.length)throw new Error(label+'：数组元素不能重复');
    if(schema.items)value.forEach((v,i)=>validateInput(v,schema.items,label+'['+i+']'));
  }
}
function effectiveLaunchInputs(bp,inputs){
  const values=Object.assign(Object.create(null),objectValue(bp.defaults),inputs);
  if(bp.schema_version===2)for(const [port,source] of Object.entries(bp.seed.inputs)){
    if(!Object.hasOwn(source,'run'))continue;
    let value=values;
    for(const key of source.run?source.run.split('.'):[]){if(value==null || !Object.hasOwn(value,key))throw new Error('缺少启动参数：'+source.run);value=value[key];}
    validateInput(value,bp.nodes[bp.entry].inputs[port],guideOf(bp).parameters?.[source.run]?.label || source.run);
  }
  return values;
}
function renderLaunchFields(item){
  const values=JSON.parse($('create-inputs').value);
  if(!values || typeof values!=='object' || Array.isArray(values))throw new Error('初始输入必须是 JSON 对象');
  const fields=launchFields(item.loop_definition,values);
  $('launch-fields').innerHTML='<h3>这次运行需要什么</h3>'+fields.map((f,i)=>{
    const value=values[f.key],str=value===undefined?'':f.type==='string'?value:pretty(value);
    const enumValues=f.schema?.enum || (f.type==='boolean'?[true,false]:null);
    const attrs=`id="launch-field-${i}" data-launch-field="${i}"`;
    const input=enumValues?`<select ${attrs}><option value="">请选择</option>${enumValues.map(v=>`<option value="${esc(pretty(v))}" ${pretty(v)===pretty(value)?'selected':''}>${esc(typeof v==='string'?v:pretty(v))}</option>`).join('')}</select>`:`<textarea ${attrs} rows="${['object','array','json'].includes(f.type)?4:2}">${esc(str)}</textarea>`;
    return `<label for="launch-field-${i}">${esc(f.label)}${f.required?' · 必需':''}</label>${input}<p class="field-note">${esc(f.description)} <span class="mono">${esc(f.key)} · ${esc(f.type)}</span></p>`;
  }).join('') || '<p>没有声明启动参数。</p>';
  $('launch-fields')._fields=fields;
}
function collectLaunchInputs(requireComplete=true){
  let values=JSON.parse($('create-inputs').value);
  if(!values || typeof values!=='object' || Array.isArray(values))throw new Error('初始输入必须是 JSON 对象');
  if(launchMode==='form'){
    values=Object.assign(Object.create(null),values);
    for(const [i,f] of $('launch-fields')._fields.entries()){
      const el=$('launch-field-'+i),text=el.value;
      if(!text && f.type!=='string'){if(f.required&&requireComplete)throw new Error('请填写 '+f.label);delete values[f.key];continue;}
      values[f.key]=parseField(text,el.tagName==='SELECT'?'json':f.type,f.label);
    }
  }
  $('create-inputs').value=pretty(values);return values;
}
function prepareLaunch(item){
  if(!$('launch-fallback'))$('launch-fields').insertAdjacentHTML('afterend','<label>Agent 兜底节点<select id="launch-fallback"></select></label><p class="small muted">未覆盖状态交给所选节点。Agent 由该节点的实现选择决定；留空时只记录问题。</p>');
  if(!$('launch-global-agent'))$('launch-fallback').parentElement.insertAdjacentHTML('afterend','<label>全局 Agent 节点<select id="launch-global-agent"></select></label>');
  $('launch-global-agent').innerHTML=globalAgentOptions(item.loop_definition,item.loop_definition.global_agent_node);
  $('launch-fallback').innerHTML=fallbackOptions(item.loop_definition,item.loop_definition.fallback_node);
  $('create-authorization').value='';launchEpoch++;pendingLaunch=null;launchMode='form';$('create-dialog').scrollTop=0;$('launch-error').textContent='';$('launch-confirm').hidden=true;$('launch-edit').hidden=false;$('launch-fields').hidden=false;$('launch-json').hidden=true;$('launch-mode').textContent='切换到高级 JSON';$('launch-ack').checked=false;
  $('create-implementation-note').textContent='接下来会检查本机条件，并列出实际执行方式。现在不会启动任何工作。';renderLaunchFields(item);
}
function executionHTML(item,bindings={}){
  return `<h4>将按这些绑定执行</h4><ul class="execution-list">${Object.keys(item.loop_definition.nodes).map(id=>[id,chosenImplementation(item,id,bindings) || {}]).map(([id,b])=>`<li><strong>${esc(item.loop_definition.nodes[id]?.label || id)}</strong> · ${esc(executionLabel(b,item.loop_definition.schema_version))}${b.command?`<details><summary>查看命令与工作目录</summary><pre>${esc(pretty({command:b.command,observe:b.observe,cwd:b.cwd || '平台进程工作目录'}))}</pre></details>`:''}</li>`).join('')}</ul><p class="small">只有明确的审批节点 / 暂停规则才会等待确认；不能假设所有外部操作都会询问你。启动后可在运行详情暂停或终止，已发生的外部操作不会被撤销。</p>${prose('作者说明 · 外部影响',guideOf(item.loop_definition).effects)}${prose('作者说明 · 人工参与',guideOf(item.loop_definition).participation)}${Object.keys(item.loop_definition.limits || {}).length?`<details><summary>平台运行预算上限</summary><pre>${esc(pretty(item.loop_definition.limits))}</pre></details>`:''}`;
}
async function reviewLaunch(){
  if(launchBusy)return;const epoch=launchEpoch;launchBusy=true;$('launch-review').disabled=true;
  try{
    const item=catalog.find(c=>c.key===$('create-loop_definition').value),inputs=effectiveLaunchInputs(item.loop_definition,collectLaunchInputs()),title=$('create-title').value.trim();
    if(!title)throw new Error('请填写运行名称');
    const report=await preflight(item);
    if(epoch!==launchEpoch || !$('create-dialog').open)return;
    if(preventsStart(report)){$('launch-error').textContent='运行前检查发现缺项，请先在「使用准备」中处理。';$('create-dialog').close();await openLoop(item.key,'prepare');toast('发现阻塞项，尚未启动。请查看使用准备。');return;}
    await savePreparation();
    pendingLaunch={key:item.key,title,inputs,authorization:$('create-authorization').value,bindings:structuredClone(launchBindings),fallback_node:$('launch-fallback').value,global_agent_node:$('launch-global-agent').value};
    $('launch-summary').innerHTML=prose('使用的 Loop',item.loop_definition.name || item.loop_definition.id)+prose('运行名称',title)+prose('用户授权',pendingLaunch.authorization || '未提供额外授权')+`<h4>本次参数</h4><dl class="input-summary">${Object.entries(inputs).map(([k,v])=>`<dt>${esc(guideOf(item.loop_definition).parameters?.[k]?.label || k)}</dt><dd>${esc(typeof v==='string'?v:pretty(v))}</dd>`).join('') || '<dd>无启动参数</dd>'}</dl>`+executionHTML(item,pendingLaunch.bindings)+`<h4>运行前检查</h4>${launchCheckHTML(report)}`;
    $('launch-edit').hidden=true;$('launch-confirm').hidden=false;$('launch-ack').checked=false;$('launch-start').disabled=false;$('create-dialog').scrollTop=0;
  }catch(error){$('launch-error').textContent=error.message;}
  finally{launchBusy=false;$('launch-review').disabled=false;}
}
function launchCheckHTML(report){
  const unknown=report.checks.filter(c=>c.status==='unknown');
  return `<div class="loop-notice"><strong>Loop 包可创建运行 · ${unknown.length} 项仍未验证</strong><p>未验证：${unknown.map(c=>esc(checkNames[c.kind] || c.kind)+' / '+esc(c.target)).join('；') || '请继续核实业务效果'}。</p><p>未配齐或未就绪的节点会在实际需要执行时报告；检查没有执行命令或修复环境。</p></div><details><summary>展开全部检查项</summary>${checkHTML(report)}</details>`;
}
$('create-dialog').addEventListener('close',()=>{launchEpoch++;pendingLaunch=null;});
async function startReviewedLaunch(){
  if(launchBusy || !pendingLaunch)return;
  if(!$('launch-ack').checked){toast('请先确认执行方式和未验证项。');return;}
  const epoch=launchEpoch;launchBusy=true;$('launch-start').disabled=true;
  try{
    await savePreparation();
    const payload=structuredClone(pendingLaunch),item=catalog.find(c=>c.key===payload.key),report=await preflight(item);
    if(epoch!==launchEpoch || !$('create-dialog').open)return;
    if(preventsStart(report)){pendingLaunch=null;$('create-dialog').close();await openLoop(item.key,'prepare');throw new Error('环境检查结果已变化，未启动。');}
    if(conversation.agent?.command?.length){await sendWebMessage('按页面中已确认的配置启动本次运行，完成初始化并安排工作。',true);return;}
    const created=await api(`conversations/${conversation.id}/start`,{revision:conversation.revision});pendingLaunch=null;preparationDirty=false;await selectRun(created.run_id);
  }finally{launchBusy=false;$('launch-start').disabled=!!conversation?.busy;}
}
async function editLoopNode(id){
  const item=currentLoop();if(!item)return;
  if(await newLoopDefinition(item,true)===false)return;
  selectEditor({node:id});
}
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button');if(!button)return;const d=button.dataset;
  if(d.loop){await openLoop(d.loop);return;}
  if(d.loopTab){await openLoop(loopKey,d.loopTab);return;}
  if(d.setupNode){await editLoopNode(d.setupNode);return;}
  switch(button.id){
    case 'download-loop-package':await downloadLoopPackage();break;
    case 'library-back':await navigateTo({type:'catalog'});break;
    case 'loop-check':{const item=currentLoop();button.disabled=true;try{const report=await preflight(item);if(page==='loop' && loopKey===item.key && loopTab==='prepare')$('loop-check-result').innerHTML=checkHTML(report);}finally{button.disabled=false;}break;}
    case 'launch-mode':{const item=catalog.find(c=>c.key===$('create-loop_definition').value);collectLaunchInputs();if(launchMode==='form')launchMode='json';else{renderLaunchFields(item);launchMode='form';}$('launch-fields').hidden=launchMode!=='form';$('launch-json').hidden=launchMode!=='json';button.textContent=launchMode==='form'?'切换到高级 JSON':'切换到参数表单';break;}
    case 'launch-back':launchEpoch++;pendingLaunch=null;$('launch-edit').hidden=false;$('launch-confirm').hidden=true;$('create-dialog').scrollTop=0;break;
    case 'launch-start':await startReviewedLaunch();break;
  }
}));

function globalAgentOptions(bp,selected){return '<option value="">默认使用兜底 Agent</option>'+Object.entries(bp.nodes).map(([id,n])=>`<option value="${esc(id)}" ${id===selected?'selected':''}>${esc(n.label||id)}</option>`).join('');}
