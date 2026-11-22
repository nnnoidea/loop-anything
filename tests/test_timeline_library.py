import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loop_anything.interfaces.platform_tools import PlatformTools
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.store import Store
from test_packages import document


class TimelineLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,LOOP_ANYTHING_IDENTITY_DIR=self.tmp.name+'/identity');env.start();self.addCleanup(env.stop)
        self.store=Store(Path(self.tmp.name)/'workspace.db');self.tools=PlatformTools(self.store)

    def loop(self,ident,version='1',name='Research'):
        doc=document();bp=doc['loop_definition'];bp.update(id=ident,version=version,name=name)
        return self.store.publish(bp,{n:{'options':{'default':{'kind':'agent'}},'default':'default'} for n in bp['nodes']})['key']

    def test_loop_groups_span_versions_keep_distinct_ids_and_page_without_loading_runs(self):
        first=self.loop('research');second=self.loop('research','2');other=self.loop('other',name='Research')
        ids=[self.store.create(first if i%2 else second,'Trial '+str(i))['timeline_id'] for i in range(5)]
        self.store.create(other,'Separate Loop')
        temp=self.tools.call('create_timeline',{'title':'Temporary'})['timeline']['id']
        with patch.object(self.store,'_load',side_effect=AssertionError('Must not load Run archives')):
            root=self.tools.call('list_timelines',{'limit':1})
            self.assertEqual(root['total'],7);self.assertEqual(len(root['timelines']),1)
            self.assertEqual({g['loop_id']:g['count'] for g in root['groups']},{'research':5,'other':1,None:1})
            page=self.tools.call('list_timelines',{'loop_id':'research','limit':2})
            seen=[]
            while True:
                seen.extend(t['id'] for t in page['timelines'])
                self.assertTrue(all(t['loop_id']=='research' for t in page['timelines']))
                if page['next_offset'] is None:break
                page=self.tools.call('list_timelines',{'loop_id':'research','limit':2,'offset':page['next_offset']})
            self.assertEqual(len(seen),5);self.assertEqual(set(seen),set(ids))
            loose=self.tools.call('list_timelines',{'unbound':True})
            self.assertEqual([t['id'] for t in loose['timelines']],[temp])
            self.assertIsNone(loose['timelines'][0]['loop_id'])

    def test_existing_timeline_moves_from_temporary_group_after_run_association(self):
        ident=self.tools.call('create_timeline',{'title':'Work','objective':'Keep goal'})['timeline']['id']
        before=self.tools.call('read_work_timeline',{'timeline_id':ident})['timeline']
        key=self.loop('research')
        run=self.store.create(key,'Associated',timeline_id=ident)
        result=self.tools.call('list_timelines',{})
        self.assertEqual(result['groups'],[{'loop_id':'research','name':'Research','count':1}])
        self.assertEqual(result['timelines'][0]['id'],ident)
        self.assertEqual(result['timelines'][0]['objective'],before['objective'])
        self.assertEqual(self.tools.call('list_timelines',{'unbound':True})['total'],0)
        # Multiple retained execution records must not multiply the Timeline count.
        with self.store.connection() as db:
            import json
            row=json.loads(db.execute('SELECT document FROM runs WHERE id=?',(run['id'],)).fetchone()[0])
            row.update(id='run-retained-copy',created_at=row['created_at']+1)
            db.execute('INSERT INTO runs(id,document) VALUES (?,?)',(row['id'],json.dumps(row)));db.commit()
        self.assertEqual(self.tools.call('list_timelines',{})['groups'][0]['count'],1)

    def test_latest_business_progress_and_newest_first_history(self):
        t=self.tools.call('create_timeline',{'title':'Inventory'})['timeline']['id']
        self.tools.call('create_timeline',{'title':'Untouched'})
        for i,kind in enumerate(['progress','decision','progress']):
            self.tools.call('append_timeline',{'timeline_id':t,'key':str(i),'kind':kind,'text':'Update '+str(i)})
        latest=self.tools.call('list_timelines',{'limit':1})['timelines'][0]
        self.assertEqual((latest['id'],latest['progress']['text']),(t,'Update 2'))
        start=self.tools.call('read_work_timeline',{'timeline_id':t,'newest_first':True,'limit':2})
        self.assertEqual(start['progress']['text'],latest['progress']['text'])
        self.assertEqual([e['text'] for e in start['entries']],['Update 2','Update 1'])
        self.tools.call('append_timeline',{'timeline_id':t,'key':'new','kind':'note','text':'Later'})
        older=self.tools.call('read_work_timeline',{'timeline_id':t,'newest_first':True,'after':start['cursor']})
        self.assertEqual([e['text'] for e in older['entries']],['Update 0'])

    def test_invalid_filters_and_pagination_are_rejected(self):
        for args in ({'loop_id':'x','unbound':True},{'limit':0},{'limit':101},{'offset':-1},{'unbound':'yes'}):
            with self.subTest(args=args),self.assertRaises(Invalid):self.tools.call('list_timelines',args)
