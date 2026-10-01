"""Counterexamples from the 0.3 capability audit, using isolated fixtures."""
import copy
import unittest
from types import SimpleNamespace
import test_authoring_capabilities as fixture
from loop_anything.packaging.packages import make_archive, read_archive, install
from loop_anything.runtime.task_refs import resolve_task_references
from loop_anything.runtime.timeline_runtime import TimelineRuntime
from loop_anything.runtime.timeline_plan import task_dependencies


class AuditRegressions(unittest.TestCase):
    def setUp(self):
        self.base=fixture.AuthoringCapabilitiesTests();self.base.setUp()
    def tearDown(self):self.base.tearDown()

    def test_ref_collect_uses_each_producers_version_not_latest_record(self):
        specs=[{'id':ident,'node':'work','ref':ref,'inputs':{},'outputs':{'result':{'id':record,'expected_revision':rev}}}
               for ident,ref,record,rev in [('old','old','shared',0),('new','new','shared',1),('other','other','other-record',1)]]
        consumer=resolve_task_references([{'id':'review','node':'review','inputs':{'results':{'task_refs':['old','other'],'port':'result'}},'outputs':{'done':{'id':'done'}}}],specs)[0]
        records={'shared':[{'id':'shared','revision':1,'value':10,'producer':'e-old','tasks':'old'},
                           {'id':'shared','revision':2,'value':99,'producer':'e-new','tasks':'new'}],
                 'other-record':[{'id':'other-record','revision':2,'value':20,'producer':'e-other','tasks':'other'}]}
        bp=self.base.tools.call('read_loop',self.base.target())['loop']['loop_definition']
        run={'loop_definition':bp,'implementations':{'review':{'kind':'agent'}},'settings':{'bindings':{}},
             'records':records,'tasks':{s['id']:{'id':s['id'],'spec':s,'status':'completed'} for s in specs},'executions':[]}
        task={'id':'review','spec':consumer,'status':'planned'};run['tasks']['review']=task
        values,sources,missing=TimelineRuntime(SimpleNamespace(store=self.base.store)).resolve_inputs(run,task)
        self.assertFalse(missing);self.assertEqual(values['results'],[10,20])
        self.assertEqual([r['revision'] for r in sources['results']],[1,2])
        self.assertEqual(set(task_dependencies(run)['review']),{'old','other'})

    def test_routed_parameter_data_is_not_reinterpreted_as_a_template(self):
        route=copy.deepcopy(self.base.routes[0]);route['steps']={'work':{'parameters':{'source':{'$':'outputs.jobs.0.params.source'}}}}
        self.base.edit('put_node',node_id='initialize',routes=[route,self.base.routes[1]])
        case=self.base.scenario();case['steps'][0]['report']['envelope']['outputs']['jobs'][0]['params']['source']='literal {user.name}'
        result=self.base.tools.call('test_loop',self.base.target(scenarios=[case]))
        self.assertTrue(result['passed'],[(r['error'],r['failed_step']) for r in result['scenarios']])
        self.assertEqual(result['scenarios'][0]['state']['by_ref']['work:A']['parameters']['source'],'literal {user.name}')

    def test_explicit_package_requirements_survive_install_copy_export(self):
        document=self.base.tools.call('read_loop',self.base.target())['loop']
        package={k:document[k] for k in ('loop_definition','implementations')};package['requires']=['notifications']
        key=install(self.base.store,make_archive(package))['key']
        copied=self.base.tools.call('copy_loop',{'key':key,'new_version':True})
        loop=self.base.tools.call('read_loop',{'draft_id':copied['draft_id']})['loop']
        restored={k:loop[k] for k in ('loop_definition','implementations')}
        self.assertIn('notifications',read_archive(make_archive(restored))[0]['requires'])

    def test_unknown_package_format_is_not_silently_downgraded_by_export(self):
        from loop_anything.runtime.model import Invalid
        document=self.base.tools.call('read_loop',self.base.target())['loop']
        package={k:document[k] for k in ('loop_definition','implementations')};package['format']='loop-anything-package/999'
        with self.assertRaisesRegex(Invalid,'Unsupported Loop package format'):make_archive(package)

    def test_record_revision_array_is_checked_and_gated_for_older_services(self):
        from loop_anything.runtime.model import Invalid, record_refs
        from loop_anything.capabilities import required_capabilities
        self.assertEqual(record_refs({'records':['a','b'],'revisions':[1,2]}),[('a',1),('b',2)])
        for source in ({'records':['a'],'revisions':[1,2]},{'record':'a','revisions':[1]},
                       {'records':['a'],'revisions':[True]},{'records':['a'],'revisions':[1],'revision':1}):
            with self.assertRaises(Invalid):record_refs(source)
        self.assertIn('record_versions',required_capabilities({'plans':{'p':{'steps':{'s':{'inputs':{'port':{'records':['a'],'revisions':[1]}}}}}}}))
