"""Service scheduling independent of the optional HTTP/web interface."""
import threading
import traceback
from loop_anything.runtime.scheduling import Scheduler
from loop_anything.runtime.store import Store


class ServiceHost:
    def __init__(self, engine, mailbox=None):
        self.engine=engine
        self.stop=threading.Event()
        self.schedulers=[]
        self.threads=[]
        self.mailbox=mailbox

    def tick(self):
        if self.mailbox:
            from loop_anything.runtime.executors import service
            backend=service(self.engine.store);backend.root=self.mailbox.root;backend.sync()
        else:self.engine.executors.advance()
        try:self.engine.communication.tick()
        except Exception:traceback.print_exc()
        for run in self.engine.store.scheduling_list():
            try:self.engine.tick(run['id'])
            except Exception as exc:
                with self.engine.store.edit(run['id']) as current:
                    current['status']='paused'
                    Store.log(current,'engine_error',str(exc))
                traceback.print_exc()

    def start(self):
        self.engine.communication.background_transport=True
        callbacks=[(self.tick,.75),(self.engine.communication.scan,.4)]
        if self.mailbox:callbacks.append((self.mailbox.tick,.5))
        for callback,interval in callbacks:
            def safe(fn=callback):
                try:fn()
                except Exception:traceback.print_exc()
            scheduler=Scheduler(self.stop);scheduler.add(safe,interval)
            thread=threading.Thread(target=scheduler.run,daemon=True)
            self.schedulers.append(scheduler);self.threads.append(thread);thread.start()
        return self

    def close(self):
        self.stop.set()
        for thread in self.threads:thread.join(timeout=5)
        self.engine.close()
