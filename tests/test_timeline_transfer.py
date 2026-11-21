"""Two independent workspaces exchange progress, never execution authority."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_business_state as fixture
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime import business_state,timelines
from loop_anything.runtime.model import Invalid,Conflict

class TimelineTransferTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.BusinessStateTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.source=self.case.store;self.tools=PlatformTools(self.source)
        self.run=self.case.first(waiting=True);self.timeline=self.run['timeline_id']
        with self.source.edit(self.run['id']) as r:
            e=next(e for e in r['executions'] if e['node']=='wait')
            e['external_id']=json.dumps({'job_run_id':'training-123','execution_profile':{'token':'private-profile'}})
            e['implementation']['command']=['private-command']
            r['tasks']['experiment']['spec']['parameters']={'learning_rate':0.01}
            business_state.apply(r,r['executions'][0],[{'type':'question','id':'q1','value':{'text':'Does A improve recall?','status':'partly answered'},'refs':[{'record':'a','revision':1}]}])
        for i in range(205):self.tools.call('append_timeline',{'timeline_id':self.timeline,'key':'note-'+str(i),'kind':'progress','text':'Progress '+str(i)})
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.target=Store(Path(self.temp.name)/'target.db');self.target_tools=PlatformTools(self.target)
        self.package=self.tools.call('export_timeline',{'timeline_id':self.timeline})['document']

    def imported(self,request='import-one'):
        return self.target_tools.call('import_timeline',{'document':self.package,'request_id':request})['timeline']

    def test_full_progress_history_and_results_continue_with_another_method(self):
        result=self.imported();ident=result['id'];self.assertNotEqual(ident,self.timeline)
        self.assertIsNone(result['active_run_id']);self.assertFalse(self.target.list())
        history=self.target_tools.call('read_business_state',{'timeline_id':ident,'type':'question','id':'q1','revision':1})
        self.assertEqual(history['records'][0]['value']['status'],'open')
        current=self.target_tools.call('read_business_state',{'timeline_id':ident})['records'][0]
        self.assertEqual(self.target_tools.call('read_work_result',{'timeline_id':ident,'id':'a','revision':1})['record']['value'],'A')
        self.assertEqual(current['revision'],2);self.assertEqual(current['refs'],[{'record':'a','revision':1}])
        with self.target.connection() as db:self.assertGreater(db.execute('SELECT count(*) FROM work_entries WHERE timeline_id=?',(ident,)).fetchone()[0],205)
        bp={'schema_version':2,'id':'different-method','version':'1','handbook':{'instructions':'Read progress and reason'},'records':{},'nodes':{},'state':{'types':{'literature':{'summary':['claim']}}}}
        bp['records']={'answer':{'type':'string'}}
        bp['nodes']={'analyze':{'instructions':'Use saved evidence','inputs':{'evidence':{'type':'string'}},'outputs':{'answer':{'record_type':'answer'}},'progression':'rules'}}
        script='import json,sys;r=json.load(sys.stdin);print(json.dumps({"event":"completed","envelope":{"outputs":{"answer":r["inputs"]["evidence"]+" continued"},"state":[{"type":"literature","id":"new","value":{"claim":"A fresh contribution"}}]}}))'
        impl={'analyze':{'options':{'local':{'kind':'command','command':[sys.executable,'-c',script]}},'default':'local'}}
        key=self.target.publish(bp,impl)['key'];run=self.target.create(key,'Continue here',timeline_id=ident,acquire=True)
        caller=RunTools(self.target,run['id'],run['agent_sessions'][0]['token'])
        read=caller.call('read_timeline',{});self.assertEqual(read['timeline']['objective'],'Compare methods')
        self.assertEqual(caller.call('read_record',{'id':'a','revision':1})['record']['value'],'A')
        self.assertEqual(run['tasks'],{});self.assertEqual(run['arrangements'],{})
        task=caller.call('add_task',{'node_id':'analyze','key':'next','inputs':{'evidence':{'record':'a','revision':1}}})['tasks'][0]
        caller.call('finish',{})
        engine=Engine(self.target);self.addCleanup(engine.close);engine.tick(run['id'])
        for future in list(engine.futures):future.result(timeout=5)
        saved=self.target.get(run['id']);self.assertEqual(saved['tasks'][task['id']]['status'],'completed')
        self.assertEqual(saved['records'][task['outputs']['answer']['id']][0]['value'],'A continued')
        self.assertEqual(len(business_state.read(self.target,ident)['records']),2)
        again=self.target_tools.call('export_timeline',{'timeline_id':ident})['document']
        self.assertEqual(len(again['state']),3);self.assertEqual(again['source']['previous']['timeline_id'],self.timeline)
        self.assertTrue(all(r in again['results'] for r in self.package['results']))

    def test_work_snapshots_are_not_jobs_and_authority_is_not_carried(self):
        encoded=json.dumps(self.package)
        self.assertNotIn('private-profile',encoded);self.assertNotIn('private-command',encoded)
        for attempt in self.source.get(self.run['id'])['executions']:self.assertNotIn(attempt['token'],encoded)
        self.assertNotIn('work',self.package)
        self.assertNotIn('training-123',encoded)
        t=self.imported();read=self.target_tools.call('read_work_timeline',{'timeline_id':t['id']})
        self.assertEqual(read['runs'],[])
        for field in ('carried_work','activity','work','waits','monitors'):self.assertNotIn(field,read)
        self.assertEqual(self.source.get(self.run['id'])['tasks']['experiment']['status'],'waiting')

    def test_retry_is_idempotent_and_does_not_reset_later_local_edits(self):
        t=self.imported();self.target_tools.call('update_timeline',{'timeline_id':t['id'],'revision':t['revision'],'change':{'objective':'Local next goal'}})
        repeated=self.imported();self.assertEqual(repeated['id'],t['id']);self.assertEqual(repeated['objective'],'Local next goal')
        self.package['timeline']['objective']='Different file'
        with self.assertRaises(Conflict):self.imported()
        self.assertNotEqual(self.imported('another-intentional-copy')['id'],t['id'])

    def test_malformed_or_duplicate_records_leave_no_partial_timeline(self):
        self.package['results'].append(copy.deepcopy(self.package['results'][0]))
        with self.assertRaises(Invalid):self.imported()
        self.assertEqual(self.target_tools.call('list_timelines',{})['total'],0)
        del self.package['results'][-1];self.package['state'][0]['at']='invalid'
        with self.assertRaises(Invalid):self.imported()
        self.assertEqual(self.target_tools.call('list_timelines',{})['total'],0)

    def test_http_client_imports_large_document_and_exports_a_real_file(self):
        import re,subprocess,time
        root=Path(self.temp.name);project=Path(__file__).resolve().parents[1]
        env=dict(os.environ,LOOP_ANYTHING_SPACES=str(root/'spaces.json'),LOOP_ANYTHING_IDENTITY_DIR=str(root/'identity'),LOOP_ANYTHING_WORK='')
        log=root/'server.log'
        with log.open('w') as stream:
            process=subprocess.Popen([sys.executable,'-m','loop_anything','--db',self.target.filename,'serve','--port','0','--allow-sleep'],cwd=project,env=env,stdout=stream,stderr=stream)
            try:
                deadline=time.monotonic()+15;url=None
                while time.monotonic()<deadline:
                    match=re.search(r'Health check: (http://127.0.0.1:\d+)/api/health',log.read_text())
                    if match:url=match.group(1);break
                    self.assertIsNone(process.poll(),log.read_text());time.sleep(.05)
                self.assertIsNotNone(url,log.read_text())
                self.package['entries'][0]['text']='x'*2_100_000
                args=root/'args.json';args.write_text(json.dumps({'document':self.package,'request_id':'large-import'}))
                client=project/'skills/loop-anything-platform/scripts/call.py'
                def call(tool,arguments,extra=()):
                    result=subprocess.run([sys.executable,str(client),tool,'--arguments',arguments,*extra],cwd=project,env=env,text=True,capture_output=True,timeout=30)
                    self.assertEqual(result.returncode,0,result.stderr+result.stdout[:500]);return json.loads(result.stdout)
                first=call('import_timeline','@'+str(args),['--url',url]);again=call('import_timeline','@'+str(args))
                self.assertEqual(first['timeline']['id'],again['timeline']['id'])
                target=root/'export.timeline.json'
                receipt=call('export_timeline',json.dumps({'timeline_id':first['timeline']['id']}),['--output',str(target)])
                exported=json.loads(target.read_text());self.assertEqual(exported['entries'][0]['text'],self.package['entries'][0]['text'])
                self.assertEqual(receipt['platform_url'],url)
                self.assertEqual(self.target_tools.call('list_timelines',{})['total'],1)
                from urllib.request import Request, urlopen
                large_id = 9007199254740993
                self.package['results'][0]['value'] = large_id
                body = json.dumps(self.package).encode()
                request = Request(url+'/api/timelines/import', data=body, headers={
                    'X-Loop-Anything':'workspace', 'Content-Type':'application/json', 'X-Request-Id':'web-import'})
                with urlopen(request) as response:
                    imported = json.load(response)['timeline_id']
                with urlopen(url+'/api/timelines/'+imported+'/file') as response:
                    self.assertEqual(json.load(response)['results'][0]['value'], large_id)
            finally:
                process.terminate();process.wait(timeout=10)

    def test_pending_nas_export_writes_file_when_result_arrives(self):
        import subprocess
        from loop_anything.runtime.tool_client import module
        from loop_anything.runtime.tool_mailbox import ToolMailbox
        root = Path(self.temp.name)
        destination = root / 'download.json'
        client = Path(__file__).resolve().parents[1] / 'skills/loop-anything-platform/scripts/call.py'
        mailbox = ToolMailbox(self.source, root / 'nas', self.case.engine)
        url = mailbox.root.as_uri().replace('file:', 'nas:')
        with patch.dict(os.environ, LOOP_ANYTHING_SPACES=str(root/'spaces.json'), LOOP_ANYTHING_WORK=''):
            ledger = module('routing').Ledger()
            try:
                with ledger.db:
                    work = ledger.create(url)
                    ledger.remember(work, [('timeline', self.timeline)])
                ledger.verify(work, self.case.engine.communication.settings()['instance_id'])
            finally:
                ledger.close()
            def call(*args):
                proc = subprocess.run([sys.executable, str(client), *args, '--request-id', 'export-once',
                                       '--output', str(destination)], capture_output=True, text=True, check=True)
                return json.loads(proc.stdout)
            pending = call('export_timeline', '--arguments', json.dumps({'timeline_id': self.timeline}), '--wait', '0')
            self.assertTrue(pending['pending'])
            self.assertFalse(destination.exists())
            mailbox.tick()
            receipt = call('result')
            self.assertEqual(Path(receipt['file']), destination.resolve())
            self.assertEqual(json.loads(destination.read_text())['state'], self.package['state'])

    def test_progress_export_does_not_need_the_original_loop(self):
        with self.source.connection() as db:
            db.execute('DELETE FROM loop_definitions WHERE key=?',(self.run['loop_key'],));db.commit()
        exported=self.tools.call('export_timeline',{'timeline_id':self.timeline})['document']
        self.assertEqual(exported['state'],self.package['state'])
        self.assertEqual(exported['results'],self.package['results'])
        self.assertNotIn('work',exported)

    def test_run_snapshot_lists_finished_and_live_tasks_without_changing_execution(self):
        before=self.source.get(self.run['id'])
        snapshot=self.tools.call('read_run',{'run_id':self.run['id'],'view':'snapshot'})
        by_id={t['task_id']:t for t in snapshot['tasks']}
        self.assertEqual(by_id['experiment']['status'],'waiting')
        self.assertEqual(by_id['init']['status'],'completed')
        self.assertEqual(snapshot['counts'],{'completed':1,'waiting':1})
        self.assertTrue(snapshot['read_only'])
        self.assertEqual(self.source.get(self.run['id']),before)
        self.assertNotIn('private-profile',json.dumps(snapshot))
        for e in before['executions']:self.assertNotIn(e['token'],json.dumps(snapshot))
        detail=self.tools.call('read_task',{'run_id':self.run['id'],'task_id':'experiment'})
        self.assertIn('training-123',detail['execution_state']['external_id'])
        progress=self.tools.call('read_timeline',{'run_id':self.run['id']})
        for field in ('tasks','settings','handbook','work','status','implementations','requests'):
            self.assertNotIn(field,progress)
        self.assertEqual(progress['timeline']['objective'],'Compare methods')
        self.case.engine.event(self.run['id'],'finish','signal',{'text':'finished'})
        self.case.engine.tick(self.run['id'])
        snapshot=self.tools.call('read_run',{'run_id':self.run['id'],'view':'snapshot'})
        self.assertEqual(snapshot['counts'],{'completed':2})
        self.assertEqual(len(snapshot['tasks']),2)

    def test_snapshot_distinguishes_observer_failure_from_task_failure(self):
        with self.source.edit(self.run['id']) as run:
            e=next(e for e in run['executions'] if e['node']=='wait')
            e['observation_error']='Observer unavailable'
        snapshot=self.tools.call('read_run',{'run_id':self.run['id'],'view':'snapshot'})
        task=next(t for t in snapshot['tasks'] if t['task_id']=='experiment')
        self.assertEqual(task['status'],'waiting')
        self.assertEqual(task['observation_error'],'Observer unavailable')
        with self.source.edit(self.run['id']) as run:
            run['tasks']['experiment']['status']='fault'
            e=next(e for e in run['executions'] if e['node']=='wait')
            e['status']='fault';e['error']='Experiment failed'
        snapshot=self.tools.call('read_run',{'run_id':self.run['id'],'view':'snapshot'})
        task=next(t for t in snapshot['tasks'] if t['task_id']=='experiment')
        self.assertEqual(task['error'],'Experiment failed')
        self.assertEqual(snapshot['counts']['fault'],1)

    def test_snapshot_exposes_original_execution_for_a_continued_task(self):
        new=self.case.second(self.source.get(self.run['id']))
        snapshot=self.tools.call('read_run',{'run_id':new['id'],'view':'snapshot'})
        task=next(t for t in snapshot['tasks'] if t['task_id']=='experiment')
        self.assertEqual(task['continuation_source'],{'run_id':self.run['id'],'task_id':'experiment'})
        original=self.tools.call('read_task',task['continuation_source'])
        self.assertIn('training-123',original['execution_state']['external_id'])
        document=self.tools.call('export_timeline',{'timeline_id':self.timeline})['document']
        self.assertNotIn('training-123',json.dumps(document))

    def test_export_reads_no_external_files_or_log_references(self):
        self.tools.call('append_timeline',{'timeline_id':self.timeline,'key':'detail','text':'Results are saved; logs optional','refs':[{'path':'/missing/training.log'}]})
        with patch('pathlib.Path.read_bytes',side_effect=AssertionError('No file reads')):
            exported=self.tools.call('export_timeline',{'timeline_id':self.timeline})
        self.assertEqual(exported['document']['entries'][-1]['refs'],[{'path':'/missing/training.log'}])

if __name__=='__main__':unittest.main()
