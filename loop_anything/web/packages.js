'use strict';
// Packaging uses the same server codec as the CLI. Selecting a file never runs it.
editorPage.querySelector('.toolbar').insertAdjacentHTML('afterbegin','<button id="loop-package">Loop 包</button>');
$('new-loop_definition').insertAdjacentHTML('beforebegin','<button id="import-loop-package">导入 Loop 包</button>');
const packageDialog=document.createElement('dialog');packageDialog.id='package-dialog';packageDialog.className='editor-json-modal';
packageDialog.innerHTML=`<div class="dialog-heading"><h2>分享与安装 Loop</h2><button class="close-dialog" aria-label="关闭">×</button></div>
<p>同一种包支持未绑定、部分绑定和完整实现。安装不执行；smoke 只检查，不修复。请勿附带凭证、运行记录或私人数据。</p>
<section id="package-author"><h3>导出当前草稿</h3><p class="small">只附带明确选择的资源。文件夹保留目录名，例如选择 scripts 文件夹得到 scripts/task.py。普通文件放在包根目录。</p>
<label>添加文件<input type="file" id="package-assets" multiple></label><label>添加文件夹<input type="file" id="package-folder" webkitdirectory multiple></label>
<div id="package-asset-list"></div><label>可选 smoke 声明 · JSON（paths / env / programs）<textarea id="package-checks" class="code" rows="3">{}</textarea></label>
<button class="primary" id="package-export">下载 .loop.zip</button></section>
<hr><h3>导入已有包</h3><input type="file" id="package-upload" accept=".zip"><p id="package-summary" class="small">先选择包查看内容；不会自动安装或启动。</p>
<div class="dialog-tasks"><button id="package-edit" disabled>载入草稿继续编辑</button><button id="package-install" disabled>安装（不启动）</button></div>
<pre id="package-result" style="max-height:220px;overflow:auto;white-space:pre-wrap"></pre>`;
document.body.append(packageDialog);
let uploadedPackage=null;
function showPackage(authoring){
  if(authoring){collectAll();if(editor.loop_definition.schema_version!==2)throw new Error('Loop 包支持 v2 Loop 定义；旧版仍可使用 JSON 导出。');editor.assets ||= [];}
  $('package-author').hidden=!authoring;$('package-result').textContent='';
  if(authoring){$('package-checks').value=pretty(editor.checks || {});renderPackageAssets();}
  uploadedPackage=null;$('package-upload').value='';$('package-edit').disabled=$('package-install').disabled=true;
  $('package-summary').textContent='先选择包查看内容；不会自动安装或启动。';packageDialog.showModal();
}
function renderPackageAssets(){
  $('package-asset-list').innerHTML=(editor.assets || []).map((a,i)=>`<p>${esc(a.path)} <button type="button" data-remove-asset="${i}">移除</button></p>`).join('') || '<p class="muted small">未附带资源文件。手册和 Skill 若已内嵌Loop 定义，会随Loop 定义导出。</p>';
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
for(const id of ['package-assets','package-folder'])$(id).addEventListener('change',event=>safely(async()=>{
  const additions=[];
  for(const file of event.target.files)additions.push({path:file.webkitRelativePath || file.name,base64:await encodeFile(file),executable:false});
  const merged=new Map((editor.assets || []).map(a=>[a.path,a]));for(const a of additions)merged.set(a.path,a);
  if(merged.size>255 || [...merged.values()].reduce((n,a)=>n+a.base64.length,0)>28*1024*1024)throw new Error('资源超过包大小或文件数限制');
  editor.assets=[...merged.values()];dirty();renderPackageAssets();event.target.value='';
}));
$('package-checks').addEventListener('change',()=>safely(async()=>{editor.checks=JSON.parse($('package-checks').value);dirty();}));
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
  if(button.dataset.removeAsset!==undefined){editor.assets.splice(Number(button.dataset.removeAsset),1);dirty();renderPackageAssets();return;}
  if(button.dataset.packageSmoke){await openLoop(button.dataset.packageSmoke,'prepare');return;}
  switch(button.id){
    case 'loop-package':showPackage(true);break;
    case 'import-loop-package':showPackage(false);break;
    case 'package-export':{
      editor.checks=JSON.parse($('package-checks').value || '{}');dirty();
      const result=await api('packages/export',{document:{loop_definition:editor.loop_definition,implementations:editor.implementations,checks:editor.checks},assets:editor.assets || []});
      downloadPackage(result.base64,editor.loop_definition.id);$('package-result').textContent='已导出。运行前请在目标环境安装并执行 smoke；本机路径不会自动改写。';break;}
    case 'package-edit':{
      if(!uploadedPackage)return;if(editor?.dirty && !confirm('当前草稿未保存，是否载入包？'))return;
      rememberEditor();editor={loop_definition:structuredClone(uploadedPackage.document.loop_definition),implementations:structuredClone(uploadedPackage.document.implementations),
              checks:structuredClone(uploadedPackage.document.checks || {}),assets:structuredClone(uploadedPackage.assets),dirty:true};
      packageDialog.close();openEditor();break;}
    case 'package-install':{
      if(!uploadedPackage)return;const installed=await api('packages/install',{base64:uploadedPackage.encoded});
      await loadCatalog();packageDialog.close();await openLoop(installed.key,'prepare');
      try{const report=await preflight(currentLoop());if(loopKey===installed.key && loopTab==='prepare')$('loop-check-result').innerHTML=checkHTML(report);}catch(error){toast('已安装，检查失败：'+error.message);return;}
      toast('已安装，未启动。请查看使用准备。');break;}
  }
}));

