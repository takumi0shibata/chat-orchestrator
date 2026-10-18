"""Workspace checkpoints stored in an app-managed Git repository.

Every regular file outside EXCLUDED_DIRS is selected; symlinks are never
followed. Contents are hashed with ``--no-filters`` and trees are built from a
private index.

Each snapshot saves the state of every selected file. With file events (see
workspace_watch), later snapshots stat and hash only files with events; Git
directories are still listed, so new and deleted files stay exact.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from bisect import bisect_left
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from app.workspace_files import scan_files
from app.workspace_watch import nfc

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
# Hashing reports progress and honours cancellation between batches.
HASH_BATCH = 2000
STATE_VERSION = 2
# Keeps the blobs of the saved state reachable when old runs are pruned.
STATE_REF = "refs/orchestrator/state"
EXCLUSIONS_MARKER = "orchestrator-exclusions-v1: "


class IncompleteCheckpoint(ValueError):
    pass


class CheckpointCancelled(Exception):
    pass


class CheckpointConflict(Exception):
    def __init__(self, paths):
        self.paths = paths
        super().__init__("Files changed after the run: " + ", ".join(paths[:10]))


def walk(root: Path, max_file_bytes: int, *, reuse=None, stale=frozenset()):
    """Apply checkpoint size limits to the shared workspace selection."""
    files, skipped = {}, {}
    for relative, state in scan_files(
        root, reuse=reuse, stale=stale
    ).items():
        if state[0] > max_file_bytes or "\n" in relative:
            skipped[relative] = state
        else:
            files[relative] = state
    return files, skipped


def stale_paths(known, events):
    """Known paths with an event on themselves or on an ancestor directory."""
    if not events:
        return set()
    index = sorted((nfc(path), path) for path in known)
    keys = [key for key, _ in index]
    result = set()
    for event in events:
        position = bisect_left(keys, event)
        if position < len(keys) and keys[position] == event:
            result.add(index[position][1])
        # Renamed or replaced directories report only the directory itself.
        position = bisect_left(keys, event + "/")
        while position < len(keys) and keys[position].startswith(event + "/"):
            result.add(index[position][1])
            position += 1
    return result


def index_checksum(path):
    """Git's trailing index checksum, tying a saved index to the saved state."""
    try:
        with open(path, "rb") as handle:
            handle.seek(-20, os.SEEK_END)
            return handle.read().hex()
    except OSError:
        return None


def same_file(entry, state):
    # Include identity and ctime: writes can preserve both size and mtime.
    return entry is not None and entry[:2] == list(state[:2]) and entry[3:6] == list(state[3:6])


def safe_relative(path: str):
    parts = PurePosixPath(path).parts
    if not parts or PurePosixPath(path).is_absolute() or ".." in parts:
        raise ValueError(f"Unsafe checkpoint path: {path}")
    return parts


