"""Workspace checkpoints stored in an app-managed Git repository.

The user's own repository, ignore rules, attributes and filters are never used:
files are hashed with ``--no-filters`` and trees are built from a private index.
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

    def scan(self, workspace: Path):
        # A workspace containing the app must never back up its own backups.
        return scan_files(workspace, excluded=(self.root,))

    def snapshot(self, workspace: Path, label: str, *, files=None):
        """Return a commit for the workspace's current regular files."""
        repo = self.repo(workspace)
        if files is None:
            files = self.scan(workspace)
        skipped = sorted(
            p for p, state in files.items()
            if state.size > self.max_file_bytes or "\n" in p
        )
        files = {p: state for p, state in files.items()
                 if state.size <= self.max_file_bytes and "\n" not in p}
        cache_path = repo / "snapshot-cache.json"
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            cache = {}
        if not isinstance(cache, dict) or cache.get("version") != 2:
            cache = {}
        previous = cache.get("files", {})
        racy = set(cache.get("racy", ()))
        # A file modified again within the same mtime tick must be re-hashed later.
        recent = time.time_ns() - 2_000_000_000
        pending = [
            p for p, state in files.items()
            if previous.get(p, [])[:-1] != list(state) or p in racy
        ]
        hashed = {}
        if pending:
            # Prefer latency to compression on the run's critical path. Git still
            # deduplicates blobs; explicit cleanup can pack/compress them later.
            output = self.git(
                repo, "-c", "core.looseCompression=0",
                "hash-object", "-w", "--no-filters", "--stdin-paths",
                # --stdin-paths treats a leading quote as a C-quoted path.
                input=b"".join(os.fsencode(json.dumps(str((workspace / p).absolute()), ensure_ascii=False))
                               + b"\n" for p in pending),
            ).decode().split()
            hashed = dict(zip(pending, output, strict=True))
        entries, next_cache = [], {}
        removed = previous.keys() - files.keys()
        for path in sorted(removed):
            entries.append(b"0 " + b"0" * len(previous[path][-1]) + b"\t" + os.fsencode(path) + b"\0")
        for path, state in sorted(files.items()):
            sha = hashed.get(path) or previous[path][-1]
            next_cache[path] = [*state, sha]
            old = previous.get(path)
            if old is None or (old[-2], old[-1]) != (state.mode, sha):
                entries.append(f"{state.mode} {sha}\t".encode() + os.fsencode(path) + b"\0")
        tree = cache.get("tree")
        if entries or tree is None:
            with tempfile.TemporaryDirectory(dir=repo) as scratch:
                index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
                if tree:
                    self.git(repo, "read-tree", tree, env=index)
                if entries:
                    self.git(
                        repo, "update-index", "-z", "--index-info",
                        input=b"".join(entries), env=index,
                    )
                tree = self.git(repo, "write-tree", env=index).decode().strip()
        commit = self.git(repo, "commit-tree", tree, "-m", label).decode().strip()
        state = dict(version=2, tree=tree, files=next_cache,
                     racy=[p for p, s in files.items() if s.mtime_ns >= recent])
        if state != cache:
            # A failed write must not leave a cache describing half an index update.
            with tempfile.TemporaryDirectory(dir=repo) as scratch:
                temporary = Path(scratch) / "cache.json"
                temporary.write_text(json.dumps(state, separators=(",", ":")))
                os.replace(temporary, cache_path)
        return dict(commit=commit, files=len(files), skipped=skipped,
                    hashed_files=len(pending))

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
        # The cached tree may become unreachable when refs are pruned.
        (repo / "snapshot-cache.json").unlink(missing_ok=True)
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
        current = self.snapshot(workspace, "pre-restore")["commit"]
        old, new, now = (self.tree(repo, c) for c in (before, after, current))
        changed = sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))
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
