"""User-Agent tools over existing Loop drafts, packages and Run operations."""
import base64
import copy
import re
from loop_anything.interfaces.agent_tasks import RunTools, object_schema, acquire
from loop_anything.runtime.timeline_model import validate_v2
from loop_anything.runtime.model import Invalid, Conflict, contract, check_schema
from loop_anything.runtime.store import uid
from loop_anything.runtime.implementations import options, default_id

WORKFLOW = ('Use the authoring_context in create_loop/copy_loop/read_loop to identify platform-owned work. read_capabilities explains automatic mechanisms, required declarations, author responsibilities, limits and composition examples, beyond the tool index. Use Loop drafts for authoring and Timeline tools for execution. Before writing adapters, inspect the available mechanisms: '
            'put_step/connect_steps declare dependencies, each expansion, collect aggregation and when conditions; ref/after_refs and task_ref/task_refs bind work by authored identities; '
            'put_node.routes maps accepted node events and result parameters to plans: the platform creates Tasks atomically with the report; '
            'build_plan selects/omits steps and binds candidate implementations and Task parameters; '
            'preview_plan validates draft expansion without a Run; validate_parameters checks node and candidate contracts including conditionals; test_loop executes saved scenarios with real Engine logic and simulated side effects; edit_tasks previews generated IDs and atomically applies live task edits; '
            'set_implementation declares parameter contracts and external lifecycle/retry rules; '
            'notify and timer/event candidates handle notification and waits. '
            'read_loop selects a node, candidate, plan, step or package asset; read_plans/read_task return the current contracts. '
            'Use the parameter schemas in this running service catalog, not remembered fields from another version. '
            'Keep editing the existing draft; publish_loop makes a local usable version, export_loop shares it. '
            'Find an existing Run with list_runs/read_timeline before editing; acquire_run only for writes and re-read revisions. '
            'Start_run acquires entry ownership. Complete the entry task, inspect receipt.routes for generated work, and finish to release scope. Do not manually duplicate declared routes. '
            'Run completion requires change_settings completion_rule/termination_signal; a business status field does not end the Run. '
            'Platform Skills teach mechanisms; the author supplies business decisions.')
TEXT = {'type': 'string'}
OBJ = {'type': 'object'}
BOOL = {'type': 'boolean'}
STRINGS = {'type': 'array', 'items': TEXT}
PORTS = {'type': 'array', 'items': object_schema({'name': TEXT, 'type': TEXT, 'schema': OBJ}, ['name'])}
REPORT = object_schema({'event': TEXT, 'report_id': TEXT, 'envelope': OBJ, 'detail': OBJ,
                        'external_id': TEXT, 'poll_after': {'type':'number'}}, ['event'])
SCENARIO = object_schema({
    'name': TEXT, 'inputs': OBJ, 'bindings': OBJ,
    'steps': {'type':'array', 'maxItems':200, 'items': {'oneOf': [
        object_schema({'task_id':TEXT,'ref':TEXT,'node':TEXT,'attempt':{'type':'integer','minimum':1},
                       'report':REPORT,'accepted':BOOL,'duplicate':BOOL,'expect_error':TEXT}, ['report']),
        object_schema({'send_event':object_schema({'event_id':TEXT,'name':TEXT,'key':TEXT,'payload':OBJ,'task_id':TEXT}, ['event_id','name','payload'])}),
        object_schema({'ticks':{'type':'integer','minimum':1,'maximum':20}})]}},
    'assertions': {'type':'array','minItems':1,'items':object_schema({'message':TEXT,'test':OBJ})}
}, ['name','steps','assertions'])
SCENARIOS = {'type':'array','maxItems':20,'items':SCENARIO}
ROUTES = {'type': 'array', 'items': object_schema({'id': TEXT, 'event': TEXT, 'plan': TEXT, 'values': OBJ,
          'each': TEXT, 'when': OBJ, 'steps': OBJ, 'round': TEXT}, ['id', 'event', 'plan', 'values'])}


