"""Run summaries and library management; execution state remains in Timeline."""
import json
import hashlib
import math
import os
import shutil
import time
from pathlib import Path
from loop_anything.runtime.model import Invalid, Conflict


def user_name(value):
    if not isinstance(value, str) or len(value) > 120 or any(ord(c) < 32 for c in value):
        raise Invalid('created_by must be a display name of at most 120 characters')
    return value.strip()


def meaningful_event(kind, detail=None):
    if kind in ('observation', 'monitor_skipped', 'stale_monitor_report', 'agent_acquired', 'agent_released'):
        return False
    if kind == 'transition' and isinstance(detail, dict):
        return detail.get('from') != detail.get('to') or detail.get('event') not in ('progress', 'check_error')
    return True


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS loop_library (key TEXT PRIMARY KEY, archived_at REAL)')
    # Headers contain all searchable metadata; never load Task/record bodies for a list.
    db.execute("""UPDATE runs SET document=json_set(document,'$.last_activity_at',
        coalesce((SELECT max(json_extract(p.document,'$.at')) FROM timeline_parts p
                  WHERE p.run_id=runs.id AND p.section='history'
                  AND json_extract(p.document,'$.kind') NOT IN
                    ('observation','monitor_skipped','stale_monitor_report','agent_acquired','agent_released')
                  AND NOT (json_extract(p.document,'$.kind')='transition'
                    AND json_extract(p.document,'$.detail.event') IN ('progress','check_error')
                    AND json_extract(p.document,'$.detail.from')=json_extract(p.document,'$.detail.to'))),
                 (SELECT max(json_extract(h.value,'$.at')) FROM json_each(runs.document,'$.history') h
                  WHERE json_extract(h.value,'$.kind') NOT IN
                    ('observation','monitor_skipped','stale_monitor_report','agent_acquired','agent_released')
                  AND NOT (json_extract(h.value,'$.kind')='transition'
                    AND json_extract(h.value,'$.detail.event') IN ('progress','check_error')
                    AND json_extract(h.value,'$.detail.from')=json_extract(h.value,'$.detail.to'))),
                 json_extract(document,'$.created_at'),0))
        WHERE json_type(document,'$.last_activity_at') IS NULL
          OR (json_extract(document,'$._storage') IS NOT 2
              AND json_extract(document,'$.last_activity_at')=json_extract(document,'$.created_at'))""")
    for name, fields in {
        'runs_activity': "json_extract(document,'$.last_activity_at') DESC, id",
        'runs_created': "json_extract(document,'$.created_at') DESC, id",
        'runs_author': "json_extract(document,'$.created_by'), json_extract(document,'$.last_activity_at') DESC, id",
        'runs_parent': "json_extract(document,'$.parent_call.run_id')",
        'runs_loop': "json_extract(document,'$.loop_key')",
    }.items():
        db.execute('CREATE INDEX IF NOT EXISTS '+name+' ON runs ('+fields+')')


