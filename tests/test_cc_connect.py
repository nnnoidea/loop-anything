"""Machine connection -> public discovery -> mapping -> real adapter subprocess."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.store import Store
from loop_anything.runtime.communication import service
from loop_anything.runtime.communication_conversations import from_source, bot_binding
from loop_anything.runtime.notifications import sender_for
from loop_anything.runtime.model import Invalid, Conflict


class CCConnectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        env=patch.dict(os.environ,LOOP_ANYTHING_IDENTITY_DIR=str(self.root/'identity'))
        env.start();self.addCleanup(env.stop)
        self.tools=PlatformTools(Store(self.root/'a.db'))
        self.other=PlatformTools(Store(self.root/'b.db'))
        self.config=self.root/'bridge.toml';self.capture=self.root/'sent.json'
        self.cli=self.root/'cc-connect'
        self.cli.write_text('#!'+sys.executable+'\nimport json,sys\nfrom pathlib import Path\nPath('+repr(str(self.capture))+').write_text(json.dumps({"args":sys.argv[1:],"body":sys.stdin.read()}))\n')
        self.cli.chmod(0o700)
        self.write_config()

    def write_config(self,extra='',options='thread_isolation=true'):
        self.config.write_text('data_dir='+json.dumps(str(self.root/'actual-data'))+'\n'+''.join(
            '\n[[projects]]\nname='+json.dumps(name)+'\n[[projects.platforms]]\ntype="feishu"\n[projects.platforms.options]\napp_id="app"\napp_secret="SECRET-DO-NOT-EXPOSE"\n'+options+'\n' for name in ('entry','papers'))+extra)

    def connect(self):
        return self.tools.call('configure_cc_connect',{'revision':0,'connection':{'executable':str(self.cli),'config_path':str(self.config)}})

    def test_machine_shared_discovery_mapping_and_fixed_outlet_send(self):
        self.assertFalse(self.tools.call('read_cc_connect',{})['configured'])
        info=self.connect()
        self.assertEqual(info,self.other.call('read_cc_connect',{}))
        self.assertEqual(len(info['bots']),2);self.assertNotIn('SECRET',json.dumps(info))
        self.assertFalse(self.capture.exists())
        bot={'project':'papers','platform':'feishu'}
        self.tools.call('communication_config',{'operation':'agent','agent_id':'papers','agent':{
            'name':'Papers','description':'Confirmed research assistant','implementation':{'kind':'agent','command':[sys.executable,'-c','pass']},'notification_bot':bot}})
        comm=service(self.tools.store)
        mapped=bot_binding(comm,comm.settings()['agents']['papers'],freeze=True)
        self.assertEqual(mapped['identity'],'papers');self.assertNotIn('command',mapped)
        context={'platform':'feishu','entry_project':'entry','session_key':'feishu:chat:root:root-message'}
        entry=from_source(comm,context)
        self.assertEqual(entry['conversation']['thread_root'],'root-message')
        self.tools.call('set_notification_channels',{'revision':0,'channels':{'updates':{'cc_connect':bot,'destination':context['session_key']}}})
        _,sender=sender_for(self.tools.store,{'settings':{}},'updates')
        # No metadata permission/API: a saved root can send through a cold fake bridge.
        result=subprocess.run(sender['command'],input=json.dumps({'id':'n','message':'done','outlet':sender}),text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        sent=json.loads(self.capture.read_text())
        self.assertEqual(sent['args'],['send','--project','papers','--session',context['session_key'],'--data-dir',str(self.root/'actual-data'),'--stdin'])
        with self.assertRaises(Conflict):self.connect()
        self.tools.call('communication_config',{'operation':'agent','agent_id':'papers','agent':{'notification_bot':{'project':'explicit-name','platform':'feishu'}}})
        self.assertEqual(comm.settings()['agents']['papers']['notification_bot']['project'],'explicit-name')
        self.write_config(extra='\n[[projects.platforms]]\ntype="feishu"\n')
        info=self.tools.call('read_cc_connect',{})
        self.assertFalse(next(b for b in info['bots'] if b['project']=='papers')['selectable'])
        self.assertNotIn('SECRET',json.dumps(info))
        # An unavailable notification Bot must not block disabling its Agent.
        self.tools.call('communication_config',{'operation':'agent','agent_id':'papers','agent':{'enabled':False,'notification_bot':bot}})
        self.assertFalse(comm.settings()['agents']['papers']['enabled'])
        self.tools.call('communication_config',{'operation':'agent','agent_id':'papers','agent':{'notification_route':'legacy'}})
        self.assertIsNone(comm.settings()['agents']['papers']['notification_bot'])

    def test_no_guessed_path_and_missing_connection_does_not_block_business(self):
        with self.assertRaises(Invalid):self.tools.call('configure_cc_connect',{'revision':0,'connection':{'executable':str(self.cli)}})
        comm=service(self.tools.store)
        entry=from_source(comm,{'platform':'feishu','entry_project':'entry','session_key':'opaque'})
        from loop_anything.runtime.communication_conversations import resolve
        binding=resolve(comm,entry['id'],include_sender=True)
        self.assertIn('configure_cc_connect',binding['sender']['configuration_error'])
        self.connect()
        repaired=resolve(comm,entry['id'],include_sender=True,refresh_sender=True)
        self.assertIn('command',repaired['sender'])
        self.assertEqual(repaired['sender']['destination'],'opaque')
        self.assertFalse(self.capture.exists())

    def test_config_and_credentials_are_not_rechecked_at_delivery(self):
        self.connect()
        self.config.unlink()  # The running bridge still owns its loaded config and secrets.
        # Explicit mappings remain editable even if discovery cannot read the file.
        self.tools.call('set_notification_channels',{'revision':0,'channels':{'entry':{'cc_connect':{'project':'entry','platform':'feishu'},'destination':'opaque'}}})
        from loop_anything.runtime.cc_connect import sender
        command=sender({'project':'entry','platform':'feishu'})['command']
        result=subprocess.run(command,input=json.dumps({'id':'n','message':'send through bridge','outlet':{'identity':'entry','destination':'feishu:chat:root:message'}}),text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertTrue(json.loads(result.stdout)['delivered'])
        self.assertTrue(self.capture.exists())

    def test_bridge_owns_default_directory_and_session_interpretation(self):
        self.config.write_text(self.config.read_text().split('\n',1)[1])
        self.connect()
        info=self.tools.call('read_cc_connect',{})
        self.assertIsNone(info['data_dir'])
        self.assertIsNone(info['connection']['data_dir'])
        from loop_anything.runtime.cc_connect import sender
        command=sender({'project':'entry','platform':'feishu'})['command']
        self.assertNotIn('--data-dir',command)
        origin={'platform':'feishu','entry_project':'entry','session_key':'opaque-future-format'}
        payload={'id':'n','message':'done','outlet':{'identity':'entry'},'conversation':origin}
        result=subprocess.run(command,input=json.dumps(payload),text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout)
        sent=json.loads(self.capture.read_text())
        self.assertNotIn('--data-dir',sent['args'])
        self.assertIn('opaque-future-format',sent['args'])
        fixed={'id':'fixed','message':'done','outlet':{'identity':'entry','destination':'workspace:feishu:chat:user'}}
        result=subprocess.run(command,input=json.dumps(fixed),text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertIn('workspace:feishu:chat:user',json.loads(self.capture.read_text())['args'])

    def test_config_refresh_relative_directory_and_secret_parse_failure(self):
        self.connect()
        self.config.write_text('data_dir="relative"\n')
        self.assertEqual(self.tools.call('read_cc_connect',{})['connection']['data_dir'],str(self.root/'actual-data'))
        self.config.write_text('data_dir="${BRIDGE_ONLY_DATA_DIR_FOR_TEST}"\n')
        info=self.tools.call('configure_cc_connect',{'revision':1,'connection':{'executable':str(self.cli),'config_path':str(self.config),'data_dir':str(self.root/'explicit-data')}})
        self.assertEqual(info['connection']['data_dir'],str(self.root/'explicit-data'))
        self.config.write_text('app_secret = SECRET-DO-NOT-EXPOSE invalid syntax')
        info=self.tools.call('read_cc_connect',{})
        self.assertIn('error',info);self.assertNotIn('SECRET',json.dumps(info))
        self.assertFalse(self.capture.exists())


if __name__=='__main__':unittest.main()
