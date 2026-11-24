"""Synchronous user controls. Retries return the original committed result."""
import json

from loop_anything.interfaces.agent_tasks import RunTools, apply_task_changes, object_schema
from loop_anything.runtime.model import Conflict, Invalid, contract, digest


def definitions():
    text = {'type':'string','minLength':1}
    actions = ['command','update_run','delete_run','edit_tasks','follow_loop_updates','refresh_observation','set_task_rounds']
    request = object_schema({'request_id':text,'run_id':text,'operation':{'enum':actions},
                             'arguments':{'type':'object'},'message':{'type':'string'}},
                            ['request_id','run_id','operation','arguments'])
    return [dict(name=name,description=description,inputSchema=schema,annotations={'readOnlyHint':read})
            for name,description,schema,read in [
                ('submit_run_request','Apply explicit Run controls and persist the result atomically.',request,False),
                ('read_run_request','Read the saved result of a Run operation.',object_schema({'request_id':text}),True)]]


def call(store, name, a):
    ident = a['request_id']
    with store.connection() as db:
        if name == 'submit_run_request':
            db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT fingerprint,receipt FROM run_requests WHERE id=?',(ident,)).fetchone()
        if row:
            if name == 'submit_run_request' and row['fingerprint'] != digest(a):
                raise Conflict('Request ID already used')
            receipt=json.loads(row['receipt'])
            receipt.pop('token',None)
            return receipt
        if name == 'read_run_request':
            raise Invalid('Unknown Run request')
        args = a['arguments']
        run_id = a['run_id']
        op = a['operation']
        if op == 'delete_run':
            from loop_anything.runtime.run_library import delete_run
            contract(args,object_schema({'metadata_revision':{'type':'integer'}}),'arguments')
            result = delete_run(store,run_id,args['metadata_revision'],_db=db)
        else:
            with store.edit(run_id,_db=db) as run:
                if op == 'edit_tasks':
                    contract(args,object_schema({'changes':{'type':'array'}}),'arguments')
                    apply_task_changes(store,run,args['changes'])
                    result = {'applied':True}
                elif op == 'refresh_observation':
                    from loop_anything.runtime.observations import refresh
                    result = refresh(db,run,args.get('name'))
                elif op == 'follow_loop_updates':
                    from loop_anything.runtime.run_methods import configure
                    contract(args,object_schema({'follow':{'type':'boolean'}}),'arguments')
                    result = configure(store,db,run,args)
                elif op == 'update_run':
                    from loop_anything.runtime.run_library import update_run_in_run
                    fields = {'metadata_revision':{'type':'integer'},'title':{'type':'string'},
                              'created_by':{'type':'string'},'archived':{'type':'boolean'}}
                    contract(args,object_schema(fields,['metadata_revision']),'arguments')
                    result = update_run_in_run(store,run,**args)
                elif op == 'set_task_rounds':
                    labels = {'type':'object','additionalProperties':{'type':'string','minLength':1}}
                    contract(args,object_schema({'rounds':labels}),'arguments')
                    rounds = {task_id:label.strip() for task_id,label in args['rounds'].items()}
                    if any(not label or task_id not in run['tasks'] or run['tasks'][task_id]['spec'].get('round')
                           for task_id,label in rounds.items()):
                        raise Invalid('Supply nonempty display labels for existing Tasks without a round')
                    if rounds != run.get('task_rounds',{}):
                        run['task_rounds'] = rounds
                    result = {'tasks':len(rounds)}
                elif op == 'command':
                    tools = RunTools(store,run_id)
                    schema = next(d['inputSchema'] for d in tools.definitions() if d['name']=='command')
                    contract(args,schema,'arguments')
                    tools.runtime.command_in_run(run,**args)
                    result = {'status':run['status']}
                else:
                    raise Invalid('Unknown Run operation')
        receipt = {'request_id':ident,'run_id':run_id,'operation':op,'status':'completed','result':result}
        db.execute('INSERT INTO run_requests VALUES (?,?,?,?)',(ident,run_id,digest(a),json.dumps(receipt)))
        db.commit()
        return receipt
