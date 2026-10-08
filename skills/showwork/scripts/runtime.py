"""Private, disposable storage outside the project tree."""

import hashlib
import os
from pathlib import Path
import stat
import tempfile


def temporary_root():
    return Path('/tmp' if os.name == 'posix' else tempfile.gettempdir()).resolve()


def workspace(project):
    project = Path(project).expanduser().resolve()
    identity = str(os.getuid()) if hasattr(os, 'getuid') else hashlib.sha256(str(Path.home()).encode()).hexdigest()
    root = temporary_root() / ('showwork-' + identity)
    target = root / hashlib.sha256(os.fsencode(project)).hexdigest()
    if target.is_relative_to(project):
        raise ValueError('Temporary Showwork storage must be outside the project')
    for directory in (root, target):
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or (os.name == 'posix' and
                (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077)):
            raise ValueError(f'Unsafe temporary directory: {directory}')
    return target
