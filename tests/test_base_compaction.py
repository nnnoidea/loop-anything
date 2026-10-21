"""Base retains unread results, not terminal streams or acknowledged transport history."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from test_dispatch_transport import FakeBase, Client
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.store import Store
from loop_anything.runtime.dispatch import publish_results
from loop_anything.runtime.model import Conflict
from loop_anything.runtime.team_transport import core


class CompactBaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.media=FakeBase().ensure();self.media.interval=0
        self.team=dict(self.media.config,id='team-compact',name='Team',enabled=True,transport='feishu_base')
        self.patches=[patch('loop_anything.runtime.team_transport.connect',return_value=self.media),
                      patch('loop_anything.runtime.team_transport.join',return_value=self.team),
                      patch('dispatch.connect',return_value=self.media)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.engines=[Engine(Store(self.root/(n+'.db'))) for n in ('a','b')]
        self.a,self.b=[e.communication for e in self.engines]
        for c in (self.a,self.b):c.config('team',link='unused-test-link')
        self.addCleanup(self.tmp.cleanup)
        for e in self.engines:self.addCleanup(e.close)
    def scan(self,*instances):
        for c in instances:
            c.last_scan=0;c._team_scan_times={};c.scan()
            self.assertFalse(getattr(c,'transport_error',None))
    def agent(self):
        self.b.config('agent',agent_id='a',task_confirmed=True,agent={'name':'Agent','description':'Help','groups':[self.team['id']],
            'implementation':{'kind':'agent','command':[sys.executable,'-c','pass']}})

    def test_explicit_probe_updates_one_record_without_delete_permission(self):
        with patch.object(self.media,'delete',side_effect=AssertionError('No delete permission')):
            for _ in range(2):
                self.assertTrue(self.a.config('probe',group_id=self.team['id'])['read_write_verified'])
        rows=self.media.rows('bucket','checks')
        self.assertEqual(len(rows),1)
        record=self.media.get('checks/'+self.a.settings()['instance_id']+'.json')
        self.assertEqual(record['instance_id'],self.a.settings()['instance_id'])

    def test_results_stay_in_base_without_local_mirror_or_delete_permission(self):
        self.agent();client=Client(self.root/'client');client.config={'team':self.team,'origin':'client-test'}
        created=client.submit({'agent_id':'a','message':'Give the full answer'})['request'];ident=created['id']
        calls=[];answer={'evidence':'完整证据，不压缩为摘要。'*5000}
        def worker(command,prompt,*a,**kw):
            c=json.loads(prompt.split('\n',1)[1]);calls.append(c['request_id'])
            self.b.worker_call(c['request_id'],c['token'],'complete',{'result':answer})
            return subprocess.CompletedProcess(command,0,'','')
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=worker):
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                self.b.last_scan=0;self.b._team_scan_times={};self.b.tick()
                if self.b.requests() and self.b.get(ident)['state']=='completed':break
                time.sleep(.01)
        self.scan(self.b)
        cloud=self.media.get('results/'+ident+'.json');self.assertEqual(cloud['result'],answer)
        with patch('loop_anything.runtime.dispatch.time.time',return_value=time.time()+30*86400):
            publish_results(self.b,self.media,self.team['id'])
        self.assertEqual(self.media.get('results/'+ident+'.json')['result'],answer)
        row=self.b.get(ident)
        forged=core.envelope(dict(row,origin='client-test'),'result_read',{'receipt':'wrong'})
        with self.assertRaises(Conflict):self.b.receive(forged)
        packet=client.request_record(ident)
        with patch.object(self.media,'delete',side_effect=AssertionError('Automatic cloud deletion')):
            self.assertEqual(client.read(ident)['result'],answer)
            self.scan(self.b)
            self.assertEqual(client.read(ident)['result'],answer)
            self.b.receive(packet);self.scan(self.b)
        self.assertFalse((self.root/'client/results'/(ident+'.json')).exists())
        saved=json.loads((self.root/'client/requests'/(ident+'.json')).read_text())
        self.assertIn('request_ref',saved);self.assertNotIn('payload',saved)
        self.assertEqual(self.media.get('results/'+ident+'.json')['result'],answer)
        self.assertEqual(calls,[ident])
        self.assertFalse(list((self.root/'b.communication').rglob('*.json')))
        self.assertFalse(list(self.media.list('messages/'+self.b.settings()['instance_id'])))
        self.assertEqual(self.media.get('messages/'+packet['target']+'/'+packet['id']+'.json'),packet)
        with self.b.store.connection() as db:
            inbox=json.loads(db.execute('SELECT document FROM communication_inbox WHERE id=?',(packet['id'],)).fetchone()[0])
        self.assertIn('_message_digest',inbox);self.assertNotIn('payload',inbox)
        self.assertEqual(client.submit({'request_id':ident,'message':'Give the full answer','agent_id':'a'})['request']['result'],answer)

    def test_progress_coalesces_without_logs_and_logs_are_read_only_on_demand(self):
        ident='request-log';row={'id':ident,'origin':self.a.settings()['instance_id'],'executor':self.b.settings()['instance_id'],
            'group_id':self.team['id'],'scope_group_id':self.team['id'],'assignment_id':'assignment-test','kind':'assistance',
            'state':'running','message':'Work','source':{},'session':{'mode':'new'},'result_schema':{'type':'object'}}
        for c in (self.a,self.b):
            with c.transaction() as db:c.save(db,dict(row))
        with self.b.transaction() as db:db.execute('INSERT INTO communication_logs VALUES (?,?,?)',(ident,1,'ABCDEFGHIJK'))
        with patch.object(self.b.engine.terminals,'read',side_effect=AssertionError('Automatic terminal log transfer')):
            for i in range(20):
                with self.b.transaction() as db:
                    current=self.b.get(ident,db);current['progress']={'text':str(i)};self.b.save(db,current)
                self.b.send_progress(ident)
        with self.b.store.connection() as db:
            rows=[json.loads(r[0]) for r in db.execute('SELECT document FROM communication_outbox')]
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['payload']['logs'],[])
        self.scan(self.b,self.a,self.a,self.b)
        self.assertEqual(self.a.get(ident)['progress']['text'],'19')
        pending=self.a.read(ident,include_logs=True,max_chars=4)['request']
        self.assertTrue(pending['logs_pending'])
        self.scan(self.a,self.b,self.b,self.a)
        page=self.a.read(ident,include_logs=True,max_chars=4)['request']
        self.assertFalse(page['logs_pending']);self.assertEqual(page['logs'],[{'sequence':1,'text':'ABCD'}])
        self.assertEqual(page['log_offset'],4)
        for _ in range(3):self.scan(self.a,self.b)
        self.assertFalse(any(r['fields']['bucket'].startswith('messages/') for r in self.media.records.values()))
        self.assertFalse(any(r['fields']['bucket'].startswith('archive/') for r in self.media.records.values()))

    def test_status_metadata_only_changes_do_not_republish_large_result(self):
        row={'id':'request-stable','origin':'client','executor':self.b.settings()['instance_id'],
            'group_id':self.team['id'],'assignment_id':'assignment-stable','state':'completed','kind':'assistance',
            'source':{},'session':{'mode':'new'},'message':'Work','dispatch_client':True,'result':{'full':'答案'*10000}}
        with self.b.transaction() as db:self.b.save(db,row)
        publish_results(self.b,self.media,self.team['id'])
        ids=set(self.media.records)
        with self.b.transaction() as db:self.b.save(db,self.b.get(row['id'],db))
        with patch.object(self.media,'put',side_effect=AssertionError('Metadata-only publication')):
            publish_results(self.b,self.media,self.team['id'])
        self.assertEqual(set(self.media.records),ids)

    def test_small_status_updates_and_replayed_deleted_message_keep_protocol_identity(self):
        key='results/request-small.json'
        self.media.put(key,{'state':'assigned'});ids=set(self.media.records)
        self.media.put(key,{'state':'running'});self.assertEqual(set(self.media.records),ids)
        message={'id':'message-replay','kind':'ack'};key='messages/worker/message-replay.json'
        self.media.put(key,message,immutable=True);self.media.delete(key)
        self.media.put(key,message,immutable=True)
        self.assertEqual(self.media.get(key),message)

    def test_old_version_cleanup_failure_does_not_fail_new_publication(self):
        key='results/request-prune.json'
        self.media.put(key,{'answer':'old'*40000})
        write=self.media.write_record
        def fail_delete(fields,record_id=None):
            if fields.get('bucket','').startswith('history/'):raise OSError('history update unavailable')
            return write(fields,record_id)
        with patch.object(self.media,'write_record',side_effect=fail_delete):
            self.media.put(key,{'answer':'new'*40000})
        self.assertEqual(self.media.get(key),{'answer':'new'*40000})
        self.assertTrue(self.media.cleanup_error)
        self.assertEqual(len(self.media.rows('key',key)),2)
        self.media.retry_cleanup()
        self.assertFalse(self.media.cleanup_error)
        self.assertEqual(len(self.media.rows('key',key)),1)

    def test_shared_file_reference_neither_uploads_nor_deletes_the_artifact(self):
        artifact=self.root/'complete-report.txt'
        content='完整证据'*10000
        artifact.write_text(content)
        result={'id':'request-reference','result':{'artifacts':[
            {'path':str(artifact),'description':'完整报告'},
            {'shared_root':'team','relative_path':'research/evidence.csv'}]}}
        key='results/request-reference.json'
        with patch.object(self.media,'upload_attachment',side_effect=AssertionError('Unexpected file upload')), \
             patch.object(self.media,'download_attachment',side_effect=AssertionError('Unexpected attachment download')), \
             patch.object(Path,'read_bytes',side_effect=AssertionError('Unexpected referenced file read')):
            self.media.put(key,result)
            self.assertEqual(self.media.get(key),result)
            self.media.delete(key)
        self.assertEqual(artifact.read_text(),content)
