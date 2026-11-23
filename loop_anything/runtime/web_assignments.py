"""User-started planning and Loop reviews. Work sessions execute; Timelines retain the results."""
import json
import time

from loop_anything.paths import platform_skill_directory
from loop_anything.runtime import timelines, work
from loop_anything.runtime.agent_models import DEFAULT_MODEL, MODEL_NAME
from loop_anything.runtime.model import Conflict, Invalid, digest
from loop_anything.runtime.store import uid


def latest_reports(db, loop_id=None):
    # Report identity belongs to the Timeline entry, independent of who started the check.
    where = " AND json_extract(document,'$.review.loop_id')=?" if loop_id else ""
    return db.execute("""WITH ranked AS (
        SELECT timeline_id,key,json_extract(document,'$.review.loop_id') AS loop_id,
               json_extract(document,'$.review.run_count') AS count,json_extract(document,'$.text') AS summary,
               json_extract(document,'$.at') AS at,
               row_number() OVER(PARTITION BY json_extract(document,'$.review.loop_id')
                                 ORDER BY json_extract(document,'$.at') DESC,rowid DESC) AS rank
        FROM work_entries WHERE json_type(document,'$.review.loop_id')='text'
          AND json_extract(document,'$.source_timeline_id')=timeline_id"""+where+""")
        SELECT * FROM ranked WHERE rank=1""",(loop_id,) if loop_id else ())


def start(store, args):
    kind = args.get('kind')
    model = args.get('model', DEFAULT_MODEL)
    request = args.get('request_id')
    if kind not in ('plan','review') or not isinstance(request,str) or not request.strip():
        raise Invalid('请选择任务并提供请求标识')
    if not isinstance(model,str) or not MODEL_NAME.fullmatch(model):
        raise Invalid('请填写模型名称')
    ident = 'session-'+digest(['web',request])[:24]
    with work.transaction(store) as db:
        old = db.execute("SELECT document FROM work_objects WHERE kind='session' AND id=?",(ident,)).fetchone()
        if old:
            session=json.loads(old[0])
            if session['assignment']['request']!=args:raise Conflict('请求内容已改变')
            return {'id':ident,'timeline_id':session['assignment']['timeline_id']}
        title=args.get('text','')
        scope={}
        timeline=None
        if kind=='plan':
            if not isinstance(title,str) or not title.strip():raise Invalid('请写下想交给 Agent 的安排')
            title=title.strip()
        else:
            key=args.get('loop_key')
            row=db.execute("SELECT document FROM loop_definitions WHERE key=?",(key,)).fetchone()
            if row is None:raise Invalid('请选择要回顾的 Loop')
            loop=json.loads(row[0])
            scope={'loop_id':loop['id'],'created_to':args['created_to'],'archived':'include'}
            if args.get('this_version',True):scope['loop_key']=key
            if 'created_from' in args:scope['created_from']=args['created_from']
            from loop_anything.runtime.run_library import list_runs
            sample=list_runs(store,**scope,view='revisions',limit=1)
            if not sample['total']:raise Invalid('所选范围内还没有 Run')
            title=loop.get('name') or loop['id']
            prior=db.execute("""SELECT json_extract(document,'$.assignment.timeline_id') FROM work_objects
                WHERE kind='session' AND json_extract(document,'$.assignment.kind')='review'
                AND json_extract(document,'$.assignment.scope.loop_id')=? LIMIT 1""",(loop['id'],)).fetchone()
            report=latest_reports(db,loop['id']).fetchone()
            timeline=report['timeline_id'] if report else prior[0] if prior else None
        if timeline is None:
            objective=title if kind=='plan' else '持续回顾并优化 '+title
            timeline=timelines.create(db,objective=objective,title=title[:80] if kind=='plan' else objective)['id']
        assignment=dict(kind=kind,title=title,timeline_id=timeline,model=model,scope=scope,request=args)
        if kind=='review':assignment['count']=sample['total']
        else:assignment['schedule_directory']=work.schedule_directory(store)
        work.put(db,'session',dict(id=ident,token=uid('session-token'),state='queued',process_id=None,wake=None,
                                   created_at=time.time(),assignment=assignment,native_session=None))
    return {'id':ident,'timeline_id':timeline}


