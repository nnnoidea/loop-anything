"""Durable work context, independent of a Loop or execution lifetime."""
import copy
import json
import time

from loop_anything.runtime.model import Invalid, Conflict, digest
from loop_anything.runtime.store import uid

CHECK_NOTICE = '目标|限制已修改，请重新检查 Timeline 是否仍然符合更新后的目标|限制，尤其是正在运行的任务，把检查结果告诉用户。检查供用户决定；用户未决定，不额外暂停、取消、重排或重跑任务。'


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS work_timelines(id TEXT PRIMARY KEY, document TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS work_entries(timeline_id TEXT NOT NULL, key TEXT NOT NULL,
            sequence INTEGER NOT NULL, document TEXT NOT NULL, PRIMARY KEY(timeline_id,key));
    ''')



def get(db, ident):
    row = db.execute('SELECT document FROM work_timelines WHERE id=?', (ident,)).fetchone()
    if row is None: raise Invalid('Unknown Timeline')
    return json.loads(row[0])


def save(db, value):
    db.execute('INSERT INTO work_timelines VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
               (value['id'], json.dumps(value, ensure_ascii=False)))


def create(db, objective='', constraints='', title='', ident=None):
    if not all(isinstance(s, str) for s in (objective, constraints, title)):
        raise Invalid('Timeline objective and constraints must be natural-language text')
    value = dict(id=ident or uid('timeline'), title=title, objective=objective, constraints=constraints,
                 revision=1, created_at=time.time(), active_run_id=None)
    save(db, value)
    return value


def append(db, ident, key, text, kind='note', refs=None, actor='agent'):
    get(db, ident)
    if not isinstance(key, str) or not key or not isinstance(text, str): raise Invalid('Entry needs key and text')
    if kind not in ('note', 'progress', 'decision', 'action', 'change'): raise Invalid('Unknown entry kind')
    body = dict(text=text, kind=kind, refs=refs or [], actor=actor)
    old = db.execute('SELECT document FROM work_entries WHERE timeline_id=? AND key=?', (ident,key)).fetchone()
    if old:
        entry=json.loads(old[0])
        if entry['fingerprint'] != digest(body): raise Conflict('Entry key already belongs to different content')
        return entry
    sequence=db.execute('SELECT coalesce(max(sequence),0)+1 FROM work_entries WHERE timeline_id=?',(ident,)).fetchone()[0]
    entry=dict(body, key=key, sequence=sequence, at=time.time(), fingerprint=digest(body))
    db.execute('INSERT INTO work_entries VALUES (?,?,?,?)',(ident,key,sequence,json.dumps(entry,ensure_ascii=False)))
    return entry


def update(db, ident, revision, change, message=''):
    if not change or set(change)-{'objective','constraints'} or any(not isinstance(v,str) for v in change.values()):
        raise Invalid('Only objective and constraints may be edited; both are text')
    value=get(db,ident)
    if revision != value['revision']: raise Conflict('Timeline changed; reread before editing')
    before={k:value[k] for k in change}
    if before == change:return dict(timeline=value,changed=False)
    value.update(change);value['revision']+=1
    save(db,value)
    append(db,ident,'change:'+str(value['revision']),message or '目标／限制已修改','change',
           [{'before':before,'after':change,'revision':value['revision']}],actor='user')
    return dict(timeline=value,changed=True,notice=CHECK_NOTICE)


def list_timelines(store, loop_id=None, unbound=False, limit=20, offset=0):
    """Classify by the current method, retaining its label after the Run is deleted."""
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise Invalid('limit must be 1..100 and offset must be nonnegative')
    if type(unbound) is not bool or loop_id is not None and (not isinstance(loop_id,str) or not loop_id):
        raise Invalid('Supply a Loop ID or unbound=true')
    if unbound and loop_id is not None:raise Invalid('Loop and temporary-work filters are mutually exclusive')
    catalog = """WITH classified AS (
        SELECT w.id,w.document,json_extract(w.document,'$.created_at') AS created_at,
            coalesce(json_extract(l.document,'$.id'),json_extract(w.document,'$.loop_id')) AS loop_id,
            coalesce(nullif(json_extract(l.document,'$.name'),''),json_extract(l.document,'$.id'),
                     json_extract(w.document,'$.loop_name')) AS loop_name
        FROM work_timelines w LEFT JOIN runs r ON r.id=json_extract(w.document,'$.active_run_id')
        LEFT JOIN loop_definitions l ON l.key=json_extract(r.document,'$.loop_key')
    ) """
    where=' WHERE loop_id IS NULL' if unbound else ' WHERE loop_id=?' if loop_id is not None else ''
    args=[loop_id] if loop_id is not None else []
    with store.connection() as db:
        db.execute('BEGIN')
        groups=[dict(r) for r in db.execute(catalog+"""SELECT loop_id,
            (SELECT loop_name FROM classified n WHERE n.loop_id IS c.loop_id
                ORDER BY created_at DESC,id DESC LIMIT 1) AS name,count(*) AS count
            FROM classified c GROUP BY loop_id ORDER BY loop_id IS NULL,name,loop_id""")]
        for group in groups:
            if group['loop_id'] is None:group['name']='临时工作'
        total=db.execute(catalog+'SELECT count(*) FROM classified'+where,args).fetchone()[0]
        rows=db.execute(catalog+'SELECT document,loop_id,loop_name FROM classified'+where+
                        ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
        items=[dict(json.loads(row['document']),loop_id=row['loop_id'],loop_name=row['loop_name']) for row in rows]
        return dict(timelines=items,groups=groups,total=total,offset=offset,limit=limit,
                    next_offset=offset+len(items) if offset+len(items)<total else None)


def read(store, ident, after=0, limit=100):
    if type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=200:raise Invalid('Invalid entry page')
    with store.connection() as db:
        db.execute('BEGIN')
        value=get(db,ident)
        rows=db.execute('SELECT document FROM work_entries WHERE timeline_id=? AND sequence>? ORDER BY sequence LIMIT ?',
                        (ident,after,limit+1)).fetchall()
        entries=[json.loads(r[0]) for r in rows[:limit]]
        runs=[]
        for row in db.execute('SELECT id,document FROM runs WHERE json_extract(document,\'$.timeline_id\')=?',(ident,)):
            run=json.loads(row[1]);run['status']=public_status(run);runs.append({k:run.get(k) for k in ('id','title','status','continued_from','superseded_by')})
        from loop_anything.runtime import business_state
        current=db.execute("SELECT l.document FROM runs r JOIN loop_definitions l ON l.key=json_extract(r.document,'$.loop_key') WHERE r.id=?",(value.get('active_run_id'),)).fetchone()
        definition=(json.loads(current[0]).get('state') if current else None) or value.get('state_definition')
        result_rows=db.execute("""SELECT id,revision,json_extract(document,'$.type') AS type,
                json_extract(document,'$.source_run_id') AS source_run_id,json_extract(document,'$.at') AS at
                FROM work_results WHERE timeline_id=? ORDER BY rowid DESC LIMIT 51""",(ident,)).fetchall()
        from loop_anything.runtime.observations import overview as view_overview
        return dict(timeline=value,observations=view_overview(db,ident),entries=entries,runs=runs,business_state=business_state.timeline_overview(db,ident,definition),
                    results={'records':[dict(r) for r in result_rows[:50]],
                             'complete':len(result_rows)<=50},
                    cursor=entries[-1]['sequence'] if entries else after,has_more=len(rows)>limit)


def attach(db, run, ident=None):
    value=get(db,ident) if ident else create(db,run['settings'].get('objective',''),
        run['settings'].get('constraints',''),run['title'])
    from loop_anything.runtime import business_state
    definition=run['loop_definition']
    value.update(loop_id=definition['id'],loop_name=definition.get('name') or definition['id'])
    run['timeline_id']=value['id']
    run['records']=business_state.results(db,value['id'])
    run['business_state']=business_state.load(db,value)
    run['arrangements']=business_state.arrangements(db,value['id']) if value.get('active_run_id') else {}
    for destination in run['tasks'].get(run['loop_definition'].get('seed',{}).get('id'),{}).get('spec',{}).get('outputs',{}).values():
        if destination['id'] in run['records']:destination['expected_revision']=run['records'][destination['id']][-1]['revision']
    save(db,value)
    project(run,value)
    if not value.get('active_run_id'):
        value['active_run_id']=run['id'];save(db,value)
    append(db,value['id'],'run:'+run['id'],'Run 已关联','action',[{'run_id':run['id']}],actor='platform')


def project(run, value):
    run['timeline']=copy.deepcopy(value)
    run['settings'].update(objective=value['objective'],constraints=value['constraints'])


def persist(db, run):
    """Support initialization writes in the same transaction, without duplicate semantic storage."""
    current=get(db,run['timeline_id'])
    loaded=run['timeline']
    changes={k:run['settings'][k] for k in ('objective','constraints') if run['settings'][k]!=loaded[k]}
    if changes:
        result=update(db,current['id'],loaded['revision'],changes)
        current=result['timeline']
    from loop_anything.runtime import business_state
    business_state.persist(db,run,current)
    save(db,current)
    project(run,current)


def continue_from(store, db, run, source_id):
    """Reuse committed work; in-flight actions remain observed at their original identities."""
    from loop_anything.runtime.task_scope import process_active, owner_for
    source=store._load(db,source_id)
    if source.get('superseded_by'):raise Conflict('Run already continued by '+source['superseded_by'])
    if source.get('identity_read_only'):raise Conflict('Copied workspace cannot take over a Run')
    for task in source['tasks'].values():
        if not (task['spec']['node']=='$flow_agent' or task['origin'].get('entry')):continue
        if any(e['implementation']['kind']=='agent' and process_active(e) and (e.get('worker_active') or owner_for(source,e.get('token')) or task['status'] not in ('completed','cancelled','skipped','stale')) for e in source['executions'] if e['task_id']==task['id']):
            raise Conflict('Original Agent is active or its stop is unconfirmed')
    run['continued_from']=source_id
    refreshed=source['loop_key']!=run['loop_key']
    if not refreshed:
        run['settings']=copy.deepcopy(source['settings'])
        run['inputs']=copy.deepcopy(source['inputs'])
        run['hook_firings']=copy.deepcopy(source['hook_firings'])
        run['task_dispositions']=copy.deepcopy(source.get('task_dispositions',{}))
    seed=copy.deepcopy(run['tasks'])
    run['tasks']=seed if refreshed else {}
    run['retained_nodes']={}
    if source.get('retained_methods'):
        run['retained_methods']=copy.deepcopy(source['retained_methods'])
    seed_id=run['loop_definition'].get('seed',{}).get('id')
    if refreshed and seed_id in source['tasks']:
        entry=run['tasks'].pop(seed_id)
        from loop_anything.runtime.store import uid
        ident=uid('task');entry['id']=entry['spec']['id']=ident
        run['tasks'][ident]=entry;run['loop_definition']['seed']['id']=ident
    for ident,task in source['tasks'].items():
        item=copy.deepcopy(task)
        if refreshed:
            item['spec']['node']=retain_node(run,source,task['spec'],task.get('execution_id'))
            item['spec'].pop('implementation',None)

        if not refreshed and item['spec']['node'] in source.get('retained_nodes',{}):
            run['retained_nodes'][item['spec']['node']]=copy.deepcopy(source['retained_nodes'][item['spec']['node']])

        # Already arranged work retains the exact available input revisions.
        # New entry results must not silently replace an old experiment's inputs.
        from loop_anything.runtime.model import record_refs, path
        attempt=next((e for e in source['executions'] if e['id']==task.get('execution_id')), {})
        for input_name,input_source in item['spec']['inputs'].items():
            if 'run' in input_source:
                try:value=copy.deepcopy(path(source['inputs'],input_source['run']))
                except (KeyError,IndexError,TypeError):raise Conflict('Retained task has unresolved original Run inputs: '+ident)
                input_source.clear();input_source['literal']=value
            if ('record' in input_source or 'records' in input_source) and 'revision' not in input_source and 'revisions' not in input_source:
                refs=record_refs(input_source)
                versions=[]
                observed=attempt.get('sources',{}).get(input_name,[])
                observed=[observed] if isinstance(observed,dict) else observed
                for index,(rid,_) in enumerate(refs):
                    pinned=observed[index] if index<len(observed) else {}
                    if pinned.get('record')==rid:versions.append(pinned['revision'])
                    elif source['records'].get(rid):versions.append(source['records'][rid][-1]['revision'])
                    else:
                        producers={d.get('expected_revision',0)+1 for t in source['tasks'].values()
                                   for d in t['spec']['outputs'].values() if d['id']==rid and t['status'] not in ('cancelled','stale','skipped')}
                        if len(producers)>1:raise Conflict('Pending input has ambiguous producer versions: '+rid)
                        versions.append(next(iter(producers),1))
                if 'record' in input_source:input_source['revision']=versions[0]
                else:input_source['revisions']=versions
        if task['status']=='completed':
            item['origin']['retained_result_refs']={p:{'record':r['id'],'revision':r['revision']} for p,r in output_records(source,task).items()}
        item['execution_id']=None
        item.pop('assistance_wait',None);item.pop('assistance_resume',None)
        if task['status'] not in ('completed','cancelled','skipped','stale','planned','ready','blocked','held'):
            item['status']='waiting'
            item['continuation_source']=copy.deepcopy(task.get('continuation_source') or {'run_id':source_id,'task_id':ident})
        run['tasks'][ident]=item
    materialize_retained(run)
    # Keep observers alive but prevent the old run from dispatching or routing new work.
    source['superseded_by']=run['id']
    if any(t.get('continuation_source') for t in run['tasks'].values()):source['status']='running'
    source['settings']['termination_signal']='';source['settings']['completion_rule']=None
    store._save(db,source)
    value=get(db,run['timeline_id']);value['active_run_id']=run['id'];save(db,value)
    append(db,value['id'],'continue:'+run['id'],'新 Run 接续已有进度；在途工作沿原执行身份观察。','action',
           [{'run_id':run['id'],'source_run_id':source_id}],actor='platform')


def detach_source(db,source):
    """Keep method inputs for retained plan routes. Only outstanding execution observations need the actual Run."""
    for row in db.execute("SELECT id,document FROM runs WHERE json_extract(document,'$.timeline_id')=? AND id!=?",
                          (source['timeline_id'],source['id'])).fetchall():
        header=json.loads(row['document'])
        if db.execute("""SELECT 1 FROM timeline_parts WHERE run_id=? AND section='tasks'
                AND json_extract(document,'$.continuation_source.run_id')=?
                AND json_extract(document,'$.status')='waiting' LIMIT 1""",(row['id'],source['id'])).fetchone():
            raise Conflict('A continuation is still observing this Run')
        # Ended/cancelled proxies no longer observe the source. A future explicit
        # retry belongs to the successor and must not resurrect the deleted link.
        db.execute("""UPDATE timeline_parts SET document=json_remove(document,'$.continuation_source')
                      WHERE run_id=? AND section='tasks' AND json_extract(document,'$.continuation_source.run_id')=?""",
                   (row['id'],source['id']))
        nodes=header.get('retained_nodes',{}).values()
        if any(n['source_run_id']==source['id'] and any(r.get('plan') for r in n['node'].get('routes',[])) for n in nodes):
            method={k:source[k] for k in ('id','loop_key','configuration') if k in source}
            coordinator=source.get('collaboration',{}).get('coordinator_implementation')
            if coordinator:method['collaboration']={'coordinator_implementation':coordinator}
            method['settings']={'bindings':source['settings'].get('bindings',{})}
            header.setdefault('retained_methods',{})[source['id']]=method
            db.execute('UPDATE runs SET document=? WHERE id=?',(json.dumps(header,ensure_ascii=False),row['id']))


def advance_continuations(store, run, runtime):
    # Complete the proxy through the normal report path, so routes and the bound
    # Agent receive the result exactly once without executing the original job.
    for task in list(run['tasks'].values()):
        ref=task.get('continuation_source')
        if not ref or task['status']!='waiting':continue
        source=store.get(ref['run_id']);old=source['tasks'][ref['task_id']]
        attempt=next((e for e in source['executions'] if e['id']==old.get('execution_id')), {})
        if old['status']=='completed':
            committed=output_records(source,old)
            outputs={port:record['value'] for port,record in committed.items()}
            e=runtime.new_execution(run,task,{'kind':'event','event':'continuation-result'},
                                    attempt.get('inputs',{}),{'continuation':dict(ref,execution_id=attempt.get('id'))})
            e['continuation_record_refs']={port:{'record':r['id'],'revision':r['revision']} for port,r in committed.items()}
            e['status']='waiting';task['status']='waiting'
            runtime.report_in_run(run,e,{'event':'completed','report_id':'continued:'+str(attempt.get('id')),
                                        'envelope':{'outputs':outputs}},'continuation')
            task.pop('continuation_source')
        elif old['status'] in ('cancelled','skipped','stale'):
            task['status']=old['status'];task.pop('continuation_source')
        else:
            task['wait_reasons']=[{'reason':'original_execution','source':ref,'status':old['status'],
                                  'error':attempt.get('observation_error') or attempt.get('error')}]


def retain_node(run, source, spec, execution_id=None):
    """Keep an arranged task's execution contract and method source together."""
    from loop_anything.runtime.implementations import selected
    original=spec['node']
    prior=source.get('retained_nodes',{}).get(original)
    if prior:
        run.setdefault('retained_nodes',{})[original]=copy.deepcopy(prior)
        materialize_retained(run)
        return original
    _,implementation=selected(source,{'spec':spec,'execution_id':execution_id})
    name='$retained:'+digest([source.get('method_ref',source['id']),original,implementation])[:24]
    node=copy.deepcopy(source['loop_definition']['nodes'][original])
    output_types={p:v['record_type'] for p,v in node['outputs'].items()}
    schemas={}
    for port,destination in node['outputs'].items():
        old_type=destination['record_type'];new_type=name+':'+port
        schemas[new_type]=source['loop_definition']['records'][old_type]
        destination['record_type']=new_type
    run.setdefault('retained_nodes',{})[name]={'node':node,'schemas':schemas,'implementation':implementation,
        'loop_key':source['loop_key'],'source_run_id':source['id'],
        **({'method_ref':source['method_ref']} if 'method_ref' in source else {}),'node_id':original,'output_types':output_types,
        'handbook':copy.deepcopy(source['loop_definition'].get('handbook',{}))}
    materialize_retained(run)
    return name


def materialize_retained(run):
    """Existing work keeps its original contract, rules and resources."""
    for name,entry in run.get('retained_nodes',{}).items():
        run['loop_definition']['nodes'][name]=copy.deepcopy(entry['node'])
        run['loop_definition']['records'].update(copy.deepcopy(entry['schemas']))
        run['implementations'][name]={'options':{'retained':copy.deepcopy(entry['implementation'])},'default':'retained'} if entry['implementation'] else {'options':{}}


def output_records(run,task):
    """Read the exact results committed by this task's execution, never latest shared values."""
    from loop_anything.runtime.timeline_runtime import record_version
    if task['status']!='completed':return {}
    attempt=next((e for e in run['executions'] if e['id']==task.get('execution_id')),None)
    if attempt is None and task.get('origin',{}).get('retained_result_refs'):
        refs=task['origin']['retained_result_refs']
    else:refs=(attempt or {}).get('record_refs',{})
    results={}
    for port,destination in task['spec']['outputs'].items():
        ref=refs.get(port)
        if not ref or ref['record']!=destination['id']:raise Conflict('Task is missing its committed result reference')
        record=record_version(run,ref['record'],ref['revision'])
        if record is None:raise Conflict('Committed task result is missing')
        results[port]=record
    return results


def task_resources(run,node_id):
    """Existing tasks use their original installed package; new tasks use this Loop."""
    retained=run.get('retained_nodes',{}).get(node_id)
    return (retained['loop_key'],retained['handbook']) if retained else (run['loop_key'],run['loop_definition'].get('handbook',{}))


def logical_node(run,node):
    return run.get('retained_nodes',{}).get(node,{}).get('node_id',node)


def completed_counts(run,items,node_of):
    counts=dict.fromkeys(run['loop_definition']['nodes'],0)
    for item in items:
        if item['status']=='completed':
            node=node_of(item)
            for ident in {node,logical_node(run,node)}:
                counts[ident]=counts.get(ident,0)+1
    return counts


def public_status(run):
    return 'continued' if run.get('superseded_by') else run['status']


def current_run_id(db,run):
    return get(db,run['timeline_id'])['active_run_id'] or run['id']
