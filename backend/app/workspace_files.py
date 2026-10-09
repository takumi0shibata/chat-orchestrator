"""Workspace selection shared by artifact detection and checkpoints."""

import os
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

EXCLUDED_DIRS = {
    ".venv", "venv", "node_modules", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
}


def git_files(root: Path):
    """Let Git prune ignored directories, retaining tracked files and nested repos."""
    # Listing must not use an inherited index/worktree or invoke a fsmonitor hook.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", LC_ALL="C")
    command = ["git", "-c", "core.fsmonitor=false", "-C", str(root)]
    options = ["ls-files", "-z", "--cached", "--others", "--exclude-per-directory=.gitignore"]
    options += [f"--exclude={name}/" for name in sorted(EXCLUDED_DIRS)]

    def run(args):
        return subprocess.run(args, env=env, capture_output=True, timeout=600)

    result = run(command + options)
    if result.returncode and b"not a git repository" in result.stderr:
        # Plain folders can also contain .gitignore. The temporary empty index is
        # outside the workspace; never create a .git or change the user's index.
        with tempfile.TemporaryDirectory(prefix="workspace-scan-") as scratch:
            init = run(["git", "init", "--bare", "--quiet", "--template=", scratch])
            if init.returncode:
                raise OSError(init.stderr.decode(errors="replace"))
            result = run(command + [f"--git-dir={scratch}", f"--work-tree={root}"] + options)
    if result.returncode:
        raise OSError("Could not list workspace files: " + result.stderr.decode(errors="replace")[-2000:])
    return {os.fsdecode(p).rstrip("/") for p in result.stdout.split(b"\0") if p}


def scan_files(root: Path, *, include=()):
    """Stat selected regular files only, without following directory symlinks.

    include is used solely to check Undo conflicts for older snapshots, whose
    paths may now be ignored. It never expands the normal checkpoint scope.
    """
    root = root.resolve()
    if not root.exists():
        return {}
    result, pending, visited = {}, [root], set()
    safe_dirs = {root: True}

    def safe_directory(path):
        if path not in safe_dirs:
            safe_dirs[path] = safe_directory(path.parent) and not path.is_symlink()
        return safe_dirs[path]

    while pending:
        folder = pending.pop()
        if folder in visited:
            continue
        visited.add(folder)
        names = git_files(folder)
        if folder == root:
            names.update(include)
        for name in names:
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError("Unsafe workspace path")
            path = folder / name
            parts = path.relative_to(root).parts
            if any(p in EXCLUDED_DIRS for p in parts[:-1]) or not safe_directory(path.parent):
                continue
            try:
                info = path.lstat()
            except (FileNotFoundError, NotADirectoryError):
                continue
            if stat.S_ISDIR(info.st_mode):
                # Git lists submodules/nested repositories as a directory entry.
                if path.name not in EXCLUDED_DIRS:
                    pending.append(path)
            elif stat.S_ISREG(info.st_mode) and path.name != ".git":
                result[path.relative_to(root).as_posix()] = (
                    info.st_size, info.st_mtime_ns,
                    "100755" if info.st_mode & stat.S_IXUSR else "100644",
                )
    return result