def progress(db,session):
    a=session['assignment']
    if a['kind']=='review':
        row=db.execute("SELECT document FROM work_entries WHERE timeline_id=? AND key=?",
                       (a['timeline_id'],session['id']+':report')).fetchone()
    else:
        row=db.execute("""SELECT document FROM work_entries WHERE timeline_id=? AND
            json_type(document,'$.refs[0].steps')='array' ORDER BY sequence DESC LIMIT 1""",(a['timeline_id'],)).fetchone()
    entry=json.loads(row[0]) if row else {}
    steps=entry['refs'][0]['steps'] if entry and a['kind']=='plan' else []
    steps=[s for s in steps if isinstance(s,dict) and isinstance(s.get('title'),str)]
    return entry.get('text',''),steps,entry.get('at')


def overview(store,kind):
    if kind not in ('plan','review'):raise Invalid('未知页面')
    with store.connection() as db:
        db.execute('BEGIN')
        items=[]
        wait_errors={}
        if kind=='plan':
            for wait in db.execute("""SELECT json_extract(document,'$.session_id'),json_extract(document,'$.message'),
                       json_extract(document,'$.error') FROM work_objects WHERE kind='wait' AND
                       json_extract(document,'$.state')='waiting' AND json_extract(document,'$.error') IS NOT NULL"""):
                wait_errors.setdefault(wait[0],[]).append(dict(message=wait[1],error=wait[2]))
        for row in db.execute("""SELECT id,json_extract(document,'$.assignment') AS assignment,
                json_extract(document,'$.state') AS state,json_extract(document,'$.created_at') AS at,
                json_extract(document,'$.error') AS error,json_extract(document,'$.process_id') AS pid FROM work_objects WHERE kind='session'
                AND json_extract(document,'$.assignment.kind')=? ORDER BY json_extract(document,'$.created_at') DESC""",(kind,)):
            a=json.loads(row['assignment'])
            summary,steps,reported_at=progress(db,dict(assignment=a,id=row['id']))
            items.append(dict(id=row['id'],title=a['title'],timeline_id=a['timeline_id'],model=a['model'],
                              state=row['state'],at=row['at'],error=row['error'],
                              summary=(summary.splitlines() or [''])[0] if kind=='review' else summary,
                              steps=steps,count=a.get('count'),scope=a['scope'],reported_at=reported_at,
                              wait_errors=wait_errors.get(row['id'],[]),
                              can_recover=row['state']=='unknown' and not work.alive(row['pid'])))
        if kind=='review':
            web_keys={(item['timeline_id'],item['id']+':report') for item in items}
            for report in latest_reports(db):
                if (report['timeline_id'],report['key']) in web_keys:continue
                lid=report['loop_id']
                loop=db.execute("SELECT json_extract(document,'$.name') FROM loop_definitions WHERE json_extract(document,'$.id')=? LIMIT 1",(lid,)).fetchone()
                items.append(dict(id=None,title=(loop[0] if loop else None) or lid,timeline_id=report['timeline_id'],
                                  state='completed',at=report['at'],reported_at=report['at'],count=report['count'],
                                  scope={'loop_id':lid},summary=(report['summary'].splitlines() or [''])[0]))
            items.sort(key=lambda item:item['at'],reverse=True)
        return {'items':items}


def follow_up(store, ident, args):
    message=args.get('text','')
    if not isinstance(message,str):raise Invalid('请填写补充说明')
    with work.transaction(store) as db:
        session=work.get(db,'session',ident)
        if 'assignment' not in session:raise Conflict('该会话没有网页规划或回顾')
        recovering=session['state']=='unknown'
        work.retry_session(session,args.get('confirmed_stopped') is True)
        if not recovering and not message.strip():raise Invalid('请填写补充说明')
        if message.strip():
            timelines.append(db,session['assignment']['timeline_id'],uid('reply'),message.strip(),'decision',actor='user')
        session['reply']=message.strip() or '原进程已确认停止。请核对已有进度和已登记的安排后接着做。'
        work.put(db,'session',session)
    return {'id':ident}


