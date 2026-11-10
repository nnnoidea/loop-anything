"""Personal task registrations persist; running them always requires an explicit start."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import signal
import socket
import threading
import time
import uuid

from loop_anything.runtime.host_runtime import lock_database, run_command, CommandNotStopped
from loop_anything.runtime.model import Conflict
from loop_anything.runtime.scheduling import Scheduler
from loop_anything.runtime.transitions import select_transition
from loop_anything.runtime.team_transport import core

RULES=[{'from':a,'event':e,'to':b} for a,e,b in (
    ('waiting','due','checking'),('checking','ready','running'),('checking','not_ready','waiting'),
    ('running','repeat','waiting'),('running','done','completed'),
    ('checking','error','failed'),('running','error','failed'))]


def read(path, default=None):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:return default


def schedule_summary(definition):
    summary = {key: definition[key] for key in ('name', 'description', 'at', 'every', 'repeat') if key in definition}
    return dict(summary, conditional=bool(definition.get('check')), receiver=bool(definition.get('receiver')))


class TaskRegistry:
    def __init__(self, root):self.root=Path(root).expanduser().resolve()

    def path(self, ident):return self.root/core.address(ident)

    def register(self, definition, ident=None):
        if not isinstance(definition,dict) or not isinstance(definition.get('name'),str) or not definition['name'].strip():
            raise ValueError('A task needs a name')
        if set(definition)-{'name','description','every','at','check','command','stdin','cwd','timeout','repeat','agent_cli','terminal','receiver'}:
            raise ValueError('Unknown local task field')
        if bool('every' in definition)==bool('at' in definition):raise ValueError('Supply exactly one of every (seconds) or at (ISO time with timezone)')
        if 'every' in definition:
            seconds=definition['every']
            if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<=0:raise ValueError('every must be positive seconds')
        else:parse_time(definition['at'])
        receiver=definition.get('receiver')
        if receiver:
            if not isinstance(receiver,dict) or set(receiver)-{'server','name','capacity'} or not receiver.get('server'):
                raise ValueError('receiver needs server, optional name and capacity')
            if not isinstance(receiver['server'],str) or not receiver['server'].startswith(('nas://','http://','https://')):
                raise ValueError('receiver.server must be a NAS or HTTP endpoint')
            if type(receiver.get('capacity',1)) is not int or not 1<=receiver.get('capacity',1)<=8:
                raise ValueError('receiver capacity must be 1–8')
            if 'command' in definition or 'check' in definition or 'at' in definition:raise ValueError('A receiver uses an every schedule without command/check')
        for field in ('command','check'):
            if field=='command' and not receiver or field in definition:
                value=definition.get(field)
                if not isinstance(value,list) or not value or not all(isinstance(x,str) and '\0' not in x for x in value):
                    raise ValueError(field+' must be a nonempty argv list')
        if 'repeat' in definition and type(definition['repeat']) is not bool:raise ValueError('repeat must be boolean')
        if 'stdin' in definition and not isinstance(definition['stdin'],str):raise ValueError('stdin must be text')
        if 'cwd' in definition and (not isinstance(definition['cwd'],str) or '\0' in definition['cwd']):raise ValueError('cwd must be a path')
        if 'agent_cli' in definition and definition['agent_cli'] not in ('codex','claude','custom'):raise ValueError('Unknown agent_cli')
        if 'terminal' in definition and type(definition['terminal']) is not bool:raise ValueError('terminal must be boolean')
        if 'timeout' in definition and (type(definition['timeout']) not in (int,float) or not math.isfinite(definition['timeout']) or definition['timeout']<=0):raise ValueError('timeout must be positive seconds')
        ident=ident or 'schedule-'+uuid.uuid4().hex
        folder=self.path(ident);folder.mkdir(parents=True,exist_ok=True)
        with lock_database(folder/'definition'):
            previous=read(folder/'definition.json',{})
            value={'id':ident,'definition':definition,'revision':previous.get('revision',0)+1}
            core.atomic_json(folder/'definition.json',value)
        return value

    def show(self, ident):
        folder=self.path(ident);item=read(folder/'definition.json')
        if item is None:raise ValueError('Unknown registered task: '+ident)
        state=read(folder/'state.json',{'status':'registered'})
        if state.get('status') in ('waiting','checking','running') and time.time()-state.get('heartbeat',0)>30:
            state=dict(state,status='offline',notice='Last owner is offline; registration does not restart it.')
        return dict(item,runtime=state,execution=read(folder/'execution.json'))

    def confirm_stopped(self, ident, execution_id, confirmed=False):
        if not confirmed:raise ValueError('Verify the previous action stopped before confirming')
        folder=self.path(ident)
        with lock_database(folder/'execution'):
            execution=read(folder/'execution.json')
            if not execution or execution['id']!=execution_id:raise ValueError('Execution identity changed; read show again')
            execution.update(state='stopped',stop_confirmed_at=time.time())
            core.atomic_json(folder/'execution.json',execution)
        return {'id':ident,'execution':execution,'started':False}

    def list(self):
        return [self.show(p.parent.name) for p in sorted(self.root.glob('*/definition.json'))]

    def stop(self, ident, *, expected_owner=None):
        item=self.show(ident);owner=item['runtime'].get('owner')
        if expected_owner is not None and owner!=expected_owner:
            raise Conflict('Schedule execution changed; refresh before stopping it')
        if owner:core.atomic_json(self.path(ident)/'stop.json',{'owner':owner})
        return {'id':ident,'stop_requested':bool(owner),'notice':'A stop request is not confirmation that the process has exited.'}


def parse_time(value):
    from datetime import datetime
    if not isinstance(value,str):raise ValueError('at must be an ISO time with timezone')
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('at must include a timezone')
    return parsed.timestamp()


class LocalRuntime:
    def __init__(self, registry, ids, jobs=4, *, expected=None):
        self.registry=registry;self.stop=threading.Event();self.items={};self.locks=[]
        self.pool=ThreadPoolExecutor(max_workers=jobs)
        self.scheduler=Scheduler(self.stop)
        self.last_control=0
        try:
            for ident in dict.fromkeys(ids):
                registry.show(ident);folder=registry.path(ident)
                self.locks.append(lock_database(folder/'execution'))
                item=registry.show(ident)
                if expected is not None and expected[ident]!=(item['revision'],item['runtime'].get('owner')):
                    raise Conflict('Schedule definition or execution changed; refresh before starting it')
                execution=read(folder/'execution.json')
                if execution and execution.get('state') not in ('exited','error','stopped'):
                    raise CommandNotStopped('Previous action may still be running: '+execution['id']+'. Inspect show; confirm-stopped that exact execution only after verifying its process stopped.')
                definition=item['definition'];now=time.time()
                state={'id':ident,'owner':uuid.uuid4().hex,'machine':socket.gethostname(),
                    'status':'waiting','started_at':now,'heartbeat':now,'definition_revision':item['revision'],
                    'schedule':schedule_summary(definition),
                    'next_at':parse_time(definition['at']) if 'at' in definition else now+(0 if definition.get('check') or definition.get('receiver') else definition['every'])}
                if item['runtime'].get('last_result'):state['last_result']=item['runtime']['last_result']
                self.items[ident]={'definition':definition,'state':state,'future':None,'stop':threading.Event()}
                self.save(ident)
            self.scheduler.add(self.tick,.2,immediate=True)
            self.scheduler.add(self.heartbeat,5)
        except BaseException:self.close();raise

    def save(self, ident):core.atomic_json(self.registry.path(ident)/'state.json',self.items[ident]['state'])

    def move(self, item, event):
        state=item['state'];decision=select_transition(RULES,state['status'],event)
        if decision['issue']:raise ValueError(decision['issue'])
        state['status']=decision['rule']['to']

    def heartbeat(self):
        for ident,item in self.items.items():
            if item['state']['status'] in ('waiting','checking','running'):
                item['state']['heartbeat']=time.time();self.save(ident)

    def stop_requested(self, ident, item):
        event = item['stop']
        if not event.is_set():
            request = read(self.registry.path(ident)/'stop.json', {})
            if request.get('owner') == item['state']['owner']:
                event.set()
        return event.is_set()

    def tick(self):
        active=False
        inspect_controls=time.monotonic()-self.last_control>=1
        if inspect_controls:self.last_control=time.monotonic()
        for ident,item in self.items.items():
            state=item['state']
            idle=not item['future'] or item['future'].done()
            due=idle and state['status']=='waiting' and time.time()>=state['next_at']
            if inspect_controls or due:self.stop_requested(ident,item)
            if item['stop'].is_set() and state['status']!='stopped' and idle:
                if item.get('receiver'):item['receiver'].close()
                state.update(status='stopped',next_at=None);self.save(ident)
            if state['status'] not in ('waiting','checking','running'):continue
            active=True
            if due:
                self.move(item,'due');self.save(ident)
                item['future']=self.pool.submit(self.execute,ident)
        if not active:self.stop.set()

    def execute(self, ident):
        item=self.items[ident];definition=item['definition'];state=item['state'];event=item['stop']
        session=None
        try:
            if self.stop_requested(ident,item):return
            if definition.get('receiver'):
                from loop_anything.runtime.executor_client import Receiver
                if 'receiver' not in item:item['receiver']=Receiver(definition['receiver'],self.registry.path(ident))
                state['executor_id']=item['receiver'].ident
                item['receiver'].tick()
                state.pop('error',None)
                self.move(item,'not_ready')
            else:
                if definition.get('check'):
                    checked,_=self.run_action(ident,checking=True)
                    if checked.returncode==1:
                        self.move(item,'not_ready');return
                    if checked.returncode:raise ValueError('Condition check failed: '+checked.stderr[-2000:])
                self.move(item,'ready');state['last_started_at']=time.time();self.save(ident)
                if self.stop_requested(ident,item):return
                result,session=self.run_action(ident)
                state['last_result']={'returncode':result.returncode,'at':time.time(),
                    'native_session':session.doc.get('native_session'),
                    **({} if session.doc.get('output_source')=='native_session' else {'stdout':result.stdout[-8192:],'stderr':result.stderr[-8192:]})}
                if result.returncode:raise ValueError('Command exited with code '+str(result.returncode))
                repeat=definition.get('repeat','every' in definition and not definition.get('check'))
                self.move(item,'repeat' if repeat and 'every' in definition else 'done')
        except Exception as exc:
            # Connection failures must not kill the receiver or its active processes.
            # The registration stays visible with an error and retries on its next due time.
            if definition.get('receiver'):self.move(item,'not_ready')
            elif isinstance(exc,CommandNotStopped):state['status']='unknown'
            elif state['status'] in ('checking','running'):self.move(item,'error')
            state['error']=str(exc)
            if session:
                state['last_result']={'at':time.time(),'returncode':session.doc.get('returncode'),
                    'native_session':session.doc.get('native_session'),'output_tail':session.output_tail,'error':str(exc)}
        finally:
            if event.is_set() and state['status']!='unknown':
                if item.get('receiver'):item['receiver'].close()
                state['status']='stopped'
            state['next_at']=time.time()+definition.get('every',1) if state['status']=='waiting' else None
            state['heartbeat']=time.time();self.save(ident)

    def run_action(self, ident, checking=False):
        from loop_anything.runtime.process_session import ProcessSession
        item=self.items[ident];definition=item['definition'];state=item['state']
        path=self.registry.path(ident)/'execution.json'
        execution={'id':'action-'+uuid.uuid4().hex,'owner':state['owner'],'machine':socket.gethostname(),
                   'state':'starting','phase':'check' if checking else 'action','started_at':time.time()}
        # Persist intent before Popen; a crash in the launch window must not imply no execution.
        core.atomic_json(path,execution)
        def changed(doc):
            execution.update({k:doc[k] for k in ('state','pid','native_session','returncode','ended_at','error') if k in doc})
            if doc.get('pid'):execution['process_group']=doc['pid']
            core.atomic_json(path,execution)
        session=ProcessSession(execution['id'],{} if checking else definition,changed)
        result=run_command(definition['check' if checking else 'command'],definition.get('stdin',''),
            definition.get('timeout',60 if checking else None),definition.get('cwd'),item['stop'],session)
        return result,session

    def run(self):
        try:self.scheduler.run()
        finally:self.close()

    def close(self):
        self.stop.set()
        for item in self.items.values():
            item['stop'].set()
        self.pool.shutdown(wait=True)
        for item in self.items.values():
            if item.get('receiver'):item['receiver'].close()
        for ident,item in self.items.items():
            if item['state']['status'] in ('waiting','checking','running'):
                item['state'].update(status='stopped',next_at=None);self.save(ident)
        for lock in self.locks:lock.close()
        self.locks=[]


def main(argv):
    parser=argparse.ArgumentParser(description='Standalone personal scheduling. Register/list never start tasks.')
    parser.add_argument('--root',required=True,help='Personal registration directory; use a NAS path to retain history across machines')
    sub=parser.add_subparsers(dest='action',required=True)
    register=sub.add_parser('register');register.add_argument('definition');register.add_argument('--id')
    sub.add_parser('list')
    for name in ('show','stop'):
        sub.add_parser(name).add_argument('id')
    confirm=sub.add_parser('confirm-stopped');confirm.add_argument('id');confirm.add_argument('--execution-id',required=True)
    confirm.add_argument('--confirmed-stopped',action='store_true')
    start=sub.add_parser('start');start.add_argument('ids',nargs='+');start.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args(argv);registry=TaskRegistry(args.root)
    if args.action=='register':result=registry.register(read(Path(args.definition)),args.id)
    elif args.action=='list':result=registry.list()
    elif args.action=='show':result=registry.show(args.id)
    elif args.action=='stop':result=registry.stop(args.id)
    elif args.action=='confirm-stopped':result=registry.confirm_stopped(args.id,args.execution_id,args.confirmed_stopped)
    else:
        if not 1<=args.jobs<=32:parser.error('--jobs must be 1–32')
        runtime=LocalRuntime(registry,args.ids,args.jobs)
        previous=signal.signal(signal.SIGTERM,lambda *_:runtime.stop.set())
        try:runtime.run()
        except KeyboardInterrupt:runtime.close()
        finally:signal.signal(signal.SIGTERM,previous)
        result=registry.list()
    print(json.dumps(result,ensure_ascii=False,indent=2))
