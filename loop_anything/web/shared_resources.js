'use strict';

function resourceUrl(value){
  try{
    const url=new URL(value);
    return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:'';
  }catch{return '';}
}

function resourceLocation(value,kind,label){
  const url=kind==='url'&&resourceUrl(value);
  return url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a><small>${esc(value)}</small>`:
    `<code>${esc(value)}</code>`;
}

function resourcePreviewHTML(preview={}){
  const facts=preview.facts?.length?`<dl class="resource-facts">${preview.facts.map(fact=>`<div><dt>${esc(fact.label)}</dt><dd>${esc(fact.value)}</dd></div>`).join('')}</dl>`:'';
  const sections=(preview.sections||[]).filter(section=>section.items.length).map(section=>`
    <section class="resource-preview-section"><h3>${esc(section.title)}</h3>
    <ul>${section.items.map(item=>`<li><strong>${esc(item.title)}</strong>
      <p>${esc(item.text)}</p>${item.details?`<details><summary>展开详情</summary><p>${esc(item.details)}</p></details>`:''}
    </li>`).join('')}</ul></section>`).join('');
  return preview.summary||facts||sections?`<section class="resource-panel">
    <h2>资源预览</h2>${preview.summary?`<p>${esc(preview.summary)}</p>`:''}${facts}${sections}</section>`:'';
}

async function openSharedResources(route,serial){
  const root=$('resources-content');
  root.innerHTML='<p class="muted">正在读取资源…</p>';
  try{
    const result=await api(route.id?'resources/'+encodeURIComponent(route.id):'resources');
    if(serial!==navigationSerial)return;
    if(!route.id){
      root.innerHTML=result.resources.length?`<ul class="resource-list">${result.resources.map(item=>`
        <li><div><span class="resource-kind">${item.location_kind==='url'?'链接':'目录'}</span>
        <h2>${navLink({type:'resources',id:item.id},item.name)}</h2></div>
        ${item.description?`<p>${esc(item.description)}</p>`:''}</li>`).join('')}</ul>`:
        '<p class="resource-panel muted">目录中还没有资源。</p>';
      return;
    }
    const item=result.resource;
    root.innerHTML=`<article class="resource-detail">
      <div class="resource-title"><h2 id="shared-resource-title">${esc(item.name)}</h2>
      ${item.description?`<p>${esc(item.description)}</p>`:''}</div>
      ${resourcePreviewHTML(item.preview)}
      <section class="resource-panel resource-access"><h2>访问与节点引用</h2><dl>
        <div><dt>资源位置</dt><dd>${resourceLocation(item.location,item.location_kind,'打开资源')}</dd></div>
        <div><dt>Skill 入口</dt><dd>${resourceLocation(item.skill,item.skill_kind,'打开 Skill')}</dd></div>
        <div><dt>资源 ID</dt><dd><code>${esc(item.id)}</code> <button type="button" id="resource-copy">复制 ID</button></dd></div>
      </dl></section></article>`;
    $('resource-copy').addEventListener('click',()=>safely(async()=>{
      await navigator.clipboard.writeText(item.id);
      toast('已复制资源 ID');
    }));
  }catch(error){
    if(serial!==navigationSerial)return;
    root.innerHTML=`<p class="resource-panel" role="status">${esc(error.message)}</p>`;
  }
}
