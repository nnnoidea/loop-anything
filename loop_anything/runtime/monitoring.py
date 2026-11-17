"""Read-only, compact monitoring overview. Never starts scripts or advances Runs."""
import json
import time
from loop_anything.runtime.model import Invalid
from loop_anything.runtime import work


def data_state(m, now):
    if m.get('error'):return 'error'
    if not m.get('sample'):return 'empty'
    if m.get('status')=='unknown':return 'unknown'
    if m.get('status')=='stopped':return 'stopped'
    if m.get('status')!='completed' and now-m['sample']['at']>m['interval']*2+m['script']['script'].get('timeout',60):
        return 'stale'
    return 'fresh'


def overview(store, offset=0, limit=20):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise Invalid('Invalid Run page')
    now=time.time()
    with store.connection() as db:
        db.execute('BEGIN')
        base=" FROM runs WHERE json_extract(document,'$.archived_at') IS NULL"
        counts={r[0]:r[1] for r in db.execute(
            "SELECT CASE WHEN json_extract(document,'$.superseded_by') IS NOT NULL THEN 'continued' ELSE json_extract(document,'$.status') END,count(*)"+base+" GROUP BY 1")}
        total=sum(counts.values())
        offset=min(offset,((max(total,1)-1)//limit)*limit)
        headers=db.execute("SELECT id,document"+base+
            " ORDER BY CASE WHEN json_extract(document,'$.status') IN ('running','paused') THEN 0 ELSE 1 END,"
            "coalesce(json_extract(document,'$.last_activity_at'),json_extract(document,'$.created_at')) DESC,id LIMIT ? OFFSET ?",(limit,offset)).fetchall()
        run_rows=[];external=[]
        for row in headers:
            run=json.loads(row[1])
            # Only current task states; do not deserialize records, prompts or execution archives.
            attention=db.execute("SELECT count(*) FROM timeline_parts WHERE run_id=? AND section='tasks' "
                "AND json_extract(document,'$.status') IN ('fault','stale','waiting_user')",(row[0],)).fetchone()[0]
            for observed in db.execute("""
                    SELECT t.item AS task_id,
                        json_extract(t.document,'$.spec.node') AS node,
                        json_extract(e.document,'$.status') AS status,
                        json_extract(e.document,'$.observation_error') AS error,
                        json_extract(e.document,'$.activity_progress.external_status') AS business_status
                    FROM timeline_parts t JOIN timeline_parts e ON e.run_id=t.run_id
                        AND e.section='attempts' AND e.item=json_extract(t.document,'$.execution_id')
                    WHERE t.run_id=? AND t.section='tasks'
                        AND json_extract(e.document,'$.implementation.kind')='external'
                    """,(row[0],)):
                external.append(dict(observed,run_id=row[0],run_title=run['title']))
            run_rows.append(dict(id=row[0],title=run['title'],status=run['status'],attention_count=attention,
                                 timeline_id=run.get('timeline_id'),superseded_by=run.get('superseded_by'),
                                 last_activity_at=run.get('last_activity_at',run.get('created_at'))))
        monitors=[]
        for m in work.rows(db,'monitor'):
            script=m['script']['script']
            monitors.append(dict(id=m['id'],name=script.get('description') or m['script'].get('id') or m['id'],
                run_id=m.get('run_id'),script_id=m['script'].get('id'),script_revision=m['script'].get('revision'),
                status=m['status'],data_state=data_state(m,now),interval=m['interval'],
                sample=m.get('sample'),error=m.get('error'),parameters=m.get('parameters',{}),
                metrics=script.get('metrics',[])))
        waits=[{k:w.get(k) for k in ('id','timeline_id','sources','condition','message','state','error','triggered_at')}
               for w in work.rows(db,'wait') if w['state'] in ('waiting','ready')]
        scripts=[dict(id=s['id'],revision=s['revision'],description=s['script'].get('description',''),
                      parameter_schema=s['script'].get('parameter_schema',{}),
                      instances=sum(m.get('script_id')==s['id'] for m in monitors))
                 for s in work.rows(db,'monitor_script')]
        return dict(at=now,counts=counts,runs=run_rows,total_runs=total,offset=offset,limit=limit,
                    monitors=monitors,external=external,waits=waits,scripts=scripts)


def history(store, monitor_id, limit=120):
    if type(limit) is not int or not 1<=limit<=240:raise Invalid('History limit must be 1..240')
    with store.connection() as db:
        work.get(db,'monitor',monitor_id)
        samples=[json.loads(r[0]) for r in db.execute(
            'SELECT document FROM monitor_samples WHERE monitor_id=? ORDER BY sequence DESC LIMIT ?',(monitor_id,limit))]
        return {'monitor_id':monitor_id,'samples':list(reversed(samples)),'retention':240}


def record_sample(db, monitor_id, call_id, data, error):
    sample={'at':time.time(),'data':data,'error':error,'call_id':call_id}
    db.execute('INSERT OR IGNORE INTO monitor_samples(monitor_id,call_id,document) VALUES (?,?,?)',
               (monitor_id,call_id,json.dumps(sample,ensure_ascii=False)))
    db.execute('DELETE FROM monitor_samples WHERE monitor_id=? AND sequence NOT IN '
               '(SELECT sequence FROM monitor_samples WHERE monitor_id=? ORDER BY sequence DESC LIMIT 240)',
               (monitor_id,monitor_id))
