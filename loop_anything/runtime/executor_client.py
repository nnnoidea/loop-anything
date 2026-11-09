"""Headless receiver driven by the same local scheduler as personal tasks."""
import copy
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import threading
import time
import uuid

from loop_anything.runtime.host_runtime import run_command, CommandNotStopped
from loop_anything.runtime.process_session import ProcessSession
from loop_anything.runtime.team_transport import core
from loop_anything.runtime.tool_client import request, module
from loop_anything.runtime import process_results


class Receiver:
    def __init__(self, config, root):
        self.config=config;self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        identity=self.root/'receiver.json'
        if not identity.exists():core.atomic_json(identity,{'id':'executor-'+uuid.uuid4().hex})
        self.ident=json.loads(identity.read_text())['id'];self.owner=uuid.uuid4().hex
        self.url=config['server'];self.nas=module('platform_transport').endpoint(self.url)[0] if self.url.startswith('nas:') else None
        self.capacity=config.get('capacity',1)
        if type(self.capacity) is not int or not 1<=self.capacity<=8:raise ValueError('receiver capacity must be 1–8')
        self.pool=ThreadPoolExecutor(max_workers=self.capacity)
        self.lock=threading.RLock();self.jobs={};self.last_heartbeat=0
        self.closed=False

    def metadata(self):
        return {'id':self.ident,'owner':self.owner,'name':self.config.get('name') or self.ident,
                'machine':socket.gethostname(),'capacity':self.capacity,'heartbeat':time.time()}

    def file(self, ident):return self.root/'receipts'/(core.address(ident)+'.json')

    def save(self, job):
        # This is local state, not a network envelope; a near-limit request still needs room for its receipt.
        core.atomic_json(self.file(job['packet']['id']),{'packet':job['packet'],'update':job['update']})

    def read_receipt(self, path):
        value=json.loads(path.read_text(encoding='utf-8'))
        return core.read_message(path) if value.get('transport') in ('snapshot-v1','parts-v1') else value

    def result_file(self, ident):return self.root/'results'/(core.address(ident)+'.json')

    def deliver(self, job):
        ident=job['packet']['id']
        # A failed disk/network write is delivery failure, never command failure.
        if 'unsaved_result' in job:self.save_result(job,job['unsaved_result'])
        with self.lock:
            content=copy.deepcopy({k:v for k,v in job['update'].items() if k!='sequence'})
            folder=self.nas/'executors'/self.ident if self.nas else None
            if not job['update'].get('result_manifest') and content==job.get('delivered') and (not folder or (folder/'reports'/(ident+'.json')).exists()):
                return (folder/'acks'/(ident+'.json')).exists() if folder else job.get('accepted',False)
            job['update']['sequence']+=1
            self.save(job)
            payload={'token':job['packet']['token'],'update':copy.deepcopy(job['update'])}
        if self.nas:
            core.Nas({'path':str(folder)}).put('reports/'+ident+'.json',payload)
            if job['update'].get('result_manifest'):
                offset=job.get('result_offset',0);description=job['update']['result_manifest']
                for _ in range(4):
                    if offset>=description['bytes']:break
                    part=process_results.chunk(self.result_file(ident),offset)
                    core.publish_message(folder/'results'/ident/(str(offset)+'.json'),part)
                    offset+=len(base64.b64decode(part['data']))
                job['result_offset']=offset
            job['delivered']=content
            return (folder/'acks'/(ident+'.json')).exists()
        answer=request(self.url,'executor_report',{'id':ident,**payload})
        if not answer.get('ok'):raise ValueError(str(answer))
        if job['update'].get('result_manifest') and not answer.get('terminal'):
            for _ in range(4):
                offset=answer.get('result_offset',0)
                part=process_results.chunk(self.result_file(ident),offset)
                answer=request(self.url,'executor_report',{'id':ident,'token':payload['token'],
                    'update':dict(payload['update'],result_chunk=part)})
                if not answer.get('ok'):raise ValueError(str(answer))
                if answer.get('terminal'):break
        job['delivered']=content;job['accepted']=answer.get('terminal',False)
        return job['accepted']

    def controls(self, job, controls):
        for control in controls:
            if control['id']<=job['update']['control_cursor']:continue
            if control.get('reason'):
                job['reason']=control['reason']
                if not job.get('session'):job['stop'].set()
            session=job.get('session')
            if control.get('data'):
                if not session:continue
                session.inputs.put_nowait(control['data'].encode())
            if control.get('cols') and session and session.master is not None:
                from loop_anything.runtime.terminal import resize
                resize(session.master,control['cols'],control['rows'])
                if session.screen:session.screen.resize(lines=control['rows'],columns=control['cols'])
            job['update']['control_cursor']=control['id']

    def tick(self):
        if self.closed:return
        if self.nas:
            folder=self.nas/'executors'/self.ident
            if time.time()-self.last_heartbeat>=5:
                core.atomic_json(folder/'worker.json',self.metadata());self.last_heartbeat=time.time()
            packets=[core.read_message(p) for p in sorted((folder/'inbox').glob('*.json'))]
            controls={p.stem:core.read_message(p) for p in (folder/'controls').glob('*.json')}
        else:
            response=request(self.url,'executor_poll',{'worker':self.metadata()})
            if not response.get('ok'):raise ValueError(str(response))
            packets=response['jobs'];controls=response['controls']
        for packet in packets:
            ident=core.address(packet['id'])
            if packet['executor']!=self.ident:continue
            if ident in self.jobs:continue
            receipt=self.file(ident)
            if receipt.exists():
                previous=self.read_receipt(receipt)
                if previous.get('acknowledged'):continue
                if previous['packet']!=packet:raise ValueError('Execution ID content changed')
                update=previous['update']
                if update['state'] not in ('completed','failed','unknown','delivering'):
                    if self.result_file(ident).exists():
                        update.update(state='delivering',execution_state='completed',result_manifest=process_results.manifest(self.result_file(ident)))
                    else:
                        update.update(state='unknown',error='Previous receiver ended; verify its process. Recorded executions are never automatically restarted.')
                self.jobs[ident]={'packet':packet,'update':update,'stop':threading.Event(),'future':None,'reason':None}
            elif sum(bool(j.get('future') and not j['future'].done()) for j in self.jobs.values())<self.capacity:
                job={'packet':packet,'update':{'state':'starting','sequence':0,'events':[],'control_cursor':0},
                     'stop':threading.Event(),'future':None,'reason':None}
                # Publish acceptance durably before launching. A lost reply cannot cause another spawn.
                self.save(job);self.jobs[ident]=job
                self.controls(job,controls.get(ident,[]))
                job['future']=self.pool.submit(self.execute,job)
        for ident,job in list(self.jobs.items()):
            self.controls(job,controls.get(ident,[]))
            accepted=self.deliver(job)
            if accepted and job['update']['state'] in ('completed','failed','unknown','delivering') and (not job.get('future') or job['future'].done()):
                core.atomic_json(self.file(ident),{'acknowledged':True,'id':ident,'state':'completed' if job['update']['state']=='delivering' else job['update']['state'],
                    'native_session':job['update'].get('session',{}).get('native_session')})
                if self.nas:
                    files=core.Nas({'path':str(self.nas/'executors'/self.ident)})
                    files.delete('reports/'+ident+'.json');files.delete('controls/'+ident+'.json')
                    for path in (self.nas/'executors'/self.ident/'results'/ident).glob('*.json'):path.unlink()
                self.result_file(ident).unlink(missing_ok=True)
                self.jobs.pop(ident,None)

    def save_result(self, job, result):
        ident=job['packet']['id']
        job['update'].pop('delivery_error',None)
        if len(json.dumps(result,ensure_ascii=False).encode())<=process_results.INLINE_BYTES:
            job['update'].update(state='completed',execution_state='completed',result=result)
        else:
            description=process_results.save(self.result_file(ident),result)
            job['update'].update(state='delivering',execution_state='completed',result_manifest=description)
        self.save(job);job.pop('unsaved_result',None)

    def execute(self, job):
        try:
            spec=copy.deepcopy(job['packet']['payload'])
            team=spec.pop('team_root',None)
            if team and self.nas:
                spec['cwd']=module('platform_transport').mount_path(spec.get('cwd'),[team],str(self.nas))
            if team:
                spec['command']=[arg.replace('{{team_root}}',str(self.nas or team)) for arg in spec['command']]
            if 'prompt_context' in spec:
                from loop_anything.runtime.agent_prompt import receiver_context
                context=receiver_context(spec['prompt_context'],team,str(self.nas) if self.nas else None)
                encoded=json.dumps(context,ensure_ascii=False,indent=spec.get('prompt_indent'))
                template=spec.get('prompt_template')
                spec['prompt']=encoded if template is None else template.replace('{{context}}',encoded)
            if job['stop'].is_set() or job['reason']:
                job['update'].update(state='completed',execution_state='not_started',result={'returncode':0,'stdout':'','stderr':''})
                return
            if spec['kind']=='agent' or spec.get('terminal'):
                def changed(doc):
                    with self.lock:
                        job['update']['session']=doc
                        if doc['state']=='running':job['update']['state']='running'
                def output(stream,text):
                    with self.lock:
                        events=job['update']['events'];number=job.get('event_id',0)+1;job['event_id']=number
                        events.append({'id':number,'stream':stream,'text':text[-8192:]});del events[:-64]
                session=ProcessSession(job['packet']['id'],spec,changed,output)
                session.native_id=spec.get('native_id') or session.native_id
                session.check=lambda:job['reason']
                job['session']=session
            else:session=None
            if job['stop'].is_set() or job['reason']:
                job['update'].update(state='completed',execution_state='not_started',result={'returncode':0,'stdout':'','stderr':''})
                return
            with self.lock:job['update']['state']='running'
            result=run_command(spec['command'],spec['prompt'],spec.get('timeout'),spec.get('cwd'),job['stop'],session)
            with self.lock:
                job['unsaved_result']={'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
                self.save_result(job,job['unsaved_result'])
        except Exception as exc:
            with self.lock:
                if 'unsaved_result' in job:job['update'].update(state='delivering',execution_state='completed',delivery_error=str(exc))
                else:job['update'].update(state='unknown' if isinstance(exc,CommandNotStopped) else 'failed',error=str(exc))
        finally:
            with self.lock:self.save(job)

    def close(self):
        if self.closed:return
        self.closed=True
        for job in self.jobs.values():job['stop'].set()
        self.pool.shutdown(wait=True)
        for job in list(self.jobs.values()):
            try:self.deliver(job)
            except (OSError,ValueError):pass  # Durable receipts are reconciled on an explicit next start.
        if self.nas:core.atomic_json(self.nas/'executors'/self.ident/'worker.json',dict(self.metadata(),heartbeat=0))
