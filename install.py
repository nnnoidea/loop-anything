"""Install Loop Anything: local platform, team connections, and task tools in one application."""
import argparse
from pathlib import Path
import shlex
import re
import shutil
import tempfile
from contextlib import contextmanager, nullcontext
from urllib.parse import urlsplit
import subprocess
import sys
import venv

from loop_anything.paths import data_directory, default_database, DEFAULT_PORT
from loop_anything.packaging.launcher import register


@contextmanager
def recover_service(environment, previous):
    """Keep a known-good environment before stopping an existing macOS service."""
    from loop_anything.runtime.service import launchctl, target, manage, service_file
    if not previous:
        yield
        return
    loaded = launchctl('print', target(), check=False).returncode == 0
    plist = service_file()
    saved = plist.read_bytes()
    with tempfile.TemporaryDirectory(prefix='loop-install-backup-', dir=environment.parent) as folder:
        backup = Path(folder) / 'venv'
        shutil.copytree(environment, backup, symlinks=True)
        (Path(folder) / 'service.plist').write_bytes(saved)
        launchers = {path: (path.read_bytes(), path.stat().st_mode) if path.exists() else None
                     for path in (environment.parent / 'Loop Anything.command', environment.parent / 'Stop Loop Anything.command')}
        try:
            manage('stop')
            yield
        except (Exception, KeyboardInterrupt) as original:
            try:
                # A failed startup may have left the new process loaded.
                manage('stop')
                shutil.rmtree(environment)
                shutil.copytree(backup, environment, symlinks=True)
                plist.write_bytes(saved)
                plist.chmod(0o600)
                for path, content in launchers.items():
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(content[0])
                        path.chmod(content[1])
                if loaded:
                    manage('start')
            except Exception as recovery:
                # Do not discard the only known-good copy when recovery fails.
                retained = environment.parent / ('recovery-' + Path(folder).name)
                Path(folder).rename(retained)
                raise RuntimeError('Installation failed: %s; recovery failed: %s. Original environment saved at %s; inspect service status before retrying.' % (original, recovery, retained)) from original
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=data_directory() / 'app', help='Application directory; runtime data is stored separately')
    parser.add_argument('--package', type=Path, help='Local source directory or wheel to install (default: bundled wheel, otherwise this source directory)')
    parser.add_argument('--team-url', help='Personal team tool address (HTTP or NAS)')
    parser.add_argument('--team-web-url', help='Personal team web address')
    parser.add_argument('--default-space', choices=['auto', 'local', 'team'], help='Default for new work; existing work keeps its platform')
    parser.add_argument('--port', type=int, help='Local listening port; omitted values keep the existing setting')
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535')
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
    windows = sys.platform == 'win32'
    python = environment / ('Scripts/python.exe' if windows else 'bin/python')
    existing_environment = (environment / 'pyvenv.cfg').is_file()
    if existing_environment:
        # An upgrade may be launched with another Python installation. Recreating
        # this venv can overwrite its interpreter links before pip can run.
        subprocess.run([str(python), '-I', '-c',
                        'import sys; assert sys.version_info >= (3, 9), "Python 3.9+ required"'], check=True)
    from loop_anything.runtime.service import option, address, definition
    from loop_anything.runtime.tool_client import module
    spaces = module('spaces')
    personal = spaces.read()
    previous = None
    background = sys.platform == 'darwin'
    launcher = prefix / ('Loop Anything.cmd' if windows else 'Loop Anything.command' if background else 'loop-anything')
    existing_launcher = launcher.read_text(encoding='utf-8') if launcher.exists() else None
    if background:
        from loop_anything.runtime.service import configuration, available
        previous = configuration()
        if previous and previous['ProgramArguments'][0] != str(python):
            parser.error('Another application directory owns the service; use its --prefix or remove that service first')
    database = str(Path(option(previous, '--db', default_database())).expanduser().resolve())
    space = option(previous, '--space', 'local')
    local = urlsplit(personal['local_url']) if personal['local_url'] else None
    port = args.port if args.port is not None else int(option(previous, '--port',
            (local.port or 80) if local and local.scheme == 'http' and not local.path else DEFAULT_PORT))
    proposed = definition(python, database=database, port=port, previous=previous)
    changes = {key: value for key, value in (
        ('team_url', args.team_url), ('team_web_url', args.team_web_url),
        ('default_space', args.default_space)) if value is not None}
    if space == 'local':
        if not personal['local_url'] or args.port is not None:
            changes['local_url'] = address(proposed)
        if not personal['local_registry']:
            changes['local_registry'] = database + '.schedules'
    spaces.validate(dict(personal, **changes))  # Fail before stopping or updating anything.
    serve_args = ['--db', database, 'serve', '--port', str(port), '--host', '127.0.0.1', '--space', 'local', '--open']
    if existing_launcher and not background:
        # The foreground launcher's current command is its saved workspace configuration.
        script = existing_launcher
        if args.port is not None:
            script, count = re.subn(r'--port [0-9]+(?=\s|$)', '--port ' + str(port), script)
            if count != 1:
                parser.error('Cannot identify one listening port in the existing launcher; edit its serve command directly')
    elif windows:
        default = 'if "%~1"=="" (\n"%~dp0venv\\Scripts\\python.exe" -I -m loop_anything ' + subprocess.list2cmdline(serve_args) + '\nexit /b\n)\n'
        script = '@echo off\nchcp 65001 >nul\n' + default + '"%~dp0venv\\Scripts\\python.exe" -I -m loop_anything %*\nif errorlevel 1 pause\n'
    else:
        command = shlex.quote(str(python)) + ' -I -m loop_anything'
        default = 'service start --open' if background else shlex.join(serve_args)
        script = '#!/bin/sh\nif [ "$#" -eq 0 ]; then\n  exec ' + command + ' ' + default + '\nfi\nexec ' + command + ' "$@"\n'
    with recover_service(environment, previous) if background else nullcontext():
        if background:
            available(proposed)
        if not existing_environment:
            venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run([str(python), '-m', 'pip', '--disable-pip-version-check', 'install', '--upgrade', '--force-reinstall', '--no-deps', str(source)], check=True)
        launcher.write_text(script, encoding='utf-8')
        if not windows:
            launcher.chmod(0o755)
        registration = register(launcher)
        if background:
            stopper = prefix / 'Stop Loop Anything.command'
            stopper.write_text('#!/bin/sh\nexec ' + shlex.quote(str(python)) + ' -I -m loop_anything service stop\n', encoding='utf-8')
            stopper.chmod(0o755)
            command = [str(python), '-I', '-m', 'loop_anything', '--db', database, 'service', 'install', '--port', str(port)]
            subprocess.run(command, check=True)
        # Only write missing or explicitly supplied personal values, with a revision check.
        if changes:
            spaces.configure(changes, revision=personal['revision'])
    print('\nLoop Anything installed. Open or run: ' + str(launcher))
    print('Registered CLI: ' + registration['command'])
    print('New terminals: loop-anything --help')
    print('For this terminal: ' + registration['current_terminal'])
    if background:
        print('Background service installed. Codex and the terminal can close. Stop with: ' + str(stopper))
    else:
        print('Foreground launcher: keep its terminal running. Ctrl+C exits.')
    print('CLI Python: ' + str(python))
    print('Install the Agent Skills for platform operations, dispatch, and local execution (also after upgrades):')
    print(str(python) + ' -m loop_anything skills --install-dir <Agent-Skill-directory>')
    print('Open Loop Anything to manage your work. Team addresses and defaults can be configured after installation.')
    print('Personal addresses and default space are stored on this machine, separate from Skill files.')
    print('Configure a team: loop-anything spaces --team-url <HTTP_OR_NAS_URL>')
    print('Choose the default: loop-anything spaces --default auto|local|team')
    print('Update generated Skills with --replace; this does not change personal space settings. Reload the Skill, then run scripts/call.py check.')
    print('Agent settings were not changed.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit('Installation failed: ' + str(exc))
