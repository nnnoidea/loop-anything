"""One local bridge connection shared by workspaces; Bot credentials stay in TOML."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

from loop_anything.paths import platform_skill_directory
from loop_anything.runtime.machine_identity import MachineIdentity
from loop_anything.runtime.model import Invalid, Conflict


def configuration(value=None, revision=None):
    identity = MachineIdentity()
    with identity.transaction() as db:
        db.execute('CREATE TABLE IF NOT EXISTS cc_connect (singleton INTEGER PRIMARY KEY, document TEXT NOT NULL)')
        row = db.execute('SELECT document FROM cc_connect WHERE singleton=1').fetchone()
        current = json.loads(row[0]) if row else {'revision': 0, 'connection': None}
        if value is not None:
            if revision != current['revision']:raise Conflict('cc-connect connection changed; read_cc_connect before saving')
            current = {'revision': current['revision'] + 1, 'connection': value or None}
            db.execute('INSERT OR REPLACE INTO cc_connect VALUES (1,?)', (json.dumps(current),))
        return current


def catalog(connection):
    script = platform_skill_directory() / 'scripts/cc_connect_context.py'
    result = subprocess.run([sys.executable, str(script), '--catalog', connection['config_path']],
                            capture_output=True, text=True, timeout=20)
    try:data = json.loads(result.stdout)
    except ValueError:raise Invalid('Cannot read cc-connect configuration; use Python 3.11+ or install tomli') from None
    if result.returncode:raise Invalid(data.get('error', 'Cannot read cc-connect configuration'))
    directory = connection['data_dir'] if 'data_dir' in connection else data.get('data_dir')
    if directory:
        if '${' in directory:raise Invalid('Supply the actual data_dir if its environment variable exists only in the bridge process')
        path = Path(directory).expanduser()
        if not path.is_absolute():raise Invalid('cc-connect data_dir is relative; configure its actual absolute data_dir on this machine')
        directory = str(path.resolve())
    data['data_dir'] = directory
    return data


def read():
    value = configuration()
    result = dict(value, bots=[], configured=bool(value['connection']))
    if value['connection']:
        try:
            result.update(catalog(value['connection']))
            if not shutil.which(value['connection']['executable']):result['error'] = 'Configured cc-connect executable is unavailable'
        except (Invalid, OSError, subprocess.TimeoutExpired) as exc:result['error'] = str(exc)
    return result


def configure(revision, connection):
    if not isinstance(connection, dict) or set(connection) - {'executable', 'config_path', 'data_dir'}:
        raise Invalid('connection accepts executable, config_path and optional data_dir; {} disconnects')
    if connection:
        connection={k:v for k,v in connection.items() if k!='data_dir' or v is not None}
        if not all(isinstance(v,str) and v.strip() for v in connection.values()):raise Invalid('Connection paths must be nonempty strings')
        executable = shutil.which(connection.get('executable') or 'cc-connect')
        if not executable:raise Invalid('Supply the local cc-connect executable or put it on PATH')
        path = Path(connection.get('config_path') or '').expanduser()
        if not path.is_absolute() or not path.is_file():raise Invalid('Supply the actual absolute config_path of the running cc-connect instance')
        connection = dict(connection, executable=str(Path(executable).absolute()), config_path=str(path.resolve()))
        data = catalog(connection)
        connection['data_dir'] = data['data_dir']
    configuration(connection, revision)
    return read()


def validate_bot(bot):
    if not isinstance(bot, dict) or set(bot) != {'project', 'platform'} or not all(isinstance(v,str) and v for v in bot.values()):
        raise Invalid('Bot reference must be {project, platform} from read_cc_connect.bots')


def sender(bot, destination=''):
    """Freeze the selected connection in the existing durable notification record."""
    value = configuration()['connection']
    if not value:return {'configuration_error': 'Configure this machine with configure_cc_connect first'}
    command = [sys.executable, str(platform_skill_directory() / 'scripts/notify_cc_connect.py'),
               '--executable', value['executable']]
    if value.get('data_dir'):command += ['--data-dir', value['data_dir']]
    return {'command': command, 'channel': 'cc-connect', 'identity': bot['project'],
            'destination': destination, 'timeout': 60}
