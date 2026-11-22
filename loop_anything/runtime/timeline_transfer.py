"""Portable progress and evidence. Imported work is data, never runnable authority."""
import copy
import json
import time
import sqlite3

from loop_anything.runtime import timelines, business_state
from loop_anything.runtime.model import Invalid, Conflict, digest

MAX_BYTES = 20 * 1024 * 1024
FORMAT = 'loop-anything-timeline'
STATE_FIELDS = ('type','id','revision','value','refs','run_id','task_id','execution_id','at','intent_revision')
RESULT_FIELDS = ('id','revision','type','value','summary','producer','tasks','source_run_id','at','sources')
ENTRY_FIELDS = ('key','sequence','text','kind','refs','actor','at')
NOTICE = '已导入任务进度。请让 Agent 读取目标、限制和当前状态，使用本平台的相关 Loop 继续。原平台的进程和执行权限未迁移，外部文件仍需可访问。'


def pick(value, fields):
    return {k:copy.deepcopy(value[k]) for k in fields if k in value}


def encode(document):
    data=json.dumps(document,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(data)>MAX_BYTES:raise Invalid('Timeline 文件超过 20 MiB')
    return data


def export_timeline(store, timeline_id):
    with store.connection() as db:
        db.execute('BEGIN')
        timeline=timelines.get(db,timeline_id)
        source={'timeline_id':timeline_id,'exported_at':time.time()}
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='communication_settings'").fetchone():
            identity=db.execute('SELECT document FROM communication_settings WHERE id=1').fetchone()
            if identity:source['workspace_id']=json.loads(identity[0])['instance_id']
        entries=[pick(json.loads(r[0]),ENTRY_FIELDS) for r in db.execute('SELECT document FROM work_entries WHERE timeline_id=? ORDER BY sequence',(timeline_id,))]
        state=[pick(json.loads(r[0]),STATE_FIELDS) for r in db.execute('SELECT document FROM work_state WHERE timeline_id=? ORDER BY type,id,revision',(timeline_id,))]
        results=[pick(json.loads(r[0]),RESULT_FIELDS) for r in db.execute('SELECT document FROM work_results WHERE timeline_id=? ORDER BY id,revision',(timeline_id,))]
        current=db.execute("SELECT l.document FROM runs r JOIN loop_definitions l ON l.key=json_extract(r.document,'$.loop_key') WHERE r.id=?",(timeline.get('active_run_id'),)).fetchone()
        definition=(json.loads(current[0]).get('state') if current else None) or timeline.get('state_definition')
        document={'format':FORMAT,'source':source,
                  'timeline':pick(timeline,('title','objective','constraints','revision','created_at')),
                  'entries':entries,'state':state,'results':results,'state_definition':definition}
        if timeline.get('import_source'):document['source']['previous']=copy.deepcopy(timeline['import_source'])
    encode(document)
    return {'filename':timeline_id+'.timeline.json','document':document}


def _rows(document, field, required):
    rows=document.get(field)
    if not isinstance(rows,list):raise Invalid('Timeline 文件缺少 '+field+' 记录列表')
    for row in rows:
        if not isinstance(row,dict) or not required<=row.keys():raise Invalid('Timeline '+field+' 记录不完整')
    return rows


def import_timeline(store, document, request_id):
    """One transaction; retries reuse the new local identity without merging old work."""
    if not isinstance(document,dict) or document.get('format')!=FORMAT:raise Invalid('请选择 Timeline 进度文件（.timeline.json）')
    encode(document)
    fingerprint=digest(document)
    intent=document.get('timeline')
    if not isinstance(intent,dict) or any(not isinstance(intent.get(k),str) for k in ('title','objective','constraints')):
        raise Invalid('Timeline 文件需要标题、目标和限制')
    revision=intent.get('revision',1)
    if type(revision) is not int or revision<1:raise Invalid('Timeline 目标版本无效')
    entries=_rows(document,'entries',{'key','text','kind','sequence'})
    state=_rows(document,'state',{'type','id','revision','value'})
    results=_rows(document,'results',{'id','revision','type','value'})
    definition=document.get('state_definition')
    business_state.validate_definition(definition)
    source=document.get('source',{})
    if not isinstance(source,dict):raise Invalid('Timeline 来源信息无效')
    # Validate only storage/reader requirements, not a Loop's business schema.
    for row in state+results:
        if any(not isinstance(row.get(k),str) or not row[k] for k in ('id','type')) or type(row['revision']) is not int or row['revision']<1:
            raise Invalid('Timeline 记录需要有效标识、类型和版本')
    for row in entries:
        if any(not isinstance(row[k],str) for k in ('key','text','kind')) or type(row['sequence']) is not int or row['sequence']<1:
            raise Invalid('Timeline 工作经过格式无效')
    for row in state+entries:
        if not isinstance(row.get('at',0),(int,float)) or not isinstance(row.get('refs',[]),list) or any(not isinstance(r,dict) for r in row.get('refs',[])):
            raise Invalid('Timeline 记录的时间或引用格式无效')
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute("SELECT document FROM work_timelines WHERE json_extract(document,'$.import_request')=?",(request_id,)).fetchone()
        if prior:
            value=json.loads(prior[0])
            if value.get('import_digest')!=fingerprint:raise Conflict('导入请求已用于另一个文件')
            return {'timeline':value,'duplicate':True,'notice':NOTICE}
        value=timelines.create(db,intent['objective'],intent['constraints'],intent['title'])
        ident=value['id']
        value.update(revision=revision,import_source=copy.deepcopy(source),import_digest=fingerprint,import_request=request_id,
                     state_definition=definition)
        timelines.save(db,value)
        try:
            for row in entries:
                entry=pick(row,ENTRY_FIELDS);entry.setdefault('refs',[]);entry.setdefault('actor','import');entry.setdefault('at',value['created_at'])
                entry['fingerprint']=digest({k:entry[k] for k in ('text','kind','refs','actor')})
                db.execute('INSERT INTO work_entries VALUES (?,?,?,?)',(ident,entry['key'],entry['sequence'],json.dumps(entry,ensure_ascii=False)))
            for row in state:
                r=pick(row,STATE_FIELDS);r.setdefault('refs',[]);r.setdefault('run_id',None);r.setdefault('at',value['created_at'])
                db.execute('INSERT INTO work_state VALUES (?,?,?,?,?)',(ident,r['type'],r['id'],r['revision'],json.dumps(r,ensure_ascii=False)))
            for row in results:
                r=pick(row,RESULT_FIELDS)
                db.execute('INSERT INTO work_results VALUES (?,?,?,?)',(ident,r['id'],r['revision'],json.dumps(r,ensure_ascii=False)))
        except sqlite3.IntegrityError as exc:
            raise Invalid('Timeline 文件含重复的记录标识或版本') from exc
        timelines.append(db,ident,'import:'+ident,'已导入任务进度，可由本平台的相关 Loop 继续推进。','progress',actor='platform')
        db.commit()
    return {'timeline':value,'duplicate':False,'notice':NOTICE}
