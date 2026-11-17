"""Pause/resume and new Run continuation reuse normal scheduling and typed state."""
import copy
import json
import unittest
import test_timeline_runtime as fixture
from test_timeline_runtime import task_spec
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime.model import Invalid


class ContinueProgressTests(unittest.TestCase):
    def case(self, metadata=True):
        c=fixture.RuntimeTests();c.setUp();self.addCleanup(c.tearDown)
        if metadata:c.bp['state']={'types':{'note':{'summary':['text']}}}
        c.bp['plans']={'follow':{'parameters':{'type':'object'},'steps':{'measure':{'node':'produce','inputs':{'source':{'literal':'original'}}}}}}
        c.bp['nodes']['wait']['routes']=[{'id':'after-wait','event':'completed','plan':'follow','values':{}}]
        e=c.start()
        c.submit(e,{'settings':{'objective':'Continue saved work'},'outputs':{'a':'A','b':'B'},
            'state':[{'type':'note','id':'n','value':{'text':'saved'}}],
            'tasks':[task_spec('external','wait',outputs={'text':'result'})]})
        c.engine.tick(c.id)
        return c

    def test_pause_and_repeated_same_loop_continuation_keep_progression_and_settings(self):
        for metadata in (False,True):
            with self.subTest(metadata=metadata):
                c=self.case(metadata);old=c.store.get(c.id);original=old['tasks']['external']['execution_id']
                c.engine.command(c.id,'pause');c.engine.tick(c.id)
                self.assertEqual(c.store.get(c.id)['records'],old['records'])
                self.assertEqual(c.store.get(c.id)['business_state'],old['business_state'])
                c.engine.command(c.id,'resume')
                self.assertEqual(c.store.get(c.id)['tasks']['external']['execution_id'],original)
                current=c.store.get(c.id)
                with c.store.edit(c.id) as run:
                    run['settings'].update(max_parallel=2,bindings={'produce':'default'})
                    run['inputs']['recipient_path']='saved'
                current=c.store.get(c.id)
                for _ in range(2):
                    new=c.store.create(current['loop_key'],'continue',timeline_id=current['timeline_id'],continue_run_id=current['id'])
                    self.assertNotIn('initialized',new)
                    self.assertEqual(new['settings'],current['settings'])
                    self.assertEqual(new['inputs'],current['inputs'])
                    self.assertEqual(new['business_state'],old['business_state'])
                    self.assertEqual(new['tasks']['init']['status'],'completed')
                    self.assertEqual(new['loop_definition']['nodes']['wait']['routes'],old['loop_definition']['nodes']['wait']['routes'])
                    current=new
                c.engine.event(old['id'],'done','signal',{'text':'observed'})
                c.engine.command(current['id'],'pause');c.engine.tick(old['id']);c.engine.tick(current['id'])
                paused=c.store.get(current['id'])
                self.assertFalse(any(e['node']=='produce' for e in paused['executions']))
                c.engine.command(current['id'],'resume');c.engine.tick(current['id']);c.engine.tick(current['id'])
                done=c.store.get(current['id'])
                self.assertEqual(done['tasks']['external']['status'],'completed')
                self.assertEqual(len([t for t in done['tasks'].values() if t['spec']['node']=='produce']),1)
                self.assertEqual(done['records']['result'][0]['producer'],original)
                self.assertEqual(len(c.store.get(old['id'])['executions']),len(old['executions']))
                self.assertFalse(any(e['node']=='init' for e in done['executions']))

    def test_pause_resume_keeps_events_and_runs_next_step_once(self):
        c=self.case();before=c.store.get(c.id)
        original=before['tasks']['external']['execution_id']
        c.engine.command(c.id,'pause')
        c.engine.event(c.id,'arrived-while-paused','signal',{'text':'received'})
        c.engine.tick(c.id);paused=c.store.get(c.id)
        self.assertEqual(paused['records'],before['records'])
        self.assertEqual(paused['business_state'],before['business_state'])
        self.assertEqual(paused['loop_definition'],before['loop_definition'])
        self.assertEqual(len(paused['tasks']),2)
        c.engine.command(c.id,'resume');c.engine.tick(c.id)
        c.engine.command(c.id,'pause');c.engine.command(c.id,'resume');c.engine.tick(c.id)
        done=c.store.get(c.id)
        self.assertEqual(done['tasks']['external']['execution_id'],original)
        self.assertEqual(done['records']['result'][0]['value'],'received')
        self.assertEqual(len([t for t in done['tasks'].values() if t['spec']['node']=='produce']),1)

    def test_continuation_keeps_settings_but_honors_explicit_start_overrides(self):
        c=self.case();old=c.store.get(c.id)
        with c.store.edit(c.id) as run:
            run['settings']['max_parallel']=2
            run['settings']['bindings']={'produce':'default'}
            run['inputs'].update(saved='kept',override='before')
        old=c.store.get(c.id)
        new=c.store.create(old['loop_key'],'continue',timeline_id=old['timeline_id'],continue_run_id=old['id'],
                           bindings={},inputs={'override':'after'},notification_route='workspace')
        self.assertEqual(new['settings']['max_parallel'],2)
        self.assertEqual(new['settings']['bindings'],{})
        self.assertEqual(new['settings']['notification_route'],'workspace')
        self.assertEqual(new['inputs'],{'saved':'kept','override':'after'})

    def test_changed_loop_keeps_arranged_rules_and_original_result(self):
        c=self.case();old=c.store.get(c.id);bp=copy.deepcopy(c.bp);bp['version']='optimized'
        bp['plans']['new-follow']=bp['plans'].pop('follow')
        bp['plans']['new-follow']['steps']['measure']['inputs']['source']={'literal':'optimized'}
        bp['nodes']['wait']['routes'][0]['plan']='new-follow'
        key=c.store.publish(bp,c.implementations)['key']
        new=c.store.create(key,'optimized',timeline_id=old['timeline_id'],continue_run_id=old['id'])
        c.id=new['id'];c.engine.tick(c.id);new=c.store.get(c.id)
        entry=next(e for e in new['executions'] if e['task_id']==new['loop_definition']['seed']['id'])
        c.submit(entry,{'settings':{'objective':'Continue saved work'},'outputs':{'a':'A','b':'B'}})
        c.engine.event(old['id'],'done','signal',{'text':'original execution'})
        c.engine.tick(old['id']);c.engine.tick(c.id);c.engine.tick(c.id)
        done=c.store.get(c.id)
        follow=next(e for e in done['executions'] if done.get('retained_nodes',{}).get(e['node'],{}).get('node_id')=='produce')
        self.assertEqual(follow['inputs']['source'],'original')
        self.assertEqual(done['records']['result'][0]['source_run_id'],old['id'])
        task=done['tasks']['external']
        view=RunTools(c.store,c.id).call('read_task',{'task_id':task['id']})
        self.assertEqual(view['routes'][0]['plan'],'follow')
        self.assertNotIn('return-to-steward',[r['route_id'] for r in view['route_receipts']])

    def test_changed_method_keeps_inflight_optional_entry(self):
        c=fixture.RuntimeTests();c.setUp();self.addCleanup(c.tearDown)
        c.bp['entry']='wait';c.bp['seed']=task_spec('external-entry','wait',outputs={'text':'observed'})
        key=c.store.publish(c.bp,c.implementations)['key'];old=c.store.create(key,'Existing experiment');c.engine.tick(old['id'])
        bp=copy.deepcopy(c.bp);bp['version']='new-method';bp.pop('entry');bp.pop('seed')
        key=c.store.publish(bp,c.implementations)['key'];new=c.store.create(key,'Continue',timeline_id=old['timeline_id'],continue_run_id=old['id'])
        self.assertEqual(new['tasks']['external-entry']['continuation_source'],{'run_id':old['id'],'task_id':'external-entry'})
        c.engine.event(old['id'],'done','signal',{'text':'original result'});c.engine.tick(old['id']);c.engine.tick(new['id'])
        done=c.store.get(new['id']);self.assertEqual(done['tasks']['external-entry']['status'],'completed')
        self.assertEqual(done['records']['observed'][0]['source_run_id'],old['id'])

    def test_boolean_and_number_changes_are_saved_and_retries_do_not_duplicate(self):
        for first,second in [(1,True),(False,0),({'enabled':1},{'enabled':True}),([False],[0])]:
            with self.subTest(first=first,second=second):
                c=fixture.RuntimeTests();c.setUp();self.addCleanup(c.tearDown);e=c.start()
                c.submit(e,{'settings':{'objective':'Save actual JSON values'},'outputs':{'a':'A','b':'B'},
                    'state':[{'type':'business','id':'flag','value':first}],
                    'tasks':[task_spec('next','produce',inputs={'source':{'literal':'next'}},outputs={'text':'next'})]})
                c.engine.tick(c.id);run=c.store.get(c.id);attempt=next(e for e in run['executions'] if e['task_id']=='next')
                tools=RunTools(c.store,c.id,attempt['token'])
                args={'task_id':'next','event':'completed','report_id':'same','envelope':{
                    'outputs':{'text':'done'},'state':[{'type':'business','id':'flag','value':second}]}}
                tools.call('report_task',args)
                self.assertTrue(tools.call('report_task',args)['duplicate'])
                row=c.store.get(c.id)['business_state']['records'][0]
                self.assertEqual(json.dumps(row['value'],sort_keys=True),json.dumps(second,sort_keys=True))
                self.assertEqual(row['revision'],2)
                with c.store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM work_state').fetchone()[0],2)

    def test_one_header_does_not_block_workspace_and_canonical_tables_are_used(self):
        c=self.case();before=c.store.get(c.id);other=c.store.create(before['loop_key'],'unrelated')
        with c.store.connection() as db:
            header=json.loads(db.execute('SELECT document FROM runs WHERE id=?',(c.id,)).fetchone()[0])
            header.update(records={'ignored':[]},tasks={},loop_definition={},implementations={})
            db.execute('UPDATE runs SET document=? WHERE id=?',(json.dumps(header),c.id));db.commit()
        reopened=Store(c.store.filename)
        self.assertEqual(reopened.get(c.id),before)
        self.assertEqual(reopened.get(other['id'])['title'],'unrelated')
        with reopened.connection() as db:
            header.pop('timeline_id');db.execute('UPDATE runs SET document=? WHERE id=?',(json.dumps(header),c.id));db.commit()
        reopened=Store(c.store.filename)
        self.assertEqual(reopened.get(other['id'])['title'],'unrelated')
        with self.assertRaises(Invalid):reopened.get(c.id)

if __name__=='__main__':unittest.main()
