"""Durable named-Agent requests. Local execution and NAS share one request lifecycle.

The source instance alone grants assignments. Group files are a trusted transport,
never a shared Run database or an instruction to schedule somebody else's Loop.
"""
import copy
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from loop_anything.runtime.model import Invalid, Conflict, contract, check_schema
from loop_anything.runtime.store import uid

END = {'completed', 'failed', 'cancelled', 'unavailable', 'not_selected'}
PRIVATE = {'access_token', 'worker_token', 'source_token', 'launch', 'pending_result', 'sender', 'rpc'}
CHILD_FIELDS=('id','origin','parent_request','kind','source','source_summary','state','message','result','error',
              'native_session','created_at','revision','agent_id','agent_label','executor','executor_name','location',
              'group_id','progress','history','notification_origin','notification_route','notification_level','notification_binding')
RPC_TOOLS = {'read_loop', 'read_task', 'read_timeline', 'read_record', 'read_plans', 'read_capabilities',
             'next_tasks', 'report_task', 'complete_task', 'finish', 'build_plan', 'change_task',
             'edit_tasks', 'notify', 'defer_task', 'change_settings', 'register_agent_session',
             'communication_status', 'request_assistance', 'read_assistance', 'wait_assistance', 'read_asset', 'read_context'}
RPC_TOOLS.update({'resolve_refs','add_task','send_event','command','resolve_request'})


