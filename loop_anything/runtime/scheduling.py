"""Small due-time scheduler shared by the service and standalone local runtime."""
import threading
import time


class Scheduler:
    def __init__(self, stop=None, clock=time.monotonic):
        self.stop=stop or threading.Event()
        self.clock=clock
        self.jobs=[]

    def add(self, callback, interval, immediate=False):
        if interval<=0:raise ValueError('Schedule interval must be positive')
        self.jobs.append([callback,interval,self.clock()+(0 if immediate else interval)])

    def tick(self):
        for job in self.jobs:
            if self.stop.is_set():break
            if self.clock()>=job[2]:
                try:job[0]()
                finally:job[2]=self.clock()+job[1]

    def run(self):
        while not self.stop.is_set():
            self.tick()
            delay=min((job[2]-self.clock() for job in self.jobs),default=1)
            self.stop.wait(max(.01,min(delay,1)))
