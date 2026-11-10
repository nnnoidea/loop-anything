"""Export the platform Skill. Author Skills stay bound to nodes in Loop packages."""
import io
import json
import sys
from pathlib import Path
import zipfile
from loop_anything.runtime.model import Invalid
from loop_anything.paths import platform_skill_directory


def install_skills(data, directory, replace=False):
    """Install only our generated archive; do not accept third-party ZIP paths."""
    root = Path(directory).expanduser().resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {Path(*Path(name).parts[1:]): archive.read(name) for name in archive.namelist()
                 if Path(name).parts[0] == 'platform'}
    folders = sorted({path.parts[0] for path in files})
    # Check the complete write set before creating anything; never follow links.
    for relative, content in files.items():
        target = root / relative
        if any(p.is_symlink() for p in (target, *target.parents) if p != root):
            raise Invalid('Skill destination contains a symbolic link: ' + str(target))
        if any(p.exists() and not p.is_dir() for p in target.parents):
            raise Invalid('Skill destination parent is not a directory: ' + str(target))
        if target.exists() and (not target.is_file() or (target.read_bytes() != content and not replace)):
            raise Invalid('Skill already differs at %s; choose another directory or use --replace to update generated files' % target)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {'directory': str(root), 'skills': folders,
            'check': ([sys.executable, str(root / 'loop-anything-platform' / 'scripts' / 'call.py'), 'check']
                      if 'loop-anything-platform' in folders else [sys.executable,'-m','loop_anything','local','--help'])}


def bundle(url, installation_url=None, only=None):
    source = platform_skill_directory()
    files = {}
    connection = json.dumps({'url': url}, ensure_ascii=False, indent=2)
    name = 'loop-anything-platform'
    prefix = 'platform/' + name + '/'
    for path in source.rglob('*'):
        if not path.is_file() or path.suffix not in ('.md', '.py', '.json', '.mjs', '.txt'):
            continue
        files[prefix + path.relative_to(source).as_posix()] = path.read_bytes()
    dispatch = source.parent / 'loop-anything-dispatch'
    for path in dispatch.rglob('*'):
        if path.is_file() and path.suffix in ('.md','.py','.json'):
            files['platform/loop-anything-dispatch/'+path.relative_to(dispatch).as_posix()]=path.read_bytes()
    local=source.parent/'loop-anything-local/SKILL.md'
    files['platform/loop-anything-local/SKILL.md']=local.read_bytes()
    from loop_anything.authoring_guidance import render_guide
    files[prefix + 'references/platform-capabilities.md'] = render_guide().encode('utf-8')
    files[prefix + 'connection.json'] = connection.encode('utf-8')
    entry = ('# Loop Anything · Agent Skills\n\n'
             '**English** | [简体中文](README.zh-CN.md)\n\n'
             'This bundle contains task-specific Skills for one client: service operations, dispatch, and local execution. Local execution uses install.py --role client; operations-only use needs no runtime installation.\n\n'
             '- [Platform Skill](platform/loop-anything-platform/SKILL.md): build and run Loops, inspect existing work, and configure receivers. Read references as needed.\n'
             '- [Dispatch Skill](platform/loop-anything-dispatch/SKILL.md): dispatch and read results through one team link; only receiving requires a running platform.\n'
             '- [Local scheduling Skill](platform/loop-anything-local/SKILL.md): the client’s independent timers, conditions, and team receiving without a web UI or service database.\n'
             '- Business handbooks and node Skills ship with Loop packages and are read through platform tools when working on a Task.\n\n')
    entry_zh = ('# Loop Anything · Agent Skills\n\n'
                '[English](README.md) | **简体中文**\n\n'
                '本包是同一客户端按场景读取的 Skill：服务操作、派单、本机执行。本机执行使用 install.py --role client 安装；仅操作服务无需安装运行程序。Skill 正文为英文。\n\n'
                '- [平台 Skill](platform/loop-anything-platform/SKILL.md)：构建、运行 Loop，查看已有工作，配置接单端；详细说明按需读取。\n'
                '- [独立派单 Skill](platform/loop-anything-dispatch/SKILL.md)：一个团队链接即可派单、查结果；仅接单需要运行平台。\n'
                '- [本机调度 Skill](platform/loop-anything-local/SKILL.md)：客户端的独立定时/条件任务与团队接单，不启动网页或服务数据库。\n'
                '- 业务说明及节点 Skill 随 Loop 包交付，处理任务时通过平台工具读取。\n\n')
    if installation_url:
        entry += '[Download the platform installer](' + installation_url + '). Follow the README.md in the extracted package.\n'
        entry_zh += '[下载平台安装包](' + installation_url + ')。首次安装步骤见解压后的 README.zh-CN.md。\n'
    else:
        entry += 'For first-time installation, start with README.md in the source repository.\n'
        entry_zh += '首次安装平台请阅读源码仓库的 README.zh-CN.md。\n'
    entry += ('\n**For the installation agent:** before installing the runtime, ask whether this machine needs the server, the client, or both. '
              'Follow an existing explicit choice without asking again. The server stores Loops/Runs, advances workflows, and provides the web interface; '
              'the client operates the server and optionally executes work locally. Use `--role server` or `--role client`; for both, install server once. '
              'Receiving and personal jobs require an explicit start.\n')
    entry_zh += ('\n**给安装 Agent：** 安装程序前先询问本机需要服务端、客户端，还是兼任两者；已有明确选择时直接沿用，不重复询问。'
                 '服务端保存 Loop/Run、推进流程并提供网页；客户端操作服务端，也可按需在本机执行任务。'
                 '安装使用 `--role server` 或 `--role client`；兼任只需安装一次 server。接单和个人任务需要明确启动。\n')
    files['README.md'] = entry.encode('utf-8')
    files['README.zh-CN.md'] = entry_zh.encode('utf-8')
    if only=='local':files={k:v for k,v in files.items() if k.startswith('platform/loop-anything-local/')}
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return raw.getvalue()
