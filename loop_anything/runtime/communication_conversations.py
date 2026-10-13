"""Conversation provenance and explicitly mapped Agent notification identities."""
import copy
import json
from loop_anything.runtime.model import Invalid, Conflict, digest
from loop_anything.runtime.store import uid


def register(comm, args):
    if comm.identity_conflict:raise Conflict('Resolve this machine identity before registering a conversation')
    from loop_anything.runtime.implementations import validate_implementation
    context=copy.deepcopy(args['conversation'])
    allowed={'platform','chat_id','chat_type','session_key','thread_root','thread_id','entry_project'}
    if not isinstance(context,dict) or set(context)-allowed or context.get('platform') not in ('feishu','lark'):
        raise Invalid('Expected a captured Feishu/Lark conversation')
    if context.get('chat_type') not in ('p2p','group','unknown') or not all(isinstance(context.get(k),str) and context[k] for k in ('session_key','entry_project')):
        raise Invalid('Conversation requires full session key and entry project')
    context.setdefault('chat_id','')
    parts=context['session_key'].split(':',3)
    root=parts[3] if len(parts)==4 and parts[2]=='root' else None
    thread=parts[3] if len(parts)==4 and parts[2]=='thread' else None
    # Scope labels are display metadata, never a validity test for the opaque key.
    if root or thread:
        context['thread_root']=root or context.get('thread_root')
        if thread and context['thread_root']==thread:context['thread_root']=None
        if thread:context.setdefault('thread_id',thread)
    if not args.get('notification_command'):raise Invalid('Conversation requires a local notification sender command')
    sender={'timeout':60,'command':args['notification_command'],'identity':context['entry_project'],'destination':context['session_key'],'channel':'cc-connect'}
    validate_implementation(dict(sender,kind='command'))
    binding={'id':uid('conversation'),'group_id':None,'enabled':True,'sender_instance':comm.settings()['instance_id'],
             'level':'key','conversation':context}
    with comm.transaction() as db:
        db.execute('INSERT INTO communication_notification_bindings VALUES (?,?)',(binding['id'],json.dumps(dict(binding,sender=sender))))
    return {'conversation_id':binding['id'],'conversation':context}


def entry_sender(comm,context):
    """Resolve local adapter configuration independently of the chat destination."""
    from loop_anything.runtime.cc_connect import configuration, sender as bridge_sender
    if configuration()['connection']:
        sender=bridge_sender({'project':context['entry_project'],'platform':context['platform']},context['session_key'])
        sender.update(identity=context['entry_project'],destination=context['session_key'],channel='cc-connect',timeout=60)
        return sender
    candidates=[s for s in comm.store.notification_channels()['channels'].values()
                if s.get('channel')=='cc-connect' and s.get('identity')==context['entry_project'] and s.get('command')]
    transports={digest({k:s[k] for k in ('command','cwd') if k in s}):s for s in candidates}
    if len(transports)==1:
        sender=copy.deepcopy(next(iter(transports.values())))
        sender['timeout']=max(s.get('timeout',30) for s in candidates)
    elif transports:sender={'configuration_error':'Multiple adapters are configured for the entry Bot; choose an explicit notification route'}
    else:
        sender=bridge_sender({'project':context['entry_project'],'platform':context['platform']},context['session_key'])
    sender.update(identity=context['entry_project'],destination=context['session_key'],channel='cc-connect',timeout=max(60,sender.get('timeout',30)))
    return sender


def from_source(comm,source):
    """Persist bridge metadata and a local adapter, without probing the channel."""
    if not isinstance(source,dict) or set(source)-{'platform','entry_project','session_key','chat_type','chat_id','thread_id','thread_root'}:
        raise Invalid('Chat context accepts platform, entry_project, session_key and optional chat_type, chat_id, thread_id, thread_root')
    if source.get('platform') not in ('feishu','lark') or not all(isinstance(source.get(k),str) and source[k] for k in ('entry_project','session_key')):
        raise Invalid('Chat context requires platform, entry project and session key')
    parts=source['session_key'].split(':',3)
    root=parts[3] if len(parts)==4 and parts[2]=='root' else None
    thread=parts[3] if len(parts)==4 and parts[2]=='thread' else None
    context=dict(source,chat_id=source.get('chat_id') or (parts[1] if len(parts)>1 else ''),
                 chat_type=source.get('chat_type','unknown'),thread_root=root or source.get('thread_root'))
    if thread and context['thread_root']==thread:context['thread_root']=None
    if thread:context.setdefault('thread_id',thread)
    if context['chat_type'] not in ('p2p','group','unknown'):raise Invalid('Invalid chat type')
    sender=entry_sender(comm,context)
    binding={'id':'conversation-'+digest([comm.settings()['instance_id'],source,sender])[:40],
             'group_id':None,'enabled':True,'sender_instance':comm.settings()['instance_id'],
             'level':'key','conversation':context}
    with comm.transaction() as db:
        db.execute('INSERT OR IGNORE INTO communication_notification_bindings VALUES (?,?)',(binding['id'],json.dumps(dict(binding,sender=sender))))
    return resolve(comm,binding['id'])


