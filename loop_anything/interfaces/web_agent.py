"""The local webpage as a client of the same Agent commands and Timeline tools."""
import copy
import json
import time
from contextlib import contextmanager
from loop_anything.paths import platform_skill_directory
from loop_anything.runtime.model import Conflict, Invalid, contract
from loop_anything.runtime.store import uid
from loop_anything.runtime.implementations import choose, validate_bindings, validate_implementation
from loop_anything.runtime.host_runtime import run_command, CommandNotStopped
from loop_anything.interfaces.agent_tasks import RunTools, object_schema, acquire, owner_for, release_in_run, recover_owner
from loop_anything.interfaces.platform_tools import PlatformTools


class WebAgent:
    def __init__(self, store, engine):
        self.store, self.engine = store, engine
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS web_conversations (id TEXT PRIMARY KEY, run_id TEXT UNIQUE, document TEXT NOT NULL)')
            for row in db.execute('SELECT id, document FROM web_conversations').fetchall():
                doc = json.loads(row['document'])
                if doc.get('turn'):
                    doc['revision'] += 1
                    doc['turn']['recovery_required'] = True
                    doc['messages'][-1].update(status='interrupted', error='平台曾中断，请先确认旧 Agent 命令已停止。')
                    self._save(db, doc)
            db.commit()

    def _save(self, db, doc):
        db.execute('INSERT INTO web_conversations VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id,document=excluded.document',
                   (doc['id'], doc.get('run_id'), json.dumps(doc, ensure_ascii=False, allow_nan=False)))

    @contextmanager
    def edit(self, ident, revision=None):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM web_conversations WHERE id=?', (ident,)).fetchone()
            if row is None:
                raise Invalid('Unknown conversation')
            doc = json.loads(row[0])
            if revision is not None and revision != doc['revision']:
                raise Conflict('准备内容已变化，请重新读取后再修改。')
            yield doc, db
            doc['revision'] += 1
            self._save(db, doc)
            db.commit()

    def read(self, ident):
        with self.store.connection() as db:
            row = db.execute('SELECT document FROM web_conversations WHERE id=?', (ident,)).fetchone()
            if row is None:
                raise Invalid('Unknown conversation')
            return json.loads(row[0])

    def view(self, doc):
        result = copy.deepcopy(doc)
        turn = result.pop('turn', None)
        result['busy'] = bool(turn)
        result['recovery_required'] = bool(turn and turn.get('recovery_required'))
        return result

    def list(self):
        with self.store.connection() as db:
            docs = [json.loads(r[0]) for r in db.execute('SELECT document FROM web_conversations ORDER BY rowid DESC')]
        return [dict(id=d['id'], key=d['launch']['key'], title=d['launch']['title'], run_id=d.get('run_id')) for d in docs]

    def create(self, key=None, run_id=None):
        if bool(key) == bool(run_id):
            raise Invalid('Choose a Loop or an existing Run')
        run = self.store.get(run_id) if run_id else None
        key = run['loop_key'] if run else key
        item = PlatformTools(self.store)._installed(key)
        bp = item['loop_definition']
        bindings = run['settings'].get('bindings', {}) if run else {}
        preferred = (run['settings'] if run else bp).get('global_agent_node') or (run['settings'] if run else bp).get('fallback_node') or bp['entry']
        implementation = choose(item['implementations'], preferred, bindings)[1] or {}
        agent = {k: implementation[k] for k in ('command', 'cwd', 'timeout') if k in implementation} if implementation.get('kind') == 'agent' and not implementation.get('simulation') else {}
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if run_id:
                old = db.execute('SELECT document FROM web_conversations WHERE run_id=?', (run_id,)).fetchone()
                if old:
                    return self.view(json.loads(old[0]))
            doc = {'id': uid('conversation'), 'revision': 1, 'run_id': run_id, 'agent': agent, 'messages': [],
                   'launch': {'key': key, 'title': run['title'] if run else bp.get('name', bp['id']),
                              'inputs': run['inputs'] if run else bp.get('defaults', {}), 'bindings': bindings,
                              'authorization': run['settings'].get('authorization', '') if run else '',
                              'fallback_node': (run['settings'] if run else bp).get('fallback_node'),
                              'global_agent_node': (run['settings'] if run else bp).get('global_agent_node')}}
            self._save(db, doc)
            db.commit()
        return self.view(doc)

    def update(self, ident, revision, launch=None, agent=None, turn_token=None):
        if type(revision) is not int:
            raise Invalid('revision is required')
        with self.edit(ident, revision) as (doc, _):
            if turn_token is not None and (not doc.get('turn') or doc['turn']['token'] != turn_token):
                raise Conflict('This webpage Agent turn expired')
            if doc.get('turn') and (doc['turn']['token'] != turn_token or doc['turn'].get('recovery_required')):
                raise Conflict('Agent 正在处理，请等待本次回复后再修改配置。')
            if launch is not None:
                if doc.get('run_id'):
                    raise Conflict('Run 已启动；请使用 Timeline 工具修改运行。')
                contract(launch, object_schema({'title': {'type': 'string'}, 'inputs': {'type': 'object'},
                    'authorization': {'type': 'string'}, 'bindings': {'type': 'object'},
                    'fallback_node': {'type': 'string'}, 'global_agent_node': {'type': 'string'}}, []), 'launch')
                bp = PlatformTools(self.store)._installed(doc['launch']['key'])
                candidate = dict(doc['launch'], **launch)
                validate_bindings(bp['loop_definition'], bp['implementations'], candidate['bindings'])
                from loop_anything.runtime.timeline_model import validate_fallback, validate_global_agent
                validate_fallback(bp['loop_definition'], bp['implementations'], candidate.get('fallback_node'))
                validate_global_agent(bp['loop_definition'], bp['implementations'], candidate.get('global_agent_node'))
                doc['launch'] = candidate
            if agent is not None:
                contract(agent, object_schema({'command': {'type': 'array', 'items': {'type': 'string'}},
                    'cwd': {'type': 'string'}, 'timeout': {'type': 'number'}}, []), 'agent')
                if agent:
                    validate_implementation(dict(agent, kind='agent'))
                doc['agent'] = agent
        return self.view(self.read(ident))

    def start(self, ident, revision, turn_token=None):
        if type(revision) is not int:
            raise Invalid('revision is required')
        with self.edit(ident, revision) as (doc, db):
            if turn_token is not None and (not doc.get('turn') or doc['turn']['token'] != turn_token or doc['turn'].get('recovery_required')):
                raise Conflict('This webpage Agent turn expired')
            if doc.get('turn') and doc['turn']['token'] != turn_token:
                raise Conflict('Agent 正在处理启动请求。')
            if doc.get('run_id'):
                return {'run_id': doc['run_id']}
            if not doc['launch']['title'].strip():
                raise Invalid('请填写本次运行名称。')
            run = self.store.create(**doc['launch'], acquire=bool(turn_token), _db=db)
            doc['run_id'] = run['id']
            if turn_token:
                doc['turn']['operator_token'] = run['agent_sessions'][0]['token']
            result = {'run_id': run['id'], 'entry_task_id': run['loop_definition']['seed']['id']}
        return result

    def send(self, ident, revision, message, start=False, scope_task=None):
        if type(revision) is not int:
            raise Invalid('revision is required')
        if not isinstance(message, str) or not message.strip() or type(start) is not bool:
            raise Invalid('Message text is required')
        with self.edit(ident, revision) as (doc, _):
            if doc.get('turn'):
                raise Conflict('请等待本次回复，或确认旧命令停止后恢复。')
            if not doc['agent'].get('command'):
                raise Invalid('请先配置网页使用的 Agent 命令。')
            if scope_task is not None and (not doc.get('run_id') or scope_task not in self.store.get(doc['run_id'])['tasks']):
                raise Invalid('Unknown scope task')
            doc['turn'] = {'token': uid('web-turn'), 'scope_task': scope_task, 'start_requested': start}
            doc['messages'].extend([{'role': 'user', 'text': message, 'at': time.time()},
                                    {'role': 'assistant', 'text': '', 'status': 'running', 'at': time.time()}])
            token = doc['turn']['token']
        self.engine.futures.add(self.engine.pool.submit(self.execute, ident, token))
        return self.view(self.read(ident))

    def turn(self, ident, token):
        doc = self.read(ident)
        if not doc.get('turn') or doc['turn']['token'] != token or doc['turn'].get('recovery_required'):
            raise Conflict('This webpage Agent turn is no longer active')
        return doc

    def definitions(self, ident, token):
        doc = self.turn(ident, token)
        defs = [
            ('read_preparation', 'Read the current webpage selections and revision. This is not a Run.', {}, []),
            ('change_preparation', 'Update agreed inputs, authorization or candidate selections before starting. Changes appear on the page. Does not run work.', {'revision': {'type': 'integer'}, 'change': {'type': 'object'}}, ['revision', 'change']),
            ('start_prepared_run', 'Only after the user explicitly requests startup: create and acquire the selected Run once. Initialize its entry with the existing Run tools, then finish. Repeating never creates a second Run.', {'revision': {'type': 'integer'}}, ['revision']),
            ('read_loop', 'Read the selected Loop, author handbook, Skills and candidate implementations.', {}, [])]
        if doc.get('run_id'):
            defs += [('acquire_run', 'Acquire the operation scope selected in the webpage, only when a write is needed. A conflict must not be bypassed.', {}, []),
                     ('read_run', 'Read the attached Run and history without internal tokens.', {}, [])]
        result = [{'name': n, 'description': d, 'inputSchema': object_schema(p, required)} for n, d, p, required in defs]
        if doc.get('run_id'):
            result += RunTools(self.store, doc['run_id']).definitions()
        return result

    def tool(self, ident, token, name, arguments):
        try:
            doc = self.turn(ident, token)
            defs = {d['name']: d for d in self.definitions(ident, token)}
            if name not in defs:
                raise Invalid('Tool is unavailable in this webpage context')
            contract(arguments, defs[name]['inputSchema'], 'arguments')
            if name == 'read_preparation':
                result = self.view(doc)
            elif name == 'change_preparation':
                result = self.update(ident, arguments['revision'], launch=arguments['change'], turn_token=token)
            elif name == 'start_prepared_run':
                result = self.start(ident, arguments['revision'], token)
            elif name == 'read_loop':
                result = PlatformTools(self.store).call('read_loop', {'key': doc['launch']['key']})
            elif name == 'read_run':
                result = PlatformTools(self.store).call('read_run', {'run_id': doc['run_id']})
            elif name == 'acquire_run':
                with self.edit(ident) as (current, db):
                    if not current.get('turn') or current['turn']['token'] != token or current['turn'].get('recovery_required'):
                        raise Conflict('This webpage Agent turn expired')
                    owner = acquire(self.store, current['run_id'], current['turn'].get('scope_task'), _db=db)
                    current['turn']['operator_token'] = owner['token']
                result = {'scope_task': owner['scope_task'], 'acquired': True}
            else:
                result = RunTools(self.store, doc['run_id'], doc['turn'].get('operator_token')).call(name, arguments)
                if name == 'finish':
                    with self.edit(ident) as (current, _):
                        if current.get('turn', {}).get('token') == token:
                            current['turn'].pop('operator_token', None)
            return dict(ok=True, **result)
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            return {'ok': False, 'error': {'code': 'conflict' if isinstance(exc, Conflict) else 'invalid_request', 'message': str(exc)}}

    def execute(self, ident, token):
        doc = self.turn(ident, token)
        skill = platform_skill_directory()
        # ponytail: replay local chat text; add compaction only when real context limits require it.
        context = {'tool_url': self.engine.platform_url + '/web/' + ident + '/' + token,
                   'preparation': doc['launch'] if not doc.get('run_id') else None, 'run_id': doc.get('run_id'),
                   'scope_task': doc['turn'].get('scope_task'), 'start_requested': doc['turn']['start_requested'],
                   'messages': [{'role': m['role'], 'text': m['text']} for m in doc['messages'][:-1]]}
        prompt = ('You are the user Agent in the Loop Anything webpage. Read ' + str(skill / 'references/run.md') + '.\n'
                  'Use the webpage tool URL below with the SAME client: python3 "' + str(skill / 'scripts/call.py') + '" TOOL --url TOOL_URL --arguments JSON. '
                  'Call list first; this scoped endpoint already supplies run_id/token, so do not pass them. '
                  'Before startup, read_loop and read_preparation; write agreed inputs and candidate selections using change_preparation. '
                  'Do not start business work during discussion. Call start_prepared_run only when start_requested is true or the user explicitly requests startup. '
                  'After startup, call list again to discover Run tools. Read_task for entry_task_id; if its implementation is agent, submit the required initial settings/outputs. Script entries run through Engine. Finish after arranging the agreed work. '
                  'For an existing Run, read live Timeline first; acquire_run only for edits. Respect scope conflicts. '
                  'Write confirmed decisions into preparation or Timeline, not just chat. After acquiring rights, finish before exit. '
                  'Replies are for the user; they are not business results. Reply in the user language. Never create another Run to bypass a conflict.\n'
                  'Web context:\n' + json.dumps(context, ensure_ascii=False))
        error, uncertain, text = None, False, ''
        try:
            result = run_command(doc['agent']['command'], prompt, doc['agent'].get('timeout'), doc['agent'].get('cwd'), self.engine.stopping)
            text = result.stdout.strip()
            if result.returncode:
                raise Invalid(result.stderr[-2000:] or 'Agent command exited with code ' + str(result.returncode))
            if doc['turn']['start_requested'] and not self.read(ident).get('run_id'):
                raise Invalid('Agent 已退出，但尚未通过工具启动 Run；请检查回复后继续。')
        except Exception as exc:
            error, uncertain = str(exc), isinstance(exc, CommandNotStopped)
        finally:
            current = self.read(ident)
            turn = current.get('turn', {})
            operator = turn.get('operator_token')
            if current.get('run_id') and operator:
                with self.store.edit(current['run_id']) as run:
                    owner = owner_for(run, operator)
                    if owner:
                        if uncertain:
                            owner['recovery_required'] = True
                        else:
                            error = error or 'Agent 退出前未调用 finish，已确认命令停止并释放操作权。'
                            release_in_run(run, operator)
                            if owner.get('scope_task') is None:
                                run['attention_error'] = error
                            if not self.engine.stopping.is_set():
                                from loop_anything.runtime.timeline_runtime import agent_exited
                                agent_exited(run, self.engine.timeline_runtime, error, owner.get('scope_task'))
            with self.edit(ident) as (current, _):
                current['messages'][-1].update(text=text, status='error' if error else 'completed', error=error)
                if uncertain:
                    current['turn']['recovery_required'] = True
                else:
                    current.pop('turn', None)

    def recover(self, ident, confirmed_stopped):
        if confirmed_stopped is not True:
            raise Conflict('先确认旧 Agent 命令已停止。')
        doc = self.read(ident)
        if not doc.get('turn', {}).get('recovery_required'):
            raise Conflict('This conversation does not need recovery')
        token = doc['turn'].get('operator_token')
        if doc.get('run_id') and token and owner_for(self.store.get(doc['run_id']), token):
            recover_owner(self.store, doc['run_id'], token, True)
        with self.edit(ident) as (doc, _):
            doc.pop('turn', None)
        return self.view(self.read(ident))
