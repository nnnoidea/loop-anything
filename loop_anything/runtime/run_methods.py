"""Apply an installed Loop version to future work in the same Run."""
import copy

from loop_anything.runtime import observations, timelines
from loop_anything.runtime.model import Conflict, Invalid
from loop_anything.runtime.store import uid


def apply(store,run,key):
    if key==run['loop_key']:return
    from loop_anything.packaging.packages import load_installed
    from loop_anything.packaging.configuration import effective, path_for, read_file
    document,root=load_installed(store.filename,key)
    if document['loop_definition']['id']!=run['loop_definition']['id']:
        raise Invalid('Choose a version of this Loop')
    settings=read_file(document,root,path_for(store.filename,key))
    if settings.get('error'):raise Invalid(settings['error'])
    configured=effective(document,root,settings['config'])
    old=copy.deepcopy(run)
    method_ref=uid('method')
    old['method_ref']=method_ref
    method={k:old[k] for k in ('id','loop_key','configuration','method_ref') if k in old}
    method['settings']={'bindings':old['settings'].get('bindings',{})}
    run['loop_key']=key
    run['configuration']={k:settings[k] for k in ('path','revision','config')}
    run['configuration']['package_root']=str(root)
    run.update({k:configured[k] for k in ('loop_definition','implementations')})
    from loop_anything.runtime.flow_agent import materialize
    materialize(run,root)
    for task in run['tasks'].values():
        node=task['spec']['node']
        spec = old['tasks'][task['id']]['spec']
        if node not in old.get('retained_nodes', {}):
            run.setdefault('retained_methods', {})[method_ref] = method
        pinned=timelines.retain_node(run,old,spec,task.get('execution_id'))
        task['spec']['node']=pinned
        task['spec'].pop('implementation',None)
        for attempt in run['executions']:
            if attempt['task_id'] == task['id']:
                attempt['node'] = (pinned if attempt['id'] == task.get('execution_id') else
                                   timelines.retain_node(run, old, spec, attempt['id']))
    from loop_anything.runtime.implementations import options
    bindings=dict(configured.get('bindings',{}))
    for node,choice in old['settings'].get('bindings',{}).items():
        if choice in options(run['implementations'].get(node,{})):bindings[node]=choice
    run['settings']['bindings']=bindings
    for field in ('fallback_node','global_agent_node'):
        selected = run['settings'].get(field)
        if selected and selected not in run['loop_definition']['nodes']:
            run['settings'][field]=run['loop_definition'].get(field)
    # A customization of an inherited view ends when the author removes that view.
    # A complete Run-local arrangement still has its own steps.
    for name in old['loop_definition'].get('observations', {}):
        if name not in configured['loop_definition'].get('observations', {}):
            patch = run.get('observation_overrides', {}).get(name)
            if patch and 'steps' not in patch:
                run['observation_overrides'].pop(name)
    run['settings']['revision']+=1
    store.log(run,'method_updated','Applied Loop version to future work',detail={'previous':old['loop_key'],'key':key})


def configure(store,db,run,args):
    from loop_anything.interfaces.agent_tasks import guard_write
    guard_write(run,args.get('token'))
    if run['status'] in ('completed','terminated'):raise Conflict('Run ended')
    if 'key' in args:apply(store,run,args['key'])
    if 'follow' in args:run['follow_loop_updates']=args['follow']
    overrides=run.setdefault('observation_overrides',{})
    for name in args.get('inherit',[]):overrides.pop(name,None)
    for name,patch in args.get('observations',{}).items():
        if not name.strip():raise Invalid('Observation needs a name')
        if patch is not None and not isinstance(patch,dict):raise Invalid('Supply an observation patch or null to disable')
        overrides[name]=None if patch is None else observations.overlay(overrides.get(name) or {}, patch)
    observations.sync(db,run)
    return {'run_id':run['id'],'key':run['loop_key'],'follow':run.get('follow_loop_updates',False),
            'observations':observations.overview(db,run['timeline_id'])['arrangements']}


def published(store,receipt):
    """Installing/importing a package alone never changes a Run."""
    key=receipt['key']
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh=db.execute('INSERT OR IGNORE INTO published_methods VALUES(?)',(key,)).rowcount
        if fresh:
            rows=db.execute("""SELECT r.id FROM runs r JOIN loop_definitions l ON l.key=json_extract(r.document,'$.loop_key')
                    WHERE json_extract(l.document,'$.id')=? AND json_extract(r.document,'$.follow_loop_updates')=1
                    AND json_extract(r.document,'$.superseded_by') IS NULL
                    AND json_extract(r.document,'$.status') IN ('running','paused')""",(receipt['loop_definition_id'],)).fetchall()
            for row in rows:
                with store.edit(row[0],_db=db) as run:
                    apply(store,run,key)
                    observations.sync(db,run)
        db.commit()
    return receipt
