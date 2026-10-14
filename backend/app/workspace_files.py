"""Workspace selection shared by artifact detection and checkpoints."""

import os
import stat
import sys
import unicodedata
from pathlib import Path

EXCLUDED_DIRS = {
    ".venv", "venv", "node_modules", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
}


def relative_name(name):
    # macOS filesystems may store decomposed names; keys match Git's precomposed form.
    if sys.platform == "darwin" and not name.isascii():
        return unicodedata.normalize("NFC", name)
    return name


def scan_files(root: Path, *, reuse=None, stale=frozenset()):
    """Stat regular files, skipping EXCLUDED_DIRS and never following symlinks.

    Each state is (size, mtime_ns, mode, ctime_ns, dev, ino). Directories are
    listed on every call, so new and deleted files stay exact. reuse maps paths
    to states known to be current (from file events); those are returned
    without a stat unless listed in stale.
    """
    root = root.resolve()
    if not root.is_dir():
        return {}
    reuse = reuse or {}
    result, pending = {}, [(str(root), "")]
    while pending:
        folder, prefix = pending.pop()
        try:
            entries = os.scandir(folder)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        with entries:
            for entry in entries:
                relative = prefix + relative_name(entry.name)
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in EXCLUDED_DIRS:
                            pending.append((entry.path, relative + "/"))
                        continue
                    # Symlinks, sockets and FIFOs are never selected.
                    if not entry.is_file(follow_symlinks=False) or entry.name == ".git":
                        continue
                    known = reuse.get(relative)
                    if known is not None and relative not in stale:
                        result[relative] = known
                        continue
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    result[relative] = (
                        info.st_size, info.st_mtime_ns,
                        "100755" if info.st_mode & stat.S_IXUSR else "100644",
                        info.st_ctime_ns, info.st_dev, info.st_ino,
                    )
    return result
