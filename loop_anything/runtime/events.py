"""Committed platform facts. Directed inputs for waiting Tasks remain in their Run."""
import json


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS platform_events(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            timeline_id TEXT, run_id TEXT, subject TEXT, detail TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS timeline_event ON platform_events(timeline_id,sequence);
        CREATE INDEX IF NOT EXISTS subject_event ON platform_events(subject,sequence);
        CREATE TRIGGER IF NOT EXISTS run_event_created AFTER INSERT ON runs BEGIN
            INSERT INTO platform_events(kind,timeline_id,run_id,subject,detail)
            VALUES('run',json_extract(new.document,'$.timeline_id'),new.id,new.id,
                   json_object('status',json_extract(new.document,'$.status')));
        END;
        CREATE TRIGGER IF NOT EXISTS run_event_changed AFTER UPDATE ON runs
        WHEN json_extract(new.document,'$.revision') IS NOT json_extract(old.document,'$.revision')
          OR json_extract(new.document,'$.status') IS NOT json_extract(old.document,'$.status') BEGIN
            INSERT INTO platform_events(kind,timeline_id,run_id,subject,detail)
            VALUES(CASE WHEN json_extract(new.document,'$.status') IS json_extract(old.document,'$.status') THEN 'run_revision' ELSE 'run' END,
                   json_extract(new.document,'$.timeline_id'),new.id,new.id,
                   json_object('status',json_extract(new.document,'$.status'),'previous',json_extract(old.document,'$.status')));
        END;
        CREATE TRIGGER IF NOT EXISTS run_event_deleted AFTER DELETE ON runs BEGIN
            INSERT INTO platform_events(kind,timeline_id,run_id,subject,detail)
            VALUES('run_deleted',json_extract(old.document,'$.timeline_id'),old.id,old.id,'{}');
        END;
        CREATE TRIGGER IF NOT EXISTS timeline_run_changed AFTER UPDATE ON work_timelines
        WHEN json_extract(new.document,'$.active_run_id') IS NOT json_extract(old.document,'$.active_run_id') BEGIN
            INSERT INTO platform_events(kind,timeline_id,run_id,subject,detail)
            VALUES('current_run',new.id,json_extract(new.document,'$.active_run_id'),new.id,'{}');
        END;
        CREATE TRIGGER IF NOT EXISTS monitor_event_insert AFTER INSERT ON work_objects WHEN new.kind='monitor' BEGIN
            INSERT INTO platform_events(kind,timeline_id,run_id,subject,detail)
            SELECT 'monitor',(SELECT json_extract(document,'$.timeline_id') FROM runs WHERE id=json_extract(new.document,'$.run_id')),
                   json_extract(new.document,'$.run_id'),new.id,json_object('status',json_extract(new.document,'$.status'));
        END;
        CREATE TRIGGER IF NOT EXISTS monitor_event_update AFTER UPDATE ON work_objects WHEN new.kind='monitor' AND (
            json_extract(new.document,'$.sample') IS NOT json_extract(old.document,'$.sample') OR
            json_extract(new.document,'$.error') IS NOT json_extract(old.document,'$.error') OR
            json_extract(new.document,'$.status') IS NOT json_extract(old.document,'$.status')) BEGIN
            INSERT INTO platform_events(kind,timeline_id,run_id,subject,detail)
            SELECT 'monitor',(SELECT json_extract(document,'$.timeline_id') FROM runs WHERE id=json_extract(new.document,'$.run_id')),
                   json_extract(new.document,'$.run_id'),new.id,json_object('status',json_extract(new.document,'$.status'),
                   'sample',json_extract(new.document,'$.sample'),'error',json_extract(new.document,'$.error'));
        END;
    """)


def emit(db,kind,timeline_id,run_id,subject,detail):
    db.execute('INSERT INTO platform_events(kind,timeline_id,run_id,subject,detail) VALUES(?,?,?,?,?)',
               (kind,timeline_id,run_id,subject,json.dumps(detail,ensure_ascii=False)))


def position(db):
    row=db.execute("SELECT seq FROM sqlite_sequence WHERE name='platform_events'").fetchone()
    return row[0] if row else 0


def wait_changed(db,wait,since):
    for alias,source in wait['sources'].items():
        kind,ident=source['kind'],source['id']
        if kind=='monitor':
            where="kind='monitor' AND subject=?"
            args=[ident]
        elif kind=='task':
            where="run_id=? AND ((kind='task' AND subject=?) OR kind='run_deleted')"
            args=[ident,source.get('task_id')]
        else:
            retained=wait.get('retained_sources',{}).get(alias,{})
            where="""(run_id=? OR timeline_id=coalesce(?,
                (SELECT json_extract(document,'$.timeline_id') FROM runs WHERE id=?)))
                AND kind IN ('run','run_revision','current_run','result','run_deleted')"""
            args=[ident,retained.get('timeline_id'),ident]
        if db.execute('SELECT 1 FROM platform_events WHERE sequence>? AND '+where+' LIMIT 1',[since,*args]).fetchone():
            return True
    return False
