import argparse
import json
import os
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'loop_anything'
from loop_anything.runtime.engine import Engine
from loop_anything.runtime.model import Invalid, validate
from loop_anything.runtime.store import Store
from loop_anything.runtime.host_runtime import lock_database, KeepAwake
from loop_anything.paths import default_database, DEFAULT_PORT, DEFAULT_URL, platform_skill_directory


def read(filename):
    return json.loads(Path(filename).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description='Loop Anything local engine and workspace')
    parser.add_argument('--db', help='Workspace database (defaults to the user data directory); use an absolute path for an existing workspace')
    commands = parser.add_subparsers(dest='command', required=True)
    service = commands.add_parser('service', help='Manage the macOS background platform')
    service.add_argument('action', choices=['install', 'start', 'stop', 'status', 'remove'])
    service.add_argument('--port', type=int)
    service.add_argument('--host')
    service.add_argument('--open', action='store_true')
    start = commands.add_parser('serve')
    start.add_argument('--port', type=int, default=DEFAULT_PORT)
    start.add_argument('--demo', action='store_true', help='Register simulated example implementations')
    for name in ('validate', 'publish'):
        cmd = commands.add_parser(name)
        cmd.add_argument('loop_definition')
        cmd.add_argument('implementations')
    pack = commands.add_parser('pack', help='Package a v2 definition with zero, partial or complete implementations')
    pack.add_argument('definition', help='JSON containing loop_definition and optional implementations/checks')
    pack.add_argument('--include', action='append', default=[], help='Explicit file/directory relative to definition file')
    pack.add_argument('--output', required=True)
    install = commands.add_parser('install', help='Install a Loop ZIP without executing it')
    install.add_argument('package')
    smoke = commands.add_parser('smoke', help='Read-only checks of an installed package; never repairs or executes')
    smoke.add_argument('key')
    tool = commands.add_parser('tool', help='Use the same structured tools as the UI and Agent')
    tool.add_argument('name', nargs='?', default='list')
    tool.add_argument('--arguments', default='{}', help='JSON arguments or @JSON_FILE')
    tool.add_argument('--output', help='Save an export result instead of printing base64')
    skills = commands.add_parser('skills', help='Export the platform Skill')
    skills.add_argument('--url', default=DEFAULT_URL)
    destination = skills.add_mutually_exclusive_group(required=True)
    destination.add_argument('--output', help='Export a ZIP')
    destination.add_argument('--install-dir', help='Install Skill folders directly into your Agent skill directory')
    skills.add_argument('--replace', action='store_true', help='Update generated Skill files at --install-dir, preserving other files')
    check = commands.add_parser('check', help='Read-only connection check; never calls a model or starts a Run')
    check.add_argument('--url', default=DEFAULT_URL)
    create = commands.add_parser('create', help='Create a Run for your Agent; acquire its operation right atomically')
    create.add_argument('key')
    create.add_argument('--title', default='New Loop')
    create.add_argument('--inputs', help='JSON file with agreed Run inputs')
    create.add_argument('--authorization', default='', help='User authorization in natural language')
    run = commands.add_parser('run', help='Start an installed package and the local foreground platform service')
    run.add_argument('key')
    run.add_argument('--title', default='Installed Loop')
    run.add_argument('--inputs', help='Optional JSON file with Run inputs')
    run.add_argument('--authorization', default='', help='User authorization in natural language')
    for cmd in (create, run):
        cmd.add_argument('--fallback-node', help='Override the Loop fallback node; an empty string disables it')
        cmd.add_argument('--bindings', help='Optional JSON file mapping node IDs to candidate implementation IDs')
    run.add_argument('--port', type=int, default=DEFAULT_PORT)
    for cmd in (start, run):
        cmd.add_argument('--host', default='127.0.0.1', help='Bind address; use 0.0.0.0 for internal sharing with LOOP_ANYTHING_EDIT_PASSWORD set')
        cmd.add_argument('--allow-sleep', action='store_true', help='Initial sleep preference; a saved webpage choice takes precedence')
        cmd.add_argument('--open', action='store_true', help='Open the workspace in the default browser')
    args = parser.parse_args(sys.argv[1:] or ['serve', '--open'])
    if args.command == 'service':
        from loop_anything.runtime.service import manage
        print(json.dumps(manage(args.action, args.db, args.port, args.host, args.open), ensure_ascii=False, indent=2))
        return
    args.db = args.db or str(default_database())
    if args.command == 'check':
        import subprocess
        client = platform_skill_directory() / 'scripts/call.py'
        raise SystemExit(subprocess.call([sys.executable, str(client), 'check', '--url', args.url]))
    if args.command == 'pack':
        from loop_anything.packaging.packages import make_archive, collect_assets
        source = Path(args.definition).resolve()
        data = make_archive(read(source), collect_assets(source.parent, args.include))
        # Never overwrite an author's existing package accidentally.
        with Path(args.output).open('xb') as output:
            output.write(data)
        print(json.dumps({'package': str(Path(args.output).resolve()), 'bytes': len(data)}))
        return
    if args.command == 'smoke':
        from loop_anything.packaging.packages import load_installed, smoke
        document, root = load_installed(args.db, args.key)
        result = smoke(document, root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        raise SystemExit(0 if result['ready'] else 2)
    if args.command == 'validate':
        result = validate(read(args.loop_definition), read(args.implementations))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        raise SystemExit(0 if result['valid'] else 1)
    if args.command == 'skills':
        from loop_anything.packaging.skill_bundle import bundle, install_skills
        if args.replace and not args.install_dir:
            parser.error('--replace requires --install-dir')
        data = bundle(args.url)
        if args.install_dir:
            print(json.dumps(install_skills(data, args.install_dir, replace=args.replace), ensure_ascii=False, indent=2))
            return
        with Path(args.output).open('xb') as target:
            target.write(data)
        print(json.dumps({'file': str(Path(args.output).resolve())}))
        return
    if args.command in ('serve', 'run') and args.host not in ('127.0.0.1', 'localhost') and not os.environ.get('LOOP_ANYTHING_EDIT_PASSWORD'):
        parser.error('Internal sharing requires LOOP_ANYTHING_EDIT_PASSWORD')
    store = Store(args.db)
    if args.command == 'tool':
        from loop_anything.interfaces.platform_tools import PlatformTools
        tools = PlatformTools(store)
        values = read(args.arguments[1:]) if args.arguments.startswith('@') else json.loads(args.arguments)
        result = {'ok': True, 'tools': tools.definitions()} if args.name == 'list' else tools.respond(args.name, values)
        if args.output and result.get('ok') and 'base64' in result:
            import base64
            with Path(args.output).open('xb') as target:
                target.write(base64.b64decode(result.pop('base64')))
            result['file'] = str(Path(args.output).resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.get('ok') else 2)
    if args.command == 'install':
        from loop_anything.packaging.packages import install
        print(json.dumps(install(store, Path(args.package).read_bytes()), ensure_ascii=False, indent=2))
        return
    if args.command == 'publish':
        print(json.dumps(store.publish(read(args.loop_definition), read(args.implementations)), ensure_ascii=False, indent=2))
        return
    if args.command == 'create':
        run = store.create(args.key, args.title, read(args.inputs) if args.inputs else None,
                           authorization=args.authorization, acquire=True, bindings=read(args.bindings) if args.bindings else None, fallback_node=args.fallback_node)
        print(json.dumps({'run_id': run['id'], 'token': run['agent_sessions'][0]['token'],
                          'entry_task_id': run['loop_definition']['seed']['id']}, ensure_ascii=False))
        return
    # A second server must not recover an execution owned by the first.
    lock = lock_database(args.db)
    if getattr(args, 'demo', False):
        from loop_anything.examples.loops import research, trip
        for factory in (research, trip):
            loop_definition, implementations = factory()
            store.publish(loop_definition, implementations)
    initial_run = None
    if args.command == 'run':
        initial_run = {'key': args.key, 'title': args.title, 'inputs': read(args.inputs) if args.inputs else None, 'authorization': args.authorization, 'bindings': read(args.bindings) if args.bindings else None, 'fallback_node': args.fallback_node}
    engine = Engine(store)
    engine.recover()
    from loop_anything.interfaces.server import serve
    import signal
    def stop_service(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt
    previous_term = signal.signal(signal.SIGTERM, stop_service)
    try:
        with KeepAwake(store.keep_awake(default=not args.allow_sleep)) as protection:
            serve(store, engine, args.port, initial_run=initial_run, protection=protection, open_browser=args.open, host=args.host)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except (Invalid, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc))
