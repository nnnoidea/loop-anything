"""Five overdesign-audit regressions, using the existing runtime fixtures."""
import copy
import io
import json
import unittest
import zipfile
from unittest.mock import patch

import test_business_state as fixture
from test_timeline_runtime import task_spec
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime import business_state,timelines
from loop_anything.runtime.implementations import selected
from loop_anything.runtime.model import Conflict,Invalid
from loop_anything.packaging.packages import make_archive,read_archive
from loop_anything.runtime.team_transport import core
from test_packages import document


class ContinuationDesignTests(unittest.TestCase):
    def case(self):
        c=fixture.BusinessStateTests();c.setUp();self.addCleanup(c.doCleanups);return c

    def test_usable_state_can_continue_after_description_optional_field_or_type_changes(self):
        for change in ('description','field','type','empty'):
            with self.subTest(change=change):
                c=self.case();old=c.first();bp=copy.deepcopy(c.base.bp);bp['version']='updated'
                if change=='description':bp['state']['types']['question']['schema']['description']='Better explanation'
                elif change=='type':bp['state']['types']['idea']={'mode':'current','schema':{'type':'string'}}
                else:bp['state']['types']['question']['schema']['properties']['note']={'type':'string'}
                timeline_id=old['timeline_id']
                if change=='empty':
                    with c.store.connection() as db:
                        empty=timelines.create(db,'Empty');timelines.save(db,empty);db.commit()
                    timeline_id=empty['id']
                key=c.store.publish(bp,c.base.implementations)['key']
                new=c.store.create(key,'continued',timeline_id=timeline_id,continue_run_id=old['id'] if change!='empty' else None)
                self.assertEqual(new['timeline_id'],timeline_id)
                self.assertEqual(new['business_state']['records'],old['business_state']['records'] if change!='empty' else [])

    def test_business_values_types_and_modes_are_loop_owned(self):
        for change in ('value','missing_type','mode'):
            with self.subTest(change=change):
                c=self.case();old=c.first();bp=copy.deepcopy(c.base.bp);bp['version']='invalid'
                if change=='value':bp['state']['types']['question']['schema']['properties']['text']={'type':'number'}
                if change=='mode':bp['state']['types']['question']['mode']='append'
                if change=='missing_type':
                    del bp['state']['types']['question']
                key=c.store.publish(bp,c.base.implementations)['key']
                new=c.store.create(key,'updated',timeline_id=old['timeline_id'],continue_run_id=old['id'])
                self.assertEqual(c.store.get(old['id'])['superseded_by'],new['id'])
                self.assertEqual(c.store.get(old['id'])['business_state']['records'],old['business_state']['records'])

    def test_retained_tasks_keep_distinct_implementations_and_reuse_their_snapshots(self):
        c=self.case()
        c.base.implementations['produce']={'options':{'a':{'kind':'agent','prompt':'A {{context}}'},'b':{'kind':'agent','prompt':'B {{context}}'}},'default':'a'}
        e=c.base.start();tasks=[task_spec('wait','wait',outputs={'text':'signal'})]
        for ident in ('a','b'):tasks.append(task_spec(ident,'produce',inputs={'source':{'literal':ident}},outputs={'text':ident+'-out'},after=['wait'],implementation=ident))
        c.base.submit(e,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'},'tasks':tasks})
        c.engine.tick(c.base.id);old=c.store.get(c.base.id);current=old;first_snapshot=None
        for count in range(4):
            if count==0:new=c.second(current)
            else:
                new=c.store.create(current['loop_key'],'same work',timeline_id=current['timeline_id'],continue_run_id=current['id'])
                c.base.id=new['id'];c.engine.tick(new['id']);new=c.store.get(new['id'])
            actual={t:selected(new,new['tasks'][t])[1]['prompt'] for t in ('a','b')}
            self.assertEqual(actual,{'a':'A {{context}}','b':'B {{context}}'})
            if first_snapshot is None:first_snapshot=copy.deepcopy(new['retained_nodes'])
            self.assertEqual(new['retained_nodes'],first_snapshot)
            if count==0:
                root=next(e for e in new['executions'] if e['node']=='reason')
                c.base.submit(root,{'settings':{'objective':'Compare methods','constraints':'Keep evaluation fixed'},'outputs':{'a':'A','b':'B'}})
            else:self.assertFalse(any(e['node']=='reason' for e in new['executions']))
            current=c.store.get(new['id'])
        c.engine.event(old['id'],'finished','signal',{'text':'ready'});c.engine.tick(old['id']);c.engine.tick(current['id'])
        dispatched={e['task_id']:e['implementation']['prompt'] for e in c.store.get(current['id'])['executions'] if e['task_id'] in ('a','b')}
        self.assertEqual(dispatched,{'a':'A {{context}}','b':'B {{context}}'})
        self.assertEqual(len(current['retained_nodes']),4)  # The ordinary completed entry also retains its provenance.

    def test_business_state_reads_do_not_block_later_execution_reports(self):
        for broad_read in (False,True):
            with self.subTest(broad_read=broad_read):
                c=self.case()
                e=c.base.start()
                c.base.submit(e,{'settings':{'objective':'Fixed work'},'outputs':{'a':'A','b':'B'},'tasks':[
                    task_spec('measure','produce',inputs={'source':{'literal':'fixed'}},outputs={'text':'measured'}),
                    task_spec('note','produce',inputs={'source':{'literal':'separate'}},outputs={'text':'noted'})]})
                c.engine.tick(c.base.id);run=c.store.get(c.base.id);attempts={e['task_id']:e for e in run['executions']}
                worker=RunTools(c.store,run['id'],attempts['measure']['token']);info=worker.call('read_task',{'task_id':'measure'})
                self.assertNotIn('basis',info)
                if broad_read:worker.call('read_timeline',{})
                c.base.submit(attempts['note'],{'outputs':{'text':'note'},'state':[{'type':'judgment','id':'note','value':'separate fact'}]})
                worker.call('read_task',{'task_id':'measure'})
                args={'task_id':'measure','report_id':'measure','event':'completed','envelope':{'outputs':{'text':'fixed result'}}}
                self.assertTrue(worker.call('report_task',args)['accepted'])
                from loop_anything.runtime.agent_prompt import task_context
                self.assertNotIn('business_state',task_context(c.store,c.store.get(run['id']),attempts['measure'],'http://unused','measure'))

    def test_retained_execution_can_save_state_with_no_new_loop_contract(self):
        c=self.case();old=c.first(waiting=True);bp=copy.deepcopy(c.base.bp);bp['version']='no-state'
        bp.pop('state')
        key=c.store.publish(bp,c.base.implementations)['key']
        new=c.store.create(key,'continued',timeline_id=old['timeline_id'],continue_run_id=old['id'])
        with c.store.edit(old['id']) as run:
            e=next(e for e in run['executions'] if e['node']=='wait')
            c.engine.timeline_runtime.report_in_run(run,e,{'event':'completed','report_id':'state-result',
                'envelope':{'outputs':{'text':'result'},'state':[{'type':'judgment','id':'j','value':{'arbitrary':'loop-defined'}}]}},'engine')
        c.engine.tick(new['id'])
        state=business_state.read(c.store,old['timeline_id'],type='judgment',id='j')
        self.assertEqual(state['records'][0]['value'],{'arbitrary':'loop-defined'})
        self.assertEqual(c.store.get(new['id'])['tasks']['experiment']['status'],'completed')

    def test_new_seed_id_does_not_overwrite_retained_task(self):
        c=self.case();e=c.base.start()
        c.base.submit(e,{'settings':{'objective':'Keep work'},'outputs':{'a':'A','b':'B'},'tasks':[
            task_spec('reason','wait',outputs={'text':'result'})]})
        c.engine.tick(c.base.id);old=c.store.get(c.base.id);new=c.second(old)
        entry=new['loop_definition']['seed']['id']
        self.assertNotEqual(entry,'reason')
        self.assertEqual(new['tasks']['reason']['continuation_source'],{'run_id':old['id'],'task_id':'reason'})
        from loop_anything.runtime.store import Store
        self.assertEqual(Store(c.store.filename).get(new['id'])['loop_definition']['seed']['id'],entry)
        attempt=next(e for e in new['executions'] if e['task_id']==entry)
        c.base.submit(attempt,{'settings':{'objective':'Keep work'},'outputs':{'a':'A','b':'B'}})
        c.engine.event(old['id'],'done','signal',{'text':'kept'});c.engine.tick(old['id']);c.engine.tick(new['id'])
        done=c.store.get(new['id'])
        self.assertEqual(done['tasks'][entry]['status'],'completed')
        self.assertEqual(done['tasks']['reason']['status'],'completed')
        self.assertEqual(done['records']['result'][0]['value'],'kept')

    def test_agent_read_and_report_keep_dispatched_input_sources(self):
        c=self.case();e=c.base.start()
        c.base.submit(e,{'settings':{'objective':'Keep provenance'},'outputs':{'a':'original','b':'B'},'tasks':[
            task_spec('measure','produce',inputs={'source':{'record':'a'}},outputs={'text':'measurement'})]})
        c.engine.tick(c.base.id);run=c.store.get(c.base.id)
        attempt=next(e for e in run['executions'] if e['task_id']=='measure')
        with c.store.edit(run['id']) as current:
            record=copy.deepcopy(current['records']['a'][-1]);record.update(revision=2,value='later evidence')
            current['records']['a'].append(record)
        worker=RunTools(c.store,run['id'],attempt['token'])
        view=worker.call('read_task',{'task_id':'measure'})
        self.assertEqual(view['inputs']['source'],'original')
        self.assertEqual(view['sources']['source']['revision'],1)
        worker.call('report_task',{'task_id':'measure','event':'completed','report_id':'result','envelope':{'outputs':{'text':'measured'}}})
        saved=next(e for e in c.store.get(run['id'])['executions'] if e['id']==attempt['id'])
        self.assertEqual(saved['inputs'],attempt['inputs'])
        self.assertEqual(saved['sources'],attempt['sources'])

    def test_number_markers_do_not_change_creation_execution_recovery_or_dependency_checks(self):
        c=self.case();c.base.bp['schema_version']=1;e=c.base.start()
        c.base.submit(e,{'settings':{'objective':'Keep work'},'outputs':{'a':'A','b':'B'},'tasks':[task_spec('wait','wait',outputs={'text':'done'})]})
        c.engine.tick(c.base.id)
        with c.store.connection() as db:
            run=json.loads(db.execute('SELECT document FROM runs WHERE id=?',(c.base.id,)).fetchone()[0]);run['schema_version']=1
            db.execute('UPDATE runs SET document=? WHERE id=?',(json.dumps(run),c.base.id));db.commit()
        with patch.object(c.engine.timeline_runtime,'recover',wraps=c.engine.timeline_runtime.recover) as recover:
            c.engine.recover();self.assertTrue(recover.called)
        c.engine.event(c.base.id,'finished','signal',{'text':'done'});c.engine.tick(c.base.id)
        self.assertEqual(c.store.get(c.base.id)['records']['done'][0]['value'],'done')
        with self.assertRaises(Invalid):
            with c.store.edit(c.base.id) as run:run['tasks']['wait']['spec']['after']=['wait']
        broken=copy.deepcopy(c.base.bp);broken['seed']['node']='missing'
        with self.assertRaises(Invalid):c.store.publish(broken,c.base.implementations)

    def test_archive_markers_do_not_bypass_file_or_capability_checks(self):
        value=document();value['format']='loop-anything-package/1'
        raw=make_archive(value)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:files={n:z.read(n) for n in z.namelist()}
        manifest=json.loads(files['loop.json']);manifest['format']='anything';files['loop.json']=json.dumps(manifest).encode()
        def archive():
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as z:
                for name,data in files.items():z.writestr(name,data)
            return stream.getvalue()
        parsed,_,_,_=read_archive(archive());self.assertEqual(parsed['format'],'anything')
        manifest['files']['missing']={'sha256':'bad','executable':False};files['loop.json']=json.dumps(manifest).encode()
        with self.assertRaises(Invalid):read_archive(archive())
        value['requires']=['missing_capability']
        with self.assertRaises(Invalid):make_archive(value)

    def test_base_uses_actual_fields_instead_of_schema_number(self):
        for marker in (1,2,99):
            media=core.Base({'app_token':'test','table_id':'table','schema_version':marker})
            with patch.object(media,'tables',return_value=[{'id':'table'}]),patch.object(media,'call',return_value={'fields':[{'name':n,'type':kind} for n,kind in media.fields.items()]}) as call:
                media.ensure()
                self.assertEqual([c.args[0] for c in call.call_args_list],['+field-list'])
            with patch.object(media,'tables',return_value=[{'id':'table'}]),patch.object(media,'call',return_value={'fields':[{'name':'key','type':'number'}]}):
                with self.assertRaisesRegex(ValueError,'field type changed'):media.ensure()

if __name__=='__main__':unittest.main()
