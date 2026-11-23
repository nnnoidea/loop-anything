'use strict';

const loopModelDialog=document.createElement('dialog');
loopModelDialog.className='loop-model-dialog';
loopModelDialog.setAttribute('aria-labelledby','loop-model-title');
document.body.append(loopModelDialog);

function agentModelModeLabel(mode){
  return {manual:'使用接手会话的模型',delegated:'由接单 Agent 决定',executor:'由执行命令决定'}[mode]||'';
}

function renderLoopModelSummary(item){
  const summary=$('reader-model-summary');
  summary.hidden=!item.installedKey;
  if(!item.installedKey)return;
  const settings=item.models;
  const count=Object.values(settings?.nodes||{}).filter(node=>node.override&&Object.values(node.candidates).includes('managed')).length;
  summary.innerHTML=`<div><span>默认模型</span> <strong>${esc(settings?.default||'读取失败')}</strong>
    ${count?`<small>${count} 个节点单独设置</small>`:''}</div><button type="button" id="open-loop-model-settings">模型设置</button>`;
}

function modelSettingsRow(id,node){
  const modes=[...new Set(Object.values(node.candidates))];
  const managed=modes.includes('managed');
  const suffix=modes.filter(mode=>mode!=='managed').map(agentModelModeLabel).join('、');
  return `<div class="loop-model-row" data-model-node="${esc(id)}">
    <div><strong>${esc(node.label)}</strong>${suffix?`<small>${esc(suffix)}</small>`:''}</div>
    ${managed?`<div class="loop-model-choice">
      <select aria-label="${esc(node.label)}模型来源">
        <option value="inherit">跟随 Loop 默认</option>
        <option value="override" ${node.override?'selected':''}>单独设置</option>
      </select>
      <input aria-label="${esc(node.label)}模型" list="loop-model-options" value="${esc(node.override||'')}" maxlength="100"
             spellcheck="false" ${node.override?'required':'hidden disabled'}>
    </div>`:''}
  </div>`;
}

async function openLoopModelSettings(focusNode){
  const item=editor;
  if(!item?.installedKey)return;
  const key=item.installedKey;
  const models=await platformCall('read_loop_models',{key});
  if(editor!==item||page!=='editor'||loopModelDialog.open)return;
  const rows=Object.entries(models.nodes);
  const suggestions=[...new Set(['gpt-6.1-sol','gpt-6.2-sol',models.default,...rows.map(([,node])=>node.override).filter(Boolean)])];
  loopModelDialog.innerHTML=`<div class="dialog-heading"><h2 id="loop-model-title">模型设置</h2>
    <button type="button" class="close-dialog" aria-label="关闭">×</button></div>
    <form class="loop-model-form">
      <datalist id="loop-model-options">${suggestions.map(model=>`<option value="${esc(model)}"></option>`).join('')}</datalist>
      <label class="loop-model-default">Loop 默认模型
        <input id="loop-default-model" list="loop-model-options" value="${esc(models.default)}" maxlength="100" spellcheck="false" required>
      </label>
      <p class="small muted">保存后用于新 Run 中由平台启动的 Codex Agent。</p>
      ${rows.length?`<section class="loop-model-nodes"><h3>Agent 节点</h3>${rows.map(([id,node])=>modelSettingsRow(id,node)).join('')}</section>`:''}
      <p class="loop-model-error" role="alert" hidden></p>
      <div class="dialog-tasks"><button type="button" class="close-dialog">取消</button><button type="submit" class="primary">保存设置</button></div>
    </form>`;
  const form=loopModelDialog.querySelector('form');
  const defaultModel=$('loop-default-model');
  const settingsRows=[...form.querySelectorAll('[data-model-node]')];
  for(const row of settingsRows){
    const select=row.querySelector('select'),input=row.querySelector('input');
    if(!select)continue;
    select.addEventListener('change',()=>{
      const separate=select.value==='override';
      input.disabled=input.hidden=!separate;
      input.required=separate;
      if(separate){
        input.value ||= defaultModel.value;
        input.focus();
        input.select();
      }
    });
  }
  const submit=form.querySelector('[type=submit]'),error=form.querySelector('[role=alert]');
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    submit.disabled=true;
    error.hidden=true;
    try{
      const nodes=Object.create(null);
      for(const row of settingsRows){
        const select=row.querySelector('select');
        const id=row.dataset.modelNode;
        const value=select?select.value==='override'&&row.querySelector('input').value.trim():models.nodes[id].override;
        if(value)nodes[id]=value;
      }
      const saved=await platformCall('set_loop_models',{key,revision:models.revision,models:{default:defaultModel.value.trim(),nodes}});
      item.models=saved;
      loopModelDialog.close();
      if(editor===item&&page==='editor'){
        renderLoopModelSummary(item);
        renderAuthorProperties();
      }
      toast('模型设置已保存');
    }catch(failure){
      error.textContent=failure.message;
      error.hidden=false;
    }finally{
      submit.disabled=false;
    }
  });
  loopModelDialog.showModal();
  const target=settingsRows.find(row=>row.dataset.modelNode===focusNode)?.querySelector('select');
  (target||defaultModel).focus();
}

document.addEventListener('click',event=>{
  const button=event.target.closest('#open-loop-model-settings,[data-model-settings-node]');
  if(button)safely(()=>openLoopModelSettings(button.dataset.modelSettingsNode));
});
