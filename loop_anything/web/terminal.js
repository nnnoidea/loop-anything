'use strict';
// The panel attaches to an existing execution; opening/closing it never starts/stops work.
const terminalDialog=document.createElement('dialog');terminalDialog.id='terminal-dialog';
terminalDialog.innerHTML='<div class="dialog-heading"><h2 id="terminal-title">执行终端</h2><button id="terminal-close" aria-label="关闭终端">×</button></div><div class="terminal-toolbar"><label>执行会话<select id="terminal-session"></select></label><span id="terminal-status" role="status"></span><button id="terminal-recover" hidden>已确认旧进程停止</button><button id="terminal-interrupt" disabled>发送 Ctrl+C</button></div><p id="terminal-help" class="small muted">关闭面板后任务继续运行。任务结果以平台提交记录为准。</p><div id="terminal-screen"></div><p id="terminal-error" role="alert"></p>';
document.body.append(terminalDialog);
let terminalView=null;
function closeTerminal(){const view=terminalView;terminalView=null;if(view){clearTimeout(view.timer);view.observer.disconnect();view.term.dispose();}terminalDialog.close();}
$('terminal-close').onclick=closeTerminal;terminalDialog.addEventListener('cancel',event=>{event.preventDefault();closeTerminal();});
function terminalSend(view,body){
  if(terminalView!==view||!view.canInput)return;
  const session=view.session;
  view.writes=view.writes.then(()=>{
    if(terminalView!==view||view.session!==session||!view.canInput)return;
    return api(view.url,{session_id:session,...body});
  }).catch(error=>{if(terminalView===view){view.canInput=false;view.term.options.disableStdin=true;$('terminal-error').textContent=error.message;}});
}
async function openTerminal(executionId,sessionId=null){
  const communication=run.executions.find(e=>e.id===executionId)?.communication_id;if(communication){await openCommunicationRequest(communication);return;}
  closeTerminal();
  const attempt=run.executions.find(e=>e.id===executionId);if(!attempt)return;
  $('terminal-title').textContent=`${nodeLabel(attempt.node)} · 第 ${attempt.attempt} 次执行`;
  $('terminal-status').textContent='连接中…';$('terminal-error').textContent='';$('terminal-screen').replaceChildren();$('terminal-session').replaceChildren();$('terminal-interrupt').disabled=true;$('terminal-recover').hidden=true;
  terminalDialog.showModal();
  const term=new Terminal({convertEol:!attempt.implementation.terminal,disableStdin:true,cursorBlink:true,fontSize:13,scrollback:10000,theme:{background:'#151923',foreground:'#e4e8ef'},linkHandler:{activate:()=>{}}});
  // The host answers device/cursor queries, including while no browser is open.
  for(const prefix of ['', '?', '>'])for(const final of ['n','c'])term.parser.registerCsiHandler({prefix,final},()=>true);
  const fit=new FitAddon.FitAddon();term.loadAddon(fit);term.open($('terminal-screen'));fit.fit();
  const view={term,fit,url:`runs/${encodeURIComponent(run.id)}/executions/${encodeURIComponent(executionId)}/terminal`,session:sessionId,cursor:0,writes:Promise.resolve(),canInput:false,timer:null,executionId};terminalView=view;
  view.observer=new ResizeObserver(()=>{if(terminalView===view){fit.fit();terminalSend(view,{cols:term.cols,rows:term.rows});}});view.observer.observe($('terminal-screen'));
  term.onData(data=>{if(view.canInput)for(let i=0;i<data.length;i+=4000)terminalSend(view,{data:data.slice(i,i+4000)});});
  async function poll(){
    try{
      const result=await api(view.url+`?after=${view.cursor}`+(view.session?'&session='+encodeURIComponent(view.session):''));
      if(terminalView!==view)return;
      const session=result.session;if(session)term.options.convertEol=!session.interactive;
      if(!session){$('terminal-status').textContent='暂无会话记录';$('terminal-help').textContent='尚未启动命令，或此执行发生在终端记录功能启用前。';}
      else{
        view.session=session.id;
        const select=$('terminal-session');if(select.options.length!==result.sessions.length){select.replaceChildren(...result.sessions.map((s,i)=>new Option(`${i+1} · ${new Date(s.created_at*1000).toLocaleTimeString()}`,s.id)));select.value=session.id;}
        if(result.output.length)await new Promise(resolve=>term.write(result.output.map(row=>row.text).join(''),resolve));
        if(terminalView!==view)return;
        const becameInteractive=!view.canInput&&session.can_input;view.cursor=result.cursor;view.canInput=!!session.can_input;term.options.disableStdin=!view.canInput;$('terminal-interrupt').disabled=!view.canInput;
        $('terminal-status').textContent=({starting:'正在启动',running:'运行中',exited:'进程已退出',error:'执行异常',interrupted:'连接已中断',released:'已确认停止'})[session.state]||session.state;
        if(session.returncode!==undefined)$('terminal-status').textContent+=' · 退出码 '+session.returncode;
        $('terminal-help').textContent=session.output_source==='native_session'?'执行过程保存在原 Agent session；从任务操作恢复该 session 查看。':view.canInput?'点击终端即可输入；关闭面板后任务继续运行。Agent 调用 finish 后平台关闭本次会话。':session.interactive?'执行结束后可查看历史；继续工作请从任务操作发起。':'实时显示命令输出；此命令使用一次性输入，不接受终端交互。';
        $('terminal-error').textContent=session.error||session.native_session_error||view.notice||'';
        $('terminal-recover').hidden=session.state!=='interrupted';
        if(becameInteractive){terminalSend(view,{cols:term.cols,rows:term.rows});term.focus();}
      }
      view.timer=setTimeout(poll,result.more?0:350);
    }catch(error){if(terminalView===view){view.canInput=false;term.options.disableStdin=true;$('terminal-error').textContent=error.message;view.timer=setTimeout(poll,1500);}}
  }
  poll();
}
$('terminal-session').onchange=()=>{if(terminalView)openTerminal(terminalView.executionId,$('terminal-session').value);};
$('terminal-recover').onclick=()=>safely(async()=>{const view=terminalView;if(!view)return;await api(view.url,{action:'confirm_stopped',session_id:view.session,confirmed_stopped:true});$('terminal-recover').hidden=true;toast('已记录进程停止，可以重新恢复会话');});
$('terminal-interrupt').onclick=()=>{if(terminalView)terminalSend(terminalView,{data:'\x03'});};
document.addEventListener('click',event=>{const button=event.target.closest('[data-open-terminal]');if(button)safely(()=>openTerminal(button.dataset.openTerminal));});

