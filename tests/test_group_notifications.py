"""Group notifications use a designated machine and the real cc-connect adapter.

The cc-connect executable is a local test double. No real chat is contacted.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_communication as fixtures
from loop_anything.runtime.model import Conflict
from loop_anything.runtime.communication_notifications import deliver


class GroupNotificationTests(unittest.TestCase):
    setUp=fixtures.CommunicationTests.setUp
    tearDown=fixtures.CommunicationTests.tearDown
    groups=fixtures.CommunicationTests.groups
    cycle=fixtures.CommunicationTests.cycle
    agent=fixtures.CommunicationTests.agent

    def configure(self, sender=None, level='key'):
        sender=sender or self.c
        self.gid=self.groups();self.log=self.root/'messages.jsonl';self.fail_file=self.root/'fail-send'
        executable=self.root/'cc-connect-test'
        executable.write_text('#!'+sys.executable+'\nimport sys,json\nfrom pathlib import Path\np=Path('+repr(str(self.log))+')\nwith p.open("a") as f:f.write(json.dumps({"argv":sys.argv[1:],"text":sys.stdin.read()})+"\\n")\nsys.exit(1 if Path('+repr(str(self.fail_file))+').exists() else 0)\n')
        executable.chmod(0o700)
        adapter=Path(__file__).resolve().parents[1]/'skills/loop-anything-platform/scripts/notify_cc_connect.py'
        sender.store.notification_channels({'feishu':{'label':'研究群','channel':'飞书','identity':'research-project','destination':'feishu-chat',
            'command':[sys.executable,str(adapter),'--executable',str(executable),'--data-dir',str(self.root/'cc-data')] }},revision=0)
        binding=sender.config('group_notifications',group_id=self.gid,notification_route='feishu',notification_level=level)['notification_binding']
        for comm in (self.a,self.b,self.c):comm.last_scan=0;comm.scan()
        return binding

    def completed_request(self, **args):
        row=self.a.request(dict(location='group',group_id=self.gid,agent_id='papers',message='论文分析完成',**args))['request']
        with self.a.transaction() as db:
            current=self.a.get(row['id'],db);current.update(state='completed',result={'summary':'实验支持该结论'});self.a.save(db,current)
        return row['id']

    def test_third_machine_cc_connect_delivery_receipt_and_duplicate_messages(self):
        binding=self.configure();ident=self.completed_request()
        self.cycle(lambda:any(n['status']=='delivered' for n in self.a.get(ident).get('notifications',[])))
        notes=self.a.get(ident)['notifications'];self.assertEqual(len(notes),1)
        self.assertEqual(notes[0]['group_binding']['sender_instance'],self.c.settings()['instance_id'])
        sent=[json.loads(x) for x in self.log.read_text().splitlines()]
        self.assertEqual(len(sent),1);self.assertIn('research-project',sent[0]['argv']);self.assertIn('feishu-chat',sent[0]['argv'])
        self.assertIn('实验支持',sent[0]['text'])
        self.assertIn('论文分析完成',sent[0]['text'])  # Fast completion can be the first observed state.
        packet=next(json.loads(p.read_text()) for p in (self.root/'nas'/'messages'/binding['sender_instance']).glob('*.json') if json.loads(p.read_text()).get('kind')=='notification_deliver')
        self.c.receive(packet)
        duplicate=dict(packet,id='duplicate-delivery');self.c.receive(duplicate)
        deliver(self.c)
        self.assertEqual(len(self.log.read_text().splitlines()),1)
        self.assertEqual(self.c.store.list(),[])
        shared=''.join(p.read_text() for p in (self.root/'nas').rglob('*.json'))
        self.assertNotIn(str(self.root/'cc-connect-test'),shared)
        self.assertNotIn('"command"',shared)
        with self.assertRaises(Conflict):self.c.receive(dict(packet,id='changed-delivery',payload=dict(packet['payload'],payload={'message':'changed'})))

    def test_lifecycle_messages_reference_same_request_without_repeating_body(self):
        self.configure()
        message='请检索这次实验相关的论文，并比较不同方法的假设'
        ident=self.a.request(dict(location='group',group_id=self.gid,agent_id='papers',message=message))['request']['id']
        for index,state in enumerate(('pending','running','completed'),1):
            with self.a.transaction() as db:
                row=self.a.get(ident,db);row['state']=state
                if state=='completed':row['result']={'summary':'找到三篇相关论文'}
                self.a.save(db,row)
            self.cycle(lambda:len([n for n in self.a.get(ident).get('notifications',[]) if n['status']=='delivered'])==index)
        sent=[json.loads(line)['text'] for line in self.log.read_text().splitlines()]
        self.assertEqual(len(sent),3)
        self.assertIn(message,sent[0])
        for text in sent[1:]:self.assertNotIn(message,text)
        for text in sent:
            self.assertEqual(text.count(ident),1)
            self.assertNotIn('通知：notice-',text)
        self.assertIn('开始执行',sent[1])
        self.assertIn('找到三篇相关论文',sent[2])
        self.assertEqual(self.a.get(ident)['message'],message)

    def test_offline_sender_waits_and_binding_changes_do_not_redirect_existing_work(self):
        binding=self.configure();ident=self.completed_request()
        self.a.deliver_notifications();self.a.scan()
        self.assertEqual(self.a.get(ident)['notifications'][0]['status'],'awaiting_delivery')
        self.assertFalse(self.log.exists())
        self.c.config('group_notifications',group_id=self.gid,binding_id=binding['id'],enabled=False)
        self.a.last_scan=0;self.a.scan()
        newer=self.completed_request()
        self.assertNotIn('notification_binding',self.a.get(newer))
        self.cycle(lambda:self.a.get(ident)['notifications'][0]['status']=='delivered')
        self.assertEqual(len(self.log.read_text().splitlines()),1)
        self.assertEqual(self.a.get(ident)['notifications'][0]['group_binding']['id'],binding['id'])

    def test_failure_explicit_retry_and_sender_restart_never_blindly_resends(self):
        self.configure();self.fail_file.touch();ident=self.completed_request()
        self.cycle(lambda:any(n['status']=='fault' for n in self.a.get(ident).get('notifications',[])))
        notice=self.a.get(ident)['notifications'][0];self.assertEqual(len(self.log.read_text().splitlines()),1)
        self.fail_file.unlink()
        self.a.control(ident,'retry_notification',notification_id=notice['id'])
        self.cycle(lambda:self.a.get(ident)['notifications'][0]['status']=='delivered')
        self.assertEqual(self.a.get(ident)['notifications'][0]['attempt'],2)
        self.assertEqual(len(self.log.read_text().splitlines()),2)
        # Simulate a crash after the durable sending marker but before any known receipt.
        other=self.completed_request();self.a.deliver_notifications();self.a.last_scan=0;self.a.scan();self.c.last_scan=0;self.c.scan()
        with self.c.transaction() as db:
            row=json.loads(db.execute("SELECT document FROM communication_deliveries WHERE json_extract(document,'$.request_id')=?",(other,)).fetchone()[0])
            row['status']='sending';db.execute('UPDATE communication_deliveries SET document=? WHERE id=?',(json.dumps(row),row['id']))
        self.c.recover()
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=AssertionError('Unknown delivery must not auto-retry')):
            self.cycle(lambda:self.a.get(other)['notifications'][0]['status']=='fault')
        self.assertIn('outcome unknown',self.a.get(other)['notifications'][0]['error'])

    def test_local_sender_uses_same_receipts_and_explicit_route_can_override_group(self):
        binding=self.configure(self.a,level='detailed');ident=self.completed_request()
        self.cycle(lambda:any(n['status']=='delivered' for n in self.a.get(ident).get('notifications',[])))
        self.assertEqual(self.a.get(ident)['notification_level'],'detailed')
        override=self.completed_request(notification_route='workspace')
        self.assertNotIn('notification_binding',self.a.get(override))
        continued=self.a.control(ident,'followup',message='继续',resume=False)['request']
        self.assertEqual(continued['notification_binding']['id'],binding['id'])
        with self.assertRaises(Conflict):self.a.config('group_notifications',group_id=self.gid,notification_route='feishu')

    def test_new_identity_cannot_send_copied_queue_or_publish_old_receipts(self):
        self.configure();ident=self.completed_request()
        self.a.deliver_notifications();self.a.last_scan=0;self.a.scan();self.c.last_scan=0;self.c.scan()
        with self.c.store.connection() as db:
            old_outbox=[json.loads(r[0]) for r in db.execute('SELECT document FROM communication_outbox')]
        self.assertTrue(old_outbox)
        self.c.identity_conflict=True
        self.c.config('identity',name='new-copy',regenerate=True)
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=AssertionError('Copied queue must not send')):
            deliver(self.c)
            self.c.last_scan=0;self.c.scan()
        self.assertFalse(self.log.exists())
        for packet in old_outbox:
            self.assertFalse((self.root/'nas'/'messages'/packet['target']/(packet['id']+'.json')).exists())


if __name__=='__main__':unittest.main()
