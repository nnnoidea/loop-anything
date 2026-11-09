'use strict';
// Packaging uses the same server codec as the CLI. Selecting a file never runs it.
editorPage.querySelector('.editor-more-actions').insertAdjacentHTML('beforeend','<button id="loop-package">下载与导入</button>');
$('catalog-page').querySelector('.toolbar').insertAdjacentHTML('beforeend','<button id="import-loop-package">导入 Loop 包</button>');
const packageDialog=document.createElement('dialog');packageDialog.id='package-dialog';packageDialog.className='editor-json-modal';
packageDialog.innerHTML=`<div class="dialog-heading"><h2>分享与安装 Loop</h2><button class="close-dialog" aria-label="关闭">×</button></div>
<p>同一种包支持未绑定、部分绑定和完整实现。安装不执行；smoke 只检查，不修复。请勿附带凭证、运行记录或私人数据。</p>
<section id="package-author"><h3>下载当前 Loop 源文件</h3><p class="small">包含 loop.json、流程图、Skill 与脚本。手动修改在导出的源文件中进行，重新打包后导入；已安装版本与已有运行保持原快照。</p><div id="package-asset-list"></div>
<button class="primary" id="package-export">下载 .loop.zip</button></section>
<hr><h3>导入已有包</h3><input type="file" id="package-upload" accept=".zip"><p id="package-summary" class="small">先选择包查看内容；不会自动安装或启动。</p>
<div class="dialog-tasks"><button id="package-edit" disabled>导入为草稿</button><button id="package-install" disabled>安装（不启动）</button></div>
<pre id="package-result" style="max-height:220px;overflow:auto;white-space:pre-wrap"></pre>`;
document.body.append(packageDialog);
let uploadedPackage=null;
function showPackage(authoring){
  if(authoring){if(editor.loop_definition.schema_version!==2)throw new Error('Loop 包支持 v2 Loop 定义；旧版仍可使用 JSON 导出。');editor.assets ||= [];}
  $('package-author').hidden=!authoring;$('package-result').textContent='';
  if(authoring)renderPackageAssets();
  uploadedPackage=null;$('package-upload').value='';$('package-edit').disabled=$('package-install').disabled=true;
  $('package-summary').textContent='先选择包查看内容；不会自动安装或启动。';packageDialog.showModal();
}
function renderPackageAssets(){
  $('package-asset-list').innerHTML=(editor.assets||[]).map(a=>`<p>${esc(a.path)}</p>`).join('')||'<p class="muted small">未附带资源文件。</p>';
}
async function encodeFile(file){
  if(file.size>20*1024*1024)throw new Error('单个文件超过 20 MiB');
  const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(binary);
}
function downloadPackage(encoded,name){
  const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
  const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));
  const link=document.createElement('a');link.href=url;link.download=name+'.loop.zip';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('package-upload').addEventListener('change',event=>safely(async()=>{
  uploadedPackage=null;$('package-edit').disabled=$('package-install').disabled=true;
  const file=event.target.files[0];if(!file)return;
  const encoded=await encodeFile(file);const inspected=await api('packages/inspect',{base64:encoded});
  uploadedPackage={encoded,...inspected};const missing=inspected.report.unbound_nodes;
  $('package-summary').textContent=`${inspected.document.loop_definition.name || inspected.document.loop_definition.id} · ${inspected.assets.length} 个资源文件 · 未绑定：${missing.length?missing.join('、'):'无'}。包有效，不代表环境已就绪。`;
  $('package-edit').disabled=$('package-install').disabled=false;
}));
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.packageSmoke){await openLoop(button.dataset.packageSmoke,'prepare');return;}
  switch(button.id){
    case 'loop-package':button.closest('details').open=false;showPackage(true);break;
    case 'import-loop-package':showPackage(false);break;
    case 'package-export':{const result=editor.installedKey?await api('packages/export',await api('packages/read',{key:editor.installedKey})):await platformCall('export_loop',{draft_id:editor.id});downloadPackage(result.base64,editor.loop_definition.id);$('package-result').textContent='已导出，未启动任何任务。';break;}
    case 'package-edit':{
      if(!uploadedPackage)return;
      const imported=await api('packages/draft',{base64:uploadedPackage.encoded});
      rememberEditor();editor={...imported};
      packageDialog.close();openEditor();break;}
    case 'package-install':{
      if(!uploadedPackage)return;const installed=await api('packages/install',{base64:uploadedPackage.encoded});
      await loadCatalog();packageDialog.close();await openLoop(installed.key,'prepare');
      toast('已安装，未启动。可以查看流程或启动。');break;}
  }
}));

