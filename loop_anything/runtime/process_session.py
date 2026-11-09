"""Run the existing terminal/process machinery without a platform database."""
import threading
import uuid
from types import SimpleNamespace
from loop_anything.runtime.terminal import Session
from loop_anything.runtime.native_sessions import Capture, provider_for


class ProcessSession(Session):
    def __init__(self, ident, config, changed=lambda doc:None, output=lambda stream,text:None):
        manager=SimpleNamespace(lock=threading.RLock(),live={})
        super().__init__(manager,{'id':ident,'run_id':'','execution_id':ident,'state':'starting',
            'interactive':config.get('terminal',False),'owner_type':'communication','cols':100,'rows':30},())
        self.changed,self.output=changed,output
        self.check=lambda:None
        def native(provider,ident):
            self.doc['native_session']={'provider':provider,'id':ident,'cwd':config.get('cwd')}
            self.save()
        self.capture=Capture(provider_for(config),native)
        self.doc['native_history']=bool(config.get('native_history') or config.get('resume_command')) or provider_for(config) in ('codex','claude')
        if config.get('native_session'):
            self.native_id=config['native_session']['id']
            self.doc['native_session']=config['native_session']
        elif config.get('native_id') or any('{{session_id}}' in arg for arg in config.get('command',[])):
            self.native_id=config.get('native_id') or str(uuid.uuid4())
            self.on_started=lambda:native(provider_for(config),self.native_id)

    def save(self):
        self.changed(dict(self.doc))

    def append(self, stream, text, final=False):
        text=self.decode_output(stream,text,final)
        self.output_tail=(self.output_tail+text)[-8192:]
        if text:self.output(stream,text)
        return text

    def finish_recording(self):
        if self.has_native_history() and self.doc.get('returncode')==0:
            self.doc['output_source']='native_session'
        else:self.doc['output_tail']=self.output_tail
