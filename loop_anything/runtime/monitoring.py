"""Read-only, compact monitoring overview. Never starts scripts or advances Runs."""
import json
import time
from loop_anything.runtime.model import Invalid, path
from loop_anything.runtime import work


RUN_STATUS = "CASE WHEN json_extract(document,'$.superseded_by') IS NOT NULL THEN 'continued' ELSE json_extract(document,'$.status') END"
RUN_GROUPS = {
    'active': "('running','paused')",
    'finished': "('completed','terminated','continued')",
}
VISIBLE_RUNS = " FROM runs WHERE json_extract(document,'$.archived_at') IS NULL"
RUN_ACTIVITY = "coalesce(json_extract(document,'$.last_activity_at'),json_extract(document,'$.created_at'))"
RUN_HEADER = """SELECT id,json_extract(document,'$.title') AS title,
    json_extract(document,'$.status') AS status,json_extract(document,'$.timeline_id') AS timeline_id,
    json_extract(document,'$.superseded_by') AS superseded_by,"""+RUN_ACTIVITY+" AS last_activity_at"
ATTENTION_COUNT = """(SELECT count(*) FROM timeline_parts WHERE run_id=runs.id AND section='tasks'
    AND json_extract(timeline_parts.document,'$.status') IN ('fault','stale','waiting_user')) AS attention_count"""


def data_state(m, now):
    if m.get('error'):return 'error'
    if not m.get('sample'):return 'empty'
    if m.get('status')=='unknown':return 'unknown'
    if m.get('status')=='stopped':return 'stopped'
    if m.get('status')!='completed' and now-m['sample']['at']>m['interval']*2+m['script']['script'].get('timeout',60):
        return 'stale'
    return 'fresh'


def run_charts(db, run):
    charts=[]
    for chart in db.execute("""
            SELECT v.name,json_extract(v.document,'$.at') AS at,
                   json_extract(v.document,'$.view.summary') AS summary,
                   json_extract(v.document,'$.view.series') AS series
            FROM run_chart_views v WHERE v.run_id=?
            ORDER BY v.name
            """,(run['id'],)):
        series=[line for line in json.loads(chart['series']) if line['points']]
        if series:
            charts.append(dict(run_id=run['id'],run_title=run['title'],timeline_id=run['timeline_id'],
                               name=chart['name'],at=chart['at'],summary=chart['summary'],series=series))
    return charts


def charts_for_run(store, run_id):
    with store.connection() as db:
        db.execute('BEGIN')
        run=db.execute(RUN_HEADER+" FROM runs WHERE id=?",(run_id,)).fetchone()
        if run is None:
            raise Invalid('Unknown Run')
        return run_charts(db,run)


def workbench_runs(store):
    active=VISIBLE_RUNS+" AND ("+RUN_STATUS+") IN "+RUN_GROUPS['active']
    finished=VISIBLE_RUNS+" AND ("+RUN_STATUS+") IN "+RUN_GROUPS['finished']
    with store.connection() as db:
        db.execute('BEGIN')
        header=RUN_HEADER+','+ATTENTION_COUNT
        total=db.execute("SELECT count(*)"+active).fetchone()[0]
        current=[dict(r) for r in db.execute(header+active+" ORDER BY last_activity_at DESC,id LIMIT 5")]
        attention=[dict(r) for r in db.execute(header+active+
            " AND attention_count>0 ORDER BY last_activity_at DESC,id LIMIT 4")]
        recent=[dict(r) for r in db.execute(RUN_HEADER+finished+" ORDER BY last_activity_at DESC,id LIMIT 4")]
        return dict(active=current,active_total=total,attention=attention,recent=recent)


