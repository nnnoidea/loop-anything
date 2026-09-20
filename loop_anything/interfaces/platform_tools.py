"""User-Agent tools over existing Loop drafts, packages and Run operations."""
import base64
import copy
import re
from loop_anything.interfaces.agent_tasks import RunTools, object_schema, acquire
from loop_anything.runtime.timeline_model import validate_v2
from loop_anything.runtime.model import Invalid, Conflict, contract, check_schema
from loop_anything.runtime.store import uid

WORKFLOW = 'Use Loop drafts for authoring and Run tools for execution. From any channel, find the existing Run with list_runs and read_timeline before editing; acquire_run only for writes. The Timeline is shared, chat histories are not. Read current revisions before edits. Platform Skills teach operations; business rules come from the author. start_run acquires operation rights; complete its entry task, handle current tasks, then finish.'
TEXT = {'type': 'string'}
OBJ = {'type': 'object'}
BOOL = {'type': 'boolean'}
STRINGS = {'type': 'array', 'items': TEXT}
PORTS = {'type': 'array', 'items': object_schema({'name': TEXT, 'type': TEXT, 'schema': OBJ}, ['name'])}


class PlatformTools:
    instructions = WORKFLOW
    def __init__(self, store):
        self.store = store
        self.run_definitions = RunTools(store, '', '').definitions()

    def definitions(self):
        draft = {'draft_id': TEXT, 'revision': {'type': 'integer'}}
        defs = [
            ('list_loops', 'List installed Loops and editable drafts. Does not start anything.', {}, [], True),
            ('read_loop', 'Read one draft_id or installed key, including the author handbook, node Skills, implementations and batch templates.', {'draft_id': TEXT, 'key': TEXT}, [], True),
            ('create_loop', 'Create an editable Loop with a generic initialization node. Add the author business handbook, tasks and implementations before validation.', {'name': TEXT, 'id': TEXT}, ['name'], False),
            ('copy_loop', 'Copy an installed Loop and its resources to an editable draft. Existing Runs stay on their original version.', {'key': TEXT, 'name': TEXT, 'new_version': BOOL}, ['key'], False),
            ('set_loop', 'Update draft metadata and the AUTHOR business handbook; handbook_path binds a package-relative Skill entry (empty clears). Preserve unspecified fields. Defaults and limits are explicit author choices. fallback_node selects a declared non-entry Agent node with no input ports; empty disables automatic fallback.', dict(draft, name=TEXT, version=TEXT, description=TEXT, handbook=TEXT, handbook_path=TEXT, defaults=OBJ, limits=OBJ, guide=OBJ, checks=OBJ, fallback_node=TEXT, global_agent_node=TEXT), ['draft_id', 'revision'], False),
            ('put_node', 'Add or edit one node. Port lists use name plus type (string/number/object/array/etc.) or a full schema; output record types are generated. Entry ports automatically update its initial input/output locations. skills are author-provided methods, with content or a package-relative path to SKILL.md.', dict(draft, node_id=TEXT, instructions=TEXT, label=TEXT, inputs=PORTS, outputs=PORTS, skills={'type': 'array', 'items': object_schema({'name': TEXT, 'content': TEXT, 'path': TEXT}, ['name'])}, plan_nodes=STRINGS, parameter_schema=OBJ, agent_settings_schema=OBJ, assertions={'type': 'array', 'items': OBJ}), ['draft_id', 'revision', 'node_id'], False),
            ('remove_node', 'Remove a draft node only after removing steps that use it. The initialization node cannot be deleted.', dict(draft, node_id=TEXT), ['draft_id', 'revision', 'node_id'], False),
            ('set_implementation', 'Add/update a named candidate with implementation_id; default=true selects the Loop default, default=false clears it. Omit implementation_id for the compact default candidate. Choose candidates per Run via settings.bindings or per Task via implementation. Execution kinds: agent, command, external, event or approval. command/observe are argv arrays, not shell strings. Optional agent prompt fully replaces the default; {{context}} expands runtime context. Existing candidates accept prompt-only updates. Use node_id=$notifications and kind=command for the user notification sender. Unbind explicitly to share an incomplete Loop.', dict(draft, node_id=TEXT, kind={'type': 'string', 'enum': ['agent', 'command', 'external', 'event', 'approval']}, command=STRINGS, observe=STRINGS, cwd=TEXT, timeout={'type': 'number'}, event=TEXT, prompt=TEXT, unbind=BOOL, implementation_id=TEXT, default=BOOL), ['draft_id', 'revision', 'node_id'], False),
            ('put_asset', 'Attach a UTF-8 script or document to the draft package. path is relative inside the package; an existing asset at this path is replaced only at the supplied draft revision.', dict(draft, path=TEXT, content=TEXT, executable=BOOL), ['draft_id', 'revision', 'path', 'content'], False),
            ('put_step', 'Add/edit a step in a named batch template. inputs map ports to literal, record, run, settings or from/port sources; each is a values array path; an empty string removes list expansion. Plan parameters describe arguments supplied to build_plan. No runtime tasks is created.', dict(draft, plan=TEXT, step=TEXT, node_id=TEXT, inputs=OBJ, parameters=OBJ, after=STRINGS, each=TEXT, plan_parameters=OBJ, implementation=TEXT), ['draft_id', 'revision', 'plan', 'step', 'node_id'], False),
            ('remove_step', 'Remove a batch step if no other step depends on it. Reconnect its consumers first.', dict(draft, plan=TEXT, step=TEXT), ['draft_id', 'revision', 'plan', 'step'], False),
            ('connect_steps', 'Connect an existing batch step output to another step input; collect=true aggregates all outputs of a list-expanded step. This records the source, not a new task.', dict(draft, plan=TEXT, from_step=TEXT, output=TEXT, to_step=TEXT, input=TEXT, collect=BOOL), ['draft_id', 'revision', 'plan', 'from_step', 'output', 'to_step', 'input'], False),
            ('validate_loop', 'Validate a draft and report missing implementations separately. Validation never runs handlers.', {'draft_id': TEXT}, ['draft_id'], True),
            ('publish_loop', 'Publish a validated draft through the existing Loop package installer. auto_version=true selects a new version if already installed, preserving the Loop ID and old Runs. Returns the current draft revision. Does not start a Run.', dict(draft, auto_version=BOOL), ['draft_id', 'revision'], False),
            ('export_loop', 'Export draft definition and attached resources as a Loop ZIP. The CLI client can save the returned base64 via --output.', {'draft_id': TEXT}, ['draft_id'], True),
            ('start_run', 'After user discussion, create a Run and acquire operation rights atomically. Complete entry_task_id using read_task/complete_task, arrange tasks and finish; no second initializer is launched. Optional bindings map node IDs to candidate IDs or null; missing implementations do not prevent Run creation. Optional fallback_node overrides the Loop choice; an empty string disables fallback. notification_command is this Run notification sender argv; persist an explicit chat destination rather than relying on the server environment.', {'key': TEXT, 'title': TEXT, 'inputs': OBJ, 'authorization': TEXT, 'bindings': OBJ, 'fallback_node': TEXT, 'global_agent_node': TEXT, 'notification_command': STRINGS}, ['key', 'title', 'authorization'], False),
            ('retry_notification', 'Retry one failed notification at its saved destination, including after the Run ends. Check whether an unknown delivery already arrived before retrying. Supply token if holding global operation rights; otherwise no overlapping Agent may be active.', {'run_id': TEXT, 'notification_id': TEXT, 'token': TEXT}, ['run_id', 'notification_id'], False),
            ('list_runs', 'Find existing Runs by title, Run ID, Loop name or objective, optionally filtering by status. Results are newest first. Continuing from another channel does not create a new Run.', {'query': TEXT, 'status': TEXT}, [], True),
            ('read_run', 'Read an existing Run and its current state/history without internal operation tokens. This does not acquire rights; use acquire_run for your own operation token.', {'run_id': TEXT}, ['run_id'], True),
            ('acquire_run', 'Acquire global rights when task_id is omitted, or the named task subtree when supplied. Only overlapping scopes conflict; never automatically take over.', {'run_id': TEXT, 'task_id': TEXT}, ['run_id'], False),
        ]
        result = [{'name': n, 'description': d, 'inputSchema': object_schema(p, required), 'annotations': {'readOnlyHint': ro}}
                  for n, d, p, required, ro in defs]
        for original in self.run_definitions:
            d = copy.deepcopy(original)
            d['inputSchema']['properties'].update(run_id=TEXT, token=TEXT)
            d['inputSchema']['required'] += ['run_id'] + ([] if d['annotations']['readOnlyHint'] else ['token'])
            result.append(d)
        return result

    def respond(self, name, arguments):
        try:
            return dict(ok=True, **self.call(name, arguments))
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            return {'ok': False, 'error': {'code': 'conflict' if isinstance(exc, Conflict) else 'invalid_request', 'message': str(exc)}}

    def _draft(self, id, revision=None):
        draft = next((d for d in self.store.drafts() if d['id'] == id), None)
        if draft is None:
            raise Invalid('Unknown draft_id')
        if revision is not None and draft['revision'] != revision:
            raise Conflict('Draft changed; call read_loop and reconsider the edit')
        return draft

    def _installed(self, key):
        loop = next((d for d in self.store.catalog() if d['key'] == key), None)
        if loop is None:
            raise Invalid('Unknown installed Loop key')
        return loop

    def _next_version(self, bp):
        versions = {item['loop_definition']['version'] for item in self.store.catalog()
                    if item['loop_definition']['id'] == bp['id']}
        if bp['version'].isdigit():
            return str(max([int(bp['version'])] + [int(v) for v in versions if v.isdigit()]) + 1)
        candidate = bp['version'] + '-next'
        while candidate in versions:
            candidate += '-next'
        return candidate

    def _validation(self, draft):
        report = validate_v2(draft['loop_definition'], draft['implementations'])
        if report['valid']:
            from loop_anything.packaging.packages import validate_document, decode_assets, validate_skill_files
            try:
                validate_document({'loop_definition': draft['loop_definition'], 'implementations': draft['implementations'], 'checks': draft.get('checks', {})})
                validate_skill_files(draft['loop_definition'], decode_assets(draft.get('assets', [])))
            except (Invalid, ValueError) as exc:
                report['valid'] = False
                report['errors'].append(str(exc))
        return report

    def _summary(self, draft):
        return {'draft_id': draft['id'], 'revision': draft['revision'], 'validation': self._validation(draft)}

    def call(self, name, arguments):
        definitions = {d['name']: d for d in self.definitions()}
        if name not in definitions:
            raise Invalid('Unknown platform tool')
        contract(arguments, definitions[name]['inputSchema'], 'arguments')
        a = copy.deepcopy(arguments)
        if name in {d['name'] for d in self.run_definitions}:
            return RunTools(self.store, a.pop('run_id'), a.pop('token', None)).call(name, a)
        if name == 'list_loops':
            return {'loops': [{'key': d['key'], 'name': d['loop_definition'].get('name', d['loop_definition']['id'])} for d in self.store.catalog()],
                    'drafts': [{'draft_id': d['id'], 'revision': d['revision'], 'name': d['loop_definition'].get('name')} for d in self.store.drafts()]}
        if name == 'read_loop':
            if bool(a.get('draft_id')) == bool(a.get('key')):
                raise Invalid('Supply exactly one draft_id or key')
            loop = self._draft(a['draft_id']) if a.get('draft_id') else self._installed(a['key'])
            if a.get('key'):
                from loop_anything.packaging.packages import resolve_skill
                bp = loop['loop_definition']
                bp['handbook'] = resolve_skill(self.store.filename, a['key'], bp.get('handbook', {}))
                for node in bp['nodes'].values():
                    if 'skills' in node:
                        node['skills'] = [resolve_skill(self.store.filename, a['key'], skill) for skill in node['skills']]
            return {'loop': loop}
        if name == 'start_run':
            run = self.store.create(a['key'], a['title'], a.get('inputs'), authorization=a['authorization'], acquire=True, bindings=a.get('bindings'), fallback_node=a.get('fallback_node'), global_agent_node=a.get('global_agent_node'), notification_command=a.get('notification_command'))
            return {'run_id': run['id'], 'token': run['agent_sessions'][0]['token'], 'entry_task_id': run['loop_definition']['seed']['id']}
        if name == 'retry_notification':
            if not self.store.get(a['run_id']).get('operator_protocol'):
                raise Invalid('Historical Run is inspect-only')
            RunTools(self.store, a['run_id'], a.get('token', '')).runtime.command(a['run_id'], 'retry_notification', notification_id=a['notification_id'], operator_token=a.get('token'))
            return {'queued': True, 'notification_id': a['notification_id']}
        if name == 'list_runs':
            query = a.get('query', '').casefold()
            runs = []
            for run in self.store.list():
                if a.get('status') and run['status'] != a['status']:
                    continue
                objective = run.get('settings', {}).get('objective', '')
                if query not in ' '.join([run['id'], run['title'], run['loop_definition'].get('name', ''), objective]).casefold():
                    continue
                runs.append(dict({k: run[k] for k in ('id', 'title', 'status', 'loop_key', 'created_at', 'revision')}, objective=objective))
            return {'runs': runs}
        if name == 'read_run':
            run = self.store.get(a['run_id'])
            for item in run.get('agent_sessions', []) + run.get('executions', []) + run.get('notifications', []):
                item.pop('token', None)
            return {'run': run}
        if name == 'acquire_run':
            return acquire(self.store, a['run_id'], a.get('task_id'))
        if name == 'create_loop':
            bp = {'schema_version': 2, 'id': a.get('id') or uid('loop'), 'name': a['name'], 'version': '1',
                  'entry': 'initialize', 'handbook': {'instructions': ''}, 'defaults': {},
                  'records': {'initial-result': {'type': 'string'}}, 'nodes': {
                      'initialize': {'label': '初始状态', 'instructions': '按已确认的用户要求初始化 Timeline 并记录初始结果。',
                          'initialize_timeline': True, 'inputs': {'request': {'type': 'string'}},
                          'outputs': {'result': {'record_type': 'initial-result'}}}},
                  'seed': {'id': 'initialize', 'node': 'initialize', 'inputs': {'request': {'run': 'request'}},
                           'outputs': {'result': {'id': 'initial.result'}}}, 'plans': {}}
            return self._summary(self.store.save_draft(bp, {}))
        if name == 'copy_loop':
            source = self._installed(a['key'])
            assets, checks = [], {}
            if source.get('package_key'):
                from loop_anything.packaging.packages import load_installed, installed_assets
                doc, root = load_installed(self.store.filename, a['key'])
                source = dict(doc, loop_definition=source['loop_definition'])
                assets = [{'path': n, 'base64': base64.b64encode(data).decode(), 'executable': executable}
                          for n, (data, executable) in installed_assets(doc, root).items()]
                checks = doc.get('checks', {})
            bp = copy.deepcopy(source['loop_definition'])
            if a.get('new_version'):
                bp['version'] = self._next_version(bp)
            else:
                bp['id'] = uid('loop')
                bp['name'] = a.get('name', bp.get('name', bp['id']) + ' · 副本')
                bp['version'] = '1'
            return self._summary(self.store.save_draft(bp, source['implementations'], assets=assets, checks=checks))
        draft = self._draft(a['draft_id'], a.get('revision'))
        bp, implementations = draft['loop_definition'], draft['implementations']
        if name == 'validate_loop':
            return self._validation(draft)
        if name in ('publish_loop', 'export_loop'):
            from loop_anything.packaging.packages import make_archive, decode_assets, install
            if name == 'publish_loop' and a.get('auto_version') and any(item['loop_definition']['id'] == bp['id'] and item['loop_definition']['version'] == bp['version'] for item in self.store.catalog()):
                bp['version'] = self._next_version(bp)
            raw = make_archive({'loop_definition': bp, 'implementations': implementations, 'checks': draft.get('checks', {})}, decode_assets(draft.get('assets', [])))
            if name == 'publish_loop':
                if a.get('auto_version'):
                    draft = self.store.save_draft(bp, implementations, draft['id'], draft['revision'], draft.get('assets'), draft.get('checks'))
                return dict(install(self.store, raw), draft_id=draft['id'], revision=draft['revision'])
            return {'filename': bp['id'] + '.loop.zip', 'base64': base64.b64encode(raw).decode()}
        if name == 'set_loop':
            for field in ('name', 'version', 'description', 'defaults', 'limits', 'guide', 'fallback_node', 'global_agent_node'):
                if field in a:
                    bp[field] = a[field]
            if 'fallback_node' in a:
                bp['fallback_node'] = a['fallback_node'] or None
            if 'checks' in a:
                draft['checks'] = a['checks']
            if 'handbook' in a:
                bp.setdefault('handbook', {})['instructions'] = a['handbook']
            if 'handbook_path' in a:
                handbook = bp.setdefault('handbook', {})
                if a['handbook_path']:
                    handbook['path'] = a['handbook_path']
                else:
                    handbook.pop('path', None)
        elif name == 'put_node':
            id = a['node_id']
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', id):
                raise Invalid('Node ID accepts letters, numbers, underscore and hyphen')
            node = bp['nodes'].setdefault(id, {'instructions': '', 'inputs': {}, 'outputs': {}})
            for field in ('instructions', 'label', 'skills', 'plan_nodes', 'parameter_schema', 'agent_settings_schema', 'assertions'):
                if field in a:
                    node[field] = a[field]
            for direction in ('inputs', 'outputs'):
                if direction not in a:
                    continue
                ports = {}
                for port in a[direction]:
                    if not port['name'] or port['name'] in ports:
                        raise Invalid('Ports need unique nonempty names')
                    schema = port.get('schema') or ({'type': port['type']} if 'type' in port else None)
                    if schema is None:
                        raise Invalid('Each port requires type or schema')
                    check_schema(schema)
                    if direction == 'inputs':
                        ports[port['name']] = schema
                    else:
                        type_id = id + '.' + port['name']
                        bp['records'][type_id] = schema
                        ports[port['name']] = {'record_type': type_id}
                node[direction] = ports
            if id == bp['entry']:
                bp['seed']['inputs'] = {p: bp['seed']['inputs'].get(p, {'run': p}) for p in node['inputs']}
                bp['seed']['outputs'] = {p: bp['seed']['outputs'].get(p, {'id': 'initial.' + p}) for p in node['outputs']}
        elif name == 'remove_node':
            id = a['node_id']
            if id == bp['entry']:
                raise Invalid('Cannot remove the initialization node')
            if id in (bp.get('fallback_node'), bp.get('global_agent_node')):
                raise Invalid('Disable or change the fallback/global Agent selection before removing this node')
            if any(s['node'] == id for plan in bp['plans'].values() for s in plan['steps'].values()):
                raise Invalid('Remove batch steps using this node first')
            del bp['nodes'][id]
            implementations.pop(id, None)
            for node in bp['nodes'].values():
                node['plan_nodes'] = [n for n in node.get('plan_nodes', []) if n != id]
        elif name == 'set_implementation':
            if a['node_id'] not in bp['nodes'] and a['node_id'] != '$notifications':
                raise Invalid('Unknown node_id')
            if a['node_id'] == '$notifications' and not a.get('unbind') and a.get('kind') != 'command':
                raise Invalid('The user notification sender must be a command implementation')
            from loop_anything.runtime.implementations import catalog_copy, validate_candidates
            node = a['node_id']
            ident = a.get('implementation_id', 'default')
            if node == '$notifications':
                if a.get('unbind'):
                    implementations.pop(node, None)
                else:
                    implementations[node] = {k: a[k] for k in ('kind', 'command', 'cwd', 'timeout') if k in a}
            else:
                candidates = catalog_copy(implementations.get(node))
                if a.get('unbind'):
                    candidates['options'].pop(ident, None)
                    if candidates['default'] == ident:
                        candidates['default'] = None
                else:
                    if 'kind' in a:
                        candidates['options'][ident] = {k: a[k] for k in ('kind', 'command', 'observe', 'cwd', 'timeout', 'event', 'prompt') if k in a}
                    elif ident not in candidates['options']:
                        raise Invalid('kind is required for a new implementation')
                    elif 'prompt' in a:
                        candidates['options'][ident]['prompt'] = a['prompt']
                    if a.get('default') is True or ('implementation_id' not in a and 'default' not in a):
                        candidates['default'] = ident
                    elif a.get('default') is False and candidates['default'] == ident:
                        candidates['default'] = None
                validate_candidates(candidates)
                implementations[node] = candidates
        elif name == 'put_asset':
            from loop_anything.packaging.packages import member_path
            path = member_path(a['path'])
            draft['assets'] = [x for x in draft.get('assets', []) if x['path'] != path] + [{'path': path, 'base64': base64.b64encode(a['content'].encode('utf-8')).decode(), 'executable': a.get('executable', False)}]
        elif name == 'put_step':
            if a['node_id'] not in bp['nodes'] or a['node_id'] == bp['entry']:
                raise Invalid('A batch step must reference a declared non-entry node')
            plan = bp['plans'].setdefault(a['plan'], {'parameters': {'type': 'object'}, 'steps': {}})
            if 'plan_parameters' in a:
                check_schema(a['plan_parameters'])
                plan['parameters'] = a['plan_parameters']
            step = plan['steps'].setdefault(a['step'], {'inputs': {}})
            step['node'] = a['node_id']
            for field in ('inputs', 'parameters', 'after', 'each', 'implementation'):
                if field in a:
                    step[field] = a[field]
            if a.get('each') == '':
                step.pop('each', None)
        elif name == 'remove_step':
            plan = bp['plans'][a['plan']]
            for key, step in plan['steps'].items():
                if key != a['step'] and (a['step'] in step.get('after', []) or any(s.get('from') == a['step'] for s in step['inputs'].values())):
                    raise Invalid('Reconnect dependent step first: ' + key)
            del plan['steps'][a['step']]
            if not plan['steps']:
                del bp['plans'][a['plan']]
        elif name == 'connect_steps':
            plan = bp['plans'][a['plan']]
            source, target = plan['steps'][a['from_step']], plan['steps'][a['to_step']]
            if a['output'] not in bp['nodes'][source['node']]['outputs'] or a['input'] not in bp['nodes'][target['node']]['inputs']:
                raise Invalid('Connection must name declared output and input ports')
            target['inputs'][a['input']] = {'from': a['from_step'], 'port': a['output']}
            if a.get('collect'):
                target['inputs'][a['input']]['collect'] = True
        saved = self.store.save_draft(bp, implementations, draft['id'], draft['revision'], draft.get('assets'), draft.get('checks'))
        return self._summary(saved)
