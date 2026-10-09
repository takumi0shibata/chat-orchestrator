"""Workspace selection shared by artifact detection and checkpoints."""

import os
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

EXCLUDED_DIRS = {
    ".venv", "venv", "node_modules", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
}


def workspace_git(root: Path, options, *, input=None, worktree=None, timeout=600, success=(0,)):
    """Run read-only Git queries, including in folders without a repository."""
    # Listing must not use an inherited index/worktree or invoke a fsmonitor hook.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", LC_ALL="C")
    command = ["git", "-c", "core.fsmonitor=false", "-C", str(root)]
    def run(args, data=None):
        return subprocess.run(args, input=data, env=env, capture_output=True, timeout=timeout)

    result = run(command + options, input)
    if result.returncode not in success and b"not a git repository" in result.stderr:
        # Plain folders can also contain .gitignore. The temporary empty index is
        # outside the workspace; never create a .git or change the user's index.
        with tempfile.TemporaryDirectory(prefix="workspace-scan-") as scratch:
            init = run(["git", "init", "--bare", "--quiet", "--template=", scratch])
            if init.returncode:
                raise OSError(init.stderr.decode(errors="replace"))
            result = run(command + [f"--git-dir={scratch}", f"--work-tree={worktree or root}"] + options, input)
    if result.returncode not in success:
        raise OSError("Could not query workspace files: " + result.stderr.decode(errors="replace")[-2000:])
    return result.stdout


def git_files(root: Path):
    """Let Git prune ignored directories, retaining tracked files and nested repos."""
    options = ["ls-files", "-z", "--cached", "--others", "--exclude-per-directory=.gitignore"]
    options += [f"--exclude={name}/" for name in sorted(EXCLUDED_DIRS)]
    output = workspace_git(root, options)
    return {os.fsdecode(p).rstrip("/") for p in output.split(b"\0") if p}


def ignored_names(root: Path, relative: str, names):
    """Decorate only the listed entries; never enumerate their descendants."""
    if not names:
        return set()
    root = root.resolve()
    try:
        output = workspace_git(
            root / relative, ["check-ignore", "--stdin", "-z", "--verbose"],
            input=b"".join(os.fsencode(name) + b"\0" for name in names),
            worktree=root, timeout=5, success=(0, 1),
        )
    except (OSError, subprocess.SubprocessError):
        # File browsing remains usable if Git is missing or unavailable.
        return set()
    fields = output.split(b"\0")[:-1]
    return {
        os.fsdecode(path)
        for source, pattern, path in zip(fields[::4], fields[2::4], fields[3::4], strict=True)
        if (source == b".gitignore" or source.endswith(b"/.gitignore"))
        and not pattern.startswith(b"!")
    }


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
