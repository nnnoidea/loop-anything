import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from loop_anything.runtime.service_host import ServiceHost
from loop_anything.runtime.store import Store


class ServiceHostTests(unittest.TestCase):
    def test_run_error_pauses_only_that_run_and_records_the_cause(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'runs.sqlite3')
            loop = {
                'schema_version': 2, 'id': 'service-host', 'version': '1',
                'handbook': {'instructions': 'Run each task independently.'},
                'nodes': {'step': {'instructions': 'Complete the task.', 'inputs': {}, 'outputs': {}}},
            }
            implementations = {'step': {'options': {'default': {'kind': 'agent'}}, 'default': 'default'}}
            key = store.publish(loop, implementations)['key']
            failed = store.create(key, 'Failing Run')['id']
            healthy = store.create(key, 'Healthy Run')['id']
            engine = SimpleNamespace(store=store, work=Mock(), executors=Mock(),
                                     tick=Mock(side_effect=[RuntimeError('Run tick failed'), None]))

            with patch.object(store, 'scheduling_list', return_value=[{'id': failed}, {'id': healthy}]), \
                    patch('loop_anything.runtime.service_host.traceback.print_exc'):
                ServiceHost(engine).tick()

            self.assertEqual([call.args[0] for call in engine.tick.call_args_list], [failed, healthy])
            run = store.get(failed)
            self.assertEqual(run['status'], 'paused')
            self.assertEqual((run['history'][-1]['kind'], run['history'][-1]['message']),
                             ('engine_error', 'Run tick failed'))
            self.assertEqual(store.get(healthy)['status'], 'running')

    def test_blocked_team_transport_does_not_delay_local_work_or_runs(self):
        release = threading.Event()
        scanning = threading.Event()
        waiting_for_lock = threading.Event()
        syncing = threading.Event()
        verify = threading.Event()
        sampled = threading.Event()
        advanced = threading.Event()
        communication_lock = threading.Lock()

        def scan():
            with communication_lock:
                scanning.set()
                release.wait()

        def communicate():
            waiting_for_lock.set()
            with communication_lock:
                pass

        def sync():
            syncing.set()
            release.wait()

        def sample():
            if verify.is_set():
                sampled.set()

        def advance(run_id):
            if verify.is_set() and run_id == 'existing-run':
                advanced.set()

        engine = SimpleNamespace(
            work=SimpleNamespace(tick=sample),
            executors=SimpleNamespace(advance=lambda: None, sync=sync),
            communication=SimpleNamespace(scan=scan, tick=communicate),
            store=SimpleNamespace(scheduling_list=lambda: [{'id': 'existing-run'}]),
            tick=advance,
            close=lambda: None,
        )
        host = ServiceHost(engine, SimpleNamespace(root='team', tick=lambda: None)).start()
        try:
            self.assertTrue(scanning.wait(3), 'The team scan did not acquire the communication lock')
            self.assertTrue(waiting_for_lock.wait(3), 'Communication did not wait for the team scan')
            self.assertTrue(syncing.wait(3), 'The NAS executor sync did not start')
            verify.set()
            self.assertTrue(sampled.wait(3), 'Local monitor scheduling stalled')
            self.assertTrue(advanced.wait(3), 'Run scheduling stalled')
        finally:
            release.set()
            host.close()
