"""Standalone client, receiver admission and shared media contracts."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from loop_anything.runtime.engine import Engine
from loop_anything.runtime.store import Store
from loop_anything.runtime.team_transport import core

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/loop-anything-dispatch/scripts'
sys.path.insert(0,str(SCRIPTS))
from dispatch import Client


class DispatchTests(unittest.TestCase):
    def test_client_exits_receiver_finishes_and_duplicate_cannot_execute_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);e=Engine(Store(root/'receiver.sqlite3'));comm=e.communication
            self.addCleanup(e.close)
            team=comm.config('team',link=str(root/'nas'),create=True)['team']
            comm.config('agent',agent_id='papers',task_confirmed=True,agent={'name':'论文','description':'查论文','groups':[team['id']],
                'implementation':{'kind':'agent','command':[sys.executable,'-c','pass']}})
            client=Client(root/'client');client.configure(str(root/'nas'))
            created=client.submit({'agent_id':'papers','message':'Return complete evidence','request_id':'request-portable'})
            packet=client.request_record('request-portable')
            calls=[]
            def worker(command,prompt,*a,**k):
                info=json.loads(prompt.split('\n',1)[1]);calls.append(info['request_id'])
                comm.worker_call(info['request_id'],info['token'],'read_context',{})
                comm.worker_call(info['request_id'],info['token'],'complete',{'result':{'evidence':'完整结果'*5000}})
                return subprocess.CompletedProcess(command,0,'','')
            with patch('loop_anything.runtime.host_runtime.run_command',side_effect=worker):
                until=time.monotonic()+8
                while time.monotonic()<until:
                    comm.last_scan=0;comm.tick()
                    if client.read('request-portable')['state']=='completed':break
                    time.sleep(.02)
                self.assertEqual(client.read('request-portable')['result']['evidence'],'完整结果'*5000)
                comm.receive(packet);comm.last_scan=0;comm.tick()
                self.assertEqual(calls,['request-portable'])
                row=comm.get('request-portable')
                self.assertIn('collaboration',row)
                self.assertTrue(any(c['state']=='completed' for c in row['rpc'].values()),row['rpc'])
                self.assertEqual(len(comm.store.list()),1)
                self.assertFalse(list((root/'nas/messages'/row['executor']).glob('*.json')))
                mutated=json.loads(json.dumps(packet));mutated['payload']['message']='different'
                with self.assertRaises(ValueError):comm.receive(mutated)
            # A fresh process imports only the Skill, with no installed platform on sys.path.
            result=subprocess.run([sys.executable,str(SCRIPTS/'dispatch.py'),'read','--config-dir',str(root/'client'),
                '--arguments','{"request_id":"request-portable"}'],cwd=folder,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)['request']['state'],'completed')

    def test_expired_dispatch_never_starts_and_cancel_before_tick(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);e=Engine(Store(root/'r.db'));self.addCleanup(e.close);comm=e.communication
            gid=comm.config('team',link=str(root/'nas'),create=True)['team']['id']
            comm.config('agent',agent_id='a',task_confirmed=True,agent={'name':'A','description':'帮助','groups':[gid],
                'implementation':{'kind':'agent','command':[sys.executable,'-c','pass']}})
            c=Client(root/'client');c.configure(str(root/'nas'));r=c.submit({'agent_id':'a','message':'help'})['request']
            c.control({'request_id':r['id'],'action':'cancel'})
            comm.last_scan=0;comm.scan()
            self.assertEqual(comm.get(r['id'])['state'],'cancelled')
            self.assertFalse(comm.live)

    def test_cancel_arriving_before_dispatch_is_not_discarded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);engine=Engine(Store(root/'receiver.db'));self.addCleanup(engine.close);comm=engine.communication
            team=comm.config('team',link=str(root/'nas'),create=True)['team']
            comm.config('agent',agent_id='a',task_confirmed=True,agent={'name':'A','description':'Help','groups':[team['id']],
                'implementation':{'kind':'agent','command':[sys.executable,'-c','pass']}})
            client=Client(root/'client');client.configure(str(root/'nas'))
            request=client.submit({'agent_id':'a','message':'help'})['request']
            packet=client.request_record(request['id'])
            cancel=core.envelope(packet['payload'],'cancel',{'reason':'withdrawn'})
            comm.receive(cancel)
            comm.receive(packet)
            comm.receive(cancel)
            self.assertEqual(comm.get(request['id'])['state'],'cancelled')
            self.assertFalse(comm.live)

    def test_default_team_is_snapshotted_but_explicit_unbinding_is_preserved(self):
        from loop_anything.runtime.collaboration import ensure_loop
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);engine=Engine(Store(root/'r.db'));self.addCleanup(engine.close);comm=engine.communication
            first=comm.config('team',link=str(root/'one'),create=True)['team']['id']
            key=ensure_loop(comm.store)
            run=comm.store.create(key,'One',{'message':'one'},authorization='test')
            self.assertEqual(comm.run_group(run),first)
            comm.config('team',link=str(root/'two'),create=True)
            self.assertEqual(comm.run_group(comm.store.get(run['id'])),first)
            comm.config('bind_loop',loop_key=key,group_id=None)
            unbound=comm.store.create(key,'Two',{'message':'two'},authorization='test')
            self.assertIsNone(comm.run_group(unbound))


class FakeBase(core.Base):
    """Official v1 API shape, paging, rich text cells and idempotent record creation."""
    def __init__(self):
        super().__init__({'app_token':'base-test','transport':'feishu_base'})
        self.tables=[];self.records={};self.tokens={};self.token_bodies={};self.counter=0;self.files={}
    def setup_views(self):
        pass
    def api(self,method,path,data=None,params=None):
        if path.endswith('/tables'):
            if method=='POST':
                self.tables.append({'table_id':'tbl-test','name':data['table']['name']})
                return {'table_id':'tbl-test'}
            return {'items':self.tables,'has_more':False}
        if path.endswith('/fields'):return {'items':[{'field_name':n,'type':t} for n,t in self.fields.items()]}
        if method=='GET' and '/records/rec' in path:return {'record':self.records[path.rsplit('/',1)[1]]}
        if method=='DELETE':self.records.pop(path.rsplit('/',1)[1],None);return {}
        if method=='PUT':
            row=self.records[path.rsplit('/',1)[1]];row['fields'].update(data['fields'])
            return {'record':row}
        if method=='POST':
            token=params['client_token']
            if token in self.token_bodies and self.token_bodies[token]!=data:raise ValueError('1255006 client token conflict')
            self.token_bodies[token]=data
            if token not in self.tokens:
                self.counter+=1;rid='rec'+str(self.counter);self.tokens[token]=rid
                fields=dict(data['fields']);fields['value']=[{'type':'text','text':fields['value']}]
                self.records[rid]={'record_id':rid,'fields':fields}
            return {'record':self.records.get(self.tokens[token],{})}
        if params and params.get('filter'):
            expression=params['filter'];field=expression.split('[')[1].split(']')[0];value=json.loads(expression.split('=',1)[1])
            rows=[r for r in self.records.values() if r['fields'].get(field)==value]
        else:rows=list(self.records.values())
        params=params or {}
        offset=int(params.get('page_token',0));end=offset+2
        return {'items':rows[offset:end],'has_more':end<len(rows),'page_token':str(end)}

    def upload_attachment(self, record_id, data):
        token='file-'+record_id;self.files[token]=data
        self.records[record_id]['fields']['payload']=[{'file_token':token}]
    def download_attachment(self, token):
        return self.files[token]


class BaseTests(unittest.TestCase):
    def test_real_numeric_cells_can_be_strings(self):
        media=FakeBase().ensure()
        key='members/worker.json'
        media.put(key,{'updated_at':100.5,'agents':[]})
        for row in media.records.values():
            for field in ('updated','part','count'):row['fields'][field]=str(row['fields'][field])
        self.assertEqual(media.get(key)['updated_at'],100.5)
        with patch.object(media,'api',wraps=media.api) as api:
            media.put(key,{'updated_at':100.5,'agents':[]})
            self.assertFalse(any(c.args[0]=='PUT' for c in api.call_args_list))

    def test_native_attachment_cli_uses_relative_paths_in_isolated_directory(self):
        media=core.Base({'app_token':'test','table_id':'tbl-test'})
        data=b'complete artifact'
        def native(args,**kwargs):
            flag='--file' if '--file' in args else '--output'
            name=args[args.index(flag)+1]
            self.assertFalse(Path(name).is_absolute())
            path=Path(kwargs['cwd'])/name
            if flag=='--file':self.assertEqual(path.read_bytes(),data)
            else:path.write_bytes(data)
            return subprocess.CompletedProcess(args,0,'{"ok":true}','')
        with patch.object(core.subprocess,'run',side_effect=native):
            media.upload_attachment('rec-test',data)
            self.assertEqual(media.download_attachment('file-test'),data)

    def test_real_empty_page_can_have_null_items(self):
        media=core.Base({'app_token':'test','table_id':'tbl-test'})
        with patch.object(media,'api',return_value={'items':None,'has_more':False}):
            self.assertEqual(media.rows('key','absent'),[])
            with self.assertRaises(FileNotFoundError):media.get('absent')

    def test_cli_stderr_permission_error_is_preserved(self):
        media=core.Base({'app_token':'test'})
        failure={'ok':False,'error':{'type':'permission','message':'Permission denied',
            'detail':{'permission_violations':[{'subject':'base:record:retrieve'}]}}}
        with patch.object(core.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'',json.dumps(failure))):
            for call in (lambda:media.api('GET',media.path),lambda:media.shortcut(['docs','+media-download'])):
                with self.assertRaisesRegex(ValueError,'base:record:retrieve'):call()

    def test_auto_schema_pagination_partial_retry_and_full_results(self):
        media=FakeBase().ensure();self.assertEqual(len(media.tables),1)
        media.ensure();self.assertEqual(len(media.tables),1)
        value={'message':'多语言完整结果'*10000}
        media.put('messages/receiver/message-one.json',value,immutable=True)
        self.assertEqual(media.get('messages/receiver/message-one.json'),value)
        self.assertEqual(list(media.list('messages/receiver')),[('message-one.json',value)])
        count=len(media.records);media.put('messages/receiver/message-one.json',value,immutable=True)
        self.assertEqual(len(media.records),count)
        with self.assertRaises(ValueError):media.put('messages/receiver/message-one.json',{'x':1},immutable=True)
        media.put('results/request.json',{'state':'running'})
        media.put('results/request.json',{'state':'completed','result':value})
        self.assertEqual(media.get('results/request.json')['result'],value)
        media.delete('messages/receiver/message-one.json')
        self.assertEqual(list(media.list('messages/receiver')),[])
        with self.assertRaises(FileNotFoundError):media.get('messages/receiver/message-one.json')


    def test_base_receiver_lifecycle_without_a_sender_platform(self):
        media=FakeBase().ensure();media.interval=0
        team=dict(media.config,id='team-test',enabled=True,name='Team',transport='feishu_base',link='https://example.feishu.cn/base/base-test')
        with tempfile.TemporaryDirectory() as folder, patch('loop_anything.runtime.team_transport.connect',return_value=media), patch('dispatch.connect',return_value=media):
            root=Path(folder);engine=Engine(Store(root/'receiver.db'));self.addCleanup(engine.close);comm=engine.communication
            with patch('loop_anything.runtime.team_transport.join',return_value=team):comm.config('team',link=team['link'])
            comm.config('agent',agent_id='a',task_confirmed=True,agent={'name':'Agent','description':'Help','groups':[team['id']],
                'implementation':{'kind':'agent','command':[sys.executable,'-c','pass']}})
            client=Client(root/'client');client.config={'team':team,'origin':'client-test'}
            request=client.submit({'message':'test','agent_id':'a'})['request']
            def worker(command,prompt,*a,**k):
                info=json.loads(prompt.split('\n',1)[1])
                comm.worker_call(info['request_id'],info['token'],'complete',{'result':{'full':'内容'*13000}})
                return subprocess.CompletedProcess(command,0,'','')
            with patch('loop_anything.runtime.host_runtime.run_command',side_effect=worker):
                until=time.monotonic()+8
                while time.monotonic()<until:
                    comm.last_scan=0;comm._team_scan_times={};comm.tick()
                    if client.read(request['id'])['state']=='completed':break
                    time.sleep(.02)
            self.assertEqual(client.read(request['id'])['result']['full'],'内容'*13000)
            comm.last_scan=0;comm._team_scan_times={};comm.scan()
            self.assertEqual(list(media.list('messages/'+comm.settings()['instance_id'])),[])
            self.assertEqual(media.get('results/'+request['id']+'.json')['state'],'completed')
            again=client.submit({'request_id':request['id'],'message':'test','agent_id':'a'})
            self.assertEqual(again['request']['state'],'completed')


    def test_incomplete_attachment_retries_without_exposing_partial_results(self):
        media=FakeBase().ensure();upload=media.upload_attachment
        value={'result':'完整证据'*30000,'updated_at':1234.5}
        def fail_after_upload(record_id,data):
            upload(record_id,data)
            raise ValueError('Connection lost after upload')
        with patch.object(media,'upload_attachment',side_effect=fail_after_upload):
            with self.assertRaises(ValueError):media.put('results/request.json',value)
        with self.assertRaises(FileNotFoundError):media.get('results/request.json')
        media.put('results/request.json',value)
        self.assertEqual(media.get('results/request.json'),value)
        self.assertEqual(len(media.records),1)
        record=next(iter(media.records.values()))
        self.assertTrue(record['fields']['payload'])
        self.assertLess(len(media.text(record['fields']['value'])),200)

    def test_large_nas_result_snapshots_preserve_complete_revisions(self):
        with tempfile.TemporaryDirectory() as folder:
            media=core.Nas({'path':folder})
            first={'result':'第一轮完整证据'*150000}
            second={'result':'第二轮完整证据'*150000}
            media.put('results/request.json',first)
            self.assertEqual(media.get('results/request.json'),first)
            media.put('results/request.json',second)
            self.assertEqual(media.get('results/request.json'),second)


    def test_nas_mount_identity_and_paths_are_checked_at_actual_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);team=core.join(str(root/'team'),create=True);media=core.connect(team)
            media.put('results/test.json',{'answer':42})
            (root/'outside').mkdir();(root/'team/escape').symlink_to(root/'outside',target_is_directory=True)
            for key in ('../leak.json','escape/leak.json','/tmp/leak.json'):
                with self.assertRaises(ValueError):media.put(key,{'private':'task'})
            with self.assertRaises(ValueError):core.choose([],agent_id='a',instance_id='../outside')
            manifest=root/'team/group.json';value=json.loads(manifest.read_text());value['id']='different-team';manifest.write_text(json.dumps(value))
            with self.assertRaises(ValueError):media.get('results/test.json')
            with self.assertRaises(ValueError):media.put('messages/receiver/new.json',{'private':'task'})
            self.assertFalse((root/'team/messages/receiver/new.json').exists())


    def test_heartbeat_updates_one_existing_row_even_for_a_large_member_directory(self):
        for size in (1,30000):
            with self.subTest(size=size):
                media=FakeBase().ensure()
                member={'instance_id':'worker','agents':[{'id':'a','description':'任务说明'*size}],
                        'loops':[],'updated_at':100,'revision':'first'}
                key='members/worker.json';media.put(key,member)
                ids=set(media.records);before=media.get(key)
                with patch.object(media,'api',wraps=media.api) as calls:
                    for stamp in (115,130,145):
                        media.put(key,dict(member,updated_at=stamp,revision=str(stamp)))
                        self.assertEqual(set(media.records),ids)
                        value=media.get(key)
                        self.assertEqual(value['updated_at'],stamp)
                        self.assertEqual(value['agents'],member['agents'])
                    writes=[c for c in calls.call_args_list if c.args[0] in ('POST','PUT','DELETE')]
                    self.assertEqual([c.args[0] for c in writes],['PUT']*3)
                    self.assertEqual(len({c.args[1] for c in writes}),1)
                    self.assertTrue(all(set(c.args[2]['fields'])=={'updated','更新时间'} for c in writes))
                self.assertNotEqual(media.get(key)['revision'],before['revision'])
                # A changed directory remains complete, then subsequent beats update its stable row.
                changed=dict(member,agents=[{'id':'b','description':'新任务'}],updated_at=160,revision='changed')
                media.put(key,changed)
                self.assertEqual(media.get(key)['agents'],changed['agents'])
                ids=set(media.records)
                media.put(key,dict(changed,updated_at=175))
                self.assertEqual(set(media.records),ids)
                self.assertEqual(dict(media.list('members'))['worker.json']['updated_at'],175)
                # The server committed a heartbeat but the response was lost: retry must not create a row.
                api=media.api
                def lose_response(method,path,data=None,params=None):
                    answer=api(method,path,data,params)
                    if method=='PUT':raise ValueError('Response lost after commit')
                    return answer
                with patch.object(media,'api',side_effect=lose_response):
                    with self.assertRaises(ValueError):media.put(key,dict(changed,updated_at=190))
                with patch.object(media,'api',wraps=media.api) as retry:
                    media.put(key,dict(changed,updated_at=190))
                    self.assertFalse(any(c.args[0] in ('POST','PUT','DELETE') for c in retry.call_args_list))
                self.assertEqual(set(media.records),ids)
                self.assertEqual(media.get(key)['updated_at'],190)
