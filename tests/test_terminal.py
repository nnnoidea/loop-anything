"""Real subprocess/PTY and Engine checks; no model credentials required."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.terminal import TerminalSessions, Redactor
from loop_anything.runtime.host_runtime import run_command
from loop_anything.runtime.implementations import validate_implementation
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.capabilities import discover, required_capabilities
from loop_anything.interfaces.platform_tools import PlatformTools
from test_run_agent import definition


def until(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.025)
    raise AssertionError('Timed out waiting for observable state')


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
        self.sessions = TerminalSessions(self.store)
        self.pool = ThreadPoolExecutor(2)
        self.stop = threading.Event()

    def tearDown(self):
        self.stop.set(); self.pool.shutdown(wait=True); self.tmp.cleanup()

    def launch(self, code, interactive=False, ident='first', prompt='hello', secrets=()):
        session = self.sessions.create('run', 'attempt', ident, interactive, secrets)
        command = [sys.executable, '-u', '-c', code] + (['{{prompt}}'] if interactive else [])
        future = self.pool.submit(run_command, command, prompt, 10, None, self.stop, session)
        return session, future

    def text(self, ident=None):
        return ''.join(r['text'] for r in self.sessions.read('run', 'attempt', ident)['output'])

    def test_native_session_keeps_live_tail_then_only_identity_after_success(self):
        session=self.sessions.create('', 'native-attempt','native',metadata={
            'native_session':{'provider':'custom','id':'recorded-session','cwd':self.tmp.name},'native_history':True})
        for i in range(20):session.append('stdout','chunk-'+str(i)+'\n')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM execution_output WHERE session_id=?',('native',)).fetchone()[0],8)
        result=run_command([sys.executable,'-c','print(\"done\")'],'',10,None,self.stop,session)
        self.assertEqual(result.returncode,0)
        saved=self.sessions.read('','native-attempt')
        self.assertEqual(saved['output'],[])
        self.assertEqual(saved['session']['native_session']['id'],'recorded-session')
        self.assertEqual(saved['session']['output_source'],'native_session')

    def test_custom_session_without_resume_keeps_diagnostics(self):
        session=self.sessions.create('', 'custom-attempt','custom',metadata={
            'native_session':{'provider':'custom','id':'custom-id'}})
        result=run_command([sys.executable,'-c','print("diagnostic output")'],'',10,None,self.stop,session)
        self.assertEqual(result.returncode,0)
        saved=self.sessions.read('','custom-attempt')
        self.assertIn('diagnostic output',str(saved['output']))
        self.assertNotIn('output_source',saved['session'])

    def test_live_pipe_output_before_exit_cursor_stderr_and_history(self):
        release = Path(self.tmp.name) / 'release'
        code = "import sys,time;from pathlib import Path;assert sys.stdin.read()=='hello';print('early');print('error',file=sys.stderr)\nwhile not Path(%r).exists():time.sleep(.02)\nprint('late')" % str(release)
        session, future = self.launch(code)
        until(lambda: 'early' in self.text() and 'error' in self.text())
        self.assertFalse(future.done())
        current = self.sessions.read('run', 'attempt')
        self.assertFalse(current['session']['can_input'])
        with self.assertRaises(Conflict):self.sessions.control('run','attempt','first',data='ignored')
        release.touch(); self.assertEqual(0, future.result(5).returncode)
        tail = self.sessions.read('run','attempt','first',current['cursor'])
        self.assertIn('late', ''.join(r['text'] for r in tail['output']))
        reopened = TerminalSessions(self.store).read('run','attempt')
        self.assertEqual('exited',reopened['session']['state'])
        self.assertIn('early',str(reopened['output']))

    @unittest.skipUnless(os.name == 'posix','PTY requires POSIX')
    def test_real_terminal_input_size_reopen_and_finished_session_rejects_writes(self):
        code="import os,sys,termios;assert os.isatty(0) and os.isatty(1);print('prompt:'+sys.argv[1]);a=input();print('received:'+a);print('size:'+str(os.get_terminal_size()))"
        session,future=self.launch(code,True,prompt='line one\nline two')
        until(lambda:'prompt:line one' in self.text())
        pid=self.sessions.read('run','attempt')['session']['pid']
        self.sessions.control('run','attempt','first',cols=121,rows=39)
        self.assertEqual(pid,self.sessions.read('run','attempt')['session']['pid'])
        with self.assertRaises(Conflict):self.sessions.control('other-run','attempt','first',data='bad\n')
        self.sessions.control('run','attempt','first',data='来自用户\n')
        self.assertEqual(0,future.result(5).returncode)
        self.assertIn('received:来自用户',self.text());self.assertIn('columns=121',self.text())
        with self.assertRaises(Conflict):self.sessions.control('run','attempt','first',data='too late\n')
        self.launch("print('another attempt')",ident='second')[1].result(5)
        self.assertEqual(2,len(self.sessions.read('run','attempt')['sessions']))
        self.assertIn('来自用户',self.text('first'));self.assertNotIn('来自用户',self.text('second'))

    @unittest.skipUnless(os.name == 'posix','PTY requires POSIX')
    def test_cursor_query_is_answered_without_any_browser(self):
        code="import os,tty;tty.setraw(0);os.write(1,b'abc\\x1b[6n');reply=os.read(0,64);assert reply==b'\\x1b[1;4R',repr(reply);os.write(1,b'query-ok')"
        session,future=self.launch(code,True)
        self.assertEqual(0,future.result(5).returncode)
        self.assertIn('query-ok',self.text())

    def test_cli_exits_before_reading_prompt_without_writer_thread_error(self):
        from unittest.mock import patch
        errors=[]
        with patch('threading.excepthook',side_effect=lambda args:errors.append(args.exc_value)):
            session,future=self.launch("print('early exit')",prompt='x'*1000000)
            self.assertEqual(0,future.result(5).returncode)
            time.sleep(.1)
        self.assertEqual([],errors)
        self.assertIn('early exit',self.text())

    def test_timeout_keeps_partial_output_and_stops_process(self):
        session=self.sessions.create('run','attempt','timeout')
        with self.assertRaises(Invalid):run_command([sys.executable,'-u','-c',"import time;print('before timeout');time.sleep(30)"],'',.2,session=session)
        self.assertIn('before timeout',self.text())
        self.assertEqual('error',self.sessions.read('run','attempt')['session']['state'])
        self.assertIsNotNone(session.process.poll())

    def test_split_token_redaction_and_interrupted_recovery(self):
        r=Redactor(['token-SECRET'])
        self.assertEqual('hello ',r.feed('hello token-SE'))
        self.assertEqual('[redacted]   world',r.feed('CRET world'))
        session,future=self.launch("import sys,time;print('token-',end='',flush=True);time.sleep(.1);print('SECRET')",secrets=['token-SECRET'])
        future.result(5);self.assertNotIn('token-SECRET',self.text());self.assertIn('[redacted]',self.text())
        self.sessions.create('run','attempt','interrupted',True)
        self.sessions.recover();self.assertEqual('interrupted',self.sessions.read('run','attempt')['session']['state'])
        with self.assertRaises(Conflict):self.sessions.control('run','attempt','interrupted',data='x')

    def test_public_configuration_roundtrip_and_requirements(self):
        tools=PlatformTools(self.store);draft=tools.call('create_loop',{'name':'Terminal'})
        args={k:draft[k] for k in ('draft_id','revision')}
        result=tools.call('set_implementation',dict(args,node_id='initialize',kind='agent',terminal=True,command=['codex','{{prompt}}']))
        doc=tools.call('read_loop',{'draft_id':draft['draft_id']})['loop']
        self.assertIn('agent_terminal',required_capabilities(doc['loop_definition'],doc['implementations']))
        self.assertIn('set_implementation',discover('agent_terminal')['guide']['agent_terminal']['tools'])
        for invalid in ({'kind':'command','terminal':True,'command':['x','{{prompt}}']},{'kind':'agent','terminal':True,'command':['x']},{'kind':'agent','terminal':'true'}):
            with self.assertRaises(Invalid):validate_implementation(invalid)
        tools.call('set_implementation',dict(draft_id=draft['draft_id'],revision=result['revision'],node_id='initialize',clear=['terminal'],command=['codex','exec','-']))

    @unittest.skipUnless(os.name == 'posix','PTY requires POSIX')
    def test_engine_same_agent_reports_result_and_finish_closes_tui(self):
        engine=Engine(self.store)
        bp,impl=definition()
        # This CLI waits for terminal input, reports using existing scoped tools, then stays in its UI.
        code="""import os,sys,json,time
