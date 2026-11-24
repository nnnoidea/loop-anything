"""Durable work/resource/request affinity for the portable client. Standard library only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import uuid


def sibling(name):
    spec=importlib.util.spec_from_file_location('_routing_'+name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

# Only these operations may begin independent work without a known resource/work.
# Every other tool fails closed; adding a tool never silently enables default routing.
INDEPENDENT=set('import_timeline check list read_capabilities read_cc_connect read_notification_channels list_loops list_resources create_loop list_runs communication_workspace communication_status list_executors read_monitor_dashboard create_timeline list_timelines register_work_session list_monitor_scripts list_monitors start_collaboration request_assistance'.split())
# Only tools declared read-only may look up an unseen resource on a verified platform.
READ_ONLY=set('query_run_facts read_execution_attempt read_observations communication_status communication_workspace export_loop export_timeline list_executors list_loops list_resources list_monitor_scripts list_monitors list_runs list_timelines next_tasks preview_plan read_assistance read_business_state read_capabilities read_cc_connect read_execution_session read_executor_call read_loop read_loop_config read_loop_models read_monitor read_monitor_dashboard read_monitor_history read_notification_channels read_plans read_record read_resource read_run read_run_request read_task read_timeline read_wait read_work_result read_work_results read_work_session read_work_timeline resolve_refs test_loop validate_loop validate_parameters'.split())
RETRYABLE_HTTP=READ_ONLY | {'list','import_timeline'}
KNOWN_TOOLS=READ_ONLY | set('acquire_run update_run_method refresh_observation acknowledge_wait add_task append_timeline archive_loop build_plan cancel_wait change_settings change_task check command communication_config communication_execute complete configure_cc_connect confirm_executor_stopped connect_steps control_assistance control_execution_session copy_loop create_loop create_timeline defer_task delete_loop edit_tasks executor_poll executor_report finish import_timeline list native_session notify progress publish_loop put_asset put_node put_step read_asset read_context register_agent_session register_monitor register_work_session remove_node remove_step report_task request_assistance resolve_continuation resolve_request restart_monitor result resume_work_session send_event set_implementation set_loop set_loop_config set_loop_models set_monitor_visibility set_notification_channels smoke_runtime source_call source_result start_collaboration start_monitor start_run stop_monitor submit_run_request update_timeline wait_assistance wait_for'.split())
LOOP_KEYS=set('update_run_method preview_plan validate_parameters test_loop archive_loop delete_loop smoke_runtime read_loop copy_loop read_loop_config set_loop_config read_loop_models set_loop_models start_run'.split())
WORK_SESSIONS=set('start_run read_work_session resume_work_session wait_for cancel_wait acknowledge_wait'.split())
NEW_REQUESTS=set('import_timeline start_run start_collaboration request_assistance submit_run_request start_monitor'.split())
FIELDS={'run_id':'run','continue_run_id':'run','parent_run_id':'run','collaboration_id':'run',
        'timeline_id':'timeline','draft_id':'draft','monitor_id':'monitor','wait_id':'wait',
        'script_id':'script','resource_id':'resource','group_id':'group','agent_id':'agent','context_id':'context',
        'space_id':'space','binding_id':'binding','loop_key':'loop','loop_id':'loop_id','executor':'executor','call_id':'call'}
LIST_FIELDS={'run_ids':'run','request_ids':'request'}
EXECUTOR_CALLS={'read_executor_call','executor_report','confirm_executor_stopped','source_result'}


def references(tool,a):
    refs=[]
    def add(kind,value):
        if isinstance(value,str) and value:refs.append((kind,value))
    for field,kind in FIELDS.items():
        if field=='script_id' and tool=='register_monitor' and a.get('revision')==0:continue
        add(kind,a.get(field))
    if tool in LOOP_KEYS:add('loop',a.get('key'))
    if tool in WORK_SESSIONS:add('session',a.get('session_id'))
    if tool in EXECUTOR_CALLS:add('call',a.get('id'))
    if tool not in NEW_REQUESTS:add('request',a.get('request_id'))
    if tool=='list_runs':
        for run in a.get('known_revisions',[]):
            if isinstance(run,dict):add('run',run.get('id'))
    for field,kind in LIST_FIELDS.items():
        for ident in a.get(field,[]):add(kind,ident)
    if tool=='request_assistance' and isinstance(a.get('source'),dict):add('run',a['source'].get('run_id'))
    if tool=='set_implementation':
        if isinstance(a.get('loop'),dict):add('loop',a['loop'].get('key'))
        if isinstance(a.get('dispatch'),dict):add('agent',a['dispatch'].get('agent_id'))
    if tool=='wait_for':
        for source in a.get('sources',{}).values():
            if isinstance(source,dict) and source.get('kind')!='schedule':add('run' if source.get('kind')=='task' else source.get('kind'),source.get('id'))
    if tool=='communication_execute' and isinstance(a.get('arguments'),dict):refs+=references(a.get('tool'),a['arguments'])
    return list(dict.fromkeys(refs))


def resources(tool,result):
    """Read protocol-owned resource envelopes, never arbitrary outputs or user text."""
    found=[]
    def row(value,kind=None):
        if not isinstance(value,dict):return
        if kind and isinstance(value.get('id'),str):found.append((kind,value['id']))
        for field,typ in FIELDS.items():
            if isinstance(value.get(field),str):found.append((typ,value[field]))
        for field,typ in (('key','loop'),('session_id','session'),('request_id','request')):
            if field=='key' and kind!='loop' and tool not in LOOP_KEYS|{'publish_loop'}:continue
            if isinstance(value.get(field),str):found.append((typ,value[field]))
    row(result)
    if tool == 'read_run':
        for task in result.get('tasks', []):
            row(task.get('continuation_source'))
    wrappers={'run':'run','timeline':'timeline','draft':'draft','session':'session','monitor':'monitor','wait':'wait','call':'call','script':'script','request':'request','resource':'resource'}
    for field,kind in wrappers.items():
        row(result.get(field),kind)
        if field=='call' and isinstance(result.get(field),dict):row(result[field].get('metadata'))
        for value in result.get(field+'s',[]) if isinstance(result.get(field+'s'),list) else []:row(value,kind)
    for field,kind in (('loops','loop'),('agents','agent'),('groups','group'),('spaces','space'),('executors','executor'),('bindings','binding'),('contexts','context'),('items','timeline' if tool=='list_timelines' else 'run' if tool=='list_runs' else None)):
        if field=='loops' and tool not in {'list_loops','list_runs'}:continue
        for value in result.get(field,[]) if isinstance(result.get(field),list) else []:row(value,kind)
    if tool in {'communication_workspace','communication_config'}:
        config=result.get('configuration',{})
        for field,kind in (('agents','agent'),('groups','group'),('spaces','space'),('contexts','context')):
            values=config.get(field,{})
            if isinstance(values,dict):
                for ident,value in values.items():
                    found.append((kind,ident));row(value,kind)
        if isinstance(result.get('directory'),dict):found+=resources('communication_status',result['directory'])
        for space in result.get('shared_spaces',[]):
            row(space,'space')
            for group in space.get('groups',[]):row(group,'group')
    if isinstance(result.get('loop'),dict):
        loop=result['loop'];row(loop);row(loop.get('loop_definition'),'loop_id')
    return list(dict.fromkeys(found))


class Ledger:
    def __init__(self):
        path=sibling('spaces').path().with_suffix('.routing.sqlite3');path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=30)
        if os.name!='nt':path.chmod(0o600)
        self.db.executescript('''CREATE TABLE IF NOT EXISTS works (id TEXT PRIMARY KEY,url TEXT NOT NULL,workspace TEXT);
          CREATE TABLE IF NOT EXISTS refs (kind TEXT,ident TEXT,work TEXT,PRIMARY KEY(kind,ident,work));
          CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY,work TEXT NOT NULL,tool TEXT NOT NULL,args TEXT NOT NULL,response TEXT,state TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS ref_lookup ON refs(kind,ident);
          CREATE INDEX IF NOT EXISTS request_business ON requests(tool,json_extract(args,'$.request_id'));''')
    def close(self):self.db.close()
    def get(self,work):
        row=self.db.execute('SELECT id,url,workspace FROM works WHERE id=?',(work,)).fetchone()
        if not row:raise ValueError('Unknown work reference. Discover the resource in its platform before continuing; no request was sent.')
        return dict(zip(('id','url','workspace'),row))
    def remember(self,work,refs):
        self.db.executemany('INSERT OR IGNORE INTO refs VALUES (?,?,?)',[(k,i,work) for k,i in refs])
    @staticmethod
    def origin(work):
        # An unverified work is distinct even from other records at the same URL.
        return (work['url'],work['workspace'],None if work['workspace'] else work['id'])
    def origins(self,ref):
        rows=self.db.execute('SELECT w.id,w.url,w.workspace FROM refs r JOIN works w ON w.id=r.work WHERE r.kind=? AND r.ident=? ORDER BY w.rowid',ref)
        found={}
        for row in rows:
            work=dict(zip(('id','url','workspace'),row))
            found.setdefault(self.origin(work),work)
        return found
    def create(self,url):
        work='work-'+uuid.uuid4().hex
        self.db.execute('INSERT INTO works VALUES (?,?,NULL)',(work,url));return work
    def choose(self,tool,args,url=None,space=None,work=None,request_id=None):
        if tool not in KNOWN_TOOLS:raise ValueError('Unknown routing contract for tool; no request was sent.')
        spaces=sibling('spaces')
        if url is not None and space is not None:raise ValueError('Supply --url or --space, not both')
        explicit=spaces.resolve(url,space) if url is not None or space is not None else None
        injected=os.environ.get('LOOP_ANYTHING_WORK')
        refs=references(tool,args)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            selected=self.get(work or injected) if work or injected else None
            if injected and work and self.origin(self.get(injected))!=self.origin(selected):
                raise ValueError('Explicit work conflicts with the injected work platform; no request was sent.')
            supplied=self.db.execute('SELECT work,tool,args FROM requests WHERE id=?',(request_id,)).fetchone() if request_id else None
            if tool in NEW_REQUESTS and args.get('request_id'):
                operations=self.db.execute("SELECT id FROM requests WHERE tool=? AND json_extract(args,'$.request_id')=?",(tool,args['request_id'])).fetchall()
                if len(operations)>1:raise ValueError('Business request has ambiguous saved attempts; inspect original work, no request was sent.')
                if operations:
                    canonical=operations[0][0]
                    if supplied and request_id!=canonical:raise ValueError('Transport request ID already belongs to another operation')
                    request_id=canonical
                elif request_id is None:
                    request_id='api-'+hashlib.sha256((tool+':'+str(args['request_id'])).encode()).hexdigest()
            retry=self.db.execute('SELECT work,tool,args FROM requests WHERE id=?',(request_id,)).fetchone() if request_id else None
            if retry:
                if tool!='result' and (retry[1]!=tool or retry[2]!=encode(args)):raise ValueError('Request ID belongs to different arguments or tool; no request was sent.')
                original=self.get(retry[0])
                if selected and self.origin(selected)!=self.origin(original):raise ValueError('Request belongs to another work platform; no request was sent.')
                selected=original
            if tool=='result' and not retry:raise ValueError('Unknown request receipt. Do not use the current default to find old work.')
            origins=[]
            unknown=[]
            for ref in refs:
                known=self.origins(ref)
                if known:
                    origins.append(known)
                else:
                    unknown.append(ref)
            if origins:
                common=set.intersection(*(set(origin) for origin in origins))
                if selected:
                    if self.origin(selected) not in common:raise ValueError('Resources belong to another work platform; no request was sent.')
                elif len(common)==1 and (next(iter(common))[1] or all(len(origin)==1 for origin in origins)):
                    selected=origins[0][next(iter(common))]
                else:raise ValueError('Ambiguous or mixed-platform resources. Use the returned work_id; no request was sent.')
            if unknown and not (tool in READ_ONLY and selected and selected['workspace']):
                kind, ident = unknown[0]
                raise ValueError('Unknown original platform for '+kind+' '+ident+'. Discover it first; no request was sent.')
            if selected and explicit and selected['url']!=explicit:raise ValueError('Existing work belongs to its original platform; an explicit target cannot override it.')
            if not selected:
                fresh=tool in INDEPENDENT or tool=='register_monitor' and args.get('revision')==0 or tool=='start_monitor' and 'script' in args
                if not fresh:raise ValueError('This operation needs its work_id or previously discovered resources; no default routing is allowed.')
                selected=self.get(self.create(explicit or spaces.resolve()))
            if request_id and not retry:self.db.execute('INSERT INTO requests VALUES (?,?,?,?,NULL,?)',(request_id,selected['id'],tool,encode(args),'reserved'))
            self.db.commit();return dict(selected,request_id=request_id)
        except Exception:self.db.rollback();raise
    def verify(self,work,identity):
        if not isinstance(identity,str) or not identity:raise ValueError('Platform did not supply its identity; no tool request was sent.')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            original=self.get(work)['workspace']
            if original and original!=identity:raise ValueError('The address now belongs to a different platform. Original work was not sent.')
            self.db.execute('UPDATE works SET workspace=? WHERE id=?',(identity,work))
    def begin(self,request_id,nas=False):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute('SELECT response,state,tool FROM requests WHERE id=?',(request_id,)).fetchone()
            if row[0] is not None:return json.loads(row[0])
            if row[1]=='sent' and not nas and row[2] not in RETRYABLE_HTTP:return {'ok':False,'outcome_unknown':True,'error':'Previous HTTP request may have executed. Inspect its original platform; do not resubmit as new work.'}
            self.db.execute("UPDATE requests SET state='sent' WHERE id=?",(request_id,))
        return None
    def finish(self,work,tool,args,result,request_id=None):
        with self.db:
            if result.get('ok',False) or result.get('pending'):
                self.remember(work,references(tool,args)+resources(tool,result))
                if tool in NEW_REQUESTS and args.get('request_id'):self.remember(work,[('request',args['request_id'])])
            if request_id and not result.get('pending') and not result.get('transport_error'):
                self.db.execute("UPDATE requests SET response=?,state='done' WHERE id=?",(encode(result),request_id))


def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def bind_context(context):
    """Only the runtime calls this, with structured origin context before process launch."""
    url=context.get('platform_url')
    if not url:return None
    ledger=Ledger()
    try:
        # Local durable binding, no network/model calls. Identity is verified on first tool call.
        with ledger.db:
            work=ledger.create(url.rstrip('/'))
            refs=resources('',context)
            refs+=resources('',{'requests':context.get('assistance_results',[])})
            if isinstance(context.get('continued_from'),dict):refs+=resources('',context['continued_from'])
            for wait in context.get('waits',[]):
                if isinstance(wait,dict):refs+=references('wait_for',{'sources':wait.get('sources',{})})
            if context.get('loop_key'):refs.append(('loop',context['loop_key']))
            ledger.remember(work,refs)
            identity=context.get('workspace_id') or (context.get('self') or {}).get('workspace_id')
            if identity:ledger.db.execute('UPDATE works SET workspace=? WHERE id=?',(identity,work))
        return work
    finally:ledger.close()
