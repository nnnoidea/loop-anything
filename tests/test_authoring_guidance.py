"""Use mechanism discovery through author tools, then execute its composition example."""
import io
import zipfile
import unittest
from pathlib import Path
import test_authoring_capabilities as fixture
from loop_anything.authoring_guidance import MECHANISMS, render_guide
from loop_anything.capabilities import CAPABILITIES
from loop_anything.packaging.skill_bundle import bundle
from loop_anything.runtime.agent_prompt import author_context


class AuthoringGuidanceTests(unittest.TestCase):
    def setUp(self):self.base=fixture.AuthoringCapabilitiesTests();self.base.setUp()
    def tearDown(self):self.base.tearDown()

    def test_build_entry_and_exported_skill_share_mechanism_contract(self):
        tools=self.base.tools
        created=tools.call('create_loop',{'name':'Use platform mechanisms'})
        self.assertIn('authoring_context',created)
        context=created['authoring_context']
        read=tools.call('read_loop',{'draft_id':created['draft_id']})
        self.assertEqual(read['authoring_context'],context)
        guide=tools.call(context['details']['tool'],context['details']['arguments'])
        self.assertEqual(set(guide['guide']),set(MECHANISMS));self.assertEqual(set(CAPABILITIES),set(MECHANISMS))
        for value in guide['guide'].values():
            self.assertTrue(value['platform_handles']);self.assertTrue(value['author_provides']);self.assertTrue(value['configuration']);self.assertTrue(value['limits'])
        self.assertEqual(guide['guide']['timeline_storage']['activation'],'automatic')
        selected=tools.call('read_capabilities',{'capability':'task_scheduler'})
        self.assertEqual(set(selected['guide']),{'task_scheduler'})
        for pattern in selected['patterns'].values():self.assertIn('task_scheduler',pattern['capabilities'])
        bp=read['loop']['loop_definition']
        self.assertEqual(author_context(self.base.store,None,bp)['platform_responsibilities'],context)
        self.assertEqual(Path('skills/loop-anything-platform/references/platform-capabilities.md').read_text(),render_guide())
        with zipfile.ZipFile(io.BytesIO(bundle('http://127.0.0.1:8769'))) as archive:
            self.assertEqual(archive.read('platform/loop-anything-platform/references/platform-capabilities.md').decode(),render_guide())

    def test_agent_can_compose_from_discovered_recipe_without_task_writer(self):
        b=self.base
        pattern=b.tools.call('read_capabilities',{'capability':'event_routes'})['patterns']['result_to_batch_and_review']
        b.edit('put_node',node_id='initialize',outputs=[{'name':'jobs','type':'array'}],routes=pattern['source_routes'])
        for name,step in pattern['plan']['steps'].items():
            args=dict(step);args['node_id']=args.pop('node')
            b.edit('put_step',plan='work_and_review',step=name,plan_parameters=pattern['plan']['parameters'],**args)
        jobs=[{'id':name,'params':{'value':i,'mode':'a','source':'input'}} for i,name in enumerate(['A','B'])]
        case={'name':'discovered recipe','steps':[
            {'node':'initialize','report':{'event':'completed','envelope':{'settings':{'objective':'Review this batch','completion_rule':fixture.equal('active_tasks',0)},'outputs':{'jobs':jobs}}},'duplicate':True},
            {'ref':'work:A','report':{'event':'completed','envelope':{'outputs':{'result':10}}}},
            {'ref':'work:B','report':{'event':'completed','envelope':{'outputs':{'result':20}}}},
            {'ref':'review:batch','report':{'event':'completed','envelope':{'outputs':{'done':True}}}}],
            'assertions':[{'message':'Automatically arranged batch','test':fixture.equal('task_count',4)},
                          {'message':'Collected the supplied facts','test':fixture.equal(['by_ref','review:batch','resolved_inputs','results'],[10,20])},
                          {'message':'Run ended using platform rule','test':fixture.equal('status','completed')}]}
        b.edit('set_loop',scenarios=[case]);self.assertTrue(b.tools.call('test_loop',b.target())['passed'])
        key=b.tools.call('publish_loop',b.target(revision=b.draft['revision']))['key']
        copied=b.tools.call('copy_loop',{'key':key,'new_version':True})
        self.assertEqual(copied['authoring_context'],b.tools.call('read_capabilities',{})['authoring_context'])
