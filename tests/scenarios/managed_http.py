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
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        turn = tool(api, 'claim_run', run_id=run_id, **session)
        if turn.get('token'):
            return turn
        time.sleep(.1)
    raise AssertionError('No management turn became ready for '+run_id)


def operate(api, turn, name, **arguments):
    return api('runs/'+turn['run_id']+'/agent', {'token':turn['token'],'tool':name,'arguments':arguments})


def finish_turn(api, turn):
    result = operate(api, turn, 'report_task', task_id=turn['task_id'], event='completed',
                     report_id='managed', envelope={'outputs':{'decision':'Accepted simulation work'}})
    assert result['accepted']
    operate(api, turn, 'finish')
