"""Exact native identity, real process resume and preservation of business history."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.store import Store
from loop_anything.runtime.native_sessions import Capture, preparation, resume
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.interfaces.agent_tasks import RunTools
from test_run_agent import definition
from test_terminal import until


class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'run.db');self.engine=Engine(self.store)
        self.bp,self.impl=definition()
    def tearDown(self):self.engine.close();self.tmp.cleanup()

    def initial(self):
        code="""import sys,json
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
r=json.loads(sys.stdin.read().split('Run context:'+chr(10),1)[1]);t=RunTools(Store(sys.argv[1]),r['run_id'],r['token'])
print(json.dumps({'type':'thread.started','thread_id':'native-exact-123'}),flush=True)
i=t.call('read_task',{'task_id':'init'})
t.call('complete_task',{'task_id':'init','task_version':i['task_version'],'envelope':{'settings':{'objective':'Keep running'},'outputs':{'result':'original result'}}})
t.call('finish',{})
"""
        self.impl['init']={'kind':'agent','agent_cli':'codex','command':[sys.executable,'-u','-c',code,self.store.filename],'cwd':str(Path(__file__).resolve().parents[1])}
        key=self.store.publish(self.bp,self.impl)['key'];self.rid=self.store.create(key,'Native sessions')['id'];self.engine.tick(self.rid)
        for future in list(self.engine.futures):future.result(8)
        self.original=self.store.get(self.rid);self.eid=self.original['executions'][0]['id']

    def test_bounded_capture_and_provider_identity(self):
        rows=[];c=Capture('codex',lambda p,i:rows.append((p,i)))
        c.feed('stdout','{"type":"thread.st');c.feed('stderr','business output\n');c.feed('stdout','arted","thread_id":"exact-one"}\n')
        c.feed('stdout','{"type":"thread.started","thread_id":"wrong-two"}\n')
        self.assertEqual([('codex','exact-one')],rows)
        rows=[];c=Capture('claude',lambda p,i:rows.append(i));c.feed('stdout','{"type":"system","subtype":"init","session_id":"claude-id"}\n')
        self.assertEqual(['claude-id'],rows)
        c=Capture('codex',lambda *_:None);c.feed('stdout','x'*100000);self.assertLessEqual(len(c.buffers['stdout']),32768)

    @unittest.skipUnless(os.name=='posix','PTY requires POSIX')
    def test_resume_same_native_id_new_token_same_result_and_duplicate_attach(self):
        self.initial();self.assertEqual('native-exact-123',self.original['executions'][0]['native_session']['id'])
        info=preparation(self.engine,self.rid,self.eid);self.assertEqual('native-exact-123',info['native_session']['id'])
        code="""import sys,json,time,os
