"""Service scheduling independent of the optional HTTP/web interface."""
import threading
import traceback
from loop_anything.runtime.scheduling import Scheduler


class ServiceHost:
    def __init__(self, engine, mailbox=None):
        self.engine=engine
        self.stop=threading.Event()
        self.schedulers=[]
        self.threads=[]
        self.mailbox=mailbox

    def tick(self):
        self.engine.work.tick()
        self.engine.executors.advance()
        for run in self.engine.store.scheduling_list():
            try:self.engine.tick(run['id'])
            except Exception as exc:
                with self.engine.store.edit(run['id']) as current:
                    current['status']='paused'
                    Store.log(current,'engine_error',str(exc))
                traceback.print_exc()

    def start(self):
        self.engine.communication.background_transport=True
        # A team transport can block in the filesystem while holding a
        # communication lock. Local work and Run scheduling have their own clock.
        callbacks=[('local',self.tick,.75),('communication',self.engine.communication.tick,.75),
                   ('transport',self.engine.communication.scan,.4)]
        if self.mailbox:
            self.engine.executors.root=self.mailbox.root
            callbacks.extend([('executors',self.engine.executors.sync,.75),('mailbox',self.mailbox.tick,.5)])
        for name,callback,interval in callbacks:
            def safe(fn=callback):
                try:fn()
                except Exception:traceback.print_exc()
            scheduler=Scheduler(self.stop);scheduler.add(safe,interval)
            thread=threading.Thread(target=scheduler.run,name='loop-'+name,daemon=True)
            self.schedulers.append(scheduler);self.threads.append(thread);thread.start()
        return self

    def close(self):
        self.stop.set()
        for thread in self.threads:thread.join(timeout=5)
        self.engine.close()
