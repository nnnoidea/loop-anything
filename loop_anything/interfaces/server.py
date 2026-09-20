"""Local same-origin workspace for loop_definition authoring and run settings."""
import json
import os
import base64
import mimetypes
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote
from loop_anything.runtime.model import Conflict, Invalid, validate
from loop_anything.paths import platform_skill_directory


def serve(store, engine, port, initial_run=None, protection=None, open_browser=False, host='127.0.0.1'):
    from loop_anything.interfaces.edit_access import EditAccess
    access = EditAccess(os.environ.get('LOOP_ANYTHING_EDIT_PASSWORD'), str(Path(store.filename).resolve()))
    if host not in ('127.0.0.1', 'localhost') and not access.password:
        raise Invalid('Internal sharing requires LOOP_ANYTHING_EDIT_PASSWORD')
    from loop_anything.interfaces.platform_tools import PlatformTools
    platform_tools = PlatformTools(store)
    tool_reads = {d['name'] for d in platform_tools.definitions() if d['annotations']['readOnlyHint']}
    run_tools = {d['name'] for d in platform_tools.run_definitions}
    root = Path(__file__).resolve().parents[1] / 'web'
    stop = threading.Event()
    from loop_anything.interfaces.web_agent import WebAgent
    web_agent = WebAgent(store, engine)
    timeline_guide = (platform_skill_directory() / 'references/run.md').read_text(encoding='utf-8')

    def power_status():
        state = protection.status() if protection else {'requested': False, 'active': False, 'backend': None, 'error': None}
        requested = store.keep_awake(default=state['requested'])
        return dict(state, requested=requested, controllable=protection is not None,
                    updating=bool(state.get('updating') or protection and requested != protection.enabled))

    def scheduler():
        while not stop.wait(0.75):
            for run in store.scheduling_list():
                try:
                    engine.tick(run['id'])
                except Exception as exc:
                    # A malformed runtime path must remain inspectable instead of spinning.
                    with store.edit(run['id']) as current:
                        current['status'] = 'paused'
                        Store.log(current, 'engine_error', str(exc))
                    traceback.print_exc()

    from loop_anything.runtime.store import Store

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def edit_status(self):
            return access.status(self.headers.get('Cookie', ''))

        def editing(self):
            return self.edit_status()['unlocked'] or (bool(access.password) and
                access.permits_header(self.headers.get('Authorization', '')))

        def visible_run(self, run):
            # Operation credentials grant writes; the rest of the Run stays visible.
            if not self.editing():
                for item in run.get('agent_sessions', []) + run.get('executions', []) + run.get('notifications', []):
                    item.pop('token', None)
            return run

        def may_post(self, parts, body):
            if parts == ['api', 'edit-access'] or self.editing():
                return True
            if parts == ['api', 'validate'] or parts == ['api', 'agent-prompts', 'preview'] or (
                    len(parts) == 3 and parts[:2] == ['api', 'packages'] and parts[2] in ('read', 'inspect', 'export', 'smoke')):
                return True
            if parts == ['api', 'tools'] and body.get('tool') in tool_reads:
                return True
            if len(parts) == 4 and parts[:2] == ['api', 'runs'] and parts[3] == 'agent' and not body.get('operation') and body.get('tool') in tool_reads | {'list'}:
                return True
            # Already-authorized commands can finish independently of browser sessions.
            # Browser mutations always require the edit cookie, even with a cached task token.
            if self.headers.get('Origin'):
                return False
            if len(parts) == 5 and parts[0] == 'web' and parts[3:] == ['api', 'tools']:
                web_agent.turn(parts[1], parts[2])
                return True
            if parts == ['api', 'tools'] and body.get('tool') in run_tools:
                args = body.get('arguments', {})
                run_id, token = args.get('run_id'), args.get('token')
            elif len(parts) == 4 and parts[:2] == ['api', 'runs'] and parts[3] == 'agent' and not body.get('operation') and body.get('tool') in run_tools:
                run_id, token = parts[2], body.get('token')
            elif len(parts) == 4 and parts[:2] == ['api', 'runs'] and parts[3] == 'submit':
                e = engine.execution(store.get(parts[2]), body['execution_id'])
                return bool(body.get('token')) and body['token'] == e.get('token')
            else:
                return False
            if not run_id or not token:
                return False
            from loop_anything.runtime.task_scope import owner_for
            return owner_for(store.get(run_id), token) is not None

        def send(self, data, status=200, cookie=None):
            content = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            if cookie is not None:
                self.send_header('Set-Cookie', cookie)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            try:
                self.get()
            except Conflict as exc:
                self.send({'error': str(exc)}, 409)
            except Invalid as exc:
                self.send({'error': str(exc)}, 404)

        def get(self):
            parts = urlsplit(self.path).path.strip('/').split('/')
            if len(parts) == 5 and parts[0] == 'web':
                web_agent.turn(parts[1], parts[2])
                if parts[3:] == ['api', 'tools']:
                    self.send({'tools': web_agent.definitions(parts[1], parts[2])})
                    return
                if parts[3:] == ['api', 'platform']:
                    parts = ['api', 'platform']
            if parts == ['api', 'agent-prompts']:
                from loop_anything.runtime.agent_prompt import DEFAULTS
                self.send(DEFAULTS)
                return
            if parts == ['api', 'edit-access']:
                self.send(self.edit_status())
                return
            if parts == ['api', 'conversations']:
                self.send(web_agent.list())
                return
            if len(parts) == 3 and parts[:2] == ['api', 'conversations']:
                self.send(web_agent.view(web_agent.read(parts[2])))
                return
            if parts == ['api', 'tools']:
                from loop_anything.interfaces.platform_tools import PlatformTools
                self.send({'tools': PlatformTools(store).definitions()})
                return
            if parts == ['api', 'skills']:
                from loop_anything.packaging.skill_bundle import bundle
                data = bundle('http://' + self.headers.get('Host', '127.0.0.1:%s' % server.server_port))
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', 'attachment; filename=loop-anything-skills.zip')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parts == ['api', 'platform']:
                import platform
                self.send({'system': platform.system(), 'database': str(Path(store.filename).resolve()),
                           'keep_awake': power_status()})
            elif parts == ['api', 'catalog']:
                self.send([dict(item, timeline_guide=timeline_guide) for item in store.catalog()])
            elif parts == ['api', 'drafts']:
                self.send(store.drafts())
            elif parts == ['api', 'runs']:
                self.send([{k: v for k, v in r.items() if k in ('id', 'title', 'status', 'loop_key', 'created_at', 'executions', 'settings')}
                           for r in [self.visible_run(r) for r in store.list()]])
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
                self.send(self.visible_run(current))
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
                self.send({'snapshot': self.visible_run(run), 'execution_id': execution['id'], 'token': execution.get('token') if self.editing() else None,
                           'settings_revision': execution['settings_revision'], 'output_contract': node_for(run, execution['node'])['outputs']})
            else:
                filename = {name: name for name in ('app.js', 'loop_graph.js', 'settings.js', 'forms.js', 'workspace.js', 'authoring.js', 'workspace.css', 'conversation.js', 'conversation.css', 'task_history.js', 'style.css', 'graph.css', 'editor.js', 'editor.css', 'packages.js', 'library.js', 'library.css', 'navigation.js')}.get('/'.join(parts))
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
                    self.send({'error': '请先解锁编辑。', 'code': 'edit_locked'}, 403)
                    return
                self.post(parts, body)
            except Conflict as exc:
                self.send({'error': str(exc)}, 409)
            except (Invalid, KeyError, TypeError, ValueError) as exc:
                self.send({'error': str(exc)}, 400)
            except Exception:
                traceback.print_exc()
                self.send({'error': 'Internal error; inspect engine console'}, 500)

        def post(self, parts, body):
            if parts == ['api', 'platform', 'keep-awake']:
                if not protection or type(body.get('enabled')) is not bool:
                    raise Invalid('Supply enabled as a boolean; sleep protection must be available')
                store.keep_awake(body['enabled'])
                self.send(power_status())
                return
            if parts == ['api', 'edit-access']:
                if body.get('action') == 'lock':
                    cookie = access.cookie(False)
                elif body.get('action') == 'unlock' and access.matches(body.get('password')):
                    cookie = access.cookie(True)
                else:
                    self.send({'error': '编辑口令不正确。'}, 403)
                    return
                self.send(access.status(cookie), cookie=cookie)
                return
            if parts == ['api', 'agent-prompts', 'preview']:
                from loop_anything.runtime.agent_prompt import author_context, render_prompt
                if body.get('conversation_id') or body.get('run_id'):
                    if body.get('conversation_id'):
                        doc = web_agent.read(body['conversation_id'])
                    else:
                        run = store.get(body['run_id'])
                        doc = {'id': '[会话建立时生成]', 'run_id': run['id'], 'launch': {'key': run['loop_key']}, 'messages': []}
                    if body.get('launch') is not None and not doc.get('run_id'):
                        doc['launch'] = dict(doc['launch'], **body['launch'])
                    context = web_agent.prompt_context(doc, '[运行时生成]', body.get('scope_task'),
                                                       body.get('start', False), body.get('message'))
                    mode = 'web'
                else:
                    # A draft has no installed Skill paths or Run identity yet.
                    context = author_context(store, None, body['loop_definition'], body['node_id'])
                    context.update(platform_url=engine.platform_url, run_id='[运行时生成]', execution_id='[运行时生成]',
                                   task_id='[运行时生成]', token='[运行时生成]', scope_task='[由实际任务归属决定]')
                    mode = 'task'
                self.send({'text': render_prompt(body, mode, context),
                           'notice': '预览不会启动 Agent。运行身份和令牌在唤醒时生成；草稿 Skill 路径在安装后解析。'})
                return
            if len(parts) == 5 and parts[0] == 'web' and parts[3:] == ['api', 'tools']:
                result = web_agent.tool(parts[1], parts[2], body['tool'], body.get('arguments', {}))
                self.send(result, 200 if result['ok'] else 409 if result['error']['code'] == 'conflict' else 400)
                return
            if parts == ['api', 'conversations']:
                self.send(web_agent.create(body.get('key'), body.get('run_id')), 201)
                return
            if len(parts) == 4 and parts[:2] == ['api', 'conversations']:
                ident, action = parts[2:]
                if action == 'update':
                    result = web_agent.update(ident, body['revision'], body.get('launch'), body.get('agent'))
                elif action == 'send':
                    result = web_agent.send(ident, body['revision'], body['message'], body.get('start', False), body.get('scope_task'))
                elif action == 'start':
                    result = web_agent.start(ident, body['revision'])
                elif action == 'recover':
                    result = web_agent.recover(ident, body.get('confirmed_stopped'))
                else:
                    raise Invalid('Unknown conversation operation')
                self.send(result)
                return
            if parts == ['api', 'tools']:
                from loop_anything.interfaces.platform_tools import PlatformTools
                result = PlatformTools(store).respond(body['tool'], body.get('arguments', {}))
                self.send(result, 200 if result['ok'] else 409 if result['error']['code'] == 'conflict' else 400)
                return
            if parts == ['api', 'packages', 'export']:
                from loop_anything.packaging.packages import make_archive, decode_assets
                data = make_archive(body['document'], decode_assets(body.get('assets', [])))
                self.send({'base64': base64.b64encode(data).decode(), 'bytes': len(data)})
            elif parts == ['api', 'packages', 'inspect']:
                from loop_anything.packaging.packages import read_archive, validate_document
                data = base64.b64decode(body['base64'], validate=True)
                document, assets, key, _ = read_archive(data)
                self.send({'document': document, 'key': key, 'report': validate_document(document),
                           'assets': [{'path': n, 'base64': base64.b64encode(v[0]).decode(), 'executable': v[1]} for n, v in assets.items()]})
            elif parts == ['api', 'packages', 'install']:
                from loop_anything.packaging.packages import install
                self.send(install(store, base64.b64decode(body['base64'], validate=True)), 201)
            elif parts == ['api', 'packages', 'read']:
                from loop_anything.packaging.packages import load_installed, installed_assets
                document, directory = load_installed(store.filename, body['key'])
                assets = installed_assets(document, directory)
                self.send({'document': document,
                           'assets': [{'path': n, 'base64': base64.b64encode(v[0]).decode(), 'executable': v[1]} for n, v in assets.items()]})
            elif parts == ['api', 'packages', 'smoke']:
                from loop_anything.packaging.packages import load_installed, smoke
                document, directory = load_installed(store.filename, body['key'])
                self.send(smoke(document, directory))
            elif parts == ['api', 'validate']:
                self.send(validate(body['loop_definition'], body.get('implementations', {})))
            elif parts == ['api', 'drafts']:
                self.send(store.save_draft(body['loop_definition'], body['implementations'], body.get('id'), body.get('revision'), body.get('assets'), body.get('checks')))
            elif parts == ['api', 'publish']:
                self.send(store.publish(body['loop_definition'], body['implementations']))
            elif parts == ['api', 'runs']:
                self.send(store.create(body['key'], body['title'], body.get('inputs'), authorization=body.get('authorization', ''), acquire=body.get('acquire', False), bindings=body.get('bindings'), fallback_node=body.get('fallback_node'), global_agent_node=body.get('global_agent_node'), notification_command=body.get('notification_command')), 201)
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
                        result = session.respond(body['tool'], body.get('arguments', {}))
                        self.send(result, 200 if result['ok'] else 409 if result['error']['code'] == 'conflict' else 400)
                        return
                elif action == 'tasks':
                    from loop_anything.interfaces.agent_tasks import edit_tasks
                    result = edit_tasks(store, run_id, body['changes'], body['revision'], body.get('operator_token'), body.get('preview', False))
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
    engine.platform_url = 'http://%s:%s' % ('127.0.0.1' if host in ('0.0.0.0', 'localhost') else host, server.server_port)
    if initial_run is not None:
        try:
            created = store.create(**initial_run)
            print(json.dumps({'run_id': created['id'], 'package': initial_run['key']}, ensure_ascii=False), flush=True)
        except Exception:
            server.server_close()
            engine.close()
            raise
    thread = threading.Thread(target=scheduler, daemon=True)
    thread.start()
    print('Loop Anything workspace: http://127.0.0.1:%s' % server.server_port, flush=True)
    if host not in ('127.0.0.1', 'localhost'):
        print('Internal workspace: http://<server-address>:%s (editing unlock lasts 24 hours)' % server.server_port, flush=True)
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
        stop.set()
        thread.join(timeout=5)
        server.server_close()
        engine.close()