def list_runs(store, query='', status='', created_by=None, loop_key='', loop_id='',
              created_from=None, created_to=None, active_from=None, active_to=None,
              sort='last_activity_at', order='desc', archived='exclude', parent_run_id=None,
              root_only=False, kind='', limit=50, offset=0):
    if sort not in ('created_at', 'last_activity_at') or order not in ('asc', 'desc'):
        raise Invalid('Sort by created_at or last_activity_at, with asc or desc order')
    if archived not in ('exclude', 'include', 'only'):
        raise Invalid('archived must be exclude, include or only')
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
        raise Invalid('limit must be 1..200 and offset must be nonnegative')
    if type(root_only) is not bool or kind not in ('', 'workflow', 'collaboration'):
        raise Invalid('Invalid root_only or kind')
    j = lambda key: "json_extract(r.document,'$."+key+"')"
    author = "coalesce("+j('created_by')+",'')"
    filters, args = [], []
    for key, value in [('status', status), ('loop_key', loop_key), ('parent_call.run_id', parent_run_id)]:
        if value is not None and value != '': filters.append(j(key)+'=?'); args.append(value)
    if loop_id: filters.append("json_extract(l.document,'$.id')=?"); args.append(loop_id)
    if created_by is not None: filters.append(author+'=?'); args.append(user_name(created_by))
    if root_only: filters.append(j('parent_call.run_id')+' IS NULL')
    if kind: filters.append(j('collaboration')+(' IS NOT NULL' if kind == 'collaboration' else ' IS NULL'))
    if archived != 'include': filters.append(j('archived_at')+(' IS NOT NULL' if archived == 'only' else ' IS NULL'))
    for field, value, op in [('created_at',created_from,'>='),('created_at',created_to,'<'),
                             ('last_activity_at',active_from,'>='),('last_activity_at',active_to,'<')]:
        if value is not None:
            if type(value) not in (int,float) or not math.isfinite(value):raise Invalid('Date bounds must be finite Unix timestamps')
            filters.append(j(field)+op+'?'); args.append(value)
    if query:
        if not isinstance(query,str):raise Invalid('query must be text')
        filters.append("instr(lower(r.id||' '||coalesce("+j('title')+",'')||' '||"+author+
                       "||' '||coalesce(json_extract(l.document,'$.name'),'')||' '||coalesce("+j('settings.objective')+",'')),lower(?))>0")
        args.append(query)
    base=' FROM runs r LEFT JOIN loop_definitions l ON l.key='+j('loop_key')
    where=' WHERE '+' AND '.join(filters) if filters else ''
    fields=['r.id AS id']+[j(k)+' AS '+k for k in ('title','status','loop_key','created_at','last_activity_at','archived_at','revision')]
    fields += [author+' AS created_by', "coalesce("+j('metadata_revision')+",0) AS metadata_revision",
               "json_extract(l.document,'$.name') AS loop_name", "json_extract(l.document,'$.id') AS loop_id",
               j('parent_call.run_id')+' AS parent_run_id', j('settings.objective')+' AS objective',
               "CASE WHEN "+j('collaboration')+" IS NULL THEN 'workflow' ELSE 'collaboration' END AS kind",
               "CASE WHEN "+j('_storage')+"=2 THEN (SELECT count(*) FROM timeline_parts p WHERE p.run_id=r.id AND p.section='attempts') ELSE coalesce(json_array_length(r.document,'$.executions'),0) END AS execution_count"]
    with store.connection() as db:
        db.execute('BEGIN')
        total=db.execute('SELECT count(*)'+base+where,args).fetchone()[0]
        groups=[dict(row) for row in db.execute('SELECT '+author+' AS created_by,count(*) AS count,max('+j('last_activity_at')+') AS last_activity_at'+base+where+' GROUP BY '+author+' ORDER BY last_activity_at DESC,created_by',args)]
        loops=[dict(row) for row in db.execute("SELECT json_extract(l.document,'$.id') AS loop_id,json_extract(l.document,'$.name') AS name,max("+j('created_at')+") AS created_at"+base+where+" GROUP BY json_extract(l.document,'$.id') ORDER BY name,loop_id",args)]
        rows=[dict(row) for row in db.execute('SELECT '+','.join(fields)+base+where+' ORDER BY '+j(sort)+' '+order+',r.id '+order+' LIMIT ? OFFSET ?',args+[limit,offset])]
        for row in rows:
            row['child_count']=db.execute("SELECT count(*) FROM runs WHERE json_extract(document,'$.parent_call.run_id')=?",(row['id'],)).fetchone()[0]
        return {'runs':rows,'total':total,'groups':groups,'loops':loops,'limit':limit,'offset':offset,
                'next_offset':offset+len(rows) if offset+len(rows)<total else None}


def update_run(store, run_id, metadata_revision, title=None, created_by=None, archived=None):
    if title is not None and (not isinstance(title,str) or not title.strip() or len(title)>500):
        raise Invalid('title must be nonempty text of at most 500 characters')
    if created_by is not None:created_by=user_name(created_by)
    if archived is not None and type(archived) is not bool:raise Invalid('archived must be boolean')
    with store.edit(run_id) as run:
        if type(metadata_revision) is not int or metadata_revision!=run.get('metadata_revision',0):
            raise Conflict('Run metadata changed; reload its summary')
        before=(run['title'],run.get('created_by',''),run.get('archived_at'))
        if title is not None:run['title']=title.strip()
        if created_by is not None:run['created_by']=created_by
        if archived is not None:run['archived_at']=(run.get('archived_at') or time.time()) if archived else None
        if before!=(run['title'],run.get('created_by',''),run.get('archived_at')):
            run['metadata_revision']=run.get('metadata_revision',0)+1
            store.log(run,'run_metadata','Run library information updated')
        result={k:run.get(k) for k in ('id','title','created_by','archived_at','last_activity_at','metadata_revision')}
    return result


