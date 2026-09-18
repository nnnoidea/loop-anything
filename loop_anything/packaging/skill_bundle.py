"""Export the platform Skill. Author Skills stay bound to nodes in Loop packages."""
import io
import json
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
            'check': ['python', str(root / 'loop-anything-platform' / 'scripts' / 'call.py'), 'check']}


def bundle(url, installation_url=None):
    source = platform_skill_directory()
    files = {}
    connection = json.dumps({'url': url}, ensure_ascii=False, indent=2)
    name = 'loop-anything-platform'
    prefix = 'platform/' + name + '/'
    for path in source.rglob('*'):
        if not path.is_file() or path.suffix not in ('.md', '.py', '.json'):
            continue
        files[prefix + path.relative_to(source).as_posix()] = path.read_bytes()
    files[prefix + 'connection.json'] = connection.encode('utf-8')
    entry = ('# Loop Anything · 平台操作 Skill\n\n'
             '本包提供安装到 Agent 的平台操作手册、调用脚本与连接配置。\n\n'
             '- [平台 Skill](platform/loop-anything-platform/SKILL.md)：按需读取 Loop 构建与 Timeline 操作说明。\n'
             '- 作者说明及节点 Skill 随 Loop 包交付，处理任务时通过平台工具读取。\n\n')
    if installation_url:
        entry += '[下载平台安装包](' + installation_url + ')。首次安装步骤见解压后的 README.md。\n'
    else:
        entry += '首次安装平台请阅读源码仓库的 README.md。\n'
    files['README.md'] = entry.encode('utf-8')
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return raw.getvalue()
