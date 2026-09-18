"""Install this local distribution in an isolated environment and create a launcher."""
import argparse
from pathlib import Path
import shlex
import subprocess
import sys
import venv

from loop_anything.paths import data_directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=data_directory() / 'app', help='Application directory; runtime data is stored separately')
    parser.add_argument('--package', type=Path, help='Local source directory or wheel to install (default: bundled wheel, otherwise this source directory)')
    args = parser.parse_args()
    if sys.version_info < (3, 9):
        parser.error('Python 3.9 or newer is required')
    distribution = Path(__file__).resolve().parent
    wheels = list(distribution.glob('loop_anything-*.whl'))
    if not args.package and len(wheels) > 1:
        parser.error('Multiple wheels found; select one with --package')
    source = (args.package or (wheels[0] if wheels else distribution)).expanduser().resolve()
    if not source.exists():
        parser.error('Local package does not exist: ' + str(source))
    prefix = args.prefix.expanduser().resolve()
    environment = prefix / 'venv'
    venv.EnvBuilder(with_pip=True).create(environment)
    windows = sys.platform == 'win32'
    python = environment / ('Scripts/python.exe' if windows else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', '--disable-pip-version-check', 'install', '--upgrade', '--no-deps', str(source)], check=True)
    if windows:
        launcher = prefix / 'Loop Anything.cmd'
        launcher.write_text('@echo off\n"%~dp0venv\\Scripts\\python.exe" -I -m loop_anything %*\nif errorlevel 1 pause\n', encoding='ascii')
    else:
        launcher = prefix / ('Loop Anything.command' if sys.platform == 'darwin' else 'loop-anything')
        launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(str(python)) + ' -I -m loop_anything "$@"\n', encoding='utf-8')
        launcher.chmod(0o755)
    print('\nInstalled. Open or run: ' + str(launcher))
    print('The launcher opens the platform; keep its terminal running. Ctrl+C exits.')
    print('CLI Python: ' + str(python))
    print('Install the platform manual into your Agent Skill directory:')
    print(str(python) + ' -m loop_anything skills --install-dir <Agent-Skill-directory> --url <platform-url>')
    print('No PATH, Agent settings, or system startup configuration was changed.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit('Installation failed: ' + str(exc))