class PlatformTools:
    instructions = WORKFLOW
    def __init__(self, store):
        self.store = store
        self.run_definitions = [d for d in RunTools(store, '', '').definitions() if d['name'] != 'read_capabilities']

    def definitions(self):
        draft = {'draft_id': TEXT, 'revision': {'type': 'integer'}}
        defs = [
            ('preview_plan', 'Expand an existing draft or installed plan without creating a Run or executing commands. Returns concrete tasks, refs and omitted steps; validates candidate parameters and dependencies. For live Run references use edit_tasks preview.', {'draft_id':TEXT,'key':TEXT,'name':TEXT,'batch_key':TEXT,'values':OBJ,'steps':OBJ,'bindings':OBJ,'round':TEXT}, ['name','batch_key','values'], True),
            ('validate_parameters', 'Validate prospective Task parameters against both node and selected candidate contracts, without creating a Task. Returns valid/errors. Reads the exact same schemas as execution; never injects defaults or filters fields.', {'draft_id':TEXT,'key':TEXT,'node_id':TEXT,'implementation_id':TEXT,'parameters':OBJ}, ['node_id','parameters'], True),
            ('test_loop', 'Run saved or supplied author scenarios in a throwaway database with real Engine dispatch, input resolution and report routing. Commands/models/notification transports are intercepted. Each scenario requires name, steps and assertions; reports select task_id/ref/node. Assertions use the existing deterministic expression over status/task_count/counts/by_ref/by_id/records/route_count. Returns passed, step errors, assertions and resolved tasks. Does not install, start or modify a real Run. Read references/testing.md via read_capabilities for complete examples.', {'draft_id':TEXT,'key':TEXT,'scenarios':SCENARIOS}, [], True),
            ('read_capabilities', 'Discover platform mechanisms beyond tools: automatic responsibilities, author obligations, activation, configuration, limits and composable examples, plus service version/build and supported schema keywords. Optional capability selects one guide. Use the live tool catalog as the interface contract.', {'capability': TEXT}, [], True),
            ('read_notification_channels', 'Read named notification outlets stored on this platform; not part of Loop packages.', {}, [], True),
            ('set_notification_channels', 'Replace local notification outlets using the current revision. Commands use the existing notification adapter stdin/receipt contract. Does not send messages.', {'revision':{'type':'integer'},'channels':OBJ}, ['revision','channels'], False),
            ('list_loops', 'List installed Loops and editable drafts. Does not start anything.', {}, [], True),
            ('smoke_runtime', 'Explicit runtime check of an installed Loop. Starts configured Agent commands (may call models), including fallback candidates, with a minimal startup prompt and bounded timeout. Simulates external lifecycle reports in a temporary Timeline; never calls business submit/observe commands. Optional node_id/implementation_id select candidates. cases supplies node, implementation, state, event and optional attempt/inputs/parameters/settings/detail/expected for conditional transitions. Does not start or change a business Run.', {'key': TEXT, 'node_id': TEXT, 'implementation_id': TEXT, 'timeout': {'type': 'number'}, 'cases': {'type': 'array', 'items': OBJ}}, ['key'], False),
            ('read_loop', 'Read a draft_id or installed key. Optional node_id (+ implementation_id), plan (+ step), or asset_path selects one part and its explicit references. Without selectors returns the complete Loop. Targeted reads include draft revision; asset text is decoded UTF-8.', {'draft_id': TEXT, 'key': TEXT, 'node_id': TEXT, 'implementation_id': TEXT, 'plan': TEXT, 'step': TEXT, 'asset_path': TEXT}, [], True),
            ('create_loop', 'Create an editable Loop with a no-input Agent entry. The user Agent initializes Timeline settings from the conversation; add business ports only when needed. Add the author business handbook, tasks and implementations before validation.', {'name': TEXT, 'id': TEXT}, ['name'], False),
            ('copy_loop', 'Copy an installed Loop and its resources to an editable draft. Existing Runs stay on their original version.', {'key': TEXT, 'name': TEXT, 'new_version': BOOL}, ['key'], False),
            ('set_loop', 'Update draft metadata and the AUTHOR business handbook; handbook_path binds a package-relative Skill entry (empty clears). Preserve unspecified fields. remove_records explicitly deletes unused record types; referenced types are protected. Defaults and limits are explicit author choices. requires lists required capability IDs; scenarios stores author acceptance cases for test_loop. Parameter contracts support the documented conditional/composition subset; read_capabilities returns supported keywords. fallback_node selects a declared non-entry Agent node with no input ports; empty disables automatic fallback.', dict(draft, name=TEXT, version=TEXT, description=TEXT, handbook=TEXT, handbook_path=TEXT, defaults=OBJ, limits=OBJ, guide=OBJ, checks=OBJ, requires=STRINGS, scenarios=SCENARIOS, fallback_node=TEXT, global_agent_node=TEXT, remove_records=STRINGS), ['draft_id', 'revision'], False),
            ('put_node', 'Add or edit one node. Port lists use name plus type or schema; output record types are generated. Entry ports update initial locations. skills bind author methods. routes optionally declare event -> plan task generation, atomically with each accepted lifecycle report. Each route has id/event/plan/values and optional each/when/steps/round. Map values and step overrides with $ references to outputs/inputs/parameters/settings/detail/task/transition/attempt/task_revision; each reads a context array and adds item/index. when is evaluated per item. Generated tasks belong to the source Task; duplicate reports never regenerate. Supplying routes replaces the list; [] clears it. plan_nodes remains the permission for scripts to arrange tasks explicitly; a route is itself an author declaration.', dict(draft, node_id=TEXT, instructions=TEXT, label=TEXT, inputs=PORTS, outputs=PORTS, skills={'type': 'array', 'items': object_schema({'name': TEXT, 'content': TEXT, 'path': TEXT}, ['name'])}, plan_nodes=STRINGS, routes=ROUTES, parameter_schema=OBJ, agent_settings_schema=OBJ, assertions={'type': 'array', 'items': OBJ}), ['draft_id', 'revision', 'node_id'], False),
            ('remove_node', 'Remove a draft node only after removing steps that use it. The initialization node cannot be deleted.', dict(draft, node_id=TEXT), ['draft_id', 'revision', 'node_id'], False),
            ('set_implementation', 'Add/update a named candidate with implementation_id; default=true selects the Loop default, default=false clears it. Omit implementation_id for the compact default candidate. Choose candidates per Run via settings.bindings or per Task via implementation. Execution kinds: agent, command, external, event, timer or approval. timer wait requires seconds or timezone-aware until; event wait accepts key/timeout. wait values support existing {parameters.x} or $ references. Timeouts emit timeout in the same lifecycle. Transition notify lists queue messages/questions atomically. command/observe are argv arrays, not shell strings. Optional Agent dispatch={location:group,agent_id:...} or capability delegates this node to the Run communication group, keeping Agent semantics; omitted dispatch remains local. Named local/remote assistance uses request_assistance and never requires creating a Loop. Agent output is recorded live automatically; terminal=true enables interactive PTY on macOS/Linux. Its command must contain {{prompt}} (initial prompt argument) or {{prompt_file}} (private prompt file path). Existing commands keep stdin prompt behavior. The same Agent owns the task; finish closes interactive execution. Optional agent_cli identifies codex/claude/custom; resume_command is explicit argv with {{session_id}} and {{prompt}} or {{prompt_file}}. Native IDs are captured from CLI startup output or register_agent_session; an explicit {{session_id}} in the initial command receives a fresh UUID (e.g. Claude --session-id). Never use --last to recover a task. Optional agent prompt fully replaces the default; {{context}} expands runtime context. parameter_schema optionally constrains the Task parameters for this candidate, in addition to the node contract. No defaults are injected. lifecycle holds the visible initial state and explicit from/event/to transitions with optional when and retry parameters. Conditions may read attempt; retry reuses the Task and agent hands off to the configured fallback. Only supplied fields change, including when kind is repeated. clear removes named optional fields; clear lifecycle explicitly restores the initial template for the selected kind. Changing kind requires lifecycle or clear lifecycle; incompatible fields must be explicitly cleared. Omitted collections are preserved; supplied lifecycle replaces the matrix. Configure notification outlets with set_notification_channels on the local platform. Unbind explicitly to share an incomplete Loop.', dict(draft, node_id=TEXT, kind={'type': 'string', 'enum': ['agent', 'command', 'external', 'event', 'approval', 'timer']}, command=STRINGS, observe=STRINGS, cwd=TEXT, timeout={'type': 'number'}, event=TEXT, wait=OBJ, prompt=TEXT, terminal=BOOL, agent_cli={"type":"string","enum":["codex","claude","custom"]}, resume_command=STRINGS, dispatch=OBJ, lifecycle=OBJ, parameter_schema=OBJ, label=TEXT, description=TEXT, clear=STRINGS, unbind=BOOL, implementation_id=TEXT, default=BOOL), ['draft_id', 'revision', 'node_id'], False),
            ('put_asset', 'Write or explicitly remove one package file. Supply content (UTF-8) to write, or remove=true to delete. Unspecified executable preserves its previous value. Paths are package-relative; removal does not delete referenced nodes or other resources.', dict(draft, path=TEXT, content=TEXT, executable=BOOL, remove=BOOL), ['draft_id', 'revision', 'path'], False),
            ('put_step', 'Add/edit a step in a named batch template. inputs map ports to literal, record, run, settings or from/port sources; each is a values array path; an empty string removes list expansion. Plan parameters describe build_plan values. ref is a Run-unique Task label template; after_refs is an array template of labels to wait for. Inputs may use task_ref/task_refs plus port. Labels can reference values/item/index. Routes resolve across all batches atomically; standalone preview/build resolves against existing and current tasks. Optional ref/after_refs and task_ref/task_refs are resolved into ordinary dependencies and record sources. Optional when uses the existing deterministic expression over values; false omits the entire step before each expansion. when={} removes the condition. No Task is created by editing a template.', dict(draft, plan=TEXT, step=TEXT, node_id=TEXT, inputs=OBJ, parameters={"type":"object","description":"Task parameter template. Values may use $ references to values/item/index; a sole {\"$\":\"values.options\"} references the entire object. Template and call-time parameter objects are expanded before merging; call-time fields win."}, after=STRINGS, ref={'type':['string','object']}, after_refs={'type':['array','object'],'items':TEXT}, each={"type":"string","description":"Array path relative to build_plan values, e.g. experiments. Expands one Task per item; matching each paths bind corresponding outputs, collect aggregates all outputs."}, plan_parameters=OBJ, implementation=TEXT, when=OBJ), ['draft_id', 'revision', 'plan', 'step', 'node_id'], False),
            ('remove_step', 'Remove a batch step if no other step depends on it. Reconnect its consumers first.', dict(draft, plan=TEXT, step=TEXT), ['draft_id', 'revision', 'plan', 'step'], False),
            ('connect_steps', 'Connect an existing batch step output to another step input; collect=true aggregates all outputs of a list-expanded step. This records the source, not a new task.', dict(draft, plan=TEXT, from_step=TEXT, output=TEXT, to_step=TEXT, input=TEXT, collect=BOOL), ['draft_id', 'revision', 'plan', 'from_step', 'output', 'to_step', 'input'], False),
            ('validate_loop', 'Validate a draft and report missing implementations separately. Validation never runs handlers.', {'draft_id': TEXT}, ['draft_id'], True),
            ('publish_loop', 'Publish a validated draft through the existing Loop package installer. auto_version=true selects a new version if already installed, preserving the Loop ID and old Runs. Returns the current draft revision. Does not start a Run.', dict(draft, auto_version=BOOL), ['draft_id', 'revision'], False),
            ('export_loop', 'Export draft definition and attached resources as a Loop ZIP. The CLI client can save the returned base64 via --output.', {'draft_id': TEXT}, ['draft_id'], True),
            ('start_run', 'After user discussion, create a Run and acquire operation rights atomically. Complete entry_task_id using read_task/report_task (event=completed, report_id and task_version required), arrange tasks and finish; no second initializer is launched. Optional bindings map node IDs to candidate IDs or null; missing implementations do not prevent Run creation. Optional fallback_node overrides the Loop choice; an empty string disables fallback. notification_command is this Run notification sender argv; persist an explicit chat destination rather than relying on the server environment.', {'key': TEXT, 'title': TEXT, 'inputs': OBJ, 'authorization': TEXT, 'bindings': OBJ, 'fallback_node': TEXT, 'global_agent_node': TEXT, 'notification_command': STRINGS, 'notification_route': TEXT}, ['key', 'title', 'authorization'], False),
            ('retry_notification', 'Retry one failed notification at its saved destination, including after the Run ends. Check whether an unknown delivery already arrived before retrying. Supply token if holding global operation rights; otherwise no overlapping Agent may be active.', {'run_id': TEXT, 'notification_id': TEXT, 'token': TEXT}, ['run_id', 'notification_id'], False),
            ('list_runs', 'Find existing Runs by title, Run ID, Loop name or objective, optionally filtering by status. Results are newest first. Continuing from another channel does not create a new Run.', {'query': TEXT, 'status': TEXT}, [], True),
            ('read_run', 'Read an existing Run and its current state/history without internal operation tokens. This does not acquire rights; use acquire_run for your own operation token.', {'run_id': TEXT}, ['run_id'], True),
            ('acquire_run', 'Acquire global rights when task_id is omitted, or the named task subtree when supplied. Only overlapping scopes conflict; never automatically take over.', {'run_id': TEXT, 'task_id': TEXT}, ['run_id'], False),
        ]
        result = [{'name': n, 'description': d, 'inputSchema': object_schema(p, required), 'annotations': {'readOnlyHint': ro}}
                  for n, d, p, required, ro in defs]
        from loop_anything.interfaces.communication_tools import definitions as communication_definitions
        result.extend(communication_definitions())
        for original in self.run_definitions:
            d = copy.deepcopy(original)
            d['inputSchema']['properties'].update(run_id=TEXT, token=TEXT)
            d['inputSchema']['required'] += ['run_id'] + ([] if d['annotations']['readOnlyHint'] or d['name'] in ('notify','send_event') else ['token'])
            result.append(d)
        return result

    def respond(self, name, arguments):
        try:
            return dict(ok=True, **self.call(name, arguments))
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            return {'ok': False, 'error': {'code': 'conflict' if isinstance(exc, Conflict) else 'invalid_request', 'message': str(exc), **({'path': exc.path} if isinstance(exc, Invalid) and exc.path else {})}}

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
                report.setdefault('issues', []).append({'path': getattr(exc, 'path', None) or ['assets'], 'message': str(exc)})
        return report

    def _summary(self, draft, authoring=False):
        result = {'draft_id': draft['id'], 'revision': draft['revision'], 'validation': self._validation(draft)}
        if authoring:
            from loop_anything.authoring_guidance import authoring_context
            result['authoring_context'] = authoring_context()
        return result

    @staticmethod
    def _changes(before, after):
        changes = []
        def compare(a, b, path):
            for key in dict.fromkeys([*a, *b]):
                place = path + [key]
                if key not in a:
                    changes.append({'path': place, 'after': b[key]})
                elif key not in b:
                    changes.append({'path': place, 'before': a[key]})
                elif isinstance(a[key], dict) and isinstance(b[key], dict):
                    compare(a[key], b[key], place)
                elif a[key] != b[key]:
                    changes.append({'path': place, 'before': a[key], 'after': b[key]})
        compare({k: before.get(k, {}) for k in ('loop_definition', 'implementations', 'checks')},
                {k: after.get(k, {}) for k in ('loop_definition', 'implementations', 'checks')}, [])
        old, new = ({x['path']: x for x in d.get('assets', [])} for d in (before, after))
        for path in dict.fromkeys([*old, *new]):
            if old.get(path) == new.get(path):
                continue
            change = {'path': ['assets', path], 'content_changed': old.get(path, {}).get('base64') != new.get(path, {}).get('base64')}
            for name, values in [('before', old), ('after', new)]:
                if path in values:
                    item = values[path]
                    change[name] = {'bytes': len(base64.b64decode(item['base64'])), 'executable': item.get('executable', False)}
            changes.append(change)
        return changes

    @staticmethod
    def _references(loop, selection):
        bp, refs = loop['loop_definition'], []
        node, plan, step, asset, impl = (selection.get(k) for k in ('node_id', 'plan', 'step', 'asset_path', 'implementation_id'))
        def add(path, value):
            refs.append({'path': path, 'value': copy.deepcopy(value)})
        if plan:
            for ident, item in bp['nodes'].items():
                for index, route in enumerate(item.get('routes', [])):
                    if route.get('plan') == plan:
                        add(['loop_definition', 'nodes', ident, 'routes', index], route)
        if node:
            for key in ('entry', 'fallback_node', 'global_agent_node'):
                if not impl and bp.get(key) == node:
                    add(['loop_definition', key], node)
            for ident, item in bp['nodes'].items():
                if not impl and node in item.get('plan_nodes', []):
                    add(['loop_definition', 'nodes', ident, 'plan_nodes'], item['plan_nodes'])
            if impl and default_id(loop['implementations'].get(node)) == impl:
                entry = loop['implementations'][node]
                add(['implementations', node] + ([] if 'kind' in entry else ['default']), entry if 'kind' in entry else impl)
            if bp.get('seed', {}).get('node') == node and (not impl or bp['seed'].get('implementation') == impl):
                add(['loop_definition', 'seed'], bp['seed'])
        for name, template in bp.get('plans', {}).items():
            for key, item in template.get('steps', {}).items():
                if node and item.get('node') == node and (not impl or item.get('implementation') == impl):
                    add(['loop_definition', 'plans', name, 'steps', key], item)
                if step and name == plan and key != step:
                    if step in item.get('after', []):
                        add(['loop_definition', 'plans', name, 'steps', key, 'after'], item['after'])
                    for port, source in item.get('inputs', {}).items():
                        if isinstance(source, dict) and source.get('from') == step:
                            add(['loop_definition', 'plans', name, 'steps', key, 'inputs', port], source)
        if asset:
            entries = [(['loop_definition', 'handbook'], bp.get('handbook', {}))]
            entries += [(['loop_definition', 'nodes', node_id, 'skills', index], skill)
                        for node_id, item in bp['nodes'].items() for index, skill in enumerate(item.get('skills', []))]
            for location, entry in entries:
                if entry.get('path') == asset:
                    add(location + ['path'], asset)
            for node_id, entry in loop['implementations'].items():
                for ident, config in options(entry).items():
                    for field in ('command', 'observe'):
                        if any(arg.removeprefix('./') == asset for arg in config.get(field, [])):
                            add(['implementations', node_id, ident, field], config[field])
        return refs

    def _read_selection(self, loop, selection):
        node, plan, asset = (selection.get(k) for k in ('node_id', 'plan', 'asset_path'))
        if sum(k in selection for k in ('node_id', 'plan', 'asset_path')) != 1 or 'implementation_id' in selection and not node or 'step' in selection and not plan:
            raise Invalid('Choose node_id (+ implementation_id), plan (+ step), or asset_path')
        bp = loop['loop_definition']
        response = {'loop_id': bp['id'], 'version': bp['version'],
                    **({'draft_id': loop['id'], 'revision': loop['revision']} if 'revision' in loop else {'key': loop['key']})}
        if node:
            if node not in bp['nodes']:
                raise Invalid('Unknown node_id')
            if 'implementation_id' in selection:
                candidates = options(loop['implementations'].get(node))
                if selection['implementation_id'] not in candidates:
                    raise Invalid('Unknown implementation_id')
                value = candidates[selection['implementation_id']]
            else:
                item = bp['nodes'].get(node)
                value = {'node': item, 'implementations': loop['implementations'].get(node),
                         'records': {s['record_type']: bp['records'].get(s['record_type']) for s in (item or {}).get('outputs', {}).values() if isinstance(s, dict) and 'record_type' in s}}
        elif plan:
            if plan not in bp.get('plans', {}):
                raise Invalid('Unknown plan')
            value = bp['plans'][plan]
            if 'step' in selection:
                if selection['step'] not in value.get('steps', {}):
                    raise Invalid('Unknown step')
                value = value['steps'][selection['step']]
        else:
            from loop_anything.packaging.packages import member_path, decode_assets, load_installed, installed_assets
            asset = member_path(asset)
            if 'revision' in loop:
                files = decode_assets(loop.get('assets', []))
            else:
                document, directory = load_installed(self.store.filename, loop['key'])
                files = installed_assets(document, directory)
            if asset not in files:
                raise Invalid('Unknown package file: ' + asset)
            content, executable = files[asset]
            try:
                text, encoding = content.decode('utf-8'), 'utf-8'
            except UnicodeDecodeError:
                text, encoding = base64.b64encode(content).decode('ascii'), 'base64'
            value = {'path': asset, 'content': text, 'encoding': encoding, 'executable': executable, 'bytes': len(content)}
        response.update(value=value, references=self._references(loop, selection))
        return response

    def call(self, name, arguments):
        definitions = {d['name']: d for d in self.definitions()}
        if name not in definitions:
            raise Invalid('Unknown platform tool')
        contract(arguments, definitions[name]['inputSchema'], 'arguments')
        a = copy.deepcopy(arguments)
        from loop_anything.interfaces.communication_tools import definitions as communication_definitions, call as communication_call
        if name in {d['name'] for d in communication_definitions()}:
            return communication_call(self.store, name, a)
        if name in {d['name'] for d in self.run_definitions}:
            return RunTools(self.store, a.pop('run_id'), a.pop('token', None)).call(name, a)
        if name in ('preview_plan','test_loop','validate_parameters'):
            if bool(a.get('draft_id')) == bool(a.get('key')):raise Invalid('Supply exactly one draft_id or key')
            document = self._draft(a['draft_id']) if a.get('draft_id') else self._installed(a['key'])
            if name == 'test_loop':
                from loop_anything.packaging.scenarios import run_scenarios
                return run_scenarios(document,a.get('scenarios'))
            if name == 'validate_parameters':
                from loop_anything.runtime.implementations import check_parameters
                node = document['loop_definition']['nodes'].get(a['node_id'])
                if node is None:raise Invalid('Unknown node_id')
                entry = document['implementations'].get(a['node_id'])
                ident = a.get('implementation_id',default_id(entry))
                candidate = options(entry).get(ident)
                if candidate is None:raise Invalid('Select a declared implementation')
                try:
                    contract(a['parameters'],node.get('parameter_schema',{'type':'object'}),'Node parameters')
                    check_parameters(candidate,a['parameters'],'Implementation parameters')
                except Invalid as exc:return {'valid':False,'errors':[str(exc)],'implementation_id':ident}
                return {'valid':True,'errors':[],'implementation_id':ident}
            from loop_anything.packaging.scenarios import preview_plan
            return preview_plan(document,a['name'],a['batch_key'],a['values'],a.get('steps'),a.get('bindings'),a.get('round'))
        if name == 'smoke_runtime':
            from loop_anything.packaging.packages import load_installed
            from loop_anything.packaging.runtime_smoke import runtime_smoke
            document, root = load_installed(self.store.filename, a.pop('key'))
            return runtime_smoke(document, root, **a)
        if name == 'read_capabilities':
            from loop_anything.capabilities import discover
            return discover(a.get('capability'))
        if name == 'read_notification_channels':
            import sys
            from loop_anything.paths import platform_skill_directory
            return dict(self.store.notification_channels(),cc_connect_command=[sys.executable,str(platform_skill_directory()/'scripts/notify_cc_connect.py')])
        if name == 'set_notification_channels':return self.store.notification_channels(a['channels'],a['revision'])
        if name == 'list_loops':
            return {'loops': [{'key': d['key'], 'loop_id': d['loop_definition']['id'], 'version': d['loop_definition']['version'], 'name': d['loop_definition'].get('name', d['loop_definition']['id'])} for d in self.store.catalog()],
                    'drafts': [{'draft_id': d['id'], 'revision': d['revision'], 'loop_id': d['loop_definition']['id'], 'version': d['loop_definition']['version'], 'updated_at': d['updated_at'], 'name': d['loop_definition'].get('name')} for d in self.store.drafts()]}
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
            from loop_anything.authoring_guidance import authoring_context
            if any(k in a for k in ('node_id', 'implementation_id', 'plan', 'step', 'asset_path')):
                return dict(self._read_selection(loop, a), platform_guide={'tool':'read_capabilities','reference':'references/platform-capabilities.md'})
            return {'loop': loop, 'authoring_context': authoring_context()}
        if name == 'start_run':
            run = self.store.create(a['key'], a['title'], a.get('inputs'), authorization=a['authorization'], acquire=True, bindings=a.get('bindings'), fallback_node=a.get('fallback_node'), global_agent_node=a.get('global_agent_node'), notification_command=a.get('notification_command'),notification_route=a.get('notification_route'))
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
                  'records': {}, 'nodes': {
                      'initialize': {'label': '初始状态', 'instructions': '根据已确认的对话将目标、要求和约束写入 Timeline settings；按需安排后续任务，提交本节点后释放操作权。',
                          'initialize_timeline': True, 'inputs': {}, 'outputs': {}}},
                  'seed': {'id': 'initialize', 'node': 'initialize', 'inputs': {}, 'outputs': {}}, 'plans': {}}
            return self._summary(self.store.save_draft(bp, {'initialize': {'kind': 'agent'}}), authoring=True)
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
            from loop_anything.packaging.packages import effective_definition
            bp = effective_definition(source)
            if a.get('new_version'):
                bp['version'] = self._next_version(bp)
            else:
                bp['id'] = uid('loop')
                bp['name'] = a.get('name', bp.get('name', bp['id']) + ' · 副本')
                bp['version'] = '1'
            return self._summary(self.store.save_draft(bp, source['implementations'], assets=assets, checks=checks), authoring=True)
        draft = self._draft(a['draft_id'], a.get('revision'))
        before = copy.deepcopy(draft)
        bp, implementations = draft['loop_definition'], draft['implementations']
        if name == 'validate_loop':
            return self._validation(draft)
        if name in ('publish_loop', 'export_loop'):
            from loop_anything.packaging.packages import make_archive, decode_assets, install, read_archive
            if name == 'publish_loop' and a.get('auto_version'):
                raw = make_archive({'loop_definition': bp, 'implementations': implementations, 'checks': draft.get('checks', {})}, decode_assets(draft.get('assets', [])))
                key = read_archive(raw)[2]
                if any(item['key'] == key for item in self.store.catalog()):
                    return dict(install(self.store, raw), draft_id=draft['id'], revision=draft['revision'])
            if name == 'publish_loop' and a.get('auto_version') and any(item['loop_definition']['id'] == bp['id'] and item['loop_definition']['version'] == bp['version'] for item in self.store.catalog()):
                bp['version'] = self._next_version(bp)
            raw = make_archive({'loop_definition': bp, 'implementations': implementations, 'checks': draft.get('checks', {})}, decode_assets(draft.get('assets', [])))
            if name == 'publish_loop':
                if a.get('auto_version'):
                    draft = self.store.save_draft(bp, implementations, draft['id'], draft['revision'], draft.get('assets'), draft.get('checks'))
                return dict(install(self.store, raw), draft_id=draft['id'], revision=draft['revision'])
            return {'filename': bp['id'] + '.loop.zip', 'base64': base64.b64encode(raw).decode()}
        if name == 'set_loop':
            if 'remove_records' in a:
                from loop_anything.runtime.timeline_model import unused_records
                removable = set(unused_records(bp))
                if set(a['remove_records']) - removable:
                    raise Invalid('Only existing unreferenced record types can be removed')
                for record in set(a['remove_records']):
                    del bp['records'][record]
            for field in ('name', 'version', 'description', 'defaults', 'limits', 'guide', 'fallback_node', 'global_agent_node', 'requires', 'scenarios'):
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
            for field in ('instructions', 'label', 'skills', 'plan_nodes', 'routes', 'parameter_schema', 'agent_settings_schema', 'assertions'):
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
            node, ident = a['node_id'], a.get('implementation_id', 'default')
            if node not in bp['nodes']:
                raise Invalid('Unknown node_id')
            from loop_anything.runtime.implementations import catalog_copy, validate_candidates
            fields = {'kind', 'command', 'observe', 'cwd', 'timeout', 'event', 'wait', 'prompt', 'terminal', 'agent_cli', 'resume_command', 'dispatch', 'lifecycle', 'parameter_schema', 'label', 'description'}
            clear = set(a.get('clear', []))
            if clear - (fields - {'kind'}) or clear & set(a):
                raise Invalid('clear names optional implementation fields, supplied once and not also updated')
            if a.get('unbind') and (clear or fields & set(a)):
                raise Invalid('Unbind separately from updating configuration')
            candidates = catalog_copy(implementations.get(node))
            created = ident not in candidates['options']
            config = copy.deepcopy(candidates['options'].get(ident, {}))
            if a.get('unbind'):
                candidates['options'].pop(ident, None)
                if candidates['default'] == ident:
                    candidates['default'] = None
            else:
                if config.get('kind') and 'kind' in a and a['kind'] != config['kind'] and 'lifecycle' in config and 'lifecycle' not in a and 'lifecycle' not in clear:
                    raise Invalid('Changing kind requires lifecycle or clear=["lifecycle"] to select a new template')
                for key in clear:
                    config.pop(key, None)
                config.update({key: a[key] for key in fields if key in a})
                try:
                    validate_candidates({'options': {ident: config}, 'default': ident})
                except Invalid as exc:
                    raise Invalid(str(exc), path=['implementations', node] + (exc.path or [])) from None
                candidates['options'][ident] = config
                if a.get('default') is True or (created and 'implementation_id' not in a and 'default' not in a):
                    candidates['default'] = ident
                elif a.get('default') is False and candidates['default'] == ident:
                    candidates['default'] = None
            implementations[node] = candidates
        elif name == 'put_asset':
            from loop_anything.packaging.packages import member_path
            path = member_path(a['path'])
            old = next((x for x in draft.get('assets', []) if x['path'] == path), None)
            if a.get('remove'):
                if 'content' in a or 'executable' in a:
                    raise Invalid('Removal cannot also write content or permissions')
                if old is None:
                    raise Invalid('Unknown package file: ' + path)
                draft['assets'] = [x for x in draft.get('assets', []) if x['path'] != path]
            else:
                if 'content' not in a:
                    raise Invalid('Supply content to write, or remove=true to delete')
                draft['assets'] = [x for x in draft.get('assets', []) if x['path'] != path] + [
                    {'path': path, 'base64': base64.b64encode(a['content'].encode('utf-8')).decode(),
                     'executable': a.get('executable', (old or {}).get('executable', False))}]
        elif name == 'put_step':
            if a['node_id'] not in bp['nodes'] or a['node_id'] == bp['entry']:
                raise Invalid('A batch step must reference a declared non-entry node')
            plan = bp['plans'].setdefault(a['plan'], {'parameters': {'type': 'object'}, 'steps': {}})
            if 'plan_parameters' in a:
                check_schema(a['plan_parameters'])
                plan['parameters'] = a['plan_parameters']
            step = plan['steps'].setdefault(a['step'], {'inputs': {}})
            step['node'] = a['node_id']
            for field in ('inputs', 'parameters', 'after', 'each', 'implementation', 'ref', 'after_refs'):
                if field in a:
                    step[field] = a[field]
            if 'when' in a:
                if a['when']:
                    step['when'] = copy.deepcopy(a['when'])
                else:
                    step.pop('when', None)
            if a.get('each') == '':
                step.pop('each', None)
        elif name == 'remove_step':
            plan = bp['plans'][a['plan']]
            if len(plan['steps']) == 1:
                for node_id, node in bp['nodes'].items():
                    if any(r.get('plan') == a['plan'] for r in node.get('routes', [])):
                        raise Invalid('Remove the route referencing this plan first: ' + node_id)
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
        return dict(self._summary(saved), changes=self._changes(before, saved))
