"""Regression reproductions for the task/session audit."""
from concurrent.futures import Future
from unittest.mock import patch
import sys
import json
import os
import signal
import time
from pathlib import Path
import unittest
from loop_anything.runtime.native_sessions import resume, validate_resume, configure_capture
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime.host_runtime import run_command
import test_native_sessions as cases


class SessionAuditTests(unittest.TestCase):
    def setUp(self):
        self.case=cases.NativeSessionTests();self.case.setUp();self.case.initial()
        self.engine,self.store,self.rid,self.eid=self.case.engine,self.case.store,self.case.rid,self.case.eid
        self.args={'provider':'codex','native_session_id':'native-exact-123','message':'Explain',
                   'command':['codex','resume','{{session_id}}','{{prompt}}']}
    def tearDown(self):self.case.tearDown()

    def test_finished_owner_does_not_allow_duplicate_process_before_exit(self):
        with patch.object(self.engine.pool,'submit',side_effect=lambda *_:Future()) as submit:
            first=resume(self.engine,self.rid,self.eid,self.args)
            owner=self.store.get(self.rid)['agent_sessions'][0]
            RunTools(self.store,self.rid,owner['token']).call('finish',{})
            second=resume(self.engine,self.rid,self.eid,self.args)
            self.assertEqual(first['session_id'],second['session_id'])
            self.assertTrue(second['attached']);self.assertEqual(1,submit.call_count)

    def test_same_native_session_cannot_run_in_two_runs(self):
        self.case.initial();other_rid,other_eid=self.case.rid,self.case.eid
        with patch.object(self.engine.pool,'submit',side_effect=lambda *_:Future()):
            resume(self.engine,self.rid,self.eid,self.args)
            with self.assertRaises(Conflict):resume(self.engine,other_rid,other_eid,self.args)

    def test_native_capture_conflict_does_not_kill_business_process(self):
        session=self.engine.terminals.create(self.rid,self.eid,'capture-conflict')
        configure_capture(self.store,self.rid,self.eid,session,{'agent_cli':'codex'})
        result=run_command([sys.executable,'-u','-c',
            "import json;print(json.dumps({'type':'thread.started','thread_id':'different-id'}));print('business-finished')"], '', 3, session=session)
        self.assertEqual(0,result.returncode);self.assertIn('business-finished',result.stdout)
        self.assertTrue(session.doc.get('native_session_error'))
        self.assertEqual('native-exact-123',self.store.get(self.rid)['executions'][0]['native_session']['id'])

    def test_interrupted_native_lease_needs_explicit_stop_confirmation(self):
        from loop_anything.runtime.native_sessions import confirm_stopped
        with patch.object(self.engine.pool,'submit',side_effect=lambda *_:Future()):
            first=resume(self.engine,self.rid,self.eid,self.args)
            owner=self.store.get(self.rid)['agent_sessions'][0]
            RunTools(self.store,self.rid,owner['token']).call('finish',{})
            with self.store.connection() as db:
                doc=json.loads(db.execute('SELECT document FROM execution_sessions WHERE id=?',(first['session_id'],)).fetchone()[0])
                doc['state']='interrupted';db.execute('UPDATE execution_sessions SET document=? WHERE id=?',(json.dumps(doc),first['session_id']));db.commit()
            with self.assertRaises(Conflict):resume(self.engine,self.rid,self.eid,self.args)
            confirm_stopped(self.engine,self.rid,self.eid,first['session_id'])
            second=resume(self.engine,self.rid,self.eid,self.args)
            self.assertNotEqual(first['session_id'],second['session_id'])

    def test_original_session_with_agent_reported_id_blocks_cross_run_resume(self):
        self.case.initial();other_rid,other_eid=self.case.rid,self.case.eid
        session=self.engine.terminals.create(self.rid,self.eid,'manual-id-live',True)
        session.doc['state']='running';session.save()  # ID was reported to the execution, not parsed from output.
        with patch.object(self.engine.pool,'submit',side_effect=lambda *_:Future()):
            with self.assertRaises(Conflict):resume(self.engine,other_rid,other_eid,self.args)

    def test_resume_recovery_does_not_change_business_failure_counters(self):
        from loop_anything.runtime.native_sessions import confirm_stopped
        with self.store.edit(self.rid) as run:run['tasks']['init']['agent_failures']=2
        before=self.store.get(self.rid)['tasks']
        with patch.object(self.engine.pool,'submit',side_effect=lambda *_:Future()):
            first=resume(self.engine,self.rid,self.eid,self.args)
            self.engine.recover()
            self.assertTrue(self.store.get(self.rid)['agent_sessions'][0]['recovery_required'])
            confirm_stopped(self.engine,self.rid,self.eid,first['session_id'])
        self.assertEqual(before,self.store.get(self.rid)['tasks'])
        self.assertFalse(self.store.get(self.rid)['agent_sessions'])

    def test_stop_confirmation_and_scope_release_are_atomic(self):
        from loop_anything.runtime.native_sessions import confirm_stopped
        with patch.object(self.engine.pool,'submit',side_effect=lambda *_:Future()):
            first=resume(self.engine,self.rid,self.eid,self.args);self.engine.recover()
        with patch('loop_anything.interfaces.agent_tasks.recover_owner',side_effect=Conflict('retry recovery')):
            with self.assertRaises(Conflict):confirm_stopped(self.engine,self.rid,self.eid,first['session_id'])
        self.assertEqual('interrupted',self.engine.terminals.read(self.rid,self.eid,first['session_id'])['session']['state'])
        self.assertTrue(self.store.get(self.rid)['agent_sessions'])
        confirm_stopped(self.engine,self.rid,self.eid,first['session_id'])
        self.assertFalse(self.store.get(self.rid)['agent_sessions'])

    def test_unknown_process_without_native_id_cannot_be_bypassed_by_manual_binding(self):
        from loop_anything.runtime.native_sessions import confirm_stopped, preparation
        with self.store.edit(self.rid) as run:run['executions'][0].pop('native_session')
        pending=self.engine.terminals.create(self.rid,self.eid,'unknown-without-id',True)
        pending.doc['state']='interrupted';pending.save()
        self.assertEqual(pending.doc['id'],preparation(self.engine,self.rid,self.eid)['active_session'])
        with patch.object(self.engine.pool,'submit',side_effect=lambda *_:Future()):
            with self.assertRaises(Conflict):resume(self.engine,self.rid,self.eid,self.args)
            confirm_stopped(self.engine,self.rid,self.eid,pending.doc['id'])
            self.assertFalse(resume(self.engine,self.rid,self.eid,self.args)['attached'])

    def test_burst_of_terminal_queries_does_not_abort_agent(self):
        session=self.engine.terminals.create(self.rid,self.eid,'query-burst',True)
        code="import os,tty;tty.setraw(0);os.write(1,b'\\x1b[6n'*48);data=b''\nwhile data.count(b'R')<48:data+=os.read(0,4096)\nos.write(1,b'queries-complete')"
        result=run_command([sys.executable,'-u','-c',code,'{{prompt}}'],'',3,session=session)
        self.assertEqual(0,result.returncode);self.assertIn('queries-complete',result.stdout)

    def test_user_can_correct_failed_manual_identity_without_erasing_history(self):
        with self.store.edit(self.rid) as run:run['executions'][0].pop('native_session')
        failed=dict(self.args,native_session_id='typo-id',command=[sys.executable,'-c','import sys;sys.exit(4)','{{session_id}}','{{prompt}}'])
        first=resume(self.engine,self.rid,self.eid,failed)
        for future in list(self.engine.futures):future.result(5)
        previous=self.store.get(self.rid)['executions'][0]['native_session']
        second=resume(self.engine,self.rid,self.eid,dict(failed,native_session_id='corrected-id',previous_native_session=previous))
        for future in list(self.engine.futures):future.result(5)
        self.assertEqual('corrected-id',self.store.get(self.rid)['executions'][0]['native_session']['id'])
        self.assertEqual('typo-id',self.engine.terminals.read(self.rid,self.eid,first['session_id'])['session']['native_session']['id'])
        self.assertNotEqual(first['session_id'],second['session_id'])

    def test_user_operated_agent_can_register_its_own_execution(self):
        from test_run_agent import definition
        bp,impl=definition();key=self.store.publish(bp,impl)['key']
        run=self.store.create(key,'User operated',acquire=True)
        token=run['agent_sessions'][0]['token'];tools=RunTools(self.store,run['id'],token)
        task=tools.call('read_task',{'task_id':'init'})
        tools.call('complete_task',{'task_id':'init','task_version':task['task_version'],'envelope':{'settings':{'objective':'Inspect'},'outputs':{'result':'manual'}}})
        execution_id=self.store.get(run['id'])['executions'][0]['id']
        value=tools.call('register_agent_session',{'execution_id':execution_id,'provider':'codex','session_id':'native-exact-123','cwd':self.case.tmp.name})
        self.assertEqual('native-exact-123',value['native_session']['id'])
        with self.assertRaises(Conflict):resume(self.engine,self.rid,self.eid,self.args)
        tools.call('finish',{})
        with self.assertRaises(Conflict):tools.call('register_agent_session',{'execution_id':execution_id,'provider':'codex','session_id':'stale-token'})

    def test_naturally_exiting_interactive_cli_does_not_leave_child_running(self):
        marker=Path(self.case.tmp.name)/'child-pid';beat=Path(self.case.tmp.name)/'child-beat'
        child="import time\nwhile True:\n with open(%r,'a') as f:f.write('x')\n time.sleep(.01)" % str(beat)
        code="import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c',%r],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);Path(%r).write_text(str(p.pid))\nwhile not Path(%r).exists():time.sleep(.01)" % (child,str(marker),str(beat))
        session=self.engine.terminals.create(self.rid,self.eid,'child-cleanup',True)
        try:
            result=run_command([sys.executable,'-c',code,'{{prompt}}'],'',3,session=session)
            self.assertEqual(0,result.returncode)
            before=beat.stat().st_size;time.sleep(.1);self.assertEqual(before,beat.stat().st_size)
        finally:
            if marker.exists():
                try:os.kill(int(marker.read_text()),signal.SIGKILL)
                except ProcessLookupError:pass

    def test_known_cli_must_actually_resume_exact_id(self):
        for argv in (['codex','{{session_id}} {{prompt}}'],['claude','{{session_id}}','{{prompt}}'],
                     ['claude','-c','--resume','{{session_id}}','{{prompt}}']):
            with self.subTest(argv=argv),self.assertRaises(Invalid):validate_resume(argv)
        validate_resume(['codex','resume','{{session_id}}','{{prompt}}'])
        validate_resume(['claude','--resume','{{session_id}}','{{prompt}}'])


if __name__=='__main__':unittest.main()
