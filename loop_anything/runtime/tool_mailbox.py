"""One service applies NAS tool requests; clients never open its SQLite database."""
import json
from pathlib import Path
import platform
import traceback
import uuid
from loop_anything.runtime.team_transport import core
from loop_anything.capabilities import service_info


class ToolMailbox:
    def __init__(self, store, root, engine):
        self.store,self.root,self.engine=store,Path(root).resolve(),engine
        self.protection=None
        self.root.mkdir(parents=True,exist_ok=True)
        path=self.root/'team.json'
        if not path.exists():core.atomic_json(path,{'version':1,'id':'service-'+uuid.uuid4().hex})
        manifest=json.loads(path.read_text());self.ident=manifest['id']
        manifest['roots']=list(dict.fromkeys([*manifest.get('roots',[]),str(Path(root).absolute()),str(self.root)]))
        core.atomic_json(path,manifest)
        engine.team_roots=manifest['roots'];engine.team_root=str(self.root)
        for part in ('requests','replies','history','rejected'):(self.root/'api'/part).mkdir(parents=True,exist_ok=True)
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tool_requests (id TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT)')
            # A process can stop after a tool commits but before its receipt is saved.
            # Never replay such a mutation automatically.
            unknown=json.dumps({'ok':False,'outcome_unknown':True,'error':{'code':'interrupted_request',
                'message':'Service stopped during this request. Inspect the target before deciding whether to issue another operation.'}})
            db.execute('UPDATE tool_requests SET response=? WHERE response IS NULL',(unknown,));db.commit()

    def dispatch(self, packet):
        from loop_anything.interfaces.platform_tools import PlatformTools
        name,args,scope=packet['tool'],packet['arguments'],packet.get('scope',[])
        if packet.get('client_root') and name=='set_implementation' and 'cwd' in args:
            from loop_anything.runtime.tool_client import module
            args=dict(args,cwd=module('platform_transport').mount_path(args['cwd'],[packet['client_root']],str(self.root)))
        tools=PlatformTools(self.store)
        if scope:
            if len(scope)!=3 or scope[0]!='communication':raise ValueError('Unknown scoped request')
            if name=='_list':return self.engine.communication.scoped_definitions(scope[1],scope[2])
            if name!='_platform':
                result=self.engine.communication.scoped_tool(scope[1],scope[2],name,args)
                return dict(result,ok=not bool(result.get('pending')))
            if not self.engine.communication.authorized({'request_id':scope[1],'token':scope[2]},worker=True):raise ValueError('Invalid execution identity')
        if name=='_platform':
            power=self.protection.status() if self.protection else {'requested':False,'active':False}
            database=str(Path(packet.get('client_root') or self.root)/Path(self.store.filename).name)
            return {'service':service_info(),'system':platform.system(),'database':database,'keep_awake':power}
        if name=='_list':return {'ok':True,'service':service_info(),'instructions':tools.instructions,'tools':tools.definitions()}
        return tools.respond(name,args)

    def tick(self):
        for path in sorted((self.root/'api/requests').glob('*.json'))[:32]:
            try:self.process(path)
            except Exception:traceback.print_exc()  # One unavailable file must not stop unrelated requests.

    def process(self, path):
        try:
            packet=core.read_message(path);ident=core.address(path.stem)
            if not isinstance(packet,dict) or packet.get('id')!=ident or packet.get('team_id')!=self.ident:
                raise ValueError('Request does not belong to this service and request ID')
            if not isinstance(packet.get('tool'),str) or not isinstance(packet.get('arguments'),dict):
                raise ValueError('A request needs a tool name and arguments object')
        except ValueError as exc:
            self.reject(path,str(exc));return
        encoded=json.dumps(packet,sort_keys=True,ensure_ascii=False)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT request,response FROM tool_requests WHERE id=?',(ident,)).fetchone()
            if row and row[0]!=encoded:
                db.rollback();self.reject(path,'Request ID already belongs to another operation');return
            if row:answer=json.loads(row[1]) if row[1] else {'ok':True,'pending':True,'request_id':ident}
            else:
                db.execute('INSERT INTO tool_requests VALUES (?,?,NULL)',(ident,encoded));db.commit()
                try:answer=self.dispatch(packet)
                except Exception as exc:answer={'ok':False,'error':{'code':'tool_error','message':str(exc)}}
                db.execute('UPDATE tool_requests SET response=? WHERE id=?',(json.dumps(answer,ensure_ascii=False),ident))
            db.commit()
        core.publish_message(self.root/'api/history'/path.name,packet)
        core.publish_message(self.root/'api/replies'/path.name,answer)
        path.unlink(missing_ok=True)

    def reject(self, path, reason):
        # Keep the original receipt authoritative; malformed/conflicting input is inspectable separately.
        path.replace(self.root/'api/rejected'/path.name)
        core.atomic_json(self.root/'api/rejected'/(path.stem+'.error.json'),{'ok':False,'error':reason})
