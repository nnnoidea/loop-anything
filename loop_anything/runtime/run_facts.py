"""Read compact execution evidence for caller-selected Runs."""
import json
from collections import defaultdict
from statistics import median

from loop_anything.runtime.model import Invalid


def wall_seconds(intervals):
    """Elapsed time covered by measured attempts. Overlapping work counts once."""
    seconds, end = 0, 0
    for start, stop in sorted(intervals):
        seconds += max(0, stop - max(start, end))
        end = max(stop, end)
    return round(seconds, 2)


def read_attempt(store, run_id, execution_id):
    # The attempt PK resolves retries without opening the full Run or its command/prompt.
    fields=('task_id','node','attempt','status','created_at','started_at','completed_at','implementation_id',
            'error','observation_error','sources','record_refs','activity_progress','activity_progress_at')
    columns=','.join(f"json_extract(document,'$.{key}') AS {key}" for key in fields)
    with store.connection() as db:
        row=db.execute(f"SELECT {columns},json_extract(document,'$.implementation.kind') AS kind FROM timeline_parts WHERE run_id=? AND section='attempts' AND item=?",
                       (run_id,execution_id)).fetchone()
    if row is None:
        raise Invalid('Unknown execution in this Run')
    result=dict(row,run_id=run_id,execution_id=execution_id)
    for key in ('sources','record_refs','activity_progress'):
        if result[key] is not None:
            result[key]=json.loads(result[key])
    return result


def fields(*names):
    return {name: "json_extract(p.document,'$."+name+"')" for name in names}


# Each source exposes the facts it actually records. Filters and groupings use
# these same names, so a group can be opened with precisely the same selection.
PARTS = {
    'attempts': dict(fields('status','attempt','started_at','created_at','error','observation_error','task_id'),
                     execution_id='p.item', kind="json_extract(p.document,'$.implementation.kind')",
                     task_status="json_extract(t.document,'$.status')",
                     finished_at="coalesce(json_extract(p.document,'$.completed_at'),times.failed_at)",
                     submitted_at='times.submitted_at'),
    'tasks': dict(fields('status','budget_error'), task_id='p.item',
                  execution_id="json_extract(p.document,'$.execution_id')"),
    'history': dict(fields('kind','message','at'), execution_id="json_extract(p.document,'$.execution')",
                    event="json_extract(p.document,'$.detail.event')",
                    status="json_extract(p.document,'$.detail.to')",
                    subject="json_extract(p.document,'$.detail.name')",
                    reason="""coalesce(json_extract(p.document,'$.detail.detail.message'),
                        json_extract(p.document,'$.detail.error'))""",
                    diagnostic_snapshot="CASE WHEN json_extract(p.document,'$.kind')='diagnostics' THEN json_extract(p.document,'$.detail') END",
                    task_id="coalesce(json_extract(a.document,'$.task_id'),json_extract(p.document,'$.detail.task_id'))"),
    'notifications': dict(fields('status','error','task_id','execution_id')),
}
RUN_STATUS = "CASE WHEN json_extract(r.document,'$.superseded_by') IS NOT NULL THEN 'continued' ELSE json_extract(r.document,'$.status') END"


def projection(source):
    columns = dict(run_id='r.id', version="json_extract(l.document,'$.version')")
    joins = ''
    condition = ''
    if source == 'runs':
        columns.update(fact_id='r.id', status=RUN_STATUS, error="json_extract(r.document,'$.attention_error')",
                       created_at="json_extract(r.document,'$.created_at')")
    elif source == 'diagnostics':
        joins = "JOIN json_each(r.document,'$.diagnostics') d"
        columns.update(fact_id='CAST(d.key AS TEXT)', kind="json_extract(d.value,'$.kind')",
                       task_id="json_extract(d.value,'$.tasks')", detail='d.value')
    elif source == 'observations':
        joins = """JOIN (
            SELECT run_id,id,name,status,error,NULL AS at,NULL AS summary FROM observation_jobs
              WHERE run_id IN (SELECT value FROM json_each(:ids))
            UNION ALL SELECT json_extract(document,'$.run_id'),job_id,name,'completed',NULL,
              json_extract(document,'$.at'),json_extract(document,'$.view.summary') FROM observation_views
              WHERE json_extract(document,'$.run_id') IN (SELECT value FROM json_each(:ids))
        ) j ON j.run_id=r.id"""
        columns.update(fact_id='CAST(j.id AS TEXT)', subject='j.name', status='j.status',
                       reason='j.error', at='j.at', summary='j.summary')
    else:
        joins = "JOIN timeline_parts p ON p.run_id=r.id AND p.section='"+source+"'"
        columns.update(fact_id='p.item', **PARTS[source])
        if source == 'history':
            joins += """ LEFT JOIN timeline_parts a ON a.run_id=r.id AND a.section='attempts'
                         AND a.item=json_extract(p.document,'$.execution')"""
        if source in ('attempts','tasks','history'):
            node = {'attempts':"json_extract(p.document,'$.node')",'tasks':"json_extract(p.document,'$.spec.node')",
                    'history':"json_extract(a.document,'$.node')"}[source]
            retained = "json_extract(r.document,'$.retained_nodes.'||json_quote("+node+")"
            columns['node'] = "coalesce("+retained+"||'.node_id'),"+node+")"
            joins += " LEFT JOIN loop_definitions prior ON prior.key="+retained+"||'.loop_key')"
            columns['label'] = ("coalesce("+retained+"||'.node.label'),"
                                "json_extract(l.document,'$.nodes.'||json_quote("+node+")||'.label'),"+node+")")
            columns['version'] = "coalesce(json_extract(prior.document,'$.version'),json_extract(l.document,'$.version'))"
        if source == 'attempts':
            joins += """ LEFT JOIN timeline_parts t ON t.run_id=r.id AND t.section='tasks'
                         AND t.item=json_extract(p.document,'$.task_id')
                         LEFT JOIN times ON times.run_id=r.id AND times.execution_id=p.item"""
            condition = " AND json_type(p.document,'$.continuation_record_refs') IS NULL"
    sql = 'SELECT '+','.join(expr+' AS '+name for name,expr in columns.items())
    sql += " FROM runs r JOIN loop_definitions l ON l.key=json_extract(r.document,'$.loop_key') "+joins
    sql += ' WHERE r.id IN (SELECT value FROM json_each(:ids))'+condition
    return columns, sql


