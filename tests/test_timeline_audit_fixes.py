"""Regression paths from the five Timeline continuation audit findings."""
import base64
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_business_state as fixture
from test_timeline_runtime import task_spec
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime import business_state, timelines, work
from loop_anything.runtime.model import Conflict
from loop_anything.packaging.packages import install, make_archive


class TimelineAuditTests(unittest.TestCase):
    def setUp(self):
        self.c=fixture.BusinessStateTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.store=self.c.store;self.engine=self.c.engine

    def test_waiting_state_writer_and_dependencies_survive_two_continuations(self):
        c=self.c
        e=c.base.start()
        c.base.submit(e,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'},
            'tasks':[task_spec('experiment','wait',outputs={'text':'result'}),
                task_spec('downstream','produce',inputs={'source':{'literal':'later'}},outputs={'text':'later'},after=['experiment'])]})
        c.engine.tick(c.base.id);old=c.store.get(c.base.id);second=c.second(old)
        # Complete only the new entry, then interrupt again before the original job finishes.
        root=next(e for e in second['executions'] if e['node']=='reason')
        c.base.submit(root,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'}})
        third=c.store.create(second['loop_key'],'again',timeline_id=old['timeline_id'],continue_run_id=second['id'])
        c.engine.tick(third['id']);third=c.store.get(third['id'])
        self.assertEqual(third['tasks']['experiment']['continuation_source'],{'run_id':old['id'],'task_id':'experiment'})
        self.assertEqual(third['tasks']['downstream']['spec']['after'],['experiment'])
        self.assertFalse(any(e['task_id']=='downstream' for e in third['executions']))
        with c.store.edit(old['id']) as run:
            attempt=next(e for e in run['executions'] if e['node']=='wait')
            c.engine.timeline_runtime.report_in_run(run,attempt,{'event':'completed','report_id':'experiment-result',
                'envelope':{'outputs':{'text':'original'},'state':[{'type':'judgment','id':'receipt','value':'experiment finished'}]}},'engine')
        c.engine.tick(third['id']);current=c.store.get(third['id'])
        self.assertEqual(current['tasks']['experiment']['status'],'completed')
        self.assertEqual(current['tasks']['downstream']['status'],'decision')
        self.assertEqual(business_state.read(c.store,old['timeline_id'])['records'][0]['value'],'experiment finished')
        self.assertEqual(len(current['records']['result']),1)
        self.assertEqual(len([e for e in c.store.get(old['id'])['executions'] if e['node']=='wait']),1)

    def test_mixed_existing_and_future_inputs_keep_exact_revisions(self):
        c=self.c;c.base.bp['nodes']['join']['inputs']={'items':{'type':'array','items':{'type':'string'}}}
        e=c.base.start()
        c.base.submit(e,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'},
            'tasks':[task_spec('experiment','wait',outputs={'text':'future'}),
                task_spec('join','join',inputs={'items':{'records':['a','future']}},outputs={'ok':'joined'})]})
        c.engine.tick(c.base.id);old=c.store.get(c.base.id);new=c.second(old)
        root=next(e for e in new['executions'] if e['node']=='reason')
        c.base.submit(root,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'NEW','b':'B'}})
        c.engine.event(old['id'],'future','signal',{'text':'future'});c.engine.tick(old['id']);c.engine.tick(new['id'])
        current=c.store.get(new['id']);joined=next(e for e in current['executions'] if e['task_id']=='join')
        self.assertEqual(joined['inputs']['items'],['A','future'])
        self.assertEqual(current['tasks']['join']['spec']['inputs']['items']['revisions'],[1,1])

    def test_dispatched_input_keeps_execution_version_even_if_source_has_newer_result(self):
        c=self.c;c.base.bp['nodes']['wait']['inputs']={'source':{'type':'string'}}
        c.base.bp['plans']['experiment']['steps']['observe']['inputs']={'source':{'literal':'planned'}}
        e=c.base.start()
        revise=task_spec('revise','produce',inputs={'source':{'literal':'new input'}},outputs={'text':'a'})
        revise['outputs']['text']['expected_revision']=1
        c.base.submit(e,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'},
            'tasks':[task_spec('experiment','wait',inputs={'source':{'record':'a'}},outputs={'text':'result'}),revise]})
        c.engine.tick(c.base.id)
        editor=next(e for e in c.store.get(c.base.id)['executions'] if e['task_id']=='revise')
        c.base.submit(editor,{'outputs':{'text':'changed after dispatch'}})
        old=c.store.get(c.base.id);new=c.second(old)
        info=RunTools(c.store,new['id']).call('read_task',{'task_id':'experiment'})
        self.assertEqual(info['inputs']['source'],'A')
        self.assertEqual(info['sources']['source']['revision'],1)
        self.assertEqual(new['records']['a'][-1]['revision'],2)

    def test_proxy_and_task_wait_use_original_result_after_later_revision(self):
        c=self.c;old=c.first(waiting=True);new=c.second(old)
        root=next(e for e in new['executions'] if e['node']=='reason')
        revision=task_spec('revise','produce',inputs={'source':{'literal':'newer'}},outputs={'text':'result'})
        revision['outputs']['text']['expected_revision']=1
        c.base.submit(root,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'},'tasks':[revision]})
        c.engine.tick(new['id']);edit=next(e for e in c.store.get(new['id'])['executions'] if e['task_id']=='revise')
        c.engine.event(old['id'],'original','signal',{'text':'original'});c.engine.tick(old['id'])
        c.base.submit(edit,{'outputs':{'text':'newer'}});c.engine.tick(new['id'])
        current=c.store.get(new['id']);proxy=next(e for e in current['executions'] if e['task_id']=='experiment')
        self.assertEqual(proxy['outputs'],{'text':'original'});self.assertEqual(proxy['record_refs']['text']['revision'],1)
        self.assertEqual(len(current['records']['result']),2)
        for ident in (old['id'],new['id']):
            self.assertEqual(work.observe(c.store,{'kind':'task','id':ident,'task_id':'experiment'})['outputs'],{'text':'original'})
        again=c.store.create(new['loop_key'],'again',timeline_id=old['timeline_id'],continue_run_id=new['id'])
        self.assertEqual(work.observe(c.store,{'kind':'task','id':again['id'],'task_id':'experiment'})['outputs'],{'text':'original'})

    def test_retained_pending_writer_can_commit_next_version_of_original_record(self):
        c=self.c;e=c.base.start()
        revise=task_spec('revise','produce',inputs={'source':{'literal':'next'}},outputs={'text':'result'},after=['experiment'])
        revise['outputs']['text']['expected_revision']=1
        c.base.submit(e,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'},
            'tasks':[task_spec('experiment','wait',outputs={'text':'result'}),revise]})
        c.engine.tick(c.base.id);old=c.store.get(c.base.id);new=c.second(old)
        c.engine.event(old['id'],'first','signal',{'text':'first'});c.engine.tick(old['id']);c.engine.tick(new['id'])
        attempt=next(e for e in c.store.get(new['id'])['executions'] if e['task_id']=='revise')
        c.base.submit(attempt,{'outputs':{'text':'next'}})
        rows=c.store.get(new['id'])['records']['result']
        self.assertEqual([r['value'] for r in rows],['first','next'])
        self.assertEqual([r['type'] for r in rows],['text','text'])

    def test_resources_follow_original_package_locally_and_remotely(self):
        from loop_anything.runtime.agent_prompt import task_context
        from loop_anything.runtime.executor_resources import snapshot
        c=self.c;bp=copy.deepcopy(c.base.bp)
        bp['nodes']['produce']['skills']=[{'name':'worker','path':'skills/worker.md'}]
        bp['handbook']={'name':'manual','path':'skills/manual.md'}
        assets={'skills/worker.md':(b'Original worker',False),'skills/manual.md':(b'Original manual',False)}
        first=install(c.store,make_archive({'loop_definition':bp,'implementations':c.base.implementations},assets))['key']
        old=c.store.create(first,'old');c.base.id=old['id'];c.engine.tick(old['id'])
        c.base.submit(c.store.get(old['id'])['executions'][0],{'settings':{'objective':'Keep work'},'outputs':{'a':'A','b':'B'},
            'tasks':[task_spec('pending','produce',inputs={'source':{'literal':'data'}},outputs={'text':'prepared'})]})
        bp['version']='2';bp['nodes'].pop('produce');bp['nodes']['init']['plan_nodes'].remove('produce')
        impl=copy.deepcopy(c.base.implementations);impl.pop('produce')
        for asset_case,new_assets in [('missing',{'skills/manual.md':(b'New manual',False)}),('changed',{'skills/manual.md':(b'New manual',False),'skills/worker.md':(b'Wrong worker',False)})]:
            # Each branch uses a fresh source Run because takeover has a single current Run.
            with self.subTest(asset_case=asset_case):
                bp['version']=asset_case
                key=install(c.store,make_archive({'loop_definition':bp,'implementations':impl},new_assets))['key']
                new=c.store.create(key,'optimized',timeline_id=old['timeline_id'],continue_run_id=old['id'])
                c.engine.tick(new['id']);new=c.store.get(new['id'])
                attempt=next(e for e in new['executions'] if e['task_id']=='pending')
                info=RunTools(c.store,new['id'],attempt['token']).call('read_task',{'task_id':'pending'})
                self.assertEqual(Path(info['skills'][0]['resolved_path']).read_text(),'Original worker')
                context=task_context(c.store,new,attempt,'http://example.invalid','pending')
                self.assertEqual(Path(context['handbook']['resolved_path']).read_text(),'Original manual')
                bundle=snapshot(c.store,{'kind':'task','run_id':new['id'],'execution_id':attempt['id']})
                self.assertEqual(bundle['key'],first)
                self.assertEqual({f['path']:base64.b64decode(f['base64']) for f in bundle['files']}['skills/worker.md'],b'Original worker')
                comm=c.engine.communication
                comm.config('agent',agent_id='retained',task_confirmed=True,agent={'name':'retained','description':'Observe test work',
                    'implementation':{'kind':'agent','command':[sys.executable,'-c','pass']}})
                dispatched=copy.deepcopy(attempt);dispatched['implementation']['dispatch']={'location':'local','agent_id':'retained'}
                comm.submit_node(new['id'],dispatched,new)
                request_id='node-'+attempt['id']
                with comm.transaction() as db:
                    request=comm.get(request_id,db);request.update(state='running',worker_token='test-token');comm.save(db,request)
                self.assertEqual(Path(comm.get(request_id)['context']['handbook']['resolved_path']).read_text(),'Original manual')
                for call_id,tool,args in [('asset','read_asset',{'path':'skills/worker.md'}),
                    ('state','read_business_state',{'timeline_id':new['timeline_id']}),
                    ('wrong','read_business_state',{'timeline_id':'another-timeline'})]:
                    comm.queue_rpc(request_id,{'id':call_id,'tool':tool,'arguments':args})
                    comm.process_rpcs()
                replies=comm.get(request_id)['rpc']
                self.assertEqual(base64.b64decode(replies['asset']['result']['base64']),b'Original worker')
                self.assertEqual(replies['state']['state'],'completed')
                self.assertEqual(replies['wrong']['state'],'failed')
                self.assertIn('assigned Timeline',replies['wrong']['error'])
                with comm.transaction() as db:
                    request=comm.get(request_id,db);request['state']='completed';comm.save(db,request)
                # A decision without a native process is explicitly released before another switch.
                from loop_anything.interfaces.agent_tasks import release_in_run
                with c.store.edit(new['id']) as current:
                    release_in_run(current,attempt['token'])
                    current['tasks']['pending']['status']='planned';current['tasks']['pending']['execution_id']=None
                    for e in current['executions']:
                        if e['id']==attempt['id']:e['status']='cancelled'
                    initializer=next(e for e in current['executions'] if e['task_id']!='pending')
                    release_in_run(current,initializer['token']);initializer['status']='cancelled'
                    current['tasks'][initializer['task_id']]['status']='cancelled'
                old=c.store.get(new['id'])

    def test_whole_work_wait_follows_current_run_but_task_wait_stays_exact(self):
        from loop_anything.runtime.run_library import list_runs
        c=self.c;old=c.first(waiting=True);new=c.second(old)
        with work.transaction(c.store) as db:
            work.put(db,'wait',dict(id='wait',timeline_id=old['timeline_id'],session_id='test',sources={'r':{'kind':'run','id':old['id']}},
                condition={'op':'eq','args':[{'path':'r.status'},'completed']},state='waiting'))
        self.assertEqual(work.poll_wait(c.store,'wait')['state'],'waiting')
        self.assertEqual(work.observe(c.store,{'kind':'run','id':old['id']})['id'],new['id'])
        self.assertEqual(work.observe(c.store,{'kind':'task','id':old['id'],'task_id':'experiment'})['status'],'waiting')
        c.engine.event(old['id'],'done','signal',{'text':'done'});c.engine.tick(old['id']);c.engine.tick(new['id'])
        root=next(e for e in c.store.get(new['id'])['executions'] if e['node']=='reason')
        c.base.submit(root,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed','termination_signal':'Done'},'outputs':{'a':'A','b':'B'}})
        c.engine.tick(new['id'])
        self.assertEqual(work.poll_wait(c.store,'wait')['state'],'ready')
        self.assertEqual(RunTools(c.store,old['id']).call('read_run',{})['run']['status'],'continued')
        self.assertEqual(RunTools(c.store,old['id']).call('read_run', {'view':'snapshot'})['status'],'continued')
        self.assertEqual(list_runs(c.store,status='continued')['runs'][0]['id'],old['id'])
        self.assertNotIn(old['id'],[r['id'] for r in list_runs(c.store,status='running')['runs']])
        self.assertEqual(next(r['status'] for r in timelines.read(c.store,old['timeline_id'])['runs'] if r['id']==old['id']),'continued')



if __name__=='__main__':unittest.main()
