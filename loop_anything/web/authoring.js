'use strict';
let authorPlan='default',portConnection=null;
function schemaForm(schema={type:'string'}){
  return `<div class="schema-form" data-schema-original="${esc(pretty(schema))}"><label>类型<select data-schema-type>${['string','number','integer','boolean','object','array'].map(t=>`<option ${schema.type===t?'selected':''}>${t}</option>`).join('')}</select></label><label>显示名称<input data-schema-title value="${esc(schema.title || '')}"></label><label>说明<input data-schema-description value="${esc(schema.description || '')}"></label><div data-schema-children>${schemaChildren(schema)}</div><details><summary>高级约束</summary><div data-schema-extra>${valueField(Object.fromEntries(Object.entries(schema).filter(([k])=>!['type','title','description','properties','items','required'].includes(k))),{type:'object'},'约束字段')}</div></details></div>`;
}
function schemaChildren(s){if(s.type==='object')return `<div data-schema-props>${Object.entries(s.properties || {}).map(([k,v])=>schemaProperty(k,v,s.required?.includes(k))).join('')}</div><button type="button" data-schema-add>＋ 子字段</button>`;if(s.type==='array')return `<details open><summary>每项内容</summary>${schemaForm(s.items || {type:'string'})}</details>`;return '';}
function schemaProperty(name,s,required){return `<details class="schema-property author-item" open><summary>${esc(name || '新字段')}</summary><label>字段名称<input data-schema-name value="${esc(name)}"></label><label class="inline-check"><input type="checkbox" data-schema-required ${required?'checked':''}>必填</label>${schemaForm(s)}<button type="button" data-schema-remove>删除字段</button></details>`;}
function readSchema(root){
  const s={...readValue(root.querySelector(':scope > details > [data-schema-extra] > [data-value-type]')),type:root.querySelector(':scope > label > [data-schema-type]').value};
  const title=root.querySelector(':scope > label > [data-schema-title]').value,description=root.querySelector(':scope > label > [data-schema-description]').value;if(title)s.title=title;if(description)s.description=description;
  if(s.type==='object'){s.properties={};s.required=[];for(const row of root.querySelector(':scope > [data-schema-children] > [data-schema-props]').children){const k=row.querySelector(':scope > label > [data-schema-name]').value.trim();if(!k||Object.hasOwn(s.properties,k))throw new Error('子字段名称不能为空或重复');s.properties[k]=readSchema(row.querySelector(':scope > .schema-form'));if(row.querySelector(':scope > label > [data-schema-required]').checked)s.required.push(k);}}
  if(s.type==='array')s.items=readSchema(root.querySelector(':scope > [data-schema-children] > details > .schema-form'));
  return s;
}
function authorPort(name,schema){return `<details class="author-port author-item"><summary>${esc(name||'新端口')} · ${esc(schema.type)}</summary><label>端口名称<input data-port-name value="${esc(name)}"></label>${schemaForm(schema)}<label>结果呈现<select data-port-format><option value="">按数据结构展示</option><option value="file" ${schema.format==='file'?'selected':''}>文件路径（string）</option></select></label><button type="button" data-remove-author-item>删除端口</button></details>`;}
function skillItem(s={}){return `<div class="author-skill author-item" data-original="${esc(pretty(s))}"><label>Skill 名称<input data-skill-name value="${esc(s.name||'')}"></label><label>包内入口路径（可选）<input data-skill-path value="${esc(s.path||'')}" placeholder="skills/method/SKILL.md"></label><label>方法说明<textarea data-skill-content rows="3">${esc(s.content||'')}</textarea></label><button type="button" data-remove-author-item>删除 Skill</button></div>`;}
function candidateParts(c){return [editor.loop_definition.nodes[editSelection.node]?.skills?.length?'共用节点 Skill':null,c.command?.length?'执行入口':null,c.kind==='agent'?'唤醒 prompt':null,c.kind==='external'?'附属监控':null,'内部状态机'].filter(Boolean);}
function waitDisplay(v){return v&&typeof v==='object'&&v.$?'{'+v.$+'}':v;}
function waitEditor(c){const w=c.wait||{},kind=c.kind;return `<section data-candidate-wait ${['timer','event'].includes(kind)?'':'hidden'}><h3>等待条件</h3><p class="small muted">平台直接等待，不启动命令。支持 {parameters.name} 引用本次任务参数。</p><div data-wait-timer ${kind==='timer'?'':'hidden'}><label>计时方式<select data-wait-mode><option value="seconds" ${w.until===undefined?'selected':''}>等待一段时间</option><option value="until" ${w.until!==undefined?'selected':''}>等待指定时刻</option></select></label><label data-wait-seconds-label ${w.until!==undefined?'hidden':''}>等待秒数<input data-wait-seconds value="${esc(waitDisplay(w.seconds??60))}"></label><label data-wait-until-label ${w.until===undefined?'hidden':''}>到达时刻（含时区）<input data-wait-until value="${esc(waitDisplay(w.until||''))}" placeholder="2026-10-01T09:00:00+08:00"></label><details><summary>计时完成时的输出（有输出端口时填写）</summary><textarea data-wait-outputs rows="3">${esc(pretty(w.outputs||{}))}</textarea></details></div><div data-wait-event ${kind==='event'?'':'hidden'}><label>事件关联标识<input data-wait-key value="${esc(waitDisplay(w.key||''))}" placeholder="留空沿用 Task parameters.event_key"></label><label>最多等待秒数（可选）<input data-wait-timeout value="${esc(waitDisplay(w.timeout??''))}" placeholder="超时产生 timeout 事件"></label></div></section>`;}
function readWait(row,kind){if(!['timer','event'].includes(kind))return null;const value=selector=>row.querySelector(selector).value.trim(),number=s=>s!==''&&Number.isFinite(Number(s))?Number(s):s,result={};if(kind==='timer'){const mode=value('[data-wait-mode]');result[mode]=mode==='seconds'?number(value('[data-wait-seconds]')):value('[data-wait-until]');const outputs=JSON.parse(value('[data-wait-outputs]')||'{}');if(Object.keys(outputs).length)result.outputs=outputs;}else{if(value('[data-wait-key]'))result.key=value('[data-wait-key]');if(value('[data-wait-timeout]'))result.timeout=number(value('[data-wait-timeout]'));}return result;}
function candidateItem(id='',c={kind:'agent'}){
  const chosen=defaultImplementation(editor.implementations[editSelection.node])===id;
  return `<details class="author-candidate author-item ${id?'existing-candidate':''}" data-last-id="${esc(id)}" data-original="${esc(pretty(c))}" open>
    <summary><span class="candidate-card-title">${esc(c.label||id||'新实现方案')}<small>${esc(id)} · ${esc(kindNames[c.kind]||c.kind)}</small></span><span class="candidate-default-badge" ${chosen?'':'hidden'}>默认方案</span></summary>
    <div class="candidate-card-overview"><p>${esc(c.description||'尚未填写用途说明')}</p><div class="candidate-parts">${candidateParts(c).map(v=>`<span>${v}</span>`).join('')}</div>${id?`<div class="candidate-card-actions"><button type="button" class="open-candidate-page" data-editor-node="${esc(editSelection.node)}" data-editor-implementation="${esc(id)}">打开方案 ↗</button><button type="button" data-candidate-default ${chosen?'disabled':''}>${chosen?'已设为默认':'设为默认'}</button></div>`:''}</div>
    <nav class="scheme-page-nav" aria-label="方案内容">${[['candidate-settings','怎么执行'],['candidate-machine','平台处理与通知'],['candidate-resources','Skill 与脚本']].map(([section,title])=>`<button type="button" data-scheme-section="${section}">${title}</button>`).join('')}</nav>
    <div class="candidate-body"><div class="candidate-settings"><h3>执行入口</h3><p class="small muted">这套方案独立配置入口和监控，共用节点的输入输出与业务 Skill。</p>
    <div class="candidate-identity"><label>方案名称<input data-candidate-label value="${esc(c.label||'')}"></label><label>实现 ID<input data-candidate-id value="${esc(id)}"></label></div>
    <label>用途说明<textarea data-candidate-description rows="2" placeholder="例如：本机调试，或提交到远端训练集群">${esc(c.description||'')}</textarea></label>
    <div class="candidate-identity"><label>执行方式<select data-candidate-kind>${['agent','command','external','event','timer','approval'].map(k=>`<option value="${k}" ${c.kind===k?'selected':''}>${esc({agent:'Agent 执行',command:'同步脚本',external:'异步提交＋附属监控',event:'等待外部事件 / 回复',timer:'等待时间',approval:'等待审批'}[k])}</option>`).join('')}</select></label><label>工作目录（可选）<input data-candidate-cwd value="${esc(c.cwd||'')}"></label></div>
    <label>执行 / 提交命令（每行一个参数）<textarea class="code" data-candidate-command rows="4">${esc((c.command||[]).join('\n'))}</textarea></label>
    <section data-candidate-monitor ${c.kind==='external'?'':'hidden'}><h4>附属监控</h4><p class="small muted">接收外部任务标识，查询并报告状态。检查记录归属于当前任务。</p><label>检查命令（每行一个参数）<textarea class="code" data-candidate-observe rows="4">${esc((c.observe||[]).join('\n'))}</textarea></label></section>
    <div data-candidate-prompt ${c.kind==='agent'?'':'hidden'}>${promptEditor('task',c)}</div>
    ${waitEditor(c)}<label data-candidate-event-label ${c.kind==='event'?'':'hidden'}>事件名称<input data-candidate-event value="${esc(c.event||'')}"></label>
    <details class="candidate-parameters"><summary>此实现的任务参数</summary><label class="inline-check"><input type="checkbox" data-candidate-parameters-enabled ${c.parameter_schema?'checked':''}>声明参数要求</label><p class="small muted">安排任务时检查；同时满足节点的参数要求，不自动填值。</p><div data-candidate-parameters ${c.parameter_schema?'':'hidden'}>${schemaForm(c.parameter_schema||{type:'object'})}</div></details>
    <label>单次调用超时秒数（Agent 留空不限时）<input data-candidate-timeout type="number" min="1" value="${esc(c.timeout||'')}"></label></div>
    <div class="candidate-machine">${lifecycleEditor(c)}</div><section class="candidate-resources">${candidateResources(c)}</section><button type="button" data-remove-author-item>删除实现</button></div></details>`;
}
function candidateResources(c){
  const node=editor.loop_definition.nodes[editSelection.node],assets=editor.assets||[],paths=new Set(assets.map(a=>a.path));
  const link=path=>paths.has(path)?`<button type="button" data-open-scheme-asset="${esc(path)}">${esc(path)} ↗</button>`:`<code>${esc(path)}</code><small>未包含在 Loop 包中</small>`;
  const refs=[...new Set([...(c.command||[]),...(c.observe||[])].map(arg=>arg.replace(/^\.\//,'')).filter(arg=>paths.has(arg)))];
  return `<h3>Skill 与脚本文件</h3><p class="small muted">节点 Skill 是各方案共用的业务说明；脚本可能由命令直接执行，也可能由 Agent 按说明调用。</p><h4>共用节点 Skill</h4>${(node.skills||[]).map(skill=>`<details class="scheme-skill" open><summary>${esc(skill.name)}</summary>${skill.content?`<pre>${esc(skill.content)}</pre>`:''}${skill.path?link(skill.path):''}</details>`).join('')||'<p class="small muted">尚未配置节点 Skill。</p>'}<button type="button" data-editor-node="${esc(editSelection.node)}">编辑共用节点 Skill ↗</button><h4>命令直接引用的包文件</h4><div class="scheme-files">${refs.map(link).join('')||'<p class="small muted">暂无包内文件引用。外部命令与路径见上方执行入口。</p>'}</div><details class="scheme-all-files"><summary>浏览 Loop 包文件 · ${assets.length}</summary><p class="small muted">包含 Skill 的 references 和其他脚本；这里列出包文件，不代表本方案会调用所有文件。</p><div class="scheme-files">${assets.map(a=>link(a.path)).join('')||'<p class="small muted">可通过顶部「Loop 包」添加文件或文件夹。</p>'}</div></details>`;
}
function planOutputChoices(plan){const b=editor.loop_definition;return Object.entries(b.seed.outputs||{}).map(([port,d])=>({id:d.id,label:'初始结果 / '+port})).concat(Object.entries(plan.steps||{}).flatMap(([key,s])=>Object.keys(b.nodes[s.node]?.outputs||{}).map(port=>({step:key,port,label:`${key} / ${port}`}))));}
function renderAuthorProperties(){
  const root=$('editor-properties'),b=editor.loop_definition;
  if(editSelection?.node){const id=editSelection.node,n=b.nodes[id],c=editor.implementations[id]||{};$('property-title').textContent='节点 · '+id;
    root.innerHTML=`${nodeFlowHTML(b,id,loopRelationships(b),true)}${authorOutputUsage(b,id)}<form id="author-node-form"><label>显示名称<input id="author-label" value="${esc(n.label||'')}"></label><label>节点职责<textarea id="author-instructions" rows="4">${esc(n.instructions)}</textarea></label><div class="author-section"><h3>后续工作与循环</h3><p class="small muted">声明后续安排；选择自身表示可再安排一次工作。脚本按此范围安排任务；Agent 的范围仍由用户授权和 Task 归属决定。</p><div id="author-plan-nodes">${Object.entries(b.nodes).filter(([target,n])=>!n.initialize_timeline).map(([target,node])=>`<label class="inline-check"><input type="checkbox" data-plan-node="${esc(target)}" ${(n.plan_nodes||[]).includes(target)?'checked':''}>${esc(node.label||target)}${target===id?' · 再次执行':''}</label>`).join('')}</div></div><div class="author-section" data-author-section="inputs"><h3>输入</h3><div id="author-inputs">${Object.entries(n.inputs).map(([k,s])=>authorPort(k,s)).join('')}</div><button type="button" data-add-author-port="inputs">＋ 输入</button></div><div class="author-section" data-author-section="outputs"><h3>输出</h3><div id="author-outputs">${Object.entries(n.outputs).map(([k,s])=>authorPort(k,b.records[s.record_type])).join('')}</div><button type="button" data-add-author-port="outputs">＋ 输出</button></div><details class="author-section"><summary>参数定义</summary><div id="author-parameter-schema">${schemaForm(n.parameter_schema||{type:'object'})}</div></details><div class="author-section"><h3>节点 Skill</h3><div id="author-skills">${(n.skills||[]).map(skillItem).join('')}</div><button type="button" id="add-author-skill">＋ Skill</button><p class="small muted">入口文件和 references 可通过「包资源」一起添加。</p></div><div class="author-section"><h3>实现方案</h3><p class="small muted">同一节点可选择不同方案，例如本地或远端训练。每套方案有自己的入口、脚本和内部状态机，共用本节点的输入输出。</p><label>默认实现<select id="author-default"><option value="">暂不指定</option>${Object.entries(implementationOptions(c)).map(([k,v])=>`<option value="${esc(k)}" ${defaultImplementation(c)===k?'selected':''}>${esc(v.label||k)}</option>`).join('')}</select></label><div id="author-candidates">${Object.entries(implementationOptions(c)).map(([k,v])=>candidateItem(k,v)).join('')}</div><button type="button" id="add-author-candidate">＋ 实现方案</button></div><p class="small muted">修改自动保存到草稿。</p>${id!==b.entry?'<button type="button" id="remove-author-node">删除节点</button>':''}</form>`;
  }else if(editSelection?.edge){authorPlan=editSelection.edge;const plan=b.plans[authorPlan];$('property-title').textContent='构建模板 · '+authorPlan;
    root.innerHTML=`<form id="author-plan-form"><p class="small muted">这些步骤由你或 Agent 按需安排到某次运行。</p><details><summary>本批参数定义</summary><div id="author-plan-schema">${schemaForm(plan.parameters||{type:'object'})}</div></details><div id="author-steps">${Object.entries(plan.steps).map(([key,s])=>stepItem(key,s,plan)).join('')}</div><label>添加步骤，选用节点<select id="author-step-node">${Object.entries(b.nodes).filter(([,n])=>!n.initialize_timeline).map(([id,n])=>`<option value="${esc(id)}">${esc(n.label||id)}</option>`).join('')}</select></label><button type="button" id="add-author-step">＋ 步骤</button><p class="small muted">修改自动保存到草稿。</p></form>`;
  }else{$('property-title').textContent='选择节点或构建模板';root.innerHTML='<p>点击节点配置职责、输入输出、Skill 和实现。选择输出端口，再选择输入端口建立数据连接。</p>';}
}
function stepConditionFields(step){
  const simple=step.when&&Object.keys(step.when).length===1&&typeof step.when.path==='string',mode=step.when?(simple?'flag':'expression'):'always';
  return `<section class="step-condition" data-condition-mode="${mode}"><label>何时安排<select data-step-condition>${[['always','每次安排'],['flag','仅当本批字段为 true'],['expression','按自定义条件']].map(([v,label])=>`<option value="${v}" ${mode===v?'selected':''}>${label}</option>`).join('')}</select></label><label data-step-flag-field ${mode==='flag'?'':'hidden'}>布尔字段路径<input data-step-when-path value="${esc(simple?step.when.path:'')}" placeholder="values.action.stages.prediction.enabled"></label><label data-step-expression-field ${mode==='expression'?'':'hidden'}>确定性条件<textarea data-step-when rows="3">${esc(step.when?pretty(step.when):'')}</textarea></label><p class="small muted">条件在安排本批任务时判断；不满足就不创建任务。字段缺失或结果不是布尔值会报错。条件适用于整个步骤，然后才按列表展开。</p></section>`;
}
function stepItem(key,s,plan){const b=editor.loop_definition,n=b.nodes[s.node];return `<details class="author-step author-item" data-step-key="${esc(key)}" data-original="${esc(pretty(s))}"><summary>${esc(key)} · ${esc(n.label||s.node)}</summary><p>${esc(s.node)}</p>${stepConditionFields(s)}<label>按列表展开（本批参数路径，可留空）<input data-step-each value="${esc(s.each||'')}" placeholder="items"></label><div data-step-sources>${Object.entries(n.inputs).map(([port,schema])=>sourceField(port,s.inputs?.[port]||{},schema,planOutputChoices(plan).filter(c=>c.step!==key),true)).join('')}</div><details><summary>任务参数（支持已有 $ 引用）</summary><div data-step-parameters>${valueField(s.parameters||{},{type:'object'},'参数')}</div></details><label>前置步骤<select data-step-after multiple size="3">${Object.keys(plan.steps).filter(k=>k!==key).map(k=>`<option value="${esc(k)}" ${s.after?.includes(k)?'selected':''}>${esc(k)}</option>`).join('')}</select></label><label>指定实现（可留空）<select data-step-implementation><option value="">沿用默认</option>${Object.keys(implementationOptions(editor.implementations[s.node])).map(k=>`<option value="${esc(k)}" ${s.implementation===k?'selected':''}>${esc(k)}</option>`).join('')}</select></label><button type="button" data-remove-step="${esc(key)}">删除步骤</button></details>`;}
function collectAuthorProperties(){
  if(!editor||!editSelection)return;const b=editor.loop_definition;
  if(editSelection.node&&$('author-node-form')){
    const id=editSelection.node,n=b.nodes[id];n.plan_nodes=[...$('author-plan-nodes').querySelectorAll('input:checked')].map(e=>e.dataset.planNode);n.label=$('author-label').value;n.instructions=$('author-instructions').value;
    for(const direction of ['inputs','outputs']){const ports={};for(const row of $('author-'+direction).children){const key=row.querySelector('[data-port-name]').value.trim();if(!key||Object.hasOwn(ports,key))throw new Error('端口名称不能为空或重复');const schema=readSchema(row.querySelector(':scope > .schema-form'));const format=row.querySelector('[data-port-format]').value;if(format){if(schema.type!=='string')throw new Error('文件输出需要 string 类型');schema.format=format;}else if(schema.format==='file')delete schema.format;if(direction==='inputs')ports[key]=schema;else{const type=n.outputs[key]?.record_type||id+'.'+key;b.records[type]=schema;ports[key]={...(n.outputs[key]||{}),record_type:type};}}n[direction]=ports;}
    if(id===b.entry){b.seed.inputs=Object.fromEntries(Object.keys(n.inputs).map(k=>[k,b.seed.inputs[k]||{run:k}]));b.seed.outputs=Object.fromEntries(Object.keys(n.outputs).map(k=>[k,b.seed.outputs[k]||{id:'initial.'+k}]));}
    const parameters=readSchema($('author-parameter-schema').querySelector('.schema-form'));if(Object.keys(parameters.properties||{}).length||n.parameter_schema)n.parameter_schema=parameters;
    n.skills=[...$('author-skills').children].map(row=>{const s=JSON.parse(row.dataset.original),name=row.querySelector('[data-skill-name]').value.trim(),path=row.querySelector('[data-skill-path]').value.trim(),content=row.querySelector('[data-skill-content]').value;if(!name)throw new Error('Skill 需要名称');s.name=name;if(path)s.path=path;else delete s.path;if(content)s.content=content;else delete s.content;return s;});
    const options={};for(const row of $('author-candidates').children){const key=row.querySelector('[data-candidate-id]').value.trim();if(!key||Object.hasOwn(options,key))throw new Error('实现 ID 不能为空或重复');const c=JSON.parse(row.dataset.original);c.kind=row.querySelector('[data-candidate-kind]').value;for(const k of ['label','description','cwd','command','observe','event','timeout']){const raw=row.querySelector('[data-candidate-'+k+']').value;if(raw)c[k]=k==='timeout'?Number(raw):['command','observe'].includes(k)?raw.split('\n'):raw;else delete c[k];}const wait=readWait(row,c.kind);if(wait)c.wait=wait;else delete c.wait;c.lifecycle=readLifecycle(row);if(row.querySelector('[data-candidate-parameters-enabled]').checked)c.parameter_schema=readSchema(row.querySelector('[data-candidate-parameters] > .schema-form'));else delete c.parameter_schema;delete c.prompt;if(c.kind==='agent')Object.assign(c,readPrompt(row,'task'));options[key]=c;}editor.implementations[id]={options,default:$('author-default').value.trim()||null};
  }else if(editSelection.edge&&$('author-plan-form')){
    const plan=b.plans[editSelection.edge];plan.parameters=readSchema($('author-plan-schema').querySelector('.schema-form'));
    for(const row of $('author-steps').children){const s=plan.steps[row.dataset.stepKey];s.inputs=readSources(row.querySelector('[data-step-sources]'));s.parameters=readValue(row.querySelector('[data-step-parameters] > [data-value-type]'));s.after=[...row.querySelector('[data-step-after]').selectedOptions].map(o=>o.value);const mode=row.querySelector('[data-step-condition]').value;if(mode==='always')delete s.when;else s.when=mode==='flag'?{path:row.querySelector('[data-step-when-path]').value.trim()}:JSON.parse(row.querySelector('[data-step-when]').value);const each=row.querySelector('[data-step-each]').value.trim(),impl=row.querySelector('[data-step-implementation]').value;if(each)s.each=each;else delete s.each;if(impl)s.implementation=impl;else delete s.implementation;}
  }
}
function authorPortButtons(id,n){
  const steps=Object.entries(editor.loop_definition.plans[authorPlan]?.steps||{}).filter(([,s])=>s.node===id),rows=nodeInputRows(editor.loop_definition,id);
  const inputs=Object.entries(n.inputs).map(([p,s])=>`<button type="button" data-port-node="${esc(id)}" data-input-port="${esc(p)}" class="${rows.some(r=>r.port===p&&r.missing)?'input-gap':''}" title="${esc(rows.filter(r=>r.port===p).map(r=>(r.plan||'入口')+' / '+r.text).join('；')||'创建任务时指定来源')}"><span>◉ ${esc(p)}</span><small>${esc(s.type)}</small></button>`).join('');
  const outputs=Object.entries(n.outputs).map(([p,s])=>`<button type="button" data-port-node="${esc(id)}" data-output-port="${esc(p)}" class="${portConnection?.node===id&&portConnection?.port===p?'chosen':''}"><span>${esc(p)} ◉</span><small>${esc(editor.loop_definition.records[s.record_type]?.type||'未定义类型')}</small></button>`).join('');
  return `<div class="editor-port-buttons"><div><strong>输入</strong>${inputs||'<small>无需输入</small>'}</div><div><strong>输出</strong>${outputs||'<small>无输出端口</small>'}</div></div>${steps.length>1?`<select data-node-step="${esc(id)}" aria-label="${esc(id)} 的模板步骤">${steps.map(([k])=>`<option>${esc(k)}</option>`).join('')}</select>`:''}`;
}
function authorOutputUsage(bp,id){
  const edges=loop_definitionEdges(bp);
  return `<section class="node-output-usage"><h4>输出会交给谁</h4>${Object.keys(bp.nodes[id].outputs).map(port=>{const targets=edges.filter(e=>e.from===id&&e.output===port);return `<div class="input-source"><strong>${esc(port)}</strong><span>${targets.map(e=>esc((bp.nodes[e.to].label||e.to)+' / '+e.input+'（'+e.id+'）')).join('<br>')||'尚无固定消费者；运行时可引用'}</span></div>`;}).join('')||'<p class="small muted">此节点没有输出端口。</p>'}</section>`;
}
async function ensureAuthorStep(node,key){const b=editor.loop_definition;if(b.nodes[node].initialize_timeline)return null;if(!b.plans[authorPlan]?.steps[key])await editWithTool('put_step',{plan:authorPlan,step:key,node_id:node,inputs:{}});return key;}
const connectionDialog=document.createElement('dialog');connectionDialog.id='connection-dialog';document.body.append(connectionDialog);
document.addEventListener('click',event=>safely(async()=>{
  const el=event.target.closest('button');if(!el||!editor)return;const d=el.dataset;
  if(d.schemeSection){el.closest('.author-candidate').querySelector('.'+d.schemeSection).scrollIntoView({block:'start'});return;}
  if(d.candidateDefault!==undefined){$('author-default').value=el.closest('.author-candidate').querySelector('[data-candidate-id]').value;dirty();collectAll();renderEditor();renderProperties();return;}
  if(d.schemaAdd!==undefined){el.previousElementSibling.insertAdjacentHTML('beforeend',schemaProperty('',{type:'string'},false));dirty();return;}
  if(d.schemaRemove!==undefined){el.closest('.schema-property').remove();dirty();return;}
  if(d.removeAuthorItem!==undefined){el.closest('.author-item').remove();refreshDefaultCandidates();dirty();return;}
  if(d.addAuthorPort){$('author-'+d.addAuthorPort).insertAdjacentHTML('beforeend',authorPort('',{type:'string'}));dirty();return;}
  if(el.id==='add-author-skill'){$('author-skills').insertAdjacentHTML('beforeend',skillItem());dirty();return;}
  if(el.id==='add-author-candidate'){$('author-candidates').insertAdjacentHTML('beforeend',candidateItem());refreshLifecycle($('author-candidates').lastElementChild);dirty();return;}
  if(el.id==='remove-author-node'){previewAuthorRemoval({node:editSelection.node});return;}
  if(el.id==='add-author-step'){collectAll();const node=$('author-step-node').value,plan=editor.loop_definition.plans[authorPlan];let key=node,i=2;while(plan.steps[key])key=node+'_'+i++;await ensureAuthorStep(node,key);return;}
  if(d.removeStep){previewAuthorRemoval({plan:authorPlan,step:d.removeStep});return;}
  if(el.id==='new-author-plan'){collectAll();const name=$('new-plan-name').value.trim();if(!name||editor.loop_definition.plans[name])throw new Error('请填写未使用的模板名称');editor.loop_definition.plans[name]={parameters:{type:'object'},steps:{}};authorPlan=name;editSelection={edge:name};dirty();renderEditor();renderProperties();return;}
  if(d.outputPort!==undefined){collectAll();const step=editorPage.querySelector(`[data-node-step="${CSS.escape(d.portNode)}"]`)?.value||Object.entries(editor.loop_definition.plans[authorPlan]?.steps||{}).find(([,s])=>s.node===d.portNode)?.[0]||d.portNode;portConnection={node:d.portNode,port:d.outputPort,step};renderEditor();return;}
  if(d.inputPort!==undefined){
    if(!portConnection){const row=nodeInputRows(editor.loop_definition,d.portNode).find(r=>r.port===d.inputPort&&(r.plan===authorPlan||!r.plan));locateEditorIssue(row?.plan?['plans',row.plan,'steps',row.key,'inputs',row.port]:['nodes',d.portNode,'inputs',d.inputPort]);return;}collectAll();const source={...portConnection},node=d.portNode,port=d.inputPort;
    const step=editorPage.querySelector(`[data-node-step="${CSS.escape(node)}"]`)?.value||Object.entries(editor.loop_definition.plans[authorPlan]?.steps||{}).find(([,s])=>s.node===node)?.[0]||node;
    if(node===editor.loop_definition.entry)throw new Error('入口输入来自初始输入');
    await ensureAuthorStep(node,step);
    if(source.node===editor.loop_definition.entry){const record=editor.loop_definition.seed.outputs[source.port].id;const t=editor.loop_definition.plans[authorPlan].steps[step];await editWithTool('put_step',{plan:authorPlan,step,node_id:node,inputs:{...t.inputs,[port]:{record}}});portConnection=null;renderEditor();return;}
    await ensureAuthorStep(source.node,source.step);
    connectionDialog.innerHTML=`<form id="connect-port-form"><h2>连接输入输出</h2><p>原来源：${esc(sourceText(editor.loop_definition.plans[authorPlan].steps[step].inputs[port]))}</p><p>改为：${esc(source.step+' / '+source.port)} → ${esc(step+' / '+port)}</p><p class="small muted">直接关联的后续步骤：${esc(Object.entries(editor.loop_definition.plans[authorPlan].steps).filter(([k,s])=>k!==step&&((s.after||[]).includes(step)||Object.values(s.inputs||{}).some(v=>v.from===step))).map(([k])=>k).join('、')||'无')}。只改草稿，已有执行结果不变。</p><label class="inline-check"><input type="checkbox" id="connect-collect">汇总上游步骤全部结果</label><button type="submit" class="primary">连接</button><button type="button" class="close-dialog">取消</button></form>`;
    connectionDialog.onSubmitData={plan:authorPlan,from_step:source.step,output:source.port,to_step:step,input:port};connectionDialog.showModal();
  }
}));
document.addEventListener('submit',event=>{if(event.target.id!=='connect-port-form')return;event.preventDefault();safely(async()=>{await editWithTool('connect_steps',{...connectionDialog.onSubmitData,collect:$('connect-collect').checked});connectionDialog.close();portConnection=null;renderEditor();});});
document.addEventListener('change',event=>{
  const el=event.target;if(el.matches('[data-candidate-parameters-enabled]'))el.closest('.author-candidate').querySelector('[data-candidate-parameters]').hidden=!el.checked;
  if(el.matches('[data-candidate-kind]')){const row=el.closest('.author-candidate');row.querySelector('[data-candidate-prompt]').hidden=el.value!=='agent';row.querySelector('[data-candidate-monitor]').hidden=el.value!=='external';row.querySelector('[data-candidate-event-label]').hidden=el.value!=='event';row.querySelector('[data-candidate-wait]').hidden=!['event','timer'].includes(el.value);row.querySelector('[data-wait-timer]').hidden=el.value!=='timer';row.querySelector('[data-wait-event]').hidden=el.value!=='event';row.querySelector('[data-lifecycle-editor]').outerHTML=lifecycleEditor({kind:el.value});refreshLifecycle(row);}
  if(el.matches('[data-step-condition]')){const root=el.closest('.step-condition');if(root.dataset.conditionMode==='flag')root.querySelector('[data-step-when]').value=pretty({path:root.querySelector('[data-step-when-path]').value.trim()});if(el.value==='flag'&&root.dataset.conditionMode==='expression'){try{const expression=JSON.parse(root.querySelector('[data-step-when]').value);root.querySelector('[data-step-when-path]').value=expression&&Object.keys(expression).length===1&&typeof expression.path==='string'?expression.path:'';}catch(error){root.querySelector('[data-step-when-path]').value='';}}root.dataset.conditionMode=el.value;root.querySelector('[data-step-flag-field]').hidden=el.value!=='flag';root.querySelector('[data-step-expression-field]').hidden=el.value!=='expression';}
  if(el.matches('[data-wait-mode]')){const root=el.closest('[data-candidate-wait]');root.querySelector('[data-wait-seconds-label]').hidden=el.value!=='seconds';root.querySelector('[data-wait-until-label]').hidden=el.value!=='until';}
  if(el.matches('[data-schema-type]')){const root=el.closest('.schema-form');root.querySelector(':scope > [data-schema-children]').innerHTML=schemaChildren({type:el.value});}
  if(el.matches('[data-plan-node]'))safely(async()=>{collectAll();renderEditor();});
  if(el.id==='author-plan-select')safely(async()=>{collectAll();authorPlan=el.value;editSelection={edge:authorPlan};portConnection=null;renderEditor();renderProperties();});
});

let authorRemoval=null;
function authorRemovalChange(selection){
  const b=structuredClone(editor.loop_definition),removed=new Map(),affected=[];
  for(const [name,plan] of Object.entries(b.plans)){
    const keys=Object.keys(plan.steps).filter(k=>selection.node?plan.steps[k].node===selection.node:name===selection.plan&&k===selection.step);
    if(keys.length)removed.set(name,new Set(keys));
    keys.forEach(k=>affected.push({plan:name,text:`移除模板步骤 ${name} / ${k}`}));
  }
  for(const [name,plan] of Object.entries(b.plans)){
    const keys=removed.get(name)||new Set();
    for(const [key,step] of Object.entries(plan.steps)){
      if(keys.has(key)){delete plan.steps[key];continue;}
      for(const [port,source] of Object.entries(step.inputs||{}))if(keys.has(source.from)){
        affected.push({plan:name,text:`${name} / ${key} 的输入 ${port} 需要重新指定来源`});delete step.inputs[port];
      }
      if((step.after||[]).some(k=>keys.has(k))){affected.push({plan:name,text:`断开 ${name} / ${key} 的先后依赖`});step.after=step.after.filter(k=>!keys.has(k));}
    }
    if(keys.size&&!Object.keys(plan.steps).length)delete b.plans[name];
  }
  if(selection.node){
    if(selection.node===b.entry)throw new Error('入口节点不能删除。');
    for(const field of ['fallback_node','global_agent_node'])if(b[field]===selection.node){b[field]=null;affected.push({text:`清除 ${field==='fallback_node'?'兜底':'全局 Agent'} 指定`});}
    for(const [id,n] of Object.entries(b.nodes))if((n.plan_nodes||[]).includes(selection.node)){n.plan_nodes=n.plan_nodes.filter(x=>x!==selection.node);affected.push({node:id,text:`移除 ${n.label||id} 对此节点的安排声明`});}
    const outputs=b.nodes[selection.node].outputs;delete b.nodes[selection.node];if(b.layout)delete b.layout[selection.node];
    for(const [port,spec] of Object.entries(outputs))if(spec.record_type===selection.node+'.'+port&&!Object.values(b.nodes).some(n=>Object.values(n.outputs||{}).some(s=>s.record_type===spec.record_type))){delete b.records[spec.record_type];affected.push({text:'清理未再引用的记录类型 '+spec.record_type});}
  }
  return {definition:b,affected};
}
function previewAuthorRemoval(selection){
  collectAll();const change=authorRemovalChange(selection);authorRemoval={selection,edits:editor.edits||0};
  $('author-removal')?.remove();
  $('editor-properties').insertAdjacentHTML('beforeend',`<section id="author-removal" class="author-removal"><h3>删除影响</h3><p>只修改草稿；已有 Run 保持原样。</p><ul>${change.affected.map(a=>`<li>${esc(a.text)} ${a.plan?`<button type="button" data-locate-plan="${esc(a.plan)}">定位修正</button>`:a.node?`<button type="button" data-locate-node="${esc(a.node)}">定位节点</button>`:''}</li>`).join('')||'<li>没有其他已声明引用。</li>'}</ul><p>确认后一起删除列出的步骤和连接。缺少来源的输入会保留为待填写，修正后才可保存为可用版本。</p><button type="button" id="confirm-author-removal">删除并断开这些引用</button><button type="button" id="cancel-author-removal">取消</button></section>`);
  $('author-removal').scrollIntoView({block:'nearest'});
}
document.addEventListener('click',event=>safely(async()=>{
  const el=event.target.closest('button');if(!el)return;
  if(el.dataset.locatePlan)selectEditor({edge:el.dataset.locatePlan});
  if(el.dataset.locateNode)selectEditor({node:el.dataset.locateNode});
  if(el.id==='cancel-author-removal'){$('author-removal').remove();authorRemoval=null;}
  if(el.id==='confirm-author-removal'){
    if(!authorRemoval||(editor.edits||0)!==authorRemoval.edits)throw new Error('草稿已变化，请重新查看删除影响。');
    const {selection}=authorRemoval;collectAll();const change=authorRemovalChange(selection);
    editor.loop_definition=change.definition;if(selection.node)delete editor.implementations[selection.node];
    editSelection=null;authorRemoval=null;dirty();populateMeta();renderEditor();renderProperties();await saveEditor();
  }
}));

function refreshDefaultCandidates(changed){
  if(!$('author-default'))return;
  let selected=$('author-default').value;
  if(changed){const row=changed.closest('.author-candidate');if(selected&&selected===row.dataset.lastId)selected=changed.value;row.dataset.lastId=changed.value;}
  const keys=[...$('author-candidates').querySelectorAll('[data-candidate-id]')].map(e=>e.value).filter(Boolean);
  $('author-default').innerHTML='<option value="">暂不指定</option>'+keys.map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join('');
  $('author-default').value=keys.includes(selected)?selected:'';
}
document.addEventListener('input',e=>{if(e.target.matches('[data-candidate-id]'))refreshDefaultCandidates(e.target);});

document.addEventListener('click',event=>{
  const summary=event.target.closest('.author-candidate > summary');if(!summary)return;
  event.preventDefault();const id=summary.parentElement.querySelector('[data-candidate-id]').value.trim();
  if(id&&!activeRoute.implementation)safely(()=>navigateTo({type:'editor',id:editor.routeId,node:editSelection.node,implementation:id}));
});
function refreshCandidateCards(refreshResources=false){
  if(!$('author-candidates'))return;
  for(const row of $('author-candidates').children){
    const id=row.querySelector('[data-candidate-id]').value,c={kind:row.querySelector('[data-candidate-kind]').value,label:row.querySelector('[data-candidate-label]').value,description:row.querySelector('[data-candidate-description]').value,command:row.querySelector('[data-candidate-command]').value.split('\n').filter(Boolean),observe:row.querySelector('[data-candidate-observe]').value.split('\n').filter(Boolean)},chosen=$('author-default').value===id;
    row.querySelector('.candidate-card-title').innerHTML=`${esc(c.label||id||'新实现方案')}<small>${esc(id)} · ${esc(kindNames[c.kind]||c.kind)}</small>`;
    row.querySelector('.candidate-default-badge').hidden=!chosen;
    row.querySelector('.candidate-card-overview > p').textContent=c.description||'尚未填写用途说明';
    row.querySelector('.candidate-parts').innerHTML=candidateParts(c).map(v=>`<span>${v}</span>`).join('');
    const choice=row.querySelector('[data-candidate-default]');if(choice){choice.disabled=chosen;choice.textContent=chosen?'已设为默认':'设为默认';}
    if(refreshResources)row.querySelector('.candidate-resources').innerHTML=candidateResources(c);
  }
}
document.addEventListener('input',event=>{if(event.target.closest('.candidate-settings')||event.target.id==='author-default')refreshCandidateCards(event.target.matches('[data-candidate-command],[data-candidate-observe],[data-candidate-kind]'));});

$('add-node').insertAdjacentHTML('afterend','<button type="button" data-add-wait="timer">＋ 等时间</button><button type="button" data-add-wait="event">＋ 等事件 / 回复</button>');
document.addEventListener('click',event=>safely(async()=>{const el=event.target.closest('[data-add-wait]');if(!el)return;collectAll();let id='wait_1',i=1;while(Object.hasOwn(editor.loop_definition.nodes,id))id='wait_'+ ++i;const kind=el.dataset.addWait;await editWithTool('put_node',{node_id:id,label:kind==='timer'?'等待时间':'等待事件 / 回复',instructions:kind==='timer'?'到达指定时间后继续。':'收到匹配事件后保存回复，供后续任务读取。',inputs:[],outputs:kind==='timer'?[]:[{name:'answer',type:'string'}]});await editWithTool('set_implementation',{node_id:id,kind,...(kind==='timer'?{wait:{seconds:60}}:{event:'reply',wait:{},parameter_schema:{type:'object',properties:{event_key:{type:'string',title:'事件关联标识'}},required:['event_key']}})});await navigateTo({type:'editor',id:editor.routeId,node:id,implementation:'default'});}));
