"""Current-session startup for the local, simulated HTTP acceptance scenarios."""
import os
import sys
import time
import uuid


def tool(api, name, **arguments):
    return api('tools', {'tool': name, 'arguments': arguments})


def register(api):
    registered = tool(api, 'register_work_session',
                native_session={'provider': 'custom', 'id': uuid.uuid4().hex, 'cwd': os.getcwd()},
                implementation={'kind': 'agent', 'command': [sys.executable, '-c', 'pass'],
                                'resume_command': [sys.executable,'-c','pass','{{session_id}}','{{prompt}}']},
                process_id=os.getpid())
    return {key:registered[key] for key in ('session_id','session_token')}


def start(api, session, key, title, **options):
    return api('runs', dict(session, request_id=uuid.uuid4().hex, key=key, title=title, **options))


def claim(api, session, run_id):
    return dict(run_id=run_id,**tool(api,'acquire_run',run_id=run_id))


def operate(api, turn, name, **arguments):
    return api('runs/'+turn['run_id']+'/agent', {'token':turn['token'],'tool':name,'arguments':arguments})


def finish_turn(api, turn):
    operate(api, turn, 'finish')
