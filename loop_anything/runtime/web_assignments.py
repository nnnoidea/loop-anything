"""User-started planning and Loop reviews. Work sessions execute; Timelines retain the results."""
from contextlib import closing
import json
import time
from urllib.parse import urlencode

from loop_anything.paths import platform_skill_directory
from loop_anything.runtime import timelines, work
from loop_anything.runtime.agent_models import DEFAULT_MODEL, MODEL_NAME
from loop_anything.runtime.model import Conflict, Invalid, digest
from loop_anything.runtime.store import uid

PLAN_CONTINUABLE = ('idle', 'stopped', 'completed')
PLAN_STOPPABLE = ('queued', 'idle', 'needs_input', 'failed')
PLAN_STEPS = "timeline_id=? AND json_type(document,'$.refs[0].steps')='array'"
REVIEW_COLUMNS = """e.timeline_id,e.key,json_extract(e.document,'$.review.run_count') AS count,
    json_extract(e.document,'$.at') AS at,
    EXISTS(SELECT 1 FROM work_review_html h WHERE h.timeline_id=e.timeline_id AND h.key=e.key) AS has_html"""
REVIEW_ENTRY = """json_type(e.document,'$.review.loop_id')='text'
    AND json_extract(e.document,'$.source_timeline_id')=e.timeline_id"""


def latest_reports(db, loop_id=None):
    # Report identity belongs to the Timeline entry, independent of who started the check.
    where = " AND json_extract(e.document,'$.review.loop_id')=?" if loop_id else ""
    return db.execute(f"""WITH ranked AS (
        SELECT {REVIEW_COLUMNS},json_extract(e.document,'$.review.loop_id') AS loop_id,
               row_number() OVER(PARTITION BY json_extract(e.document,'$.review.loop_id')
                                 ORDER BY json_extract(e.document,'$.at') DESC,e.rowid DESC) AS rank
        FROM work_entries e WHERE {REVIEW_ENTRY}{where})
        SELECT * FROM ranked WHERE rank=1""",(loop_id,) if loop_id else ())


def review_entry(db, session):
    assignment=session['assignment']
    return db.execute(f"""SELECT {REVIEW_COLUMNS} FROM work_entries e WHERE e.timeline_id=? AND e.key=?
                      AND json_extract(e.document,'$.review.loop_id')=? AND {REVIEW_ENTRY}""",
                      (assignment['timeline_id'],session['id']+':report',assignment['scope']['loop_id'])).fetchone()


def report_url(timeline_id, key):
    return '/api/assignments/review/report?' + urlencode(dict(timeline_id=timeline_id,key=key))


def report_metadata(report):
    return dict(reported_at=report['at'],count=report['count'],
                report_url=report_url(report['timeline_id'],report['key']) if report['has_html'] else None)


def save_report_html(db, entry, html):
    if not entry.get('review') or not entry['text'].strip():
        raise Invalid('HTML 报告需要回顾记录与供 Agent 接续的正文')
    content = html.encode('utf-8')
    if len(content)>1024*1024:
        raise Invalid('回顾 HTML 须在 1 MiB 以内')
    if not html.lstrip().lower().startswith('<!doctype html>'):
        raise Invalid('请提交 ReadableDocs 导出的完整 HTML 文档')
    identity = (entry['source_timeline_id'],entry['key'])
    inserted=db.execute('INSERT OR IGNORE INTO work_review_html(timeline_id,key,html) VALUES (?,?,?)',(*identity,content))
    if not inserted.rowcount:
        previous=db.execute('SELECT html FROM work_review_html WHERE timeline_id=? AND key=?',identity).fetchone()
        if previous[0]!=content:
            raise Conflict('这条回顾记录已有关联的 HTML 报告')
    return report_url(*identity)


def read_report_html(store, timeline_id, key):
    with store.connection() as db:
        row=db.execute('SELECT html FROM work_review_html WHERE timeline_id=? AND key=?',(timeline_id,key)).fetchone()
    if row is None:
        raise Invalid('没有找到这份 HTML 报告')
    return row[0]


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


def report_steps(entry):
    return [s for s in entry['refs'][0]['steps'] if isinstance(s,dict) and isinstance(s.get('title'),str)]


def completed_steps(steps):
    occurrences={}
    for step in steps:
        title=step['title']
        occurrence=occurrences.get(title,0)
        occurrences[title]=occurrence+1
        if step.get('status')=='done':
            yield (title,occurrence),step


def add_step_completion_times(steps, at, older_reports):
    # Walk back through the current completed streak of each step. Later
    # progress reports can repeat completed steps or reopen them.
    remaining=dict(completed_steps(steps))
    for row in older_reports:
        previous=json.loads(row[0])
        previous_done=dict(completed_steps(report_steps(previous)))
        for key in remaining.keys()-previous_done.keys():
            remaining.pop(key)['completed_at']=at
        if not remaining:
            break
        at=previous['at']
    for step in remaining.values():
        step['completed_at']=at


