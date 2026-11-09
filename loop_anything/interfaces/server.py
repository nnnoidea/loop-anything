"""Local same-origin workspace for loop_definition authoring and run settings."""
import json
import base64
import mimetypes
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote
from loop_anything.runtime.model import Conflict, Invalid, validate
from loop_anything.paths import platform_skill_directory


def serve(store, engine, port, initial_run=None, protection=None, open_browser=False, host='127.0.0.1', mailbox=None, public_url=None):
    from loop_anything.interfaces.platform_tools import PlatformTools
    platform_tools = PlatformTools(store)
    root = Path(__file__).resolve().parents[1] / 'web'
    timeline_guide = (platform_skill_directory() / 'references/run.md').read_text(encoding='utf-8')

    def power_status():
        state = protection.status() if protection else {'requested': False, 'active': False, 'backend': None, 'error': None}
        requested = store.keep_awake(default=state['requested'])
        return dict(state, requested=requested, controllable=protection is not None,
                    updating=bool(state.get('updating') or protection and requested != state['requested']))

    from loop_anything.runtime.store import Store

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def may_post(self,parts,body):
            # These handles bind execution reports to a specific live request/turn.
            if len(parts)==5 and parts[0]=='communication' and parts[3:]==['api','tools']:
                return not self.headers.get('Origin') and engine.communication.authorized({'request_id':parts[1],'token':parts[2]},worker=True)
            return True

        def send(self, data, status=200):
            content = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            try:
                self.get()
            except Conflict as exc:
                self.send({'error': str(exc), **({'conflicts': exc.conflicts} if hasattr(exc, 'conflicts') else {})}, 409)
            except Invalid as exc:
                self.send({'error': str(exc)}, 404)

        def get(self):
            parts = urlsplit(self.path).path.strip('/').split('/')
            query = {k:v[-1] for k,v in parse_qs(urlsplit(self.path).query,keep_blank_values=True).items()}
            if len(parts)==5 and parts[0]=='communication' and parts[3:]==['api','tools']:
                self.send(engine.communication.scoped_definitions(parts[1],parts[2]));return
            if len(parts)==5 and parts[0]=='communication' and parts[3:]==['api','platform']:
                if not engine.communication.authorized({'request_id':parts[1],'token':parts[2]},worker=True):raise Conflict('Invalid execution credential')
                parts=['api','platform']
            if parts[0]=='web' or parts[:2]==['api','conversations']:
                raise Invalid('独立网页 Agent 对话已移除；节点 session 仅用于 Run 任务。')
            if len(parts) == 6 and parts[:2] == ['api', 'runs'] and parts[3] == 'executions' and parts[5] in ('terminal','session'):
                if host in ('127.0.0.1', 'localhost') and self.headers.get('Host') not in ('127.0.0.1:%s' % server.server_port, 'localhost:%s' % server.server_port):
                    raise Invalid('Workspace host required')
                engine.execution(store.get(parts[2]), parts[4])
                if parts[5]=='session':
                    from loop_anything.runtime.native_sessions import preparation
                    self.send(preparation(engine,parts[2],parts[4]));return
                query = parse_qs(urlsplit(self.path).query)
                try:
                    after = int(query.get('after', ['0'])[0])
                except ValueError:
                    raise Invalid('Invalid output cursor')
                self.send(engine.terminals.read(parts[2], parts[4], query.get('session', [None])[0], after))
                return
            if parts == ['api', 'lifecycles']:
                from loop_anything.runtime.lifecycle import template, KINDS
                self.send({kind: template(kind) for kind in KINDS})
                return
            if parts == ['api', 'agent-prompts']:
                from loop_anything.runtime.agent_prompt import DEFAULTS
                self.send(DEFAULTS)
                return
            if parts == ['api', 'tools']:
                from loop_anything.interfaces.platform_tools import PlatformTools
                from loop_anything.capabilities import service_info
                self.send({'service': service_info(), 'instructions': PlatformTools.instructions, 'tools': PlatformTools(store).definitions()})
                return
            if parts == ['api', 'skills']:
                from loop_anything.packaging.skill_bundle import bundle
                data = bundle(engine.platform_url if mailbox else 'http://' + self.headers.get('Host', '127.0.0.1:%s' % server.server_port))
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', 'attachment; filename=loop-anything-skills.zip')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parts == ['api','notification-channels']:
                from loop_anything.interfaces.platform_tools import PlatformTools
                self.send(PlatformTools(store).call('read_notification_channels',{}))
                return
            if parts == ['api', 'platform']:
                import platform
                from loop_anything.capabilities import service_info
                self.send({'service': service_info(), 'system': platform.system(), 'database': str(Path(store.filename).resolve()),
                           'keep_awake': power_status()})
            elif parts == ['api', 'catalog']:
                self.send([dict(item, timeline_guide=timeline_guide) for item in store.catalog(query.get('include_archived')=='true')])
            elif parts == ['api', 'drafts']:
                self.send(store.drafts(query.get('include_archived')=='true'))
            elif parts == ['api', 'runs']:
                for k in ('limit','offset'):
                    if k in query:
                        try:query[k]=int(query[k])
                        except ValueError:raise Invalid(k+' must be an integer')
                for k in ('created_from','created_to','active_from','active_to'):
                    if k in query:
                        try:query[k]=float(query[k])
                        except ValueError:raise Invalid(k+' must be a Unix timestamp')
                if 'root_only' in query:
                    if query['root_only'] not in ('true','false'):raise Invalid('root_only must be true or false')
                    query['root_only']=query['root_only']=='true'
                self.send(platform_tools.call('list_runs',query))
            elif len(parts) == 3 and parts[:2] == ['api', 'runs']:
                current = store.get(parts[2])
                if current.get('operator_protocol'):
                    from loop_anything.interfaces.agent_tasks import task_list
                    current['agent_tasks'] = task_list(current, engine.timeline_runtime)
                    for owner in current['agent_sessions']:
                        wakeup = next((e for e in current['executions'] if e['id'] == owner.get('execution_id')), None)
                        if wakeup and not wakeup['implementation'].get('command'):
                            owner['tasks'] = task_list(current, engine.timeline_runtime, owner)['items']
                from loop_anything.runtime.timeline_plan import task_dependencies
                current['task_dependencies'] = task_dependencies(current) if current.get('schema_version') == 2 else {}
                self.send(current)
            elif len(parts) == 4 and parts[:2] == ['api', 'runs'] and parts[3] == 'artifact':
                from loop_anything.packaging.packages import load_installed
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    run = store.get(parts[2])
                    attempt = engine.execution(run, query['execution'][0])
                    port = query['output'][0]
                    node = run['loop_definition']['nodes'][attempt['node']]
                    schema = run['loop_definition']['records'][node['outputs'][port]['record_type']]
                    value = attempt['outputs'][port]
                    for key in json.loads(query.get('path', ['[]'])[0]):
                        if schema['type'] == 'array' and type(key) is int:
                            schema, value = schema['items'], value[key]
                        elif schema['type'] == 'object' and isinstance(key, str):
                            schema, value = schema['properties'][key], value[key]
                        else:
                            raise Invalid('Invalid artifact field')
                    if schema.get('format') != 'file' or not isinstance(value, str):
                        raise Invalid('This output is not a declared file')
                    _, package_root = load_installed(store.filename, run['loop_key'])
                    directory = Path(attempt['implementation'].get('cwd') or package_root)
                    base = (directory if directory.is_absolute() else Path(package_root) / directory).resolve()
                    target = (base / value).resolve()
                    if not target.is_relative_to(base) or not target.is_file():
                        raise Invalid('Artifact is missing or outside this execution working directory')
                    mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                    inline = mime in ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'application/pdf')
                    if mime.startswith('text/') or target.suffix in ('.md', '.json', '.log', '.csv'):
                        mime, inline = 'text/plain; charset=utf-8', True
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(target.stat().st_size))
                    self.send_header('Content-Disposition', ('inline' if inline else 'attachment') + "; filename*=UTF-8''" + quote(target.name))
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Content-Security-Policy', "sandbox; default-src 'none'")
                    self.end_headers()
                    with target.open('rb') as source:
                        while chunk := source.read(65536):
                            self.wfile.write(chunk)
                except (KeyError, ValueError, TypeError, IndexError, OSError, StopIteration) as exc:
                    raise Invalid('Cannot open artifact: ' + str(exc)) from exc
            elif len(parts) == 4 and parts[:2] == ['api', 'runs'] and parts[3] == 'tasks':
                from loop_anything.interfaces.agent_tasks import task_list
                self.send(task_list(store.get(parts[2]), engine.timeline_runtime))
            elif len(parts) == 5 and parts[:2] == ['api', 'runs'] and parts[3] == 'snapshot':
                run = store.get(parts[2])
                execution = engine.execution(run, parts[4])
                from loop_anything.interfaces.agent_tasks import node_for
                self.send({'snapshot': run, 'execution_id': execution['id'], 'token': execution.get('token'),
                           'settings_revision': execution['settings_revision'], 'output_contract': node_for(run, execution['node'])['outputs']})
            else:
                filename = {name: name for name in ('communication.js', 'communication.css', 'terminal.js', 'terminal.css', 'xterm.js', 'xterm-fit.js', 'xterm.css', 'app.js', 'notifications.js', 'lifecycle.js', 'loop_graph.js', 'flow_bridge.js', 'settings.js', 'forms.js', 'workspace.js', 'authoring.js', 'workspace.css', 'launch.js', 'task_history.js', 'style.css', 'graph.css', 'editor.js', 'editor.css', 'packages.js', 'library.js', 'library.css', 'navigation.js', 'run_library.js')}.get('/'.join(parts))
                if parts == ['']:
                    filename = 'index.html'
                if not filename:
                    self.send({'error': 'Not found'}, 404)
                    return
                content = (root / filename).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', mimetypes.guess_type(filename)[0] + '; charset=utf-8')
                self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        def do_POST(self):
            try:
                # No remote page may mutate a local run through a browser form or fetch.
                origin = self.headers.get('Origin')
                request_host = self.headers.get('Host', '')
                if not request_host or host in ('127.0.0.1', 'localhost') and request_host not in ('127.0.0.1:%s' % server.server_port, 'localhost:%s' % server.server_port):
                    raise Invalid('Workspace host required')
                if origin and origin != 'http://' + request_host:
                    raise Invalid('Cross-origin mutation rejected')
                if self.headers.get('X-Loop-Anything') != 'workspace':
                    raise Invalid('X-Loop-Anything header required')
                length = int(self.headers.get('Content-Length', '0'))
                package_route = urlsplit(self.path).path.startswith('/api/packages/') or urlsplit(self.path).path == '/api/drafts'
                limit = 30_000_000 if package_route else 2_000_000
                if not 0 < length <= limit:
                    raise Invalid('JSON body exceeds request limit')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise Invalid('JSON object required')
                parts = urlsplit(self.path).path.strip('/').split('/')
                if not self.may_post(parts, body):
                    self.send({'error': 'Invalid execution identity', 'code': 'invalid_execution'}, 403)
                    return
                self.post(parts, body)
            except Conflict as exc:
                self.send({'error': str(exc), **({'conflicts': exc.conflicts} if hasattr(exc, 'conflicts') else {})}, 409)
            except (Invalid, KeyError, TypeError, ValueError) as exc:
                self.send({'error': str(exc)}, 400)
            except Exception:
                traceback.print_exc()
                self.send({'error': 'Internal error; inspect engine console'}, 500)

        def post(self, parts, body):
            if len(parts)==5 and parts[0]=='communication' and parts[3:]==['api','tools']:
                result=engine.communication.scoped_tool(parts[1],parts[2],body['tool'],body.get('arguments',{}))
                self.send(dict(result,ok=not bool(result.get('pending'))));return
            if len(parts)==6 and parts[:2]==['api','runs'] and parts[3]=='executions' and parts[5]=='resume':
                from loop_anything.runtime.native_sessions import resume
                self.send(resume(engine,parts[2],parts[4],body));return
            if len(parts) == 6 and parts[:2] == ['api', 'runs'] and parts[3] == 'executions' and parts[5] == 'terminal':
                if body.get('action')=='confirm_stopped':
                    if body.get('confirmed_stopped') is not True:raise Invalid('Explicit confirmation that the old process stopped is required')
                    from loop_anything.runtime.native_sessions import confirm_stopped
                    self.send(confirm_stopped(engine,parts[2],parts[4],body.get('session_id')));return
                self.send(engine.terminals.control(parts[2], parts[4], body.get('session_id'), body.get('data'), body.get('cols'), body.get('rows')))
                return
            if parts == ['api', 'platform', 'keep-awake']:
                if not protection or type(body.get('enabled')) is not bool:
                    raise Invalid('Supply enabled as a boolean; sleep protection must be available')
                store.keep_awake(body['enabled'])
                self.send(power_status())
                return
            if parts[0]=='web' or parts[:2]==['api','conversations']:
                raise Invalid('独立网页 Agent 对话已移除；节点 session 仅用于 Run 任务。')
            if parts == ['api', 'tools']:
                from loop_anything.interfaces.platform_tools import PlatformTools
                result = PlatformTools(store).respond(body['tool'],body.get('arguments',{}))
                self.send(result, 200 if result['ok'] else 409 if result['error']['code'] == 'conflict' else 400)
                return
            if parts == ['api', 'packages', 'export']:
                from loop_anything.packaging.packages import make_archive, decode_assets
                assets=decode_assets(body.get('assets',[]))
                data=make_archive(body['document'],assets)
                self.send({'base64': base64.b64encode(data).decode(), 'bytes': len(data)})
            elif parts == ['api', 'packages', 'inspect']:
                from loop_anything.packaging.packages import read_archive, validate_document, effective_definition
                data = base64.b64decode(body['base64'], validate=True)
                document, assets, key, _ = read_archive(data)
                self.send({'document': dict(document, loop_definition=effective_definition(document)), 'key': key, 'report': validate_document(document),
                           'assets': [{'path': n, 'base64': base64.b64encode(v[0]).decode(), 'executable': v[1]} for n, v in assets.items()]})
            elif parts == ['api', 'packages', 'install']:
                from loop_anything.packaging.packages import install
                self.send(install(store,base64.b64decode(body['base64'],validate=True)),201)
            elif parts == ['api', 'packages', 'draft']:
                from loop_anything.packaging.packages import import_draft
                self.send(import_draft(store,base64.b64decode(body['base64'],validate=True)),201)
            elif parts == ['api', 'packages', 'read']:
                from loop_anything.packaging.packages import load_installed, installed_assets, effective_definition
                document, directory = load_installed(store.filename, body['key'])
                assets = installed_assets(document, directory)
                self.send({'document': dict(document, loop_definition=effective_definition(document)),
                           'assets': [{'path': n, 'base64': base64.b64encode(v[0]).decode(), 'executable': v[1]} for n, v in assets.items()]})
            elif parts == ['api', 'packages', 'smoke']:
                from loop_anything.packaging.packages import load_installed, smoke
                from loop_anything.packaging.configuration import installed
                document, directory, configuration = installed(store.filename, body['key'])
                self.send(smoke(document, directory, configuration=configuration['config']))
            elif parts == ['api', 'validate']:
                self.send(validate(body['loop_definition'], body.get('implementations', {})))
            elif parts == ['api', 'drafts']:
                self.send(store.save_draft(body['loop_definition'], body['implementations'], body.get('id'), body.get('revision'), body.get('assets'), body.get('checks')))
            elif parts == ['api', 'publish']:
                self.send(store.publish(body['loop_definition'],body['implementations']))
            elif parts == ['api', 'runs']:
                self.send(store.create(body['key'], body['title'], body.get('inputs'), authorization=body.get('authorization', ''), acquire=body.get('acquire', False), bindings=body.get('bindings'), fallback_node=body.get('fallback_node'), global_agent_node=body.get('global_agent_node'), notification_command=body.get('notification_command'),notification_route=body.get('notification_route'),conversation_id=body.get('conversation_id'),chat_context=body.get('chat_context'),created_by=body.get('created_by')), 201)
            elif len(parts) == 4 and parts[:2] == ['api', 'runs']:
                run_id, action = parts[2:]
                if action == 'request':
                    from loop_anything.interfaces.agent_tasks import user_request
                    result = user_request(store, run_id, body['text'], body.get('task_id'), body.get('operator_token'))
                elif action == 'agent':
                    from loop_anything.interfaces.agent_tasks import acquire, RunTools
                    if body.get('operation') == 'acquire':
                        result = acquire(store, run_id, body.get('task_id'))
                    elif body.get('operation') == 'release_stopped':
                        from loop_anything.interfaces.agent_tasks import recover_owner
                        recover_owner(store, run_id, body['token'], body.get('confirmed_stopped'))
                        result = {'released': True}
                    else:
                        session = RunTools(store, run_id, body.get('token'))
                        if body.get('tool') == 'list':
                            from loop_anything.interfaces.agent_tasks import require_owner
                            if body.get('token') is not None:
                                require_owner(store.get(run_id), body['token'])
                            self.send(session.definitions())
                            return
                        arguments=dict(body.get('arguments',{}),run_id=run_id)
                        if 'token' in body:arguments['token']=body['token']
                        result=PlatformTools(store).respond(body['tool'],arguments)
                        self.send(result, 200 if result['ok'] else 409 if result['error']['code'] == 'conflict' else 400)
                        return
                elif action == 'tasks':
                    from loop_anything.interfaces.agent_tasks import edit_tasks
                    result = edit_tasks(store, run_id, body['changes'], body.get('revision'), body.get('operator_token'), body.get('preview', False), body.get('basis'))
                elif action == 'settings':
                    result = engine.change_settings(run_id, body['revision'], body['change'], body.get('operator_token'))
                elif action == 'command':
                    result = engine.command(run_id, body['action'], body.get('execution_id'),
                                            **{k: body[k] for k in ('hook_firing', 'notification_id', 'operator_token') if k in body})
                elif action == 'submit':
                    result = engine.submit(run_id, body['execution_id'], body['token'], body['envelope'])
                elif action == 'event':
                    engine.event(run_id, body['event_id'], body['name'], body['payload'], body.get('key'))
                    result = store.get(run_id)
                else:
                    raise Invalid('Unknown operation')
                self.send(result)
            else:
                raise Invalid('Unknown route')

    class LocalHTTPServer(ThreadingHTTPServer):
        def service_actions(self):
            # Windows execution-state assertions belong to their calling thread.
            if protection:
                protection.set_enabled(store.keep_awake(default=protection.enabled))

        def server_bind(self):
            # Loopback needs no reverse DNS; a broken resolver must not block startup.
            TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address

    server = LocalHTTPServer((host, port), Handler)
    engine.web_url = 'http://%s:%s' % ('127.0.0.1' if host in ('0.0.0.0', 'localhost') else host, server.server_port)
    engine.platform_url = public_url or engine.web_url
    if initial_run is not None:
        try:
            created = store.create(**initial_run)
            print(json.dumps({'run_id': created['id'], 'package': initial_run['key']}, ensure_ascii=False), flush=True)
        except Exception:
            server.server_close()
            engine.close()
            raise
    from loop_anything.runtime.service_host import ServiceHost
    runtime=ServiceHost(engine,mailbox).start()
    print('Loop Anything workspace: http://127.0.0.1:%s' % server.server_port, flush=True)
    if host not in ('127.0.0.1', 'localhost'):
        print('Trusted workspace: http://<server-address>:%s' % server.server_port, flush=True)
    print('Database: ' + str(Path(store.filename).resolve()), flush=True)
    if protection and protection.status()['error']:
        print('WARNING: sleep protection unavailable: ' + protection.status()['error'], flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open('http://127.0.0.1:%s' % server.server_port)
    print('Local engine active. Keep this process running; Ctrl+C exits.', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        runtime.close()
