"""macOS user service; launchd owns the process, configuration and restart policy."""
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
from loop_anything.paths import data_directory, default_database, DEFAULT_PORT
from loop_anything.runtime.host_runtime import lock_database
from loop_anything.runtime.model import Invalid

LABEL = 'com.loop-anything.platform'


def service_file():
    return Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')


def configuration():
    return plistlib.loads(service_file().read_bytes()) if service_file().exists() else None


def target():
    return 'gui/' + str(os.getuid()) + '/' + LABEL


def launchctl(*args, check=True):
    result = subprocess.run(['/bin/launchctl', *args], text=True, capture_output=True, timeout=130)
    if check and result.returncode:
        raise Invalid('launchctl ' + args[0] + ': ' + result.stderr.strip())
    return result


def option(config, flag, default):
    argv = (config or {}).get('ProgramArguments', [])
    return argv[argv.index(flag) + 1] if flag in argv else default


def definition(python, database=None, port=None, host=None, previous=None):
    database = str(Path(database or option(previous, '--db', default_database())).expanduser().resolve())
    port = int(port if port is not None else option(previous, '--port', DEFAULT_PORT))
    host = host or option(previous, '--host', '127.0.0.1')
    if not 1 <= port <= 65535:
        raise Invalid('Service port must be between 1 and 65535')
    env = dict((previous or {}).get('EnvironmentVariables', {}))
    env.update(PATH=os.environ.get('PATH', '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'), PYTHONUNBUFFERED='1')
    if 'LOOP_ANYTHING_EDIT_PASSWORD' in os.environ:
        env['LOOP_ANYTHING_EDIT_PASSWORD'] = os.environ['LOOP_ANYTHING_EDIT_PASSWORD']
    if host not in ('127.0.0.1', 'localhost') and not env.get('LOOP_ANYTHING_EDIT_PASSWORD'):
        raise Invalid('Internal sharing requires LOOP_ANYTHING_EDIT_PASSWORD')
    argv = [str(Path(python).absolute()), '-I', '-m', 'loop_anything', '--db', database,
            'serve', '--host', host, '--port', str(port)]
    if '--allow-sleep' in (previous or {}).get('ProgramArguments', []):
        argv.append('--allow-sleep')
    logs = data_directory() / 'logs'
    return {'Label': LABEL, 'ProgramArguments': argv, 'WorkingDirectory': str(Path(database).parent),
            'EnvironmentVariables': env, 'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False},
            'ThrottleInterval': 10, 'ExitTimeOut': 120,
            'StandardOutPath': str(logs / 'platform.log'), 'StandardErrorPath': str(logs / 'platform-error.log')}


def address(config):
    host = option(config, '--host', '127.0.0.1')
    return 'http://%s:%s' % ('127.0.0.1' if host in ('0.0.0.0', 'localhost') else host, option(config, '--port', DEFAULT_PORT))


def health(config):
    try:
        with urlopen(address(config) + '/api/platform', timeout=1) as response:
            result = json.load(response)
        actual = Path(result['database']).resolve()
    except (OSError, URLError, ValueError, KeyError):
        return None
    if actual != Path(option(config, '--db', default_database())).resolve():
        raise Invalid('This address belongs to a different workspace; stop it or choose another port')
    return result


def status():
    config = configuration()
    return {'installed': config is not None, 'loaded': launchctl('print', target(), check=False).returncode == 0,
            'url': address(config), 'database': option(config, '--db', str(default_database())),
            'platform': health(config) if config else None, 'service_file': str(service_file()),
            'log': config.get('StandardErrorPath') if config else None}


def available(config):
    database = Path(option(config, '--db', default_database()))
    database.parent.mkdir(parents=True, exist_ok=True)
    with lock_database(database):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((option(config, '--host', '127.0.0.1'), int(option(config, '--port', DEFAULT_PORT))))
            except OSError as exc:
                raise Invalid('Service port is occupied; stop the foreground preview or choose another port') from exc


def manage(action, database=None, port=None, host=None, open_browser=False):
    if sys.platform != 'darwin':
        raise Invalid('Native background service currently supports macOS; use serve on this system')
    config = configuration()
    loaded = launchctl('print', target(), check=False).returncode == 0
    if action == 'status':
        return status()
    if action in ('stop', 'remove'):
        if config or loaded:
            launchctl('disable', target())
            if loaded:
                launchctl('bootout', target())
                # bootout can return while SIGTERM cleanup is still running.
                deadline = time.monotonic() + 125
                while launchctl('print', target(), check=False).returncode == 0:
                    if time.monotonic() >= deadline:
                        raise Invalid('Service is still stopping; inspect its log before restarting')
                    time.sleep(.2)
        if action == 'remove':
            service_file().unlink(missing_ok=True)
        return status()
    if action == 'install':
        if loaded:
            raise Invalid('Stop the background service before changing its configuration')
        config = definition(sys.executable, database, port, host, config)
        available(config)
        service_file().parent.mkdir(parents=True, exist_ok=True)
        Path(config['StandardOutPath']).parent.mkdir(parents=True, exist_ok=True)
        # Native plist is the only persisted service configuration; it can contain an edit password.
        with service_file().open('wb') as stream:
            os.chmod(service_file(), 0o600)
            plistlib.dump(config, stream)
    if not config:
        raise Invalid('Install the background service first: service install')
    if not loaded:
        available(config)
    launchctl('enable', target())
    if loaded:
        launchctl('kickstart', target())  # No -k: opening the page must not kill a running process.
    else:
        launchctl('bootstrap', 'gui/' + str(os.getuid()), str(service_file()))
    deadline = time.monotonic() + 15
    while not health(config):
        if time.monotonic() >= deadline:
            raise Invalid('Background service did not become ready; inspect ' + config['StandardErrorPath'])
        time.sleep(.2)
    if open_browser:
        import webbrowser
        webbrowser.open(address(config))
    return status()
