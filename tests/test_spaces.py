import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from loop_anything.runtime.tool_client import module
from loop_anything.runtime.local_tasks import TaskRegistry,main as local_main
from loop_anything.packaging.skill_bundle import bundle,install_skills


class SpaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.config=self.root/'spaces.json'
        env=patch.dict(os.environ,LOOP_ANYTHING_SPACES=str(self.config),LOOP_ANYTHING_PLATFORM_URL='',LOOP_ANYTHING_IDENTITY_DIR=str(self.root/'identity'))
        env.start();self.addCleanup(env.stop);self.spaces=module('spaces')

    def test_recorded_addresses_auto_prefer_team_and_manual_choice_persists(self):
        self.assertFalse(self.config.exists())
        self.assertEqual(self.spaces.read()['default_space'],'auto')
        with self.assertRaisesRegex(ValueError,'No platform address'):self.spaces.resolve()
        for local,team,expected in (
            ('http://127.0.0.1:8767',None,'http://127.0.0.1:8767'),
            (None,'https://team.example','https://team.example'),
            ('http://127.0.0.1:8767','https://team.example','https://team.example')):
            with self.subTest(local=local,team=team):
                self.spaces.configure({'local_url':local,'team_url':team,'default_space':'auto'})
                self.assertEqual(self.spaces.resolve(),expected)
        chosen=self.spaces.configure({'default_space':'local'})
        self.spaces.configure({'team_url':'https://new-team.example'})
        self.assertEqual(self.spaces.resolve(),'http://127.0.0.1:8767')
        with self.assertRaisesRegex(ValueError,'reread'):self.spaces.configure({'default_space':'auto'},chosen['revision'])
        self.spaces.configure({'default_space':'auto'})
        self.assertEqual(self.spaces.resolve(),'https://new-team.example')
        self.assertEqual(self.spaces.resolve(space='local'),'http://127.0.0.1:8767')
        self.assertEqual(self.spaces.resolve(url='http://original:9000'),'http://original:9000')

    def test_team_only_web_has_no_guessed_local_address_and_clear_team_restores_auto(self):
        config=self.spaces.configure({'team_url':'https://team.example'})
        self.assertIsNone(config['local_url'])
        self.assertEqual(self.spaces.browser_url(config),'https://team.example')
        self.spaces.configure({'local_url':'http://127.0.0.1:9876','default_space':'team'})
        with patch('sys.stdout',new_callable=io.StringIO):self.spaces.main(['--clear-team'])
        self.assertEqual(self.spaces.read()['default_space'],'auto')
        self.assertEqual(self.spaces.resolve(),'http://127.0.0.1:9876')

    def test_team_browser_opens_only_its_address_and_nas_needs_web_address(self):
        config=self.spaces.configure({'local_url':'http://127.0.0.1:9876','team_url':'nas:///team','default_space':'team'})
        with self.assertRaisesRegex(ValueError,'team_web_url'):self.spaces.browser_url(config)
        config=self.spaces.configure({'team_web_url':'https://team.example'})
        self.assertEqual(self.spaces.browser_url(config),'https://team.example')

    def test_invalid_configuration_never_overwrites_personal_choices(self):
        for change in ({'default_space':'team'},{'local_url':'http://remote:80'},
                       {'team_url':'javascript:alert(1)'},{'team_web_url':'nas:///team'},{'unknown':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.spaces.configure(change)
        self.assertFalse(self.config.exists())
        with self.assertRaisesRegex(ValueError,'nonempty'):self.spaces.resolve(url='')
        self.config.write_text('{"url":"http://old"}')
        with self.assertRaisesRegex(ValueError,'Invalid personal'):self.spaces.read()

    def test_concurrent_personal_edits_cannot_overwrite_the_same_revision(self):
        from concurrent.futures import ThreadPoolExecutor
        def edit(url):
            try:return self.spaces.configure({'team_url':url},0)
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(edit,['https://one.example','https://two.example']))
        self.assertEqual(sum(v is not None for v in results),1)
        self.assertEqual(self.spaces.read()['revision'],1)

    def test_skill_update_keeps_personal_defaults_and_export_only_records_provenance(self):
        self.spaces.configure({'team_url':'https://chosen.example','default_space':'team'})
        before=self.config.read_bytes();target=self.root/'skills'
        install_skills(bundle('https://export-one.example'),target)
        install_skills(bundle('https://export-two.example'),target,replace=True)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertFalse((target/'loop-anything-platform/connection.json').exists())
        self.assertEqual(json.loads((target/'loop-anything-platform/platform-source.json').read_text())['platform_url'],'https://export-two.example')
        client=target/'loop-anything-platform/scripts/call.py'
        result=subprocess.run([sys.executable,str(client),'spaces'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['team_url'],'https://chosen.example')

    def test_personal_schedules_use_local_registry_even_when_team_is_default(self):
        registry=self.root/'local.db.schedules';TaskRegistry(registry).register({'name':'Private task','every':600,'command':['unused']},'private')
        self.spaces.configure({'local_registry':str(registry),'team_url':'https://team.example','default_space':'team'})
        with patch('sys.stdout',new_callable=io.StringIO) as output:local_main(['list'])
        self.assertEqual(json.loads(output.getvalue())[0]['id'],'private')
        self.assertEqual(TaskRegistry(registry).show('private')['runtime']['status'],'registered')

    def test_default_installer_includes_local_server_client_and_saves_local_registry(self):
        import install as installer
        prefix=self.root/'app';env=prefix/'venv';(env/'bin').mkdir(parents=True);(env/'pyvenv.cfg').write_text('version=3.9')
        wheel=self.root/'app.whl';wheel.write_bytes(b'test')
        with patch.object(sys,'argv',['install.py','--prefix',str(prefix),'--package',str(wheel)]), \
             patch.object(sys,'platform','darwin'),patch.object(installer,'default_database',return_value=self.root/'private.db'),patch.object(installer.subprocess,'run') as run, \
             patch('loop_anything.runtime.service.configuration',return_value=None),patch('loop_anything.runtime.service.available'), \
             patch.object(installer,'register',return_value={'command':'test','current_terminal':'test'}),patch('builtins.print'):
            installer.main()
        calls=[c.args[0] for c in run.call_args_list]
        config=self.spaces.read()
        self.assertEqual(config['local_url'],'http://127.0.0.1:8767');self.assertEqual(config['local_registry'],str((self.root/'private.db').resolve())+'.schedules')
        service=next(c for c in calls if 'service' in c)
        self.assertEqual(service[-4:],['service','install','--port','8767'])
        self.assertIn(str((self.root/'private.db').resolve()),service)
        self.assertIn('service start --open',(prefix/'Loop Anything.command').read_text())
        from loop_anything.runtime.service import definition
        self.assertIn('--allow-sleep',definition(sys.executable,database=self.root/'private.db')['ProgramArguments'])


class SpaceHTTPTests(unittest.TestCase):
    def test_team_cannot_see_personal_settings_and_cli_defaults_never_fail_over(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);processes=[]
            env=dict(os.environ,LOOP_ANYTHING_SPACES=str(root/'spaces.json'),LOOP_ANYTHING_IDENTITY_DIR=str(root/'identity'),LOOP_ANYTHING_PLATFORM_URL='')
            def start(kind):
                log=root/(kind+'.log');stream=log.open('w')
                p=subprocess.Popen([sys.executable,'-m','loop_anything','--db',str(root/(kind+'.db')),'serve','--port','0','--space',kind,'--allow-sleep'],env=env,stdout=stream,stderr=stream)
                processes.append((p,stream));deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    match=re.search(r'Health check: (http://127.0.0.1:\d+)/api/health',log.read_text())
                    if match:return match.group(1)
                    self.assertIsNone(p.poll(),log.read_text());time.sleep(.05)
                self.fail(log.read_text())
            def request(url,body=None,origin=None):
                headers={'X-Loop-Anything':'workspace','Content-Type':'application/json'}
                if origin:headers['Origin']=origin
                with urlopen(Request(url,data=json.dumps(body).encode() if body is not None else None,headers=headers),timeout=5) as response:return json.load(response)
            client=Path('skills/loop-anything-platform/scripts/call.py').resolve()
            def cli(*args):return subprocess.run([sys.executable,str(client),*args],env=env,text=True,capture_output=True)
            try:
                local=start('local');team=start('team')
                self.assertEqual(request(local+'/api/spaces')['configuration']['default_space'],'auto')
                self.assertIsNone(request(team+'/api/spaces')['configuration'])
                with urlopen(Request(local+'/api/spaces',headers={'Host':'outside.example:1234'})) as response:
                    self.assertIsNone(json.load(response)['configuration'])
                saved=request(local+'/api/spaces',{'revision':0,'change':{'local_url':local,'team_url':team,'default_space':'auto'}},local)
                self.assertEqual(saved['configuration']['default_space'],'auto')
                before=(root/'spaces.json').read_bytes()
                with self.assertRaises(HTTPError) as error:request(team+'/api/spaces',{'revision':1,'change':{'default_space':'local'}},team)
                self.assertEqual(error.exception.code,403);self.assertEqual((root/'spaces.json').read_bytes(),before)
                with self.assertRaises(HTTPError):request(local+'/api/spaces',{'revision':1,'change':{'default_space':'local'}},team)
                result=cli('check');self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['url'],team)
                for options,expected in (([],team),(['--space','local'],local),(['--url',local],local)):
                    with self.subTest(check=options):
                        checked=subprocess.run([sys.executable,'-m','loop_anything','check',*options],env=env,text=True,capture_output=True)
                        self.assertEqual(checked.returncode,0,checked.stderr)
                        self.assertEqual(json.loads(checked.stdout)['url'],expected)
                direct=subprocess.run([sys.executable,'-m','loop_anything','tool','list'],env=env,text=True,capture_output=True)
                self.assertEqual(direct.returncode,0,direct.stderr);self.assertEqual(json.loads(direct.stdout)['platform_url'],team)
                bound=cli('read_run','--arguments','{"run_id":"private-run"}')
                self.assertNotEqual(bound.returncode,0);self.assertIn('original platform',bound.stderr)
                request(local+'/api/spaces',{'revision':1,'change':{'team_url':'http://127.0.0.1:1','default_space':'auto'}},local)
                failed_team=cli('check');self.assertNotEqual(failed_team.returncode,0);self.assertEqual(json.loads(failed_team.stdout)['url'],'http://127.0.0.1:1')
                request(local+'/api/spaces',{'revision':2,'change':{'team_url':team}},local)
                request(local+'/api/spaces',{'revision':3,'change':{'local_url':'http://127.0.0.1:1','default_space':'local'}},local)
                failed=cli('check');self.assertNotEqual(failed.returncode,0);self.assertEqual(json.loads(failed.stdout)['url'],'http://127.0.0.1:1')
                self.assertEqual(cli('check','--space','team').returncode,0)
            finally:
                for p,stream in processes:
                    p.terminate()
                    try:p.wait(timeout=10)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
                    stream.close()
