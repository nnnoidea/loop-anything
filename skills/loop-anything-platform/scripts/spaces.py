"""Personal platform addresses. Standalone Skills and the installed client share this file."""
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager
from urllib.parse import urlsplit


def path():
    return Path(os.environ.get('LOOP_ANYTHING_SPACES') or Path.home()/'.config/loop-anything/spaces.json').expanduser().resolve()


def base_url(value, local=False, web=False):
    if not isinstance(value,str) or not value.strip():raise ValueError('Supply a platform address')
    value=value.strip().rstrip('/')
    parsed=urlsplit(value)
    if parsed.scheme=='nas' and not local and not web:
        if parsed.netloc or not parsed.path.startswith('/') or parsed.query or parsed.fragment:
            raise ValueError('Use nas:///absolute/mounted/team/path')
    elif parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an HTTP(S) platform base URL without credentials, query or fragment')
    if local and parsed.hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('The local platform must use a loopback address')
    if parsed.scheme in ('http','https'):_=parsed.port
    return value


def validate(config):
    if not isinstance(config,dict) or set(config)!={'revision','default_space','local_url','team_url','team_web_url','local_registry'}:
        raise ValueError('Invalid personal spaces configuration')
    if type(config['revision']) is not int or config['revision']<0:raise ValueError('Invalid configuration revision')
    if config['default_space'] not in ('auto','local','team'):raise ValueError('Choose auto, local or team')
    config=dict(config)
    if config['local_url'] is not None:config['local_url']=base_url(config['local_url'],local=True)
    for field in ('team_url','team_web_url'):
        if config[field] is not None:config[field]=base_url(config[field],web=field=='team_web_url')
    if config['default_space'] in ('local','team') and not config[config['default_space']+'_url']:
        raise ValueError('Record the '+config['default_space']+' address before selecting it')
    if config['local_registry'] is not None and (not isinstance(config['local_registry'],str) or not Path(config['local_registry']).is_absolute()):
        raise ValueError('local_registry must be an absolute path')
    return config


def read():
    location=path()
    if not location.exists():return dict(revision=0,default_space='auto',local_url=None,team_url=None,team_web_url=None,local_registry=None)
    return validate(json.loads(location.read_text(encoding='utf-8')))


@contextmanager
def configuration_lock():
    location=path();location.parent.mkdir(parents=True,exist_ok=True)
    with location.with_suffix('.lock').open('a+b') as stream:
        if os.name=='nt':
            import msvcrt
            if stream.tell()==0:stream.write(b'0');stream.flush()
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX)
        try:yield
        finally:
            if os.name=='nt':stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)


def configure(change, revision=None):
    with configuration_lock():
        config=read()
        if revision is not None and revision!=config['revision']:raise ValueError('Space configuration changed; reread before saving')
        if not isinstance(change,dict) or not change or set(change)-{'default_space','local_url','team_url','team_web_url','local_registry'}:
            raise ValueError('Supply default_space, local_url, team_url, team_web_url or local_registry')
        updated=validate(dict(config,**change))
        if updated==config:return config
        updated['revision']+=1
        location=path();location.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=location.parent,delete=False) as stream:
            temporary=Path(stream.name);stream.write(json.dumps(updated,ensure_ascii=False,indent=2)+'\n')
        try:temporary.replace(location)
        finally:temporary.unlink(missing_ok=True)
        return updated


def selected_space(config):
    if config['default_space']!='auto':return config['default_space']
    if config['team_url']:return 'team'
    if config['local_url']:return 'local'
    return None


def resolve(url=None, space=None):
    if url is not None and space is not None:raise ValueError('Supply --url or --space, not both')
    if url is not None:
        if not isinstance(url,str) or not url.strip():raise ValueError('Supply a nonempty explicit platform URL')
        return url.strip().rstrip('/')
    config=read();selected=space or selected_space(config)
    if selected is None:raise ValueError('No platform address is recorded. Configure local_url or team_url with spaces first. No request was sent.')
    if selected not in ('local','team'):raise ValueError('Choose local or team')
    target=config[selected+'_url']
    if not target:raise ValueError(selected.capitalize()+' space is not configured; configure it explicitly. No request was sent.')
    return target


def browser_url(config):
    selected=selected_space(config)
    if selected is None:raise ValueError('No platform address is recorded. Configure local_url or team_url first.')
    if selected=='local':return config['local_url']
    target=config['team_web_url'] or config['team_url']
    if not target or target.startswith('nas:'):raise ValueError('Configure team_web_url to open the team webpage; tool calls may still use NAS')
    return target


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-url');parser.add_argument('--team-url');parser.add_argument('--team-web-url')
    parser.add_argument('--default',dest='default_space',choices=['auto','local','team'])
    parser.add_argument('--local-registry');parser.add_argument('--clear-team',action='store_true')
    parser.add_argument('--revision',type=int)
    args=parser.parse_args(argv)
    change={k:getattr(args,k) for k in ('local_url','team_url','team_web_url','default_space','local_registry') if getattr(args,k) is not None}
    if args.clear_team:
        if args.team_url or args.team_web_url or args.default_space=='team':parser.error('--clear-team conflicts with a team address/default')
        change.update(team_url=None,team_web_url=None)
        if args.default_space is None and read()['default_space']=='team':change['default_space']='auto'
    try:config=configure(change,args.revision) if change else read()
    except (OSError,ValueError) as exc:parser.error(str(exc))
    print(json.dumps(dict(config,selected_space=selected_space(config),path=str(path())),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