from pathlib import Path
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
assert sys.argv[1]=='native-exact-123';assert os.isatty(0)
r=json.loads(Path(sys.argv[2]).read_text().split('Run context:'+chr(10),1)[1]);assert r['token']!=sys.argv[4]
t=RunTools(Store(sys.argv[3]),r['run_id'],r['token'])
i=t.call('read_task',{'task_id':'init'});assert i['task']['status']=='completed'
assert not RunTools(Store(sys.argv[3]),r['run_id'],sys.argv[4]).respond('finish',{})['ok']
assert not t.respond('complete_task',{'task_id':'init','task_version':i['task_version'],'envelope':{'outputs':{'result':'overwrite'}}})['ok']
print('RESUMED-EXACT',flush=True);input();t.call('finish',{});time.sleep(60)
"""
        args=dict(revision=info['revision'],provider='codex',native_session_id='native-exact-123',message='Explain the saved result',command=[sys.executable,'-u','-c',code,'{{session_id}}','{{prompt_file}}',self.store.filename,self.original['executions'][0]['token']])
        response=resume(self.engine,self.rid,self.eid,args)
        until(lambda:'RESUMED-EXACT' in str(self.engine.terminals.read(self.rid,self.eid,response['session_id'])['output']))
        again=resume(self.engine,self.rid,self.eid,args);self.assertTrue(again['attached']);self.assertEqual(response['session_id'],again['session_id'])
        self.engine.terminals.control(self.rid,self.eid,response['session_id'],data='continue\n')
        for future in list(self.engine.futures):future.result(8)
        after=self.store.get(self.rid)
        self.assertEqual(self.original['records'],after['records']);self.assertEqual(self.original['tasks'],after['tasks']);self.assertEqual(1,len(after['executions']));self.assertFalse(after['agent_sessions'])
        state=self.engine.terminals.read(self.rid,self.eid,response['session_id'])['session'];self.assertEqual(0,state['returncode']);self.assertTrue(state['finished_by_tool'])

    @unittest.skipUnless(os.name=='posix','PTY requires POSIX')
    def test_missing_native_session_is_failure_not_a_fresh_task(self):
        self.initial();info=preparation(self.engine,self.rid,self.eid)
        args=dict(revision=info['revision'],provider='codex',native_session_id='native-exact-123',message='Explain',command=[sys.executable,'-c',"import sys;print('session not found');sys.exit(4)",'{{session_id}}','{{prompt}}'])
        result=resume(self.engine,self.rid,self.eid,args)
        for f in list(self.engine.futures):f.result(8)
        after=self.store.get(self.rid);self.assertFalse(after['agent_sessions']);self.assertEqual(self.original['records'],after['records']);self.assertEqual(self.original['tasks'],after['tasks'])
        self.assertEqual(4,self.engine.terminals.read(self.rid,self.eid,result['session_id'])['session']['returncode'])
        with self.assertRaises(Invalid):resume(self.engine,self.rid,self.eid,dict(args,native_session_id='--last'))
        with self.assertRaises(Conflict):resume(self.engine,self.rid,self.eid,dict(args,native_session_id='different-session'))

    def test_explicit_generated_session_id_reaches_cli_and_is_saved(self):
        self.impl['init']={'kind':'agent','agent_cli':'claude','command':[sys.executable,'-c',
            "import sys,uuid;uuid.UUID(sys.argv[1]);print(sys.argv[1])",'{{session_id}}']}
        key=self.store.publish(self.bp,self.impl)['key'];rid=self.store.create(key,'Assigned native ID')['id'];self.engine.tick(rid)
        for future in list(self.engine.futures):future.result(8)
        execution=self.store.get(rid)['executions'][0]
        native=execution['native_session'];self.assertEqual('configured_id',native['source'])
        logs=self.engine.terminals.read(rid,execution['id']);self.assertIn(native['id'],str(logs['output']))
        self.assertNotEqual(native['id'],execution['id'])

    def test_own_native_registration_and_historical_log_discovery(self):
        key=self.store.publish(self.bp,self.impl)['key'];rid=self.store.create(key,'Register')['id'];self.engine.tick(rid)
        run=self.store.get(rid);e=run['executions'][0];tools=RunTools(self.store,rid,e['token'])
        value=tools.call('register_agent_session',{'execution_id':e['id'],'provider':'codex','session_id':'real-cli-id'})
        self.assertEqual('real-cli-id',value['native_session']['id'])
        with self.assertRaises(Conflict):tools.call('register_agent_session',{'execution_id':e['id'],'provider':'codex','session_id':'different'})
        self.assertFalse(RunTools(self.store,rid).respond('register_agent_session',{'execution_id':e['id'],'provider':'codex','session_id':'real-cli-id'})['ok'])
        # Older task output may already contain the exact startup identity; inspect only its own rows.
        self.initial()
        with self.store.edit(self.rid) as current:current['executions'][0].pop('native_session')
        read=preparation(self.engine,self.rid,self.eid)
        self.assertEqual('native-exact-123',read['native_session']['id']);self.assertNotIn('native_session',self.store.get(self.rid)['executions'][0])


if __name__=='__main__':unittest.main()
