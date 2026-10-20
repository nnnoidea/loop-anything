"""Dispatch/read/control a named Agent through a team link; no platform daemon on the caller."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time
import uuid
from urllib.request import Request, urlopen

from team_transport import atomic_json, connect, join, choose, prepare_dispatch, envelope, default_team

END = {'completed','failed','cancelled','unavailable','not_selected'}


def wait_requests(read, request_ids, timeout=300, poll_interval=15):
    """Wait inside this script; timeout never withdraws or republishes work."""
    if not isinstance(request_ids,list) or not request_ids:
        raise ValueError('Supply distinct request_ids, or one request_id')
    for ident in request_ids:Client.valid_id(ident)
    if len(set(request_ids))!=len(request_ids):raise ValueError('Supply distinct request_ids')
    if type(timeout) not in (int,float) or not 0<=timeout<=86400:raise ValueError('timeout must be 0–86400 seconds')
    if type(poll_interval) not in (int,float) or not 1<=poll_interval<=300:raise ValueError('poll_interval must be 1–300 seconds')
    deadline=time.monotonic()+timeout;results={}
    while True:
        for ident in request_ids:
            if results.get(ident,{}).get('state') not in END:results[ident]=read(ident)
        finished=all(results[i].get('state') in END for i in request_ids)
        remaining=deadline-time.monotonic()
        if finished or remaining<=0:
            answer={'finished':finished,'timed_out':not finished}
            if len(request_ids)==1:answer['request']=results[request_ids[0]]
            else:answer['requests']=[results[i] for i in request_ids]
            return answer
        time.sleep(min(poll_interval,remaining))


def directory_result(result, name=None, agent_id=None, instance_id=None):
    if name is not None and (not isinstance(name,str) or not name.strip()):raise ValueError('name must be nonempty text')
    fields=('id','name','description','instance_id','machine_id','machine','machine_name','location','group_id','capabilities','online','enabled','busy','error')
    return {'agents':[{k:a[k] for k in fields if k in a} for a in result['agents']
        if (name is None or a.get('name','').casefold()==name.casefold()) and
           (agent_id is None or a.get('id')==agent_id) and (instance_id is None or a.get('instance_id')==instance_id)],
        **{k:result[k] for k in ('self','instance_id','default_team') if k in result},
        **({'team':{k:result['team'][k] for k in ('id','name','link','transport') if k in result['team']}} if 'team' in result else {})}


class Client:
    def __init__(self, directory):
        self.directory=Path(directory).expanduser()
        self.file=self.directory/'connection.json'
        self.config=json.loads(self.file.read_text()) if self.file.exists() else {}
    def teams(self):
        teams=dict(self.config.get('teams',{}))
        old=self.config.get('team')
        if old:teams.setdefault(old['id'],old)
        return teams
    def team(self, group_id=None):
        teams=self.teams()
        selected=group_id or default_team(teams,self.config.get('default_team') or (self.config.get('team') or {}).get('id'))
        if selected not in teams:raise ValueError('Join a team link; specify group_id if multiple teams share the highest priority')
        if not teams[selected].get('enabled',True):raise ValueError('This team is disabled for new requests')
        return teams[selected]
    def save_teams(self, teams, preferred=None):
        selected=default_team(teams,preferred)
        # Keep the old single-team field as a compatibility alias, not the connection registry.
        self.config.update(teams=teams,default_team=selected,team=teams.get(selected))
        atomic_json(self.file,self.config)
    def configure(self, link, **kwargs):
        team=join(link,**kwargs)
        teams=self.teams();teams[team['id']]=team
        self.directory.mkdir(parents=True,exist_ok=True)
        identity=self.directory/'identity.json'
        try:
            with identity.open('x') as f:json.dump({'origin':self.config.get('origin') or 'client-'+uuid.uuid4().hex},f)
        except FileExistsError:pass
        self.config['origin']=json.loads(identity.read_text())['origin']
        preferred=self.config.get('default_team') or (self.config.get('team') or {}).get('id')
        self.save_teams(teams,preferred)
        return {'team':team,'default_team':self.config['default_team'],'origin':self.config['origin']}
    def leave(self, group_id=None):
        team=self.team(group_id);teams=self.teams()
        teams[team['id']]=dict(team,enabled=False)
        self.save_teams(teams,self.config.get('default_team'))
        return {'disabled_team':team['id'],'default_team':self.config['default_team']}
    def media(self, group_id=None):
        return connect(self.team(group_id))
    def agent_directory(self, team):
        media=connect(team)
        return {'agents':[dict(a,online=time.time()-p.get('updated_at',0)<media.offline_seconds)
            for _,p in media.list('members') for a in p.get('agents',[])],
            'team':team}
    def agents(self, name=None, agent_id=None, instance_id=None, group_id=None):
        return directory_result(self.agent_directory(self.team(group_id)),name,agent_id,instance_id)
    def wait(self, args):
        ids=args.get('request_ids') or [args.get('request_id')]
        if not isinstance(ids,list) or not ids:raise ValueError('Supply request_ids or request_id')
        for ident in ids:self.valid_id(ident)
        minimum=max(connect(self.request_team(ident,args.get('group_id'))).interval for ident in ids)
        interval=args.get('poll_interval',minimum)
        if type(interval) not in (int,float) or not 1<=interval<=300:raise ValueError('poll_interval must be 1–300 seconds')
        return wait_requests(lambda ident:self.read(ident,args.get('group_id')),ids,
                             args.get('timeout',300),max(minimum,interval))
    def request_team(self, ident, group_id=None):
        self.valid_id(ident)
        saved=self.directory/'requests'/(ident+'.json')
        cache=self.directory/'results'/(ident+'.json')
        if not saved.exists() and not cache.exists():return self.team(group_id)
        value=json.loads((saved if saved.exists() else cache).read_text())
        team=value.get('team') or value.get('request_ref',{}).get('team')
        if not team:
            # Legacy raw envelopes identify their team; never substitute today's default.
            original=value['group_id'];team=self.teams().get(original)
            if not team and cache.exists():team=json.loads(cache.read_text()).get('team')
            if not team:raise ValueError('Reconnect the original team link for request '+ident+' ('+original+')')
        if group_id and group_id!=team['id']:raise ValueError('Request belongs to a different team')
        return team
    def request_record(self, ident):
        value=json.loads((self.directory/'requests'/(ident+'.json')).read_text())
        if 'request_ref' in value:
            ref=value['request_ref']
            try:return connect(ref['team']).get(ref['key'])
            except FileNotFoundError:raise ValueError('Original request was removed from team history')
        return value.get('packet',value)
    def read(self, ident, group_id=None):
        self.valid_id(ident)
        cache=self.directory/'results'/(ident+'.json')
        if cache.exists():return self.deliver_read_receipt(cache,json.loads(cache.read_text()))
        team=self.request_team(ident,group_id);media=connect(team)
        try:
            result=media.get('results/'+ident+'.json')
            if result.get('state') not in END:
                try:member=media.get('members/'+result['executor']+'.json')
                except FileNotFoundError:member={}
                if time.time()-member.get('updated_at',0)>media.offline_seconds:
                    result=dict(result,last_observed_state=result['state'],state='unknown',
                        state_hint='Receiver heartbeat is stale; execution may still be active. Do not republish as new work.')
            if result.get('state') in END and result.get('result_receipt'):
                saved=self.directory/'requests'/(ident+'.json')
                packet=self.request_record(ident) if saved.exists() else None
                if packet and packet['sender']==result.get('origin') and packet['assignment_id']==result.get('assignment_id'):
                    receipt=envelope(packet['payload'],'result_read',{'receipt':result['result_receipt']})
                    document={'request':result,'receipt':receipt,'team':team,'receipt_sent':False}
                    # Never authorize cloud cleanup before the complete answer is durable locally.
                    atomic_json(cache,document)
                    return self.deliver_read_receipt(cache,document)
            elif result.get('state') in END and team.get('transport')=='feishu_base':
                saved=self.directory/'requests'/(ident+'.json')
                if saved.exists():
                    packet=self.request_record(ident)
                    if packet['sender']==result.get('origin') and packet['assignment_id']==result.get('assignment_id'):
                        atomic_json(saved,{'id':ident,'request_ref':{'team':team,
                            'key':'messages/'+packet['target']+'/'+packet['id']+'.json'}})
            return result
        except FileNotFoundError:
            path=self.directory/'requests'/(ident+'.json')
            if not path.exists():raise ValueError('Unknown request ID')
            row=self.request_record(ident)['payload']
            result={k:row[k] for k in ('id','state','agent_id','executor','deadline','created_at')}
            if time.time()>row['deadline']:result.update(state='unknown',state_hint='Acceptance not observed before the deadline; inspect the receiver before retrying as new work.')
            return result
    def deliver_read_receipt(self, path, document):
        result=dict(document['request'])
        if not document.get('receipt_sent'):
            packet=document['receipt']
            try:
                connect(document['team']).put('messages/'+packet['target']+'/'+packet['id']+'.json',packet,immutable=True)
                document['receipt_sent']=True;atomic_json(path,document)
            except (OSError,ValueError):result['receipt_pending']=True
        return result

    @staticmethod
    def valid_id(ident):
        if not isinstance(ident,str) or not ident or len(ident)>100 or any(not(c.isascii() and (c.isalnum() or c in '_-')) for c in ident):
            raise ValueError('Invalid request ID')
    def submit(self, args, team=None):
        if 'agent_name' in args and (not isinstance(args['agent_name'],str) or not args['agent_name'].strip()):raise ValueError('Agent name must be nonempty text')
        ident=args.get('request_id') or 'request-'+uuid.uuid4().hex[:12];self.valid_id(ident)
        saved=self.directory/'requests'/(ident+'.json')
        # Retrying the same ID reuses the exact envelope, even after an uncertain publish.
        if saved.exists():
            team=self.request_team(ident,args.get('group_id'))
            packet=self.request_record(ident)
            original=packet['payload']
            for field in ('message','context','agent_id','session'):
                if field in args and original.get(field)!=args[field]:raise ValueError('Request ID already used with different '+field)
            if args.get('agent_name') and original.get('agent_label') and args['agent_name'].casefold()!=original['agent_label'].casefold():
                raise ValueError('Request ID already used with a different Agent name')
            if args.get('instance_id') and original['executor']!=args['instance_id']:raise ValueError('Request target changed')
        else:
            team=team or self.team(args.get('group_id'))
            if not isinstance(args.get('message'),str) or not args['message'].strip():raise ValueError('Describe the task')
            if not isinstance(args.get('context',{}),dict):raise ValueError('context must be an object')
            seconds=args.get('wait_seconds',300)
            if type(seconds) not in (float,int) or not 1<=seconds<=2592000:raise ValueError('wait_seconds must be 1–2592000')
            target=choose(self.agent_directory(team)['agents'],args.get('agent_id'),args.get('instance_id'),args.get('capability'),args.get('agent_name'))
            now=time.time();gid=team['id']
            row={'id':ident,'origin':self.config['origin'],'origin_name':'派单 Skill','group_id':gid,'scope_group_id':gid,
                 'location':'group','kind':'assistance','source':{},'message':args['message'],'context':args.get('context',{}),
                 'state':'pending','created_at':now,'deadline':now+seconds,'dispatch_client':True,'agent_label':target.get('name',target['id']),
                 'session':args.get('session',{'mode':'new'}),'result_schema':args.get('result_schema',{'type':'object'}),
                 'notification_route':args.get('notification_route','workspace'),'notification_level':args.get('notification_level','key'),
                 'notification_policy':'explicit' if 'notification_route' in args else 'actor_first','notification_level_explicit':'notification_level' in args}
            chat=args.get('chat_context')
            if chat is None and os.environ.get('CC_PROJECT') and os.environ.get('CC_SESSION_KEY','').split(':')[0] in ('feishu','lark'):
                chat={'platform':os.environ['CC_SESSION_KEY'].split(':')[0],'entry_project':os.environ['CC_PROJECT'],'session_key':os.environ['CC_SESSION_KEY']}
            if chat and 'notification_route' not in args:row['chat_context']=chat
            if args.get('previous_request_id'):row['previous_request_id']=args['previous_request_id']
            prepare_dispatch(row,target['instance_id'],target['id'])
            packet=envelope(row);atomic_json(saved,{'packet':packet,'team':team})
        media=connect(team)
        cache=self.directory/'results'/(ident+'.json')
        if cache.exists():return {'request':self.read(ident),'published':True}
        try:
            result=media.get('results/'+ident+'.json')
            if result.get('origin')==packet['sender'] and result.get('assignment_id')==packet['assignment_id']:
                return {'request':self.read(ident),'published':True}
        except FileNotFoundError:pass
        media.put('messages/'+packet['target']+'/'+packet['id']+'.json',packet,immutable=True)
        return {'request':self.read(ident),'published':True}
    def control(self, args):
        ident=args['request_id'];self.valid_id(ident)
        team=self.request_team(ident,args.get('group_id'))
        packet=self.request_record(ident)
        row=packet['payload'];action=args['action']
        if action=='followup':
            result=self.read(ident)
            if result['state'] not in END:raise ValueError('Wait for the previous request to finish')
            session={'mode':'new'}
            if args.get('resume',True):
                native=result.get('native_session') or {}
                if not native.get('id'):raise ValueError('No native session; explicitly choose resume=false')
                session={'mode':'resume','request_id':ident,'instance_id':row['executor'],'native_id':native['id']}
            return self.submit(dict(message=args['message'],agent_id=row['agent_id'],instance_id=row['executor'],
                previous_request_id=ident,session=session,context={'original_context':row['context'].get('original_context',row['context']),
                'previous_result':result.get('result')},**{k:row[k] for k in ('chat_context','notification_route','notification_level') if k in row and (k!='notification_route' or row['notification_policy']=='explicit')}),team=team)
        if action not in ('cancel','input'):raise ValueError('Choose cancel, input or followup')
        command=envelope(row,action,{'data':args.get('message',''),'reason':args.get('reason','')})
        connect(team).put('messages/'+row['executor']+'/'+command['id']+'.json',command,immutable=True)
        return {'request_id':ident,'control_published':action}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['join','leave','agents','submit','read','control','wait'])
    parser.add_argument('--arguments',default='{}',help='JSON or @file')
    parser.add_argument('--config-dir',default=os.environ.get('LOOP_ANYTHING_DISPATCH_HOME',str(Path.home()/'.config/loop-anything-dispatch')))
    parser.add_argument('--output',help='Save the complete response JSON to a file and print its location')
    parser.add_argument('--tool-url',help='Existing Loop scoped tool endpoint; preserves its wait/session scope')
    parser.add_argument('--platform-url',help='Receiver platform for explicitly local Agents or managed Loop registration')
    args=parser.parse_args()
    values=json.loads(Path(args.arguments[1:]).read_text() if args.arguments.startswith('@') else args.arguments)
    if args.operation=='submit' and not any(k in values for k in ('notification_route','conversation_id','chat_context')) and not values.get('source',{}).get('run_id') and os.environ.get('CC_PROJECT') and os.environ.get('CC_SESSION_KEY','').split(':')[0] in ('feishu','lark'):
        values['chat_context']={'platform':os.environ['CC_SESSION_KEY'].split(':')[0],
            'entry_project':os.environ['CC_PROJECT'],'session_key':os.environ['CC_SESSION_KEY']}
    if args.tool_url or args.platform_url:
        tool={'submit':'request_assistance','read':'read_assistance','control':'control_assistance','agents':'communication_status','wait':'read_assistance','leave':'communication_config'}.get(args.operation)
        if not tool:raise ValueError('Join a team using its link or communication_config(operation=team)')
        url=(args.tool_url or args.platform_url).rstrip('/')+'/api/tools'
        def invoke(arguments):
            req=Request(url,json.dumps({'tool':tool,'arguments':arguments}).encode(),{'Content-Type':'application/json','X-Loop-Anything':'workspace'})
            with urlopen(req,timeout=30) as response:result=json.load(response)
            if result.get('ok') is False:raise ValueError(json.dumps(result,ensure_ascii=False))
            return result
        if args.operation=='wait':
            common={k:v for k,v in values.items() if k not in ('request_id','request_ids','timeout','poll_interval')}
            result=wait_requests(lambda ident:invoke(dict(common,request_id=ident))['request'],
                                 values.get('request_ids') or [values.get('request_id')],
                                 values.get('timeout',300),values.get('poll_interval',15))
        elif args.operation=='agents':
            filters={k:values[k] for k in ('name','agent_id','instance_id') if k in values}
            result=directory_result(invoke({k:v for k,v in values.items() if k not in filters}),**filters)
        elif args.operation=='leave':result=invoke(dict(values,operation='leave'))
        else:result=invoke(values)
    else:
        client=Client(args.config_dir)
        if args.operation=='join':result=client.configure(**values)
        elif args.operation=='leave':result=client.leave(**values)
        elif args.operation=='agents':result=client.agents(**values)
        elif args.operation=='submit':result=client.submit(values)
        elif args.operation=='read':result={'request':client.read(values['request_id'],values.get('group_id'))}
        elif args.operation=='wait':result=client.wait(values)
        else:result=client.control(values)
    if args.output:
        output=Path(args.output).expanduser().resolve();atomic_json(output,result)
        brief={k:result[k] for k in ('finished','timed_out') if k in result}
        if 'request' in result:brief.update({k:result['request'].get(k) for k in ('id','state')})
        if 'requests' in result:brief['requests']=[{k:r.get(k) for k in ('id','state')} for r in result['requests']]
        result={'file':str(output),**brief}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False));sys.exit(2)
    except KeyboardInterrupt:
        print(json.dumps({'ok':False,'error':'Wait interrupted; requests remain active.'}));sys.exit(130)
