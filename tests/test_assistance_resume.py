"""Real platform/CLI processes prove assistance resumes the original conversation.

The test CLI keeps private conversation memory in a session file. No model calls.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request,urlopen

import test_timeline_runtime as fixture
from loop_anything.runtime.store import Store


NODE_CLI=r'''import json,sys
from pathlib import Path
from urllib.request import Request,urlopen
state_path,mode,native,prompt=sys.argv[1:]
c=json.loads(prompt);remote=c.get('kind')=='node_execution'
def call(name,args):
 if not remote and name not in ('request_assistance','read_assistance'):args=dict(args,run_id=c['run_id'],token=c['token'])
 r=Request(c['platform_url']+'/api/tools',data=json.dumps({'tool':name,'arguments':args}).encode(),headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})
 with urlopen(r,timeout=30) as f:v=json.load(f)
 assert v.get('ok'),v
 return v
p=Path(state_path)
if mode=='new':
 assert not p.exists(),'Starting a new session again loses the conversation'
 state={'session':native,'memory':'reasoning-before-assistance','calls':['new'],'tokens':[c['token']]}
 p.write_text(json.dumps(state))
 call('register_agent_session',{'execution_id':c['execution_id'],'provider':'custom','session_id':native})
 args={'location':'local','agent_id':'helper','message':'find paper'}
 if not remote:args.update(source={'run_id':c['run_id'],'task_id':c['task_id']},token=c['token'])
 created=call('request_assistance',args);helper=created['request']
 state['helper_token']=created['request_token'];p.write_text(json.dumps(state))
 call('wait_assistance',{'task_id':c['task_id'],'request_ids':[helper['id']],'seconds':30})
else:
 state=json.loads(p.read_text());assert native==state['session'],'Wrong session ID'
 assert c['token']!=state['tokens'][-1],'Old credential reused'
 assert c['assistance_resume']['native_session']['id']==native
 state['calls'].append(mode);state['tokens'].append(c['token']);p.write_text(json.dumps(state))
 if mode=='fail':sys.exit(4)
 assert c['assistance_results'][0]['result']['paper']=='paper-found',c
 assert not {'logs','last_sent','history','context'} & c['assistance_results'][0].keys(),c
 assert 'HELPER_LOG' not in json.dumps(c['assistance_results']),c
 lookup={'request_id':c['assistance_results'][0]['id']}
 if not remote:lookup['token']=state['helper_token']
 assert call('read_assistance',lookup)['request']['result']['paper']=='paper-found'
 info=call('read_task',{'task_id':c['task_id']})
 call('report_task',{'task_id':c['task_id'],'task_version':info['task_version'],'event':'completed','report_id':'after-assistance','envelope':{'settings':{'objective':'continuous reasoning'},'outputs':{'a':state['memory'],'b':c['assistance_results'][0]['result']['paper']}}})
call('finish',{})
if remote:call('communication_execute',{'request_id':c['request_id'],'token':c['token'],'tool':'complete','arguments':{'result':{}}})
'''

HELPER_CLI=r'''import json,sys,time
from urllib.request import Request,urlopen
c=json.loads(sys.stdin.read());time.sleep(.2)
print('HELPER_LOG'*3000,flush=True)
r=Request(c['platform_url']+'/api/tools',data=json.dumps({'tool':'communication_execute','arguments':{'request_id':c['request_id'],'token':c['token'],'tool':'complete','arguments':{'result':{'paper':'paper-found'}}}}).encode(),headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})
with urlopen(r,timeout=10) as f:assert json.load(f)['ok']
'''


class AssistanceResumeTests(unittest.TestCase):
    def test_local_and_remote_resume_exact_session_with_memory_results_and_new_credentials(self):
        for remote in (False,True):
            with self.subTest(remote=remote):self.exercise(remote)

    def test_resume_failure_does_not_fall_back_to_a_new_session(self):
        for remote in (False,True):
            with self.subTest(remote=remote):self.exercise(remote,fail=True)

    def exercise(self,remote,fail=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);script=root/'node.py';script.write_text(NODE_CLI)
            processes=[];logs=[];urls=[]
            try:
                for i in range(2 if remote else 1):
                    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                    log=(root/(str(i)+'.log')).open('w+');logs.append(log)
                    p=subprocess.Popen([sys.executable,'-m','loop_anything','--db',str(root/(str(i)+'.db')),'serve','--port',str(port),'--allow-sleep'],stdout=log,stderr=log,
                        env=dict(os.environ))
                    processes.append(p);urls.append('http://127.0.0.1:'+str(port))
                    for _ in range(100):
                        try:
                            with urlopen(urls[-1]+'/api/platform',timeout=.2):break
                        except (URLError,TimeoutError):time.sleep(.05)
                    else:self.fail('Server did not start')
                def tool(i,name,args):
                    request=Request(urls[i]+'/api/tools',data=json.dumps({'tool':name,'arguments':args}).encode(),headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'})
                    with urlopen(request,timeout=10) as f:result=json.load(f)
                    self.assertTrue(result.get('ok'),result);return result
                implementation={'kind':'agent','command':[sys.executable,str(script),str(root/'session.json'),'new','{{session_id}}','{{prompt}}'],
                    'resume_command':[sys.executable,str(script),str(root/'session.json'),'fail' if fail else 'resume','{{session_id}}','{{prompt}}'],
                    'terminal':True,'agent_cli':'custom','prompt':'{{context}}'}
                executor=1 if remote else 0
                tool(executor,'communication_config',{'operation':'agent','agent_id':'helper','agent':{'name':'helper','local':True,'implementation':{'kind':'agent','command':[sys.executable,'-c',HELPER_CLI],'prompt':'{{context}}'}}})
                source=Store(root/'0.db');case=fixture.RuntimeTests();case.setUp()
                try:
                    if remote:
                        config=tool(0,'communication_config',{'operation':'group','path':str(root/'nas'),'create':True})['configuration'];gid=next(iter(config['groups']))
                        tool(1,'communication_config',{'operation':'group','path':str(root/'nas')})
                        tool(1,'communication_config',{'operation':'agent','task_confirmed':True,'agent_id':'research','agent':{'name':'research','description':'Research experimental results','groups':[gid],'implementation':implementation}})
                        case.implementations['init']={'kind':'agent','dispatch':{'location':'group','agent_id':'research'}}
                    else:case.implementations['init']=implementation
                    key=source.publish(case.bp,case.implementations)['key']
                    if remote:tool(0,'communication_config',{'operation':'bind_loop','loop_key':key,'group_id':gid})
                    rid=source.create(key,'wait and resume')['id']
                    paused_admission=False
                    deadline=time.monotonic()+40
                    while time.monotonic()<deadline:
                        run=source.get(rid);task=run['tasks']['init']
                        if remote and not fail and task.get('assistance_wait') and not paused_admission:
                            tool(1,'communication_config',{'operation':'agent','agent_id':'research','agent':{'enabled':False}})
                            tool(1,'communication_config',{'operation':'leave','group_id':gid})
                            tool(0,'communication_config',{'operation':'bind_loop','run_id':rid})
                            paused_admission=True
                        if task['status'] in ('completed','fault') and not run['agent_sessions']:
                            if not remote:break
                            request=tool(0,'read_assistance',{'request_id':run['executions'][-1]['communication_id']})['request']
                            if request['state'] in ('completed','failed'):break
                        time.sleep(.1)
                    self.assertEqual(task['status'],'fault' if fail else 'completed',run['history'])
                    self.assertEqual(len(run['tasks']),1)
                    self.assertEqual(len(run['executions']),2,run['history'])
                    state=json.loads((root/'session.json').read_text())
                    self.assertEqual(state['calls'],['new','fail' if fail else 'resume'])
                    self.assertNotEqual(state['tokens'][0],state['tokens'][1])
                    self.assertEqual([e['native_session']['id'] for e in run['executions']],[state['session']]*2)
                    if fail:self.assertEqual(run['records'],{})
                    else:
                        self.assertEqual(run['records']['a'][0]['value'],'reasoning-before-assistance')
                        self.assertEqual(run['records']['b'][0]['value'],'paper-found')
                    if remote:
                        if not fail:self.assertTrue(paused_admission)
                        self.assertEqual(tool(1,'list_runs',{})['runs'],[])
                        requests=tool(0,'communication_workspace',{})['requests']
                        nodes=[r for r in requests if r['kind']=='node_execution']
                        self.assertEqual(len({(r['executor'],r['agent_id']) for r in nodes}),1)
                        self.assertEqual(nodes[0]['session']['mode'],'resume')
                finally:case.tearDown()
            finally:
                for p in processes:p.terminate()
                for p in processes:
                    try:p.wait(timeout=10)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
                for log in logs:log.close()


if __name__=='__main__':unittest.main()