def plan_progress(db,timeline_id, *, completion_times=False):
    row=db.execute(f"SELECT sequence,document FROM work_entries WHERE {PLAN_STEPS} ORDER BY sequence DESC LIMIT 1",
                   (timeline_id,)).fetchone()
    if row is None:
        return '',[],None
    entry=json.loads(row['document'])
    steps=report_steps(entry)
    if completion_times:
        for step in steps:
            step.pop('completed_at',None)
        if any(step.get('status')=='done' for step in steps):
            with closing(db.execute(f"SELECT document FROM work_entries WHERE {PLAN_STEPS} AND sequence<? ORDER BY sequence DESC",
                                    (timeline_id,row['sequence']))) as reports:
                add_step_completion_times(steps,entry['at'],reports)
    return entry.get('text',''),steps,entry.get('at')


def plan_agent_state(state, pid, process_state, alive):
    if state == 'unknown':
        return 'running' if alive else 'unknown'
    if state == 'queued' or (state == 'running' and not pid):
        return 'starting'
    if state == 'running' and process_state == 'running':
        return 'running' if alive else 'idle'
    return 'idle'


def overview(store,kind, *, allow_stop=True):
    if kind not in ('plan','review'):raise Invalid('未知页面')
    with store.connection() as db:
        db.execute('BEGIN')
        items=[]
        wait_errors={}
        wait_messages={}
        if kind=='plan':
            for wait in db.execute("""SELECT json_extract(document,'$.session_id'),json_extract(document,'$.message'),
                       json_extract(document,'$.error') FROM work_objects WHERE kind='wait' AND
                       json_extract(document,'$.state')='waiting' ORDER BY json_extract(document,'$.created_at') DESC"""):
                session_id,message,error=wait
                if message and message not in wait_messages.setdefault(session_id,[]):
                    wait_messages[session_id].append(message)
                if error is not None:
                    wait_errors.setdefault(session_id,[]).append(dict(message=message,error=error))
        for row in db.execute("""SELECT id,json_extract(document,'$.assignment') AS assignment,
                json_extract(document,'$.state') AS state,json_extract(document,'$.created_at') AS at,
                json_extract(document,'$.error') AS error,json_extract(document,'$.process_id') AS pid,
                json_extract(document,'$.process.state') AS process_state,
                json_extract(document,'$.native_session.id') AS native_id,
                json_extract(document,'$.wake') AS wake FROM work_objects WHERE kind='session'
                AND json_extract(document,'$.assignment.kind')=? ORDER BY json_extract(document,'$.created_at') DESC""",(kind,)):
            a=json.loads(row['assignment'])
            is_plan=kind=='plan'
            alive=work.alive(row['pid'])
            item=dict(id=row['id'],title=a['title'],timeline_id=a['timeline_id'],model=a['model'],
                              state=row['state'],at=row['at'],error=row['error'],
                              count=a.get('count'),scope=a['scope'],
                              wait_messages=wait_messages.get(row['id'],[]),
                              wait_errors=wait_errors.get(row['id'],[]),
                              can_follow_up=is_plan and row['state'] in PLAN_CONTINUABLE and
                              bool(row['native_id']) and not row['wake'] and not alive,
                              can_stop=allow_stop and is_plan and row['state'] in PLAN_STOPPABLE and
                              not row['wake'] and not alive,
                              can_recover=row['state']=='unknown' and not alive)
            if is_plan:
                summary,steps,reported_at=plan_progress(db,a['timeline_id'],completion_times=True)
                item.update(summary=summary,steps=steps,reported_at=reported_at)
                item['agent_state']=plan_agent_state(row['state'],row['pid'],row['process_state'],alive)
            items.append(item)
        if kind=='review':
            web_items={(item['timeline_id'],item['id']+':report'):item for item in items}
            for report in latest_reports(db):
                lid=report['loop_id']
                item=web_items.get((report['timeline_id'],report['key']))
                if item and item['scope']['loop_id']==lid:
                    item.update(report_metadata(report))
                    continue
                loop=db.execute("SELECT json_extract(document,'$.name') FROM loop_definitions WHERE json_extract(document,'$.id')=? LIMIT 1",(lid,)).fetchone()
                items.append(dict(id=None,title=(loop[0] if loop else None) or lid,timeline_id=report['timeline_id'],
                                  state='completed',at=report['at'],scope={'loop_id':lid},**report_metadata(report)))
            items.sort(key=lambda item:item['at'],reverse=True)
        return {'items':items}


def follow_up(store, ident, args, *, instruction=False):
    message=args.get('text','')
    if not isinstance(message,str):raise Invalid('请填写补充说明')
    message=message.strip()
    with work.transaction(store) as db:
        session=work.get(db,'session',ident)
        if 'assignment' not in session:raise Conflict('该会话没有网页规划或回顾')
        state=session['state']
        continuing=instruction and session['assignment']['kind']=='plan' and state in PLAN_CONTINUABLE
        if instruction and not continuing:
            raise Conflict('请等当前 Agent 退出后再发送指令')
        if continuing and (not session.get('native_session') or session.get('wake')):
            raise Conflict('原 Agent 会话尚未准备好续接')
        work.retry_session(session,args.get('confirmed_stopped') is True,follow_up=continuing)
        if state!='unknown' and not message:raise Invalid('请填写指令' if continuing else '请填写补充说明')
        timeline_id=session['assignment']['timeline_id']
        if message:
            entry=timelines.append(db,timeline_id,uid('reply'),message,'decision',actor='user')
            session['reply_sequence']=entry['sequence']
        if state=='stopped':
            session['reply_after_stop']=True
        session['reply']=message or '原进程已确认停止。请核对已有进度和已登记的安排后接着做。'
        work.put(db,'session',session)
    return {'id':ident}


