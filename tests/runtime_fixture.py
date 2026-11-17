"""Internal runtime fixtures; public startup is exercised in test_steward.

Low-level lifecycle/contract tests construct an execution identity directly, without
pretending to be a client or invoking a real steward CLI.
"""
from loop_anything.interfaces.agent_tasks import acquire


def runtime_run(store, arguments):
    run = store.create(acquire=True, **arguments)
    return {'run_id': run['id'], 'token': run['agent_sessions'][0]['token'],
            'entry_task_id': run['loop_definition']['seed']['id']}


def runtime_acquire(store, arguments):
    return acquire(store, **arguments)


def update_work(store, run_id, change, revision=None):
    """User semantic edits now use the independent Timeline, not Run settings."""
    from loop_anything.interfaces.platform_tools import PlatformTools
    run=store.get(run_id)
    return PlatformTools(store).call('update_timeline',{
        'timeline_id':run['timeline_id'],
        'revision':run['timeline']['revision'] if revision is None else revision,
        'change':change})


from loop_anything.interfaces.platform_tools import PlatformTools


class RuntimeStewardTools(PlatformTools):
    """Exercise the existing internal decision lifecycle without spawning a caller.
    Public current-session startup is covered by test_work_context.
    """
    def call(self,name,arguments):
        if name=='assign_run_steward':
            from loop_anything.runtime.steward import assign
            return assign(self.store,arguments['run_id'],arguments['steward_id'],arguments['generation'])
        if name=='start_run' and 'steward_id' in arguments and 'request_id' in arguments:
            from loop_anything.runtime.steward import submit
            return submit(self.store,dict(arguments,operation='start'))
        return super().call(name,arguments)


from contextlib import contextmanager

@contextmanager
def client_work(url, refs=()):
    """A previously discovered platform for tests of payloads, not routing itself."""
    import os
    import tempfile
    from unittest.mock import patch
    from loop_anything.runtime.tool_client import module
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,LOOP_ANYTHING_SPACES=folder+'/spaces.json'):
        routing=module('routing');work=routing.bind_context({'platform_url':url,'workspace_id':'test-workspace'})
        ledger=routing.Ledger()
        try:
            with ledger.db:ledger.remember(work,refs)
        finally:ledger.close()
        with patch.dict(os.environ,LOOP_ANYTHING_WORK=work):yield work
