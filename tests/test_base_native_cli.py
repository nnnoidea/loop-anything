"""Base v3 CLI boundary: native input, real matrix shape and exact filtering."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from loop_anything.runtime.team_transport import core


class NativeBaseTests(unittest.TestCase):
    def test_reuse_default_grid_and_hide_protocol_columns(self):
        media=core.Base({'app_token':'test','table_id':'tbl-test'})
        views=[{'id':'view-default','name':'Grid'}];visible={}
        def native(args,**kwargs):
            operation=args[1]
            def flag(name):return args[args.index('--'+name)+1]
            if operation=='+view-list':return {'data':{'views':list(views),'total':len(views)}}
            if operation=='+view-rename':views[0]['name']=flag('name')
            elif operation=='+view-create':
                views.append({'id':'view-'+str(len(views)),'name':json.loads(flag('json'))['name']})
            elif operation=='+view-set-visible-fields':
                visible[flag('view-id')]=json.loads(flag('json'))['visible_fields']
            elif operation!='+view-set-filter':raise AssertionError(operation)
            return {'data':{}}
        with patch.object(media,'shortcut',side_effect=native):
            media.setup_views()
            media.setup_views()
        self.assertEqual(len(views),3)
        self.assertEqual(media.config['views']['请求与结果'],'view-default')
        self.assertTrue(all('key' not in fields and 'value' not in fields for fields in visible.values()))

    def test_native_record_roundtrip_and_offset_filter(self):
        media=core.Base({'app_token':'test','table_id':'tbl-test','schema_version':2})
        calls=[]
        payload={'value':'完整回复'*25000,'count':1}
        def native(args,**kwargs):
            calls.append(args)
            self.assertEqual(args[1],'base')
            operation=args[2]
            if operation=='+record-upsert':
                name=args[args.index('--json')+1]
                self.assertEqual(name,'@./body.json')
                self.assertEqual(json.loads((Path(kwargs['cwd'])/name[1:]).read_text()),payload)
                self.assertNotIn(payload['value'],args)
                answer={'record':{'record_id_list':['rec-one']},'created':True}
            elif operation=='+record-list':
                self.assertEqual(args[args.index('--format')+1],'json')
                self.assertEqual(json.loads(args[args.index('--filter-json')+1]),
                    {'logic':'and','conditions':[['key','==','results/request-"quoted".json']]})
                offset=int(args[args.index('--offset')+1])
                # A short non-final page must still advance by actual row count.
                answer={'fields':['value','count'],'record_id_list':['rec-'+str(offset)],
                    'data':[[payload['value'],1]],'has_more':offset==0}
            elif operation=='+record-get':
                answer={'fields':['value','count'],'record_id_list':['rec-one'],
                    'data':[[payload['value'],1]],'has_more':False}
            else:raise AssertionError(operation)
            return subprocess.CompletedProcess(args,0,json.dumps({'ok':True,'data':answer}),'')
        with patch.object(core.subprocess,'run',side_effect=native):
            self.assertEqual(media.write_record(payload)['record_id'],'rec-one')
            self.assertEqual(len(media.rows('key','results/request-"quoted".json')),2)
            self.assertEqual(media.get_record('rec-one')['fields'],payload)
        self.assertFalse(any('bitable/v1' in arg for args in calls for arg in args))

    def test_invalid_matrix_and_empty_continuation_fail_without_truncation(self):
        media=core.Base({'app_token':'test','table_id':'tbl-test'})
        with self.assertRaisesRegex(ValueError,'matrix'):
            media.matrix_records({'fields':['value'],'record_id_list':['rec-one'],'data':[]})
        with patch.object(media,'call',return_value={'fields':[],'data':[],'has_more':True}):
            with self.assertRaisesRegex(ValueError,'pagination'):media.rows('key','x')

    def test_no_legacy_permission_retry(self):
        media=core.Base({'app_token':'test','table_id':'tbl-test'})
        error={'ok':False,'error':{'message':'Missing base:record:read'}}
        with patch.object(core.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'',json.dumps(error))) as run:
            with self.assertRaisesRegex(ValueError,'base:record:read'):media.rows('key','x')
            self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.args[0][1:3],['base','+record-list'])


if __name__=='__main__':unittest.main()
