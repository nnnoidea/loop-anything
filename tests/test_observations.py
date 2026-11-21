"""Durable facts, independent observers and live method changes through public tools."""
import copy
import json
import sys
import unittest

import test_work_context as fixture
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.runtime import events, observations, work


# Embedded scripts use the same bound client and read tools as an authored Loop.
READ = """import json,subprocess,sys
d=json.load(sys.stdin)
def read(tool, **args):
    args['timeline_id']=d['timeline_id']
    answer=subprocess.check_output([sys.executable,d['platform_client'],tool,'--arguments',json.dumps(args)])
    return json.loads(answer)['records']
"""


def chart(title):
    code=READ+"""scores=[r['value'] for r in read('read_work_results') if r['value'] in ('measured','old','new')]
print(json.dumps({'summary':sys.argv[1]+str(len(scores)), 'series':[{'label':'score','points':[[i,len(v)] for i,v in enumerate(scores)]}]}))
"""
    return {'description':title,'steps':[{'kind':'command','command':[sys.executable,'-c',code,title]}],
            'on':{'kind':'result','node':'work'}}


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.c=fixture.WorkContextTests()
        self.c.setUp()
        self.addCleanup(self.c.doCleanups)
        self.store,self.engine,self.tools=self.c.store,self.c.engine,self.c.tools
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        tools = self.tools
        class Endpoint(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def reply(self,value):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())
            def do_GET(self):
                self.reply({'workspace_id':'observation-test'})
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.reply(tools.respond(body['tool'],body['arguments']))
        http=ThreadingHTTPServer(('127.0.0.1',0),Endpoint)
        thread=threading.Thread(target=http.serve_forever,kwargs={'poll_interval':.02},daemon=True)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(http.shutdown)
        self.engine.platform_url='http://127.0.0.1:%d' % http.server_port
        self.turn=self.c.start()
        self.run_id=self.turn['run_id']
        self.tid=self.turn['timeline_id']
        self.rt=RunTools(self.store,self.run_id,self.turn['token'])

    def update(self,**options):
        return self.tools.call('update_run_method',dict(run_id=self.run_id,token=self.turn['token'],**options))

    def views(self):
        return self.tools.call('read_observations',{'timeline_id':self.tid})

    def finish(self):
        self.rt.call('report_task',{'event':'completed','task_id':self.turn['task_id'],'report_id':'done',
                                     'envelope':{'outputs':{'decision':'arranged'}}})
        self.rt.call('finish',{})

    def claim(self,key):
        self.tools.call('submit_run_request',{'run_id':self.run_id,'request_id':key,'operation':'message','message':key})
        self.turn=self.tools.call('claim_run',dict(self.c.session,run_id=self.run_id))
        self.rt=RunTools(self.store,self.run_id,self.turn['token'])

    def drain(self):
        for _ in range(4):
            jobs=observations.collect(self.store)
            if not jobs:return
            for job in jobs:observations.execute(self.engine,job)
        self.fail('observation loop')

    def test_snapshot_then_fanout_preview_and_retry(self):
        self.update(observations={'a':chart('A'),'b':chart('B')})
        initial=observations.collect(self.store)
        self.assertEqual(len(initial),2)
        task=self.rt.call('add_task',{'key':'job','node_id':'work','inputs':{}})['tasks'][0]['id']
        self.finish()
        self.engine.tick(self.run_id)
        self.engine.event(self.run_id,'e','result',{'value':'measured'})
        self.engine.tick(self.run_id)
        self.assertEqual(self.store.get(self.run_id)['tasks'][task]['status'],'completed')
        for job in initial:observations.execute(self.engine,job)
        self.assertEqual({v['view']['summary'] for v in self.views()['views']},{'A0','B0'})
        self.drain()
        self.assertEqual({v['view']['summary'] for v in self.views()['views']},{'A1','B1'})
        self.claim('change')
        self.assertFalse(any(n['id'].startswith('observation:') for n in self.store.get(self.run_id)['notifications']))
        self.tools.call('refresh_observation',{'run_id':self.run_id,'name':'a','token':self.turn['token']})
        old=observations.collect(self.store)[0]
        self.update(observations={'a':chart('new'),'b':None})
        self.drain()
        observations.execute(self.engine,old)
        data=self.views()
        self.assertEqual([r['name'] for r in data['arrangements']],['a'])
        self.assertIn('new1',[v['view']['summary'] for v in data['views']])

    def test_rollback_no_event_and_interrupted_claim_no_relaunch(self):
        with self.store.connection() as db:
            pos=events.position(db)
            events.emit(db,'state',self.tid,self.run_id,'score',{})
            db.rollback()
            self.assertEqual(events.position(db),pos)
        self.update(observations={'a':chart('A')})
        self.assertEqual(len(observations.collect(self.store)),1)
        work.WorkRuntime(self.engine)
        self.assertEqual(self.views()['arrangements'][0]['status'],'pending')
        self.assertEqual(len(observations.collect(self.store)),1)
        with work.transaction(self.store) as db:
            db.execute("UPDATE observation_jobs SET status='running'")
        work.WorkRuntime(self.engine)
        self.assertEqual(self.views()['arrangements'][0]['status'],'unknown')
        self.assertFalse(observations.collect(self.store))
        self.tools.call('refresh_observation',{'run_id':self.run_id,'name':'a','token':self.turn['token'],'confirmed_stopped':True})
        self.drain()
        self.assertEqual(self.views()['views'][0]['view']['summary'],'A0')

    def test_published_follow_preserves_local_overrides_inflight_and_run_id(self):
        self.update(follow=True,observations={'local':chart('local')})
        task=self.rt.call('add_task',{'key':'one','node_id':'work','inputs':{}})['tasks'][0]['id']
        self.finish()
        self.engine.tick(self.run_id)
        old=self.store.get(self.run_id)
        old_attempt=old['tasks'][task]['execution_id']
        other=self.tools.call('start_run',dict(self.c.session,key=self.c.key,title='pinned',request_id='pinned'))
        from loop_anything.packaging.packages import load_installed,install,make_archive
        doc,_=load_installed(self.store.filename,self.c.key)
        bp=copy.deepcopy(doc['loop_definition'])
        bp.update(version='next',observations={'team':chart('team')})
        impl=copy.deepcopy(doc['implementations'])
        next(iter(impl['work']['options'].values()))['event']='new-event'
        installed=install(self.store,make_archive({'loop_definition':bp,'implementations':impl},{}))
        self.assertEqual(self.store.get(self.run_id)['loop_key'],self.c.key)
        self.store.publish(bp,impl)
        updated=self.store.get(self.run_id)
        self.assertEqual(updated['loop_key'],installed['key'])
        self.assertEqual(updated['timeline_id'],self.tid)
        self.assertEqual(self.store.get(other['run_id'])['loop_key'],self.c.key)
        self.assertEqual(updated['tasks'][task]['execution_id'],old_attempt)
        self.assertEqual({r['name'] for r in self.views()['arrangements']},{'team','local'})
        self.engine.event(self.run_id,'old-finish','result',{'value':'old'})
        self.engine.tick(self.run_id)
        self.assertEqual(self.store.get(self.run_id)['tasks'][task]['status'],'completed')
        self.claim('more work')
        new=self.rt.call('add_task',{'key':'two','node_id':'work','inputs':{}})['tasks'][0]['id']
        self.finish()
        self.engine.tick(self.run_id)
        self.engine.event(self.run_id,'new-finish','new-event',{'value':'new'})
        self.engine.tick(self.run_id)
        self.assertEqual(self.store.get(self.run_id)['tasks'][new]['status'],'completed')
        self.drain()
        self.assertEqual({v['view']['summary'] for v in self.views()['views']},{'team2','local2'})

    def test_remote_restart_uses_same_receipt_and_retires_removed_observer(self):
        worker = {'id':'worker', 'name':'Observation worker', 'owner':'test'}
        self.engine.executors.register(worker)
        definition = {'steps':[{'kind':'command', 'executor':worker['id'],
                                'command':[sys.executable,'-c','import json; print(json.dumps(dict(summary="Remote result")))']}]}
        self.update(observations={'remote':definition})
        self.drain()
        packet, = self.engine.executors.poll(worker)['jobs']
        context = packet['payload']['prompt_context']
        self.assertEqual(context['run_id'], self.run_id)
        self.assertEqual(set(context), {'run_id','timeline_id','loop_key','platform_url','platform_client','reason'})
        with work.transaction(self.store) as db:
            # Process stopped after the receiver accepted the call, before the worker yielded.
            db.execute("UPDATE observation_jobs SET status='running'")
        work.WorkRuntime(self.engine)
        self.drain()
        self.assertEqual([j['id'] for j in self.engine.executors.poll(worker)['jobs']], [packet['id']])
        def finish_on_worker(job):
            self.engine.executors.report(job['id'], job['token'], {
                'sequence':1, 'state':'completed',
                'result':{'returncode':0,'stdout':'{"summary":"Remote result"}','stderr':''}})
        finish_on_worker(packet)
        self.drain()
        self.assertTrue(self.engine.executors.get(packet['id'])['applied'])
        self.assertEqual(self.views()['views'][0]['view']['summary'], 'Remote result')
        self.tools.call('refresh_observation', {'run_id':self.run_id, 'token':self.turn['token'], 'name':'remote'})
        self.drain()
        late, = self.engine.executors.poll(worker)['jobs']
        self.update(observations={'remote':None})
        finish_on_worker(late)
        observations.release_receipts(self.engine)
        self.assertTrue(self.engine.executors.get(late['id'])['applied'])
        self.assertFalse(self.views()['arrangements'])

    def test_hook_schedule_and_preview_share_steps_but_only_schedule_notifies(self):
        definition = chart('Chart')
        definition.update(on={'kind':'signal','subject':'score-ready'}, every=3600,
                          notify_on=['schedule'], route='workspace', web_url='https://team.example')
        code = "import sys,json;d=json.load(sys.stdin);print(json.dumps({'summary':d['reason']+' '+d['previous']['summary']}))"
        definition['steps'].append({'kind':'agent','command':[sys.executable,'-c',code], 'prompt':'{{context}}'})
        self.update(observations={'result':definition})
        run = self.store.get(self.run_id)
        hook = {'id':'scored','action':'signal','name':'score-ready','target':{'node':'work'},
                'frequency':'always','phase':'after'}
        self.rt.call('change_settings', {'revision':run['settings']['revision'], 'change':{'hooks':[hook]}})
        self.drain()
        self.assertEqual(self.views()['views'][0]['view']['summary'], 'initial Chart0')
        self.rt.call('add_task', {'key':'score', 'node_id':'work','inputs':{}})
        self.finish()
        self.engine.tick(self.run_id)
        self.engine.event(self.run_id,'scored','result',{'value':'measured'})
        self.engine.tick(self.run_id)
        self.drain()
        self.assertEqual(self.views()['views'][0]['view']['summary'], 'event Chart1')
        def observation_notices():
            return [n for n in self.store.get(self.run_id)['notifications'] if n['id'].startswith('observation:')]
        self.assertFalse(observation_notices())
        with work.transaction(self.store) as db:
            db.execute("UPDATE observations SET due=0")
        self.drain()
        notice, = observation_notices()
        self.assertEqual(notice['requested_route'], 'workspace')
        self.assertIn('schedule Chart1', notice['message'])
        self.assertIn('/#work/timelines/'+self.tid, notice['message'])
        self.claim('change')
        self.update(observations={'result':{'steps':[{'kind':'command','command':[sys.executable,'-c','raise ValueError("boom")']}]}})
        self.drain()
        self.assertEqual(self.views()['arrangements'][0]['status'], 'failed')
        self.assertEqual(self.views()['views'][0]['view']['summary'], 'schedule Chart1')

    def test_following_removed_default_preserves_run_local_observation(self):
        self.update(follow=True)
        from loop_anything.packaging.packages import load_installed
        document, _ = load_installed(self.store.filename, self.c.key)
        bp = document['loop_definition']
        bp.update(version='with-overview', observations={'shared':dict(chart('Shared'), every=60)})
        self.store.publish(bp, document['implementations'])
        self.update(observations={
            'shared':{'daily':'18:00','timezone':'Asia/Shanghai'},
            'personal':chart('Personal')})
        self.drain()
        self.assertEqual({v['view']['summary'] for v in self.views()['views']}, {'Shared0','Personal0'})
        bp.update(version='without-overview', observations={})
        receipt = self.store.publish(bp, document['implementations'])
        self.assertEqual(self.store.get(self.run_id)['loop_key'], receipt['key'])
        self.assertEqual([a['name'] for a in self.views()['arrangements']], ['personal'])
        self.assertEqual({v['name'] for v in self.views()['views']}, {'shared','personal'})

    def test_each_state_event_reads_its_committed_revision(self):
        from loop_anything.runtime.business_state import apply
        program = READ+"""e=d['trigger']
r=read('read_business_state', type=e['type'],id=e['subject'],revision=e['revision'])[0] if e else None
print(json.dumps({'summary':str(r['value']) if r else 'initial'}))
"""
        self.update(observations={'revisions':{
            'on':{'kind':'state','type':'metric'}, 'each':True, 'notify_on':['event'],
            'condition':{'op':'eq','args':[{'path':'reason'},'event']},
            'steps':[{'kind':'command','command':[sys.executable,'-c',program]}]}})
        self.drain()
        for score in [12,27]:
            with self.store.edit(self.run_id) as run:
                apply(run, run['executions'][0], [{'type':'metric','id':'best','value':score}])
        self.drain()
        messages = [n['message'] for n in self.store.get(self.run_id)['notifications'] if n['id'].startswith('observation:')]
        self.assertEqual(messages, ['12','27'])
        self.assertEqual(self.views()['views'][0]['view']['summary'], '27')

    def test_metadata_publication_keeps_queued_notifications_cursor_and_timer(self):
        from loop_anything.packaging.packages import load_installed
        from loop_anything.runtime.business_state import apply

        self.update(follow=True, observations={'mine':dict(
            chart('score'), on={'kind':'state'}, each=True, every=3600, notify_on=['event'])})
        self.drain()

        def score(value):
            with self.store.edit(self.run_id) as run:
                apply(run, run['executions'][0], [{'type':'metric','id':'best','value':value}])

        def subscription(db):
            return tuple(db.execute('SELECT generation,cursor,due FROM observations').fetchone())

        score(1)
        with work.transaction(self.store) as db:
            observations.dispatch(db, 0)
            before = subscription(db)
            first = db.execute('SELECT id FROM observation_jobs').fetchone()[0]
        score(2)  # Committed but not yet dispatched when the author publishes.
        doc, _ = load_installed(self.store.filename, self.c.key)
        self.store.publish(dict(doc['loop_definition'], version='label-change', description='new label'),
                           doc['implementations'])
        with self.store.connection() as db:
            self.assertEqual(subscription(db), before)
            self.assertEqual([tuple(r) for r in db.execute('SELECT id,reason FROM observation_jobs')], [(first,'event')])
        self.drain()
        notices = [n['id'] for n in self.store.get(self.run_id)['notifications'] if n['id'].startswith('observation:')]
        self.assertEqual(len(notices), 2)
        self.assertIn('observation:'+str(first), notices)

    def test_packaged_script_edit_honors_old_deliveries_and_draws_new_view(self):
        from loop_anything.packaging.packages import install, load_installed, make_archive
        from loop_anything.runtime.business_state import apply
        from loop_anything.runtime.run_methods import published

        doc, _ = load_installed(self.store.filename, self.c.key)
        cfg = {'steps':[{'kind':'command','command':[sys.executable,'view.py']}],
               'on':{'kind':'state'}, 'each':True, 'notify_on':['event'], 'route':'workspace'}
        def publish(version):
            bp = dict(doc['loop_definition'], version=version, observations={'chart':cfg})
            content = "import json; print(json.dumps({'summary':%r}))" % version
            package = make_archive({'loop_definition':bp,'implementations':doc['implementations']},
                                   {'view.py':(content.encode(),False)})
            return published(self.store,install(self.store,package))

        self.update(follow=True)
        old_key = publish('before')['key']
        self.drain()
        with self.store.edit(self.run_id) as run:
            apply(run, run['executions'][0], [{'type':'score','id':'test','value':10}])
        # The new publication must account for unprocessed facts under the original script.
        publish('after')
        from loop_anything.runtime.model import Conflict
        from loop_anything.runtime.run_library import manage_loop
        with self.assertRaisesRegex(Conflict,'observation'):
            manage_loop(self.store,key=old_key,delete=True)
        jobs = {j['reason']:j for j in observations.collect(self.store)}
        self.assertEqual(set(jobs), {'event','initial'})
        observations.execute(self.engine,jobs['initial'])
        observations.execute(self.engine,jobs['event'])
        self.drain()
        self.assertEqual(self.views()['views'][0]['view']['summary'], 'after')
        notices = [n for n in self.store.get(self.run_id)['notifications'] if n['id'].startswith('observation:')]
        self.assertEqual([n['message'] for n in notices], ['before'])
        self.assertEqual(notices[0]['requested_route'], 'workspace')
        manage_loop(self.store,key=old_key,delete=True)

    def test_follow_update_preserves_disabled_run_roles_and_replaces_missing_reference(self):
        from test_timeline_runtime import RuntimeTests, node
        from loop_anything.interfaces.platform_tools import PlatformTools

        case = RuntimeTests()
        case.setUp()
        self.addCleanup(case.tearDown)
        case.bp['nodes']['repair'] = node()
        case.implementations['repair'] = copy.deepcopy(case.implementations['produce'])
        case.bp.update(fallback_node='repair', global_agent_node='produce')
        entry = case.start()
        tools = PlatformTools(case.store)
        run_tools = RunTools(case.store,case.id,entry['token'])
        run_tools.call('change_settings',{'revision':case.read()['settings']['revision'],
                       'change':{'global_agent_node':'','fallback_node':None}})
        tools.call('update_run_method',{'run_id':case.id,'token':entry['token'],'follow':True})
        case.store.publish(dict(case.bp,version='metadata'),case.implementations)
        self.assertFalse(case.read()['settings']['fallback_node'])
        self.assertFalse(case.read()['settings']['global_agent_node'])

        run_tools.call('change_settings',{'revision':case.read()['settings']['revision'],
                       'change':{'global_agent_node':'repair'}})
        updated = copy.deepcopy(case.bp)
        updated.update(version='remove-repair', fallback_node=None)
        del updated['nodes']['repair']
        case.store.publish(updated,{k:v for k,v in case.implementations.items() if k!='repair'})
        self.assertEqual(case.read()['settings']['global_agent_node'], 'produce')
        self.assertFalse(case.read()['settings']['fallback_node'])

    def test_remote_delivery_reconnects_after_followed_version_change(self):
        from loop_anything.packaging.packages import load_installed
        from loop_anything.runtime.business_state import apply

        worker = {'id':'worker','name':'Remote observer','owner':'test'}
        self.engine.executors.register(worker)
        old = dict(chart('old'), on={'kind':'state'}, each=True, notify_on=['event'], route='workspace')
        old['steps'].append({'kind':'command','executor':worker['id'],
                             'command':[sys.executable,'-c',
                                        "import json,sys;print(json.dumps(json.load(sys.stdin)['previous']))"]})
        self.update(follow=True)
        doc, _ = load_installed(self.store.filename, self.c.key)
        def publish(version, config):
            self.store.publish(dict(doc['loop_definition'], version=version, observations={'chart':config}),
                               doc['implementations'])
        def report(packet, summary):
            self.engine.executors.report(packet['id'],packet['token'],{
                'sequence':1,'state':'completed','result':{'returncode':0,'stdout':json.dumps({'summary':summary}),'stderr':''}})

        publish('original',old)
        self.drain()
        initial, = self.engine.executors.poll(worker)['jobs']
        report(initial,'original')
        self.drain()
        with self.store.edit(self.run_id) as run:
            apply(run,run['executions'][0],[{'type':'score','id':'a','value':1}])
        self.drain()
        late, = self.engine.executors.poll(worker)['jobs']
        event_input = late['payload']['prompt_context']
        self.assertEqual(event_input['reason'], 'event')
        self.assertEqual(event_input['previous']['summary'], 'old0')
        self.assertNotIn('trigger', event_input)
        publish('changed',chart('updated'))
        self.drain()
        self.assertEqual(self.views()['views'][0]['view']['summary'], 'updated0')
        work.WorkRuntime(self.engine)
        report(late,'old receipt')
        self.drain()
        self.assertTrue(self.engine.executors.get(late['id'])['applied'])
        self.assertEqual(len(self.engine.executors.calls()), 2)
        self.assertEqual(self.views()['views'][0]['view']['summary'], 'updated0')
        notices = [n for n in self.store.get(self.run_id)['notifications'] if n['id'].startswith('observation:')]
        self.assertEqual([(n['message'],n['requested_route']) for n in notices], [('old receipt','workspace')])

    def test_platform_extracts_large_history_before_remote_render(self):
        import time
        from unittest.mock import patch
        from loop_anything.runtime.business_state import apply
        from loop_anything.runtime.executor_client import Receiver

        team = self.c.root / 'team'
        team.mkdir()
        self.engine.executors.root = str(team)
        receiver = Receiver({'server':'nas://' + str(team)}, self.c.root / 'receiver')
        self.addCleanup(receiver.close)
        receiver.tick()
        self.engine.executors.sync()

        private = 'LOCAL_EVIDENCE_ONLY'
        with self.store.edit(self.run_id) as run:
            history = [{'type':'notes','id':str(i),'value':private + 'x' * (512 * 1024)} for i in range(65)]
            history.append({'type':'trial','id':'candidate','value':{'latency':37,'notes':private}})
            apply(run,run['executions'][0],history)
        extract = READ+"""assert 'state' not in d and 'results' not in d
points=[[i,r['value']['latency']] for i,r in enumerate(read('read_business_state',type='trial'))]
print(json.dumps({'points':points}))
"""
        render = """import json,subprocess,sys
d=json.load(sys.stdin)
request={'key':d['loop_key'],'asset_path':'units.txt'}
unit=json.loads(subprocess.check_output([sys.executable,d['platform_client'],'read_loop','--arguments',json.dumps(request)]))['value']['content']
assert unit=='ms'
assert not {'results','state','trigger','timeline'} & d.keys()
print(json.dumps({'series':[{'label':'latency','points':d['previous']['points']}]}))
"""
        from loop_anything.packaging.packages import load_installed, make_archive, install
        doc,_ = load_installed(self.store.filename,self.c.key)
        bp = dict(doc['loop_definition'],version='plot-assets')
        assets = {'draw.py':(('from helper import label\n'+render.replace("'latency'",'label')).encode(),False),
                  'helper.py':(b'label="latency"\n',False), 'units.txt':(b'ms',False),
                  'scratch/unused.bin':(b'UNUSED_RESOURCE'*80000,False)}
        installed=install(self.store,make_archive({'loop_definition':bp,'implementations':doc['implementations']},assets))
        selected=self.tools.call('read_loop',{'key':installed['key'],'asset_path':'helper.py'})
        self.assertEqual(selected['value']['content'],'label="latency"\n')
        self.update(key=installed['key'],observations={'latency':{
            'on':{'kind':'state','type':'trial'},
            'condition':{'op':'ge','args':[{'op':'len','args':[{'path':'state'}]},1]},
            'steps':[{'kind':'command','command':[sys.executable,'-c',extract]},
                     {'kind':'agent','executor':receiver.ident,'cwd':'scratch','command':[sys.executable,'../draw.py'],'asset_manifest':['helper.py']}]}})
        self.drain()
        packet, = self.engine.executors.poll(receiver.metadata())['jobs']
        self.assertEqual({f['path'] for f in packet['payload']['resources']['files']}, {'helper.py','draw.py'})
        context = packet['payload']['prompt_context']
        self.assertEqual(context['previous'], {'points':[[0,37]]})
        self.assertEqual(set(context), {'previous','run_id','timeline_id','loop_key','platform_url','platform_client','reason'})
        self.assertNotIn(private, json.dumps(packet))
        self.assertLess(len(json.dumps(context)), 1024)

        work.WorkRuntime(self.engine)
        deadline = time.monotonic() + 10
        with patch('loop_anything.runtime.business_state.record_page',side_effect=AssertionError('reading history again on receipt')):
            while time.monotonic() < deadline:
                self.engine.executors.sync()
                receiver.tick()
                self.drain()
                if self.views()['views']:
                    break
                time.sleep(.02)
        self.assertEqual(self.views()['views'][0]['view']['series'], [{'label':'latency','points':[[0,37]]}])
        self.assertTrue(self.engine.executors.get(packet['id'])['applied'])

    def test_restart_between_extraction_and_dispatch_keeps_original_event_and_delivery(self):
        from unittest.mock import patch
        from loop_anything.runtime.business_state import apply
        worker={'id':'plotter','owner':'test','name':'Plotter'}
        self.engine.executors.register(worker)
        self.update(observations={'plot':{'steps':[
            {'kind':'command','command':[sys.executable,'-c','print(\'{"x":2}\')']},
            {'kind':'command','executor':worker['id'],'command':['draw']}],
            'on':{'kind':'state'},'each':True,'notify_on':['event'],'route':'workspace',
            'condition':{'op':'eq','args':[{'path':'reason'},'event']}}})
        self.drain()
        with self.store.edit(self.run_id) as run:
            apply(run,run['executions'][0],[{'type':'score','id':'one','value':2}])
        job, = observations.collect(self.store)
        class ServiceExit(BaseException): pass
        original=self.engine.implementation
        def interrupt(step):
            if step.get('executor'):raise ServiceExit()
            return original(step)
        with patch.object(self.engine,'implementation',side_effect=interrupt), self.assertRaises(ServiceExit):
            observations.execute(self.engine,job)
        work.WorkRuntime(self.engine)
        with patch('loop_anything.runtime.host_runtime.run_command',side_effect=AssertionError('extraction repeated')):
            self.drain()
        packet,=self.engine.executors.poll(worker)['jobs']
        self.assertEqual(packet['payload']['prompt_context']['previous'],{'x':2})
        self.engine.executors.report(packet['id'],packet['token'],{'sequence':1,'state':'completed',
                                     'result':{'returncode':0,'stdout':'{"summary":"ready"}','stderr':''}})
        self.drain()
        self.drain()
        for _ in range(2):
            self.engine.tick(self.run_id)
            for future in list(self.engine.futures):
                future.result(timeout=5)
        notices=[n for n in self.store.get(self.run_id)['notifications'] if n['id'].startswith('observation:')]
        self.assertEqual([(n['id'],n['status']) for n in notices],[('observation:'+str(job['id']),'delivered')])

    def test_metadata_only_condition_never_queries_history_even_on_receipt(self):
        from unittest.mock import patch
        worker={'id':'worker','name':'Worker','owner':'test'}
        self.engine.executors.register(worker)
        self.update(observations={'clock':{'on':None,
            'condition':{'op':'eq','args':[{'path':'reason'},'initial']},
            'steps':[{'kind':'command','executor':worker['id'],'command':['clock-view']}]}})
        with patch('loop_anything.runtime.business_state.record_query', side_effect=AssertionError('history query')):
            self.drain()
            packet,=self.engine.executors.poll(worker)['jobs']
            self.engine.executors.report(packet['id'],packet['token'],{'sequence':1,'state':'completed',
                'result':{'returncode':0,'stdout':'{"summary":"done"}','stderr':''}})
            self.drain()
        self.assertEqual(self.views()['views'][0]['view'],{'summary':'done'})
