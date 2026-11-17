"""Expose the installed launcher in the user's PATH, without changing system files."""
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile

MARKER = '# Loop Anything managed launcher'
BEGIN = '# >>> loop-anything PATH >>>'
END = '# <<< loop-anything PATH <<<'


def _write(path, content, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    permissions = mode if mode is not None else (path.stat().st_mode & 0o777) if path.exists() else 0o644
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.chmod(permissions)
        os.replace(temporary, path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def _section(path, content):
    previous = path.read_text(encoding='utf-8') if path.exists() else ''
    block = BEGIN + '\n' + content + '\n' + END
    pattern = re.escape(BEGIN) + r'.*?' + re.escape(END)
    if BEGIN in previous and not re.search(pattern, previous, flags=re.S):
        raise ValueError('Incomplete Loop Anything PATH section in ' + str(path))
    updated = re.sub(pattern, lambda _: block, previous, flags=re.S) if BEGIN in previous else previous.rstrip('\n') + '\n\n' + block + '\n'
    if previous != updated:
        _write(path.resolve(), updated)


def _windows_path(directory):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
        try: value, kind = winreg.QueryValueEx(key, 'Path')
        except FileNotFoundError: value, kind = '', winreg.REG_EXPAND_SZ
        entries = [s for s in value.split(';') if s]
        if str(directory).casefold() not in {s.rstrip('\\/').casefold() for s in entries}:
            winreg.SetValueEx(key, 'Path', 0, kind, ';'.join([str(directory), *entries]))
    import ctypes
    ctypes.windll.user32.SendMessageTimeoutW(0xffff, 0x1a, 0, ctypes.c_wchar_p('Environment'), 2, 2000, None)


def register(launcher=None, *, home=None, environ=None):
    home = Path(home) if home is not None else Path.home()
    environ = os.environ if environ is None else environ
    windows = sys.platform == 'win32'
    directory = home / '.local' / 'bin'
    target = directory / ('loop-anything.cmd' if windows else 'loop-anything')
    if launcher is None:
        app = Path(sys.prefix).parent
        name = 'Loop Anything.cmd' if windows else 'Loop Anything.command' if sys.platform == 'darwin' else 'loop-anything'
        candidate = app / name
        launcher = candidate if candidate.is_file() else None
    if launcher:
        launcher = Path(launcher).expanduser().absolute()
        if launcher == target.absolute():raise ValueError('Register the installed launcher, not the PATH wrapper itself')
        launcher = launcher.resolve()
        if not launcher.is_file():raise ValueError('Installed launcher is missing: ' + str(launcher))
    if windows:
        command = '"' + str(launcher).replace('%', '%%') + '" %*' if launcher else '"' + sys.executable.replace('%', '%%') + '" -I -m loop_anything %*'
        content = '@echo off\nrem ' + MARKER + '\n' + command + '\n'
    else:
        command = shlex.quote(str(launcher)) if launcher else shlex.quote(sys.executable) + ' -I -m loop_anything'
        content = '#!/bin/sh\n' + MARKER + '\nexec ' + command + ' "$@"\n'
    if target.exists() or target.is_symlink():
        same_launcher = target.is_symlink() and launcher and target.resolve() == launcher
        if not same_launcher and (not target.is_file() or MARKER not in target.read_text(encoding='utf-8', errors='replace')):
            raise FileExistsError('Another command already occupies ' + str(target))
    _write(target, content, 0o644 if windows else 0o755)  # Replace the wrapper, never its former symlink destination.
    profiles = []
    if windows:
        _windows_path(directory)
        activation = 'Open a new terminal.'
    else:
        shell = Path(environ.get('SHELL', '/bin/sh')).name
        quoted = shlex.quote(str(directory))
        script = 'case ":$PATH:" in\n  *:' + quoted + ':*) ;;\n  *) export PATH=' + quoted + ':"$PATH" ;;\nesac'
        if shell == 'fish':
            config = Path(environ.get('XDG_CONFIG_HOME') or home / '.config')
            profiles = [config / 'fish' / 'conf.d' / 'loop-anything.fish']
            script = 'contains -- ' + quoted + ' $PATH; or set -gx PATH ' + quoted + ' $PATH'
        elif shell == 'zsh':
            profiles = [Path(environ.get('ZDOTDIR') or home) / '.zshrc']
        elif shell == 'bash':
            login = next((home / n for n in ('.bash_profile', '.bash_login') if (home / n).exists()), home / '.profile')
            profiles = [home / '.bashrc', login]
        else:
            profiles = [home / '.profile']
        for profile in profiles:_section(profile, script)
        activation = ('set -gx PATH ' + quoted + ' $PATH') if shell == 'fish' else 'export PATH=' + quoted + ':"$PATH"'
    return {'command': str(target), 'profiles': [str(p) for p in profiles],
            'new_terminal': 'loop-anything --help', 'current_terminal': activation}
