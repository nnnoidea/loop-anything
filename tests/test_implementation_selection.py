"""Selection drives actual dispatch; attempts retain their own implementation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from loop_anything.runtime.store import Store
from loop_anything.runtime.engine import Engine
from loop_anything.interfaces.agent_tasks import RunTools
from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.packaging.packages import make_archive, install, load_installed, smoke
from test_run_agent import definition, task_spec


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'runs.db')
        self.engine = Engine(self.store)
        self.bp, self.impl = definition()

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def start(self, bindings=None):
        self.key = self.store.publish(self.bp, self.impl)['key']
        r = self.store.create(self.key, 'Selection', acquire=True, bindings=bindings)
        self.id = r['id']
        self.tools = RunTools(self.store, self.id, r['agent_sessions'][0]['token'])
        self.complete('init', settings={'objective': 'Select implementations'})

    def complete(self, id, **extra):
        info = self.tools.call('read_task', {'task_id': id})
        return self.tools.call('complete_task', {'task_id': id, 'task_version': info['task_version'], 'envelope': {'outputs': {'result': 'done'}, **extra}})

    def settings(self, **change):
        r = self.store.get(self.id)
        self.tools.call('change_settings', {'revision': r['settings']['revision'], 'change': change})

    def add(self, spec):
        from loop_anything.runtime.timeline_plan import add_task
        with self.store.edit(self.id) as r:
            add_task(r, spec, {'test': True})

    def until(self, predicate):
        for _ in range(150):
            self.engine.tick(self.id)
            r = self.store.get(self.id)
            if predicate(r):return r
            time.sleep(.02)
        self.fail(str(self.store.get(self.id)['diagnostics']))

    def test_task_revisions_keep_retry_identity_history_and_downstream(self):
        self.start()
        self.add(task_spec('work','script',parameters={'fail':True}))
        self.add(task_spec('downstream','finish',inputs={'value':{'record':'work.result'}},after=['work']))
        downstream=copy.deepcopy(self.store.get(self.id)['tasks']['downstream'])
        run=self.until(lambda r:r['tasks']['work']['status']=='fault')
        self.assertEqual(run['tasks']['work']['revision'],1)
        self.tools.call('change_task',{'task_id':'work','operation':'retry','reason':'Transient failure'})
        run=self.until(lambda r:r['tasks']['work']['status']=='fault')
        self.assertEqual(run['tasks']['work']['revision'],1)
        result=self.tools.call('change_task',{'task_id':'work','operation':'retry','reason':'Correct the parameters','parameters':{'fail':False}})
        self.assertEqual(result['task_revision'],2)
        run=self.until(lambda r:r['tasks']['work']['status']=='completed')
        attempts=[e for e in run['executions'] if e['task_id']=='work']
        self.assertEqual([(e['attempt'],e['task_revision']) for e in attempts],[(1,1),(2,1),(3,2)])
        self.assertEqual([e['task_spec']['parameters']['fail'] for e in attempts],[True,True,False])
        self.assertEqual(run['tasks']['downstream']['spec'],downstream['spec'])
        self.assertEqual(run['tasks']['downstream']['revision'],1)
        self.assertEqual(set(run['tasks']),{'init','work','downstream'})
        changes=[h['detail'] for h in run['history'] if h['kind']=='agent_action_change' and h['detail']['tasks']=='work']
        self.assertEqual([(d['before_revision'],d['after_revision']) for d in changes],[(1,1),(1,2)])
        self.assertEqual(changes[-1]['actor']['kind'],'interactive')
        self.assertNotIn('token',changes[-1]['actor'])
        # Returning to identical parameters must still invalidate an older read token.
        self.add(task_spec('decision','reason',parameters={}))
        info=self.tools.call('read_task',{'task_id':'decision'})
        self.tools.call('change_task',{'task_id':'decision','operation':'update','reason':'No change','parameters':{}})
        self.assertEqual(self.tools.call('read_task',{'task_id':'decision'})['task_revision'],1)
        for params in ({'value':1},{}):self.tools.call('change_task',{'task_id':'decision','operation':'update','reason':'Reconsider','parameters':params})
        with self.assertRaises(Conflict):self.tools.call('complete_task',{'task_id':'decision','task_version':info['task_version'],'envelope':{'outputs':{'result':'stale'}}})
        self.assertEqual(self.tools.call('read_task',{'task_id':'decision'})['task_revision'],3)

    def test_legacy_attempt_revisions_are_not_fabricated(self):
        self.start();self.add(task_spec('old','script',parameters={'fail':True}))
        run=self.until(lambda r:r['tasks']['old']['status']=='fault')
        old_id=run['tasks']['old']['execution_id']
        with self.store.edit(self.id) as run:
            run['tasks']['old'].pop('revision')
            attempt=next(e for e in run['executions'] if e['id']==old_id)
            attempt.pop('task_revision');attempt.pop('task_spec')
        self.assertIsNone(self.tools.call('read_task',{'task_id':'old'})['task_revision'])
        self.tools.call('change_task',{'task_id':'old','operation':'retry','reason':'Retry same legacy task'})
        run=self.until(lambda r:r['tasks']['old']['status']=='fault')
        self.assertEqual(run['tasks']['old']['revision'],1)
        self.assertNotIn('task_revision',next(e for e in run['executions'] if e['id']==old_id))
        self.assertEqual(run['executions'][-1]['task_revision'],1)

    def test_candidate_parameters_validate_writes_rebinding_and_retry(self):
        common={'type':'object','properties':{'count':{'type':'integer','minimum':1}},'required':['count']}
        local={'type':'object','properties':{'file':{'type':'string','nonempty':True}},'required':['file']}
        remote={'type':'object','properties':{'queue':{'type':'string','enum':['gpu']}},'required':['queue']}
        command=copy.deepcopy(self.impl['script'])
        self.bp['nodes']['script']['parameter_schema']=common
        self.impl['script']={'default':'local','options':{'local':dict(command,parameter_schema=local),'remote':dict(command,parameter_schema=remote)}}
        self.bp['plans']={'pair':{'steps':{k:{'node':'script','inputs':{}} for k in ('a','b')}}}
        self.start()
        before=self.store.get(self.id)
        with self.assertRaises(Invalid):self.tools.call('add_task',{'node_id':'script','key':'bad','inputs':{},'parameters':{'count':1}})
        with self.assertRaises(Invalid):self.tools.call('build_plan',{'name':'pair','key':'bad','values':{},'steps':{'a':{'parameters':{'count':1,'file':'data'}},'b':{'parameters':{'count':1}}}})
        self.assertEqual(before,self.store.get(self.id))
        task=self.tools.call('add_task',{'node_id':'script','key':'work','inputs':{},'parameters':{'count':1,'file':'data'}})['tasks'][0]
        self.settings(bindings={'script':'remote'})
        self.engine.tick(self.id)
        run=self.store.get(self.id);self.assertEqual(run['tasks'][task['id']]['status'],'blocked')
        self.assertFalse(any(e['task_id']==task['id'] for e in run['executions']))
        info=self.tools.call('read_task',{'task_id':task['id']})
        self.assertEqual(info['implementation']['parameter_schema'],remote)
        self.assertEqual(info['parameter_schema'],common)
        self.assertTrue(any(m['reason']=='invalid_parameters' for m in info['missing']))
        for params in ({'count':0,'queue':'gpu'},{'count':1,'queue':'cpu'}):
            with self.assertRaises(Invalid):self.tools.call('change_task',{'task_id':task['id'],'operation':'update','reason':'Choose remote','parameters':params})
        self.tools.call('change_task',{'task_id':task['id'],'operation':'update','reason':'Choose remote','parameters':{'count':1,'queue':'gpu','fail':True}})
        run=self.until(lambda r:r['tasks'][task['id']]['status']=='fault')
        for future in list(self.engine.futures):future.result(timeout=5)
        run=self.store.get(self.id)
        attempt=copy.deepcopy(next(e for e in run['executions'] if e['task_id']==task['id']))
        with self.assertRaises(Invalid):self.tools.call('change_task',{'task_id':task['id'],'operation':'retry','reason':'Use local','implementation':'local','parameters':{'count':1}})
        self.assertEqual(run,self.store.get(self.id))
        self.tools.call('change_task',{'task_id':task['id'],'operation':'retry','reason':'Use local','implementation':'local','parameters':{'count':1,'file':'data'}})
        done=self.until(lambda r:r['tasks'][task['id']]['status']=='completed')
        latest=next(e for e in done['executions'] if e['id']==done['tasks'][task['id']]['execution_id'])
        self.assertEqual(latest['implementation_id'],'local');self.assertEqual(latest['implementation']['parameter_schema'],local)
        self.assertEqual(next(e for e in done['executions'] if e['id']==attempt['id'])['implementation'],attempt['implementation'])

    def test_entry_uses_selected_contract_before_creating_seed_and_fallback_needs_no_parameters(self):
        self.impl['init']={'default':'needs_queue','options':{'needs_queue':{'kind':'agent','parameter_schema':{'type':'object','required':['queue']}},'interactive':{'kind':'agent'}}}
        key=self.store.publish(self.bp,self.impl)['key']
        with self.assertRaises(Invalid):self.store.create(key,'Missing parameters')
        run=self.store.create(key,'Interactive entry',bindings={'init':'interactive'})
        self.assertEqual(run['settings']['bindings']['init'],'interactive')
        self.bp['fallback_node']='reason'
        self.impl['reason']={'kind':'agent','parameter_schema':{'type':'object','required':['queue']}}
        with self.assertRaises(Invalid):self.store.publish(self.bp,self.impl)

    def test_run_override_and_task_override_execute_without_new_loop(self):
        def command(value):
            return {'kind': 'command', 'command': [sys.executable, '-c', 'import json; print(json.dumps({"outputs":{"result":'+repr(value)+'}}))']}
        self.impl = {'init': {'kind': 'agent'}, 'script': {'default': 'local', 'options': {'local': command('local'), 'remote': command('remote')}}}
        self.bp['plans']={'pair':{'steps':{'a':{'node':'script','inputs':{}},'b':{'node':'script','inputs':{}}}}}
        self.start({'script': 'remote'})
        specs=self.tools.call('build_plan',{'name':'pair','key':'choose','values':{},'steps':{'b':{'implementation':'local'}}})['tasks']
        ids=[spec['id'] for spec in specs]
        r = self.until(lambda r: all(r['tasks'][k]['status']=='completed' for k in ids))
        self.assertEqual(['remote','local'],[r['records'][k+'.result'][0]['value'] for k in ids])
        self.assertEqual(['remote','local'],[e['implementation_id'] for e in r['executions'] if e['node']=='script'])
        self.assertEqual(1,len(self.store.catalog()))
        self.assertEqual(self.key,r['loop_key'])
        self.assertEqual([],r['diagnostics'])  # Unused unimplemented nodes do not block.

    def test_inflight_event_and_finished_attempt_keep_snapshot_after_default_switch(self):
        self.impl['wait']={'default':'first','options':{'first':{'kind':'event','event':'first'},'second':{'kind':'event','event':'second'}}}
        self.start()
        self.add(task_spec('a','wait'))
        first = self.until(lambda r:r['tasks']['a']['status']=='waiting')['executions'][-1]
        self.settings(bindings={'wait':'second'})
        self.add(task_spec('b','wait'))
        self.until(lambda r:r['tasks']['b']['status']=='waiting')
        self.engine.event(self.id,'evt-first','first',{'result':'old'})
        r = self.until(lambda r:r['tasks']['a']['status']=='completed')
        self.assertEqual('waiting',r['tasks']['b']['status'])
        self.assertEqual(first['implementation'],next(e for e in r['executions'] if e['id']==first['id'])['implementation'])
        self.engine.event(self.id,'evt-second','second',{'result':'new'})
        self.until(lambda r:r['tasks']['b']['status']=='completed')
        with self.assertRaises(Conflict):self.tools.call('change_task',{'task_id':'a','operation':'update','implementation':'second','reason':'Already executed'})

    def test_missing_selection_is_reported_and_selecting_invalidates_old_read(self):
        self.impl['reason']={'options':{'a':{'kind':'agent'},'b':{'kind':'agent'}}}
        self.start()
        self.add(task_spec('choose','reason'))
        self.engine.tick(self.id)
        r=self.store.get(self.id)
        self.assertTrue(any(d['kind']=='missing_implementation' for d in r['diagnostics']))
        self.settings(bindings={'reason':'a'})
        old=self.tools.call('read_task',{'task_id':'choose'})
        self.settings(bindings={'reason':'b'})
        with self.assertRaises(Conflict):self.tools.call('complete_task',{'task_id':'choose','task_version':old['task_version'],'envelope':{'outputs':{'result':'stale'}}})
        self.complete('choose')
        self.assertEqual('b',self.store.get(self.id)['executions'][-1]['implementation_id'])
        with self.assertRaises(Invalid):self.settings(bindings={'reason':'absent'})
        with self.assertRaises(Invalid):self.store.create(self.key,'Bad',bindings=[])

    def test_author_candidates_roundtrip_package_and_task_retry_selects_alternative(self):
        tools=PlatformTools(self.store)
        draft=tools.call('create_loop',{'id':'variants','name':'Variants'})
        draft=tools.call('set_loop',{'draft_id':draft['draft_id'],'revision':draft['revision'],'handbook':'Initialize from the agreed request.'})
        draft=tools.call('set_implementation',dict(draft_id=draft['draft_id'],revision=draft['revision'],node_id='initialize',unbind=True))
        for ident,default in [('one',True),('two',False)]:
            draft=tools.call('set_implementation',dict(draft_id=draft['draft_id'],revision=draft['revision'],node_id='initialize',implementation_id=ident,kind='agent',default=default))
        document=tools.call('read_loop',{'draft_id':draft['draft_id']})['loop']
        entry=document['implementations']['initialize']
        self.assertEqual({'one','two'},set(entry['options']));self.assertEqual('one',entry['default'])
        key=tools.call('publish_loop',{'draft_id':draft['draft_id'],'revision':draft['revision']})['key']
        packed,root=load_installed(self.store.filename,key)
        self.assertEqual(entry,packed['implementations']['initialize']);self.assertTrue(smoke(packed,root)['startable'])
        self.impl['script']={'default':'broken','options':{'broken':{'kind':'command','command':[sys.executable,'-c','raise SystemExit(2)']},'fixed':{'kind':'command','command':[sys.executable,'-c','print(\'{"outputs":{"result":"recovered"}}\')']}}}
        self.start();self.add(task_spec('retry','script'))
        r=self.until(lambda r:r['tasks']['retry']['status']=='fault')
        old=copy.deepcopy(r['executions'][-1])
        self.tools.call('change_task',{'task_id':'retry','operation':'retry','implementation':'fixed','reason':'No side effect; use working candidate'})
        r=self.until(lambda r:r['tasks']['retry']['status']=='completed')
        self.assertEqual('recovered',r['records']['retry.result'][0]['value'])
        self.assertEqual(old['implementation'],next(e for e in r['executions'] if e['id']==old['id'])['implementation'])
        self.assertEqual('fixed',r['executions'][-1]['implementation_id'])