// Reuse draft assets and the revision-checked authoring tool; opening a file never executes it.
const schemeFileDialog=document.createElement('dialog');schemeFileDialog.className='scheme-file-dialog';document.body.append(schemeFileDialog);
document.addEventListener('click',event=>safely(async()=>{
  const button=event.target.closest('[data-open-scheme-asset]');if(!button||!editor)return;
  const draft=editor;await saveEditor();
  const result=await platformCall('read_loop',{draft_id:draft.id,asset_path:button.dataset.openSchemeAsset});
  if(editor!==draft||page!=='editor')return;
  const file=result.value;
  schemeFileDialog.innerHTML=`<form><div class="dialog-heading"><h2>${esc(file.path)}</h2><button type="button" class="close-dialog" aria-label="关闭">×</button></div><p class="small muted">包内共用文件 · 保存到当前草稿，引用它的方案都会读取修改后的内容。已有 Run 保持原样。</p><p class="small muted">${file.bytes} bytes · ${file.executable?'可执行':'普通文件'} · ${result.references.length} 处直接引用</p>${file.encoding==='utf-8'?`<textarea aria-label="包文件内容" spellcheck="false">${esc(file.content)}</textarea>`:'<p>二进制文件，请通过 Loop 包替换。</p>'}<p class="scheme-file-error" role="alert"></p><div class="dialog-tasks">${file.encoding==='utf-8'?'<button type="submit" class="primary">保存文件到草稿</button>':''}<button type="button" class="close-dialog">关闭</button></div></form>`;
  schemeFileDialog.querySelector('form').onsubmit=async event=>{
    event.preventDefault();const submit=schemeFileDialog.querySelector('[type=submit]');submit.disabled=true;
    try{if(editor!==draft||page!=='editor')throw new Error('当前草稿已切换，请重新打开文件。');await editWithTool('put_asset',{path:file.path,content:schemeFileDialog.querySelector('textarea').value});schemeFileDialog.close();toast('文件已保存到草稿');}
    catch(error){schemeFileDialog.querySelector('.scheme-file-error').textContent=error.message;}
    finally{submit.disabled=false;}
  };
  schemeFileDialog.showModal();
}));
