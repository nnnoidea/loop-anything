"""Call an installed Loop using ordinary Runs and the existing report/wait lifecycle."""
import json
from loop_anything.runtime.model import Invalid,digest
from loop_anything.runtime.store import Store,uid
from loop_anything.runtime.timeline_model import expand


def header(db, ident):
    row=db.execute('SELECT document FROM runs WHERE id=?',(ident,)).fetchone()
    if row is None:raise Invalid('Called Run is missing: '+ident)
    return json.loads(row[0])


def advance(runtime, run_id):
    store=runtime.store
    # One transaction links the new Run and its caller, including across crashes/concurrent ticks.
    with store.connection() as db:
        if not db.execute("SELECT 1 FROM timeline_parts WHERE run_id=? AND section='attempts' AND json_extract(document,'$.implementation.kind')='loop' AND json_extract(document,'$.status')='waiting' LIMIT 1",(run_id,)).fetchone():return
        db.execute('BEGIN IMMEDIATE')
        with store.edit(run_id,_db=db) as run:
            from loop_anything.runtime.timeline_runtime import end_condition
            if run['status']!='running' or end_condition(run)[0]:return
            for attempt in run['executions']:
                if attempt['implementation']['kind']!='loop' or attempt['status']!='waiting' or attempt.get('observation_error'):
                    continue
                task=run['tasks'][attempt['task_id']]
                if task.get('execution_id')!=attempt['id']:continue
                if end_condition(run)[0]:break
                config=attempt['implementation']['loop']
                try:
                    # Expand once per attempt; later settings edits cannot change an in-flight call.
                    if not attempt.get('child_run_id'):
                        values=expand(config.get('inputs',{'$':'inputs'}),{'inputs':attempt['inputs'],
                            'parameters':attempt['parameters'],'settings':run['settings']})
                        if not isinstance(values,dict):raise Invalid('Called Loop inputs must resolve to an object')
                    binding=task.get('child_call')
                    if binding:
                        if not attempt.get('child_run_id') and (binding['key']!=config['key'] or binding['inputs']!=digest(values)):
                            raise Invalid('This Task already called a Loop with different inputs/key; create a new Task to start different work')
                        child=header(db,binding['run_id'])
                    else:
                        ancestor=run
                        while True:
                            if ancestor['loop_key']==config['key']:
                                raise Invalid('Recursive Loop calls are not supported; use Tasks/plans for iteration')
                            parent=ancestor.get('parent_call')
                            if not parent:break
                            ancestor=header(db,parent['run_id'])
                        db.execute('SAVEPOINT create_child')
                        try:
                            child=store.create(config['key'],run['title']+' / '+task['id'],values,
                                authorization=run['settings'].get('authorization',''),acquire=False,_db=db,created_by=run.get('created_by',''),
                                notification_command=run['settings'].get('notification_command'),
                                notification_route=run['settings'].get('notification_route'))
                            child['parent_call']={'run_id':run_id,'task_id':task['id'],'execution_id':attempt['id']}
                            if run.get('notification_conversation_id'):child['notification_conversation_id']=run['notification_conversation_id']
                            Store.log(child,'called_by','Run created by a Loop node',detail=child['parent_call'])
                            store._save(db,child)
                        except BaseException:
                            db.execute('ROLLBACK TO create_child');raise
                        finally:db.execute('RELEASE create_child')
                        task['child_call']={'run_id':child['id'],'key':config['key'],'inputs':digest(values)}
                        Store.log(run,'loop_called','Created called Run',attempt['id'],{'run_id':child['id'],'key':config['key']})
                    attempt['child_run_id']=child['id'];attempt['child_status']=child['status']
                    if not attempt.get('external_id'):
                        runtime.report_in_run(run,attempt,{'event':'submitted','report_id':'loop:'+child['id']+':submitted',
                            'external_id':child['id']},'engine')
                    if attempt['status']!='waiting':continue
                    if child['status']=='completed':
                        child=store._load(db,child['id'])
                        attempt['child_revision']=child['revision']
                        context={'records':{key:versions[-1]['value'] for key,versions in child['records'].items() if versions},
                                 'settings':child['settings'],'inputs':child['inputs'],'run_id':child['id']}
                        result=expand(config.get('result',{'outputs':{}}),context)
                        runtime.report_in_run(run,attempt,{'event':'completed','report_id':'loop:'+child['id']+':completed',
                            'envelope':result,'detail':{'child_run_id':child['id'],'child_revision':child['revision']}},'engine')
                    elif child['status']=='terminated':
                        runtime.report_in_run(run,attempt,{'event':'failed','report_id':'loop:'+child['id']+':terminated',
                            'detail':{'message':'Called Run was terminated','child_run_id':child['id']}},'engine')
                except (KeyError,IndexError,TypeError,ValueError) as exc:
                    runtime.report_in_run(run,attempt,{'event':'process_error','report_id':uid('loop-error'),
                        'detail':{'message':str(exc),'child_run_id':attempt.get('child_run_id')}},'engine')
        db.commit()