def clean(value):
    if isinstance(value, dict):
        return {k: copy.deepcopy(v) if k in ('inputs','parameters','outputs','value','result','context') else clean(v)
                for k, v in value.items() if k not in PRIVATE and k != 'token'}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise Invalid('Identity must contain 1–100 letters, digits, underscores or hyphens')
    return value


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + path.name + '.' + secrets.token_hex(8))
    try:
        with temp.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def publish_message(path, message):
    if path.exists():
        try:previous=read_message(path)
        except (OSError,ValueError):pass  # A partial/corrupt publication can be repaired by its owning sender.
        else:
            if previous!=message:raise Conflict('Published message ID has different content')
            return  # Durable files are retained; retransmission need not rewrite every historical ACK.
    data=json.dumps(message,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(data)<=1_000_000:
        atomic_json(path,message);return
    if len(data)>32*1024*1024:raise Invalid('Communication message exceeds 32 MiB; use artifact references')
    parts=(len(data)+524287)//524288
    for index in range(parts):
        part=path.with_name(path.stem+'-part-'+str(index)+'.bin');part.parent.mkdir(parents=True,exist_ok=True)
        temp=part.with_name('.'+part.name+'.'+secrets.token_hex(8))
        try:
            with temp.open('xb') as out:out.write(data[index*524288:(index+1)*524288]);out.flush();os.fsync(out.fileno())
            os.replace(temp,part)
        finally:temp.unlink(missing_ok=True)
    atomic_json(path,{'transport':'parts-v1','parts':parts,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})


def read_message(path):
    if path.stat().st_size>2_000_000:raise Invalid('Invalid transport envelope size')
    message=json.loads(path.read_text())
    if isinstance(message,dict) and message.get('transport')=='parts-v1':
        if type(message.get('parts')) is not int or not 1<=message['parts']<=64 or type(message.get('bytes')) is not int or not 0<message['bytes']<=32*1024*1024:raise Invalid('Invalid multipart envelope')
        chunks=[]
        for index in range(message['parts']):
            part=path.with_name(path.stem+'-part-'+str(index)+'.bin')
            if part.stat().st_size>524288:raise Invalid('Invalid message part size')
            chunks.append(part.read_bytes())
        data=b''.join(chunks)
        if len(data)!=message['bytes'] or hashlib.sha256(data).hexdigest()!=message.get('sha256'):raise Invalid('Incomplete or corrupted message')
        message=json.loads(data)
    return message


class Communication:
    def __init__(self, store):
        self.store, self.engine = store, None
        self.lock = threading.RLock()
        self.live = {}
        self.last_scan = 0
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS communication_settings (id INTEGER PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS communication_requests (id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS communication_outbox (id TEXT PRIMARY KEY, document TEXT NOT NULL, sent REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS communication_inbox (id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS communication_peers (id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS communication_logs (request_id TEXT NOT NULL, sequence INTEGER NOT NULL, text TEXT NOT NULL, PRIMARY KEY(request_id,sequence));
                CREATE TABLE IF NOT EXISTS communication_notification_bindings (id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS communication_deliveries (id TEXT PRIMARY KEY, document TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO communication_settings VALUES (1,?)', (json.dumps({
                'instance_id': uid('machine'), 'name': socket.gethostname(), 'revision': 1, 'agents': {},
                'groups': {}, 'contexts': {}, 'loop_groups': {}, 'heartbeat_seconds': 5, 'offline_seconds': 30}),))
            db.commit()
        with self.transaction() as db:
            config=self.settings(db)
            location={'host':socket.gethostname(),'database':str(Path(store.filename).resolve())}
            self.identity_conflict=bool(config.get('identity_location') and config['identity_location']!=location)
            if not config.get('identity_location'):
                config['identity_location']=location
                db.execute('UPDATE communication_settings SET document=? WHERE id=1',(json.dumps(config),))

    @contextmanager
    def transaction(self):
        with self.lock, self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def settings(self, db=None):
        if db is None:
            with self.store.connection() as db:
                return self.settings(db)
        return json.loads(db.execute('SELECT document FROM communication_settings WHERE id=1').fetchone()[0])

    def requests(self, db=None):
        # ponytail: scan retained JSON records for small workspaces; index active requests if archives grow.
        if db is None:
            with self.store.connection() as db:
                return self.requests(db)
        return [json.loads(r[0]) for r in db.execute('SELECT document FROM communication_requests ORDER BY rowid DESC')]

    def get(self, ident, db=None):
        if db is None:
            with self.store.connection() as db:
                return self.get(ident, db)
        row = db.execute('SELECT document FROM communication_requests WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise Invalid('Unknown communication request')
        return json.loads(row[0])

    def save(self, db, request):
        request['updated_at'] = time.time()
        request['revision'] = request.get('revision',0)+1
        db.execute('INSERT INTO communication_requests VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                   (request['id'], json.dumps(request, ensure_ascii=False, allow_nan=False)))

    def event(self, request, kind, detail=None):
        request.setdefault('history', []).append({'at': time.time(), 'kind': kind, 'detail': clean(detail or {})})

    def config(self, operation, **a):
        if operation=='space':
            from loop_anything.runtime.communication_spaces import configure
            return configure(self,a)
        if operation=='group_notifications':
            from loop_anything.runtime.communication_notifications import configure
            return configure(self,a)
        if operation == 'probe':
            config=self.settings();group=config['groups'].get(a['group_id'])
            if not group:raise Invalid('Unknown group')
            root=Path(group['path'])
            if json.loads((root/'group.json').read_text()).get('id')!=group['id']:raise Invalid('Group identity changed')
            path=root/'checks'/(uid('check')+'.json');value={'instance_id':config['instance_id'],'nonce':secrets.token_hex(16)}
            try:
                atomic_json(path,value)
                if json.loads(path.read_text())!=value:raise Invalid('Shared directory read-back mismatch')
            finally:path.unlink(missing_ok=True)
            return {'read_write_verified':True,'group_id':group['id'],'multi_machine_verified':False,
                    'notice':'Only this machine read/write verified; peer visibility and actual NAS recovery need installation acceptance.'}
        with self.transaction() as db:
            config = self.settings(db)
            if a.get('revision') is not None and a['revision'] != config['revision']:
                raise Conflict('Communication configuration changed')
            if operation == 'identity':
                config['name'] = a['name']
                if a.get('regenerate'):
                    if not self.identity_conflict:raise Conflict('Identity regeneration is only for a detected copied/moved workspace')
                    config['instance_id']=uid('machine')
                    config['identity_location']={'host':socket.gethostname(),'database':str(Path(self.store.filename).resolve())}
                    self.identity_conflict=False
            elif operation == 'agent':
                from loop_anything.runtime.implementations import validate_implementation
                ident = identifier(a.get('agent_id') or uid('agent'))
                old = config['agents'].get(ident, {})
                agent = dict(old, **a['agent'], id=ident)
                if set(agent) - {'id', 'name', 'description', 'capabilities', 'local', 'enabled', 'groups', 'capacity', 'implementation'}:
                    raise Invalid('Unsupported named Agent setting')
                if not isinstance(agent.get('name'),str) or not agent['name'].strip() or not isinstance(agent.get('description', ''), str):
                    raise Invalid('Named Agent needs name and description text')
                launch = agent.get('implementation', {})
                validate_implementation(launch)
                if launch.get('kind') != 'agent' or not launch.get('command') or launch.get('dispatch'):
                    raise Invalid('Named Agent requires a local Agent command')
                if not isinstance(agent.get('capabilities', []), list) or not all(isinstance(x, str) for x in agent.get('capabilities', [])):
                    raise Invalid('capabilities must be strings')
                if not isinstance(agent.get('groups', []), list) or any(g not in config['groups'] for g in agent.get('groups', [])):
                    raise Invalid('Join groups before exposing an Agent to them')
                if type(agent.get('capacity', 1)) is not int or not 1 <= agent.get('capacity', 1) <= 8:
                    raise Invalid('Agent capacity must be 1–8')
                for key in ('enabled', 'local'):
                    if type(agent.get(key, True)) is not bool:
                        raise Invalid(key + ' must be boolean')
                config['agents'][ident] = agent
                if a['agent'].get('enabled') is True:config.get('agent_errors',{}).pop(ident,None)
            elif operation == 'group':
                relative=None
                if a.get('space_id'):
                    from loop_anything.runtime.communication_spaces import group_path
                    root,relative=group_path(config,a)
                else:root = Path(a['path']).expanduser().resolve()
                if a.get('create'):root.mkdir(parents=True, exist_ok=True)
                manifest = root / 'group.json'
                if manifest.exists():
                    from loop_anything.runtime.communication_spaces import manifest as read_manifest
                    group = read_manifest(manifest)
                    if a.get('group_id') and a['group_id']!=group['id']:
                        raise Conflict('Group identity changed; discover and select it again')
                elif a.get('create'):
                    # Exclusive manifest creation: two creators must not silently overwrite identity.
                    description=a.get('description','')
                    name=a.get('name') or root.name
                    if not isinstance(name,str) or not name.strip() or len(name)>256:raise Invalid('Group name must contain 1–256 characters')
                    if not isinstance(description,str) or len(description)>4000:raise Invalid('Group description must contain at most 4000 characters')
                    group = {'version': 1, 'id': uid('group'), 'name': name,'description':description}
                    with manifest.open('x', encoding='utf-8') as out:
                        json.dump(group, out, ensure_ascii=False)
                else:
                    raise Invalid('Group does not exist; explicitly create it first')
                config['groups'][group['id']] = dict(config['groups'].get(group['id'],{}), **group, path=str(root), enabled=True)
                if relative:config['groups'][group['id']].update(space_id=a['space_id'],relative_path=relative)
            elif operation == 'leave':
                group = config['groups'].get(a['group_id'])
                if group is None:
                    raise Invalid('Unknown group')
                group['enabled'] = False  # Keep the transport for already accepted requests and receipts.
            elif operation == 'context':
                ident = identifier(a.get('context_id') or uid('context'))
                group_id = a.get('group_id')
                if group_id and not config['groups'].get(group_id, {}).get('enabled'):
                    raise Invalid('Choose an enabled group')
                config['contexts'][ident] = {'group_id': group_id, 'label': a.get('name', '')}
            elif operation == 'bind_loop':
                if a.get('run_id'):
                    self.store.get(a['run_id'])
                elif not any(x['key'] == a.get('loop_key') for x in self.store.catalog()):
                    raise Invalid('Unknown installed Loop')
                group_id = a.get('group_id')
                if group_id and not config['groups'].get(group_id, {}).get('enabled'):
                    raise Invalid('Choose an enabled group')
                key = 'run:' + a['run_id'] if a.get('run_id') else 'loop:' + a['loop_key']
                config['loop_groups'][key] = group_id
            else:
                raise Invalid('Unknown communication configuration operation')
            config['revision'] += 1
            db.execute('UPDATE communication_settings SET document=? WHERE id=1', (json.dumps(config),))
        self.last_scan = 0
        return {'configuration': config}

    def run_group(self, run, config=None):
        config = config or self.settings()
        # The Run already snapshots its Loop default at creation; explicit null means unbound.
        return config['loop_groups'].get('run:'+run['id'],run.get('communication_group'))

    def directory(self, group_id=None):
        config = self.settings()
        rows = []
        for agent in config['agents'].values():
            if agent.get('local', True):
                rows.append(self.public_agent(agent, config, 'local'))
        with self.store.connection() as db:
            peers = [json.loads(r[0]) for r in db.execute('SELECT document FROM communication_peers')]
        for peer in peers:
            if group_id and peer['group_id'] != group_id:
                continue
            group = config['groups'].get(peer['group_id'], {})
            if not group.get('enabled'):
                continue
            for agent in peer['agents']:
                rows.append(dict(agent, group_id=peer['group_id'], location='group',
                                 online=time.time() - peer['seen_at'] < config['offline_seconds']))
        loops=[dict(ref,group_id=peer['group_id']) for peer in peers if (not group_id or peer['group_id']==group_id) and config['groups'].get(peer['group_id'],{}).get('enabled') for ref in peer.get('loops',[])]
        return {'instance_id': config['instance_id'], 'agents': rows, 'loops':loops,
                'groups': [{k: v for k, v in g.items() if k != 'path'} for g in config['groups'].values()]}

    def public_agent(self, agent, config, location):
        running = sum(r.get('executor') == config['instance_id'] and r.get('agent_id') == agent['id'] and
                      not r.get('mirror') and r['state'] in ('assigned', 'starting', 'running', 'unknown', 'cancelling') for r in self.requests())
        return {k: agent.get(k, '' if k in ('name', 'description') else []) for k in ('name', 'description', 'capabilities')} | {
            'id': agent['id'], 'instance_id': config['instance_id'], 'machine': config['name'], 'location': location,
            'online': True, 'enabled': agent.get('enabled', True), 'busy': running >= agent.get('capacity', 1),
            'error':'启动配置不可用，请由机器所有者修复并重新启用' if config.get('agent_errors',{}).get(agent['id']) else None}

    def request(self, a, node=None, continuation_from=None):
        if self.identity_conflict:raise Conflict('Copied/moved platform identity: explicitly create a new instance identity before executing')
        config = self.settings()
        source = copy.deepcopy(a.get('source') or {})
        source_summary={}
        group_id = a.get('group_id')
        if source.get('run_id'):
            from loop_anything.runtime.task_scope import owner_for, require_scope
            run = self.store.get(source['run_id'])
            owner = owner_for(run, a.get('token'))
            if not owner:
                raise Conflict('Run-linked requests need current Agent operation rights')
            require_scope(run, owner, source.get('task_id'))
            task=run['tasks'].get(source.get('task_id'),{})
            node_definition=run['loop_definition']['nodes'].get(task.get('spec',{}).get('node'),{})
            source_summary={'loop_key':run['loop_key'],'loop_name':run['loop_definition'].get('name',run['loop_key']),
                            'run_id':run['id'],'run_title':run['title'],'task_id':source.get('task_id'),
                            'node_label':node_definition.get('label',task.get('spec',{}).get('node','运行协助'))}
            bound = self.run_group(run)
            if a.get('location', 'local') == 'group':
                continuing_node=bool(node and continuation_from and continuation_from.get('kind')=='node_execution' and
                    all(continuation_from['source'].get(k)==source.get(k) for k in ('run_id','task_id')) and group_id==continuation_from.get('group_id'))
                if group_id and group_id != bound and not continuing_node:
                    raise Conflict('The request must use the Run communication group')
                if not continuing_node:group_id = bound
        elif a.get('context_id'):
            context = config['contexts'].get(a['context_id'])
            if context is None:
                raise Invalid('Unknown calling context')
            group_id = group_id or context.get('group_id')
        location = a.get('location', 'local')
        scope_group_id=bound if source.get('run_id') else group_id
        if a.get('_parent_request'):
            parent=self.get(a['_parent_request'])
            scope_group_id=parent.get('scope_group_id',parent.get('group_id'))
        if location not in ('local', 'group'):
            raise Invalid('Choose local or group')
        if location=='group' and not (a.get('agent_id') or a.get('capability')):raise Invalid('Choose a named Agent or capability for the selected group')
        if location == 'group' and group_id not in config['groups']:
            raise Invalid('Choose one joined group; requests are never broadcast across groups')
        if location=='group' and a.get('agent_id') and not a.get('instance_id'):
            instances={x['instance_id'] for x in self.directory(group_id)['agents'] if x['location']=='group' and x['id']==a['agent_id']}
            if len(instances)>1:raise Invalid('Agent ID appears on multiple instances; specify instance_id')
        schema = a.get('result_schema', {'type': 'object'})
        check_schema(schema)
        if not isinstance(a.get('message'), str) or not a['message'].strip():
            raise Invalid('A request needs instructions')
        context = a.get('context', {})
        if not isinstance(context, dict):
            raise Invalid('Context must be an object')
        encoded=json.dumps(context,ensure_ascii=False,allow_nan=False)
        credentials=[a.get('token')]
        if a.get('_parent_request'):credentials.append(self.get(a['_parent_request']).get('worker_token'))
        for credential in credentials:
            if credential:encoded=encoded.replace(credential,'[redacted]')
        context=json.loads(encoded)
        session = a.get('session', {'mode': 'new'})
        if session.get('mode') not in ('new', 'resume'):
            raise Invalid('Session mode must be new or resume')
        if session['mode'] == 'resume' and not all(session.get(k) for k in ('request_id', 'instance_id', 'native_id')):
            raise Invalid('Resume requires the exact previous request, instance and native session ID')
        deadline = a.get('wait_seconds', 300)
        if type(deadline) not in (int, float) or not 1 <= deadline <= 2592000:
            raise Invalid('Acceptance deadline must be 1–2592000 seconds')
        ident = identifier(a.get('request_id') or uid('request'))
        request = {'id': ident, 'origin': config['instance_id'], 'location': location,
                   'group_id': group_id if location == 'group' else None, 'kind': 'node_execution' if node else 'assistance',
                   'scope_group_id':scope_group_id,
                   'agent_id': a.get('agent_id'), 'target_instance':a.get('instance_id'), 'capability': a.get('capability'), 'source': source,
                   'message': a['message'], 'context': context, 'result_schema': schema, 'session': session,
                   'source_summary':source_summary,'origin_name':config['name'],
                   'state': 'pending', 'created_at': time.time(), 'deadline': time.time() + deadline,
                   'access_token': secrets.token_urlsafe(32), 'notification_origin':config['instance_id'],
                   'notification_route': a.get('notification_route', 'default' if source.get('run_id') else 'workspace'),
                   'notification_level': a.get('notification_level', 'key'), 'history': [], 'rpc': {}, 'logs': []}
        binding=config['groups'].get(scope_group_id,{}).get('notification_binding')
        if binding and 'notification_route' not in a:
            request['notification_route']='workspace'
            if binding['enabled']:request['notification_binding']=copy.deepcopy(binding)
            if 'notification_level' not in a:request['notification_level']=binding['level']
        if continuation_from is not None:
            request.update(notification_route=continuation_from['notification_route'],notification_level=continuation_from['notification_level'])
            request['scope_group_id']=continuation_from.get('scope_group_id',continuation_from.get('group_id'))
            request['source_reference']=copy.deepcopy(continuation_from['source'] or continuation_from.get('source_reference',{}))
            request['source_summary']=copy.deepcopy(continuation_from.get('source_summary',{}))
            request.pop('notification_binding',None)
            if continuation_from.get('notification_binding'):request['notification_binding']=copy.deepcopy(continuation_from['notification_binding'])
        if a.get('_parent_request'):
            request['parent_request']=a['_parent_request']
            parent=self.get(a['_parent_request'])
            request['source_reference']=parent['source'] or parent.get('source_reference',{})
            request['source_summary']=parent.get('source_summary',{})
            request['notification_origin']=parent.get('notification_origin',parent['origin'])
            request['notification_route']=parent['notification_route']
            request['notification_level']=parent['notification_level']
            request.pop('notification_binding',None)
            if parent.get('notification_binding'):request['notification_binding']=copy.deepcopy(parent['notification_binding'])
        if node:
            request['source_token'] = a['token']
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM communication_requests WHERE id=?', (ident,)).fetchone():
                old = self.get(ident, db)
                if (old['source'], old['kind'], old['message']) != (source, request['kind'], request['message']):
                    raise Conflict('Request ID already exists with different work')
                return {'request': clean(old), 'request_token': old['access_token']}
            self.event(request, 'requested')
            if location == 'local':
                candidates = [x for x in config['agents'].values() if self.eligible(x, request, config)]
                if not candidates:
                    request['state'] = 'unavailable'
                    self.event(request, 'unavailable', {'message': 'No eligible local Agent'})
                else:
                    if len(candidates) > 1 and not request.get('agent_id'):
                        raise Invalid('Choose an Agent ID from the local directory')
                    self.assign(request, config['instance_id'], candidates[0]['id'])
                    request.update(accepted_at=time.time(),launch=copy.deepcopy(candidates[0]['implementation']))
                    request.update(agent_label=candidates[0]['name'],executor_name=config['name'])
            else:
                local = next((x for x in config['agents'].values() if request.get('agent_id') and self.eligible(x,request,config)),None)
                continuation=self.continuing_wait(request,db)
                if continuation and continuation['executor']==config['instance_id']:
                    local={'id':continuation['agent_id'],'name':continuation.get('agent_label',continuation['agent_id']),'implementation':continuation['launch']}
                if not config['groups'][group_id]['enabled'] and not continuation:
                    request.update(state='unavailable',error='This platform has left the selected group')
                    self.event(request,'unavailable')
                elif local:
                    self.assign(request,config['instance_id'],local['id'])
                    request.update(accepted_at=time.time(),launch=copy.deepcopy(local['implementation']))
                    request.update(agent_label=local['name'],executor_name=config['name'])
                else:self.emit(db, request, 'broadcast', 'offer', clean(request))
            self.save(db, request)
        return {'request': clean(request), 'request_token': request['access_token']}

    def eligible(self, agent, request, config):
        return (agent.get('enabled', True) and
                (not request.get('target_instance') or request['target_instance']==config['instance_id']) and
                (not request.get('agent_id') or request['agent_id'] == agent['id']) and
                (not request.get('capability') or request['capability'] in agent.get('capabilities', [])) and
                (agent.get('local', True) if request['location'] == 'local' else
                 request['group_id'] in agent.get('groups', []) and config['groups'].get(request['group_id'], {}).get('enabled')))

    def continuing_wait(self,request,db=None):
        session=request.get('session',{})
        if request.get('kind')!='node_execution' or session.get('mode')!='resume':return None
        try:old=self.get(session['request_id'],db)
        except (Invalid,KeyError):return None
        if old['kind']!='node_execution' or old['state'] not in END:return None
        if any(old.get(k)!=request.get(k) for k in ('origin','agent_id','group_id')):return None
        if any(old['source'].get(k)!=request['source'].get(k) for k in ('run_id','task_id')):return None
        if (old.get('executor'),old.get('native_session',{}).get('id'))!=(session.get('instance_id'),session.get('native_id')):return None
        if not any(c['tool']=='wait_assistance' and c['state']=='completed' for c in old.get('rpc',{}).values()):return None
        return old

    def assign(self, request, instance, agent):
        request.update(executor=instance, agent_id=agent, assignment_id=uid('assignment'), state='assigned')
        self.event(request, 'assigned', {'agent_id': agent, 'instance_id': instance})

    def emit(self, db, request, target, kind, payload):
        config = self.settings(db)
        mid = 'ack-' + config['instance_id'] + '-' + payload['message_id'] if kind == 'ack' else uid('message')
        msg = {'version': 1, 'id': mid, 'request_id': request['id'], 'group_id': request['group_id'],
               'sender': config['instance_id'], 'target': target, 'kind': kind, 'payload': payload,
               'assignment_id': request.get('assignment_id'), 'at': time.time()}
        if len(json.dumps(msg,ensure_ascii=False).encode())>32*1024*1024:raise Invalid('Communication message exceeds 32 MiB; use artifact references')
        db.execute('INSERT OR IGNORE INTO communication_outbox(id,document) VALUES (?,?)', (msg['id'], json.dumps(msg)))
        return msg['id']

    def read(self, ident, after=0):
        if type(after) is not int or after<0:raise Invalid('Log cursor must be nonnegative')
        request = self.get(ident)
        result = clean(request)
        result['can_control']=not request.get('mirror') and request['origin']==self.settings()['instance_id']
        result['can_retry_notification']=request.get('notification_origin',request['origin'])==self.settings()['instance_id']
        if result['can_control'] and request['kind']=='node_execution':
            run=self.store.get(request['source']['run_id'])
            attempt=next(e for e in run['executions'] if e['id']==request['source']['execution_id'])
            result['business_outputs']=copy.deepcopy(attempt.get('outputs',{}))
        if self.engine and request.get('executor') == self.settings()['instance_id']:
            result['terminal'] = self.engine.terminals.read('', ident, after=after)
        else:
            with self.store.connection() as db:
                result['logs']=[dict(x) for x in db.execute('SELECT sequence,text FROM communication_logs WHERE request_id=? AND sequence>? ORDER BY sequence LIMIT 64',(ident,after))]
            result['log_cursor']=result['logs'][-1]['sequence'] if result['logs'] else after
        return {'request': result}

    def authorized(self, a, worker=False):
        try:
            row = self.get(a.get('request_id'))
            key = 'worker_token' if worker else 'access_token'
            return bool(a.get('token') and secrets.compare_digest(a['token'], row.get(key, '')))
        except (Invalid, TypeError):
            return False

    def control(self, ident, action, **a):
        if action == 'followup':
            old = self.get(ident)
            if old.get('mirror') or old['origin']!=self.settings()['instance_id']:raise Conflict('Control belongs to the request source platform')
            if old['state'] not in END:
                raise Conflict('Use input for an active interactive terminal, or wait for completion before a follow-up')
            session = {'mode': 'new'}
            if a.get('resume', True):
                native = old.get('native_session') or {}
                if not native.get('id'):
                    raise Invalid('No recorded native session; explicitly choose a new session')
                session = {'mode': 'resume', 'request_id': ident, 'instance_id': old['executor'], 'native_id': native['id']}
            return self.request(dict(location=old['location'], group_id=old.get('group_id'), agent_id=old['agent_id'], instance_id=old.get('executor'),
                                     message=a['message'], context={'previous_request': clean(old)}, session=session,
                                     notification_route=old['notification_route'],_parent_request=old.get('parent_request')),continuation_from=old)
        with self.transaction() as db:
            row = self.get(ident, db)
            owns_notice=action=='retry_notification' and row.get('notification_origin',row['origin'])==self.settings(db)['instance_id']
            if not owns_notice and (row.get('mirror') or row['origin'] != self.settings(db)['instance_id']):
                raise Conflict('Control belongs to the source platform')
            if action == 'cancel':
                if row['state'] in END | {'cancelling'} or row.get('cancel_requested'):
                    return {'request': clean(row)}
                row['cancel_requested']=True
                if row.get('assignment_id'):
                    local=row.get('executor')==self.settings(db)['instance_id']
                    if row['state']!='unknown':row['state'] = 'cancelled' if local and row['state']=='assigned' else 'cancelling'
                    if not local:
                        self.emit(db, row, row['executor'], 'cancel', {})
                else:
                    row['state'] = 'cancelled'
                    db.execute("DELETE FROM communication_outbox WHERE json_extract(document,'$.request_id')=? AND json_extract(document,'$.kind')='offer'",(row['id'],))
                self.event(row, 'cancel_requested')
            elif action == 'confirm_stopped':
                if ident in self.live or row['state'] != 'unknown' or not a.get('confirmed_stopped'):
                    raise Conflict('Explicitly verify the unknown execution is stopped first')
                if row.get('executor')!=self.settings(db)['instance_id']:
                    self.emit(db,row,row['executor'],'confirm_stopped',{})
                    self.event(row,'stop_confirmation_requested')
                else:
                    self.confirm_execution_stopped(db,row)
            elif action == 'retry_notification':
                notice=next((n for n in row.get('notifications',[]) if n['id']==a.get('notification_id')),None)
                if not notice or notice['status'] not in ('fault','waiting_configuration'):
                    raise Conflict('Choose a failed notification; verify any unknown delivery before retry')
                row['retry_notification']=notice['id']
            elif action == 'input':
                if row['state'] != 'running':
                    raise Conflict('Input requires a running interactive session')
                if row.get('executor') != self.settings(db)['instance_id']:
                    self.emit(db, row, row['executor'], 'input', {'data': a['message']})
                else:
                    self.input(row, a['message'])
            else:
                raise Invalid('Unknown request action')
            self.save(db, row)
        return {'request': clean(row)}

    def input(self, row, text):
        if not self.engine:
            raise Conflict('Execution service is not running')
        return self.engine.terminals.control('', row['id'], row['terminal_id'], data=text)

    def confirm_execution_stopped(self,db,row):
        if row['id'] in self.live or row['state']!='unknown':
            raise Conflict('Executor has not confirmed an interrupted process')
        row['state']='failed'
        self.event(row,'stop_confirmed')
        for terminal in db.execute('SELECT id,document FROM execution_sessions WHERE run_id=? AND execution_id=?',('',row['id'])).fetchall():
            doc=json.loads(terminal['document'])
            if doc['state'] in ('starting','running','interrupted'):
                doc.update(state='stopped',ended_at=time.time(),error='Old process explicitly confirmed stopped')
                db.execute('UPDATE execution_sessions SET document=? WHERE id=?',(json.dumps(doc),terminal['id']))

    def recover(self):
        with self.transaction() as db:
            for row in self.requests(db):
                for notice in row.get('notifications',[]):
                    if notice['status']=='sending':notice.update(status='fault',error='Interrupted delivery: outcome unknown; verify before retry')
                for call in row.get('rpc', {}).values():
                    if call['state'] == 'executing':
                        call.update(state='failed', error='Source interrupted during tool call; inspect its effect before retry')
                        if row['origin']==self.settings(db)['instance_id'] and row.get('executor')!=row['origin']:
                            self.emit(db,row,row['executor'],'rpc_result',call)
                if not row.get('mirror') and row.get('executor') == self.settings(db)['instance_id'] and row['state'] in ('starting', 'running', 'cancelling'):
                    row['state'] = 'unknown'
                    self.event(row, 'interrupted', {'message': 'Verify the old process before starting again'})
                self.save(db, row)
            from loop_anything.runtime.communication_notifications import recover
            recover(self,db)

    def tick(self):
        if not self.engine or self.engine.stopping.is_set() or self.identity_conflict:
            return
        if not getattr(self,'background_transport',False):self.scan()
        self.resume_dispatches()
        config = self.settings()
        for row in self.requests():
            if row.get('mirror'):continue
            if row['origin'] == config['instance_id'] and row.get('executor') not in (None,config['instance_id']) and row['state'] in ('assigned','starting','running','unknown','cancelling'):
                with self.store.connection() as db:
                    peer = db.execute('SELECT document FROM communication_peers WHERE id=?',(row['group_id']+':'+row['executor'],)).fetchone()
                online = peer and time.time()-json.loads(peer[0])['seen_at'] < config['offline_seconds']
                with self.transaction() as db:
                    current=self.get(row['id'],db)
                    if not online and current['state']!='unknown':
                        current.update(state_before_disconnect=current['state'],state='unknown')
                        self.event(current,'disconnected',{'message':'Execution state unknown; not reassigned'})
                    elif online and current.get('state_before_disconnect'):
                        current['state']=current.pop('state_before_disconnect')
                        self.event(current,'reconnected')
                    self.save(db,current)
            if row['origin'] == config['instance_id'] and row['state'] == 'pending' and row['deadline'] <= time.time():
                with self.transaction() as db:
                    current = self.get(row['id'], db)
                    if current['state'] == 'pending':
                        current['state'] = 'unavailable'
                        db.execute("DELETE FROM communication_outbox WHERE json_extract(document,'$.request_id')=? AND json_extract(document,'$.kind')='offer'",(row['id'],))
                        self.event(current, 'unavailable', {'message': 'No Agent accepted before the deadline'})
                        self.save(db, current)
            if row.get('executor') == config['instance_id'] and row['state'] == 'assigned':
                try:
                    self.launch(row['id'])
                except (Invalid,Conflict,OSError,ValueError) as exc:
                    with self.transaction() as db:
                        current=self.get(row['id'],db)
                        if current['state']=='assigned':
                            current.update(state='failed',error=str(exc))
                            self.save(db,current)
            if row.get('executor') == config['instance_id']:
                self.send_progress(row['id'])
        self.process_rpcs()
        self.reconcile_nodes()
        self.wake_assistance()
        self.deliver_notifications()
        from loop_anything.runtime.communication_notifications import deliver
        deliver(self)
        self.engine.futures.difference_update([f for f in list(self.engine.futures) if f.done()])

    def resume_dispatches(self):
        for run in self.store.list():
            if run['status'] != 'running':continue
            for e in run.get('executions',[]):
                if not e['implementation'].get('dispatch') or e['status'] != 'executing':continue
                with self.store.connection() as db:
                    present=db.execute('SELECT 1 FROM communication_requests WHERE id=?',('node-'+e['id'],)).fetchone()
                if present:continue
                try:self.submit_node(run['id'],e,run)
                except (Invalid,Conflict) as exc:
                    from loop_anything.interfaces.agent_tasks import owner_for, release_in_run
                    with self.store.edit(run['id']) as current:
                        attempt=self.engine.execution(current,e['id'])
                        self.engine.timeline_runtime.report_in_run(current,attempt,{'event':'process_error','report_id':'dispatch:'+e['id'],'detail':{'message':str(exc)}},'engine')
                        if owner_for(current,e['token']):release_in_run(current,e['token'])

    def submit_node(self, run_id, execution, snapshot):
        from loop_anything.interfaces.agent_tasks import RunTools
        tools = RunTools(self.store, run_id, execution['token'])
        info = tools.call('read_task', {'task_id': execution['task_id']})
        node = snapshot['loop_definition']['nodes'][execution['node']]
        context = {'task': clean(info), 'handbook': snapshot['loop_definition'].get('handbook', {}),
                   'inputs': execution['inputs'], 'output_contract': {k: snapshot['loop_definition']['records'][v['record_type']] for k,v in node['outputs'].items()}}
        context['scope_task']=next((o.get('scope_task') for o in snapshot['agent_sessions'] if o['token']==execution['token']),None)
        from loop_anything.packaging.packages import load_installed, resolve_skill
        document, root = load_installed(self.store.filename,snapshot['loop_key'])
        context['asset_manifest'] = list(document.get('files', {}))
        context['handbook']=resolve_skill(self.store.filename,snapshot['loop_key'],context['handbook'])
        context.update(loop_key=snapshot['loop_key'],node_id=execution['node'],parameters=execution['parameters'])
        dispatch = dict(execution['implementation']['dispatch'])
        continuation=execution.get('assistance_resume')
        previous_request=None
        session={'mode':'new'}
        if continuation:
            remote=continuation['communication']
            previous_request=self.get(remote['request_id'])
            dispatch.update(agent_id=remote['agent_id'],instance_id=remote['instance_id'],group_id=remote['group_id'])
            dispatch.pop('capability',None)
            session=dict(mode='resume',request_id=remote['request_id'],instance_id=remote['instance_id'],native_id=continuation['native_session']['id'])
        context['assistance_results']=copy.deepcopy(snapshot['tasks'][execution['task_id']].get('assistance_results',[]))
        if continuation:context['assistance_resume']={'previous_execution_id':continuation['execution_id'],'native_session':continuation['native_session']}
        result = self.request(dict(dispatch, request_id='node-' + execution['id'], message=node['instructions'],session=session,
                                   context=context, result_schema={'type':'object'},
                                   source={'run_id':run_id,'task_id':execution['task_id'],'execution_id':execution['id']},
                                   token=execution['token']), node=True,continuation_from=previous_request)
        with self.store.edit(run_id) as run:
            current = self.engine.execution(run, execution['id'])
            current['communication_id'] = result['request']['id']
            current['started_at'] = current.get('started_at') or time.time()

    def reconcile_nodes(self):
        from loop_anything.interfaces.agent_tasks import owner_for, release_in_run
        for row in self.requests():
            if row.get('mirror') or row['origin'] != self.settings()['instance_id'] or row['kind'] != 'node_execution':
                continue
            with self.store.edit(row['source']['run_id']) as run:
                e = self.engine.execution(run,row['source']['execution_id'])
                task = run['tasks'][e['task_id']]
                if row.get('native_session'):
                    e['native_session'] = dict(row['native_session'], source='communication')
                e['communication_state'] = row['state']
                if row['state'] in ('failed','unavailable','cancelled') and e['status'] not in ('completed','fault','cancelled') and task.get('execution_id') == e['id']:
                    self.engine.timeline_runtime.report_in_run(run,e,{'event':'process_error','report_id':row['id']+':'+row['state'],
                        'detail':{'message':row.get('error',row['state'])}},'engine')
                if row['state'] in ('failed','unavailable','cancelled') and owner_for(run,e['token']):release_in_run(run,e['token'])
            if (run['status'] == 'terminated' or run['status'] == 'completed' and e['status'] != 'completed' or task.get('execution_id') != e['id']) and row['state'] not in END | {'cancelling'}:
                self.control(row['id'],'cancel')

    def wait_assistance(self, run_id, token, task_id, request_ids, seconds=300):
        from loop_anything.runtime.task_scope import owner_for, require_scope
        if not isinstance(request_ids,list) or not request_ids or len(set(request_ids)) != len(request_ids):
            raise Invalid('Choose distinct requests to wait for')
        if type(seconds) not in (int,float) or not 1 <= seconds <= 2592000:
            raise Invalid('Wait deadline must be 1–2592000 seconds')
        with self.transaction() as db:
            with self.store.edit(run_id,_db=db) as run:
                owner = owner_for(run,token)
                if not owner:raise Conflict('Current Agent rights required')
                require_scope(run,owner,task_id)
                task = run['tasks'][task_id]
                e = next(e for e in run['executions'] if e['id']==task.get('execution_id'))
                if e['token'] != token or e['status'] not in ('executing','decision'):
                    raise Conflict('Only the current executing Agent may defer its task')
                for ident in request_ids:
                    request = self.get(ident,db)
                    parent=self.get(request['parent_request'],db) if request.get('parent_request') else None
                    source=parent['source'] if parent else request['source']
                    if request['kind'] != 'assistance' or source.get('run_id') != run_id or source.get('task_id') != task_id:
                        raise Conflict('Wait only for this task’s own assistance')
                continuation=self.assistance_continuation(e,db)
                task['assistance_resume']=continuation
                task.pop('assistance_resume_error',None)
                task['assistance_wait'] = {'requests':request_ids,'deadline':time.time()+seconds,'execution_id':e['id']}
                task['status'] = e['status'] = 'waiting_user'
                run.setdefault('task_dispositions',{})['task:'+task_id] = {'status':'waiting_user','reason':'等待外援回复'}
                self.store.log(run,'assistance_wait','Waiting for assistance',e['id'],{'requests':request_ids})
        return {'waiting':True,'next':'finish'}

    def assistance_continuation(self,execution,db=None):
        from loop_anything.runtime.native_sessions import resume_config,validate_identity
        result={'execution_id':execution['id'],'implementation':copy.deepcopy(execution['implementation']),
                'implementation_id':execution.get('implementation_id')}
        if execution['implementation'].get('dispatch'):
            request=self.get(execution.get('communication_id') or 'node-'+execution['id'],db)
            native=request.get('native_session')
            if not native or not request.get('resume_ready'):raise Conflict('Executor must register its native session and validate resume before waiting')
            validate_identity(native.get('provider'),native.get('id'))
            result['communication']={'request_id':request['id'],'instance_id':request['executor'],
                                     'agent_id':request['agent_id'],'group_id':request['group_id']}
        else:
            if not execution['implementation'].get('command'):
                raise Invalid('Automatic assistance waiting requires a platform-managed Agent CLI')
            native=execution.get('native_session')
            resume_config(execution['implementation'],native)
        result['native_session']=copy.deepcopy(native)
        return result

    def wake_assistance(self):
        from loop_anything.runtime.task_scope import owner_for
        for summary in self.store.list():
            run = self.store.get(summary['id'])
            if run['status'] != 'running':continue
            for task in run.get('tasks',{}).values():
                wait = task.get('assistance_wait')
                if not wait:continue
                if task['status']!='waiting_user' or task.get('execution_id')!=wait['execution_id']:continue
                replies = [self.get(i) for i in wait['requests']]
                if not all(r['state'] in END for r in replies) and time.time()<wait['deadline']:continue
                with self.store.edit(run['id']) as current:
                    t = current['tasks'][task['id']]
                    if t.get('assistance_wait') != wait or t['status']!='waiting_user' or t.get('execution_id')!=wait['execution_id']:continue
                    e = next(e for e in current['executions'] if e['id']==wait['execution_id'])
                    if e.get('worker_active') or owner_for(current,e.get('token')):continue
                    if e.get('communication_id') and self.get(e['communication_id'])['state'] not in END:continue
                    if not t.get('assistance_resume'):
                        try:t['assistance_resume']=self.assistance_continuation(e)
                        except (Invalid,Conflict) as exc:
                            if t.get('assistance_resume_error')!=str(exc):
                                t['assistance_resume_error']=str(exc)
                                current.setdefault('task_dispositions',{})['task:'+task['id']]={'status':'waiting_user','reason':'无法恢复原 session：'+str(exc)}
                                self.store.log(current,'assistance_resume_blocked',str(exc),e['id'])
                            continue
                    t['assistance_results'] = [clean(r) for r in replies]
                    t.pop('assistance_wait',None)
                    current.get('task_dispositions',{}).pop('task:'+task['id'],None)
                    t['status']='ready'
                    self.store.log(current,'assistance_ready','Assistance wait ended; continue this task',e['id'])

    def scan(self):
        if self.identity_conflict:return
        config = self.settings()
        now = time.time()
        if now - self.last_scan < .4:
            return
        self.last_scan = now
        for gid, group in config['groups'].items():
            root = Path(group['path'])
            try:
                if not root.is_dir() or json.loads((root / 'group.json').read_text()).get('id') != gid:
                    raise Invalid('Group mount missing or identity changed')
                from loop_anything.runtime.communication_notifications import refresh
                refresh(self,gid,group)
                me = root / 'members' / (config['instance_id'] + '.json')
                if not me.exists() or now - me.stat().st_mtime >= config['heartbeat_seconds']:
                    agents = [self.public_agent(a, config, 'group') for a in config['agents'].values()
                              if group['enabled'] and gid in a.get('groups', [])]
                    loops=[]
                    if group['enabled']:
                        for loop in self.store.catalog():
                            if config['loop_groups'].get('loop:'+loop['key'])==gid:
                                loops.append({'instance_id':config['instance_id'],'loop_key':loop['key'],'name':loop['loop_definition'].get('name',loop['key'])})
                        for run in self.store.list():
                            if config['loop_groups'].get('run:'+run['id'],run.get('communication_group'))==gid:
                                loops.append({'instance_id':config['instance_id'],'loop_key':run['loop_key'],'name':run['loop_definition'].get('name',run['loop_key']),'run_id':run['id'],'title':run['title']})
                    atomic_json(me, {'instance_id': config['instance_id'], 'revision': uid('heartbeat'), 'agents': agents,'loops':loops})
                for peerpath in (root / 'members').glob('*.json'):
                    try:
                        peer = json.loads(peerpath.read_text())
                        identifier(peer['instance_id'])
                        if not isinstance(peer.get('agents'),list) or not isinstance(peer.get('revision'),str):continue
                        if not isinstance(peer.get('loops',[]),list) or any(not isinstance(x,dict) for x in peer.get('loops',[])):continue
                        if any(not isinstance(a,dict) or a.get('instance_id')!=peer['instance_id'] or not isinstance(a.get('id'),str) for a in peer['agents']):continue
                    except (OSError,ValueError,KeyError,TypeError):continue
                    peerkey = gid + ':' + peer['instance_id']
                    with self.transaction() as db:
                        previous = db.execute('SELECT document FROM communication_peers WHERE id=?', (peerkey,)).fetchone()
                        old = json.loads(previous[0]) if previous else {}
                        peer.update(group_id=gid, seen_at=old.get('seen_at', now) if old.get('revision') == peer['revision'] else now)
                        db.execute('INSERT INTO communication_peers VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document', (peerkey, json.dumps(peer)))
                with self.store.connection() as db:
                    outgoing = [(r[0], json.loads(r[1])) for r in db.execute('SELECT id,document FROM communication_outbox WHERE sent<?', (now - 3,))]
                for mid, message in outgoing:
                    if message['group_id'] != gid or message['sender'] != config['instance_id']:
                        continue
                    publish_message(root / 'messages' / identifier(message['target']) / (mid + '.json'), message)
                    with self.transaction() as db:
                        db.execute('UPDATE communication_outbox SET sent=? WHERE id=?', (now, mid))
                for target in ('broadcast', config['instance_id']):
                    for file in (root / 'messages' / target).glob('*.json'):
                        try:
                            message = read_message(file)
                            if not isinstance(message,dict):continue
                        except (OSError,ValueError):continue
                        if message.get('group_id') != gid or message.get('version') != 1 or message.get('target') != target:
                            continue
                        try:
                            self.receive(message)
                        except (Invalid, Conflict, KeyError, TypeError, ValueError) as exc:
                            with self.transaction() as db:
                                inserted=db.execute('INSERT OR IGNORE INTO communication_inbox VALUES (?,?)', (message.get('id', file.stem), json.dumps({'rejected': str(exc),'message':message,'request_id':message.get('request_id'),'at':time.time()})))
                                if inserted.rowcount and message.get('kind') not in ('ack','rejected'):
                                    try:row=self.get(message['request_id'],db)
                                    except (Invalid,KeyError):row=None
                                    if row and message.get('sender') in (row['origin'],row.get('executor')) and message.get('assignment_id')==row.get('assignment_id'):
                                        self.emit(db,row,message['sender'],'rejected',{'message_id':message['id'],'error':str(exc)})
            except (OSError, ValueError, Invalid) as exc:
                self.transport_error = str(exc)

    def receive(self, msg):
        with self.transaction() as db:
            config = self.settings(db)
            if msg['sender'] == config['instance_id']:
                return
            identifier(msg['id']); identifier(msg['sender'])
            identifier(msg['request_id'])
            old = db.execute('SELECT document FROM communication_inbox WHERE id=?', (msg['id'],)).fetchone()
            if old:
                previous=json.loads(old[0])
                if previous.get('rejected') and previous.get('message')==msg:return
                if previous != msg:
                    raise Conflict('Message ID reused with different content')
                if msg['kind'] != 'ack' and msg['target'] != 'broadcast':
                    # A lost receipt must be reproducible without repeating its business effect.
                    self.emit(db, {'id':msg['request_id'],'group_id':msg['group_id'],'assignment_id':msg.get('assignment_id')},msg['sender'],'ack',{'message_id':msg['id']})
                return
            kind, payload = msg['kind'], msg['payload']
            gid = msg['group_id']
            if kind == 'ack':
                db.execute('DELETE FROM communication_outbox WHERE id=? AND json_extract(document,\'$.target\')=?', (payload['message_id'], msg['sender']))
            elif kind in ('notification_deliver','notification_receipt'):
                from loop_anything.runtime.communication_notifications import accept, receive_receipt
                if gid not in config['groups'] or msg['target']!=config['instance_id']:raise Invalid('Wrong notification group/target')
                (accept if kind=='notification_deliver' else receive_receipt)(self,db,msg)
            elif kind == 'offer':
                continuation=self.continuing_wait(payload,db)
                if not config['groups'][gid]['enabled'] and not continuation or payload['origin'] != msg['sender'] or payload['group_id'] != gid or payload['id'] != msg['request_id']:
                    raise Invalid('Invalid offer scope')
                if not db.execute('SELECT 1 FROM communication_requests WHERE id=?', (payload['id'],)).fetchone():
                    candidates = [a for a in config['agents'].values() if self.eligible(a, payload, config)]
                    if continuation and continuation['executor']==config['instance_id']:
                        candidates=[{'id':continuation['agent_id'],'name':continuation.get('agent_label',continuation['agent_id'])}]
                    if not candidates:
                        return
                    row = dict(payload, state='offered', proposed_agent=candidates[0]['id'], rpc={})
                    self.save(db, row)
                    self.emit(db, row, row['origin'], 'claim', {'agent_id': candidates[0]['id'],'agent_label':candidates[0]['name'],'executor_name':config['name']})
            else:
                row = self.get(msg['request_id'], db)
                if row['group_id'] != gid:
                    raise Invalid('Wrong request group')
                if kind == 'claim':
                    if row['origin']==config['instance_id'] and row['state']=='pending' and row.get('agent_id') and not row.get('target_instance'):
                        peers=[json.loads(r[0]) for r in db.execute('SELECT document FROM communication_peers')]
                        matches={p['instance_id'] for p in peers if p['group_id']==gid and any(a['id']==row['agent_id'] for a in p['agents'])}
                        if len(matches)>1:
                            row.update(state='unavailable',error='Agent ID is ambiguous; select an instance_id')
                            self.save(db,row)
                            db.execute("DELETE FROM communication_outbox WHERE json_extract(document,'$.request_id')=? AND json_extract(document,'$.kind')='offer'",(row['id'],))
                    if row['origin'] != config['instance_id'] or row['state'] != 'pending' or row['deadline'] < time.time():
                        if row['origin']==config['instance_id']:
                            self.emit(db,row,msg['sender'],'not_selected',{})
                            db.execute('INSERT INTO communication_inbox VALUES (?,?)',(msg['id'],json.dumps(msg)))
                            self.emit(db,row,msg['sender'],'ack',{'message_id':msg['id']})
                        return
                    if row.get('target_instance') and row['target_instance'] != msg['sender']:raise Invalid('Claim from wrong instance')
                    if row.get('agent_id') and row['agent_id'] != payload['agent_id']:
                        raise Invalid('Claim does not match requested Agent')
                    self.assign(row, msg['sender'], identifier(payload['agent_id']))
                    row.update(agent_label=payload.get('agent_label',row['agent_id']),executor_name=payload.get('executor_name',msg['sender']))
                    self.emit(db, row, msg['sender'], 'grant', {'agent_id': row['agent_id']})
                    # Stop repeatedly broadcasting an assigned offer.
                    db.execute("DELETE FROM communication_outbox WHERE json_extract(document,'$.request_id')=? AND json_extract(document,'$.kind')='offer'", (row['id'],))
                elif kind == 'grant':
                    if msg['sender'] != row['origin'] or row['state'] != 'offered' or payload['agent_id'] != row['proposed_agent']:
                        raise Conflict('Grant does not match offer')
                    row.update(state='assigned', executor=config['instance_id'], agent_id=payload['agent_id'], assignment_id=msg['assignment_id'])
                    agent=config['agents'].get(row['agent_id'])
                    continuation=self.continuing_wait(row,db)
                    if continuation and continuation['executor']==config['instance_id']:
                        row.update(accepted_at=time.time(),launch=copy.deepcopy(continuation['launch']),agent_label=continuation.get('agent_label',row['agent_id']),executor_name=config['name'])
                    elif not agent or not self.eligible(agent,row,config):
                        row.update(state='failed',error='Agent stopped accepting before the grant arrived')
                    else:row.update(accepted_at=time.time(),launch=copy.deepcopy(agent['implementation']),agent_label=agent['name'],executor_name=config['name'])
                elif kind=='not_selected' and msg['sender']==row['origin']:
                    if row['state']=='offered':row['state']='not_selected'
                else:
                    if row['state']=='offered' and msg['sender']==row['origin']:
                        return  # The grant may be later in the same directory scan.
                    if msg['assignment_id'] != row.get('assignment_id'):
                        raise Conflict('Stale or different assignment')
                    if kind=='rejected' and msg['sender'] in (row['origin'],row.get('executor')):
                        self.event(row,'communication_rejected',payload)
                        db.execute('DELETE FROM communication_outbox WHERE id=? AND json_extract(document,\'$.target\')=?',(payload['message_id'],msg['sender']))
                    elif kind in ('progress', 'rpc'):
                        if msg['sender'] != row.get('executor') or row['origin'] != config['instance_id']:
                            raise Conflict('Report is not from the assigned executor')
                        if kind == 'rpc':
                            self.import_children(db,row,payload.get('children',[]))
                            if payload.get('tool')=='wait_assistance' and payload.get('resume_ready'):
                                from loop_anything.runtime.native_sessions import validate_identity
                                native=payload['native_session'];validate_identity(native.get('provider'),native.get('id'))
                                if row.get('native_session') and any(row['native_session'].get(k)!=native.get(k) for k in ('provider','id')):raise Conflict('Native session changed before waiting')
                                row.update(native_session=native,resume_ready=True)
                            row.setdefault('rpc', {}).setdefault(payload['id'], dict(payload, state='pending'))
                        else:
                            # Logs are independently deduplicated: out-of-order status must not discard output.
                            for log in payload.get('logs',[]):
                                if type(log.get('sequence')) is not int or not isinstance(log.get('text'),str):raise Invalid('Invalid log chunk')
                                db.execute('INSERT OR IGNORE INTO communication_logs VALUES (?,?,?)',(row['id'],log['sequence'],log['text']))
                        if kind == 'progress' and payload['sequence'] > row.get('remote_sequence', 0):
                            row['remote_sequence'] = payload['sequence']
                            row['remote_state'] = payload['state']
                            self.import_children(db,row,payload.get('children',[]))
                            if row['state'] not in END:
                                if payload['state'] == 'completed':
                                    contract(payload['result'], row['result_schema'], 'Remote result')
                                row.pop('state_before_disconnect',None)
                                row.update({k: payload[k] for k in ('state', 'result', 'error', 'native_session') if k in payload})
                                if row.get('cancel_requested') and row['state'] not in END | {'unknown'}:row['state']='cancelling'
                                if payload.get('progress'):row['progress']=payload['progress']
                                self.event(row, 'remote_' + row['state'])
                    elif msg['sender'] == row['origin'] and row.get('executor') == config['instance_id']:
                        if kind == 'cancel':
                            row['cancel_requested']=True
                            if row['state'] not in END | {'unknown'}:row['state'] = 'cancelling' if row['state'] in ('starting', 'running','cancelling') else 'cancelled'
                        elif kind == 'input':
                            self.input(row, payload['data'])
                        elif kind == 'confirm_stopped':
                            self.confirm_execution_stopped(db,row)
                        elif kind == 'rpc_result':
                            row.setdefault('rpc', {})[payload['id']] = payload
                        else:
                            raise Invalid('Unknown source command')
                    else:
                        raise Invalid('Unknown message or sender')
                self.save(db, row)
            db.execute('INSERT INTO communication_inbox VALUES (?,?)', (msg['id'], json.dumps(msg)))
            if kind != 'ack' and msg['target'] != 'broadcast':
                self.emit(db, {'id': msg['request_id'], 'group_id': gid, 'assignment_id': msg.get('assignment_id')}, msg['sender'], 'ack', {'message_id': msg['id']})

    def launch(self, ident):
        if self.get(ident).get('mirror'):return
        if not self.prepare_resources(ident):
            return
        with self.transaction() as db:
            row, config = self.get(ident, db), self.settings(db)
            if row.get('mirror') or row['state'] != 'assigned' or ident in self.live:
                return
            agent = config['agents'].get(row['agent_id'])
            if config.get('agent_errors',{}).get(row['agent_id']):
                row.update(state='failed',error=config['agent_errors'][row['agent_id']]);self.save(db,row);return
            if not row.get('accepted_at') and (not agent or not self.eligible(agent, row, config)):
                row.update(state='failed', error='Agent stopped accepting this work before launch')
                self.save(db, row)
                return
            agent=agent or {'id':row['agent_id'],'capacity':1}
            busy = sum(r['id'] != ident and r.get('agent_id') == agent['id'] and r.get('executor') == config['instance_id'] and
                       not r.get('mirror') and r['state'] in ('starting', 'running', 'unknown', 'cancelling') for r in self.requests(db))
            if busy >= agent.get('capacity', 1):
                return
            row.update(state='starting', worker_token=secrets.token_urlsafe(32), launch=copy.deepcopy(row.get('launch') or agent['implementation']), terminal_id=uid('terminal'))
            if row['session']['mode'] == 'resume':
                old = self.get(row['session']['request_id'], db)
                native = old.get('native_session', {})
                if any(old.get(key)!=row.get(key) for key in ('origin','agent_id','parent_request')):
                    raise Conflict('Resume requires the same request source, named Agent and parent scope')
                if old.get('executor') != config['instance_id'] or row['session']['instance_id'] != config['instance_id'] or native.get('id') != row['session']['native_id'] or old['state'] not in END:
                    raise Conflict('The exact previous session is unavailable or still active')
                from loop_anything.runtime.native_sessions import active_native
                if active_native(db,native['provider'],native['id'],self.store):raise Conflict('This native session is active in another local execution')
                from loop_anything.runtime.native_sessions import resume_config
                row['launch']=resume_config(old.get('launch') or row['launch'],native)
                row['native_session'] = native
            elif any('{{session_id}}' in arg for arg in row['launch']['command']):
                import uuid
                from loop_anything.runtime.native_sessions import provider_for
                row['native_session']={'provider':provider_for(row['launch']) or 'custom','id':str(uuid.uuid4()),'instance_id':config['instance_id'],'cwd':row['launch'].get('cwd') or os.getcwd()}
            self.save(db, row)
            self.live[ident] = True
        self.engine.futures.add(self.engine.pool.submit(self.execute, ident))

    def execute(self,ident):
        try:self._execute(ident)
        except Exception as exc:
            with self.transaction() as db:
                row=self.get(ident,db)
                if row['state'] not in END:
                    row.update(state='unknown' if row.get('pid') else 'failed',error=str(exc))
                    self.event(row,row['state']);self.save(db,row)
        finally:self.live.pop(ident,None)

    def _execute(self, ident):
        from loop_anything.runtime.host_runtime import run_command, CommandNotStopped, CommandStartError
        from loop_anything.runtime.native_sessions import Capture, provider_for
        from loop_anything.paths import platform_skill_directory
        row = self.get(ident)
        session = self.engine.terminals.create('', ident, row['terminal_id'], row['launch'].get('terminal', False),
                                              [row['worker_token']], {'owner_type': 'communication', 'request_id': ident,'native_session':row.get('native_session')})
        session.check = lambda: 'revoked' if self.get(ident)['state'] == 'cancelling' or row['session']['mode']=='resume' and session.doc.get('native_session_error') else 'finished' if self.get(ident).get('worker_finished') else None
        def native(provider, native_id):
            with self.transaction() as db:
                current = self.get(ident, db)
                previous = current.get('native_session')
                if previous and (previous['provider'],previous['id']) != (provider,native_id):
                    raise Conflict('Native session identity changed')
                current['native_session'] = {'provider': provider, 'id': native_id, 'instance_id': self.settings(db)['instance_id'],'cwd':row['launch'].get('cwd') or os.getcwd()}
                self.save(db, current)
            session.doc['native_session']=current['native_session'];session.save()
        session.capture = Capture((row.get('native_session') or {}).get('provider') or provider_for(row['launch']), native)
        if row.get('native_session'):
            session.native_id = row['native_session']['id']
        def started():
            with self.transaction() as db:
                current = self.get(ident, db)
                if current['state'] != 'cancelling':
                    current['state'] = 'running'
                current['pid'] = session.process.pid
                self.save(db, current)
        session.on_started = started
        context = {'request_id': ident, 'token': row['worker_token'], 'message': row['message'], 'context': row['context'],
                   'source': row['source'], 'kind': row['kind'], 'result_schema': row['result_schema'],
                   'execution_url': getattr(self.engine, 'platform_url', None),
                   'client': str(platform_skill_directory() / 'scripts/communication.py')}
        base=getattr(self.engine,'platform_url','') or ''
        context['platform_url']=base+'/communication/'+ident+'/'+row['worker_token']
        context['platform_client']=str(platform_skill_directory()/'scripts/call.py')
        context['platform_guide']=str(platform_skill_directory()/'references/communication.md')
        context.update(row['source'])
        if row.get('source_reference'):context['source_reference']=row['source_reference']
        context.update({k:row['context'][k] for k in ('handbook','inputs','scope_task','loop_key','node_id','parameters','resource_root','assistance_results','assistance_resume') if k in row['context']})
        task_info=row['context'].get('task')
        if not isinstance(task_info,dict):task_info={}
        context.update({k:task_info.get(k) for k in ('skills','instructions')})
        prompt = ('You are executing a named Agent request. Use the supplied client to report progress and structured results; '
                  'When assistance_resume is present, continue the exact saved CLI session and use assistance_results. All earlier platform tokens are obsolete; use only this fresh context. '
                  'your final chat text is not a result. The client accepts --context FILE, or --url URL --request ID --token TOKEN, '
                  'then TOOL --arguments JSON. For assistance call complete with {"result":...}. For node_execution call '
                  'the source read_task/report_task/finish tools using source_call {"tool":...,"arguments":...}; '
                  'then call complete with {"result":{}} after source finish is accepted. Read source context only as authorized. '
                  'For optional help on this executor, call communication_status/request_assistance/read_assistance directly on this client. These use the executor local directory or this request group. Source calls return a call handle: only state=completed confirms acceptance; poll source_result if pending. '
                  'For a node waiting on assistance, call source wait_assistance with task_id/request_ids/seconds, then source finish and complete with an empty result. The platform continues the same Task with replies; do not keep a CLI occupied just to poll. '
                  'read_context reads associated Loop/task context without granting writes, including for assistance; it may return a pending call handle. '
                  'Use native_session to register {"provider":...,"id":...} if available.\n' + json.dumps(context, ensure_ascii=False))
        if 'prompt' in row['launch']:
            prompt=row['launch']['prompt'].replace('{{context}}',json.dumps(context,ensure_ascii=False))
        error = None
        try:
            result = run_command(row['launch']['command'], prompt, row['launch'].get('timeout'), row['launch'].get('cwd'), self.engine.stopping, session)
            if row['session']['mode']=='resume' and session.doc.get('native_session_error'):raise Invalid(session.doc['native_session_error'])
            if result.returncode and not self.get(ident).get('worker_finished'):
                raise Invalid('Agent command exited: ' + str(result.returncode))
            current = self.get(ident)
            if not current.get('worker_finished') and current['state'] != 'cancelling':
                raise Invalid('Agent exited without submitting a structured result')
        except Exception as exc:
            error = str(exc)
            uncertain = isinstance(exc, CommandNotStopped)
            if isinstance(exc,CommandStartError):
                with self.transaction() as db:
                    config=self.settings(db)
                    if row['agent_id'] in config['agents']:
                        config['agents'][row['agent_id']]['enabled']=False
                        config.setdefault('agent_errors',{})[row['agent_id']]=error
                        config['revision']+=1
                        db.execute('UPDATE communication_settings SET document=? WHERE id=1',(json.dumps(config),))
                self.last_scan=0
        else:
            uncertain = False
        finally:
            with self.transaction() as db:
                current = self.get(ident, db)
                if uncertain or self.engine.stopping.is_set() and not current.get('worker_finished'):
                    current.update(state='unknown', error=error or 'Platform stopped; verify execution')
                elif current['state'] == 'cancelling':
                    current['state'] = 'cancelled'
                elif current.get('worker_finished'):
                    current.update(state='completed', result=current.pop('pending_result'))
                else:
                    current.update(state='failed', error=error)
                self.event(current, current['state'])
                self.save(db, current)
            self.live.pop(ident, None)

    def worker_call(self, ident, token, tool, arguments):
        if not self.authorized({'request_id': ident, 'token': token}, worker=True):
            raise Conflict('Invalid execution credential')
        parent=self.get(ident)
        if tool=='read_context':
            if parent['state'] not in ('starting','running'):raise Conflict('Request is no longer executing')
            if parent.get('parent_request'):
                try:enclosing=self.get(parent['parent_request'])
                except Invalid:enclosing=None
                if enclosing and (enclosing['source'].get('run_id') or enclosing.get('source_reference',{}).get('run_id')):
                    call=self.queue_rpc(enclosing['id'],{'tool':'read_context','arguments':{}},child_id=ident)['call']
                    with self.transaction() as db:
                        current=self.get(ident,db);current.setdefault('rpc',{})[call['id']]=dict(call,forward_parent=enclosing['id'],local_forward=True,state='forwarded');self.save(db,current)
                    return {'call':call}
            if parent['source'].get('run_id') or parent.get('source_reference',{}).get('run_id'):return self.queue_rpc(ident,{'tool':'read_context','arguments':{}})
            return {'context':copy.deepcopy(parent['context'])}
        if tool in ('communication_status','request_assistance','read_assistance','control_assistance'):
            if parent['state'] not in ('starting','running'):raise Conflict('Parent request is no longer executing')
            scope_group=parent.get('scope_group_id',parent.get('group_id'))
            if tool=='communication_status':
                result=self.directory(scope_group)
                result['agents']=[x for x in result['agents'] if x['location']=='local' or x.get('group_id')==scope_group]
                result['groups']=[g for g in result['groups'] if g['id']==scope_group]
                result['loops']=[x for x in result['loops'] if x['group_id']==scope_group]
                return result
            if tool=='request_assistance':
                args=dict(arguments)
                if args.get('location','local')=='group':
                    if args.get('group_id') not in (None,scope_group) or not scope_group:
                        raise Conflict('Choose the parent request group')
                    args['group_id']=scope_group
                for key in ('source','token','context_id','request_id'):args.pop(key,None)
                args['_parent_request']=ident
                return self.request(args)
            child=self.get(arguments['request_id'])
            parents={ident};previous=parent
            while True:
                previous=self.continuing_wait(previous)
                if not previous or previous['id'] in parents:break
                parents.add(previous['id'])
            if child.get('parent_request') not in parents:raise Conflict('Read/control only your own child assistance')
            if tool=='read_assistance':return self.read(child['id'],arguments.get('after',0))
            return self.control(child['id'],arguments['action'],**{k:v for k,v in arguments.items() if k not in ('request_id','action','token')})
        if tool == 'source_call':
            return self.queue_rpc(ident, arguments)
        if tool == 'source_result':
            row = self.get(ident)
            rpc = copy.deepcopy(row.get('rpc', {}).get(arguments['id']))
            if rpc and rpc.get('local_forward'):rpc=copy.deepcopy(self.get(rpc['forward_parent'])['rpc'][arguments['id']])
            if rpc and row.get('resource_root'):
                self.localize(rpc, row['resource_root'])
            return {'call': rpc}
        with self.transaction() as db:
            row = self.get(ident, db)
            if row['state'] not in ('starting', 'running'):
                raise Conflict('Request is not executing')
            if tool == 'complete':
                if row['kind'] == 'node_execution' and not any(c['tool']=='finish' and c['state']=='completed' for c in row.get('rpc',{}).values()):
                    raise Conflict('Source finish must be accepted before completing the execution request')
                contract(arguments['result'], row['result_schema'], 'Assistance result')
                if row.get('worker_finished') and row['pending_result'] != arguments['result']:
                    raise Conflict('Result already submitted')
                row.update(worker_finished=True, pending_result=arguments['result'])
            elif tool == 'progress':
                self.event(row, 'progress', arguments)
                row['progress']=copy.deepcopy(arguments)
            elif tool == 'native_session':
                from loop_anything.runtime.native_sessions import validate_identity
                validate_identity(arguments['provider'], arguments['id'])
                if row.get('native_session') and any(row['native_session'].get(k)!=arguments[k] for k in ('provider','id')):
                    raise Conflict('Native session already recorded')
                row['native_session'] = dict(arguments, instance_id=self.settings(db)['instance_id'],cwd=row['launch'].get('cwd') or os.getcwd())
                terminal=db.execute('SELECT document FROM execution_sessions WHERE id=?',(row.get('terminal_id'),)).fetchone()
                if terminal:
                    doc=json.loads(terminal[0]);doc['native_session']=row['native_session']
                    db.execute('UPDATE execution_sessions SET document=? WHERE id=?',(json.dumps(doc),row['terminal_id']))
            else:
                raise Invalid('Unknown execution tool')
            self.save(db, row)
        return {'accepted': True}

    def queue_rpc(self, ident, arguments, child_id=None):
        if arguments.get('tool') not in RPC_TOOLS:
            raise Invalid('Tool is not available through a request')
        if arguments['tool']=='register_agent_session':
            parent=self.get(ident);a=arguments['arguments']
            if a.get('execution_id')!=parent['source'].get('execution_id'):raise Conflict('Register only the assigned execution')
            self.worker_call(ident,parent['worker_token'],'native_session',{'provider':a['provider'],'id':a['session_id']})
        with self.transaction() as db:
            row = self.get(ident, db)
            context_only=arguments['tool']=='read_context'
            if child_id and (not context_only or self.get(child_id,db).get('parent_request')!=ident):raise Conflict('Invalid child context scope')
            if row['state'] not in ('starting', 'running') and not child_id or row['kind'] != 'node_execution' and not (context_only and (row['source'].get('run_id') or row.get('source_reference',{}).get('run_id'))):
                raise Conflict('Only active node executions can operate their source Run')
            args=copy.deepcopy(arguments.get('arguments',{}))
            if args.get('run_id') not in (None,row['source'].get('run_id')):raise Conflict('Wrong source Run')
            if args.get('token') not in (None,row.get('worker_token')):raise Conflict('Wrong execution credential')
            args.pop('run_id',None);args.pop('token',None)
            call = {'id': identifier(arguments.get('id') or uid('call')), 'tool': arguments['tool'],
                    'arguments': args, 'state': 'pending'}
            if call['tool']=='wait_assistance':
                from loop_anything.runtime.native_sessions import resume_config
                resume_config(row['launch'],row.get('native_session'))
                row['resume_ready']=True
                call.update(resume_ready=True,native_session=copy.deepcopy(row['native_session']))
            call['children']=self.child_views(ident,db)
            previous = row.setdefault('rpc', {}).get(call['id'])
            if previous:
                if (previous['tool'],previous['arguments']) != (call['tool'],call['arguments']):
                    raise Conflict('Call ID already used')
                return {'call': clean(previous)}
            row['rpc'][call['id']] = call
            if row['origin'] != self.settings(db)['instance_id']:
                self.emit(db, row, row['origin'], 'rpc', call)
            self.save(db, row)
        return {'call': call}

    def scoped_tool(self,ident,token,tool,args):
        if not self.authorized({'request_id':ident,'token':token},worker=True):raise Conflict('Invalid execution credential')
        if tool=='communication_execute':
            if args.get('request_id')!=ident or args.get('token')!=token:raise Conflict('Wrong execution scope')
            return self.worker_call(ident,token,args['tool'],args['arguments'])
        if tool=='read_capabilities':
            from loop_anything.capabilities import discover
            return discover(args.get('capability'))
        if tool=='read_context':
            response=self.worker_call(ident,token,tool,args)
            if 'call' not in response:return response
            call=response['call'];deadline=time.monotonic()+20
            while call['state'] in ('pending','executing','awaiting_context') and time.monotonic()<deadline:
                time.sleep(.1);call=self.worker_call(ident,token,'source_result',{'id':call['id']})['call']
            if call['state']=='failed':raise Invalid(call['error'])
            if call['state']!='completed':return {'pending':True,'call_id':call['id'],'error':{'code':'pending','message':'Context is not confirmed; poll source_result'}}
            return call['result']
        local={'communication_status','request_assistance','read_assistance','control_assistance','complete','progress','native_session','source_result'}
        if tool in local:return self.worker_call(ident,token,tool,args)
        response=self.queue_rpc(ident,{'tool':tool,'arguments':args})
        call=response['call'];deadline=time.monotonic()+20
        while call['state'] in ('pending','executing','awaiting_context') and time.monotonic()<deadline:
            time.sleep(.1)
            call=self.get(ident)['rpc'][call['id']]
        if call['state']=='failed':raise Invalid(call['error'])
        if call['state']!='completed':return {'pending':True,'call_id':call['id'],'error':{'code':'pending','message':'Source tool not confirmed; poll source_result before proceeding'}}
        result=copy.deepcopy(call['result']);row=self.get(ident)
        if row.get('resource_root'):self.localize(result,row['resource_root'])
        return result

    def scoped_definitions(self,ident,token):
        if not self.authorized({'request_id':ident,'token':token},worker=True):raise Conflict('Invalid execution credential')
        from loop_anything.interfaces.communication_tools import definitions
        from loop_anything.interfaces.agent_tasks import RunTools
        allowed={'communication_status','request_assistance','read_assistance','control_assistance','communication_execute','read_capabilities'}
        if self.get(ident)['kind']=='node_execution':allowed.add('wait_assistance')
        result=[d for d in definitions() if d['name'] in allowed]
        result.append({'name':'read_context','description':'Read the provided context and the associated Loop/task context without acquiring write rights. No Loop is required.','inputSchema':{'type':'object','properties':{},'additionalProperties':False}})
        for definition in result:
            if definition['name']=='communication_execute':continue
            for key in ('run_id','token','source'):definition['inputSchema']['properties'].pop(key,None)
            definition['inputSchema']['required']=[k for k in definition['inputSchema'].get('required',[]) if k not in ('run_id','token','source')]
        node=self.get(ident)['kind']=='node_execution'
        result += [d for d in RunTools(self.store,'').definitions() if d['name']=='read_capabilities' or node and d['name'] in RPC_TOOLS]
        if node:
            from loop_anything.interfaces.agent_tasks import object_schema
            result += [dict(name='read_loop',description='Read this request’s source Loop definition.',inputSchema=object_schema({}),annotations={'readOnlyHint':True}),
                       dict(name='read_asset',description='Read a source Loop package asset chunk. The platform normally transfers package resources automatically.',inputSchema=object_schema({'path':{'type':'string'},'offset':{'type':'integer','minimum':0}},['path']),annotations={'readOnlyHint':True})]
        from loop_anything.capabilities import service_info
        return {'tools':result,'service':service_info(),'instructions':'This URL is scoped to the active communication request. Ordinary platform tools operate the source Run. Do not pass source credentials. Pending tool replies are not confirmation; poll source_result using the execution client. Assistance completes through communication_execute/complete.'}

    def process_rpcs(self):
        for row in self.requests():
            if row.get('mirror') or row['origin'] != self.settings()['instance_id']:
                continue
            for call in list(row.get('rpc', {}).values()):
                if call['state']=='awaiting_context':
                    forwarded=self.get(call['forward_parent'])['rpc'][call['forward_call']]
                    if forwarded['state'] not in ('completed','failed'):continue
                    answer=dict(call,state=forwarded['state'])
                    answer.pop('forward_parent',None);answer.pop('forward_call',None)
                    answer.update({k:forwarded[k] for k in ('result','error') if k in forwarded})
                    self.rpc_answer(row,call['id'],answer)
                    continue
                if call['state'] != 'pending':
                    continue
                # Write-ahead marker: an interrupted mutating call is not blindly replayed.
                with self.transaction() as db:
                    current = self.get(row['id'], db)
                    current['rpc'][call['id']]['state'] = 'executing'
                    self.save(db, current)
                try:
                    from loop_anything.interfaces.agent_tasks import RunTools
                    if (row['state'] in END or row['kind'] != 'node_execution') and call['tool']!='read_context':
                        raise Conflict('Source execution ended')
                    tool = call['tool']
                    if tool not in RPC_TOOLS:
                        raise Invalid('Unknown source tool')
                    if tool == 'read_context':
                        if not row['source'].get('run_id') and row.get('parent_request'):
                            forwarded=self.queue_rpc(row['parent_request'],{'id':'context-'+call['id'],'tool':'read_context','arguments':{}},child_id=row['id'])['call']
                            answer=dict(call,state='awaiting_context',forward_parent=row['parent_request'],forward_call=forwarded['id'])
                            with self.transaction() as db:
                                current=self.get(row['id'],db);current['rpc'][call['id']]=answer;self.save(db,current)
                            continue
                        context_source=row['source'] or row.get('source_reference',{})
                        run=self.store.get(context_source['run_id'])
                        task_id=context_source.get('task_id')
                        task=RunTools(self.store,run['id']).call('read_task',{'task_id':task_id}) if task_id else None
                        if task:
                            for skill in task.get('skills',[]):skill.pop('resolved_path',None)
                        result={'context':{'run':{k:run[k] for k in ('id','title','status')},
                                          'settings':{k:run['settings'].get(k) for k in ('objective','intent','guidance','constraints')},
                                          'loop_definition':clean(run['loop_definition']),'task':clean(task)}}
                    elif tool == 'read_asset':
                        from loop_anything.packaging.packages import load_installed, member_path
                        run = self.store.get(row['source']['run_id'])
                        document, root = load_installed(self.store.filename,run['loop_key'])
                        path = member_path(call['arguments']['path'])
                        file = (root/path).resolve()
                        if path not in document['files'] or root.resolve() not in file.parents:
                            raise Invalid('Asset is not in the source Loop package')
                        offset=call['arguments'].get('offset',0)
                        if type(offset) is not int or not 0<=offset<=file.stat().st_size:raise Invalid('Invalid asset offset')
                        with file.open('rb') as stream:
                            stream.seek(offset);chunk=stream.read(262144)
                        result = {'path':path,'offset':offset,'total':file.stat().st_size,'sha256':document['files'][path]['sha256'],'base64':base64.b64encode(chunk).decode(),'executable':document['files'][path].get('executable',False)}
                    elif tool in ('communication_status','request_assistance','read_assistance','wait_assistance'):
                        from loop_anything.interfaces.communication_tools import call as communicate
                        args = dict(call['arguments'])
                        if tool == 'request_assistance':args.update(source=row['source'],token=row['source_token'])
                        elif tool in ('communication_status','wait_assistance'):args.update(run_id=row['source']['run_id'],token=row['source_token'])
                        elif self.get(args['request_id'])['source'] != row['source'] and self.get(args['request_id']).get('parent_request')!=row['id']:raise Conflict('Read only assistance associated with this execution')
                        result = communicate(self.store,tool,args)
                    elif tool == 'read_loop':
                        run = self.store.get(row['source']['run_id'])
                        result = {'loop_definition': clean(run['loop_definition'])}
                    else:
                        result = RunTools(self.store, row['source']['run_id'], row['source_token']).call(tool, call['arguments'])
                    answer = dict(call, state='completed', result=clean(result))
                except Exception as exc:
                    answer = dict(call, state='failed', error=str(exc))
                self.rpc_answer(row,call['id'],answer)

    def rpc_answer(self,row,call_id,answer):
        with self.transaction() as db:
            current=self.get(row['id'],db)
            current['rpc'][call_id]=answer
            if current.get('executor')!=current['origin']:
                try:self.emit(db,current,current['executor'],'rpc_result',answer)
                except Invalid as exc:
                    answer={k:v for k,v in answer.items() if k!='result'}
                    answer.update(state='failed',error=str(exc));current['rpc'][call_id]=answer
                    self.emit(db,current,current['executor'],'rpc_result',answer)
            self.save(db,current)

    def send_progress(self, ident):
        row = self.get(ident)
        if row.get('executor') == row['origin'] or not row.get('assignment_id'):
            return
        terminal = self.engine.terminals.read('', ident, after=row.get('log_cursor',0))
        with self.transaction() as db:
            row = self.get(ident, db)
            payload = {k: row[k] for k in ('state', 'result', 'error', 'native_session','progress') if k in row}
            payload['children']=self.child_views(ident,db)
            payload['logs'] = terminal.get('output', [])
            row['log_cursor'] = terminal.get('cursor',row.get('log_cursor',0))
            fingerprint = json.dumps(payload, sort_keys=True)
            if row.get('last_sent') == fingerprint:
                return
            row['last_sent'] = fingerprint
            row['sequence'] = row.get('sequence', 0) + 1
            payload['sequence'] = row['sequence']
            self.emit(db, row, row['origin'], 'progress', payload)
            self.save(db, row)

    def import_children(self,db,parent,children,seen=None):
        seen=set() if seen is None else seen
        seen.add(parent['id'])
        for child in children:
            identifier(child['id'])
            if child['id'] in seen:raise Invalid('Cyclic or duplicate child request reference')
            if child.get('parent_request')!=parent['id'] or child.get('origin')!=parent['executor'] or child.get('kind')!='assistance':
                raise Invalid('Child assistance does not belong to this executor/request')
            previous=db.execute('SELECT document FROM communication_requests WHERE id=?',(child['id'],)).fetchone()
            old={}
            if previous:
                old=json.loads(previous[0])
                if old.get('parent_request')!=parent['id']:raise Conflict('Child identity already used')
            if previous and not old.get('mirror'):
                authority=old  # A returned view must never replace a locally owned request or execution.
            else:
                authority={k:copy.deepcopy(child[k]) for k in CHILD_FIELDS if k in child}
                authority.update(mirror=True,mirror_revision=child.get('revision',0),
                    notification_origin=parent.get('notification_origin',parent['origin']),
                    notification_route=parent.get('notification_route','workspace'),
                    notification_level=parent.get('notification_level','key'))
                authority.pop('notification_binding',None)
                if parent.get('notification_binding'):authority['notification_binding']=copy.deepcopy(parent['notification_binding'])
                if old.get('mirror_revision',-1)<child.get('revision',0):
                    authority.update({k:old[k] for k in ('notifications','notified_signature','retry_notification') if k in old})
                    self.save(db,authority)
                else:authority=old
            self.import_children(db,authority,child.get('children',[]),seen)

    def child_views(self,ident,db):
        children={}
        for row in self.requests(db):children.setdefault(row.get('parent_request'),[]).append(row)
        def descend(parent,seen):
            result=[]
            for row in children.get(parent,[]):
                if row['id'] in seen:raise Invalid('Cyclic child request')
                view={k:copy.deepcopy(row[k]) for k in CHILD_FIELDS if k in row}
                view['children']=descend(row['id'],seen|{row['id']});result.append(view)
            return result
        return descend(ident,{ident})

    @staticmethod
    def localize(value, root):
        if isinstance(value,dict):
            if 'resolved_path' in value:
                from loop_anything.packaging.packages import member_path
                value['resolved_path'] = str(Path(root)/member_path(value['path'])) if value.get('path') else None
            for item in value.values():Communication.localize(item,root)
        elif isinstance(value,list):
            for item in value:Communication.localize(item,root)

    def prepare_resources(self, ident):
        row=self.get(ident)
        paths=row.get('context',{}).get('asset_manifest',[]) if row['kind']=='node_execution' else []
        if not paths or row.get('resource_root'):return True
        from loop_anything.packaging.packages import member_path, file_hash
        root=Path(self.store.filename).resolve().parent/'communication-resources'/ident
        with self.transaction() as db:
            row=self.get(ident,db)
            if row['state']!='assigned':return False
            offsets=row.setdefault('asset_offsets',{});done=row.setdefault('assets_ready',[])
            for index,path in enumerate(paths):
                if path in done:continue
                offset=offsets.get(path,0);call_id='asset-'+str(index)+'-'+str(offset)
                call=row.setdefault('rpc',{}).get(call_id)
                if call is None:
                    call={'id':call_id,'tool':'read_asset','arguments':{'path':path,'offset':offset},'state':'pending'}
                    row['rpc'][call_id]=call
                    if row['origin']!=self.settings(db)['instance_id']:self.emit(db,row,row['origin'],'rpc',call)
                if call['state']=='failed':
                    row.update(state='failed',error='Resource delivery failed: '+call['error']);break
                if call['state']!='completed':continue
                asset=call['result'];file=root/member_path(asset['path']);partial=file.with_name(file.name+'.partial')
                file.parent.mkdir(parents=True,exist_ok=True)
                if file.is_symlink() or partial.is_symlink() or root.resolve() not in file.resolve().parents:raise Invalid('Resource escaped request directory')
                chunk=base64.b64decode(asset['base64'],validate=True)
                if asset['offset']!=offset or offset+len(chunk)>asset['total'] or asset['total']>20*1024*1024:raise Invalid('Invalid resource chunk')
                with partial.open('r+b' if partial.exists() else 'w+b') as out:
                    partial.chmod(0o600);out.seek(offset);out.write(chunk);out.flush();os.fsync(out.fileno())
                    if offset+len(chunk)==asset['total']:out.truncate(asset['total'])
                offsets[path]=offset+len(chunk)
                if offsets[path]==asset['total']:
                    if file_hash(partial.read_bytes())!=asset['sha256']:raise Invalid('Resource checksum mismatch')
                    os.replace(partial,file);file.chmod(0o700 if asset['executable'] else 0o600);done.append(path)
            complete=len(done)==len(paths)
            if complete:
                row['resource_root']=str(root);row['context']['resource_root']=str(root);self.localize(row['context'],root)
            self.save(db,row)
        return complete

    def deliver_notifications(self):
        from loop_anything.runtime.notifications import sender_for, NotificationConfigurationError, deliver_command
        from loop_anything.runtime.host_runtime import run_command
        from loop_anything.runtime.model import digest
        labels={'pending':'请求外援','running':'开始执行','completed':'执行完成','failed':'需要处理：执行失败',
                'unknown':'状态暂时未知','unavailable':'暂无可用成员','cancelled':'已取消'}
        for row in self.requests():
            if row.get('notification_origin',row['origin']) != self.settings()['instance_id']:continue
            state=row['state'];retry=row.get('retry_notification')
            signature=state+(':'+digest(row.get('progress',{})) if row.get('notification_level')=='detailed' else '')
            if not retry and (signature==row.get('notified_signature') or state not in labels):continue
            if not retry and row.get('notification_level')=='attention' and state not in ('failed','unknown','unavailable'):continue
            if not retry and row.get('notification_level')=='attention' and row['kind']=='assistance' and state=='unavailable':continue
            with self.transaction() as db:
                current=self.get(row['id'],db)
                if retry:
                    notice=copy.deepcopy(next(n for n in current['notifications'] if n['id']==retry))
                    current.pop('retry_notification',None)
                    notice.update(status='sending',attempt=notice.get('attempt',1)+1)
                else:
                    current['notified_signature']=signature
                    summary=row.get('source_summary',{})
                    scope=' / '.join(str(summary[k]) for k in ('loop_name','run_title','node_label') if summary.get(k)) or '独立协助'
                    actor=str(row.get('agent_label') or row.get('agent_id') or row.get('capability') or '待承接成员')
                    machine=str(row.get('executor_name') or row.get('origin_name') or '')
                    result_value=row.get('result')
                    if row['kind']=='node_execution' and state=='completed':
                        result_value=next((c['arguments'].get('envelope',{}).get('outputs') for c in reversed(list(row.get('rpc',{}).values()))
                            if c['state']=='completed' and c['tool'] in ('report_task','complete_task') and c.get('result',{}).get('accepted') and (c['tool']=='complete_task' or c['arguments'].get('event')=='completed')),result_value)
                    text=scope+'\n'+actor+' · '+machine+' · '+labels[state]+('（外援回复）' if row['kind']=='assistance' and state=='completed' else '')+'\n请求：'+row['id']
                    if not current.get('notifications'):text+='\n'+row['message'][:300]
                    if result_value:text+='\n结果摘要：'+json.dumps(result_value,ensure_ascii=False)[:600]
                    if row.get('error'):text+='\n'+str(row['error'])[:300]
                    notice={'id':uid('notice'),'state':state,'status':'sending','attempt':1,'requested_route':row['notification_route'],
                            'payload':{'request_id':row['id'],'source':row['source'],'agent_id':row.get('agent_id'),'title':summary.get('run_title','独立协助'),'run_id':summary.get('run_id'),'task_label':summary.get('node_label',''),
                            'message':text,
                            'result':result_value,'progress':row.get('progress'),'error':row.get('error')}}
                    if row.get('notification_binding'):notice['group_binding']=copy.deepcopy(row['notification_binding'])
                    current.setdefault('notifications',[]).append(notice)
                if notice.get('group_binding'):notice['status']='awaiting_delivery'
                current['notifications']=[notice if n['id']==notice['id'] else n for n in current['notifications']]
                self.save(db,current)
                if notice.get('group_binding'):
                    from loop_anything.runtime.communication_notifications import queue
                    queue(self,db,current,notice)
                    continue
            def send(ident=row['id'],notice=notice,snapshot=row):
                try:
                    if 'sender' not in notice:
                        run_id=snapshot['source'].get('run_id') or snapshot.get('source_summary',{}).get('run_id')
                        run=self.store.get(run_id) if run_id else {'settings':{}}
                        notice['route'],notice['sender']=sender_for(self.store,run,notice['requested_route'])
                    sender=notice['sender'];payload=dict(notice['payload'],id=notice['id'])
                    payload['outlet']={k:sender[k] for k in ('channel','identity','destination') if k in sender}
                    receipt={'delivered':True,'channel':'workspace'}
                    if notice['route']!='workspace':
                        receipt=deliver_command(sender,payload,run_command)
                    notice.update(status='delivered',receipt=receipt,error=None)
                except Exception as exc:
                    notice.update(status='waiting_configuration' if isinstance(exc,NotificationConfigurationError) else 'fault',error=str(exc))
                with self.transaction() as db:
                    current=self.get(ident,db)
                    current['notifications']=[notice if n['id']==notice['id'] else n for n in current['notifications']]
                    self.save(db,current)
            self.engine.futures.add(self.engine.pool.submit(send))


def service(store):
    if not hasattr(store, '_communication'):
        store._communication = Communication(store)
    return store._communication
