import json
import unittest

import test_communication as fixtures
from loop_anything.interfaces.communication_tools import call
from loop_anything.runtime.communication_views import continuation_context
from loop_anything.runtime.model import Invalid


class CommunicationViewTests(unittest.TestCase):
    setUp=fixtures.CommunicationTests.setUp
    tearDown=fixtures.CommunicationTests.tearDown
    agent=fixtures.CommunicationTests.agent

    def request(self):
        self.agent(self.a)
        return self.a.request({'location':'local','agent_id':'papers','message':'Analyze the paper',
                               'context':{'task':'Compare methods','dataset':'shared/papers'}})['request']['id']

    def noisy(self,ident):
        with self.a.transaction() as db:
            row=self.a.get(ident,db)
            row.update(state='completed',result={'answer':42,'token':'business-value'},
                       history=[{'text':'history-noise'*10000}],last_sent='transport-noise'*10000,
                       logs=['log-noise'*10000],notifications=[{'id':'notice','state':'completed','status':'delivered',
                           'attempt':1,'payload':{'message':'notice-noise'*10000}}])
            self.a.save(db,row)

    def test_default_view_retains_results_without_context_or_diagnostic_archives(self):
        ident=self.request();self.noisy(ident)
        result=call(self.a.store,'read_assistance',{'request_id':ident})['request']
        for field in ('context','history','last_sent','logs','terminal'):self.assertNotIn(field,result)
        self.assertEqual(result['result'],{'answer':42,'token':'business-value'})
        self.assertLess(len(json.dumps(result)),4000)
        self.assertEqual(result['notifications'][0]['status'],'delivered')
        detail=call(self.a.store,'read_assistance',{'request_id':ident,'include_details':True})['request']
        self.assertIn('history-noise',json.dumps(detail['history']))
        self.assertNotIn('last_sent',detail);self.assertNotIn('logs',detail)
        self.assertGreater(len(json.dumps(self.a.get(ident))),200000)

    def test_local_and_remote_log_pages_are_bounded_and_lossless(self):
        for local in (True,False):
            with self.subTest(local=local):
                ident=self.request();expected=['首段😀'*5000+'\0末尾仍需保留', '\0开头也需保留', '']+['part-%s\n'%i for i in range(80)]
                with self.a.transaction() as db:
                    if local:
                        self.engines[0].terminals.create('',ident,'terminal-'+ident,_db=db)
                        table,key,owner='execution_output','session_id','terminal-'+ident
                    else:
                        row=self.a.get(ident,db);row['executor']=self.b.settings()['instance_id'];self.a.save(db,row)
                        table,key,owner='communication_logs','request_id',ident
                    db.executemany(f'INSERT INTO {table} ({key},sequence,text) VALUES (?,?,?)',
                                   [(owner,i,text) for i,text in enumerate(expected,1)])
                after=offset=0;received=[]
                for _ in range(100):
                    page=call(self.a.store,'read_assistance',{'request_id':ident,'include_logs':True,'after':after,'offset':offset,'max_chars':997})['request']
                    text=''.join(x['text'] for x in page['logs']);self.assertLessEqual(len(text),997)
                    received.append(text);after,offset=page['log_cursor'],page['log_offset']
                    if not page['log_more']:break
                else:self.fail('Log pagination did not terminate')
                self.assertEqual(''.join(received),''.join(expected));self.assertEqual(offset,0)
                self.assertEqual(self.a.read(ident,include_logs=True,after=after)['request']['logs'],[])
                for args in ({'max_chars':16001},{'max_chars':True},{'offset':-1},{'include_logs':'yes'}):
                    with self.assertRaises(Invalid):self.a.read(ident,**args)

    def test_repeated_followups_keep_business_context_without_recursive_archives(self):
        ident=self.request();lengths=[]
        for _ in range(8):
            self.noisy(ident)
            next_request=self.a.control(ident,'followup',message='Explain the result',resume=False)['request']
            row=self.a.get(next_request['id']);context=row['context']
            self.assertEqual(context['original_context'],{'task':'Compare methods','dataset':'shared/papers'})
            self.assertEqual(context['previous_request']['id'],ident)
            self.assertEqual(context['previous_request']['result']['answer'],42)
            self.assertNotIn('context',context['previous_request']);self.assertNotIn('history',context['previous_request'])
            self.assertNotIn('noise',json.dumps(context));self.assertNotIn('context',next_request)
            lengths.append(len(json.dumps(context)));ident=row['id']
        self.assertLess(max(lengths)-min(lengths),200)

    def test_legacy_followup_archive_is_flattened_without_losing_original_business_data(self):
        first={'id':'request-old','kind':'assistance','context':{'task':'Business task'},'logs':['old-noise']}
        second={'id':'request-next','kind':'assistance','context':{'previous_request':first},'logs':['next-noise'],'session':{'mode':'resume','request_id':first['id']}}
        current={'id':'request-current','kind':'assistance','message':'Continue','context':{'previous_request':second},'session':{'mode':'resume','request_id':second['id']}}
        context=continuation_context(current)
        self.assertEqual(context['original_context'],{'task':'Business task'})
        self.assertNotIn('noise',json.dumps(context))
        business={'previous_request':first}
        self.assertEqual(continuation_context({'context':business})['original_context'],business)

    def test_scoped_child_reads_forward_log_options(self):
        parent=self.request()
        with self.a.transaction() as db:
            row=self.a.get(parent,db);row.update(state='running',worker_token='test-worker');self.a.save(db,row)
        child=self.a.request({'location':'local','agent_id':'papers','message':'help','_parent_request':parent})['request']['id']
        with self.a.transaction() as db:
            row=self.a.get(child,db);row['executor']=self.b.settings()['instance_id'];self.a.save(db,row)
            db.execute('INSERT INTO communication_logs VALUES (?,?,?)',(child,1,'worker-output'))
        default=self.a.worker_call(parent,'test-worker','read_assistance',{'request_id':child})['request']
        self.assertNotIn('logs',default)
        page=self.a.worker_call(parent,'test-worker','read_assistance',{'request_id':child,'include_logs':True,'max_chars':6})['request']
        self.assertEqual(page['logs'][0]['text'],'worker');self.assertTrue(page['log_more'])