def delete_run(store, run_id, metadata_revision):
    from loop_anything.runtime.task_scope import process_active
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        run=store._load(db,run_id)
        if type(metadata_revision) is not int or metadata_revision!=run.get('metadata_revision',0):
            raise Conflict('Run metadata changed; reload before deleting')
        if run['status'] not in ('completed','terminated') or any(process_active(e) for e in run['executions']):
            raise Conflict('End this Run and its active executions before deleting it')
        if db.execute("SELECT 1 FROM runs WHERE json_extract(document,'$.parent_call.run_id')=? LIMIT 1",(run_id,)).fetchone():
            raise Conflict('Delete or retain child Runs explicitly before deleting their parent')
        parent=run.get('parent_call',{}).get('run_id')
        if parent:
            row=db.execute('SELECT document FROM runs WHERE id=?',(parent,)).fetchone()
            if row and json.loads(row[0])['status'] not in ('completed','terminated'):
                raise Conflict('The parent Run still needs this child result')
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'execution_sessions' in tables and db.execute("SELECT 1 FROM execution_sessions WHERE run_id=? AND json_extract(document,'$.state') IN ('starting','running','interrupted') LIMIT 1",(run_id,)).fetchone():
            raise Conflict('Run still has an active or unconfirmed execution session')
        linked_ids=set()
        if 'communication_requests' in tables:
            from loop_anything.runtime.communication import END
            linked=[]
            for row in db.execute('SELECT id,document FROM communication_requests'):
                request=json.loads(row['document'])
                if any((request.get(field) or {}).get('run_id')==run_id for field in ('source','source_reference','collaboration')):
                    linked_ids.add(row['id'])
                    if request['state'] not in END:raise Conflict('Run still has an unfinished assistance request')
                    if request.get('collaboration',{}).get('run_id')==run_id:
                        request['collaboration']['deleted']=True;linked.append((json.dumps(request),row['id']))
            db.executemany('UPDATE communication_requests SET document=? WHERE id=?',linked)
        if 'executor_calls' in tables:
            for job in db.execute("SELECT json_extract(document,'$.metadata.run_id') AS run_id,json_extract(document,'$.metadata.request_id') AS request_id FROM executor_calls WHERE json_extract(document,'$.applied') IS NOT 1"):
                if job['run_id']==run_id or job['request_id'] in linked_ids:
                    raise Conflict('Wait for the remote execution receipt to be applied before deleting this Run')
        db.execute('DELETE FROM timeline_parts WHERE run_id=?',(run_id,))
        db.execute('DELETE FROM runs WHERE id=?',(run_id,))
        db.commit()
    return {'deleted':True,'run_id':run_id}


def pristine_package(root, document, digest):
    """Only remove an unchanged installation, never incidental outputs or user edits."""
    from loop_anything.packaging.packages import MAX_BYTES
    expected={'loop.json':digest,**{name:meta['sha256'] for name,meta in document['files'].items()}}
    expected_dirs={parent.as_posix() for name in expected for parent in Path(name).parents if str(parent)!='.'}
    found=set()
    for directory, dirs, files in os.walk(root,followlinks=False):
        if any((Path(directory)/name).is_symlink() or (Path(directory)/name).relative_to(root).as_posix() not in expected_dirs for name in dirs):return False
        for name in files:
            path=Path(directory)/name;relative=path.relative_to(root).as_posix()
            if relative not in expected or path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES:return False
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected[relative]:return False
            found.add(relative)
    return found==set(expected)


def manage_loop(store, key=None, draft_id=None, revision=None, archived=None, delete=False):
    if bool(key)==bool(draft_id):raise Invalid('Supply exactly one key or draft_id')
    ident=key or draft_id; root=None; digest=None; package_document=None
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        table,field=('loop_definitions','key') if key else ('loop_drafts','id')
        row=db.execute('SELECT * FROM '+table+' WHERE '+field+'=?',(ident,)).fetchone()
        if row is None:raise Invalid('Unknown Loop')
        if draft_id and (type(revision) is not int or revision!=row['revision']):raise Conflict('Draft changed; read it again')
        if delete:
            if key:
                if db.execute("SELECT 1 FROM runs WHERE json_extract(document,'$.loop_key')=? LIMIT 1",(key,)).fetchone():
                    raise Conflict('Runs still reference this Loop version; archive it to hide it while retaining history')
                from loop_anything.runtime.implementations import options
                def calls(implementations):
                    return any(candidate.get('kind')=='loop' and candidate['loop']['key']==key
                               for entry in implementations.values() for candidate in options(entry).values())
                for other in db.execute('SELECT key,implementations FROM loop_definitions'):
                    if other['key']!=key and calls(json.loads(other['implementations'])):raise Conflict('Another Loop calls this version')
                for other in db.execute('SELECT document FROM loop_drafts'):
                    if calls(json.loads(other[0]).get('implementations',{})):raise Conflict('A draft calls this Loop version')
                package=db.execute('SELECT root,digest,document FROM loop_packages WHERE key=?',(key,)).fetchone()
                if package:root,digest,package_document=Path(package['root']),package['digest'],json.loads(package['document'])
                db.execute('DELETE FROM loop_packages WHERE key=?',(key,))
            db.execute('DELETE FROM '+table+' WHERE '+field+'=?',(ident,))
            db.execute('DELETE FROM loop_library WHERE key=?',(ident,))
        else:
            if type(archived) is not bool:raise Invalid('archived must be boolean')
            db.execute('INSERT INTO loop_library VALUES (?,?) ON CONFLICT(key) DO UPDATE SET archived_at=excluded.archived_at',
                       (ident,time.time() if archived else None))
        db.commit()
    if delete and root and root.name==digest and not root.is_symlink() and root.parent.resolve()==(Path(store.filename).resolve().parent/'packages').resolve():
        # Serialize cleanup with reinstall; a newly restored package owns its files.
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM loop_packages WHERE key=?',(key,)).fetchone():
                try:
                    if pristine_package(root,package_document,digest):shutil.rmtree(root,ignore_errors=True)
                except OSError:pass  # Retain files when their ownership cannot be established.
            db.commit()
    retained=bool(delete and root and root.exists())
    return {'deleted':delete,'key':key,'draft_id':draft_id,
            **({'archived':archived} if not delete else {'package_files_retained':retained}),
            **({'retained_package_path':str(root)} if retained else {})}