def launch(session,context):
    a=session['assignment']
    directory=platform_skill_directory()
    reference='work.md' if a['kind']=='plan' else 'loop-review.md'
    context.update(timeline_id=a['timeline_id'],scope=a['scope'])
    if a['scope']:context.update({k:a['scope'][k] for k in ('loop_id','loop_key') if k in a['scope']})
    context['assignment']={'kind':a['kind'],'objective':a['title'],'reply':session.get('reply'),
                           'report_key':session['id']+':report'}
    if a['kind']=='review':context['assignment']['review']={'loop_id':a['scope']['loop_id'],'run_count':a['count']}
    base=['codex','exec']
    native=session.get('native_session')
    if native:base+=['resume']
    command=base+['--skip-git-repo-check','--json','--model',a['model']]+([native['id']] if native else [])+['-']
    config=dict(kind='agent',command=command,agent_cli='codex')
    if native:config['cwd']=native.get('cwd')
    # Supply the same shipped operator guidance on the first turn and after a wake.
    instruction=(directory/'references'/reference).read_text(encoding='utf-8')
    contract=(PLAN if a['kind']=='plan' else REVIEW)
    prompt=('You are the server Agent executing a user request. Use the platform Skill at '+str(directory/'SKILL.md')+
            '. Invoke the supplied platform_client with Python, TOOL --arguments JSON. Check ok on each response. '
            'Read this Timeline before acting. Write for the user in their language. Use the supplied session_id and '
            'session_token for waits; this work session is already registered. Never copy tokens into Timeline entries. Acknowledge handled ready waits before exiting.\n'
            +instruction+'\n'+contract+'\n'+json.dumps(context,ensure_ascii=False))
    return config,prompt


PLAN="""Carry out the arrangement, not just an outline. To display the plan, call append_timeline(kind=progress)
initially, at each meaningful change and before exiting. Use a distinct stable key for each update, a short text
describing what is happening, and refs=[{"steps":[{"title":"…","status":"active","note":"…"}]}].
Send the full current ordered step list each time. Status is pending, active, waiting, needs_input, done or skipped.
Include the actual wait condition or decision in note. When relevant add the real run_id and optional task_id to the step. When handing a later step to the local scheduler, use the supplied schedule_directory for registration and start.
Register wait_for on the returned schedule ID (kind=schedule; condition alias.terminal == true for a one-off).
On wake inspect last_result, status and error. Never start another copy just to resume the plan.
Register wait_for when required, then exit; only mark done
when evidenced. If clarification or consent is needed, use needs_input, write the question and exit."""
REVIEW="""Perform the full review now. Use list_runs with the supplied scope, follow every page, then query_run_facts
and drill down for evidence. Save the report with append_timeline(kind=progress,key=assignment.report_key,review=assignment.review) on the
supplied optimization timeline. Put the main conclusion on the first line and include scope, findings and evidence
in the report. Reuse past facts when appropriate. Do not change the Loop."""


def finished(db,session):
    summary,steps,_=progress(db,session)
    if session['assignment']['kind']=='review' and summary.strip():return 'completed',None
    statuses=[s.get('status') for s in steps if isinstance(s,dict) and s.get('title')]
    if statuses and all(s in ('done','skipped') for s in statuses):return 'completed',None
    if 'needs_input' in statuses:return 'needs_input',None
    if statuses and db.execute("""SELECT 1 FROM work_objects WHERE kind='wait'
       AND json_extract(document,'$.session_id')=? AND json_extract(document,'$.state') IN ('waiting','ready') LIMIT 1""",(session['id'],)).fetchone():
        return 'idle',None
    return 'failed','Agent 已退出，尚未提交完整结果或下一步等待条件。'