// Reuse draft assets and the revision-checked authoring tool; opening a file never executes it.
const schemeFileDialog=document.createElement('dialog');schemeFileDialog.className='scheme-file-dialog';document.body.append(schemeFileDialog);
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('[data-open-scheme-asset]');if(!button||!editor)return;
  const draft=editor;
  const result=await platformCall('read_loop',{...readerIdentity(draft),asset_path:button.dataset.openSchemeAsset});
  if(editor!==draft||page!=='editor')return;
  const file=result.value;
  schemeFileDialog.innerHTML=`<div class="dialog-heading"><h2>${esc(file.path)}</h2><button type="button" class="close-dialog" aria-label="关闭">×</button></div><p class="small muted">包文件内容 · 只读；修改由 Agent 完成。</p><p class="small muted">${file.bytes} bytes · ${file.executable?'可执行':'普通文件'} · ${result.references.length} 处直接引用</p>${file.encoding==='utf-8'?`<textarea aria-label="包文件内容" spellcheck="false" readonly>${esc(file.content)}</textarea>`:'<p>二进制文件，可导出 Loop 包查看。</p>'}<details><summary>直接引用位置</summary><pre>${esc(pretty(result.references))}</pre></details><button type="button" class="close-dialog">关闭</button>`;
  schemeFileDialog.showModal();
}));

// Recipient settings stay outside the shared workflow. The web exposes reading/download;
// the existing Agent tools edit the JSON with a revision, without another configuration editor.
editorPage.querySelector('.editor-more-actions').insertAdjacentHTML('beforeend','<button id="loop-config-template">运行配置模板</button>');
const loopConfigDialog=document.createElement('dialog');loopConfigDialog.className='editor-json-modal loop-config-modal';document.body.append(loopConfigDialog);
let viewedLoopConfig=null;
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.loopConfig||button.id==='loop-config-template'){
    const draft=button.id==='loop-config-template'&&!editor.installedKey;
    if(button.id==='loop-config-template')button.closest('details').open=false;
    const args=draft?{draft_id:editor.id}:{key:button.dataset.loopConfig||editor.installedKey};
    const result=await platformCall('read_loop_config',args);
    viewedLoopConfig={text:result.raw??pretty(result.config),name:draft?'config.example.json':(button.dataset.loopConfig||editor.installedKey)+'.json'};
    loopConfigDialog.innerHTML=`<div class="dialog-heading"><h2>${draft?'分享用运行配置模板':'接收方运行配置'}</h2><button type="button" class="close-dialog" aria-label="关闭">×</button></div><p>${draft?'模板随 Loop 包分享；接收方填写自己的环境配置。':'新 Run 自动读取；本次启动参数优先。修改对应文件或通过 Agent 配置，已有 Run 保持原快照。'}</p><p class="small muted">${draft?'包内文件':'平台服务端文件'}：<code>${esc(result.path)}</code>${result.exists?'':'（尚未单独保存，当前显示模板）'}</p><textarea aria-label="运行配置 JSON" readonly>${esc(result.raw??pretty(result.config))}</textarea>${result.error?`<p class="task-error">${esc(result.error)}；可交给 Agent 修正后保存。</p>`:''}<div class="dialog-tasks"><button type="button" id="download-loop-config">下载配置文件</button><button type="button" class="close-dialog">关闭</button></div>`;
    loopConfigDialog.showModal();
  }
  if(button.id==='download-loop-config'&&viewedLoopConfig){
    const url=URL.createObjectURL(new Blob([viewedLoopConfig.text+'\n'],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=viewedLoopConfig.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
}));
