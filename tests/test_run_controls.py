import unittest

from tests import test_work_context as fixture
from loop_anything.runtime.model import Conflict


class RunControlTests(unittest.TestCase):
    def test_controls_complete_without_agent_and_retry_has_no_side_effects(self):
        case = fixture.WorkContextTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        tools = case.tools
        start = tools.call('start_run',dict(key=case.key,title='Direct controls',request_id='start'))
        run = start['run_id']
        def control(key,op,**args):
            return tools.call('submit_run_request',dict(request_id=key,run_id=run,operation=op,arguments=args))
        self.assertEqual(control('pause','command',action='pause')['result']['status'],'paused')
        self.assertEqual(control('resume','command',action='resume')['result']['status'],'running')
        case.initialize(start)
        case.engine.tick(run)
        task = next(iter(case.store.get(run)['tasks']))
        changes = [{'tool':'change_task','arguments':{'task_id':task,'operation':'cancel','reason':'User request'}}]
        saved = control('cancel','edit_tasks',changes=changes)
        self.assertEqual(control('cancel','edit_tasks',changes=changes),saved)
        self.assertEqual(case.store.get(run)['tasks'][task]['status'],'cancelled')
        with self.assertRaises(Conflict):
            control('cancel','command',action='pause')
        control('end','command',action='terminate')
        deleted=control('delete','delete_run',metadata_revision=0)
        self.assertTrue(deleted['result']['deleted'])
        self.assertEqual(tools.call('read_run_request',{'request_id':'delete'}),deleted)
