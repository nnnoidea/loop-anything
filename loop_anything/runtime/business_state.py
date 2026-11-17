"""Loop-defined business records owned by a Timeline, independent of Run topology."""
import copy
import json
import time

from loop_anything.runtime.model import Invalid, Conflict, digest


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS work_state(
            timeline_id TEXT NOT NULL,type TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,
            document TEXT NOT NULL,PRIMARY KEY(timeline_id,type,id,revision));
        CREATE TABLE IF NOT EXISTS work_arrangements(
            timeline_id TEXT NOT NULL,key TEXT NOT NULL,document TEXT NOT NULL,PRIMARY KEY(timeline_id,key));
        CREATE TABLE IF NOT EXISTS work_results(
            timeline_id TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,
            PRIMARY KEY(timeline_id,id,revision));
    ''')


def validate_definition(definition):
    """Check only the metadata structure needed to display Loop-owned state."""
    if definition is None:return
    if not isinstance(definition,dict) or not isinstance(definition.get('types',{}),dict):
        raise Invalid('state.types must be an object')
    for name,spec in definition.get('types',{}).items():
        if not isinstance(name,str) or not name or not isinstance(spec,dict):raise Invalid('State types need a name and description object')
        if not isinstance(spec.get('summary',[]),list) or any(not isinstance(k,str) for k in spec.get('summary',[])):
            raise Invalid('State summary must name fields')


def load(db,timeline):
    rows=db.execute('''SELECT document FROM work_state s WHERE timeline_id=? AND revision=(
        SELECT max(revision) FROM work_state n WHERE n.timeline_id=s.timeline_id AND n.type=s.type AND n.id=s.id)
        ORDER BY type,id''',(timeline['id'],))
    records=[json.loads(r[0]) for r in rows]
    return {'records':records}


def overview(state,definition=None,limit=50):
    types=(definition or {}).get('types',{})
    ordered=sorted(state['records'],key=lambda r:(types.get(r['type'],{}).get('mode')!='current',-r['at'],r['type'],r['id']))
    records=[]
    for row in ordered[:limit]:
        fields=types.get(row['type'],{}).get('summary',[])
        value=row['value']
        summary={k:copy.deepcopy(value[k]) for k in fields if isinstance(value,dict) and k in value} if fields else {'value':copy.deepcopy(value)}
        records.append({k:copy.deepcopy(row[k]) for k in ('type','id','revision','refs','run_id','at')} | {'summary':summary})
    return {'records':records,'total':len(ordered),'complete':len(records)==len(ordered),
            'next_offset':len(records) if len(records)<len(ordered) else None}


def read(store,timeline_id,type=None,id=None,revision=None,offset=0,limit=50):
    from loop_anything.runtime import timelines
    if offset.__class__ is not int or offset<0 or limit.__class__ is not int or not 1<=limit<=200:
        raise Invalid('Invalid state page')
    if revision is not None and (not type or not id or revision.__class__ is not int or revision<1):
        raise Invalid('A historical state read needs type, id and positive revision')
    with store.connection() as db:
        db.execute('BEGIN')
        timeline=timelines.get(db,timeline_id)
        if revision is not None:
            row=db.execute('SELECT document FROM work_state WHERE timeline_id=? AND type=? AND id=? AND revision=?',
                           (timeline_id,type,id,revision)).fetchone()
            if not row:raise Invalid('Unknown business record revision')
            records=[json.loads(row[0])]
        else:
            records=[r for r in load(db,timeline)['records'] if (type is None or r['type']==type) and (id is None or r['id']==id)]
        page=records[offset:offset+limit]
        return {'timeline_id':timeline_id,'records':page,'total':len(records),
                'next_offset':offset+len(page) if offset+len(page)<len(records) else None}


def apply(run,execution,updates):
    """Stage a batch in the existing report transaction; the Store commits it with tasks/results."""
    if not isinstance(updates,list):raise Invalid('envelope.state must be an array')
    if not updates:return
    state=run['business_state']
    indexed={(r['type'],r['id']):r for r in state['records']}
    changed=[]
    for update in updates:
        if not isinstance(update,dict) or set(update)-{'type','id','value','refs'} or not {'type','id','value'}<=set(update):
            raise Invalid('State update needs type, id, value and optional refs')
        kind=update['type'];ident=update['id']
        if not isinstance(kind,str) or not kind or not isinstance(ident,str) or not ident:
            raise Invalid('State needs a nonempty type and id')
        key=(kind,ident);old=indexed.get(key)
        refs=update.get('refs',[])
        if not isinstance(refs,list) or any(not isinstance(r,dict) for r in refs):raise Invalid('State refs must be objects')
        for ref in refs:
            if set(ref) not in ({'type','id','revision'},{'record','revision'}) or type(ref.get('revision')) is not int or ref['revision']<1 or any(not isinstance(v,str) or not v for k,v in ref.items() if k!='revision'):
                raise Invalid('State refs require exact record identity and positive revision')
        if old and digest(old['value'])==digest(update['value']) and old['refs']==refs:continue
        row=dict(type=kind,id=ident,revision=old['revision']+1 if old else 1,value=copy.deepcopy(update['value']),refs=copy.deepcopy(refs),
                 run_id=run['id'],task_id=execution['task_id'],execution_id=execution['id'],at=time.time(),
                 intent_revision=run['timeline']['revision'])
        indexed[key]=row;changed.append(row)
    state['records']=list(indexed.values())
    run.setdefault('_state_updates',[]).extend(changed)


def persist(db,run,timeline):
    updates=run.pop('_state_updates',[])
    if not updates:return
    if any(not writer_allowed(db,timeline,run,row['task_id']) for row in updates):raise Conflict('Business state writer changed')
    for row in updates:
        row['intent_revision']=timeline['revision']
        for ref in row['refs']:
            if set(ref)=={'type','id','revision'}:
                found=any(r['type']==ref['type'] and r['id']==ref['id'] and r['revision']==ref['revision'] for r in updates)
                found=found or db.execute('SELECT 1 FROM work_state WHERE timeline_id=? AND type=? AND id=? AND revision=?',
                    (timeline['id'],ref['type'],ref['id'],ref['revision'])).fetchone()
            elif set(ref)=={'record','revision'}:
                found=any(r['revision']==ref['revision'] for r in run['records'].get(ref['record'],[]))
            else:raise Invalid('State reference must identify a state record or an output record and its exact revision')
            if not found:raise Invalid('Business evidence reference is missing')
        db.execute('INSERT INTO work_state VALUES (?,?,?,?,?)',(timeline['id'],row['type'],row['id'],row['revision'],json.dumps(row,ensure_ascii=False,allow_nan=False)))


def results(db,timeline_id):
    result={}
    for row in db.execute('SELECT document FROM work_results WHERE timeline_id=? ORDER BY id,revision',(timeline_id,)):
        record=json.loads(row[0]);result.setdefault(record['id'],[]).append(record)
    return result


def save_results(db,run):
    for versions in run['records'].values():
        for record in versions:
            row=db.execute('SELECT document FROM work_results WHERE timeline_id=? AND id=? AND revision=?',
                           (run['timeline_id'],record['id'],record['revision'])).fetchone()
            if row:
                if json.loads(row[0])!=record:raise Conflict('Committed result revisions cannot be rewritten')
            else:
                db.execute('INSERT INTO work_results VALUES (?,?,?,?)',(run['timeline_id'],record['id'],record['revision'],json.dumps(record,ensure_ascii=False,allow_nan=False)))


def arrangements(db,timeline_id):
    return {r[0]:json.loads(r[1]) for r in db.execute('SELECT key,document FROM work_arrangements WHERE timeline_id=?',(timeline_id,))}


def save_arrangements(db,run):
    for key,value in run.get('arrangements',{}).items():
        previous=db.execute('SELECT document FROM work_arrangements WHERE timeline_id=? AND key=?',(run['timeline_id'],key)).fetchone()
        if previous:
            if json.loads(previous[0])!=value:raise Conflict('Work key already has a different arrangement')
        else:db.execute('INSERT INTO work_arrangements VALUES (?,?,?)',(run['timeline_id'],key,json.dumps(value,ensure_ascii=False,allow_nan=False)))


def writer_allowed(db,timeline,run,task_id):
    if timeline.get('active_run_id')==run['id'] and not run.get('superseded_by'):return True
    # A retained execution may finish its already-authorized state/result report;
    # it cannot create new arrangements. The active Run must still await this task.
    return bool(run.get('superseded_by') and db.execute("""SELECT 1 FROM timeline_parts WHERE run_id=? AND section='tasks'
        AND json_extract(document,'$.status')='waiting'
        AND json_extract(document,'$.continuation_source.run_id')=?
        AND json_extract(document,'$.continuation_source.task_id')=? LIMIT 1""",
        (timeline.get('active_run_id'),run['id'],task_id)).fetchone())
