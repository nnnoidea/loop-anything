"""Cross-Run consumers keep their dependencies when an ended Run is removed."""
import os
import unittest

import test_business_state as fixture
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime import work


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.BusinessStateTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.store = self.case.store
        self.tools = PlatformTools(self.store)
        self.session = self.tools.call('register_work_session', {
            'process_id': os.getpid(), 'native_session': {'provider': 'custom', 'id': 'test', 'cwd': os.getcwd()},
            'implementation': {'kind': 'agent', 'command': ['unused'],
                               'resume_command': ['unused', '{{session_id}}', '{{prompt}}']}})

    def delete(self, run):
        return self.tools.call('submit_run_request', {'operation': 'delete_run', 'run_id': run['id'],
                               'request_id': 'delete-'+run['id'], 'arguments': {'metadata_revision': 0}})

    def test_ended_work_and_exact_task_wait_survive_deletion(self):
        case = self.case
        case.base.bp['state']['types']['question']['summary'] = ['status']
        run = case.first(waiting=True)
        timeline = run['timeline_id']
        monitor = self.tools.call('start_monitor', {'request_id': 'gpu', 'interval': 60,
                                  'script': {'command': ['unused']}})['monitor']
        def gpu(count):
            import time
            with work.transaction(self.store) as db:
                monitor['sample'] = {'at': time.time(), 'data': {'gpu': count}}
                work.put(db, 'monitor', monitor)
        gpu(4)
        sources = {'job': {'kind': 'run', 'id': run['id']},
                   'task': {'kind': 'task', 'id': run['id'], 'task_id': 'experiment'},
                   'capacity': {'kind': 'monitor', 'id': monitor['id']}}
        def wait(key, checks):
            condition = {'op': 'and', 'args': [{'op': 'eq', 'args': [{'path': path}, value]} for path, value in checks]}
            return self.tools.call('wait_for', dict(self.session, timeline_id=timeline, key=key,
                                                   sources=sources, condition=condition))['wait']['id']
        common = [('task.outputs.text','original'), ('capacity.data.gpu',8)]
        exact = wait('exact', common+[('job.status','terminated'),('job.records.result','original')])
        success = wait('successful', [('job.status','completed')])
        follows = wait('continue', common+[('job.status','running')])
        case.engine.event(run['id'], 'returned', 'signal', {'text':'original'})
        case.engine.tick(run['id'])
        case.engine.command(run['id'], 'terminate')
        self.delete(run)
        self.assertEqual(work.poll_wait(self.store, exact)['state'], 'waiting')
        state = work.poll_wait(self.store, success)
        self.assertEqual(state['state'], 'waiting')
        self.assertIsNone(state['error'])
        self.assertEqual(state['retained_sources']['job']['refs'], {})
        self.assertEqual(state['retained_sources']['task']['refs'], {})
        gpu(8)
        state = work.poll_wait(self.store, exact)
        self.assertEqual(state['state'], 'ready')
        self.assertEqual(set(state['evidence']['job']['records']), {'result'})
        self.assertEqual(state['evidence']['task']['outputs'], {'text':'original'})
        saved = self.tools.call('read_work_timeline', {'timeline_id':timeline})
        self.assertEqual(saved['business_state']['records'][0]['summary'], {'status':'open'})
        self.assertEqual(self.tools.call('list_timelines', {})['groups'][0]['loop_id'],case.base.bp['id'])
        self.assertTrue(self.tools.call('export_timeline', {'timeline_id':timeline})['document']['state_definition'])
        next_run = self.store.create(run['loop_key'], 'Continue', timeline_id=timeline)
        state = work.poll_wait(self.store, follows)
        self.assertEqual(state['state'], 'ready')
        self.assertEqual(state['evidence']['job']['id'], next_run['id'])
        self.assertEqual(state['evidence']['task']['outputs']['text'],'original')

    def test_successful_completion_and_whole_result_condition_survive_deletion(self):
        case=self.case
        attempt=case.base.start()
        run=self.store.get(case.base.id)
        source={'kind':'run','id':run['id']}
        args=dict(self.session,timeline_id=run['timeline_id'],key='after-success',sources={'a':source},
                  condition={'op':'and','args':[{'op':'eq','args':[{'path':'a.status'},'completed']},
                                  {'op':'eq','args':[{'op':'len','args':[{'path':['a','records']}]},2]}]})
        saved=self.tools.call('wait_for',args)['wait']
        self.assertEqual(saved['state'],'waiting')
        case.base.submit(attempt,{'settings':{'objective':'Done','completion_rule':{'op':'eq','args':[1,1]}},
                                   'outputs':{'a':'one','b':'two'}})
        case.engine.tick(run['id'])
        self.assertEqual(self.store.get(run['id'])['status'],'completed')
        self.delete(run)
        ready=work.poll_wait(self.store,saved['id'])
        self.assertEqual(ready['state'],'ready')
        self.assertEqual(ready['evidence']['a']['records'],{'a':'one','b':'two'})
        self.assertNotIn('retained_sources',ready)

    def test_new_arrangement_after_removing_continuation_has_real_tasks(self):
        caller, report = self.case.submit_experiment()
        caller.call('finish', {})
        old = self.store.get(self.case.base.id)
        successor = self.case.second(old)
        self.case.engine.command(successor['id'], 'terminate')
        self.delete(successor)
        turn = self.tools.call('start_run', dict(self.session, key=old['loop_key'], title='Continue',
                               request_id='restart',timeline_id=old['timeline_id']))
        tools = RunTools(self.store, turn['run_id'], turn['token'])
        args = report['envelope']['operations'][0]['arguments']
        reply = tools.call('build_plan', args)
        actual = self.store.get(turn['run_id'])
        self.assertTrue(reply['tasks'])
        self.assertTrue(all(t['id'] in actual['tasks'] for t in reply['tasks']))
        self.assertEqual(tools.call('build_plan', args),reply)

    def test_delete_finished_starter_and_predecessor(self):
        # A seedless Run can be renamed, ended and referenced by a continuation.
        bp={'schema_version':2,'id':'cleanup','version':'1','records':{},'nodes':{},'handbook':{'instructions':'test'}}
        key=self.store.publish(bp,{})['key']
        turn=self.tools.call('start_run',dict(self.session,key=key,title='研'*501,request_id='old'))
        args={'run_id':turn['run_id'],'request_id':'rename','operation':'update_run','arguments':{'metadata_revision':0,'title':'新'*501}}
        self.tools.call('submit_run_request',args)
        self.case.engine.command(turn['run_id'],'terminate')
        next_run=self.store.create(key,'again',timeline_id=turn['timeline_id'],continue_run_id=turn['run_id'])
        self.case.engine.command(next_run['id'],'terminate')
        args.update(request_id='delete',operation='delete_run',arguments={'metadata_revision':1})
        self.assertTrue(self.tools.call('submit_run_request',args)['result']['deleted'])
        self.assertEqual(self.store.get(next_run['id'])['timeline_id'],turn['timeline_id'])
