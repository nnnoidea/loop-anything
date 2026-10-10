"""Compact Agent-facing request views; full diagnostics stay in the store."""
import copy
from loop_anything.runtime.model import Invalid


def summary(request):
    from loop_anything.runtime.communication import clean
    fields=('id','kind','state','message','message_truncated','source','source_reference','source_summary','parent_request','origin','origin_name','revision',
            'agent_id','agent_label','executor','executor_name','location','group_id','scope_group_id',
            'created_at','updated_at','native_session','result','error','progress','session','notification_binding',
            'notification_origin','notification_route','notification_level')
    result=clean({k:request[k] for k in fields if k in request})
    if len(result.get('message',''))>500:
        result['message']=result['message'][:500];result['message_truncated']=True
    notices=request.get('notifications',[])
    result['notification_count']=request.get('notification_count',len(notices))
    result['notifications']=[{k:n[k] for k in ('id','state','status','attempt','error') if k in n} for n in notices[-3:]]
    return result


def continuation_context(request):
    # Keep initial business context and the immediately preceding outcome, not nested request archives.
    context=request.get('context',{})
    if request.get('previous_request_id') and 'original_context' in context:
        original=context['original_context']
    else:
        original=context
        # Older platform follow-ups stored an entire previous request at each level.
        owner=request
        while isinstance(original,dict) and set(original)=={'previous_request'}:
            previous=original['previous_request']
            if not isinstance(previous,dict) or not {'id','kind','context'}<=previous.keys():break
            if owner.get('session',{}).get('request_id')!=previous['id']:break
            original=previous['context']
            owner=previous
    previous=summary(request)
    previous['message']=request.get('message','')
    return {'previous_request':previous,'original_context':copy.deepcopy(original)}


def log_page(db, table, key, ident, after, offset, max_chars):
    # Table and key are selected by platform code; only values come from tool arguments.
    rows=db.execute(f'SELECT sequence FROM {table} WHERE {key}=? AND sequence>? ORDER BY sequence LIMIT 65',
                    (ident,after)).fetchall()
    logs=[];cursor=after;remaining=max_chars
    for index,row in enumerate(rows):
        if index==64:break
        start=offset if index==0 else 0
        # SQLite length/substr stop at NUL; terminal output must retain the full chunk.
        chunk=db.execute(f'SELECT text FROM {table} WHERE {key}=? AND sequence=?',
                         (ident,row['sequence'])).fetchone()[0]
        if start>len(chunk):raise Invalid('Log offset exceeds the next chunk')
        take=min(remaining,len(chunk)-start)
        text=chunk[start:start+take]
        if text:logs.append({'sequence':row['sequence'],'text':text})
        remaining-=take
        if start+take<len(chunk):
            return {'logs':logs,'log_cursor':cursor,'log_offset':start+take,'log_more':True}
        cursor=row['sequence']
        if remaining==0:break
    if not rows and offset:raise Invalid('Log offset has no corresponding chunk')
    return {'logs':logs,'log_cursor':cursor,'log_offset':0,'log_more':bool(rows and cursor<rows[-1]['sequence'])}
