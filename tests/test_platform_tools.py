"""One author-to-user workflow through the public tools, not handwritten loop_definitions."""
import io
import base64
import subprocess
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import zipfile
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Conflict
from loop_anything.packaging.packages import load_installed, install
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.packaging.skill_bundle import bundle
from loop_anything.runtime.store import Store


class PlatformToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
        self.tools = PlatformTools(self.store)
        self.engine = Engine(self.store)
        self.draft = self.tools.call('create_loop', {'name': 'Tool-built Loop'})

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def edit(self, name, **arguments):
        self.draft = self.tools.call(name, dict(draft_id=self.draft['draft_id'], revision=self.draft['revision'], **arguments))
        return self.draft

    def test_conversation_entry_needs_no_form_or_artificial_result(self):
        draft=self.tools.call('read_loop',{'draft_id':self.draft['draft_id']})['loop']
        self.assertEqual(draft['loop_definition']['nodes']['initialize']['inputs'],{})
        self.assertEqual(draft['loop_definition']['records'],{})
        self.edit('set_loop',handbook='Discuss the objective, then initialize settings.')
        key=self.tools.call('publish_loop',{'draft_id':self.draft['draft_id'],'revision':self.draft['revision']})['key']
        started=self.tools.call('start_run',{'key':key,'title':'Agreed goal','authorization':'Initialize only'})
        args={'run_id':started['run_id'],'token':started['token']}
        info=self.tools.call('read_task',dict(args,task_id=started['entry_task_id']))
        self.tools.call('complete_task',dict(args,task_id=started['entry_task_id'],task_version=info['task_version'],envelope={'settings':{'objective':'Goal from conversation'},'outputs':{}}))
        self.tools.call('finish',args)
        run=self.store.get(started['run_id'])
        self.assertTrue(run['initialized']);self.assertEqual(run['settings']['objective'],'Goal from conversation')
        self.assertEqual(run['records'],{});self.assertFalse(run['agent_sessions'])

    def test_removal_cleans_generated_types_and_protects_shared_and_published_types(self):
        self.edit('set_loop',handbook='A draft with shared output types.')
        for node in ('a','b'):
            self.edit('put_node',node_id=node,instructions='Work',outputs=[{'name':'result','type':'string'}])
        draft=self.tools.call('read_loop',{'draft_id':self.draft['draft_id']})['loop']
        bp=draft['loop_definition'];bp['nodes']['b']['outputs']['result']['record_type']='a.result'
        bp['records']['spare']={'type':'string'}
        saved=self.store.save_draft(bp,draft['implementations'],draft['id'],draft['revision'])
        self.draft.update(revision=saved['revision'])
        key=self.tools.call('publish_loop',{'draft_id':saved['id'],'revision':saved['revision']})['key']
        original=next(c for c in self.store.catalog() if c['key']==key)
        old_run=self.store.create(key,'Original')
        self.edit('remove_node',node_id='a')
        doc=self.tools.call('read_loop',{'draft_id':saved['id']})['loop']
        self.assertIn('a.result',doc['loop_definition']['records'])
        denied=self.tools.respond('set_loop',dict(draft_id=saved['id'],revision=doc['revision'],remove_records=['a.result','spare']))
        self.assertFalse(denied['ok'])
        # b.result was cleaned when its generated output changed; deleting b leaves a shared type for explicit cleanup.
        self.assertNotIn('b.result',doc['loop_definition']['records'])
        self.edit('put_node',node_id='c',instructions='Work',outputs=[{'name':'out','type':'string'}])
        self.edit('put_node',node_id='c',outputs=[])
        doc=self.tools.call('read_loop',{'draft_id':saved['id']})['loop']
        self.assertNotIn('c.out',doc['loop_definition']['records'])
        self.edit('remove_node',node_id='b')
        report=self.tools.call('validate_loop',{'draft_id':saved['id']})
        self.assertEqual(report['unused_records'],['a.result','spare'])
        self.edit('set_loop',remove_records=report['unused_records'])
        self.assertEqual(self.tools.call('read_loop',{'draft_id':saved['id']})['loop']['loop_definition']['records'],{})
        self.assertEqual(original,next(c for c in self.store.catalog() if c['key']==key))
        self.assertEqual(old_run,self.store.get(old_run['id']))

    def build(self):
        self.edit('put_node', node_id='initialize', inputs=[{'name':'request','type':'string'}], outputs=[{'name':'result','type':'string'}])
        self.edit('set_loop', handbook='AUTHOR BUSINESS INSTRUCTIONS: transform the given text and report it.')
        for id, terminal in [('convert', False), ('finish', True)]:
            self.edit('put_node', node_id=id, instructions='Complete the author task.', inputs=[{'name': 'value', 'type': 'string'}],
                      outputs=[{'name': 'result', 'type': 'string'}], skills=[{'name': 'author-method', 'content': 'AUTHOR METHOD: preserve the supplied result.'}] if terminal else [])
        self.edit('put_asset', path='scripts/convert.py', content="import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({'outputs': {'result': r['inputs']['value'].upper()}}))\n")
        self.edit('set_implementation', node_id='initialize', kind='agent')
        self.edit('set_implementation', node_id='convert', kind='command', command=[sys.executable, 'scripts/convert.py'])
        self.edit('set_implementation', node_id='finish', kind='agent')
        self.edit('put_step', plan='round', step='convert', node_id='convert', inputs={'value': {'record': 'initial.result'}})
        self.edit('put_step', plan='round', step='finish', node_id='finish')
        self.edit('connect_steps', plan='round', from_step='convert', output='result', to_step='finish', input='value')
        self.assertTrue(self.tools.call('validate_loop', {'draft_id': self.draft['draft_id']})['valid'])
        return self.tools.call('publish_loop', {'draft_id': self.draft['draft_id'], 'revision': self.draft['revision']})['key']

    def test_candidate_partial_updates_preserve_fields_and_return_actual_changes(self):
        from loop_anything.runtime.lifecycle import template
        lifecycle = template('agent')
        lifecycle['transitions'].append({'from':'executing','event':'reviewed','to':'executing'})
        self.edit('set_implementation', node_id='initialize', implementation_id='chosen', kind='agent',
                  command=['old'], cwd='/tmp', timeout=42, prompt='Author prompt', lifecycle=lifecycle)
        selected = dict(draft_id=self.draft['draft_id'],node_id='initialize',implementation_id='chosen')
        before = self.tools.call('read_loop', selected)['value']
        change = self.edit('set_implementation', node_id='initialize', implementation_id='chosen', command=['new'])
        self.assertEqual([c['path'] for c in change['changes']], [['implementations','initialize','options','chosen','command']])
        after = self.tools.call('read_loop', selected)['value']
        self.assertEqual(after, dict(before, command=['new']))
        self.edit('set_implementation', node_id='initialize', implementation_id='chosen', kind='agent', command=['newer'])
        self.assertEqual(self.tools.call('read_loop', selected)['value'], dict(before, command=['newer']))
        self.edit('set_implementation', node_id='initialize', implementation_id='chosen', clear=['prompt','timeout'])
        cleared=self.tools.call('read_loop',selected)['value']
        self.assertNotIn('prompt',cleared);self.assertNotIn('timeout',cleared)
        self.assertEqual(cleared['lifecycle'],lifecycle)
        stale=self.tools.respond('set_implementation',dict(selected,revision=change['revision'],command=['stale']))
        self.assertFalse(stale['ok']);self.assertEqual(self.tools.call('read_loop',selected)['value'],cleared)
        self.edit('set_implementation',node_id='$notifications',kind='command',command=['old'],timeout=15)
        self.edit('set_implementation',node_id='$notifications',command=['new'])
        sender=self.tools.call('read_loop',dict(draft_id=self.draft['draft_id'],node_id='$notifications',implementation_id='default'))['value']
        self.assertEqual(sender,{'kind':'command','command':['new'],'timeout':15})
        self.edit('set_implementation',node_id='initialize',kind='agent',command=['default'])
        self.edit('set_implementation',node_id='initialize',implementation_id='chosen',default=True)
        self.edit('set_implementation',node_id='initialize',command=['patched-default'])
        self.assertEqual(self.tools.call('read_loop',{'draft_id':self.draft['draft_id'],'node_id':'initialize'})['value']['implementations']['default'],'chosen')

        schema={'type':'object','properties':{'queue':{'type':'string'}},'required':['queue']}
        self.edit('set_implementation',node_id='initialize',implementation_id='chosen',parameter_schema=schema)
        self.edit('set_implementation',node_id='initialize',implementation_id='chosen',command=['preserve-contract'])
        self.assertEqual(self.tools.call('read_loop',selected)['value']['parameter_schema'],schema)
        invalid=self.tools.respond('set_implementation',dict(selected,revision=self.draft['revision'],parameter_schema={'type':'string'}))
        self.assertFalse(invalid['ok']);self.assertEqual(invalid['error']['path'][-1],'parameter_schema')
        self.edit('set_implementation',node_id='initialize',implementation_id='chosen',clear=['parameter_schema'])
        self.assertNotIn('parameter_schema',self.tools.call('read_loop',selected)['value'])

    def test_targeted_reads_and_files_support_edit_publish_and_delete(self):
        key=self.build()
        draft_id=self.draft['draft_id']
        selected=self.tools.call('read_loop',{'draft_id':draft_id,'node_id':'convert'})
        self.assertNotIn('loop',selected)
        self.assertEqual(selected['value']['node']['outputs']['result']['record_type'],'convert.result')
        self.assertTrue(any(ref['path'][-1]=='convert' for ref in selected['references']))
        step=self.tools.call('read_loop',{'draft_id':draft_id,'plan':'round','step':'convert'})
        self.assertTrue(any(ref['path'][-2:]==['inputs','value'] for ref in step['references']))
        listed=self.tools.call('list_loops',{})
        self.assertEqual(listed['drafts'][0]['loop_id'],listed['loops'][0]['loop_id'])
        path='scripts/convert.py'
        old=self.tools.call('read_loop',{'key':key,'asset_path':path})['value']['content']
        self.edit('put_asset',path=path,content=old,executable=True)
        change=self.edit('put_asset',path=path,content='# updated\n'+old)
        file=self.tools.call('read_loop',{'draft_id':draft_id,'asset_path':path})
        self.assertTrue(file['value']['executable']);self.assertTrue(file['value']['content'].startswith('# updated'))
        self.assertTrue(file['references']);self.assertTrue(change['changes'][0]['content_changed'])
        self.assertEqual(self.tools.call('read_loop',{'key':key,'asset_path':path})['value']['content'],old)
        revision=self.draft['revision']
        failed=self.tools.respond('put_asset',{'draft_id':draft_id,'revision':revision-1,'path':path,'remove':True})
        self.assertFalse(failed['ok'])
        self.assertFalse(self.tools.respond('read_loop',{'draft_id':draft_id,'asset_path':'../outside'})['ok'])
        self.edit('put_asset',path=path,remove=True)
        self.assertFalse(self.tools.respond('read_loop',{'draft_id':draft_id,'asset_path':path})['ok'])
        self.assertEqual(self.tools.call('read_loop',{'key':key,'asset_path':path})['value']['content'],old)

    def test_errors_locate_candidate_or_step_without_partial_writes(self):
        self.build()
        draft_id=self.draft['draft_id'];revision=self.draft['revision']
        before=self.tools.call('read_loop',{'draft_id':draft_id})
        error=self.tools.respond('set_implementation',{'draft_id':draft_id,'revision':revision,'node_id':'convert','timeout':-1})
        self.assertFalse(error['ok'])
        self.assertEqual(error['error']['path'],['implementations','convert','options','default','timeout'])
        self.assertEqual(before,self.tools.call('read_loop',{'draft_id':draft_id}))
        edited=self.edit('put_step',plan='round',step='finish',node_id='finish',inputs={})
        self.assertFalse(edited['validation']['valid'])
        self.assertEqual(edited['validation']['issues'][0]['path'],['plans','round','steps','finish','inputs','value'])
        # An unfinished draft remains editable and reports the precise missing input.
        self.edit('connect_steps',plan='round',from_step='convert',output='result',to_step='finish',input='value')
        self.assertTrue(self.tools.call('validate_loop',{'draft_id':draft_id})['valid'])

    def test_frequent_edits_keep_identity_and_automatically_skip_installed_versions(self):
        key = self.build()
        before = self.store.catalog()
        run = self.store.create(key, 'Existing Run', {'request': 'original'})
        snapshot = self.store.get(run['id'])
        second = self.tools.call('copy_loop', {'key': key, 'new_version': True})
        self.tools.call('publish_loop', {'draft_id': second['draft_id'], 'revision': second['revision'], 'auto_version': True})
        third = self.tools.call('copy_loop', {'key': key, 'new_version': True})
        doc = self.tools.call('read_loop', {'draft_id': third['draft_id']})['loop']
        self.assertEqual('3', doc['loop_definition']['version'])
        changed = self.tools.call('set_loop', {'draft_id': self.draft['draft_id'], 'revision': self.draft['revision'], 'description': 'new requirements'})
        published = self.tools.call('publish_loop', {'draft_id': changed['draft_id'], 'revision': changed['revision'], 'auto_version': True})
        self.assertEqual('3', published['version'])
        self.assertEqual(snapshot, self.store.get(run['id']))
        self.assertEqual(before[0], next(c for c in self.store.catalog() if c['key'] == key))
        self.assertEqual(1, len({c['loop_definition']['id'] for c in self.store.catalog()}))
        stale = self.tools.respond('publish_loop', {'draft_id': changed['draft_id'], 'revision': changed['revision'], 'auto_version': True})
        self.assertFalse(stale['ok'])

    def test_author_tools_publish_then_user_tools_initialize_and_run(self):
        key = self.build()
        started = self.tools.call('start_run', {'key': key, 'title': 'User run', 'inputs': {'request': 'uppercase'}, 'authorization': 'Run this example'})
        id, token = started['run_id'], started['token']
        def call(tool_name, **arguments):
            return self.tools.call(tool_name, dict(run_id=id, token=token, **arguments))
        self.engine.tick(id)
        self.assertEqual([], self.store.get(id)['executions'])
        entry = call('read_task', task_id=started['entry_task_id'])
        call('complete_task', task_id=started['entry_task_id'], task_version=entry['task_version'], envelope={'settings': {'objective': 'Use the author Loop', 'completion_rule': {'op': 'and', 'args': [{'op': 'ge', 'args': [{'path': ['completed', 'finish']}, 1]}, {'op': 'eq', 'args': [{'path': 'active_tasks'}, 0]}]}}, 'outputs': {'result': 'hello'}})
        batch_tasks = call('build_plan', name='round', key='first', values={}, round='第1轮')['tasks']
        for _ in range(100):
            self.engine.tick(id)
            tasks = call('next_tasks')['items']
            if any(t.get('node') == 'finish' for t in tasks):
                break
            time.sleep(.02)
        finish = next(w for w in batch_tasks if w['node'] == 'finish')
        info = call('read_task', task_id=finish['id'])
        self.assertEqual('HELLO', info['inputs']['value'])
        call('complete_task', task_id=finish['id'], task_version=info['task_version'], envelope={'outputs': {'result': info['inputs']['value']}})
        call('finish')
        self.engine.tick(id)
        run = self.store.get(id)
        self.assertEqual('completed', run['status'])
        self.assertEqual({'第1轮'}, {w['spec']['round'] for w in run['tasks'].values() if w['spec']['node'] != 'initialize'})
        self.assertFalse(any(h['kind'] == 'agent_acquired' and h['detail']['kind'] == 'background' for h in run['history']))
        document, _ = load_installed(self.store.filename, key)
        bp = document['loop_definition']
        self.assertEqual('AUTHOR BUSINESS INSTRUCTIONS: transform the given text and report it.', bp['handbook']['instructions'])
        self.assertEqual([{'name': 'author-method', 'content': 'AUTHOR METHOD: preserve the supplied result.'}], bp['nodes']['finish']['skills'])
        self.assertEqual([], bp['nodes']['convert']['skills'])
        self.assertEqual(bp['nodes']['finish']['skills'], info['skills'])
        with zipfile.ZipFile(io.BytesIO(bundle('http://localhost:1234'))) as archive:
            self.assertEqual(['platform/loop-anything-platform/SKILL.md'], [n for n in archive.namelist() if n.endswith('/SKILL.md')])
            self.assertFalse(any(n.startswith('author/') for n in archive.namelist()))
            connection = json.loads(archive.read('platform/loop-anything-platform/connection.json'))
            self.assertEqual({'url': 'http://localhost:1234'}, connection)
            self.assertIn('platform/loop-anything-platform/scripts/call.py', archive.namelist())

    def test_notification_destination_survives_restart_retry_and_parallel_runs(self):
        key = self.build()
        root = Path(self.tmp.name)
        sender = root / 'sender.py'
        sender.write_text("import sys,json,pathlib\nn=json.load(sys.stdin)\np=pathlib.Path(sys.argv[1])\nwith p.open('a') as f:f.write(json.dumps(n)+'\\n')\nprint(json.dumps({'delivered':True}))\n")
        failure = root / 'fail.py'
        failure.write_text("import json,sys;print(json.dumps({'delivered':False,'error':'bridge offline'}));sys.exit(2)")
        destinations = [root / 'first.jsonl', root / 'second.jsonl']
        commands = [[sys.executable, str(sender), str(path)] for path in destinations]
        started = [self.tools.call('start_run', {'key':key,'title':'Chat '+str(i),'authorization':'test',
                   'notification_command':commands[i]}) for i in range(2)]
        def agent(index, tool, **args):
            return self.tools.call(tool, dict(run_id=started[index]['run_id'], token=started[index]['token'], **args))
        for i in range(2):
            with self.store.edit(started[i]['run_id']) as run:
                run['notifications'].append({'id':'notice','tasks':None,'status':'pending','message':'Progress',
                    'route':'user','attempt':0,'at':time.time()})
        # First attempt fails, keeping its destination for a later retry.
        original = sender.read_text(); sender.write_text(failure.read_text())
        self.engine.tick(started[0]['run_id'])
        for f in list(self.engine.futures): f.result()
        notice = self.store.get(started[0]['run_id'])['notifications'][0]
        self.assertEqual('fault',notice['status']); self.assertIn('bridge offline',notice['error'])
        agent(0,'change_settings',revision=1,change={'notification_command':commands[1]})
        self.engine.close(); self.store = Store(root / 'runs.db'); self.engine = Engine(self.store)
        sender.write_text(original)
        self.engine.command(started[0]['run_id'],'retry_notification',notification_id='notice',operator_token=started[0]['token'])
        for item in started: self.engine.tick(item['run_id'])
        for f in list(self.engine.futures): f.result()
        for i in range(2):
            messages = [json.loads(line) for line in destinations[i].read_text().splitlines()]
            self.assertEqual([started[i]['run_id']], [n['run_id'] for n in messages])
            self.assertNotIn('sender',messages[0]); self.assertNotIn('token',messages[0])
            self.assertEqual('delivered',self.store.get(started[i]['run_id'])['notifications'][0]['status'])
        # Completion follows the explicitly updated destination and emits once.
        agent(0,'change_settings',revision=2,change={'termination_signal':'User goal met'})
        agent(0,'finish')
        for _ in range(3): self.engine.tick(started[0]['run_id'])
        for f in list(self.engine.futures): f.result()
        notices = self.store.get(started[0]['run_id'])['notifications']
        self.assertEqual(1,sum(n['id'].startswith('completed:') for n in notices))
        self.assertEqual('运行已完成',json.loads(destinations[1].read_text().splitlines()[-1])['message'])
        # An ended Run can retry delivery without reopening its business state.
        with self.store.edit(started[0]['run_id']) as run:
            run['notifications'][-1]['status'] = 'fault'
        self.assertTrue(self.tools.call('retry_notification', {'run_id':started[0]['run_id'], 'notification_id':notices[-1]['id']})['queued'])
        self.assertEqual('completed',self.store.get(started[0]['run_id'])['status'])


    def test_cc_connect_sender_captures_context_and_uses_argv_stdin(self):
        import importlib.util
        import os
        from unittest.mock import patch
        script = Path(__file__).resolve().parents[1] / 'skills/loop-anything-platform/scripts/notify_cc_connect.py'
        spec = importlib.util.spec_from_file_location('notify_sender_test',script)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        root = Path(self.tmp.name); executable = root / 'cc-connect'
        capture = root / 'sent.json'
        executable.write_text('#!' + sys.executable + '\nimport sys,json,pathlib\npathlib.Path('+repr(str(capture))+').write_text(json.dumps({"argv":sys.argv[1:],"text":sys.stdin.read()}))\n')
        executable.chmod(0o755)
        with patch.dict(os.environ, {'CC_PROJECT':'project A','CC_SESSION_KEY':'feishu:original','CC_DATA_DIR':str(root)}), patch.object(module.shutil,'which',return_value=str(executable)):
            command = module.sender_command()
        printed = subprocess.run([sys.executable,str(script),'--print-command'],text=True,capture_output=True,
            env=dict(os.environ,PATH=str(root)+os.pathsep+os.environ.get('PATH',''),CC_PROJECT='project A',CC_SESSION_KEY='feishu:original',CC_DATA_DIR=str(root)))
        self.assertEqual(0,printed.returncode,printed.stderr)
        self.assertEqual(command,json.loads(printed.stdout))
        self.assertFalse(capture.exists(), 'Generating adapter configuration must not send a message')
        payload = {'id':'n1','title':'Run','run_id':'r1','message':'a "quote"\n$(touch bad) `echo nope`'}
        result = subprocess.run(command,input=json.dumps(payload),text=True,capture_output=True,
                                env=dict(os.environ,CC_PROJECT='wrong',CC_SESSION_KEY='wrong',CC_DATA_DIR='/wrong'))
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertTrue(json.loads(result.stdout)['delivered'])
        sent = json.loads(capture.read_text())
        self.assertEqual(['send','--project','project A','--session','feishu:original','--data-dir',str(root.resolve()),'--stdin'],sent['argv'])
        self.assertIn(payload['message'],sent['text'])
        with patch.dict(os.environ,{'CC_PROJECT':'','CC_SESSION_KEY':''}):
            with self.assertRaises(ValueError): module.sender_command()
        executable.write_text('#!' + sys.executable + '\nimport sys;sys.stderr.write("bridge offline");sys.exit(1)\n')
        failed = subprocess.run(command,input=json.dumps(payload),text=True,capture_output=True)
        self.assertNotEqual(0,failed.returncode); self.assertFalse(json.loads(failed.stdout)['delivered'])

    def test_portable_client_accepts_generic_notification_command(self):
        import importlib.util
        from unittest.mock import patch
        script = Path(__file__).resolve().parents[1] / 'skills/loop-anything-platform/scripts/call.py'
        spec = importlib.util.spec_from_file_location('platform_client_test',script)
        client = importlib.util.module_from_spec(spec); spec.loader.exec_module(client)
        command = [sys.executable, '/custom bridge/send.py', '--destination', 'chosen-chat']
        path = Path(self.tmp.name) / 'command.json'; path.write_text(json.dumps(command))
        for tool,args in [('start_run',{'key':'loop','title':'Example','authorization':'test'}),
                          ('change_settings',{'run_id':'r','token':'own-token','revision':3,'change':{'guidance':'keep this'}})]:
            argv = [str(script),tool,'--url','http://127.0.0.1:8767','--notification-command','@'+str(path),'--arguments',json.dumps(args)]
            with patch.object(sys,'argv',argv), patch.object(client,'fetch',return_value={'ok':True}) as send, patch('sys.stdout',new=io.StringIO()):
                with self.assertRaises(SystemExit) as done: client.main()
            self.assertEqual(0,done.exception.code)
            posted = json.loads(send.call_args.kwargs['data'])['arguments']
            if tool=='change_settings':
                self.assertEqual('keep this',posted['change']['guidance']); posted=posted['change']
            self.assertEqual(command,posted['notification_command'])

    def test_any_entry_reads_without_ownership_and_continues_same_timeline(self):
        from unittest.mock import patch
        key = self.build()
        terminal = self.tools.call('start_run', {'key':key,'title':'Shared research','inputs':{'request':'compare'},
                     'authorization':'Edit this Run','notification_command':[sys.executable,'sender-for-original-chat.py']})
        rid = terminal['run_id']
        def write(session, tool_name, **args):
            return self.tools.call(tool_name,dict(run_id=rid,token=session['token'],**args))
        before = self.store.get(rid)
        # Reading must not enter Store.edit, even while another entry owns the Run.
        with patch.object(self.store,'edit',side_effect=AssertionError('read entered a write transaction')):
            self.assertEqual([rid],[x['id'] for x in self.tools.call('list_runs',{'query':'SHARED','status':'running'})['runs']])
            snapshot = self.tools.call('read_timeline',{'run_id':rid})
            self.assertTrue(snapshot['read_only'])
            self.assertEqual(rid,snapshot['run_id'])
            self.tools.call('next_tasks',{'run_id':rid})
            self.tools.call('read_plans',{'run_id':rid})
            task = self.tools.call('read_task',{'run_id':rid,'task_id':terminal['entry_task_id']})
            raw = self.tools.call('read_run',{'run_id':rid})
            self.assertNotIn(terminal['token'],json.dumps(raw))
        self.assertEqual(before,self.store.get(rid))
        with self.assertRaises(Conflict): self.tools.call('acquire_run',{'run_id':rid})
        self.assertFalse(self.tools.respond('change_settings',{'run_id':rid,'revision':1,'change':{'objective':'unauthorized'}})['ok'])
        write(terminal,'complete_task',task_id=terminal['entry_task_id'],task_version=task['task_version'],
              envelope={'settings':{'objective':'Original objective'},'outputs':{'result':'Evidence from terminal'}})
        batch = write(terminal,'build_plan',name='round',key='one',values={})['tasks']
        write(terminal,'finish')
        with self.assertRaises(Conflict): write(terminal,'read_timeline')
        # A fresh Agent with no chat history can inspect facts and edit the same Run.
        feishu = self.tools.call('acquire_run',{'run_id':rid})
        self.assertNotEqual(feishu['token'],terminal['token'])
        timeline = write(feishu,'read_timeline'); self.assertFalse(timeline['read_only'])
        record = self.tools.call('read_record',{'run_id':rid,'id':'initial.result'})
        self.assertEqual('Evidence from terminal',record['record']['value'])
        write(feishu,'change_settings',revision=timeline['settings']['revision'],change={'objective':'Revised in Feishu','guidance':'Use the saved evidence'})
        convert = next(t for t in batch if t['node']=='convert')
        write(feishu,'change_task',task_id=convert['id'],operation='update',inputs={'value':{'literal':'new input'}},reason='User changed the input')
        write(feishu,'finish')
        weixin = self.tools.call('read_timeline',{'run_id':rid})
        self.assertEqual('Revised in Feishu',weixin['settings']['objective'])
        self.assertEqual({'value':'new input'},self.tools.call('read_task',{'run_id':rid,'task_id':convert['id']})['inputs'])
        self.assertEqual(before['settings']['notification_command'],weixin['settings']['notification_command'])
        self.assertEqual(1,len(self.store.list()))
        self.assertEqual([],self.store.get(rid)['agent_sessions'])
        weixin_owner = self.tools.call('acquire_run',{'run_id':rid})
        with self.assertRaises(Conflict):
            write(weixin_owner,'change_settings',revision=timeline['settings']['revision'],change={'guidance':'stale overwrite'})
        write(weixin_owner,'change_settings',revision=weixin['settings']['revision'],change={'guidance':'Confirmed in Weixin'})
        write(weixin_owner,'finish')
        self.assertEqual('Confirmed in Weixin',self.tools.call('read_timeline',{'run_id':rid})['settings']['guidance'])
        self.assertEqual([],self.tools.call('list_runs',{'status':'completed'})['runs'])

    def test_readonly_inspection_of_active_agents_and_completed_run(self):
        key = self.build()
        run = self.store.create(key,'Inspectable',inputs={'request':'test'})
        rid = run['id']; self.engine.tick(rid)
        before = self.store.get(rid)
        work = self.tools.call('next_tasks',{'run_id':rid})
        self.assertFalse(any(i.get('task_id')=='initialize' for i in work['items']))
        self.assertTrue(any(i.get('task_id')=='initialize' for i in work['waiting']))
        token = before['agent_sessions'][0]['token']
        self.assertTrue(any(i.get('task_id')=='initialize' for i in self.tools.call('next_tasks',{'run_id':rid,'token':token})['items']))
        self.assertEqual(before,self.store.get(rid))
        self.assertFalse(self.tools.respond('read_timeline',{'run_id':rid,'token':'invalid'})['ok'])
        self.engine.command(rid,'terminate',operator_token=token)
        snapshot = self.tools.call('read_timeline',{'run_id':rid})
        self.assertEqual('terminated',snapshot['status']); self.assertTrue(snapshot['read_only'])
        self.assertEqual([rid],[x['id'] for x in self.tools.call('list_runs',{'status':'terminated'})['runs']])

    def test_skill_paths_resolve_resources_after_installing_on_another_machine(self):
        self.edit('set_loop', handbook_path='skills/loop/SKILL.md')
        self.edit('put_node', node_id='initialize', skills=[{'name': 'initializer', 'path': 'skills/node/SKILL.md'}])
        self.assertFalse(self.tools.call('validate_loop', {'draft_id': self.draft['draft_id']})['valid'])
        resources = {
            'skills/loop/SKILL.md': 'Read [method](references/method.md).',
            'skills/loop/references/method.md': 'Loop business method',
            'skills/node/SKILL.md': 'Read [method](references/method.md); run scripts/check.py.',
            'skills/node/references/method.md': 'Node business method',
            'skills/node/scripts/check.py': "print('node script')",
        }
        for path, content in resources.items():
            self.edit('put_asset', path=path, content=content)
        self.edit('set_implementation', node_id='initialize', kind='agent')
        self.assertTrue(self.tools.call('validate_loop', {'draft_id': self.draft['draft_id']})['valid'])
        archive = self.tools.call('export_loop', {'draft_id': self.draft['draft_id']})
        target = Store(Path(self.tmp.name) / 'receiving machine' / 'runs.db')
        key = install(target, base64.b64decode(archive['base64']))['key']
        tools = PlatformTools(target)
        loop = tools.call('read_loop', {'key': key})['loop']['loop_definition']
        loop_entry = Path(loop['handbook']['resolved_path'])
        self.assertTrue(loop_entry.is_absolute())
        self.assertIn('receiving machine', str(loop_entry))
        self.assertEqual('Loop business method', (loop_entry.parent / 'references/method.md').read_text())
        run = tools.call('start_run', {'key': key, 'title': 'Read skills', 'inputs': {'request': 'Read only'}, 'authorization': 'Read the fixture Skills'})
        arguments = {'run_id': run['run_id'], 'token': run['token']}
        task = tools.call('read_task', dict(arguments, task_id=run['entry_task_id']))
        node_entry = Path(task['skills'][0]['resolved_path'])
        self.assertEqual('Node business method', (node_entry.parent / 'references/method.md').read_text())
        output = subprocess.check_output([sys.executable, str(node_entry.parent / 'scripts/check.py')], text=True)
        self.assertEqual('node script', output.strip())
        self.assertEqual(str(loop_entry), tools.call('read_timeline', arguments)['handbook']['resolved_path'])
        document, _ = load_installed(target.filename, key)
        self.assertEqual({'instructions': '', 'path': 'skills/loop/SKILL.md'}, document['loop_definition']['handbook'])
        copied = tools.call('copy_loop', {'key': key})
        draft = tools.call('read_loop', {'draft_id': copied['draft_id']})['loop']
        self.assertNotIn('resolved_path', draft['loop_definition']['handbook'])
        self.assertEqual('skills/node/SKILL.md', draft['loop_definition']['nodes']['initialize']['skills'][0]['path'])

    def test_stale_edits_and_bad_connections_do_not_change_the_draft(self):
        before = self.tools.call('read_loop', {'draft_id': self.draft['draft_id']})
        with self.assertRaises(Conflict):
            self.tools.call('set_loop', {'draft_id': self.draft['draft_id'], 'revision': 0, 'name': 'overwrite'})
        self.assertEqual(before, self.tools.call('read_loop', {'draft_id': self.draft['draft_id']}))
        self.assertFalse(self.tools.respond('publish_loop', {'draft_id': self.draft['draft_id'], 'revision': self.draft['revision']})['ok'])
        self.assertEqual([], self.store.catalog())
        key = self.build()
        original = self.tools.call('read_loop', {'key': key})
        copied = self.tools.call('copy_loop', {'key': key})
        self.tools.call('set_loop', {'draft_id': copied['draft_id'], 'revision': copied['revision'], 'name': 'Changed copy'})
        self.assertEqual(original, self.tools.call('read_loop', {'key': key}))


if __name__ == '__main__':
    unittest.main()