def stop_plan(store, ident):
    with work.transaction(store) as db:
        session=work.get(db,'session',ident)
        if session.get('assignment',{}).get('kind')!='plan':
            raise Invalid('只能停止托管规划')
        if session['state']=='stopped':
            return {'id':ident,'state':'stopped'}
        if session['state'] not in PLAN_STOPPABLE or session.get('wake') or work.alive(session.get('process_id')):
            raise Conflict('请等当前 Agent 退出后再停止规划')
        for wait in db.execute("""SELECT document FROM work_objects WHERE kind='wait'
                AND json_extract(document,'$.session_id')=?
                AND json_extract(document,'$.state') IN ('waiting','ready')""",(ident,)).fetchall():
            value=json.loads(wait[0])
            value.update(state='cancelled',error=None)
            value.pop('retained_sources',None)
            work.put(db,'wait',value)
        timelines.append(db,session['assignment']['timeline_id'],uid('plan-stop'),'托管规划已停止。','decision',actor='user')
        session.update(state='stopped',error=None,process_id=None)
        session.pop('reply',None)
        session.pop('reply_sequence',None)
        session.pop('reply_after_stop',None)
        work.put(db,'session',session)
    return {'id':ident,'state':'stopped'}


def launch(session,context):
    a=session['assignment']
    directory=platform_skill_directory()
    reference='work.md' if a['kind']=='plan' else 'loop-review.md'
    context.update(timeline_id=a['timeline_id'],scope=a['scope'])
    if a['scope']:context.update({k:a['scope'][k] for k in ('loop_id','loop_key') if k in a['scope']})
    context['assignment']={'kind':a['kind'],'objective':a['title'],'reply':session.get('reply'),
                           'report_key':session['id']+':report'}
    if session.get('reply') and a['kind']=='plan':
        context['assignment']['reply_after_stop']=session.get('reply_after_stop',False)
        context['assignment']['pending_waits']=[
            {k:wait.get(k) for k in ('id','state','message','sources','condition')}
            for wait in context.pop('pending_waits',[])
        ]
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
when evidenced. If clarification or consent is needed, use needs_input, write the question and exit.
When assignment.reply is present, treat it as the latest user instruction. Read the saved Timeline first.
Review assignment.pending_waits and ready waits against the new instruction. Keep waits that still apply,
cancel obsolete ones through cancel_wait, and avoid repeating work already carried out. Use a new key
for a replacement wait after cancellation. If assignment.reply_after_stop is true, the user stopped
the previous arrangement. Act on the new instruction and restart stopped steps only if it asks you to."""
REVIEW="""Perform the full review now. Use list_runs with the supplied scope, follow every page, then query_run_facts
and drill down for evidence. Follow the reporting instructions above to generate the ReadableDocs HTML.
Submit the Agent-readable record and the HTML together with append_timeline(kind=progress,key=assignment.report_key,
review=assignment.review,review_html=the exported HTML text) on the supplied optimization Timeline.
Set review.run_count to the number of Runs actually checked. Reuse past facts when appropriate."""


def finished(db,session):
    if session['assignment']['kind']=='review':
        report=review_entry(db,session)
        if report and report['has_html']:
            return 'completed',None
        return 'failed',('Agent 已保存回顾记录，尚未提交 ReadableDocs HTML。' if report
                         else 'Agent 已退出，尚未提交回顾记录和 HTML 报告。')
    _,steps,_=plan_progress(db,session['assignment']['timeline_id'])
    statuses=[s.get('status') for s in steps if isinstance(s,dict) and s.get('title')]
    if session.get('reply_sequence') is not None and not db.execute("""SELECT 1 FROM work_entries
            WHERE timeline_id=? AND sequence>? AND json_type(document,'$.refs[0].steps')='array' LIMIT 1""",
            (session['assignment']['timeline_id'],session['reply_sequence'])).fetchone():
        return 'failed','Agent 已退出，尚未记录这次补充指令的处理结果。'
    if statuses and all(s in ('done','skipped') for s in statuses):return 'completed',None
    if 'needs_input' in statuses:return 'needs_input',None
    if statuses and db.execute("""SELECT 1 FROM work_objects WHERE kind='wait'
       AND json_extract(document,'$.session_id')=? AND json_extract(document,'$.state') IN ('waiting','ready') LIMIT 1""",(session['id'],)).fetchone():
        return 'idle',None
    return 'failed','Agent 已退出，尚未提交完整结果或下一步等待条件。'
