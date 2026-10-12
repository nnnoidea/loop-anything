"""Two real platform processes and CLI subprocesses; no model or external channel calls."""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


WORKER = '''import json,sys,time
from urllib.request import Request,urlopen
c=json.loads((sys.argv[1] if len(sys.argv)>1 else sys.stdin.read()).split("\\n",1)[1])
with urlopen(c["platform_url"]+"/api/tools",timeout=10) as f: catalog=json.load(f)
names=[d["name"] for d in catalog["tools"]]
assert len(names)==len(set(names)) and "read_capabilities" in names,catalog
if c["kind"]=="node_execution": assert "resolve_refs" in names and "add_task" in names
def call(tool,a):
 body={"tool":"communication_execute","arguments":{"request_id":c["request_id"],"token":c["token"],"tool":tool,"arguments":a}}
 r=Request(c["platform_url"]+"/api/tools",data=json.dumps(body).encode(),headers={"Content-Type":"application/json","X-Loop-Anything":"workspace"})
 with urlopen(r,timeout=10) as f: result=json.load(f)
 assert result.get("ok"),result
 return result
print("执行进度：正在检查",flush=True)
call("native_session",{"provider":"custom","id":sys.argv[2] if len(sys.argv)>2 else "session-"+c["request_id"]})
call("progress",{"message":"已读取任务"})
if c["kind"]=="node_execution":
 def source(tool,a):
  r=Request(c["platform_url"]+"/api/tools",data=json.dumps({"tool":tool,"arguments":a}).encode(),headers={"Content-Type":"application/json","X-Loop-Anything":"workspace"})
  with urlopen(r,timeout=25) as f: v=json.load(f)
  assert v.get("ok") and not v.get("pending"),v
  return v
 info=source("read_task",{"task_id":c["task_id"]})
 source("resolve_refs",{})
 source("report_task",{"task_id":c["task_id"],"task_version":info["task_version"],"event":"completed","report_id":"http-node-done","envelope":{"outputs":{"a":"A","b":"B"},"settings":{"objective":"HTTP remote node"}}})
 source("finish",{})
 call("complete",{"result":{}})
else:
 call("complete",{"result":{"papers":["example"],"message":c["message"],"context":c["context"]}})
'''


