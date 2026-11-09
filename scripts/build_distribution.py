"""Build a local wheel plus an installation ZIP; no publishing or user installation."""
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from loop_anything.paths import DEFAULT_URL
from loop_anything.packaging.skill_bundle import bundle
output = root / 'dist'
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as folder:
    source = Path(folder) / 'source'
    source.mkdir()
    shutil.copytree(root / 'loop_anything', source / 'loop_anything', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(root / 'skills', source / 'skills', ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
    shutil.copy2(root / 'pyproject.toml', source / 'pyproject.toml')
    subprocess.run([sys.executable, '-m', 'pip', '--disable-pip-version-check', 'wheel', str(source),
                    '--no-deps', '--no-build-isolation', '--wheel-dir', folder], check=True)
    wheel = next(Path(folder).glob('loop_anything-*.whl'))
    (output / wheel.name).write_bytes(wheel.read_bytes())
    version = wheel.name.split('-')[1]
    filename = output / ('loop-anything-' + version + '-install.zip')
    prefix = 'loop-anything-' + version + '/'
    with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(wheel, prefix + wheel.name)
        archive.writestr(prefix + 'README.md',
                         '# Loop Anything installation package\n\n'
                         '**English** | [简体中文](README.zh-CN.md)\n\n'
                         'Ask your Agent to follow the [installation and upgrade guide](docs/installation.md) (Chinese) to configure the platform and Skills.\n\n'
                         'For everyday use, see the [user guide](docs/user-guide.md) (Chinese). For building and running Loops, use the English [platform Skill](skills/loop-anything-platform/SKILL.md).\n')
        archive.writestr(prefix + 'README.zh-CN.md',
                         '# Loop Anything 安装包\n\n'
                         '[English](README.md) | **简体中文**\n\n'
                         '请让你的 Agent 按[安装与升级说明](docs/installation.md)完成平台和 Skill 配置。\n\n'
                         '日常使用见[使用手册](docs/user-guide.md)，构建与运行见[平台 Skill](skills/loop-anything-platform/SKILL.md)。\n')
        for name in ('install.py', 'pyproject.toml'):
            archive.write(root / name, prefix + name)
        for directory in ('loop_anything', 'skills'):
            for source in sorted((root / directory).rglob('*')):
                if source.is_file() and '__pycache__' not in source.parts and source.suffix in ('.py', '.md', '.json', '.html', '.css', '.js', '.mjs', '.txt'):
                    archive.write(source, prefix + source.relative_to(root).as_posix())
        for name in ('installation.md', 'agent-integration.md', 'timeline.md', 'loop-packages.md', 'implementation-selection.md', 'development.md', 'user-guide.md'):
            archive.write(root / 'docs' / name, prefix + 'docs/' + name)
    print(filename)
    # Static entry and Skills can be read before installing or running the platform.
    entry = output / 'agent-entry'
    if entry.exists():
        shutil.rmtree(entry)  # This directory is generated exclusively by this builder.
    entry.mkdir()
    import io
    with zipfile.ZipFile(io.BytesIO(bundle(DEFAULT_URL, installation_url='../' + filename.name))) as skills:
        for name in skills.namelist():
            target = entry / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(skills.read(name))
    print(entry / 'README.md')

# A sender can install just this Skill, without the wheel or a running platform.
with zipfile.ZipFile(output / 'loop-anything-dispatch.zip','w',zipfile.ZIP_DEFLATED) as archive:
    dispatch = root / 'skills/loop-anything-dispatch'
    for path in dispatch.rglob('*'):
        if path.is_file() and path.suffix in ('.md','.py'):
            archive.write(path,'loop-anything-dispatch/'+path.relative_to(dispatch).as_posix())

with zipfile.ZipFile(output / 'loop-anything-local.zip','w',zipfile.ZIP_DEFLATED) as archive:
    archive.write(root/'skills/loop-anything-local/SKILL.md','loop-anything-local/SKILL.md')
