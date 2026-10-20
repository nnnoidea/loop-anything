import json
import os
import subprocess
import sys
import tempfile
import socket
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

from loop_anything.runtime.engine import Engine
from loop_anything.runtime.store import Store
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.collaboration import start


CALLER_CLI = r'''
import json,os,sys,time
from pathlib import Path
from urllib.request import Request,urlopen
mode,url,filename,native=sys.argv[1:5]
state=Path(filename)
def call(tool,args):
 r=Request(url+'/api/tools',data=json.dumps({'tool':tool,'arguments':args}).encode(),headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})
 with urlopen(r,timeout=10) as f:v=json.load(f)
 assert v.get('ok'),v
 return v
if mode=='initial':
 implementation={'kind':'agent','command':[sys.executable,__file__,'initial',url,filename,'original'],
  'resume_command':[sys.executable,__file__,'resume',url,filename,'{{session_id}}','{{prompt}}'],'prompt':'{{context}}'}
 c=call('start_collaboration',{'message':'Analyse with paper evidence','caller':{'implementation':implementation,
  'native_session':{'provider':'custom','id':native},'process_id':os.getpid()}})
 state.write_text(json.dumps(dict(c,memory='private reasoning retained',calls=['initial'])))
 r=call('request_assistance',{'location':'local','agent_id':'papers','message':'Find papers',
  'source':{'run_id':c['run_id'],'task_id':c['task_id']},'token':c['token']})
 call('wait_assistance',{'run_id':c['run_id'],'task_id':c['task_id'],'token':c['token'],'request_ids':[r['request']['id']]})
 call('finish',{'run_id':c['run_id'],'token':c['token']})
 time.sleep(.4)
 saved=json.loads(state.read_text());assert saved['calls']==['initial'],'Resume overlapped old caller'
 saved['original_exited']=True;state.write_text(json.dumps(saved))
else:
 c=json.loads(sys.argv[5]);saved=json.loads(state.read_text())
 assert native=='original' and saved['original_exited']
 assert c['token']!=saved['token'] and c['run_id']==saved['run_id']
 assert c['assistance_results'][0]['result']=={'paper':'found'}
 saved['calls'].append('resume');state.write_text(json.dumps(saved))
 info=call('read_task',{'run_id':c['run_id'],'task_id':c['task_id'],'token':c['token']})
 call('report_task',{'run_id':c['run_id'],'task_id':c['task_id'],'token':c['token'],
  'task_version':info['task_version'],'report_id':'done','event':'completed',
  'envelope':{'settings':{'objective':'Analyse with paper evidence'},'outputs':{'result':{'memory':saved['memory'],'paper':'found'}}}})
 call('finish',{'run_id':c['run_id'],'token':c['token']})
'''

HELPER_CLI = r'''
import json,sys
from urllib.request import Request,urlopen
c=json.loads(sys.stdin.read())
r=Request(c['platform_url']+'/api/tools',data=json.dumps({'tool':'communication_execute','arguments':{
 'request_id':c['request_id'],'token':c['token'],'tool':'complete','arguments':{'result':{'paper':'found'}}}}).encode(),
 headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})
with urlopen(r,timeout=10) as f:assert json.load(f)['ok']
'''


class StandaloneCollaborationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = Engine(Store(Path(self.tmp.name) / 'workspace.db'))
        self.comm = self.engine.communication

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def advance(self):
        for _ in range(4):
            self.comm.tick()
            for run in self.engine.store.list():self.engine.tick(run['id'])

    def test_standalone_result_uses_event_task_and_followup_reuses_run(self):
        first = self.comm.request({'location': 'local', 'agent_id': 'missing', 'message': 'find papers'})['request']
        link = first['collaboration']
        self.advance()
        run = self.engine.store.get(link['run_id'])
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['tasks'][link['task_id']]['status'], 'completed')
        self.assertEqual(run['records']['result.' + first['id']][0]['value']['state'], 'unavailable')
        # Explicit follow-up keeps the Run, and gets a distinct result record.
        second = self.comm.control(first['id'], 'followup', message='try again', resume=False)['request']
        self.assertEqual(second['collaboration']['run_id'], run['id'])
        self.advance()
        self.assertEqual(len(self.engine.store.list()), 1)
        self.assertEqual(len(self.engine.store.get(run['id'])['events']), 2)
        self.engine.close()
        self.engine = Engine(Store(self.engine.store.filename));self.comm = self.engine.communication
        self.advance()
        self.assertEqual(len(self.engine.store.get(run['id'])['events']), 2)

    def test_group_requires_user_confirmation_and_description_changes_invalidate_it(self):
        gid = next(iter(self.comm.config('group', path=str(Path(self.tmp.name)/'group'), create=True)['configuration']['groups']))
        agent = {'name': 'Papers', 'description': 'Find papers and compare methods', 'groups': [gid],
                 'implementation': {'kind': 'agent', 'command': [sys.executable, '-c', 'pass']}}
        with self.assertRaisesRegex(Invalid, 'main task'):
            self.comm.config('agent', agent_id='local-empty', agent=dict(agent,groups=[],description=' '))
        with self.assertRaisesRegex(Invalid, 'Ask the user'):
            self.comm.config('agent', agent_id='papers', agent=agent)
        self.comm.config('agent', agent_id='papers', agent=agent, task_confirmed=True)
        published = self.comm.public_agent(self.comm.settings()['agents']['papers'], self.comm.settings(), 'group', gid)
        self.assertTrue(published['task_confirmed']);self.assertTrue(published['enabled'])
        with self.assertRaisesRegex(Invalid, 'Ask the user'):
            self.comm.config('agent', agent_id='papers', agent={'description': 'Train models'})
        self.comm.config('agent', agent_id='papers', agent={'enabled': False})
        self.comm.config('agent', agent_id='papers', agent={'enabled': True})
        # Legacy saved descriptions are not evidence of human confirmation.
        with self.comm.transaction() as db:
            settings=self.comm.settings(db);settings['agents']['papers'].pop('task_confirmation')
            db.execute('UPDATE communication_settings SET document=? WHERE id=1',(json.dumps(settings),))
        legacy=self.comm.settings()['agents']['papers']
        self.assertFalse(self.comm.public_agent(legacy,self.comm.settings(),'group',gid)['enabled'])
        self.assertFalse(self.comm.eligible(legacy,{'location':'group','group_id':gid},self.comm.settings()))

    def test_managed_coordinator_reserves_named_capacity_and_keeps_followups(self):
        self.comm.config('agent',agent_id='coordinator',agent={'name':'Coordinator','description':'Coordinate collaboration results',
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass']}})
        created=start(self.comm,{'message':'Research','agent_id':'coordinator'})
        self.assertEqual(created['mode'],'managed')
        self.assertEqual(self.engine.store.get(created['run_id'])['implementations']['coordinate']['command'],[sys.executable,'-c','pass'])
        self.assertTrue(self.comm.directory()['agents'][0]['busy'])
        with self.assertRaises(Conflict):start(self.comm,{'message':'Second','agent_id':'coordinator'})
        from loop_anything.interfaces.agent_tasks import acquire, RunTools
        owner=acquire(self.engine.store,created['run_id'])
        request=self.comm.request({'location':'local','agent_id':'missing','message':'help',
            'source':{'run_id':created['run_id'],'task_id':'coordinate'},'token':owner['token']})['request']
        followed=self.comm.control(request['id'],'followup',message='More help',resume=False)['request']
        self.assertEqual(followed['collaboration']['run_id'],created['run_id'])
        from loop_anything.interfaces.agent_tasks import release_in_run
        with self.engine.store.edit(created['run_id']) as run:release_in_run(run,owner['token'])

    def test_coordinator_notifications_inherit_chat_and_respect_explicit_override(self):
        from loop_anything.runtime.notifications import enqueue
        self.comm.config('agent',agent_id='coordinator',agent={'name':'Coordinator','description':'Coordinate collaboration results','capacity':3,
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass']}})
        source={'platform':'feishu','entry_project':'entry','session_key':'feishu:oc_chat:root:om_root'}
        created=start(self.comm,{'message':'Research','agent_id':'coordinator','chat_context':source})
        run=self.engine.store.get(created['run_id'])
        notice=enqueue(self.engine.store,run,'result',{'message':'done'})
        self.assertEqual(notice['route'],'user')
        self.assertEqual(notice['conversation']['thread_root'],'om_root')
        explicit=start(self.comm,{'message':'Local only','agent_id':'coordinator','chat_context':source,'notification_route':'workspace'})
        run=self.engine.store.get(explicit['run_id'])
        self.assertNotIn('notification_conversation_id',run)
        self.assertEqual(enqueue(self.engine.store,run,'result',{'message':'done'})['route'],'workspace')
        count=len(self.engine.store.list())
        with self.assertRaises(Invalid):start(self.comm,{'message':'Bad entrance','agent_id':'coordinator','conversation_id':'missing'})
        with self.assertRaises(Invalid):start(self.comm,{'message':'Bad route','agent_id':'coordinator','notification_route':''})
        self.assertEqual(len(self.engine.store.list()),count)

    def test_managed_coordinator_actually_executes_after_reloading_run(self):
        from unittest.mock import patch
        from loop_anything.interfaces.agent_tasks import RunTools
        self.comm.config('agent',agent_id='coordinator',agent={'name':'Coordinator','description':'Coordinate collaboration results',
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass'],'prompt':'{{context}}'}})
        started=start(self.comm,{'message':'Finish standalone work','agent_id':'coordinator'})
        def worker(command,prompt,*args,**kwargs):
            c=json.loads(prompt)
            tools=RunTools(self.engine.store,c['run_id'],c['token'])
            info=tools.call('read_task',{'task_id':c['task_id']})
            tools.call('report_task',{'task_id':c['task_id'],'task_version':info['task_version'],
                'event':'completed','report_id':'managed-result','envelope':{
                    'settings':{'objective':'Finish standalone work'},'outputs':{'result':{'done':True}}}})
            tools.call('finish',{})
            return subprocess.CompletedProcess(command,0,'','')
        with patch('loop_anything.runtime.timeline_runtime.run_command',side_effect=worker):
            self.engine.tick(started['run_id'])
            for future in list(self.engine.futures):future.result(timeout=5)
            self.engine.tick(started['run_id'])
        run=self.engine.store.get(started['run_id'])
        self.assertEqual(run['status'],'completed')
        self.assertEqual(run['records']['collaboration.result'][0]['value'],{'done':True})

    def test_active_legacy_request_is_adopted_without_restarting_or_rewriting_it(self):
        request=self.comm.request({'location':'local','agent_id':'missing','message':'legacy'})['request']
        with self.comm.transaction() as db:
            old=self.comm.get(request['id'],db);old.pop('collaboration');old['state']='unknown'
            self.comm.save(db,old)
        from loop_anything.runtime.collaboration import adopt_pending
        adopt_pending(self.comm)
        current=self.comm.get(request['id'])
        self.assertEqual(current['state'],'unknown')
        self.assertIn('collaboration',current)
        before=len(self.engine.store.list());adopt_pending(self.comm)
        self.assertEqual(len(self.engine.store.list()),before)

    def test_adopted_caller_cannot_resume_until_original_process_exits(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
        implementation = {'kind':'agent','command':[sys.executable,'-c','pass'],
                          'resume_command':[sys.executable,'-c','pass','{{session_id}}','{{prompt}}']}
        try:
            caller={'implementation':implementation,'native_session':{'provider':'custom','id':'original'},'process_id':process.pid}
            adopted=start(self.comm,{'message':'analyse','caller':caller})
            with self.assertRaises(Conflict):start(self.comm,{'message':'duplicate','caller':caller})
            r=self.comm.request({'location':'local','agent_id':'missing','message':'find papers',
                'source':{'run_id':adopted['run_id'],'task_id':adopted['task_id']},'token':adopted['token']})['request']
            self.comm.wait_assistance(adopted['run_id'],adopted['token'],adopted['task_id'],[r['id']])
            from loop_anything.interfaces.agent_tasks import RunTools
            RunTools(self.engine.store,adopted['run_id'],adopted['token']).call('finish',{})
            self.comm.wake_assistance()
            self.assertEqual(self.engine.store.get(adopted['run_id'])['tasks']['coordinate']['status'],'waiting_user')
            process.terminate();process.wait()
            self.comm.wake_assistance()
            task=self.engine.store.get(adopted['run_id'])['tasks']['coordinate']
            self.assertEqual(task['status'],'ready')
            self.assertEqual(task['assistance_resume']['native_session']['id'],'original')
            self.assertEqual(task['assistance_results'][0]['state'],'unavailable')
        finally:
            if process.poll() is None:process.terminate();process.wait()

    def test_real_external_caller_resumes_original_session_through_builtin_loop(self):
        root=Path(self.tmp.name);script=root/'caller.py';script.write_text(CALLER_CLI)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url='http://127.0.0.1:'+str(port)
        log=(root/'server.log').open('w+')
        server=subprocess.Popen([sys.executable,'-m','loop_anything','--db',str(root/'server.db'),
            'serve','--port',str(port),'--allow-sleep'],stdout=log,stderr=log)
        caller=None
        try:
            for _ in range(100):
                try:
                    with urlopen(url+'/api/platform',timeout=.2):break
                except (URLError,TimeoutError):time.sleep(.05)
            else:self.fail('Server did not start')
            def call(name,args):
                r=Request(url+'/api/tools',data=json.dumps({'tool':name,'arguments':args}).encode(),
                    headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})
                with urlopen(r,timeout=10) as f:result=json.load(f)
                self.assertTrue(result.get('ok'),result);return result
            call('communication_config',{'operation':'agent','agent_id':'papers','agent':{'name':'Papers','description':'Find research papers',
                'implementation':{'kind':'agent','command':[sys.executable,'-c',HELPER_CLI],'prompt':'{{context}}'}}})
            caller=subprocess.Popen([sys.executable,str(script),'initial',url,str(root/'memory.json'),'original'],stdout=log,stderr=log)
            self.assertEqual(caller.wait(timeout=15),0)
            saved=json.loads((root/'memory.json').read_text())
            for _ in range(160):
                run=call('read_run',{'run_id':saved['run_id']})['run']
                if run['status']=='completed':break
                time.sleep(.05)
            self.assertEqual(run['status'],'completed',run.get('diagnostics'))
            self.assertEqual(json.loads((root/'memory.json').read_text())['calls'],['initial','resume'])
            self.assertEqual(run['records']['collaboration.result'][0]['value'],{'memory':'private reasoning retained','paper':'found'})
        except BaseException:
            log.flush();log.seek(0);print(log.read()[-8000:]);raise
        finally:
            if caller and caller.poll() is None:caller.terminate();caller.wait(timeout=5)
            server.terminate();server.wait(timeout=10);log.close()


if __name__ == '__main__':unittest.main()
