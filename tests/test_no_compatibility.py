"""No retired API adapters; usable structures are not excluded by version markers."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.packaging.packages import make_archive
from loop_anything.runtime.communication import Communication
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.store import Store
from loop_anything.runtime.team_transport import core
from test_packages import document


class NoCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'workspace.db')

    def test_retired_cli_entries_are_rejected(self):
        for argv in ([sys.executable,'install.py','--role','platform'],
                     [sys.executable,'install.py','--role','local'],
                     [sys.executable,'-m','loop_anything','local','--help']):
            result=subprocess.run(argv,text=True,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('unrecognized arguments' if 'install.py' in argv else 'invalid choice',result.stderr)

    def test_tools_have_only_current_reporting_edit_and_chat_contracts(self):
        definitions={d['name']:d['inputSchema']['properties'] for d in PlatformTools(self.store).definitions()}
        self.assertNotIn('complete_task',definitions)
        self.assertNotIn('revision',definitions['edit_tasks'])
        self.assertNotIn('token',definitions['read_assistance'])
        self.assertNotIn('conversation_id',definitions['start_run'])
        self.assertNotIn('conversation_id',definitions['request_assistance'])
        comm=Communication(self.store)
        with self.assertRaises(Invalid):comm.config('conversation',conversation={})

    def test_old_package_version_and_definition_fields_are_not_converted(self):
        for transform in (
            lambda d:d.update(edit_protection={}),
            lambda d:d.update(requires=['loop_edit_protection']),
            lambda d:next(iter(d['loop_definition']['nodes'].values())).update(completion_checks=[{'left':'x','right':'y'}]),
        ):
            value=copy.deepcopy(document());transform(value);before=copy.deepcopy(value)
            with self.assertRaises(Invalid):make_archive(value)
            self.assertEqual(value,before)
        self.assertEqual(self.store.catalog(),[])

    def test_old_request_schema_is_not_altered_on_open(self):
        with self.store.connection() as db:
            db.execute('DROP TABLE run_requests')
            db.execute('CREATE TABLE run_requests(id TEXT PRIMARY KEY,run_id TEXT,fingerprint TEXT)');db.commit()
        with self.assertRaises(Invalid):Store(self.store.filename)
        with self.store.connection() as db:
            self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(run_requests)')],['id','run_id','fingerprint'])

    def test_flat_nas_directory_is_not_discovered_or_modified(self):
        root=self.root/'flat';root.mkdir()
        path=root/'group.json';path.write_text(json.dumps({'version':1,'id':'group-old','name':'Old'}))
        before=path.read_bytes()
        with self.assertRaises(FileNotFoundError):core.join(str(root))
        self.assertEqual(path.read_bytes(),before);self.assertFalse((root/'agents').exists())

    def test_offer_does_not_create_an_execution_or_reply(self):
        comm=Communication(self.store)
        team=comm.config('team',link=str(self.root/'team'),create=True)['team']
        packet={'version':1,'id':'old-offer','kind':'offer','request_id':'old-request',
                'sender':'old-sender','target':comm.settings()['instance_id'],
                'group_id':team['id'],'assignment_id':None,'payload':{}}
        with self.assertRaises(Invalid):comm.receive(packet)
        self.assertEqual(comm.requests(),[])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM communication_outbox').fetchone()[0],0)

    def test_local_execution_receipts_do_not_read_transport_wrappers(self):
        from loop_anything.runtime.executor_client import Receiver
        receiver=Receiver.__new__(Receiver)
        path=self.root/'receipt.json'
        current={'packet':{'id':'execution-test'},'update':{'state':'running'}}
        path.write_text(json.dumps(current))
        self.assertEqual(receiver.read_receipt(path),current)
        acknowledged={'acknowledged':True,'id':'execution-test','state':'completed','native_session':None}
        path.write_text(json.dumps(acknowledged))
        self.assertEqual(receiver.read_receipt(path),acknowledged)
        path.write_text(json.dumps({'transport':'snapshot-v1','file':'old.blob'}))
        with self.assertRaises(ValueError):receiver.read_receipt(path)

    def test_base_marker_does_not_reject_or_rewrite_configuration(self):
        config={'app_token':'unused','schema_version':1}
        before=copy.deepcopy(config)
        self.assertEqual(core.Base(config).app,'unused')
        self.assertEqual(config,before)

    def test_bare_candidates_are_rejected_without_changing_document(self):
        value=document()
        value['implementations']['initialize']=value['implementations']['initialize']['options']['default']
        before=copy.deepcopy(value)
        with self.assertRaisesRegex(Invalid,'options'):make_archive(value)
        self.assertEqual(value,before)

    def test_stdout_requires_an_explicit_report_event(self):
        from unittest.mock import patch
        from test_timeline_runtime import RuntimeTests, task_spec
        for payload in ({'outputs':{'text':'must-not-commit'}},
                        {'status':'waiting','external_id':'old-job','poll_after':100}):
            with self.subTest(payload=payload):
                case=RuntimeTests();case.setUp()
                try:
                    case.implementations['produce']={'options':{'default':{
                        'kind':'external','command':['submit'],'observe':['observe']}},'default':'default'}
                    with patch('loop_anything.runtime.timeline_runtime.run_command',return_value=
                               subprocess.CompletedProcess([],0,json.dumps(payload),'')):
                        case.initialize([task_spec('job','produce',{'source':{'record':'a'}},{'text':'out'})])
                        for future in list(case.engine.futures):future.result(timeout=5)
                    run=case.read()
                    self.assertEqual(run['tasks']['job']['status'],'fault')
                    self.assertNotIn('out',run['records'])
                    attempt=next(e for e in run['executions'] if e['task_id']=='job')
                    self.assertNotIn('external_id',attempt)
                finally:case.tearDown()
