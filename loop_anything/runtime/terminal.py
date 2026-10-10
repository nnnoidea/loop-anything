"""Durable execution output and optional PTY attachment to the existing Agent process."""
import codecs
from contextlib import nullcontext
import errno
import json
import os
from pathlib import Path
import queue
import select
import subprocess
import sys
import tempfile
import threading
import time
from loop_anything.runtime.model import Invalid, Conflict
from loop_anything.runtime.host_runtime import CommandStartError, CommandNotStopped, stop_command


class Redactor:
    """Keep only a possible secret prefix between chunks, without delaying normal output."""
    def __init__(self, secrets):
        self.secrets = [s for s in secrets if s]
        self.pending = ''

    def feed(self, text, final=False):
        text = self.pending + text
        for secret in self.secrets:
            text = text.replace(secret, '[redacted]'.ljust(len(secret)))
        keep = 0
        if not final:
            for secret in self.secrets:
                for size in range(1, min(len(secret), len(text) + 1)):
                    if text.endswith(secret[:size]):
                        keep = max(keep, size)
        self.pending = text[-keep:] if keep else ''
        return text[:-keep] if keep else text


class TerminalSessions:
    def __init__(self, store):
        self.store, self.live, self.lock = store, {}, threading.RLock()
        with store.connection() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS execution_sessions (
              id TEXT PRIMARY KEY, run_id TEXT NOT NULL, execution_id TEXT NOT NULL, document TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS sessions_execution ON execution_sessions(run_id, execution_id);
            CREATE TABLE IF NOT EXISTS execution_output (
              session_id TEXT NOT NULL, sequence INTEGER NOT NULL, text TEXT NOT NULL,
              PRIMARY KEY(session_id, sequence));
            ''')

    def recover(self):
        with self.store.connection() as db:
            for row in db.execute('SELECT id, document FROM execution_sessions').fetchall():
                doc = json.loads(row['document'])
                if doc['state'] in ('starting', 'running'):
                    doc.update(state='interrupted', ended_at=time.time(), error='平台连接中断；确认旧进程停止后再恢复任务。')
                    db.execute('UPDATE execution_sessions SET document=? WHERE id=?', (json.dumps(doc), row['id']))
            db.commit()

    def create(self, run_id, execution_id, ident, interactive=False, secrets=(), metadata=None, _db=None):
        doc = dict(id=ident, run_id=run_id, execution_id=execution_id, interactive=interactive,
                   state='starting', created_at=time.time(), cols=100, rows=30)
        doc.update(metadata or {})
        with (self.store.connection() if _db is None else nullcontext(_db)) as db:
            db.execute('INSERT INTO execution_sessions VALUES (?,?,?,?)', (ident, run_id, execution_id, json.dumps(doc)))
            if _db is None:db.commit()
        return Session(self, doc, secrets)

    def read(self, run_id, execution_id, ident=None, after=0):
        if type(after) is not int or after < 0:
            raise Invalid('Output cursor must be a nonnegative integer')
        with self.store.connection() as db:
            docs = [json.loads(r[0]) for r in db.execute('SELECT document FROM execution_sessions WHERE run_id=? AND execution_id=? ORDER BY rowid', (run_id, execution_id))]
            if not docs:
                return dict(sessions=[], session=None, output=[], cursor=0, more=False)
            doc = next((d for d in docs if d['id'] == ident), None) if ident else docs[-1]
            if doc is None:
                raise Invalid('Unknown execution session')
            rows = [dict(r) for r in db.execute('SELECT sequence, text FROM execution_output WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT 64', (doc['id'], after))]
        with self.lock:
            session = self.live.get(doc['id'])
            doc['can_input'] = bool(session and session.writable())
        return dict(sessions=docs, session=doc, output=rows, cursor=rows[-1]['sequence'] if rows else after, more=len(rows) == 64)

    def control(self, run_id, execution_id, ident, data=None, cols=None, rows=None):
        if data is not None and (not isinstance(data, str) or not data or len(data.encode()) > 65536):
            raise Invalid('Terminal input must be 1–65536 UTF-8 bytes')
        if (cols is not None or rows is not None) and not (type(cols) is int and type(rows) is int and 2 <= cols <= 500 and 2 <= rows <= 300):
            raise Invalid('Invalid terminal dimensions')
        if data is None and cols is None:
            raise Invalid('Supply terminal input or dimensions')
        with self.lock:
            session = self.live.get(ident)
            if not session or (session.doc['run_id'], session.doc['execution_id']) != (run_id, execution_id) or not session.writable():
                raise Conflict('此执行会话已结束、尚未就绪或不支持输入。')
            if data is not None:
                try:
                    session.inputs.put_nowait(data.encode())
                except queue.Full:
                    raise Conflict('终端输入忙，请稍后重试。')
            if cols is not None:
                resize(session.master, cols, rows)
                session.screen.resize(lines=rows, columns=cols)
                session.doc.update(cols=cols, rows=rows)
                session.save()
        return {'accepted': True}


def resize(fd, cols, rows):
    import fcntl
    import struct
    import termios
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))


class Session:
    def __init__(self, manager, doc, secrets):
        self.manager, self.doc = manager, doc
        self.sequence, self.master, self.process = 0, None, None
        self.redactors = {s: Redactor(secrets) for s in ('stdout', 'stderr')}
        self.check = self.capture = self.on_started = None
        self.native_id = None
        self.output_tail = ''
        self.inputs = queue.Queue(maxsize=32)
        self.responses = bytearray()
        self.screen = self.stream = None
        if doc['interactive']:
            from loop_anything._vendor.pyte import Screen, Stream
            self.screen = Screen(doc['cols'], doc['rows'])
            self.screen.write_process_input = lambda data: self.responses.extend(data.encode())
            self.stream = Stream(self.screen)

    def save(self):
        with self.manager.store.connection() as db:
            db.execute('UPDATE execution_sessions SET document=? WHERE id=?', (json.dumps(self.doc), self.doc['id']))
            db.commit()

    def append(self, stream, text, final=False):
        if self.capture:
            try:self.capture.feed(stream,text,final)
            except (Invalid, Conflict) as exc:
                # Identity discovery is ancillary; it must not abort work or hide an uncertain stop.
                self.capture.found=True
                self.doc['native_session_error']=str(exc)
                self.save()
        if self.stream and text:
            with self.manager.lock:
                self.stream.feed(text)
        text = self.redactors[stream].feed(text, final)
        if text:
            self.output_tail = (self.output_tail + text)[-65536:]
            self.sequence += 1
            with self.manager.store.connection() as db:
                db.execute('INSERT INTO execution_output VALUES (?,?,?)', (self.doc['id'], self.sequence, text))
                db.commit()
        return text

    def writable(self):
        return self.doc['interactive'] and self.master is not None and self.process is not None and self.process.poll() is None and (not self.check or self.check() is None)

    def run(self, command, prompt, timeout, cwd, stop):
        interactive = self.doc['interactive']
        if interactive and os.name != 'posix':
            self.doc.update(state='error', error='交互终端当前需要 macOS/Linux；此主机请使用普通命令模式。', ended_at=time.time())
            self.save()
            raise CommandStartError(self.doc['error'])
        events, readers = queue.Queue(maxsize=64), []
        collected = {'stdout': '', 'stderr': ''}
        def reader(stream, source):
            decoder = codecs.getincrementaldecoder('utf-8')('replace')
            try:
                while True:
                    try:
                        chunk = os.read(source, 8192)
                    except OSError as exc:
                        if interactive and exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                            select.select([source], [], [], .1)
                            continue
                        if interactive and exc.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    events.put((stream, decoder.decode(chunk)))
            finally:
                events.put((stream, decoder.decode(b'', final=True)))
                events.put((stream, None))
        error, slave = None, None
        try:
            if stop is not None and stop.is_set():
                raise Invalid('Platform stopped before command started')
            with tempfile.TemporaryDirectory(prefix='loop-agent-prompt-') as directory:
                argv = [arg.replace('{{session_id}}', self.native_id) if self.native_id else arg for arg in command]
                env = None
                if interactive:
                    import pty
                    self.master, slave = pty.openpty()
                    resize(slave, self.doc['cols'], self.doc['rows'])
                    os.set_blocking(self.master, False)
                    file = Path(directory) / 'prompt.txt'
                    file.write_text(prompt, encoding='utf-8'); file.chmod(0o600)
                    argv = [arg.replace('{{prompt_file}}', str(file)).replace('{{prompt}}', prompt) for arg in argv]
                    # The helper acquires a controlling terminal without preexec_fn in a threaded host.
                    argv = [sys.executable, str(Path(__file__).with_name('terminal_child.py')), *argv]
                    env = dict(os.environ, TERM='xterm-256color', LOOP_ANYTHING_PROMPT_FILE=str(file))
                options = {'start_new_session': True} if os.name == 'posix' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
                try:
                    self.process = subprocess.Popen(argv, stdin=slave if interactive else subprocess.PIPE,
                        stdout=slave if interactive else subprocess.PIPE, stderr=slave if interactive else subprocess.PIPE,
                        cwd=cwd, env=env, **options)
                except OSError as exc:
                    raise CommandStartError('Cannot start command in cwd ' + str(cwd or Path.cwd()) + ': ' + str(exc)) from exc
                if slave is not None:
                    os.close(slave); slave = None
                if self.on_started:self.on_started()
                self.doc.update(state='running', pid=self.process.pid)
                self.save()
                with self.manager.lock:
                    self.manager.live[self.doc['id']] = self
                sources = [('stdout', self.master)] if interactive else [('stdout', self.process.stdout.fileno()), ('stderr', self.process.stderr.fileno())]
                for stream, fd in sources:
                    thread = threading.Thread(target=reader, args=(stream, fd), daemon=True)
                    thread.start(); readers.append(thread)
                if not interactive:
                    def send_prompt():
                        try:
                            self.process.stdin.write(prompt.encode()); self.process.stdin.flush()
                        except (BrokenPipeError, OSError):
                            pass
                        finally:
                            try:self.process.stdin.close()
                            except (BrokenPipeError, OSError):pass
                    writer = threading.Thread(target=send_prompt, daemon=True); writer.start()
                deadline = time.monotonic() + timeout if timeout is not None else None
                ended, checked, finished, exit_seen = 0, 0, False, None
                pending_input = b''
                while ended < len(sources) or self.process.poll() is None:
                    now = time.monotonic()
                    if (stop is not None and stop.is_set()) or (deadline is not None and now >= deadline):
                        raise Invalid('Platform stopped the Agent command' if stop is not None and stop.is_set() else 'Configured command timed out')
                    if (interactive or self.doc.get('owner_type') == 'communication') and self.check and not finished and now >= checked:
                        reason = self.check(); checked = now + .3
                        if reason:
                            stop_command(self.process, drain=False)
                            if reason != 'finished':
                                raise Conflict('Agent execution ownership ended')
                            finished = True
                    if interactive and self.process.poll() is None and not finished:
                        if self.responses:
                            try:del self.responses[:os.write(self.master,self.responses)]
                            except BlockingIOError:pass
                            if self.responses:
                                # Backpressure before parsing more output bounds query responses to one chunk.
                                time.sleep(.01)
                                continue
                        if not pending_input:
                            try:
                                pending_input = self.inputs.get_nowait()
                            except queue.Empty:
                                pass
                        if pending_input:
                            try:
                                pending_input = pending_input[os.write(self.master, pending_input):]
                            except BlockingIOError:
                                pass
                    if self.process.poll() is not None:
                        exit_seen = exit_seen or now
                        if ended < len(sources) and now - exit_seen > 1:
                            stop_command(self.process, drain=False)
                    try:
                        stream, value = events.get(timeout=.05)
                    except queue.Empty:
                        continue
                    if value is None:
                        ended += 1
                        value = self.append(stream, '', final=True)
                    else:
                        value = self.append(stream, value)
                    # Output is durable; only the diagnostic tail is held in memory.
                    collected[stream] = (collected[stream] + value)[-65536:]
                self.process.wait()
                if (interactive or self.doc.get('owner_type') == 'communication') and not finished:
                    # A CLI can exit before the finish poll; detached stdio is not proof its children stopped.
                    stop_command(self.process, drain=False)
                self.doc.update(state='exited', returncode=0 if finished else self.process.returncode, finished_by_tool=finished)
                return subprocess.CompletedProcess(command, self.doc['returncode'], collected['stdout'], collected['stderr'])
        except BaseException as exc:
            error = exc
            if self.process is not None:
                try:
                    stop_command(self.process, drain=False)
                except (OSError, subprocess.SubprocessError, CommandNotStopped) as failure:
                    error = CommandNotStopped('Unable to confirm Agent stopped: ' + str(failure))
            self.doc.update(state='interrupted' if isinstance(error, CommandNotStopped) else 'error', error=str(error))
            raise error
        finally:
            with self.manager.lock:
                self.manager.live.pop(self.doc['id'], None)
                if self.master is not None:
                    os.close(self.master); self.master = None
            if slave is not None:
                os.close(slave)
            # Drain reader queues even on timeout, preserving the last visible diagnostics.
            until = time.monotonic() + 2
            while readers and (any(t.is_alive() for t in readers) or not events.empty()) and time.monotonic() < until:
                try:
                    stream, value = events.get(timeout=.05)
                    self.append(stream, value or '', final=value is None)
                except queue.Empty:
                    pass
            for stream in self.redactors:
                self.append(stream, '', final=True)
            if self.process is not None:
                for stream in (self.process.stdout, self.process.stderr):
                    if stream:
                        stream.close()
            self.doc['ended_at'] = time.time()
            self.save()
