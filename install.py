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
    parser.add_argument('--no-service', action='store_true', help='Install without registering a macOS background service')
    parser.add_argument('--db', type=Path, help='Existing workspace for the macOS service; upgrades retain the saved workspace')
    parser.add_argument('--port', type=int, help='macOS service port; upgrades retain the saved port')
    parser.add_argument('--host', help='macOS service bind address; default is loopback')
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
    background = sys.platform == 'darwin' and not args.no_service
    if background:
        from loop_anything.runtime.service import configuration, manage, definition, available
        previous = configuration()
        expected = str(environment / 'bin/python')
        if previous and previous['ProgramArguments'][0] != expected:
            parser.error('Another application directory owns the service; use its --prefix or remove that service first')
        if previous:
            manage('stop')
        available(definition(expected, args.db, args.port, args.host, previous))
    venv.EnvBuilder(with_pip=True).create(environment)
    windows = sys.platform == 'win32'
    python = environment / ('Scripts/python.exe' if windows else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', '--disable-pip-version-check', 'install', '--upgrade', '--force-reinstall', '--no-deps', str(source)], check=True)
    if windows:
        launcher = prefix / 'Loop Anything.cmd'
        launcher.write_text('@echo off\n"%~dp0venv\\Scripts\\python.exe" -I -m loop_anything %*\nif errorlevel 1 pause\n', encoding='ascii')
    else:
        launcher = prefix / ('Loop Anything.command' if sys.platform == 'darwin' else 'loop-anything')
        command = shlex.quote(str(python)) + ' -I -m loop_anything'
        script = '#!/bin/sh\n'
        if background:
            script += 'if [ "$#" -eq 0 ]; then\n  exec ' + command + ' service start --open\nfi\n'
        launcher.write_text(script + 'exec ' + command + ' "$@"\n', encoding='utf-8')
        launcher.chmod(0o755)
    print('\nInstalled. Open or run: ' + str(launcher))
    if background:
        stopper = prefix / 'Stop Loop Anything.command'
        stopper.write_text('#!/bin/sh\nexec ' + shlex.quote(str(python)) + ' -I -m loop_anything service stop\n', encoding='utf-8')
        stopper.chmod(0o755)
        command = [str(python), '-I', '-m', 'loop_anything']
        if args.db is not None:
            command += ['--db', str(args.db.expanduser().resolve())]
        command += ['service', 'install']
        if args.port is not None:
            command += ['--port', str(args.port)]
        if args.host is not None:
            command += ['--host', args.host]
        subprocess.run(command, check=True)
        print('Background service installed. Codex and the terminal can close. Stop with: ' + str(stopper))
    else:
        print('Foreground launcher: keep its terminal running. Ctrl+C exits.')
    print('CLI Python: ' + str(python))
    print('Install the platform manual into your Agent Skill directory:')
    print(str(python) + ' -m loop_anything skills --install-dir <Agent-Skill-directory> --url <platform-url>')
    print('No shell PATH or Agent settings were changed.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit('Installation failed: ' + str(exc))
