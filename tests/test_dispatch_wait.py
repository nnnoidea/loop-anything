import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from test_dispatch_transport import Client, FakeBase, core
from dispatch import wait_requests, directory_result


class DispatchWaitTests(TestCase):
    def test_wait_collects_results_by_id_and_does_not_reread_finished_work(self):
        calls=[];clock=[0]
        def read(ident):
            calls.append(ident)
            state='completed' if ident=='a' or clock[0]>=2 else 'running'
            return {'id':ident,'state':state,'result':{'answer':ident} if state=='completed' else None}
        with patch('dispatch.time.monotonic',side_effect=lambda:clock[0]), \
             patch('dispatch.time.sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)):
            result=wait_requests(read,['a','b'],timeout=5,poll_interval=1)
        self.assertTrue(result['finished']);self.assertFalse(result['timed_out'])
        self.assertEqual([r['result']['answer'] for r in result['requests']],['a','b'])
        self.assertEqual(calls.count('a'),1)

    def test_wait_timeout_only_returns_last_status(self):
        with tempfile.TemporaryDirectory() as folder:
            client=Client(Path(folder));client.config={'team':{'id':'team-wait','path':folder,'transport':'nas'}}
            with patch.object(client,'read',return_value={'id':'r','state':'running'}), \
                 patch.object(client,'control',side_effect=AssertionError('Must not cancel')), \
                 patch.object(client,'submit',side_effect=AssertionError('Must not republish')):
                answer=client.wait({'request_id':'r','timeout':0})
        self.assertTrue(answer['timed_out']);self.assertEqual(answer['request']['state'],'running')

    def test_failed_work_returns_without_waiting_for_timeout(self):
        result=wait_requests(lambda i:{'id':i,'state':'failed','error':'worker failed'},['r'],timeout=10)
        self.assertTrue(result['finished']);self.assertFalse(result['timed_out'])
        self.assertEqual(result['request']['error'],'worker failed')

    def test_directory_resolves_names_even_offline_but_never_guesses_ids(self):
        agents=[{'id':'papers','instance_id':'machine-a','name':'论文 Agent','description':'查论文','online':False}]
        self.assertEqual(core.choose(agents,name='论文 Agent')['id'],'papers')
        self.assertEqual(core.choose(agents,'papers','machine-a')['instance_id'],'machine-a')
        with self.assertRaises(ValueError):core.choose([],agent_id='papers',instance_id='machine-a')
        with self.assertRaises(ValueError):core.choose(agents+[dict(agents[0],instance_id='machine-b')],name='论文 Agent')
        public=directory_result({'agents':[dict(agents[0],notification_bot={'project':'private-routing'})]},name='论文 Agent')
        self.assertEqual(public['agents'],agents)

    def test_named_dispatch_retry_cannot_change_recipient(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);client=Client(root/'client');client.configure(str(root/'nas'),create=True)
            client.media().put('members/machine.json',{'updated_at':0,'agents':[
                {'id':'papers','instance_id':'machine','name':'论文 Agent','description':'查论文'}]})
            args={'request_id':'named-retry','agent_name':'论文 Agent','message':'help'}
            first=client.submit(args)
            self.assertEqual(client.submit(args)['request']['id'],first['request']['id'])
            with self.assertRaisesRegex(ValueError,'different Agent name'):
                client.submit(dict(args,agent_name='评审 Agent'))

    def test_readable_directory_and_full_reply_are_not_raw_protocol_views(self):
        media=FakeBase().ensure()
        member={'instance_id':'machine','updated_at':1,'agents':[
            {'id':'papers','instance_id':'machine','name':'论文 Agent','description':'查论文'},
            {'id':'review','instance_id':'machine','name':'评审 Agent','description':'评审实验'}]}
        media.put('members/machine.json',member)
        rows=media.rows('bucket','agents/machine')
        self.assertEqual({r['fields']['主要任务'] for r in rows},{'查论文','评审实验'})
        for r in rows:self.assertEqual(r['fields']['记录类型'],'Agent')
        full='详细回答。'*4000
        media.put('results/request-one.json',{'id':'request-one','state':'completed','result':{'answer':full}})
        row=media.rows('key','results/request-one.json')[0]
        self.assertIn(full,row['fields']['完整回复'])
        self.assertFalse(row['fields'].get('payload'))
        self.assertEqual(media.get('results/request-one.json')['result']['answer'],full)
        media.put('members/machine.json',dict(member,updated_at=2,agents=member['agents'][:1]))
        retired=media.get('agents/machine/review.json')
        self.assertFalse(retired['enabled'])

    def test_non_bmp_text_uses_attachment_before_exceeding_cell_capacity(self):
        media=FakeBase().ensure()
        answer={'result':{'answer':'😀'*50000}}
        media.put('results/emoji.json',answer)
        row=media.rows('key','results/emoji.json')[0]
        self.assertTrue(row['fields']['payload'])
        self.assertEqual(media.get('results/emoji.json'),answer)
