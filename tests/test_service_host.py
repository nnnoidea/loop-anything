import threading
import unittest
from types import SimpleNamespace

from loop_anything.runtime.service_host import ServiceHost


class ServiceHostTests(unittest.TestCase):
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
