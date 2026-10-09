"""Workspace checkpoints stored in an app-managed Git repository.

File selection respects .gitignore while retaining tracked files. Contents are
hashed with ``--no-filters`` and trees are built from a private index.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

from app.workspace_files import scan_files

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "chat-orchestrator",
    "GIT_AUTHOR_EMAIL": "checkpoints@localhost",
    "GIT_COMMITTER_NAME": "chat-orchestrator",
    "GIT_COMMITTER_EMAIL": "checkpoints@localhost",
}
MAX_PATCH_CHARS = 200_000


class CheckpointConflict(Exception):
    def __init__(self, paths):
        self.paths = paths
        super().__init__("Files changed after the run: " + ", ".join(paths[:10]))


def walk(root: Path, max_file_bytes: int, *, include=()):
    """Apply checkpoint size limits to the shared workspace selection."""
    files, skipped = {}, []
    for relative, state in scan_files(root, include=include).items():
        if state[0] > max_file_bytes or "\n" in relative:
            skipped.append(relative)
        else:
            files[relative] = state
    return files, sorted(skipped)


def safe_relative(path: str):
    parts = PurePosixPath(path).parts
    if not parts or PurePosixPath(path).is_absolute() or ".." in parts:
        raise ValueError(f"Unsafe checkpoint path: {path}")
    return parts


class Checkpoints:
    def __init__(self, root: Path, max_file_bytes: int):
        self.root = root
        self.max_file_bytes = max_file_bytes
        self.available = shutil.which("git") is not None

    def repo(self, workspace: Path):
        key = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
        repo = self.root / f"{key}.git"
        if not (repo / "HEAD").exists():
            repo.parent.mkdir(parents=True, exist_ok=True)
            self.git(repo, "init", "--quiet", "--bare", str(repo), bare_init=True)
            (repo / "workspace").write_text(str(workspace.resolve()))
        return repo

    def git(self, repo, *args, input=None, env=None, bare_init=False):
        command = ["git"] + ([] if bare_init else [f"--git-dir={repo}"]) + list(args)
        result = subprocess.run(
            command, input=input, capture_output=True, check=False,
            env={**os.environ, **GIT_ENV, **(env or {})}, timeout=600,
        )
        if result.returncode:
            raise RuntimeError(
                "git " + args[0] + " failed: "
                + result.stderr.decode(errors="replace")[-2000:]
            )
        return result.stdout

    def snapshot(self, workspace: Path, label: str, *, include=()):
        """Return a commit for the workspace's current regular files."""
        repo = self.repo(workspace)
        files, skipped = walk(workspace, self.max_file_bytes, include=include)
        cache_path = repo / "snapshot-cache.json"
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            cache = {}
        # The reverted optimization used a different, versioned cache layout.
        # Rebuild that metadata without touching existing commits or run refs.
        if not isinstance(cache, dict) or isinstance(cache.get("version"), int):
            cache = {}
        # A file modified again within the same mtime tick must be re-hashed later.
        recent = time.time_ns() - 2_000_000_000
        pending = [
            p for p, (size, mtime, _) in files.items()
            if cache.get(p, [None, None])[:2] != [size, mtime]
        ]
        hashed = {}
        if pending:
            output = self.git(
                repo, "hash-object", "-w", "--no-filters", "--stdin-paths",
                input=b"".join(os.fsencode(workspace / p) + b"\n" for p in pending),
            ).decode().split()
            hashed = dict(zip(pending, output, strict=True))
        entries, next_cache = [], {}
        for path, (size, mtime, mode) in sorted(files.items()):
            sha = hashed.get(path) or cache[path][2]
            entries.append(f"{mode} {sha}\t".encode() + os.fsencode(path) + b"\0")
            if mtime < recent:
                next_cache[path] = [size, mtime, sha]
        with tempfile.TemporaryDirectory(dir=repo) as scratch:
            index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
            if entries:
                self.git(
                    repo, "update-index", "-z", "--index-info",
                    input=b"".join(entries), env=index,
                )
            tree = self.git(repo, "write-tree", env=index).decode().strip()
        commit = self.git(repo, "commit-tree", tree, "-m", label).decode().strip()
        cache_path.write_text(json.dumps(next_cache))
        return dict(commit=commit, files=len(files), skipped=skipped)

    def repos(self):
        return sorted(self.root.glob("*.git")) if self.root.exists() else []

    def run_ids(self, repo):
        output = self.git(repo, "for-each-ref", "--format=%(refname)", "refs/checkpoints/")
        return {line.split("/")[2] for line in output.decode().splitlines() if line.count("/") >= 3}

    def delete_runs(self, repo, rids):
        """Drop every checkpoint ref of these runs, then discard unreachable objects."""
        refs = [
            line for line in self.git(
                repo, "for-each-ref", "--format=%(refname)", "refs/checkpoints/"
            ).decode().splitlines()
            if line.count("/") >= 3 and line.split("/")[2] in rids
        ]
        if not refs:
            return 0
        self.git(repo, "update-ref", "--stdin", input="".join(f"delete {r}\n" for r in refs).encode())
        self.git(repo, "gc", "--prune=now", "--quiet")
        return len({r.split("/")[2] for r in refs})

    def set_ref(self, workspace, rid, name, commit):
        self.git(self.repo(workspace), "update-ref", f"refs/checkpoints/{rid}/{name}", commit)

    def get_ref(self, workspace, rid, name):
        try:
            return self.git(
                self.repo(workspace), "rev-parse", "--verify", "--quiet",
                f"refs/checkpoints/{rid}/{name}^{{commit}}",
            ).decode().strip() or None
        except RuntimeError:
            return None

    def tree(self, repo, commit):
        output = self.git(repo, "ls-tree", "-r", "-z", commit)
        result = {}
        for entry in output.split(b"\0"):
            if entry:
                meta, path = entry.split(b"\t", 1)
                mode, _, sha = meta.decode().split()
                result[os.fsdecode(path)] = (mode, sha)
        return result

    def changes(self, workspace, before, after):
        repo = self.repo(workspace)
        status = self.git(
            repo, "diff-tree", "-r", "-z", "--no-renames", "--name-status", before, after
        ).split(b"\0")
        numstat = self.git(
            repo, "diff-tree", "-r", "-z", "--no-renames", "--numstat", before, after
        ).split(b"\0")
        counts = {}
        for entry in numstat:
            if entry:
                added, removed, path = entry.split(b"\t", 2)
                counts[os.fsdecode(path)] = (added.decode(), removed.decode())
        files = []
        for code, path in zip(status[0::2], status[1::2], strict=False):
            if not code:
                continue
            path = os.fsdecode(path)
            added, removed = counts.get(path, ("0", "0"))
            files.append(dict(
                path=path,
                status={"A": "added", "D": "deleted"}.get(code.decode()[0], "modified"),
                added=None if added == "-" else int(added),
                removed=None if removed == "-" else int(removed),
                binary=added == "-",
            ))
        return files

    def patch(self, workspace, before, after, path):
        safe_relative(path)
        text = self.git(
            self.repo(workspace), "diff-tree", "-p", "--no-renames", "--no-color",
            "--no-ext-diff", "--no-textconv", before, after, "--", f":(literal){path}",
        ).decode(errors="replace")
        if len(text) > MAX_PATCH_CHARS:
            return text[:MAX_PATCH_CHARS] + "\n[diff truncated]\n", True
        return text, False

    @staticmethod
    def prune_empty_dirs(root, directory, old):
        """Remove directories the run created once their last file is restored away."""
        while directory != root:
            prefix = directory.relative_to(root).as_posix() + "/"
            if any(p.startswith(prefix) for p in old) or directory.is_symlink():
                return
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent

    def restore(self, workspace: Path, before, after, force=False):
        """Return files changed between before and after to their before state."""
        repo = self.repo(workspace)
        old, new = (self.tree(repo, c) for c in (before, after))
        changed = sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))
        current = self.snapshot(workspace, "pre-restore", include=changed)["commit"]
        now = self.tree(repo, current)
        conflicts = [p for p in changed if now.get(p) != new.get(p)]
        if conflicts and not force:
            raise CheckpointConflict(conflicts)
        root = workspace.resolve()
        for path in changed:
            target = root.joinpath(*safe_relative(path))
            # Never write through a symlinked directory created after the snapshot.
            for parent in list(target.relative_to(root).parents)[:-1][::-1]:
                if (root / parent).is_symlink():
                    raise ValueError(f"Refusing to restore through symlink: {parent}")
            if path not in old:
                if target.is_symlink() or target.is_file():
                    target.unlink()
                self.prune_empty_dirs(root, target.parent, old)
                continue
            mode, sha = old[path]
            if target.is_symlink() or target.is_dir():
                raise ValueError(f"Refusing to replace non-regular file: {path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            data = self.git(repo, "cat-file", "blob", sha)
            fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".restore-")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                permissions = target.stat().st_mode & 0o777 if target.exists() else 0o644
                if mode == "100755" and not permissions & 0o111:
                    permissions |= (permissions & 0o444) >> 2
                elif mode == "100644":
                    permissions &= ~0o111
                os.chmod(temporary, permissions)
                os.replace(temporary, target)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
        return dict(restored=changed, overwritten=conflicts)