def overview(store, offset=0, limit=20, run_group='', charts_only=False, include_charts=True, dashboard_only=False):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise Invalid('Invalid Run page')
    if run_group not in ('','active','finished'):
        raise Invalid('Invalid Run monitoring group')
    if any(type(flag) is not bool for flag in (charts_only,include_charts,dashboard_only)):
        raise Invalid('Invalid monitoring projection')
    now=time.time()
    with store.connection() as db:
        db.execute('BEGIN')
        base=VISIBLE_RUNS
        if run_group:
            base+=" AND ("+RUN_STATUS+") IN "+RUN_GROUPS[run_group]
        if charts_only:
            base+=" AND EXISTS (SELECT 1 FROM run_chart_views v WHERE v.run_id=runs.id)"
        counts={} if charts_only else {r[0]:r[1] for r in db.execute(
            "SELECT "+RUN_STATUS+",count(*)"+VISIBLE_RUNS+" GROUP BY 1")}
        total=db.execute('SELECT count(*)'+base).fetchone()[0] if run_group or charts_only else sum(counts.values())
        offset=min(offset,((max(total,1)-1)//limit)*limit)
        header=RUN_HEADER if charts_only else RUN_HEADER+','+ATTENTION_COUNT
        headers=db.execute(header+base+
            " ORDER BY CASE WHEN ("+RUN_STATUS+") IN "+RUN_GROUPS['active']+" THEN 0 ELSE 1 END,"
            "last_activity_at DESC,id LIMIT ? OFFSET ?",(limit,offset)).fetchall()
        run_rows=[];external=[];result_charts=[]
        for run in headers:
            if charts_only or include_charts:
                result_charts.extend(run_charts(db,run))
            if charts_only:
                run_rows.append({k:run[k] for k in ('id','status','superseded_by')})
                continue
            run_rows.append(dict(run))
            if dashboard_only:
                continue
            for observed in db.execute("""
                    SELECT t.item AS task_id,
                        json_extract(t.document,'$.spec.node') AS node,
                        json_extract(e.document,'$.status') AS status,
                        json_extract(e.document,'$.observation_error') AS error,
                        coalesce(json_extract(r.document,'$.retained_nodes.'||json_quote(json_extract(t.document,'$.spec.node'))||'.node.label'),
                                 json_extract(l.document,'$.nodes.'||json_quote(json_extract(t.document,'$.spec.node'))||'.label')) AS label,
                        coalesce(json_extract(r.document,'$.retained_nodes.'||json_quote(json_extract(t.document,'$.spec.node'))||'.node.readout'),
                                 json_extract(l.document,'$.nodes.'||json_quote(json_extract(t.document,'$.spec.node'))||'.readout')) AS readout,
                        json_extract(t.document,'$.spec.round') AS round,
                        json_extract(t.document,'$.spec.ref') AS ref,
                        json_extract(e.document,'$.external_id') AS external_id,
                        json_extract(e.document,'$.activity_progress') AS reading,
                        json_extract(e.document,'$.activity_progress_at') AS sampled_at,
                        json_extract(e.document,'$.started_at') AS started_at,
                        json_extract(e.document,'$.completed_at') AS completed_at
                    FROM timeline_parts t JOIN timeline_parts e ON e.run_id=t.run_id
                        AND e.section='attempts' AND e.item=json_extract(t.document,'$.execution_id')
                    JOIN runs r ON r.id=t.run_id
                    LEFT JOIN loop_definitions l ON l.key=json_extract(r.document,'$.loop_key')
                    WHERE t.run_id=? AND t.section='tasks'
                        AND json_extract(e.document,'$.implementation.kind')='external'
                    """,(run['id'],)):
                item=dict(observed,run_id=run['id'],run_title=run['title'])
                reading=json.loads(item.pop('reading') or '{}')
                item['readout']=json.loads(item['readout'] or '[]')
                item.update(business_status=reading.get('external_status'),phase=reading.get('phase'),
                            progress=reading.get('progress'),metrics=reading.get('metrics'))
                external.append(item)
        if charts_only:
            return dict(result_charts=result_charts,runs=run_rows,total_runs=total,offset=offset,limit=limit)
        monitors=[]
        for m in work.rows(db,'monitor'):
            visible=m.get('show_on_dashboard') is True
            if dashboard_only and not visible:
                continue
            script=m['script']['script']
            monitors.append(dict(id=m['id'],name=script.get('description') or m['script'].get('id') or m['id'],
                run_id=m.get('run_id'),script_id=m['script'].get('id'),script_revision=m['script'].get('revision'),
                status=m['status'],data_state=data_state(m,now),interval=m['interval'],
                sample=m.get('sample'),error=m.get('error'),parameters=m.get('parameters',{}),
                display=script.get('display'),metrics=script.get('metrics',[]),show_on_dashboard=visible))
        waits=[] if dashboard_only else [
            {k:w.get(k) for k in ('id','timeline_id','sources','condition','message','state','error','triggered_at')}
            for w in work.rows(db,'wait') if w['state'] in ('waiting','ready')]
        instance_counts={}
        for m in monitors:
            script_id=m['script_id']
            instance_counts[script_id]=instance_counts.get(script_id,0)+1
        scripts=[dict(id=s['id'],revision=s['revision'],description=s['script'].get('description',''),
                      parameter_schema=s['script'].get('parameter_schema',{}),
                      instances=instance_counts.get(s['id'],0))
                 for s in work.rows(db,'monitor_script') if not dashboard_only or s['id'] in instance_counts]
        return dict(at=now,counts=counts,runs=run_rows,total_runs=total,offset=offset,limit=limit,
                    monitors=monitors,external=external,result_charts=result_charts,waits=waits,scripts=scripts)


def history(store, monitor_id, limit=120, metric=None):
    if type(limit) is not int or not 1<=limit<=240:raise Invalid('History limit must be 1..240')
    with store.connection() as db:
        work.get(db,'monitor',monitor_id)
        samples=[json.loads(r[0]) for r in db.execute(
            'SELECT document FROM monitor_samples WHERE monitor_id=? ORDER BY sequence DESC LIMIT ?',(monitor_id,limit))]
        samples.reverse()
        if metric is not None:
            points = []
            for sample in samples:
                try:
                    value = path(sample['data'], metric) if not sample['error'] else None
                except (TypeError, KeyError, ValueError, IndexError):
                    value = None
                points.append({'at': sample['at'], 'value': value if type(value) in (float, int) else None})
            return {'monitor_id': monitor_id, 'metric': metric, 'points': points}
        return {'monitor_id':monitor_id,'samples':samples,'retention':240}


def record_sample(db, monitor_id, call_id, data, error):
    sample={'at':time.time(),'data':data,'error':error,'call_id':call_id}
    db.execute('INSERT OR IGNORE INTO monitor_samples(monitor_id,call_id,document) VALUES (?,?,?)',
               (monitor_id,call_id,json.dumps(sample,ensure_ascii=False)))
    db.execute('DELETE FROM monitor_samples WHERE monitor_id=? AND sequence NOT IN '
               '(SELECT sequence FROM monitor_samples WHERE monitor_id=? ORDER BY sequence DESC LIMIT 240)',
               (monitor_id,monitor_id))
