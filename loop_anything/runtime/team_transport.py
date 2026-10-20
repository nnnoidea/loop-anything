"""Load the exact standalone dispatch implementation shipped to Agents."""
import importlib.util
import sys
from loop_anything.paths import platform_skill_directory

path = platform_skill_directory().parent / 'loop-anything-dispatch/scripts/team_transport.py'
spec = importlib.util.spec_from_file_location('_loop_anything_team_transport', path)
core = importlib.util.module_from_spec(spec)
sys.modules.setdefault(spec.name, core)
spec.loader.exec_module(core)
connect = core.connect
join = core.join
prepare_dispatch = core.prepare_dispatch
default_team = core.default_team


def transport(comm, group):
    cache = getattr(comm, '_team_transports', {})
    key = (group['id'], group.get('path'), group.get('app_token'), group.get('table_id'), group.get('lark_cli'), group.get('identity'))
    if key not in cache:cache[key] = connect(group)
    comm._team_transports = cache
    return cache[key]