class CommunicationHTTPTests(unittest.TestCase):
    def test_two_platform_processes_exchange_results_with_scoped_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);worker=root/'worker.py';worker.write_text(WORKER)
            servers=[];logs=[];urls=[]
            try:
                for name in ('a','b'):
                    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
                    log=(root/(name+'.log')).open('w+');logs.append(log)
                    process=subprocess.Popen([sys.executable,'-m','loop_anything','--db',str(root/(name+'.db')),'serve','--port',str(port),'--allow-sleep'],
                        stdout=log,stderr=log,env=dict(os.environ,LOOP_ANYTHING_EDIT_PASSWORD='test-only-password',PATH=''))
                    servers.append(process);url='http://127.0.0.1:'+str(port);urls.append(url)
                    for _ in range(100):
                        try:
                            with urlopen(url+'/api/platform',timeout=.2):break
                        except (URLError,TimeoutError):time.sleep(.05)
                    else:self.fail('Platform did not start')
                def tool(index,name,args,admin=True):
                    headers={'Content-Type':'application/json','X-Loop-Anything':'workspace'}
                    if admin:headers['Authorization']='Basic '+base64.b64encode(b':test-only-password').decode()
                    request=Request(urls[index]+'/api/tools',data=json.dumps({'tool':name,'arguments':args}).encode(),headers=headers)
                    with urlopen(request,timeout=10) as f:value=json.load(f)
                    self.assertTrue(value.get('ok'),value)
                    return value
                # Trusted workspace operations are open independently of the legacy global env password.
                discovered=tool(0,'communication_status',{},admin=False)
                self.assertEqual(discovered['agents'],[])
                self.assertNotIn('access_token',json.dumps(discovered))
                self.assertTrue(tool(0,'communication_config',{'operation':'identity','name':'open workspace'},admin=False)['ok'])
                independent=tool(0,'request_assistance',{'location':'local','agent_id':'not-configured','message':'independent help'},admin=False)
                self.assertEqual(tool(0,'read_assistance',{'request_id':independent['request']['id']},admin=False)['request']['state'],'unavailable')
                group=tool(0,'communication_config',{'operation':'group','path':str(root/'nas'),'create':True})
                gid=next(iter(group['configuration']['groups']))
                tool(1,'communication_config',{'operation':'group','path':str(root/'nas')})
                tool(1,'set_notification_channels',{'revision':0,'channels':{'test-outlet':{'label':'测试投递','command':[sys.executable,'-c','import json;print(json.dumps({"delivered":True,"channel":"test"}))']}}})
                binding=tool(1,'communication_config',{'operation':'group_notifications','group_id':gid,'notification_route':'test-outlet'})['notification_binding']
                for _ in range(100):
                    discovered=tool(0,'communication_status',{'group_id':gid})['groups']
                    if next(g for g in discovered if g['id']==gid).get('notification_bindings',{}).get(binding['sender_instance'],{}).get('id')==binding['id']:break
                    time.sleep(.1)
                else:self.fail('Group notification binding was not discovered')
                tool(1,'communication_config',{'operation':'agent','task_confirmed':True,'agent_id':'papers','agent':{'description':'查找研究论文','name':'论文助手','local':True,'groups':[gid],
                     'implementation':{'kind':'agent','command':[sys.executable,str(worker)],'agent_cli':'custom','resume_command':[sys.executable,str(worker),'{{prompt}}','{{session_id}}']}}})
                public=tool(1,'communication_status',{'group_id':gid},admin=False)
                local=next(a for a in public['agents'] if a['location']=='local' and a['id']=='papers')
                self.assertNotIn('implementation',local)
                self.assertNotIn('command',json.dumps(public))
                self.assertNotIn(str(root/'nas'),json.dumps(public))
                # The client carries origin metadata even without cc-connect on either side.
                client=Path(__file__).resolve().parents[1]/'skills/loop-anything-platform/scripts/call.py'
                response=subprocess.run([sys.executable,str(client),'request_assistance','--url',urls[1],'--arguments',json.dumps({'location':'local','agent_id':'papers','message':'works without notification bridge'})],
                    env=dict(os.environ,PATH='',CC_PROJECT='entrance',CC_SESSION_KEY='feishu:oc_isolated:root:om_isolated'),capture_output=True,text=True,timeout=10)
                self.assertEqual(response.returncode,0,response.stderr);accepted=json.loads(response.stdout);self.assertTrue(accepted['ok'])
                rid=accepted['request']['id']
                for _ in range(150):
                    state=tool(1,'read_assistance',{'request_id':rid,'include_details':True},admin=False)['request']
                    if state['state']=='completed' and any(n.get('status')=='fault' for n in state.get('notifications',[])):break
                    time.sleep(.05)
                else:self.fail(str(state))
                self.assertEqual(state['result']['message'],'works without notification bridge')
                self.assertEqual(state['notification_conversation']['conversation']['thread_root'],'om_isolated')
                for origin,location in ((1,'local'),(0,'group')):
                    business_context={'task':'分析实验结果并查找相关论文'}
                    created=tool(origin,'request_assistance',{'location':location,'group_id':gid,'agent_id':'papers','message':'查论文','context':business_context})
                    args={'request_id':created['request']['id'],'token':created['request_token']}
                    self.assertTrue(tool(origin,'read_assistance',{'request_id':args['request_id']},admin=False)['ok'])
                    for _ in range(100):
                        result=tool(origin,'read_assistance',args,admin=False)['request']
                        if result['state'] in ('completed','failed'):break
                        time.sleep(.15)
                    self.assertEqual(result['state'],'completed',result)
                    self.assertEqual(result['result']['papers'],['example'])
                    self.assertEqual(result['result']['context'],business_context)
                    for _ in range(100):
                        result=tool(origin,'read_assistance',args,admin=False)['request']
                        if any(n['state']=='completed' and n['status']=='delivered' for n in result.get('notifications',[])):break
                        time.sleep(.1)
                    else:self.fail('Group notification receipt was not returned')
                    self.assertEqual(next(n for n in result['notifications'] if n['state']=='completed')['routing']['binding_id'],binding['id'])
                    self.assertEqual(result['native_session']['provider'],'custom')
                    self.assertNotIn('worker_token',result)
                    if location=='local':
                        resumed=tool(origin,'control_assistance',dict(args,action='followup',message='继续解释',resume=True),admin=False)
                        for _ in range(100):
                            continued=tool(origin,'read_assistance',{'request_id':resumed['request']['id'],'token':resumed['request_token']},admin=False)['request']
                            if continued['state'] in ('completed','failed'):break
                            time.sleep(.1)
                        self.assertEqual(continued['state'],'completed',continued)
                        self.assertEqual(continued['native_session']['id'],result['native_session']['id'])
                        self.assertEqual(continued['result']['message'],'继续解释')
                standalone_runs={i:{r['id'] for r in tool(i,'list_runs',{})['runs']} for i in (0,1)}
                for i,ids in standalone_runs.items():
                    self.assertTrue(ids)
                    for rid in ids:self.assertIn('collaboration',tool(i,'read_run',{'run_id':rid})['run'])
                self.assertTrue(tool(0,'communication_workspace',{},admin=False)['ok'])
                import test_timeline_runtime as fixture
                from loop_anything.runtime.store import Store
                definition=fixture.RuntimeTests();definition.setUp()
                try:
                    definition.implementations['init']={'kind':'agent','dispatch':{'location':'group','agent_id':'papers'}}
                    source_store=Store(root/'a.db');key=source_store.publish(definition.bp,definition.implementations)['key']
                    tool(0,'communication_config',{'operation':'bind_loop','loop_key':key,'group_id':gid})
                    runid=source_store.create(key,'real remote node')['id']
                    for _ in range(160):
                        actual=source_store.get(runid)
                        if actual['tasks']['init']['status']=='completed' and not actual['agent_sessions']:break
                        time.sleep(.15)
                    self.assertEqual(actual['tasks']['init']['status'],'completed',actual['history'])
                    self.assertEqual(actual['records']['a'][0]['value'],'A')
                    self.assertEqual(actual['agent_sessions'],[])
                    self.assertEqual({r['id'] for r in tool(1,'list_runs',{})['runs']},standalone_runs[1])
                finally:definition.tearDown()
            finally:
                for p in servers:
                    p.terminate()
                for p in servers:
                    try:p.wait(timeout=10)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
                for log in logs:log.close()


if __name__=='__main__':unittest.main()