# Transitions contain the external submission and the end of failed attempts.
# Select only the requested Runs, including failures which later recovered.
TIMES = """times AS (
    SELECT run_id,json_extract(document,'$.execution') AS execution_id,
      min(CASE WHEN json_extract(document,'$.detail.event')='submitted'
               AND json_extract(document,'$.detail.accepted')=1
               AND json_extract(document,'$.detail.to') NOT IN ('fault','retry','agent')
               THEN json_extract(document,'$.at') END) AS submitted_at,
      min(CASE WHEN json_extract(document,'$.detail.to') IN ('fault','retry','agent')
                 OR json_extract(document,'$.detail.accepted')=0 THEN json_extract(document,'$.at') END) AS failed_at
    FROM timeline_parts WHERE section='history' AND run_id IN (SELECT value FROM json_each(:ids))
      AND json_extract(document,'$.kind')='transition' GROUP BY run_id,execution_id), """


class Median:
    def __init__(self):
        self.values = []

    def step(self, value):
        if value is not None:
            self.values.append(value)

    def finalize(self):
        return round(median(self.values), 2) if self.values else None


class RunWallTime:
    def __init__(self):
        self.spans = defaultdict(list)

    def step(self, run_id, start, stop):
        if start is not None and stop is not None and stop >= start:
            self.spans[run_id].append((start, stop))

    def finalize(self):
        if self.spans:
            return round(median(wall_seconds(spans) for spans in self.spans.values()), 2)


def query(store, run_ids, source, filters=None, group_by=None, order_by=None, descending=False, offset=0, limit=100):
    columns, sql = projection(source)
    params = dict(ids=json.dumps(run_ids), offset=offset, limit=limit+1)
    conditions = []
    for i, (field, value) in enumerate((filters or {}).items()):
        if field not in columns or isinstance(value, (list, dict)):
            raise Invalid('Filter by a scalar field from '+source+': '+', '.join(columns))
        param = 'f'+str(i)
        conditions.append(field+' IS :'+param)
        params[param] = value
    prefix = 'WITH '+(TIMES if source == 'attempts' else '')+'facts AS ('+sql+') '
    where = ' WHERE '+' AND '.join(conditions) if conditions else ''
    if group_by is None:
        select = 'SELECT * FROM facts'+where
        sortable = columns
        default_order = 'run_id,fact_id'
    else:
        if any(field not in columns for field in group_by):
            raise Invalid('Group by fields from '+source+': '+', '.join(columns))
        keys = ','.join(dict.fromkeys(group_by))
        measures = ['count(*) AS count','count(DISTINCT run_id) AS run_count']
        if source == 'attempts':
            duration = 'CASE WHEN finished_at>=started_at THEN finished_at-started_at END'
            measures += ['count('+duration+') AS measured','median('+duration+') AS median_seconds',
                         'max('+duration+') AS max_seconds','count(CASE WHEN attempt>1 THEN 1 END) AS retries',
                         'median(CASE WHEN finished_at>=submitted_at THEN finished_at-submitted_at END) AS median_external_seconds',
                         'run_wall(run_id,started_at,finished_at) AS median_run_wall_seconds']
        select = 'SELECT '+(keys+',' if keys else '')+','.join(measures)+' FROM facts'+where
        if keys:
            select += ' GROUP BY '+keys
        sortable = list(group_by)+[m.rsplit(' AS ',1)[1] for m in measures]
        default_order = 'count DESC'+(','+keys if keys else '')
    if order_by is not None and order_by not in sortable:
        raise Invalid('Order by a returned field: '+', '.join(sortable))
    order = order_by+(' DESC' if descending else ' ASC')+',' if order_by else ''
    select += ' ORDER BY '+order+default_order
    with store.connection() as db:
        db.execute('BEGIN')
        db.create_aggregate('median',1,Median)
        db.create_aggregate('run_wall',3,RunWallTime)
        found = {r[0] for r in db.execute('SELECT id FROM runs WHERE id IN (SELECT value FROM json_each(:ids))',params)}
        rows = [dict(row) for row in db.execute(prefix+select+' LIMIT :limit OFFSET :offset',params)]
    if group_by is None:
        for row in rows:
            for key in ('detail','diagnostic_snapshot'):
                if row.get(key) is not None:
                    row[key] = json.loads(row[key])
    return dict(source=source, fields=list(columns), items=rows[:limit],
                next_offset=offset+limit if len(rows)>limit else None, missing_run_ids=sorted(set(run_ids)-found))