const resultDialog=document.createElement('dialog');resultDialog.id='task-result-dialog';resultDialog.innerHTML='<div class="dialog-heading"><h2 id="task-result-title">运行结果</h2><button id="task-result-close" aria-label="关闭结果">×</button></div><label>执行尝试<select id="task-result-attempt"></select></label><div id="task-result-content"></div>';document.body.append(resultDialog);
$('task-result-close').onclick=()=>resultDialog.close();
let resultTask=null;
function renderTaskResult(){
  const task=run.tasks[resultTask],node=run.loop_definition.nodes[task.spec.node],attempt=run.executions.find(e=>e.id===$('task-result-attempt').value);
  $('task-result-title').textContent=taskLabel(task)+' · 运行结果';
  const outputs=Object.entries(attempt?.outputs||{});
  $('task-result-content').innerHTML=`<p>${badge(attempt?.status||task.status)} <span class="small muted">${esc(task.id)}${attempt?' · 第 '+attempt.attempt+' 次执行':''}</span></p>${outputs.length?outputs.map(([port,value])=>`<section class="result-section"><h3>${esc(run.loop_definition.records[node.outputs[port]?.record_type]?.title||port)}</h3>${resultWithSchema(value,run.loop_definition.records[node.outputs[port]?.record_type]||{},attempt,port)}</section>`).join(''):`<p class="empty-inline">${attempt?.status==='completed'?'本次执行已完成，没有声明的输出。':'本次执行尚未提交结果。'}</p>`}${taskError(attempt)}${!attempt||attempt.id===task.execution_id?taskWaitReasons(task):''}${attempt?.implementation.kind==='agent'?`<div class="toolbar"><button data-result-terminal="${esc(attempt.id)}">查看会话记录</button>${!['completed','terminated'].includes(run.status)?`<button data-result-resume="${esc(attempt.id)}">${attempt.worker_active?'打开会话':'恢复会话'}</button>`:''}</div>`:''}`;
}
async function openTaskResult(taskId){
  run=await api('runs/'+run.id);resultTask=taskId;const attempts=run.executions.filter(e=>e.task_id===taskId);
  $('task-result-attempt').replaceChildren(...attempts.map(e=>new Option(`第 ${e.attempt} 次 · ${labels[e.status]||e.status}`,e.id)));if(attempts.length)$('task-result-attempt').value=attempts.at(-1).id;
  $('task-result-attempt').disabled=!attempts.length;renderTaskResult();resultDialog.showModal();
}
$('task-result-attempt').onchange=renderTaskResult;
const resumeDialog=document.createElement('dialog');resumeDialog.id='resume-agent-dialog';resumeDialog.innerHTML='<form id="resume-agent-form"><div class="dialog-heading"><h2>恢复 Agent 会话</h2><button type="button" id="resume-agent-close" aria-label="关闭恢复会话">×</button></div><p id="resume-agent-notice" class="small muted"></p><div class="candidate-identity"><label>CLI<select id="resume-agent-provider"><option value="codex">Codex</option><option value="claude">Claude Code</option><option value="custom">其他 CLI</option></select></label><label>原生 session ID<input id="resume-agent-id" required placeholder="该次 CLI 执行的真实会话 ID"></label></div><label>工作目录<input id="resume-agent-cwd" placeholder="沿用原执行目录"></label><p id="resume-agent-identity-note" class="small muted"></p><label>想继续讨论或处理什么？<textarea id="resume-agent-message" rows="3" required placeholder="例如：解释这次结果，并指出还有哪些未验证的假设"></textarea></label><details><summary>恢复命令（每行一个参数，或 JSON 数组）</summary><textarea id="resume-agent-command" class="code" rows="5" required></textarea><p class="small muted">使用 {{session_id}} 和 {{prompt}} / {{prompt_file}}。请保留所需 CLI 配置；不会自动添加模型或权限参数。</p></details><p id="resume-agent-error" role="alert"></p><div class="dialog-tasks"><button class="primary" id="resume-agent-submit">恢复并继续</button></div></form>';document.body.append(resumeDialog);
let resumeTarget=null;
$('resume-agent-close').onclick=()=>resumeDialog.close();
async function openAgentSession(executionId){
  const communication=run.executions.find(e=>e.id===executionId)?.communication_id;if(communication){await openCommunicationRequest(communication);return;}
  const runId=run.id,info=await api(`runs/${encodeURIComponent(runId)}/executions/${encodeURIComponent(executionId)}/session`);
  if(info.active_session){await openTerminal(executionId,info.active_session);return;}
  resumeTarget={runId,executionId,revision:info.revision,native:info.native_session};$('resume-agent-cwd').value=info.cwd||'';$('resume-agent-provider').value=info.provider;$('resume-agent-id').value=info.native_session?.id||'';$('resume-agent-command').value=argvText(info.resume_command);$('resume-agent-command').closest('details').open=!info.resume_command.length;$('resume-agent-message').value='';$('resume-agent-error').textContent='';
  $('resume-agent-notice').textContent=info.notice;$('resume-agent-identity-note').textContent=info.native_session?'已关联该次执行的原生 CLI 会话。若此前关联有误，修改 ID 并提交会重新关联；旧记录保留。':'该次执行尚未记录原生 ID。请从对应 CLI 会话取得后填入，平台不会猜测最近一次会话。';
  $('resume-agent-submit').disabled=!info.can_resume;if(!info.can_resume)$('resume-agent-error').textContent='当前 Run 或主机不支持交互恢复。';resumeDialog.showModal();
}
$('resume-agent-provider').onchange=()=>{const provider=$('resume-agent-provider').value;$('resume-agent-command').value=(provider==='codex'?['codex','resume','{{session_id}}','{{prompt}}']:provider==='claude'?['claude','--resume','{{session_id}}','{{prompt}}']:[]).join('\n');$('resume-agent-command').closest('details').open=true;};
$('resume-agent-form').onsubmit=async event=>{
  event.preventDefault();$('resume-agent-submit').disabled=true;
  try{const value=await api(`runs/${encodeURIComponent(resumeTarget.runId)}/executions/${encodeURIComponent(resumeTarget.executionId)}/resume`,{revision:resumeTarget.revision,previous_native_session:resumeTarget.native,provider:$('resume-agent-provider').value,native_session_id:$('resume-agent-id').value.trim(),command:readArgv($('resume-agent-command').value),message:$('resume-agent-message').value,...($('resume-agent-cwd').value.trim()?{cwd:$('resume-agent-cwd').value.trim()}:{})});resumeDialog.close();await openTerminal(resumeTarget.executionId,value.session_id);if(value.attached&&terminalView){terminalView.notice='此会话已在运行，本次要求尚未发送。请在终端输入：'+$('resume-agent-message').value;$('terminal-error').textContent=terminalView.notice;}}
  catch(error){$('resume-agent-error').textContent=error.message;const current=await api('runs/'+resumeTarget.runId);resumeTarget.revision=current.revision;}
  finally{$('resume-agent-submit').disabled=false;}
};
document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;const d=button.dataset;
  if(d.taskResult)safely(()=>openTaskResult(d.taskResult));
  if(d.agentSession)safely(()=>openAgentSession(d.agentSession));
  if(d.resultTerminal){resultDialog.close();safely(()=>openTerminal(d.resultTerminal));}
  if(d.resultResume){resultDialog.close();safely(()=>openAgentSession(d.resultResume));}
});
