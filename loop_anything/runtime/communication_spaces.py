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
                    target=groups_root(root)/group['relative_path']
                    if target.is_symlink() or manifest(target/'group.json')['id']!=group['id']:
                        raise Conflict('Joined group identity changed at the new mount')
                    group['path']=str(target)
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
    if path.is_symlink():raise Invalid('Group discovery does not follow symlinks')
    return path,relative


def discover(comm):
    config=comm.settings();rows=[]
    for space in config.get('spaces',{}).values():
        row=dict(space,groups=[],errors=[])
        try:
            folder=groups_root(space_root(config,space['id']))
            if folder.exists():
                for path in sorted(folder.iterdir()):
                    if path.is_symlink() or not path.is_dir():continue
                    try:
                        from loop_anything.runtime.communication import identifier
                        identifier(path.name)
                        group=manifest(path/'group.json')
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
    space=config.get('spaces',{}).get(group.get('space_id'))
    where=(f"配置共享空间「{space['name']}」（ID：{space['id']}），在发现列表中选择此群组。\n群组相对目录：groups/{group['relative_path']}"
           if space else '在“直接加入已有群组目录”中填写这个群组在目标机器上的实际挂载路径。')
    return {'group_id':group_id,'instructions':f"加入 Loop Anything 群组「{group['name']}」\n群组 ID：{group_id}\n"
        '1. 向共享空间提供者取得 NAS 地址和访问权限，先在目标机器挂载。\n'
        f'2. 打开“Agent 通信”。{where}\n'
        '3. 核对群组 ID 后点击加入。各机器本地挂载路径可以不同。\n'
        '4. 如需提供服务，先向用户询问并确认 Agent 主要任务及开放群组，再填写说明、配置本机 CLI/工作目录/恢复命令并确认公开；Agent 不可自拟说明代替用户确认。也可只调用别人。\n'
        '5. 在成员列表检查对方 Agent，给 Loop / Run 绑定群组或给普通对话设置默认群组。\n'
        '群组 ID 仅用于核对身份，NAS 权限负责访问控制。此说明不包含命令或凭据。'}
