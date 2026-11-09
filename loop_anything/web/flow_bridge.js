'use strict';
// Runs inside the opaque iframe. Its only platform action is selecting a known node.
function bindOverviewNodes(nodes){
  const ids=new Set(nodes.map(([id])=>id)),aliases=new Map();
  for(const [id,label] of nodes)for(const alias of new Set([id,label].filter(Boolean))){
    if(!aliases.has(alias))aliases.set(alias,new Set());
    aliases.get(alias).add(id);
  }
  const bound=[];
  for(const el of document.querySelectorAll('[data-loop-node],.am-node[data-key]')){
    const explicit=el.getAttribute('data-loop-node'),matches=aliases.get(el.getAttribute('data-key'));
    const id=explicit!==null?explicit:matches?.size===1?[...matches][0]:null;
    if(!ids.has(id))continue;
    el.setAttribute('data-loop-node',id);el.setAttribute('role','button');el.setAttribute('tabindex','0');
    el.setAttribute('aria-label','查看节点详情：'+(nodes.find(n=>n[0]===id)[1]||id));
    const select=event=>{event.preventDefault();event.stopPropagation();parent.postMessage({type:'loop-node-select',node:id},'*');};
    el.addEventListener('click',select);
    el.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' ')select(event);});
    el.closest('svg[role=img]')?.setAttribute('role','group');
    bound.push(el);
  }
  window.addEventListener('message',event=>{
    if(event.source!==parent||event.data?.type!=='loop-node-selected')return;
    for(const el of bound)el.setAttribute('aria-pressed',String(el.getAttribute('data-loop-node')===event.data.node));
  });
}

// Loaded by the sandboxed overview only; no API calls or platform DOM access.
bindOverviewNodes(JSON.parse(document.currentScript.dataset.nodes));
