"""Run-owned subscriptions and recoverable generation of a Timeline view."""
import base64
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loop_anything.runtime import checks, events, timelines
from loop_anything.runtime.model import Invalid
from loop_anything.runtime.store import uid


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS published_methods(key TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS observations(
            run_id TEXT, name TEXT, timeline_id TEXT NOT NULL, generation TEXT NOT NULL,
            config TEXT NOT NULL, cursor INTEGER NOT NULL, due REAL, PRIMARY KEY(run_id,name));
        CREATE TABLE IF NOT EXISTS observation_jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, name TEXT NOT NULL,
            generation TEXT NOT NULL, reason TEXT NOT NULL, input TEXT, status TEXT NOT NULL, error TEXT, process_pid INTEGER, remote_call TEXT);
        CREATE INDEX IF NOT EXISTS observation_queue ON observation_jobs(status,run_id,name);
        CREATE INDEX IF NOT EXISTS observation_jobs_run ON observation_jobs(run_id,id);
        CREATE TABLE IF NOT EXISTS observation_views(
            timeline_id TEXT, name TEXT, job_id INTEGER NOT NULL, document TEXT NOT NULL,
            PRIMARY KEY(timeline_id,name));
        CREATE INDEX IF NOT EXISTS observation_views_run ON observation_views(json_extract(document,'$.run_id'));
        CREATE TRIGGER IF NOT EXISTS remove_observation_jobs AFTER DELETE ON observations BEGIN
            DELETE FROM observation_jobs WHERE run_id=old.run_id AND name=old.name;
        END;
        CREATE TRIGGER IF NOT EXISTS remove_run_observations AFTER DELETE ON runs BEGIN
            DELETE FROM observations WHERE run_id=old.id;
        END;
    """)


def encode(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def next_due(config,now):
    if 'every' in config:
        interval=config['every']
        if type(interval) not in (float,int) or not math.isfinite(interval) or interval<=0:
            raise Invalid('every must be a positive interval in seconds')
        return now+interval
    if 'daily' in config:
        try:
            hour,minute=map(int,config['daily'].split(':'))
            local=datetime.fromtimestamp(now,ZoneInfo(config['timezone']))
            target=local.replace(hour=hour,minute=minute,second=0,microsecond=0)
            if target<=local:target+=timedelta(days=1)
            return target.timestamp()
        except (ValueError,KeyError,TypeError,AttributeError,ZoneInfoNotFoundError) as exc:
            raise Invalid('daily needs HH:MM and an IANA timezone') from exc
    return None


def validate(config):
    if not isinstance(config,dict):raise Invalid('Observation must be an object')
    steps=config.get('steps')
    if not isinstance(steps,list) or not steps:raise Invalid('Observation needs command or agent steps')
    for step in steps:
        if not isinstance(step,dict) or step.get('kind') not in ('command','agent'):
            raise Invalid('Observation steps use command or agent')
        from loop_anything.runtime.implementations import validate_implementation
        validate_implementation(step)
        if step.get('dispatch'):raise Invalid('Use the configured Agent command or an executor for an observation')
        if 'asset_manifest' in step and not (isinstance(step['asset_manifest'],list) and all(isinstance(p,str) for p in step['asset_manifest'])):
            raise Invalid('asset_manifest must list required package paths')
        if not step.get('command'):raise Invalid('Supply the observation command')
    match=config.get('on',{'kind':'result'})
    if match is not None and (not isinstance(match,dict) or match.get('kind') not in
            ('result','state','task','run','monitor','current_run','signal','run_deleted')):
        raise Invalid('on must select a platform fact kind or be null')
    if 'condition' in config:checks.validate_expression(config['condition'])
    if 'every' in config and 'daily' in config:raise Invalid('Choose interval or daily schedule')
    next_due(config,time.time())
    if 'notify_on' in config and (not isinstance(config['notify_on'],list) or
                                  set(config['notify_on'])-{'event','schedule'}):
        raise Invalid('notify_on selects event or schedule')


def validate_defaults(definitions):
    if not isinstance(definitions,dict):raise Invalid('observations must map names to definitions')
    for name,config in definitions.items():
        if not isinstance(name,str) or not name.strip():raise Invalid('Observation needs a name')
        validate(config)


def snapshot(db,sub,trigger):
    timeline=timelines.get(db,sub['timeline_id'])
    # Both version tables are append-only. Capture their high water marks in the enqueue transaction.
    as_of = {key:db.execute('SELECT coalesce(max(rowid),0) FROM '+table).fetchone()[0]
             for key,table in (('results','work_results'),('state','work_state'))}
    return {'timeline':{k:timeline[k] for k in ('id','title','objective','constraints')},
            'run_id':sub['run_id'],'trigger':trigger,'as_of':as_of}


def queue(db,sub,reason,trigger=None):
    payload=encode(snapshot(db,sub,trigger))
    config=json.loads(sub['config'])
    # Only coalesce like triggers; a manual preview must never acquire a scheduled send.
    if reason=='event' and not config.get('each'):
        updated=db.execute("""UPDATE observation_jobs SET input=? WHERE run_id=? AND name=?
                AND generation=? AND reason='event' AND status='pending'
                AND remote_call IS NULL AND json_type(input,'$.step') IS NULL""",
                (payload,sub['run_id'],sub['name'],sub['generation']))
        if updated.rowcount:return
    db.execute("""INSERT INTO observation_jobs(run_id,name,generation,reason,input,status)
                  VALUES(?,?,?,?,?,'pending')""",(sub['run_id'],sub['name'],sub['generation'],reason,payload))


def overlay(defaults, patch):
    config = dict(defaults)
    if 'daily' in patch:
        config.pop('every', None)
    if 'every' in patch:
        config.pop('daily', None)
    config.update(patch)
    return config


def generation_changed(db, previous, current):
    metadata = {'loop_key', 'package_root', 'description'}
    missing = object()
    if any(previous.get(k, missing) != current.get(k, missing) for k in (previous.keys() | current.keys()) - metadata):
        return True
    if previous['loop_key'] == current['loop_key']:
        return False
    # A script can import other bundled assets. Compare the existing file manifests,
    # so editing Loop metadata preserves the queue while editing script contents redraws.
    manifests = [json.loads(row[0]) for row in db.execute(
        "SELECT json_extract(document,'$.files') FROM loop_packages WHERE key IN (?,?)",
        (previous['loop_key'], current['loop_key']))]
    return len(manifests) != 2 or manifests[0] != manifests[1]


def sync(db,run):
    defaults=run['loop_definition'].get('observations',{})
    overrides=run.get('observation_overrides',{})
    existing={r['name']:r for r in db.execute('SELECT * FROM observations WHERE run_id=?',(run['id'],))}
    for name in set(defaults)|set(overrides)|set(existing):
        patch=overrides.get(name,{})
        config=overlay(defaults.get(name,{}),patch) if patch is not None else {}
        old=existing.get(name)
        if not config:
            if old:db.execute('DELETE FROM observations WHERE run_id=? AND name=?',(run['id'],name))
            continue
        validate(config)
        config['package_root']=(run.get('configuration') or {}).get('package_root')
        config['loop_key']=run['loop_key']
        packed=encode(config)
        now = time.time()
        if old:
            previous = json.loads(old['config'])
            if previous == config:
                continue
            package_changed = previous['loop_key'] != config['loop_key']
            revised = generation_changed(db, previous, config)
            if revised:
                # Match facts committed before the edit using the old subscription.
                dispatch(db, now, old['generation'])
            if package_changed or revised:
                # Jobs already accepted retain their original steps, package and notification route.
                db.execute("""UPDATE observation_jobs SET input=json_set(input,'$.observation_config',json(?))
                    WHERE generation=? AND input IS NOT NULL AND json_type(input,'$.observation_config') IS NULL""",
                    (old['config'], old['generation']))
            if not revised:
                db.execute('UPDATE observations SET config=? WHERE generation=?', (packed, old['generation']))
                continue
            # Superseded previews can be discarded. Accepted deliveries still run to their receipt.
            db.execute("""DELETE FROM observation_jobs WHERE generation=?
                AND reason NOT IN (SELECT value FROM json_each(?, '$.notify_on'))""",
                (old['generation'], old['config']))
            schedule_keys = ('every', 'daily', 'timezone')
            due = (next_due(config, now) if any(previous.get(k) != config.get(k) for k in schedule_keys)
                   else db.execute('SELECT due FROM observations WHERE generation=?', (old['generation'],)).fetchone()[0])
            db.execute('UPDATE observations SET config=?,generation=?,cursor=?,due=? WHERE generation=?',
                       (packed,uid('view'),events.position(db),due,old['generation']))
        else:
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?)',
                       (run['id'],name,run['timeline_id'],uid('view'),packed,events.position(db),next_due(config,now)))
        sub=db.execute('SELECT * FROM observations WHERE run_id=? AND name=?',(run['id'],name)).fetchone()
        queue(db,sub,'initial')


def dispatch(db,now,generation=None):
    high=events.position(db)
    query = 'SELECT * FROM observations WHERE (cursor<? OR due<=?)'
    args = [high, now]
    if generation is not None:
        query += ' AND generation=?'
        args.append(generation)
    for sub in db.execute(query,args).fetchall():
        config=json.loads(sub['config'])
        match=config.get('on',{'kind':'result'})
        due=sub['due']
        timeline=timelines.get(db,sub['timeline_id'])
        header=db.execute("SELECT json_extract(document,'$.status') FROM runs WHERE id=?",(sub['run_id'],)).fetchone()
        active=timeline.get('active_run_id')==sub['run_id'] and header and header[0] not in ('completed','terminated')
        last_match=None
        if match:
            # A Run-owned subscription observes its Timeline until that Run ends or is replaced.
            for event in db.execute("""SELECT * FROM platform_events WHERE (timeline_id=? OR
                    (kind='monitor' AND subject=?)) AND sequence>? AND sequence<=? ORDER BY sequence""",(sub['timeline_id'],match.get('subject') if match.get('kind')=='monitor' else None,sub['cursor'],high)):
                detail=json.loads(event['detail'])
                fact=dict(detail,sequence=event['sequence'],kind=event['kind'],subject=event['subject'],run_id=event['run_id'])
                if all(fact.get(k)==v for k,v in match.items()):
                    if config.get('each'):queue(db,sub,'event',fact)
                    else:last_match=fact
                if ((fact['kind']=='run' and fact['run_id']==sub['run_id'] and fact.get('status') in ('completed','terminated'))
                        or (fact['kind']=='current_run' and fact['run_id']!=sub['run_id'])):
                    # Keep the config for reading and its final pending jobs, stop further subscriptions.
                    config['on']=None
                    db.execute('UPDATE observations SET config=? WHERE generation=?',(encode(config),sub['generation']))
                    break
        if last_match is not None:queue(db,sub,'event',last_match)
        if due is not None and due<=now and active:
            queue(db,sub,'schedule')
            due=next_due(config,now)
        db.execute('UPDATE observations SET cursor=?,due=? WHERE generation=?',
                   (high,due if active else None,sub['generation']))


def condition_matches(db, expression, facts):
    from loop_anything.runtime import business_state
    from loop_anything.runtime.model import path
    tid = facts['timeline']['id']

    def read_path(key, size=False):
        parts = key.split('.') if isinstance(key,str) and key else list(key)
        root = parts[0] if parts else None
        if root in ('state','results'):
            query,args = business_state.record_query(tid,root,as_of=facts['as_of'][root])
            if len(parts)==1 and size:
                return db.execute('SELECT count(*)'+query,args).fetchone()[0]
            order = ' ORDER BY s.type,s.id' if root=='state' else ' ORDER BY s.rowid'
            if len(parts)>1:
                index = int(parts[1])
                if index<0:
                    index += db.execute('SELECT count(*)'+query,args).fetchone()[0]
                row = db.execute('SELECT s.document'+query+order+' LIMIT 1 OFFSET ?', [*args,index]).fetchone()
                if index<0 or row is None:
                    raise IndexError('Record outside observation snapshot')
                value = path(json.loads(row[0]),parts[2:])
            else:
                value = [json.loads(r[0]) for r in db.execute('SELECT s.document'+query+order,args)]
        elif root=='trigger' and facts.get('trigger') and (len(parts)==1 or parts[1]=='record'):
            trigger = dict(facts['trigger'])
            if trigger['kind'] in ('state','result'):
                collection = 'state' if trigger['kind']=='state' else 'results'
                page = business_state.record_page(db,tid,collection,id=trigger['subject'],revision=trigger['revision'],
                                                   type=trigger.get('type'),limit=1)
                trigger['record'] = page['records'][0]
            value = path(trigger,parts[1:])
        else:
            value = path(facts,parts)
        return len(value) if size else value

    return checks.evaluate(expression,facts,read_path=read_path)


def recover(db,store):
    # A claim only reserves a worker slot. Only a launched local process is ambiguous.
    db.execute("UPDATE observation_jobs SET status='pending' WHERE status IN ('claimed','preparing')")
    db.execute("""UPDATE observation_jobs SET status='pending' WHERE status='running'
                  AND (remote_call IS NOT NULL OR json_extract(input,'$.step') >=
                  coalesce(json_array_length(input,'$.observation_config.steps'),
                      (SELECT json_array_length(config,'$.steps') FROM observations s
                       WHERE s.generation=observation_jobs.generation)))""")
    interrupted = db.execute("SELECT id,run_id,name FROM observation_jobs WHERE status='running'").fetchall()
    db.execute("""UPDATE observation_jobs SET status='unknown',
                  error='Service interrupted during execution; inspect before retry'
                  WHERE status='running'""")

    for job in interrupted:
        log_outcome(store,db,job,'unknown','Service interrupted during execution; inspect before retry')


def log_outcome(store,db,job,status,error=None):
    with store.edit(job['run_id'],_db=db) as run:
        store.log(run,'observation_'+status,job['name'],detail=dict(name=job['name'],job=job['id'],error=error))


def release_receipts(engine):
    # Disabling an arrangement can leave an executor finishing its last step.
    with engine.store.connection() as db:
        rows = db.execute("""SELECT id FROM executor_calls c
            WHERE json_extract(document,'$.metadata.kind')='observation'
            AND json_extract(document,'$.applied') IS NOT 1
            AND json_extract(document,'$.state') IN ('completed','failed')
            AND NOT EXISTS (SELECT 1 FROM observation_jobs j WHERE j.remote_call=c.id
                            AND j.status NOT IN ('failed','unknown'))""").fetchall()
    for row in rows:
        engine.executors.applied(row['id'])


def collect(store):
    """Claim one job per arrangement, atomically with its consumer cursor."""
    from loop_anything.runtime.work import transaction
    with transaction(store) as db:
        dispatch(db,time.time())
        db.execute("""UPDATE observation_jobs SET status='pending',error=NULL WHERE status='remote' AND EXISTS(
            SELECT 1 FROM executor_calls WHERE executor_calls.id=observation_jobs.remote_call
            AND json_extract(document,'$.state') IN ('completed','failed','unknown'))""")
        jobs=db.execute("""SELECT j.*,s.timeline_id,coalesce(json_extract(j.input,'$.observation_config'),s.config) AS config
            FROM observation_jobs j JOIN observations s ON s.run_id=j.run_id AND s.name=j.name WHERE j.status='pending' AND j.id=(
            SELECT min(p.id) FROM observation_jobs p WHERE p.generation=j.generation
            AND p.status IN ('pending','claimed','preparing','running','remote','unknown')) ORDER BY j.id""").fetchall()
        for job in jobs:db.execute("UPDATE observation_jobs SET status='claimed' WHERE id=?",(job['id'],))
        # All older changes have either been acknowledged or turned into durable work.
        cursor=db.execute("""SELECT min(n) FROM (SELECT min(cursor) n FROM observations UNION ALL
                 SELECT min(coalesce(json_extract(document,'$.cursor'),0)) FROM work_objects
                 WHERE kind='wait' AND json_extract(document,'$.state')='waiting')""").fetchone()[0]
        db.execute('DELETE FROM platform_events WHERE sequence<=?',(events.position(db) if cursor is None else cursor,))
    return jobs


def execute(engine,job):
    from loop_anything.paths import platform_skill_directory
    from loop_anything.runtime.host_runtime import CommandNotStopped
    from loop_anything.runtime.executors import run
    from loop_anything.runtime.work import transaction
    config=json.loads(job['config'])
    try:
        with transaction(engine.store) as db:
            claimed = db.execute("UPDATE observation_jobs SET status='preparing' WHERE id=? AND status='claimed'", (job['id'],))
            if not claimed.rowcount:
                return
            active = timelines.get(db, job['timeline_id']).get('active_run_id')
            if active and active != job['run_id']:
                db.execute('DELETE FROM observation_jobs WHERE id=?', (job['id'],))
                return
        checkpoint = json.loads(job['input'])
        first = checkpoint.get('step', 0)
        previous = checkpoint.get('previous')
        remaining = config['steps'][first:]
        facts = {k:v for k,v in checkpoint.items() if k in ('timeline','trigger','run_id','as_of')}
        facts['reason'] = job['reason']
        if first == 0 and not job['remote_call'] and 'condition' in config:
            with engine.store.connection() as db:
                matches = condition_matches(db,config['condition'],facts)
            if not matches:
                with transaction(engine.store) as db:
                    db.execute('DELETE FROM observation_jobs WHERE id=?',(job['id'],))
                return
        from loop_anything.runtime.executors import RemotePending
        for index,step in enumerate(remaining,first):
            with engine.store.connection() as db:
                if not db.execute('SELECT 1 FROM observation_jobs WHERE id=?',(job['id'],)).fetchone():return
            step=engine.implementation(dict(step))
            from loop_anything.runtime.agent_prompt import process_prompt
            # Business data crosses to an executor only through the author's step output.
            context = dict(run_id=job['run_id'], timeline_id=job['timeline_id'], loop_key=config['loop_key'],
                           platform_url=getattr(engine, 'platform_url', None), reason=job['reason'],
                           platform_client=str(platform_skill_directory()/'scripts/call.py'))
            if not step.get('executor'):
                context.update(facts)
            if previous is not None:
                context['previous'] = previous
            template = step.get('prompt', '{{context}}') if step['kind'] == 'agent' else None
            prompt = process_prompt(step, context, template)
            cwd=step.get('cwd') or config.get('package_root')
            if cwd and config.get('package_root') and not Path(cwd).is_absolute():cwd=str(Path(config['package_root'])/cwd)
            ident=f"observation-{job['id']}-{index}"
            meta={'kind':'observation','loop_key':config['loop_key'],'run_id':job['run_id'],'job_id':job['id'],'step':index}
            if step.get('executor'):
                # Persist the deterministic receipt before dispatch, including the crash window
                # between the executor accepting a call and this worker yielding its slot.
                with transaction(engine.store) as db:
                    if not db.execute('UPDATE observation_jobs SET remote_call=? WHERE id=?', (ident, job['id'])).rowcount:
                        return
                try:
                    process=run(engine,step,step['command'],prompt,step.get('timeout'),cwd,engine.stopping,
                                ident=ident,metadata=meta)
                except RemotePending:
                    with transaction(engine.store) as db:
                        db.execute("UPDATE observation_jobs SET status='remote',remote_call=? WHERE id=?",(ident,job['id']))
                    with engine.executors.lock:engine.executors.waiting.pop(ident,None)
                    return
            else:
                from loop_anything.runtime.host_runtime import run_command
                from loop_anything.runtime.process_session import ProcessSession
                session=ProcessSession(ident,step) if step['kind']=='agent' or step.get('terminal') else None
                def started(pid):
                    with transaction(engine.store) as db:
                        db.execute('UPDATE observation_jobs SET process_pid=? WHERE id=?',(pid,job['id']))
                if session:
                    session.changed=lambda doc:started(doc['pid']) if doc.get('pid') else None
                with transaction(engine.store) as db:
                    if not db.execute("UPDATE observation_jobs SET status='running' WHERE id=?", (job['id'],)).rowcount:
                        return
                process=run_command(step['command'],prompt,step.get('timeout'),cwd,engine.stopping,session,context,started=started,observation_as_of=facts.get('as_of'))
            if process.returncode:raise Invalid(process.stderr.strip() or 'Observation command failed')
            output=json.loads(process.stdout)
            if not isinstance(output,dict):raise Invalid('Observation must return a JSON object')
            previous=output
            with transaction(engine.store) as db:
                changed=db.execute("""UPDATE observation_jobs
                    SET status='preparing',input=json_set(input,'$.step',?,'$.previous',json(?)),process_pid=NULL,remote_call=NULL WHERE id=?""",
                    (index+1,encode(output),job['id'])).rowcount
            if step.get('executor'):
                engine.executors.applied(ident)
                with engine.executors.lock:engine.executors.waiting.pop(ident,None)
            if not changed:return
        output=previous
        validate_view(output)
        with transaction(engine.store) as db:
            if not db.execute('SELECT 1 FROM observation_jobs WHERE id=?',(job['id'],)).fetchone():return
            active=timelines.get(db,job['timeline_id']).get('active_run_id')
            if active and active!=job['run_id']:
                db.execute('DELETE FROM observation_jobs WHERE id=?',(job['id'],))
                return
            if db.execute('SELECT 1 FROM observations WHERE generation=?',(job['generation'],)).fetchone():
                view={'run_id':job['run_id'],'at':time.time(),'view':output}
                db.execute("""INSERT INTO observation_views VALUES(?,?,?,?) ON CONFLICT(timeline_id,name)
                    DO UPDATE SET job_id=excluded.job_id,document=excluded.document WHERE job_id<excluded.job_id""",
                    (job['timeline_id'],job['name'],job['id'],encode(view)))
            if job['reason'] in config.get('notify_on',[]) and output.get('notify',True):
                from loop_anything.runtime.notifications import enqueue
                with engine.store.edit(job['run_id'],_db=db) as current:
                    message=output.get('summary') or job['name']
                    base=config.get('web_url') or getattr(engine,'platform_url','')
                    from urllib.parse import urlsplit
                    if base and base.startswith(('https://','http://')) and urlsplit(base).hostname not in ('127.0.0.1','localhost','::1'):
                        message+='\n'+base.rstrip('/')+'/#work/timelines/'+job['timeline_id']
                    enqueue(engine.store,current,'observation:'+str(job['id']),{'message':message,'route':config.get('route','default')})
            if db.execute("SELECT 1 FROM observation_jobs WHERE run_id=? AND name=? AND status='failed' AND id<? LIMIT 1",
                          (job['run_id'],job['name'],job['id'])).fetchone():
                log_outcome(engine.store,db,job,'recovered')
            db.execute("DELETE FROM observation_jobs WHERE run_id=? AND name=? AND (id=? OR (status='failed' AND id<?))",
                       (job['run_id'],job['name'],job['id'],job['id']))
    except Exception as exc:
        with transaction(engine.store) as db:
            status='unknown' if isinstance(exc,CommandNotStopped) else 'failed'
            changed=db.execute('UPDATE observation_jobs SET status=?,error=?,input=NULL WHERE id=?',(status,str(exc),job['id']))
            if changed.rowcount:
                log_outcome(engine.store,db,job,status,str(exc))


def validate_view(view):
    if not isinstance(view.get('summary',''),str) or not isinstance(view.get('series',[]),list):
        raise Invalid('Return summary text and/or chart series')
    for line in view.get('series',[]):
        if not isinstance(line,dict) or not isinstance(line.get('label'),str) or not isinstance(line.get('points'),list):
            raise Invalid('Chart series need label and points')
        for point in line['points']:
            if not isinstance(point,list) or len(point)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point):
                raise Invalid('Chart points must be finite numeric [x,y] pairs')
    if 'notify' in view and type(view['notify']) is not bool:raise Invalid('notify must be a boolean')
    if 'image_png' in view:
        try:png=base64.b64decode(view['image_png'],validate=True)
        except (ValueError,TypeError) as exc:raise Invalid('image_png needs base64 PNG bytes') from exc
        if not png.startswith(b'\x89PNG\r\n\x1a\n'):raise Invalid('Expected a PNG observation image')
    if not any(view.get(k) for k in ('summary','series','image_png')):raise Invalid('Return a summary, series or image_png')
    encode(view)


def overview(db,timeline_id):
    views=[dict(name=r['name'],**json.loads(r['document'])) for r in db.execute(
        'SELECT name,document FROM observation_views WHERE timeline_id=? ORDER BY name',(timeline_id,))]
    arrangements=[]
    for row in db.execute("""SELECT s.* FROM observations s JOIN work_timelines t ON t.id=s.timeline_id
                    WHERE t.id=? AND json_extract(t.document,'$.active_run_id')=s.run_id ORDER BY s.name""",(timeline_id,)):
        config=json.loads(row['config'])
        job=db.execute("""SELECT status,error,process_pid,remote_call FROM observation_jobs WHERE run_id=? AND name=? ORDER BY
                       CASE status WHEN 'unknown' THEN 0 WHEN 'claimed' THEN 1 WHEN 'preparing' THEN 1 WHEN 'running' THEN 1 WHEN 'remote' THEN 1 WHEN 'pending' THEN 2 ELSE 3 END,id DESC LIMIT 1""",
                       (row['run_id'],row['name'])).fetchone()
        arrangements.append({'name':row['name'],'run_id':row['run_id'],'description':config.get('description',''),'on':config.get('on',{'kind':'result'}),
                             'next_at':row['due'],'status':job['status'] if job else 'idle','error':job['error'] if job else None,'pid':job['process_pid'] if job else None,'remote_call':job['remote_call'] if job else None})
    return {'views':views,'arrangements':arrangements}

def refresh(db,run,name,confirmed_stopped=False):
    from loop_anything.runtime.model import Conflict
    sub=db.execute('SELECT * FROM observations WHERE run_id=? AND name=?',(run['id'],name)).fetchone()
    if not sub:raise Invalid('Unknown observation')
    unknown = db.execute("SELECT process_pid,remote_call FROM observation_jobs WHERE run_id=? AND name=? AND status='unknown'",
                         (run['id'],name)).fetchall()
    for interrupted in unknown:
        from loop_anything.runtime.work import alive
        if not confirmed_stopped or alive(interrupted['process_pid']):
            raise Conflict('Inspect interrupted observation and confirm its process has stopped')
        if interrupted['remote_call']:
            job=db.execute('SELECT document FROM executor_calls WHERE id=?',(interrupted['remote_call'],)).fetchone()
            if job and not json.loads(job[0]).get('applied'):
                raise Conflict('Resolve the original executor receipt first')
    if unknown:
        db.execute("DELETE FROM observation_jobs WHERE run_id=? AND name=? AND status='unknown'",(run['id'],name))
    queue(db,sub,'manual')
    return {'queued':True,'run_id':run['id'],'timeline_id':run['timeline_id']}
