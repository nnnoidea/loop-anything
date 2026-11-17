"""Owner-configured NAS discovery; joining and exposing Agents remain explicit."""
import json
from pathlib import Path

from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.store import uid

MANIFEST = '.loop-anything-space.json'


def manifest(path):
    from loop_anything.runtime.communication import identifier
    if path.stat().st_size > 16384:raise Invalid('Discovery manifest is too large')
    value=json.loads(path.read_text())
    if not isinstance(value,dict) or value.get('version')!=1:raise Invalid('Unsupported discovery manifest')
    identifier(value.get('id'))
    if not isinstance(value.get('name'),str) or not value['name'].strip() or len(value['name'])>256:raise Invalid('Discovery name must contain 1–256 characters')
    if not isinstance(value.get('description',''),str) or len(value.get('description',''))>4000:raise Invalid('Group description must contain at most 4000 characters')
    return {k:value[k] for k in ('version','id','name','description') if k in value}


def space_root(config, ident):
    space=config.get('spaces',{}).get(ident)
    if not space:raise Invalid('Configure this shared space on this machine first')
    root=Path(space['path'])
    if not root.is_dir() or manifest(root/MANIFEST)['id']!=ident:
        raise Conflict('Shared space is unavailable or its identity changed; check the NAS mount')
    return root


def groups_root(root):
    folder=root/'groups'
    if folder.is_symlink():raise Invalid('Shared-space groups directory must not be a symlink')
    return folder


def configure(comm, args):
    from loop_anything.runtime.communication import atomic_json
    value=args.get('path')
    if not isinstance(value,str) or not value.strip():raise Invalid('Supply the mounted NAS directory')
    root=Path(value).expanduser().resolve()
    if not root.is_dir():raise Invalid('Mount the shared directory first; a missing NAS path will not be created')
    path=root/MANIFEST
    if not path.exists():
        name=args.get('name') or root.name
        if not isinstance(name,str) or not name.strip() or len(name)>256:raise Invalid('Supply a shared-space name of 1–256 characters')
        # Exclusive creation keeps simultaneous first-time configurations from replacing identity.
        try:
            with path.open('x',encoding='utf-8') as out:
                json.dump({'version':1,'id':uid('space'),'name':name},out,ensure_ascii=False)
        except FileExistsError:pass
    info=manifest(path)
    if args.get('space_id') and args['space_id']!=info['id']:raise Conflict('This is a different shared space')
    probe=root/('.loop-check-'+uid('probe'))
    try:
        atomic_json(probe,{'space_id':info['id']})
        if json.loads(probe.read_text())!={'space_id':info['id']}:raise Invalid('Shared-space read-back mismatch')
    finally:probe.unlink(missing_ok=True)
    with comm.transaction() as db:
        config=comm.settings(db)
        if args.get('revision') is not None and args['revision']!=config['revision']:raise Conflict('Communication configuration changed')
        old=config.setdefault('spaces',{}).get(info['id'])
        # Preserve membership and identity when the same NAS has a new local mount path.
        if old and old['path']!=str(root):
            for group in config['groups'].values():
                if group.get('space_id')==info['id']:
                    target=groups_root(root)/group['relative_path']/'agents'
                    if target.parent.is_symlink() or target.is_symlink() or manifest(target/'group.json')['id']!=group['id']:
                        raise Conflict('Joined group identity changed at the new mount')
                    group.update(path=str(target),link=target.parent.as_uri())
        config['spaces'][info['id']]=dict(info,path=str(root))
        config['revision']+=1
        db.execute('UPDATE communication_settings SET document=? WHERE id=1',(json.dumps(config),))
    return {'configuration':config,'space_id':info['id'],'read_write_verified':True,'multi_machine_verified':False}


def group_path(config, args):
    from loop_anything.runtime.communication import identifier
    root=groups_root(space_root(config,args['space_id']))
    if args.get('create'):
        if not isinstance(args.get('name'),str) or not args['name'].strip():raise Invalid('Supply a new group name')
        relative=uid('group')
    else:
        relative=identifier(args.get('relative_path'))
        identifier(args.get('group_id'))  # Join the identity that the user selected, not a replacement.
    path=root/relative
    if path.is_symlink() or (path/'agents').is_symlink():raise Invalid('Group discovery does not follow symlinks')
    return path,relative


def discover(comm):
    config=comm.settings();rows=[]
    for space in config.get('spaces',{}).values():
        row=dict(space,groups=[],errors=[])
        try:
            folder=groups_root(space_root(config,space['id']))
            if folder.exists():
                for path in sorted(folder.iterdir()):
                    if path.is_symlink() or (path/'agents').is_symlink() or not path.is_dir():continue
                    try:
                        from loop_anything.runtime.communication import identifier
                        identifier(path.name)
                        group=manifest(path/'agents'/'group.json')
                        joined=config['groups'].get(group['id'],{})
                        row['groups'].append(dict(group,relative_path=path.name,joined=bool(joined.get('enabled'))))
                    except (OSError,ValueError,Invalid,TypeError,KeyError) as exc:
                        row['errors'].append({'directory':path.name,'error':str(exc)})
        except (OSError,ValueError,Invalid,Conflict,TypeError,KeyError) as exc:row['error']=str(exc)
        rows.append(row)
    return rows


def join_instructions(comm, group_id):
    config=comm.settings();group=config['groups'].get(group_id)
    if not group:raise Invalid('Unknown group')
    return {'group_id':group_id,'team_link':group['link'],'instructions':
        '派单：安装 loop-anything-dispatch Skill，join 保存这个团队链接。接单：安装并运行平台，'
        'communication_config(operation=team,link=...) 接入；由用户确认主要任务后配置具名 Agent。'
        '内部表结构自动管理，无需记表 ID。NAS 使用接收机器上的实际挂载路径。'}
