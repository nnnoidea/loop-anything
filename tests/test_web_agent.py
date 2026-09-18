"""Real local commands use the scoped web endpoint; no model calls."""
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.store import Store
from loop_anything.runtime.model import Conflict
from loop_anything.runtime.host_runtime import CommandNotStopped
from loop_anything.interfaces.agent_tasks import acquire, RunTools
from loop_anything.interfaces.web_agent import WebAgent
from test_run_agent import definition

AGENT = r'''import json,sys
from urllib.request import Request,urlopen
c=json.loads(sys.stdin.read().split('Web context:\n')[1])
def call(name,args={}):
 req=Request(c['tool_url']+'/api/tools',data=json.dumps({'tool':name,'arguments':args}).encode(),headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})
 with urlopen(req) as res:r=json.load(res)
 assert r['ok'],r
 return r
mode=sys.argv[1]
if mode=='discuss':
 p=call('read_preparation');call('change_preparation',{'revision':p['revision'],'change':{'bindings':{'script':'remote'},'inputs':{'request':'已讨论的要求'}}});print('已选择远端，还没有启动。')
elif mode=='start':
 p=call('read_preparation');r=call('start_prepared_run',{'revision':p['revision']});i=call('read_task',{'task_id':r['entry_task_id']})
 call('complete_task',{'task_id':r['entry_task_id'],'task_version':i['task_version'],'envelope':{'settings':{'objective':'已讨论的要求'},'outputs':{'result':'initialized'}}})
 call('add_task',{'key':'training','node_id':'script','inputs':{}});call('finish');print('已启动并初始化。')
elif mode=='read':
 r=call('read_timeline');print('只读状态：'+str(r['read_only']))
elif mode=='edit':
 call('acquire_run');r=call('read_timeline');call('change_settings',{'revision':r['settings']['revision'],'change':{'guidance':'用户要求修改'}});call('finish');print('已修改本次运行。')
'''


class WebAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
        self.engine = Engine(self.store)
        self.web = WebAgent(self.store, self.engine)
        web = self.web
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                _, _, ident, token, *_ = self.path.split('/')
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                data = web.tool(ident, token, body['tool'], body.get('arguments', {}))
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(data).encode())
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True); self.thread.start()
        self.engine.platform_url = 'http://127.0.0.1:%s' % self.http.server_port
        bp, implementations = definition()
        implementations['script'] = {'default': 'local', 'options': {name: {'kind': 'command', 'command': [sys.executable, '-c', 'import json;print(json.dumps({"outputs":{"result":%r}}))' % name]} for name in ('local', 'remote')}}
        self.key = self.store.publish(bp, implementations)['key']
        self.doc = self.web.create(key=self.key)

    def tearDown(self):
        self.engine.close(); self.http.shutdown(); self.thread.join(); self.http.server_close(); self.tmp.cleanup()

    def turn(self, mode, start=False):
        self.doc = self.web.view(self.web.read(self.doc['id']))
        self.doc = self.web.update(self.doc['id'], self.doc['revision'], agent={'command': [sys.executable, '-c', AGENT, mode]})
        self.web.send(self.doc['id'], self.doc['revision'], mode, start)
        for future in list(self.engine.futures):
            future.result(timeout=8)
        self.doc = self.web.view(self.web.read(self.doc['id']))
        return self.doc

    def test_discuss_reload_select_start_once_and_continue_same_run(self):
        original = self.store.catalog()
        doc = self.turn('discuss')
        self.assertEqual([], self.store.list())
        self.assertEqual({'script': 'remote'}, doc['launch']['bindings'])
        self.assertEqual(original, self.store.catalog())
        with self.assertRaises(Conflict):
            self.web.update(doc['id'], doc['revision'] - 1, launch={'title': 'stale'})
        self.assertEqual(doc, self.web.view(self.web.read(doc['id'])))
        doc = self.turn('start', True)
        self.assertEqual('completed', doc['messages'][-1]['status'], doc['messages'][-1])
        run_id = doc['run_id']; run = self.store.get(run_id)
        self.assertTrue(run['initialized']); self.assertEqual([], run['agent_sessions'])
        self.assertEqual({'script': 'remote'}, run['settings']['bindings'])
        self.assertEqual(run_id, self.web.start(doc['id'], doc['revision'])['run_id'])
        self.assertEqual(1, len(self.store.list()))
        self.engine.tick(run_id)
        for future in list(self.engine.futures):future.result(timeout=5)
        self.assertTrue(any(e.get('outputs', {}).get('result') == 'remote' for e in self.store.get(run_id)['executions']))
        self.assertEqual(doc['id'], self.web.create(run_id=run_id)['id'])
        doc = self.turn('edit')
        self.assertEqual('completed', doc['messages'][-1]['status'], doc['messages'][-1])
        self.assertEqual('用户要求修改', self.store.get(run_id)['settings']['guidance'])
        self.assertEqual(1, len(self.store.list()))

    def test_read_does_not_take_rights_and_write_cannot_steal_them(self):
        doc = self.turn('start', True); run_id = doc['run_id']
        owner = acquire(self.store, run_id)
        doc = self.turn('read');self.assertEqual('completed',doc['messages'][-1]['status'])
        self.assertIn('True', doc['messages'][-1]['text'])
        doc = self.turn('edit');self.assertEqual('error',doc['messages'][-1]['status'])
        self.assertEqual(owner['token'], self.store.get(run_id)['agent_sessions'][0]['token'])
        self.assertNotEqual('用户要求修改',self.store.get(run_id)['settings']['guidance'])

    def test_interrupted_turn_preserves_rights_and_requires_confirmed_recovery(self):
        ident = self.doc['id']
        with self.web.edit(ident) as (doc, _):
            doc['agent'] = {'command': [sys.executable, '-c', 'pass']}
            doc['turn'] = {'token':'test-turn','scope_task':None,'start_requested':False}
            doc['messages'] = [{'role':'user','text':'start'},{'role':'assistant','text':'','status':'running'}]
        self.web.start(ident, self.web.read(ident)['revision'], 'test-turn')
        with patch('loop_anything.interfaces.web_agent.run_command', side_effect=CommandNotStopped('still alive')):
            self.web.execute(ident,'test-turn')
        doc = self.web.read(ident);run_id=doc['run_id']
        self.assertTrue(self.web.view(doc)['recovery_required'])
        self.assertTrue(self.store.get(run_id)['agent_sessions'][0]['recovery_required'])
        self.assertFalse(self.web.tool(ident,'test-turn','start_prepared_run',{'revision':doc['revision']})['ok'])
        with self.assertRaises(Conflict):self.web.recover(ident,False)
        WebAgent(self.store,self.engine)  # Restart must not silently release the old owner.
        self.assertTrue(self.store.get(run_id)['agent_sessions'])
        self.web.recover(ident,True)
        self.assertFalse(self.store.get(run_id)['agent_sessions'])
        self.assertFalse(self.web.tool(ident,'test-turn','start_prepared_run',{'revision':doc['revision']})['ok'])
        self.assertEqual(1,len(self.store.list()))
