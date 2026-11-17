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
                      if 'loop-anything-platform' in folders else [sys.executable,'-m','loop_anything','client','local','--help'])}


def bundle(url, installation_url=None, only=None):
    source = platform_skill_directory()
    files = {}
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
    files[prefix + 'platform-source.json'] = json.dumps({'platform_url':url},ensure_ascii=False,indent=2).encode('utf-8')
    entry = ('# Loop Anything · Agent Skills\n\n'
             '**English** | [简体中文](README.zh-CN.md)\n\n'
             'Skills for Loop Anything, organized by capability: platform work, dispatch, and local scheduling/execution. Use local and team spaces through one application; operations-only use can load these Skills without installing the runtime.\n\n'
             '- [Platform Skill](platform/loop-anything-platform/SKILL.md): build and run Loops, inspect existing work, and configure receivers. Read references as needed.\n'
             '- [Dispatch Skill](platform/loop-anything-dispatch/SKILL.md): dispatch and read results through one team link; only receiving requires a running platform.\n'
             '- [Local scheduling Skill](platform/loop-anything-local/SKILL.md): personal timers, conditions, and team receiving; can run independently of the workspace.\n'
             '- Business handbooks and node Skills ship with Loop packages and are read through platform tools when working on a Task.\n\n')
    entry_zh = ('# Loop Anything · Agent Skills\n\n'
                '[English](README.md) | **简体中文**\n\n'
                '本包是 Loop Anything 按能力组织的 Skill：平台工作、派单、本机调度与执行。通过一个软件使用本地和团队空间；仅操作已有平台时可直接使用 Skill，无需安装运行程序。Skill 正文为英文。\n\n'
                '- [平台 Skill](platform/loop-anything-platform/SKILL.md)：构建、运行 Loop，查看已有工作，配置接单端；详细说明按需读取。\n'
                '- [独立派单 Skill](platform/loop-anything-dispatch/SKILL.md)：一个团队链接即可派单、查结果；仅接单需要运行平台。\n'
                '- [本机调度 Skill](platform/loop-anything-local/SKILL.md)：个人定时/条件任务与团队接单，可独立于工作台运行。\n'
                '- 业务说明及节点 Skill 随 Loop 包交付，处理任务时通过平台工具读取。\n\n')
    if installation_url:
        entry += '[Download the platform installer](' + installation_url + '). Follow the README.md in the extracted package.\n'
        entry_zh += '[下载平台安装包](' + installation_url + ')。首次安装步骤见解压后的 README.zh-CN.md。\n'
    else:
        entry += 'For first-time installation, start with README.md in the source repository.\n'
        entry_zh += '首次安装平台请阅读源码仓库的 README.zh-CN.md。\n'
    entry += ('\n**Installation:** install Loop Anything with `python3 install.py` for a local workspace, task tools, and team connections. New profiles select automatically from recorded addresses, preferring team when both exist. '
              'Installation has one path; do not ask for a role or deployment mode. Configure a team with `loop-anything spaces --team-url URL`; '
              'override the preference with `--default local|team` or restore `--default auto`. Installing Skills never changes that personal choice or uploads local work. '
              'Receiving and schedules require an explicit start. This bundle was exported by '+url+'.\n')
    entry_zh += ('\n**给安装 Agent：** 运行 `python3 install.py` 安装 Loop Anything，一次具备本地工作台、任务工具和团队连接能力，未指定偏好时按已记录地址自动选择，两个都有时优先团队；无需再询问安装角色。'
                 '团队地址由 `loop-anything spaces --team-url URL` 配置，`--default local|team` 指定默认，`--default auto` 恢复自动选择。'
                 '更新 Skill 不修改个人空间选择，不上传本地工作；接单和定时任务须明确启动。本包导出来源：'+url+'。\n')
    files['README.md'] = entry.encode('utf-8')
    files['README.zh-CN.md'] = entry_zh.encode('utf-8')
    if only=='local':files={k:v for k,v in files.items() if k.startswith('platform/loop-anything-local/')}
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return raw.getvalue()