class Checkpoints:
    def __init__(self, root: Path, max_file_bytes: int, watcher_factory=None):
        self.root = root
        self.max_file_bytes = max_file_bytes
        self.available = shutil.which("git") is not None
        self.watcher_factory = watcher_factory
        self.watchers = {}
        self.watch_lock = threading.Lock()
        # Snapshots and restores of one workspace (runs, Undo, warm-up) never overlap.
        self.locks = {}
        self.progress = {}
        self.cancelled = threading.Event()
        self.states = {}

    def locked(self, repo, progress=None):
        """Acquire the workspace's lock, reporting the holder's hashing progress."""
        with self.watch_lock:
            lock = self.locks.setdefault(repo, threading.RLock())
        while not lock.acquire(timeout=0.5):
            if progress and repo in self.progress:
                progress(*self.progress[repo])
        return lock

    @contextmanager
    def transaction(self, repo, progress=None):
        """Keep checkpoint objects reachable throughout a multi-step operation."""
        lock = self.locked(repo, progress)
        try:
            yield
        finally:
            lock.release()

    def watcher(self, workspace, repo, state):
        """Start watching lazily, resuming from the saved state's event cursor."""
        if not self.watcher_factory:
            return None
        with self.watch_lock:
            if repo not in self.watchers:
                self.watchers[repo] = self.watcher_factory(
                    workspace, repo / "watch-marks", state["cursor"], state["device"]
                )
            return self.watchers[repo]

    def close(self):
        self.cancelled.set()
        with self.watch_lock:
            for watcher in self.watchers.values():
                if watcher:
                    watcher.close()
            self.watchers.clear()

    def load_state(self, repo):
        path = repo / "snapshot-state.json"
        try:
            info = path.stat()
            key = (info.st_mtime_ns, info.st_size, info.st_ino)
            cached = self.states.get(repo)
            if cached and cached[0] == key:
                return cached[1]  # Callers never mutate the state.
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            state, key = None, None
        if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
            # Older releases kept a hash cache: {path: [size, mtime, ctime, dev, ino, sha]}.
            # A versioned cache came from a reverted optimization and is discarded.
            try:
                cache = json.loads((repo / "snapshot-cache.json").read_text())
            except (OSError, ValueError):
                cache = {}
            if not isinstance(cache, dict) or isinstance(cache.get("version"), int):
                cache = {}
            files = {
                path: [e[0], e[1], None, *e[2:6]]
                for path, e in cache.items() if isinstance(e, list) and len(e) == 6
            }
            state = dict(version=STATE_VERSION, device=None, cursor=None,
                         files=files, skipped={}, recent=[])
        if state["files"] and not self.has_ref(repo, STATE_REF):
            # Pruning may have removed blobs that no ref protected.
            shas = sorted({e[6] for e in state["files"].values()})
            output = self.git(
                repo, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                input="".join(sha + "\n" for sha in shas).encode(),
            ).decode().split("\n")
            present = {line.split()[0] for line in output if line.endswith(" blob")}
            state["files"] = {p: e for p, e in state["files"].items() if e[6] in present}
        if key:
            self.states[repo] = (key, state)
        return state

    def has_ref(self, repo, ref):
        try:
            return bool(self.git(repo, "rev-parse", "--verify", "--quiet", ref).strip())
        except RuntimeError:
            return False

    def save_state(self, repo, state, commit):
        self.git(repo, "update-ref", STATE_REF, commit)
        path = repo / "snapshot-state.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, separators=(",", ":")))
        os.replace(temporary, path)
        (repo / "snapshot-cache.json").unlink(missing_ok=True)

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

    def snapshot(self, workspace: Path, label: str, *, rehash=(), progress=None):
        """Return a commit for the workspace's current regular files.

        progress(done, total) is called while files are hashed, including while
        waiting for another snapshot of the same workspace (e.g. the warm-up).
        """
        repo = self.repo(workspace)
        lock = self.locked(repo, progress)
        try:
            return self._snapshot(workspace, repo, label, rehash, progress)
        finally:
            self.progress.pop(repo, None)
            lock.release()

    def snapshot_run(self, workspace, rid, name, *, progress=None):
        # GC must not run between creating a commit and publishing its run ref.
        with self.transaction(self.repo(workspace), progress):
            result = self.snapshot(workspace, f"{rid} {name}", progress=progress)
            self.set_ref(workspace, rid, name, result["commit"])
            return result

    def restore_run(self, workspace, rid, force=False, *, legacy_skipped=None):
        # Read refs, restore every file, and record completion under one lock.
        with self.transaction(self.repo(workspace)):
            before, after, reverted = (
                self.get_ref(workspace, rid, name)
                for name in ("before", "after", "reverted")
            )
            if not before or not after:
                raise KeyError("Checkpoint not found")
            if reverted:
                raise ValueError("This run has already been reverted")
            result = self.restore(workspace, before, after, force, legacy_skipped=legacy_skipped)
            self.set_ref(workspace, rid, "reverted", before)
            return result

    def commit_snapshot(self, repo, tree, label, skipped):
        # Commit metadata is immutable, survives restarts and is pruned together
        # with its snapshot. Use stdin so large exclusion lists fit safely.
        metadata = EXCLUSIONS_MARKER + json.dumps(sorted(skipped), ensure_ascii=True)
        return self.git(repo, "commit-tree", tree, input=f"{label}\n\n{metadata}\n".encode()).decode().strip()

    def exclusions(self, workspace, before, after, *, legacy_skipped=None):
        skipped = set()
        for commit in (before, after):
            message = self.git(self.repo(workspace), "show", "-s", "--format=%B", commit).decode()
            metadata = next((line[len(EXCLUSIONS_MARKER):] for line in message.splitlines()
                             if line.startswith(EXCLUSIONS_MARKER)), None)
            if metadata is None:
                if legacy_skipped is None:
                    raise IncompleteCheckpoint("Undo is unavailable because this older checkpoint has incomplete exclusion records. Files have not been changed.")
                skipped.update(legacy_skipped)
                continue
            try:
                paths = json.loads(metadata)
                if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                    raise ValueError("Invalid exclusions")
                for path in paths:
                    safe_relative(path)
            except (ValueError, TypeError):
                raise IncompleteCheckpoint("Undo is unavailable because checkpoint exclusion records are invalid. Files have not been changed.") from None
            skipped.update(paths)
        return skipped

    @staticmethod
    def covered(path, skipped):
        # A size-excluded file may have become a directory (or vice versa).
        return not any(path == p or path.startswith(p + "/") or p.startswith(path + "/") for p in skipped)

    def _snapshot(self, workspace, repo, label, rehash, progress):
        state = self.load_state(repo)
        # Undo's conflict check re-hashes paths but never updates the saved state.
        persist = not rehash
        watcher = self.watcher(workspace, repo, state) if persist else None
        sync = watcher.sync() if watcher else None
        incremental = bool(
            sync and sync.complete and state["cursor"] is not None
            and state["device"] == watcher.device and watcher.base <= state["cursor"]
        )
        if (
            incremental and sync.quiet and state.get("tree")
            and state.get("max_file_bytes") == self.max_file_bytes
        ):
            # Nothing could have changed: reuse the saved tree without listing files.
            # Recently written files need no re-hash here: any write after the
            # saved snapshot's barrier is a later event, so the sync is not quiet.
            commit = self.commit_snapshot(repo, state["tree"], label, state["skipped"])
            watcher.commit(sync, full=False)
            known = state["files"] | state["skipped"]
            return dict(
                commit=commit, files=len(state["files"]), skipped=sorted(state["skipped"]),
                scanned={p: tuple(e[:2]) for p, e in known.items()}, scan="unchanged",
            )
        reuse, stale = None, frozenset()
        if incremental:
            known = state["files"] | state["skipped"]
            reuse = {path: tuple(entry[:6]) for path, entry in known.items()}
            # A file modified again within the same mtime tick must be re-hashed later.
            stale = stale_paths(known, sync.paths) | set(state["recent"])
        files, skipped = walk(
            workspace, self.max_file_bytes, reuse=reuse, stale=stale
        )
        previous = state["files"]
        rehash = set(rehash) | set(state["recent"])
        pending = [
            p for p in files if p in rehash or not same_file(previous.get(p), files[p])
        ]
        hashed = {}
        for start in range(0, len(pending), HASH_BATCH):
            if self.cancelled.is_set():
                raise CheckpointCancelled("Checkpoint cancelled")
            batch = pending[start:start + HASH_BATCH]
            output = self.git(
                repo, "hash-object", "-w", "--no-filters", "--stdin-paths",
                input=b"".join(os.fsencode(workspace / p) + b"\n" for p in batch),
            ).decode().split()
            hashed.update(zip(batch, output, strict=True))
            if len(pending) > HASH_BATCH:
                self.progress[repo] = (len(hashed), len(pending))
                if progress:
                    progress(len(hashed), len(pending))
        recent_ns = time.time_ns() - 2_000_000_000
        saved, recent = {}, []
        for path, file in files.items():
            saved[path] = [*file, hashed.get(path) or previous[path][6]]
            if file[1] >= recent_ns:
                recent.append(path)
        saved_index = repo / "snapshot-index"
        # The saved index matches the saved state, so only changed entries are
        # updated and write-tree reuses cached trees of unchanged directories.
        base = state.get("index") is not None and index_checksum(saved_index) == state["index"]
        if base:
            removed = [
                b"0 " + b"0" * 40 + b"\t" + os.fsencode(p) + b"\0"
                for p in previous.keys() - saved.keys()
            ]
            changed = sorted(
                p for p, e in saved.items()
                if previous.get(p) is None or previous[p][2] != e[2] or previous[p][6] != e[6]
            )
        else:
            removed, changed = [], sorted(saved)
        entries = removed + [
            f"{saved[p][2]} {saved[p][6]}\t".encode() + os.fsencode(p) + b"\0" for p in changed
        ]
        with tempfile.TemporaryDirectory(dir=repo) as scratch:
            scratch_index = Path(scratch) / "index"
            if base:
                shutil.copyfile(saved_index, scratch_index)
            index = {"GIT_INDEX_FILE": str(scratch_index)}
            if entries:
                self.git(
                    repo, "update-index", "-z", "--replace", "--index-info",
                    input=b"".join(entries), env=index,
                )
            tree = self.git(repo, "write-tree", env=index).decode().strip()
            if persist and scratch_index.exists():
                os.replace(scratch_index, saved_index)
        commit = self.commit_snapshot(repo, tree, label, skipped)
        if persist:
            self.save_state(repo, dict(
                version=STATE_VERSION,
                device=watcher.device if sync else None,
                cursor=sync.cursor if sync else None,
                index=index_checksum(saved_index) if entries or base else None,
                tree=tree, max_file_bytes=self.max_file_bytes, files=saved, skipped={p: list(s) for p, s in skipped.items()}, recent=recent,
            ), commit)
            if sync:
                watcher.commit(sync, full=not incremental)
        # scanned matches file_snapshot, so callers need not scan the workspace again.
        scanned = {p: info[:2] for p, info in (files | skipped).items()}
        return dict(
            commit=commit, files=len(files), skipped=sorted(skipped), scanned=scanned,
            scan="incremental" if incremental else "full",
        )

    def repos(self):
        return sorted(self.root.glob("*.git")) if self.root.exists() else []

    def run_ids(self, repo):
        output = self.git(repo, "for-each-ref", "--format=%(refname)", "refs/checkpoints/")
        return {line.split("/")[2] for line in output.decode().splitlines() if line.count("/") >= 3}

    def delete_runs(self, repo, rids):
        """Drop every checkpoint ref of these runs, then discard unreachable objects."""
        with self.transaction(repo):
            return self._delete_runs(repo, rids)

    def _delete_runs(self, repo, rids):
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

    def changes(self, workspace, before, after, *, skipped=None):
        if skipped is None:
            skipped = self.exclusions(workspace, before, after)
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
            if not self.covered(path, skipped):
                continue
            added, removed = counts.get(path, ("0", "0"))
            files.append(dict(
                path=path,
                status={"A": "added", "D": "deleted"}.get(code.decode()[0], "modified"),
                added=None if added == "-" else int(added),
                removed=None if removed == "-" else int(removed),
                binary=added == "-",
            ))
        return files

    def patch(self, workspace, before, after, path, *, legacy_skipped=None):
        safe_relative(path)
        if not self.covered(path, self.exclusions(workspace, before, after, legacy_skipped=legacy_skipped)):
            raise ValueError("This file was not fully saved in both checkpoints and cannot be undone.")
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

    def restore(self, workspace: Path, before, after, force=False, *, legacy_skipped=None):
        """Return files changed between before and after to their before state."""
        repo = self.repo(workspace)
        lock = self.locked(repo)
        try:
            return self._restore(workspace, repo, before, after, force, legacy_skipped)
        finally:
            lock.release()

    def _restore(self, workspace, repo, before, after, force, legacy_skipped):
        skipped = self.exclusions(workspace, before, after, legacy_skipped=legacy_skipped)
        old, new = (self.tree(repo, c) for c in (before, after))
        changed = sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p) and self.covered(p, skipped))
        current = self.snapshot(workspace, "pre-restore", rehash=changed)["commit"]
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