from pathlib import Path
from loop_anything.runtime.store import Store
from loop_anything.interfaces.agent_tasks import RunTools
r=json.loads(Path(sys.argv[2]).read_text().split('Run context:'+chr(10),1)[1])
t=RunTools(Store(sys.argv[1]),r['run_id'],r['token'])
assert os.isatty(0)
print('ready for user',flush=True)
answer=input()
i=t.call('read_task',{'task_id':'init'})
t.call('complete_task',{'task_id':'init','task_version':i['task_version'],'envelope':{'settings':{'objective':'Terminal'},'outputs':{'result':answer}}})
t.call('finish',{})
time.sleep(60)
"""
        impl['init']={'kind':'agent','terminal':True,'command':[sys.executable,'-u','-c',code,self.store.filename,'{{prompt_file}}'],'cwd':str(Path(__file__).resolve().parents[1])}
        key=self.store.publish(bp,impl)['key'];run=self.store.create(key,'Terminal')
        try:
            engine.tick(run['id']);attempt=self.store.get(run['id'])['executions'][0]
            def ready():
                result=engine.terminals.read(run['id'],attempt['id'])
                return result if 'ready for user' in str(result['output']) else None
            output=until(ready)
            self.assertEqual(1,len(self.store.get(run['id'])['agent_sessions']))
            engine.terminals.control(run['id'],attempt['id'],output['session']['id'],data='用户补充内容\n')
            for future in list(engine.futures):future.result(8)
            latest=self.store.get(run['id'])
            self.assertEqual('completed',latest['tasks']['init']['status'])
            self.assertEqual('用户补充内容',latest['records']['init.result'][-1]['value'])
            self.assertEqual([],latest['agent_sessions'])
            self.assertEqual(1,len(latest['executions']))
            session=engine.terminals.read(run['id'],attempt['id'])['session']
            self.assertTrue(session['finished_by_tool']);self.assertEqual(0,session['returncode'])
        finally:engine.close()


if __name__=='__main__':unittest.main()
