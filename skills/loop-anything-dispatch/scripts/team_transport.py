"""Portable, stdlib-only team transport. No platform service or database imports."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import uuid
from urllib.parse import urlparse, unquote
_readable_spec=importlib.util.spec_from_file_location('_loop_base_readable',Path(__file__).with_name('base_readable.py'))
_readable=importlib.util.module_from_spec(_readable_spec);_readable_spec.loader.exec_module(_readable)
READABLE_FIELDS=_readable.FIELDS
readable_columns,readable_directory,readable_views=_readable.columns,_readable.directory,_readable.views

MAX_BYTES = 32 * 1024 * 1024

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
            if previous!=message:raise ValueError('Published message ID has different content')
            return  # Durable files are retained; retransmission need not rewrite every historical ACK.
    data=json.dumps(message,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(data)<=1_000_000:
        atomic_json(path,message);return
    if len(data)>32*1024*1024:raise ValueError('Communication message exceeds 32 MiB; use artifact references')
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
    if path.stat().st_size>2_000_000:raise ValueError('Invalid transport envelope size')
    message=json.loads(path.read_text())
    if isinstance(message,dict) and message.get('transport')=='snapshot-v1':
        name=message.get('file','')
        if Path(name).name!=name or not name.endswith('.blob'):raise ValueError('Invalid snapshot reference')
        target=path.with_name(name)
        if target.resolve().parent!=path.parent.resolve():raise ValueError('Snapshot reference escaped its directory')
        return read_message(target)
    if isinstance(message,dict) and message.get('transport')=='parts-v1':
        if type(message.get('parts')) is not int or not 1<=message['parts']<=64 or type(message.get('bytes')) is not int or not 0<message['bytes']<=32*1024*1024:raise ValueError('Invalid multipart envelope')
        chunks=[]
        for index in range(message['parts']):
            part=path.with_name(path.stem+'-part-'+str(index)+'.bin')
            if part.stat().st_size>524288:raise ValueError('Invalid message part size')
            chunks.append(part.read_bytes())
        data=b''.join(chunks)
        if len(data)!=message['bytes'] or hashlib.sha256(data).hexdigest()!=message.get('sha256'):raise ValueError('Incomplete or corrupted message')
        message=json.loads(data)
    return message


class Nas:
    interval = 1
    heartbeat_seconds = 5
    offline_seconds = 30
    def __init__(self, config):
        self.root = Path(config['path']).expanduser().resolve()
        self.team_id = config.get('id')
    def path(self, key):
        if not isinstance(key,str) or '\\' in key or Path(key).is_absolute() or '..' in key.split('/'):
            raise ValueError('Invalid team object path')
        path=self.root/key
        if path.resolve()!=self.root and self.root not in path.resolve().parents:
            raise ValueError('Team object escaped its directory')
        return path
    def check_identity(self):
        if self.team_id and read_message(self.path('group.json')).get('id')!=self.team_id:
            raise ValueError('Team mount identity changed; reconnect the intended team')
    def get(self, key):
        self.check_identity()
        return read_message(self.path(key))
    def put(self, key, value, immutable=False):
        self.check_identity()
        path = self.path(key)
        if immutable:
            publish_message(path, value)
        else:
            # Mutable directory/status documents are small; result snapshots may be large.
            if path.exists() and self.get(key) == value:return
            if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())<=1_000_000:
                atomic_json(path,value)
            else:
                # Parts are staged under a revision-specific basename, then the pointer switches atomically.
                rev=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                key_path=path.with_name(path.stem+'-'+rev+'.blob')
                publish_message(key_path,value)
                atomic_json(path,{'transport':'snapshot-v1','file':key_path.name})
    def list(self, bucket):
        self.check_identity()
        for path in sorted(self.path(bucket).glob('*.json')):
            try:yield path.name, read_message(self.path(bucket+'/'+path.name))
            except (OSError, ValueError):continue
    def delete(self, key):
        self.check_identity()
        path = self.path(key)
        path.unlink(missing_ok=True)
        for part in path.parent.glob(path.stem + '-part-*.bin'):part.unlink()


class Base:
    """One automatically managed table in an existing Base; lark-cli owns authentication.

    Readers expose complete revisions; large values use native attachments.
    A request has one explicit executor, so table row updates are never used as a lock.
    """
    interval = 15
    heartbeat_seconds = 60
    offline_seconds = 180
    inline_chars = 90000
    table_name = 'Loop Anything 通信'
    fields = {**READABLE_FIELDS,'key':1, 'bucket':1, 'revision':1, 'part':2, 'count':2, 'value':1, 'updated':2, 'payload':17}
    def __init__(self, config):
        self.config = config
        self.app = config['app_token']
        self.table = config.get('table_id')
        self.pending_cleanup = {}
        self.cleanup_error = None
        self._schema_ready=config.get('schema_version')==2
    def api(self, method, path, data=None, params=None):
        args = [self.config.get('lark_cli', 'lark-cli'), 'api', method, path,
                '--as', self.config.get('identity', 'user'), '--format', 'json']
        if params:args += ['--params', json.dumps(params)]
        if data is not None:args += ['--data', '-']
        for attempt in range(4):
            try:
                result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                                        text=True, capture_output=True, timeout=60)
            except subprocess.TimeoutExpired:raise ValueError('lark-cli timed out; publication may be pending, retry the same request ID')
            try:body = json.loads(result.stdout.strip() or result.stderr)
            except ValueError:raise ValueError('lark-cli returned no JSON response: ' + result.stderr[-1000:])
            code = body.get('code', 0)
            if code in (1254290, 1254291, 1254607, 99991400) and attempt < 3:
                time.sleep(.3 * 2**attempt);continue
            if result.returncode or code or body.get('error'):
                raise ValueError('Feishu Base API failed: ' + json.dumps(body, ensure_ascii=False)[:2000])
            value=body.get('data',body)
            if isinstance(value,dict) and 'code' in value:
                if value['code']:raise ValueError('Feishu Base API failed: '+json.dumps(value,ensure_ascii=False)[:2000])
                value=value.get('data',value)
            return value
    @property
    def path(self):
        return '/open-apis/bitable/v1/apps/' + self.app + '/tables'
    def pages(self, path, params=None):
        query = dict(params or {}, page_size=100)
        while True:
            data = self.api('GET', path, params=query)
            yield from data.get('items') or []
            if not data.get('has_more'):break
            token = data.get('page_token')
            if not token or token == query.get('page_token'):raise ValueError('Invalid Base pagination cursor')
            query['page_token'] = token
    def ensure(self):
        upgrading=not self._schema_ready
        tables = list(self.pages(self.path))
        if self.table:
            if not any(t['table_id'] == self.table for t in tables):raise ValueError('Configured team table no longer exists')
        else:
            matches = sorted(t['table_id'] for t in tables if t['name'] == self.table_name)
            if not matches:
                try:
                    self.api('POST', self.path, {'table':{'name':self.table_name, 'default_view_name':'通信记录',
                        'fields':[{'field_name':name, 'type':kind} for name,kind in self.fields.items()]}})
                except ValueError:
                    if not any(t['name']==self.table_name for t in self.pages(self.path)):raise
                matches = sorted(t['table_id'] for t in self.pages(self.path) if t['name'] == self.table_name)
            if len(matches) != 1:raise ValueError('Team table initialization is ambiguous; retry after resolving duplicate table names')
            self.table = matches[0]
        current = {f['field_name']:f for f in self.pages(self.path+'/'+self.table+'/fields')}
        for name,kind in self.fields.items():
            if name not in current:self.api('POST', self.path+'/'+self.table+'/fields', {'field_name':name,'type':kind})
            elif current[name]['type'] != kind:raise ValueError('Team table field type changed: '+name)
        self.config['table_id'] = self.table
        self._attachment_ready=True
        self._schema_ready=True
        self.config['schema_version']=2
        if upgrading:_readable.backfill(self)
        try:
            self.setup_views()
            self.config.pop('view_error',None)
        except (OSError,ValueError,KeyError) as exc:
            # Readable views are presentation, never a gate on valid communication.
            self.config['view_error']=str(exc)
        return self
    def setup_views(self):
        readable_views(self)
    def rows(self, field, value):
        if not self.table:self.ensure()
        # Formula values are JSON-quoted; never interpolate raw user text into a formula.
        return list(self.pages(self.path+'/'+self.table+'/records',
            {'filter':'CurrentValue.['+field+']='+json.dumps(value,ensure_ascii=False)}))
    @staticmethod
    def text(value):
        if isinstance(value,list):return ''.join(v.get('text','') for v in value)
        return value
    def shortcut(self, arguments, cwd=None):
        binary=self.config.get('lark_cli','lark-cli')
        if '/' in binary:binary=str(Path(binary).expanduser().resolve())
        args=[binary,*arguments,'--as',self.config.get('identity','user')]
        try:result=subprocess.run(args,capture_output=True,text=True,timeout=120,cwd=cwd)
        except subprocess.TimeoutExpired:raise ValueError('Feishu attachment operation timed out; retry the same request')
        try:body=json.loads(result.stdout.strip() or result.stderr)
        except ValueError:raise ValueError('lark-cli attachment operation returned no JSON: '+result.stderr[-1000:])
        if result.returncode or body.get('ok') is False or body.get('code') or body.get('error'):
            raise ValueError('Feishu attachment operation failed: '+json.dumps(body,ensure_ascii=False)[:2000])
        return body
    def upload_attachment(self, record_id, data):
        with tempfile.TemporaryDirectory(prefix='loop-base-upload-') as directory:
            path=Path(directory)/'payload.json';path.write_bytes(data)
            self.shortcut(['base','+record-upload-attachment','--base-token',self.app,'--table-id',self.table,
                           '--record-id',record_id,'--field-id','payload','--file','./payload.json'],cwd=directory)
    def download_attachment(self, token):
        cached=getattr(self,'_attachment_cache',None)
        if cached and cached[0]==token:return cached[1]
        with tempfile.TemporaryDirectory(prefix='loop-base-download-') as directory:
            path=Path(directory)/'payload.json'
            self.shortcut(['docs','+media-download','--token',token,'--output','./payload.json'],cwd=directory)
            if path.stat().st_size>MAX_BYTES:raise ValueError('Attachment exceeds the communication size limit')
            data=path.read_bytes()
        # Keep only one small attachment in memory; never accumulate a history cache.
        if len(data)<=4*1024*1024:self._attachment_cache=(token,data)
        return data
    def decode(self, rows, heartbeat=False):
        revisions = {}
        for row in rows:
            f = row['fields'];rev = self.text(f.get('revision'))
            revisions.setdefault(rev, []).append(f)
        ordered = sorted(revisions.values(), key=lambda fs:max(float(f.get('updated') or 0) for f in fs), reverse=True)
        for fields in ordered:
            chunks = {int(f['part']):self.text(f['value']) for f in fields}
            count = int(fields[0]['count'])
            if count < 1 or count > 12000 or set(chunks) != set(range(count)):continue
            data = ''.join(chunks[i] for i in range(count)).encode()
            # Old multipart rows remain readable; new large publications use native attachments.
            try:marker=json.loads(data)
            except ValueError:continue
            if isinstance(marker,dict) and marker.get('transport')=='attachment-json-v1':
                attachments=fields[0].get('payload',[])
                if count!=1 or not attachments:continue
                data=self.download_attachment(attachments[0]['file_token'])
                if len(data)!=marker['bytes'] or hashlib.sha256(data).hexdigest()!=self.text(fields[0]['revision']):
                    raise ValueError('Incomplete or corrupted communication attachment')
            if hashlib.sha256(data).hexdigest() != self.text(fields[0]['revision']):continue
            value=json.loads(data)
            if heartbeat:
                anchor=max((f for f in fields if int(f['part'])==0),key=lambda f:float(f['updated']))
                value=dict(value,updated_at=float(anchor['updated']),
                           revision='heartbeat-'+str(anchor['updated'])+'-'+self.text(anchor['revision']))
            return value
        raise FileNotFoundError('No complete object revision')
    def get(self, key):
        return self.decode(self.rows('key', key),heartbeat=key.startswith('members/'))
    def list(self, bucket):
        groups = {}
        for row in self.rows('bucket', bucket):groups.setdefault(self.text(row['fields']['key']), []).append(row)
        for key,rows in sorted(groups.items()):
            try:yield key.rsplit('/',1)[-1], self.decode(rows,heartbeat=key.startswith('members/'))
            except FileNotFoundError:continue
    def put(self, key, value, immutable=False):
        if not self._schema_ready:self.ensure()
        if key.startswith('members/') and value.get('instance_id'):
            readable_directory(self,value)
        display=readable_columns(key,value)
        heartbeat_at=value.get('updated_at') if key.startswith('members/') and not immutable else None
        if heartbeat_at is not None:value={k:v for k,v in value.items() if k not in ('updated_at','revision')}
        data=json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True)
        raw=data.encode();rev=hashlib.sha256(raw).hexdigest()
        if len(raw)>MAX_BYTES:raise ValueError('Message exceeds 32 MiB; use artifact references')
        previous=self.rows('key',key)
        current=[r for r in previous if self.text(r['fields']['revision'])==rev]
        complete=next((r for r in current if int(r['fields']['count'])==1 and int(r['fields']['part'])==0),None)
        if complete:
            if heartbeat_at is not None and float(complete['fields']['updated'])!=heartbeat_at:
                self.api('PUT',self.path+'/'+self.table+'/records/'+complete['record_id'],{'fields':{'updated':heartbeat_at,'更新时间':display['更新时间']}})
            elif not self.text(complete['fields'].get('记录类型')):
                self.api('PUT',self.path+'/'+self.table+'/records/'+complete['record_id'],{'fields':display})
            self.prune(previous, complete['record_id'])
            return
        try:old=self.decode(previous)
        except FileNotFoundError:old=None
        if old is not None and immutable and old!=value:raise ValueError('Published message ID has different content')
        now=heartbeat_at if heartbeat_at is not None else value.get('updated_at',value.get('at',value.get('created_at',time.time())))
        fields={'key':key,'bucket':key.rsplit('/',1)[0] if '/' in key else '', 'revision':rev,
                'part':0,'count':1,'value':data,'updated':now,**display}
        if len(data.encode('utf-16-le'))//2>self.inline_chars:
            if not getattr(self,'_attachment_ready',False):self.ensure()
            fields.update(count=0,value=json.dumps({'transport':'attachment-json-v1','bytes':len(raw)}))
            pending=next((r for r in current if int(r['fields']['count'])==0),None)
            if pending:record=pending
            else:record=self.api('POST',self.path+'/'+self.table+'/records',{'fields':fields},
                                 {'client_token':str(uuid.uuid4())})['record']
            if not record['fields'].get('payload'):self.upload_attachment(record['record_id'],raw)
            # Only expose the record after the attachment has been bound successfully.
            record=self.api('GET',self.path+'/'+self.table+'/records/'+record['record_id'])['record']
            attachments=record['fields'].get('payload',[])
            if not attachments:raise ValueError('Attachment binding not yet visible; retry the same request')
            self.api('PUT',self.path+'/'+self.table+'/records/'+record['record_id'],{'fields':{'count':1}})
        else:
            # A native single-record update is atomic and keeps status record IDs stable.
            record=next((r for r in previous if int(r['fields']['part'])==0),None) if not immutable else None
            if record:
                if record['fields'].get('payload'):fields['payload']=[]
                self.api('PUT',self.path+'/'+self.table+'/records/'+record['record_id'],{'fields':fields})
            else:record=self.api('POST',self.path+'/'+self.table+'/records',{'fields':fields},
                                 {'client_token':str(uuid.uuid4())})['record']
        self.prune(previous, record['record_id'])
    def prune(self, previous, keep):
        # Retain superseded revisions outside the active key/bucket; no delete permission needed.
        for row in previous:
            if row['record_id']!=keep:
                f=row['fields'];key=self.text(f['key'])
                self.pending_cleanup[row['record_id']]={'key':'versions/'+key+'/'+self.text(f['revision']),
                    'bucket':'history/'+self.text(f['bucket']),'记录类型':'历史'}
        self.pending_cleanup.pop(keep,None)
        self.retry_cleanup()
    def retry_cleanup(self):
        self.cleanup_error = None
        for record_id,fields in list(self.pending_cleanup.items()):
            try:self.api('PUT',self.path+'/'+self.table+'/records/'+record_id,{'fields':fields})
            except (OSError,ValueError) as exc:self.cleanup_error = str(exc)
            else:self.pending_cleanup.pop(record_id,None)
    def retire(self, key):
        for row in self.rows('key',key):
            bucket=self.text(row['fields']['bucket'])
            if not bucket.startswith('history/'):
                self.api('PUT',self.path+'/'+self.table+'/records/'+row['record_id'],
                         {'fields':{'bucket':'history/'+bucket}})
    def delete(self, key):
        for row in self.rows('key', key):
            self.api('DELETE', self.path+'/'+self.table+'/records/'+row['record_id'])
            self.pending_cleanup.pop(row['record_id'],None)


def connect(config):
    return Base(config) if config.get('transport') == 'feishu_base' else Nas(config)


def join(link, create=False, name=None, lark_cli='lark-cli', identity='user'):
    parsed = urlparse(link)
    if parsed.scheme in ('http','https'):
        segments = parsed.path.strip('/').split('/')
        if len(segments) < 2 or segments[0] not in ('base','wiki'):
            raise ValueError('Use the team Feishu Base link')
        config = {'transport':'feishu_base','link':link, 'app_token':segments[1],
                  'lark_cli':lark_cli,'identity':identity}
        transport = Base(config)
        if segments[0] == 'wiki':
            node = transport.api('GET','/open-apis/wiki/v2/spaces/get_node',params={'token':segments[1]})['node']
            if node['obj_type'] != 'bitable':raise ValueError('Team link must reference a Base')
            config['app_token'] = node['obj_token'];transport = Base(config)
        transport.ensure()
        # The Base token, rather than a racing manifest writer, defines the team identity.
        gid = 'team-' + hashlib.sha256(config['app_token'].encode()).hexdigest()[:32]
        return dict(config,id=gid,name=name or '团队',enabled=True)
    path = Path(unquote(parsed.path) if parsed.scheme == 'file' else link).expanduser().resolve()
    if parsed.scheme and parsed.scheme != 'file':raise ValueError('Use a Base URL or mounted NAS path')
    if create:path.mkdir(parents=True,exist_ok=True)
    manifest = path/'group.json'
    if not manifest.exists() and create:
        value = {'version':1,'id':'group-'+uuid.uuid4().hex[:12],'name':name or path.name,'description':''}
        try:
            with manifest.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False)
        except FileExistsError:pass
    group = json.loads(manifest.read_text())
    return dict(group,transport='nas',path=str(path),link=path.as_uri(),enabled=True)


def prepare_dispatch(request, instance, agent):
    """One protocol for Skill, local dispatch and Loop execution; selection precedes publication."""
    request.update(protocol='direct-v1',executor=instance,target_instance=instance,agent_id=agent,
                   assignment_id=request.get('assignment_id') or 'assignment-'+uuid.uuid4().hex[:12])
    return request


def envelope(request, kind='dispatch', payload=None):
    return {'version':1,'id':'message-'+uuid.uuid4().hex[:12],'request_id':request['id'],
        'group_id':request['group_id'],'sender':request['origin'],'target':request['executor'],
        'kind':kind,'payload':request if payload is None else payload,
        'assignment_id':request['assignment_id'],'at':time.time()}


def address(value):
    if not isinstance(value,str) or not 1<=len(value)<=100 or any(not(c.isascii() and (c.isalnum() or c in '_-')) for c in value):
        raise ValueError('Agent and machine addresses must be stable directory IDs')
    return value


def choose(agents, agent_id=None, instance_id=None, capability=None, name=None):
    if name is not None and (not isinstance(name,str) or not name.strip()):raise ValueError('Agent name must be nonempty text')
    if agent_id:address(agent_id)
    if instance_id:address(instance_id)
    matches = {(a['instance_id'],a['id']):a for a in agents
               if (not agent_id or a['id']==agent_id) and (not instance_id or a['instance_id']==instance_id)
               and (not name or a.get('name','').casefold()==name.casefold())
               and (not capability or capability in a.get('capabilities',[])) and a.get('enabled',True)}
    if len(matches)!=1:raise ValueError('Select one named Agent and machine from the team directory; matched '+str(len(matches)))
    target=next(iter(matches.values()))
    address(target['id']);address(target['instance_id'])
    return target
