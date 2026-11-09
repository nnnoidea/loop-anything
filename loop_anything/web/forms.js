'use strict';
// Shared native value fields for inputs, parameters and authoring. No business keys.
function valueType(v){return v===null?'null':Array.isArray(v)?'array':typeof v==='object'?'object':typeof v;}
function emptyValue(schema={}){return schema.default ?? ({string:'',number:0,integer:0,boolean:false,object:{},array:[],null:null}[schema.type] ?? '');}
function valueField(value,schema={},name='值'){
  if(Array.isArray(schema?.type)||(!schema?.type&&['oneOf','anyOf','allOf'].some(k=>schema?.[k])))return `<textarea data-value-type="json" rows="4" aria-label="${esc(name)}">${esc(pretty(value===undefined?(schema.default??null):value))}</textarea>`;
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
  if(type==='json')return JSON.parse(el.value);
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
document.addEventListener('input',e=>{const row=e.target.closest('[data-value-content]')?.parentElement;if(row){const include=row.querySelector(':scope > .value-row-head > label > [data-value-include]');if(include)include.checked=true;}});

// Line-per-argument remains convenient; JSON preserves embedded newlines exactly.
function argvText(argv=[]){return argv.some(a=>/[\r\n]/.test(a))?JSON.stringify(argv,null,2):argv.join('\n');}
function readArgv(text){const value=text.trimStart().startsWith('[')?JSON.parse(text):text.split('\n').filter(Boolean);if(!Array.isArray(value)||value.some(a=>typeof a!=='string'))throw new Error('命令必须是字符串参数数组');return value;}
