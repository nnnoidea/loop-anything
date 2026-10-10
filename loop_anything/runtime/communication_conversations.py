"""Conversation provenance and explicitly mapped Agent notification identities."""
import copy
import json
from loop_anything.runtime.model import Invalid, Conflict, digest
from loop_anything.runtime.store import uid


def register(comm, args):
    if comm.identity_conflict:raise Conflict('Resolve this machine identity before registering a conversation')
    from loop_anything.runtime.implementations import validate_implementation
    context=copy.deepcopy(args['conversation'])
    allowed={'platform','chat_id','chat_type','session_key','thread_root','entry_project'}
    if not isinstance(context,dict) or set(context)-allowed or context.get('platform') not in ('feishu','lark'):
        raise Invalid('Expected a captured Feishu/Lark conversation')
    if context.get('chat_type') not in ('p2p','group') or not all(isinstance(context.get(k),str) and context[k] for k in ('chat_id','session_key','entry_project')):
        raise Invalid('Conversation requires chat type, chat ID, full session key and entry project')
    parts=context['session_key'].split(':')
    if parts[:2]!=[context['platform'],context['chat_id']] or len(parts) not in (2,3,4):raise Invalid('Conversation/session mismatch')
    root=parts[3] if len(parts)==4 and parts[2] in ('root','thread') else None
    if len(parts)==4 and not root or context.get('thread_root')!=root:raise Invalid('Thread root/session mismatch')
    if root and context['chat_type']!='group':raise Invalid('A private conversation cannot have a group thread')
    if not args.get('notification_command'):raise Invalid('Conversation requires a local notification sender command')
    sender={'timeout':60,'command':args['notification_command'],'identity':context['entry_project'],'destination':context['session_key'],'channel':'cc-connect'}
    validate_implementation(dict(sender,kind='command'))
    binding={'id':uid('conversation'),'group_id':None,'enabled':True,'sender_instance':comm.settings()['instance_id'],
             'level':'key','conversation':context}
    with comm.transaction() as db:
        db.execute('INSERT INTO communication_notification_bindings VALUES (?,?)',(binding['id'],json.dumps(dict(binding,sender=sender))))
    return {'conversation_id':binding['id'],'conversation':context}


def resolve(comm, ident, include_sender=False):
    with comm.store.connection() as db:
        row=db.execute('SELECT document FROM communication_notification_bindings WHERE id=?',(ident,)).fetchone()
    binding=json.loads(row[0]) if row else {}
    if 'conversation' not in binding or binding.get('sender_instance')!=comm.settings()['instance_id']:
        raise Invalid('Unknown conversation on this platform')
    return {k:copy.deepcopy(v) for k,v in binding.items() if include_sender or k!='sender'}


def bot_binding(comm,agent,group_id=None,freeze=False):
    route=agent.get('notification_route')
    if not route:return None
    sender=comm.store.notification_channels()['channels'].get(route)
    if not sender or not sender.get('command'):return None
    sender=dict(sender,timeout=max(60,sender.get('timeout',30)))
    binding={'group_id':group_id,'enabled':True,'sender_instance':comm.settings()['instance_id'],
             'agent_id':agent['id'],'level':'key','route':route,
             **{k:sender.get(k,'') for k in ('channel','identity','label')}}
    binding['id']='bot-'+digest([binding,sender])[:40]
    if freeze:
        with comm.transaction() as db:
            db.execute('INSERT OR IGNORE INTO communication_notification_bindings VALUES (?,?)',(binding['id'],json.dumps(dict(binding,sender=sender))))
    return binding


def select(comm,request,state):
    entry=copy.deepcopy(request['notification_conversation'])
    context=entry['conversation']
    route={'policy':'conversation','reason':'entry_bot','sender_instance':entry['sender_instance'],
           'chat_id':context['chat_id'],'thread_root':context.get('thread_root'),'binding_id':entry['id']}
    if context['chat_type']=='group' and state in ('running','completed','failed'):
        gid=request.get('scope_group_id') or request.get('group_id')
        for agent in comm.directory(gid)['agents']:
            if agent['id']!=request.get('agent_id') or agent['instance_id']!=request.get('executor'):continue
            if agent['location']=='group' and agent.get('group_id')!=gid:continue
            if agent['location']=='local' and request.get('executor')!=comm.settings()['instance_id']:continue
            if not agent.get('online') or not agent.get('enabled'):continue
            binding=agent.get('notification_binding')
            if binding:
                if agent['location']=='local':binding=bot_binding(comm,comm.settings()['agents'][agent['id']],freeze=True)
                route.update(reason='agent_bot',sender_instance=binding['sender_instance'],binding_id=binding['id'])
                return copy.deepcopy(binding),route,entry
    return entry,route,None