def remember_context(comm,db,entry,receipt):
    """Learn channel facts only from the selected adapter's delivery receipt."""
    checked=receipt.get('conversation') if isinstance(receipt,dict) else None
    if not isinstance(checked,dict) or checked.get('chat_type') not in ('p2p','group','unknown'):return
    checked={k:checked.get(k) for k in ('platform','chat_id','chat_type','session_key','thread_root','entry_project','thread_id') if k in checked}
    expected=entry['conversation']
    if any(checked.get(k)!=expected.get(k) for k in ('platform','chat_id','session_key','entry_project')):return
    if expected.get('chat_type') not in ('unknown',checked['chat_type']):return
    row=db.execute('SELECT document FROM communication_notification_bindings WHERE id=?',(entry['id'],)).fetchone()
    binding=json.loads(row[0]) if row else entry
    current=binding['conversation']
    if any(current.get(k)!=expected.get(k) for k in ('platform','chat_id','session_key','entry_project')):return
    if current.get('chat_type') in ('p2p','group'):
        if checked['chat_type'] not in ('unknown',current['chat_type']):return
        checked['chat_type']=current['chat_type']
    for key in ('thread_root','thread_id'):
        saved=current.get(key)
        # Legacy thread records stored the topic ID in the root field.
        parts=current['session_key'].split(':',3)
        if key=='thread_root' and len(parts)==4 and parts[2]=='thread' and saved==parts[3]:saved=None
        if saved and checked.get(key) and saved!=checked[key]:return
        if saved and not checked.get(key):checked[key]=saved
    if row:
        binding['conversation']=copy.deepcopy(checked)
        db.execute('UPDATE communication_notification_bindings SET document=? WHERE id=?',(json.dumps(binding),entry['id']))
    entry['conversation']=copy.deepcopy(checked)


def resolve(comm, ident, include_sender=False, refresh_sender=False):
    with comm.store.connection() as db:
        row=db.execute('SELECT document FROM communication_notification_bindings WHERE id=?',(ident,)).fetchone()
    binding=json.loads(row[0]) if row else {}
    if 'conversation' not in binding or binding.get('sender_instance')!=comm.settings()['instance_id']:
        raise Invalid('Unknown conversation on this platform')
    # Resolve an unselected transport after configuration is fixed; freeze it once chosen.
    if refresh_sender and binding.get('sender',{}).get('configuration_error'):
        sender=entry_sender(comm,binding['conversation'])
        if not sender.get('configuration_error'):
            binding['sender']=sender
            with comm.transaction() as db:
                db.execute("UPDATE communication_notification_bindings SET document=? WHERE id=? AND json_extract(document,'$.sender.configuration_error') IS NOT NULL",(json.dumps(binding),ident))
                binding=json.loads(db.execute('SELECT document FROM communication_notification_bindings WHERE id=?',(ident,)).fetchone()[0])
    return {k:copy.deepcopy(v) for k,v in binding.items() if include_sender or k!='sender'}


def bot_binding(comm,agent,group_id=None,freeze=False):
    bot=agent.get('notification_bot')
    route=agent.get('notification_route')
    if bot:
        from loop_anything.runtime.cc_connect import sender as bridge_sender
        sender=bridge_sender(bot)
    elif route:
        from loop_anything.runtime.notifications import resolve_outlet
        config=comm.store.notification_channels()['channels'].get(route)
        sender=resolve_outlet(config) if config else None
    else:return None
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
    # Refresh cached channel facts learned by the sending adapter.
    if entry.get('sender_instance')==comm.settings()['instance_id']:
        entry=resolve(comm,entry['id'],refresh_sender=True)
    context=entry['conversation']
    route={'policy':'conversation','reason':'entry_bot','sender_instance':entry['sender_instance'],
           'chat_id':context['chat_id'],'thread_root':context.get('thread_root'),'binding_id':entry['id']}
    if context['chat_type']!='p2p' and state in ('running','completed','failed'):
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
