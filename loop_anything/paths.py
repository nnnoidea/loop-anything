"""Shared local defaults; explicit --db always selects an existing workspace."""
import os
from pathlib import Path
import sys

DEFAULT_PORT = 8767
DEFAULT_URL = 'http://127.0.0.1:%s' % DEFAULT_PORT


def data_directory():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'Loop Anything'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Loop Anything'
    base = Path(os.environ.get('XDG_DATA_HOME', ''))
    if not base.is_absolute():
        base = Path.home() / '.local' / 'share'
    return base / 'loop-anything'


def default_database():
    return data_directory() / 'runs.sqlite3'


def platform_skill_directory():
    """Use the source Skill or the same resources installed with the platform."""
    source = Path(__file__).resolve().parents[1] / 'skills/loop-anything-platform'
    if (source / 'SKILL.md').is_file():
        return source
    return Path(sys.prefix) / 'share/loop-anything/skills/loop-anything-platform'
