"""Small OS boundary for the platform process, locks and idle-sleep protection."""
import ctypes
import errno
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

from loop_anything.runtime.model import Invalid


class CommandNotStopped(Invalid):
    """The caller must retain Agent ownership until the command is confirmed stopped."""


def lock_database(filename):
    lock = open(str(Path(filename).resolve()) + '.engine.lock', 'a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            if lock.seek(0, 2) == 0:
                lock.write(b'\0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        lock.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            raise Invalid('Another engine already owns this database') from exc
        raise
    return lock  # Closing the descriptor releases either OS lock.


def run_command(command, request_text, timeout, cwd=None, stop=None):
    if stop is not None and stop.is_set():
        raise Invalid('Platform stopped before command started')
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace', cwd=cwd, **options)
    deadline = time.monotonic() + timeout if timeout is not None else None
    try:
        while True:
            remaining = max(0, deadline - time.monotonic()) if deadline is not None else None
            wait = (min(1, remaining) if remaining is not None else 1) if stop is not None else remaining
            try:
                out, err = process.communicate(request_text, timeout=wait)
                break
            except subprocess.TimeoutExpired:
                request_text = None  # communicate retains buffered input/output across waits.
                if (stop is not None and stop.is_set()) or (deadline is not None and time.monotonic() >= deadline):
                    raise
    except subprocess.TimeoutExpired as exc:
        try:
            stop_command(process)
        except (OSError, subprocess.SubprocessError) as failure:
            raise CommandNotStopped('Unable to confirm command stopped: ' + str(failure)) from failure
        raise Invalid('Platform stopped the Agent command' if stop is not None and stop.is_set() else 'Configured command timed out') from exc
    return subprocess.CompletedProcess(command, process.returncode, out, err)


def stop_command(process):
    if os.name == 'nt':
        result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=5)
        if result.returncode:
            raise CommandNotStopped('Unable to stop timed-out command tree: ' + result.stderr.decode(errors='replace'))
        process.communicate(timeout=5)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # A parent closing its pipes does not prove its children stopped.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=5)
        deadline = time.monotonic() + 5
        while True:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() >= deadline:
                raise CommandNotStopped('Timed-out process group still exists; verify it stopped before releasing ownership')
            time.sleep(.02)


def windows_execution_state(flags):
    call = ctypes.windll.kernel32.SetThreadExecutionState
    call.argtypes = [ctypes.c_uint]
    call.restype = ctypes.c_uint
    previous = call(flags)
    if not previous:
        raise OSError('Windows rejected the idle-sleep protection request')
    return previous


class KeepAwake:
    """Acquire for the server lifetime; no persistent power-plan changes."""
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.active = False
        self.backend = None
        self.error = None
        self.process = None
        self.previous = None
        self.reader = None

    def __enter__(self):
        if not self.enabled:
            return self
        try:
            if sys.platform == 'win32':
                self.backend = 'Windows execution state'
                self.previous = windows_execution_state(0x80000001)  # continuous + system required, not display
            elif sys.platform == 'darwin':
                self.backend = 'caffeinate'
                self.process = subprocess.Popen(['/usr/bin/caffeinate', '-i', '-w', str(os.getpid())],
                                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    self.process.wait(timeout=.1)
                except subprocess.TimeoutExpired:
                    pass
                else:
                    raise OSError(self.process.stderr.read().decode(errors='replace') or 'caffeinate exited')
            elif sys.platform.startswith('linux'):
                self.backend = 'systemd-inhibit'
                executable = shutil.which('systemd-inhibit')
                if not executable:
                    raise OSError('systemd-inhibit is unavailable; no sleep protection was acquired')
                # The child runs only after the inhibitor is acquired. EOF also releases on parent exit.
                self.process = subprocess.Popen([executable, '--what=idle:sleep', '--mode=block', '--who=Loop Anything',
                    '--why=Loop Anything is running', sys.executable, '-c',
                    'import sys;print("ready",flush=True);sys.stdin.read()'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                ready, response = threading.Event(), []
                def read_ready():
                    response.append(self.process.stdout.readline().strip())
                    ready.set()
                self.reader = threading.Thread(target=read_ready, daemon=True)
                self.reader.start()
                if not ready.wait(3) or response != ['ready']:
                    raise OSError('Could not acquire a logind inhibitor; check systemd-inhibit and session permissions')
            else:
                raise OSError('No sleep-inhibition backend for this operating system')
            self.active = True
        except OSError as exc:
            self.error = str(exc)
            self._close_process()
        return self

    def status(self):
        if self.active and self.process is not None and self.process.poll() is not None:
            self.active = False
            self.error = 'The sleep-protection helper exited; protection is no longer active'
        return {'requested': self.enabled, 'active': self.active, 'backend': self.backend, 'error': self.error}

    def _close_process(self):
        if self.process is None:
            return
        if self.process.stdin:
            self.process.stdin.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        if self.reader:
            self.reader.join(timeout=1)
        for stream in (self.process.stdout, self.process.stderr):
            if stream:
                stream.close()
        self.process = None

    def __exit__(self, *args):
        if self.previous is not None:
            windows_execution_state(self.previous | 0x80000000)
            self.previous = None
        self._close_process()
        self.active = False
