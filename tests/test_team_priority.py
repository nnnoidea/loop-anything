"""Media preference must never move an already published request or bound Run."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_dispatch_transport import Client, FakeBase, core
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.store import Store
from loop_anything.runtime.collaboration import ensure_loop


class TeamPriorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.base=FakeBase().ensure()
        self.base.config.update(id='team-base',name='Base',enabled=True,link='https://example/base/test')
        self.nas=core.join(str(self.root/'nas'),create=True)
        self.client=Client(self.root/'client')
        def join(link,**kwargs):
            return dict(self.base.config) if link.startswith('https:') else core.join(link,**kwargs)
        def connect(team):
            return self.base if team.get('transport')=='feishu_base' else core.connect(team)
        for target,side_effect in [('dispatch.join',join),('dispatch.connect',connect),
                ('loop_anything.runtime.team_transport.connect',connect)]:
            mocked=patch(target,side_effect=side_effect);mocked.start();self.addCleanup(mocked.stop)
        for media in (self.base,core.connect(self.nas)):
            media.put('members/worker.json',{'instance_id':'worker','revision':'one','updated_at':0,'agents':[
                {'id':'papers','instance_id':'worker','name':'论文 Agent','description':'Find papers','enabled':True}]})

    def join_base(self):
        self.client.configure(self.base.config['link'])

    def join_nas(self):
        self.client.configure(self.nas['path'])

    def finish(self,ident):
        packet=self.client.request_record(ident)
        team=self.client.request_team(ident)
        media=self.base if team.get('transport')=='feishu_base' else core.connect(team)
        media.put('results/'+ident+'.json',dict(packet['payload'],state='completed',
            result={'answer':team['id']},native_session={'provider':'custom','id':'session-'+ident}))

    def test_join_order_keeps_base_preferred_and_leave_selects_nas(self):
        for order in ((self.join_nas,self.join_base),(self.join_base,self.join_nas)):
            for join in order:join()
            self.assertEqual(self.client.team()['id'],'team-base')
            self.assertEqual(len(self.client.teams()),2)
        self.assertEqual(self.client.agents(group_id=self.nas['id'])['team']['id'],self.nas['id'])
        self.client.leave('team-base')
        self.assertEqual(Client(self.client.directory).team()['id'],self.nas['id'])
        self.join_base();self.assertEqual(self.client.team()['id'],'team-base')
        self.client.config['teams']['second-base']=dict(self.base.config,id='second-base')
        self.join_nas()
        self.assertEqual(self.client.team()['id'],'team-base')

    def test_existing_requests_and_followups_keep_original_media_after_rejoin(self):
        self.join_nas()
        old=self.client.submit({'agent_id':'papers','message':'old'})['request']['id']
        original=self.client.request_record(old)
        self.join_base()
        new=self.client.submit({'agent_id':'papers','message':'new'})['request']['id']
        self.finish(old);self.finish(new)
        waited=self.client.wait({'request_ids':[new,old],'timeout':0})
        self.assertEqual([r['result']['answer'] for r in waited['requests']],['team-base',self.nas['id']])
        # Base result compaction and a fresh client retain the original connection.
        self.join_nas();self.client=Client(self.client.directory)
        self.assertEqual(self.client.read(new)['result']['answer'],'team-base')
        self.assertEqual(self.client.submit({'request_id':old,'message':'old'})['request']['id'],old)
        self.assertEqual(self.client.request_record(old),original)
        followup=self.client.control({'request_id':old,'action':'followup','message':'continue'})['request']['id']
        self.assertEqual(self.client.request_team(followup)['id'],self.nas['id'])
        self.assertEqual(self.client.request_record(followup)['payload']['session']['native_id'],'session-'+old)
        self.client.control({'request_id':followup,'action':'cancel'})
        messages=list(core.connect(self.nas).list('messages/worker'))
        self.assertTrue(any(p['kind']=='cancel' and p['request_id']==followup for _,p in messages))
        self.assertFalse(any(p['request_id']==followup for _,p in self.base.list('messages/worker')))

    def test_legacy_connection_and_raw_envelope_still_resolve_original_team(self):
        self.join_nas()
        ident=self.client.submit({'agent_id':'papers','message':'legacy'})['request']['id']
        packet=self.client.request_record(ident)
        core.atomic_json(self.client.directory/'requests'/(ident+'.json'),packet)
        self.client.config={'team':self.nas,'origin':self.client.config['origin']}
        core.atomic_json(self.client.file,self.client.config)
        self.client=Client(self.client.directory)
        self.join_base();self.finish(ident)
        self.assertEqual(self.client.read(ident)['result']['answer'],self.nas['id'])

    def test_base_error_never_publishes_or_reads_from_nas(self):
        self.join_nas();self.join_base()
        with patch.object(self.base,'list',side_effect=ValueError('permission denied')):
            with self.assertRaisesRegex(ValueError,'permission denied'):
                self.client.submit({'agent_id':'papers','message':'new'})
        self.assertFalse(list(core.connect(self.nas).list('messages/worker')))
        ident=self.client.submit({'agent_id':'papers','message':'published'})['request']['id']
        self.client.leave('team-base')
        with patch.object(self.base,'get',side_effect=ValueError('network failed')):
            with self.assertRaisesRegex(ValueError,'network failed'):self.client.read(ident)
            with self.assertRaisesRegex(ValueError,'network failed'):
                self.client.submit({'request_id':ident,'message':'published'})
        self.assertFalse(list(core.connect(self.nas).list('messages/worker')))

    def test_platform_defaults_and_old_run_scope_survive_default_change(self):
        engine=Engine(Store(self.root/'platform.db'));self.addCleanup(engine.close);comm=engine.communication
        comm.config('team',link=self.nas['path'])
        key=ensure_loop(comm.store)
        old=comm.store.create(key,'Old NAS run',{'message':'before'},acquire=True)
        token=old['agent_sessions'][0]['token']
        first=comm.request({'location':'group','agent_id':'papers','message':'old request'})['request']
        with patch('loop_anything.runtime.team_transport.join',return_value=dict(self.base.config)):
            comm.config('team',link=self.base.config['link'])
        comm.config('team',link=self.nas['path'])
        self.assertEqual(comm.settings()['default_team'],'team-base')
        new=comm.store.create(key,'New Base run',{'message':'after'})
        self.assertEqual(new['communication_group'],'team-base')
        self.assertEqual(comm.run_group(comm.store.get(old['id'])),self.nas['id'])
        source=comm.request({'location':'group','agent_id':'papers','message':'scoped',
            'source':{'run_id':old['id'],'task_id':old['loop_definition']['seed']['id']},'token':token})['request']
        self.assertEqual(source['group_id'],self.nas['id'])
        continued=comm.request({'location':'group','agent_id':'papers','message':'next',
            'collaboration_id':first['collaboration']['run_id']})['request']
        self.assertEqual(continued['group_id'],self.nas['id'])
        retry=comm.request({'request_id':first['id'],'location':'group','agent_id':'papers','message':'old request'})['request']
        self.assertEqual(retry['id'],first['id'])
        comm.config('bind_loop',loop_key=key,group_id=self.nas['id'])
        explicit=comm.store.create(key,'Explicit NAS',{'message':'explicit'})
        self.assertEqual(explicit['communication_group'],self.nas['id'])
        comm.config('bind_loop',loop_key=key,group_id=None)
        self.assertIsNone(comm.store.create(key,'Unbound',{'message':'none'})['communication_group'])
        comm.config('leave',group_id='team-base')
        self.assertEqual(comm.settings()['default_team'],self.nas['id'])


if __name__=='__main__':unittest.main()
