'use strict';
// Shared native value fields for inputs, parameters and authoring. No business keys.
function valueType(v){return v===null?'null':Array.isArray(v)?'array':typeof v==='object'?'object':typeof v;}
function emptyValue(schema={}){return schema.default ?? ({string:'',number:0,integer:0,boolean:false,object:{},array:[],null:null}[schema.type] ?? '');}
function valueField(value,schema={},name='值'){
  const type=schema.type || valueType(value===undefined?'':value),v=value===undefined?emptyValue(schema):value;
  const attrs=`data-value-type="${esc(type)}" data-value-schema="${esc(pretty(schema))}"`;
  if(schema.enum)return `<select ${attrs} data-enum aria-label="${esc(name)}">${schema.enum.map(x=>`<option value="${esc(JSON.stringify(x))}" ${pretty(x)===pretty(v)?'selected':''}>${esc(String(x))}</option>`).join('')}</select>`;
  if(type==='object'||type==='array'){
    const obj=type==='object',props=schema.properties || {},keys=obj?[...new Set([...Object.keys(props),...Object.keys(v || {})])]:Object.keys(v || []);
    return `<fieldset class="value-composite" ${attrs}><legend>${esc(name)}</legend><div data-value-children>${keys.map(k=>valueRow(k,v?.[k],obj?props[k] || {}:schema.items || {},obj,!!props[k],schema.required?.includes(k),Object.hasOwn(v || {},k))).join('')}</div>${!obj||schema.additionalProperties!==false?`<button type="button" data-value-add>＋ ${obj?'字段':'项目'}</button>`:''}</fieldset>`;
  }
  if(type==='boolean')return `<select ${attrs} aria-label="${esc(name)}"><option value="true" ${v===true?'selected':''}>是</option><option value="false" ${v!==true?'selected':''}>否</option></select>`;
  if(type==='null')return `<span ${attrs}>空值</span>`;
  if(type==='number'||type==='integer')return `<input ${attrs} type="number" step="${type==='integer'?1:'any'}" value="${esc(v)}" aria-label="${esc(name)}" ${schema.minimum!==undefined?`min="${esc(schema.minimum)}"`:''} ${schema.maximum!==undefined?`max="${esc(schema.maximum)}"`:''}>`;
  return `<textarea ${attrs} rows="2" aria-label="${esc(name)}">${esc(v)}</textarea>`;
}
function valueRow(key,v,schema,obj,fixed=false,required=false,present=true){
  return `<div class="value-row"><div class="value-row-head">${obj?`<input data-value-key aria-label="字段名称" value="${esc(key)}" ${fixed?'readonly':''}>`:''}${fixed?`<label class="inline-check"><input type="checkbox" data-value-include ${present||required?'checked':''} ${required?'disabled':''}>${required?'必填':'使用'}</label>`:`<select data-value-kind aria-label="值类型">${['string','number','integer','boolean','object','array','null'].map(t=>`<option ${t===(schema.type || valueType(v===undefined?'':v))?'selected':''}>${t}</option>`).join('')}</select>${!obj?'<button type="button" data-value-up aria-label="上移项目">↑</button><button type="button" data-value-down aria-label="下移项目">↓</button>':''}<button type="button" data-value-remove aria-label="删除字段或项目">×</button>`}</div><div data-value-content>${valueField(v,schema,schema.title || key || '项目')}</div>${schema.description?`<p class="small muted">${esc(schema.description)}</p>`:''}</div>`;
}
function readValue(el){
  if(!el)throw new Error('表单尚未准备好');
  if(el.hasAttribute('data-enum'))return JSON.parse(el.value);
  const type=el.dataset.valueType;
  if(type==='object'||type==='array'){
    const entries=[...el.querySelector(':scope > [data-value-children]').children].filter(row=>!row.querySelector(':scope > .value-row-head > label > [data-value-include]')||row.querySelector(':scope > .value-row-head > label > [data-value-include]').checked).map(row=>[row.querySelector(':scope > .value-row-head > [data-value-key]')?.value,readValue(row.querySelector(':scope > [data-value-content] > [data-value-type]'))]);
    if(type==='array')return entries.map(x=>x[1]);
    if(entries.some(([k])=>!k)||new Set(entries.map(x=>x[0])).size!==entries.length)throw new Error('字段名称不能为空或重复');
    return Object.fromEntries(entries);
  }
  if(type==='null')return null;
  if(type==='boolean')return el.value==='true';
  if(type==='number'||type==='integer'){if(!el.value.trim()||!el.checkValidity())throw new Error('请填写有效数字');return Number(el.value);}
  return el.value;
}
document.addEventListener('click',e=>{
  const b=e.target.closest('[data-value-add],[data-value-remove],[data-value-up],[data-value-down]');if(!b)return;
  const group=b.closest('[data-value-type]');
  if(b.hasAttribute('data-value-up')||b.hasAttribute('data-value-down')){const row=b.closest('.value-row'),peer=b.hasAttribute('data-value-up')?row.previousElementSibling:row.nextElementSibling;if(peer)b.hasAttribute('data-value-up')?peer.before(row):peer.after(row);}
  else if(b.hasAttribute('data-value-remove'))b.closest('.value-row').remove();
  else{const schema=JSON.parse(group.dataset.valueSchema),obj=group.dataset.valueType==='object';group.querySelector(':scope > [data-value-children]').insertAdjacentHTML('beforeend',valueRow('',undefined,obj?{}:schema.items || {},obj));}
  group.dispatchEvent(new Event('input',{bubbles:true}));
});
document.addEventListener('change',e=>{if(!e.target.matches('[data-value-kind]'))return;const row=e.target.closest('.value-row'),schema={type:e.target.value};row.querySelector(':scope > [data-value-content]').innerHTML=valueField(emptyValue(schema),schema);});
function valueAt(id){return readValue($(id).querySelector('[data-value-type]'));}
function resultView(value){
  if(value===null||value===undefined)return '<span class="muted">暂无结果</span>';
  if(Array.isArray(value)){
    if(value.length && value.every(v=>v && typeof v==='object'&&!Array.isArray(v))){const keys=[...new Set(value.flatMap(Object.keys))];return `<div class="result-table"><table><thead><tr>${keys.map(k=>`<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${value.map(v=>`<tr>${keys.map(k=>`<td>${resultView(v[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
    return `<ol>${value.map(v=>`<li>${resultView(v)}</li>`).join('')}</ol>`;
  }
  if(typeof value==='object')return `<dl class="result-fields">${Object.entries(value).map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${resultView(v)}</dd></div>`).join('')}</dl>`;
  return `<span class="result-text">${esc(typeof value==='boolean'?(value?'是':'否'):value)}</span>`;
}
function sourceField(name,source,schema,choices=[],plan=false){
  const modes=[...(plan?['unset']:[]),'literal','record','records','run','settings',...(plan?['from','value','template']:[])],mode=plan&&source?.literal&&typeof source.literal==='object'&&Object.hasOwn(source.literal,'$')?'value':plan&&JSON.stringify(source||{}).includes('"$"')?'template':modes.find(k=>Object.hasOwn(source || {},k)) || (plan?'unset':'literal');
  const names={unset:'待指定来源',literal:'直接填写',record:'单个结果',records:'多个结果',run:'初始输入字段',settings:'运行设置字段',from:'本批次上游输出',value:'本批参数或当前列表项',template:'参数化来源（高级）'};
  return `<fieldset class="source-field" data-source-name="${esc(name)}" data-source-schema="${esc(pretty(schema))}" data-source-original="${esc(pretty(source || {}))}" data-source-choices="${esc(pretty(choices))}"><legend>${esc(schema.title || name)}</legend><select data-source-mode aria-label="${esc(name)} 来源">${modes.map(m=>`<option value="${m}" ${m===mode?'selected':''}>${names[m]}</option>`).join('')}</select><div data-source-body>${sourceBody(mode,source || {},schema,choices)}</div></fieldset>`;
}
function sourceBody(mode,s,schema,choices){
  if(mode==='unset')return '<p class="input-gap">尚未指定输入来源；可先保存草稿。</p>';
  if(mode==='template')return valueField(s,{type:'object'},'参数化来源');
  if(mode==='value')return `<label>引用路径<input data-source-path value="${esc(s.literal?.$ || 'item')}" placeholder="item 或 values.字段"></label>`;
  if(mode==='literal')return valueField(Object.hasOwn(s,'literal')?s.literal:undefined,schema,'内容');
  if(mode==='record'||mode==='records'){
    const available=[...choices.filter(c=>c.id),...(s.records || (s.record?[s.record]:[])).filter(id=>!choices.some(c=>c.id===id)).map(id=>({id}))];
    const field=mode==='records'?valueField(s.records || [],{type:'array',items:{type:'string',enum:available.map(c=>c.id)}},'结果来源（按此顺序传入）'):`<select data-source-record aria-label="结果来源"><option value="">请选择结果</option>${available.map(c=>`<option value="${esc(c.id)}" ${s.record===c.id?'selected':''}>${esc(c.label || c.id)}</option>`).join('')}</select>`;
    return field+`<label>结果内字段路径（可选）<input data-source-path value="${esc(s.path || '')}"></label><label>固定版本（留空使用最新）<input data-source-revision type="number" min="1" value="${esc(s.revision || '')}"></label>`;
  }
  if(mode==='from')return `<select data-source-from aria-label="上游输出"><option value="">请选择输出</option>${choices.filter(c=>c.step).map(c=>`<option value="${esc(JSON.stringify([c.step,c.port]))}" ${c.step===s.from&&c.port===s.port?'selected':''}>${esc(c.label)}</option>`).join('')}</select><label class="inline-check"><input type="checkbox" data-source-collect ${s.collect?'checked':''}>汇总该步骤全部结果</label>`;
  return `<input data-source-path value="${esc(s[mode] || '')}" aria-label="字段路径">`;
}
function readSources(root){return Object.fromEntries([...root.querySelectorAll('.source-field')].map(el=>{
  const mode=el.querySelector('[data-source-mode]').value,body=el.querySelector('[data-source-body]');let source;
  if(mode==='unset')return null;
  if(mode==='literal')source={literal:readValue(body.querySelector('[data-value-type]'))};
  else if(mode==='record'||mode==='records'){
    const values=mode==='records'?readValue(body.querySelector('[data-value-type]')):[body.querySelector('[data-source-record]').value];if(values.some(v=>typeof v!=='string'||!v))throw new Error('请选择 '+el.dataset.sourceName+' 的结果来源');
    source=mode==='record'?{record:values[0]}:{records:values};
    const path=body.querySelector('[data-source-path]').value,revision=body.querySelector('[data-source-revision]').value;if(path)source.path=path;if(revision){if(!Number.isInteger(Number(revision))||Number(revision)<1)throw new Error('版本必须是正整数');source.revision=Number(revision);}
  }else if(mode==='from'){const raw=body.querySelector('[data-source-from]').value;if(!raw)throw new Error('请选择上游输出');const [from,port]=JSON.parse(raw);source={from,port};if(body.querySelector('[data-source-collect]').checked)source.collect=true;}
  else if(mode==='template')source=readValue(body.querySelector('[data-value-type]'));
  else if(mode==='value')source={literal:{$:body.querySelector('[data-source-path]').value}};
  else source={[mode]:body.querySelector('[data-source-path]').value};
  return [el.dataset.sourceName,source];
}).filter(Boolean));}
document.addEventListener('change',e=>{if(!e.target.matches('[data-source-mode]'))return;const el=e.target.closest('.source-field');el.querySelector('[data-source-body]').innerHTML=sourceBody(e.target.value,JSON.parse(el.dataset.sourceOriginal),JSON.parse(el.dataset.sourceSchema),JSON.parse(el.dataset.sourceChoices));});

document.addEventListener('input',e=>{const row=e.target.closest('[data-value-content]')?.parentElement;if(row){const include=row.querySelector(':scope > .value-row-head > label > [data-value-include]');if(include)include.checked=true;}});
