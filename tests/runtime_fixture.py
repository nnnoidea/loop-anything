"""Internal runtime fixtures for scoped execution tests."""
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


def seeded_draft(tools, arguments):
    """Explicit ordinary entry for tests of ports, routing and standalone execution."""
    result=tools.call('create_loop',arguments)
    draft=tools._draft(result['draft_id'])
    bp=draft['loop_definition'];bp.update(entry='initialize',seed={'id':'initialize','node':'initialize','inputs':{},'outputs':{}})
    bp['nodes']['initialize']={'instructions':'Read current progress and arrange the specified work.','inputs':{},'outputs':{}}
    impl={'initialize':{'options':{'default':{'kind':'agent'}},'default':'default'}}
    return tools._summary(tools.store.save_draft(bp,impl,draft['id'],draft['revision']),authoring=True)
