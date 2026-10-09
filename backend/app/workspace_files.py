"""One metadata scan shared by checkpoints and artifact detection."""

import os
import stat
from pathlib import Path
from typing import NamedTuple

EXCLUDED_DIRS = {
    ".venv", "venv", "node_modules", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
}


class FileState(NamedTuple):
    size: int
    mtime_ns: int
    ctime_ns: int
    inode: int
    device: int
    mode: str


def scan_files(root: Path, *, excluded=()):
    """Stat each regular file once; never follow symlinks or read contents."""
    result = {}
    excluded = {str(Path(path).resolve()) for path in excluded}
    pending = [(str(root.resolve()), "")]
    while pending:
        folder, prefix = pending.pop()
        if folder in excluded or os.path.islink(folder):
            continue
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    relative = prefix + entry.name
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in EXCLUDED_DIRS:
                                pending.append((entry.path, relative + "/"))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        info = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    result[relative] = FileState(
                        info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                        info.st_ino, info.st_dev,
                        "100755" if info.st_mode & stat.S_IXUSR else "100644",
                    )
        except FileNotFoundError:
            continue
    return result
