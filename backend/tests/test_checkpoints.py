import subprocess
import json
import os
import time

import pytest

from app import checkpoints as checkpoint_module
from app.checkpoints import (
    STATE_REF, CheckpointCancelled, CheckpointConflict, Checkpoints, stale_paths,
)
from app.workspace_watch import Sync


@pytest.fixture
def setup(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    return Checkpoints(tmp_path / "data", max_file_bytes=1024), work


def test_snapshot_includes_gitignored_files_without_applying_filters(setup):
    cp, work = setup
    subprocess.run(["git", "init", "-q", str(work / "nested")], check=True)
    (work / ".gitignore").write_text("ignored/\n")
    (work / ".gitattributes").write_text("*.bin filter=lfs -text\n")
    (work / "ignored").mkdir()
    (work / "ignored/out.txt").write_text("v1\n")
    (work / "nested/inner.txt").write_text("v1\n")
    (work / "data.bin").write_bytes(b"raw\r\n")
    (work / "keep.txt").write_text("same\n")
    (work / "big.dat").write_bytes(b"x" * 2048)
    (work / "node_modules").mkdir()
    (work / "node_modules/pkg.js").write_text("v1\n")
    before = cp.snapshot(work, "before")
    assert before["skipped"] == ["big.dat"]

    (work / "ignored/out.txt").write_text("v2\n")
    (work / "nested/inner.txt").write_text("v2\n")
    (work / "data.bin").write_bytes(b"changed")
    (work / "new dir").mkdir()
    (work / "new dir/created [1].txt").write_text("new\n")
    (work / "keep.txt").unlink()
    after = cp.snapshot(work, "after")

    changes = {f["path"]: f for f in cp.changes(work, before["commit"], after["commit"])}
    assert {p: f["status"] for p, f in changes.items()} == {
        "data.bin": "modified", "keep.txt": "deleted", "ignored/out.txt": "modified",
        "nested/inner.txt": "modified", "new dir/created [1].txt": "added",
    }
    assert changes["nested/inner.txt"]["added"] == 1
    patch, truncated = cp.patch(work, before["commit"], after["commit"], "nested/inner.txt")
    assert "-v1\n+v2" in patch and not truncated

    result = cp.restore(work, before["commit"], after["commit"])
    assert result["overwritten"] == []
    assert (work / "ignored/out.txt").read_text() == "v1\n"
    assert (work / "nested/inner.txt").read_text() == "v1\n"
    assert (work / "data.bin").read_bytes() == b"raw\r\n"
    assert (work / "keep.txt").read_text() == "same\n"
    assert not (work / "new dir").exists()
    assert (work / "big.dat").exists()


def test_restore_detects_later_edits(setup):
    cp, work = setup
    (work / "a.txt").write_text("v1\n")
    before = cp.snapshot(work, "before")["commit"]
    (work / "a.txt").write_text("v2\n")
    after = cp.snapshot(work, "after")["commit"]
    (work / "a.txt").write_text("user edit\n")
    with pytest.raises(CheckpointConflict) as error:
        cp.restore(work, before, after)
    assert error.value.paths == ["a.txt"]
    assert (work / "a.txt").read_text() == "user edit\n"
    assert cp.restore(work, before, after, force=True)["overwritten"] == ["a.txt"]
    assert (work / "a.txt").read_text() == "v1\n"


def test_restore_keeps_permissions_and_refs(setup):
    cp, work = setup
    script = work / "run.sh"
    script.write_text("v1\n")
    script.chmod(0o750)
    before = cp.snapshot(work, "before")["commit"]
    script.write_text("v2\n")
    after = cp.snapshot(work, "after")["commit"]
    cp.set_ref(work, "run1", "before", before)
    assert cp.get_ref(work, "run1", "before") == before
    assert cp.get_ref(work, "run1", "after") is None
    cp.restore(work, before, after)
    assert script.stat().st_mode & 0o777 == 0o750


def test_restore_refuses_symlinked_parent(setup, tmp_path):
    cp, work = setup
    (work / "dir").mkdir()
    (work / "dir/a.txt").write_text("v1\n")
    before = cp.snapshot(work, "before")["commit"]
    (work / "dir/a.txt").write_text("v2\n")
    after = cp.snapshot(work, "after")["commit"]
    (work / "dir/a.txt").unlink()
    (work / "dir").rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (work / "dir").symlink_to(outside)
    with pytest.raises((ValueError, CheckpointConflict)):
        cp.restore(work, before, after, force=True)
    assert not (outside / "a.txt").exists()


def test_gitignored_and_tracked_files_both_have_diffs_and_undo(setup):
    cp, work = setup
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    (work / ".gitignore").write_text("*.txt\n")
    (work / "tracked.txt").write_text("before")
    (work / "ignored.txt").write_text("before")
    subprocess.run(["git", "-C", str(work), "add", "-f", "tracked.txt"], check=True)
    before = cp.snapshot(work, "before")["commit"]
    (work / "tracked.txt").write_text("after")
    (work / "ignored.txt").write_text("after")
    after = cp.snapshot(work, "after")["commit"]
    assert [f["path"] for f in cp.changes(work, before, after)] == ["ignored.txt", "tracked.txt"]
    cp.restore(work, before, after)
    assert (work / "tracked.txt").read_text() == "before"
    assert (work / "ignored.txt").read_text() == "before"


@pytest.mark.parametrize("rules", [("logs/\n", ""), ("", "logs/\n")])
def test_editing_gitignore_never_adds_or_deletes_existing_files(setup, rules):
    cp, work = setup
    (work / ".gitignore").write_text(rules[0])
    (work / "logs").mkdir()
    (work / "logs/run.log").write_text("existed before the run")
    before = cp.snapshot(work, "before")["commit"]
    (work / ".gitignore").write_text(rules[1])
    after = cp.snapshot(work, "after")["commit"]
    assert [f["path"] for f in cp.changes(work, before, after)] == [".gitignore"]
    cp.restore(work, before, after)
    assert (work / ".gitignore").read_text() == rules[0]
    assert (work / "logs/run.log").read_text() == "existed before the run"


def test_versioned_cache_is_rebuilt_without_deleting_old_refs(setup):
    cp, work = setup
    (work / "version").write_text("one")
    before = cp.snapshot(work, "before")["commit"]
    cp.set_ref(work, "old", "before", before)
    (cp.repo(work) / "snapshot-state.json").unlink()
    (cp.repo(work) / "snapshot-cache.json").write_text('{"version":2,"files":{},"tree":"unused"}')
    after = cp.snapshot(work, "after")["commit"]
    assert cp.changes(work, before, after) == []
    assert cp.get_ref(work, "old", "before") == before


def test_snapshot_detects_same_size_writes_with_preserved_mtime(setup):
    cp, work = setup
    path = work / "a.txt"
    path.write_text("before")
    timestamp = time.time_ns() - 10_000_000_000
    os.utime(path, ns=(timestamp, timestamp))
    before = cp.snapshot(work, "before")["commit"]
    path.write_text("AFTER!")
    os.utime(path, ns=(timestamp, timestamp))
    after = cp.snapshot(work, "after")["commit"]
    assert [f["path"] for f in cp.changes(work, before, after)] == ["a.txt"]


def test_undo_rehashes_changed_files_even_when_cache_claims_no_change(setup):
    cp, work = setup
    path = work / "a.txt"
    path.write_text("before")
    before = cp.snapshot(work, "before")["commit"]
    path.write_text("AFTER!")
    timestamp = time.time_ns() - 10_000_000_000
    os.utime(path, ns=(timestamp, timestamp))
    after = cp.snapshot(work, "after")["commit"]
    path.write_text("USER!!")
    os.utime(path, ns=(timestamp, timestamp))
    # Simulate stale metadata from coarse timestamps or an old cache. Undo must
    # verify the actual bytes regardless of what the cache says.
    info = path.stat()
    sha = cp.tree(cp.repo(work), after)["a.txt"][1]
    state_path = cp.repo(work) / "snapshot-state.json"
    state = json.loads(state_path.read_text())
    state["files"]["a.txt"] = [
        info.st_size, info.st_mtime_ns, "100644", info.st_ctime_ns, info.st_dev, info.st_ino, sha,
    ]
    state_path.write_text(json.dumps(state))
    with pytest.raises(CheckpointConflict) as error:
        cp.restore(work, before, after)
    assert error.value.paths == ["a.txt"]
    assert path.read_text() == "USER!!"


def test_old_unversioned_cache_is_rehashed_without_changing_refs(setup):
    cp, work = setup
    path = work / "a.txt"
    path.write_text("before")
    before = cp.snapshot(work, "before")["commit"]
    cp.set_ref(work, "old", "before", before)
    info = path.stat()
    sha = cp.tree(cp.repo(work), before)["a.txt"][1]
    (cp.repo(work) / "snapshot-state.json").unlink()
    (cp.repo(work) / "snapshot-cache.json").write_text(json.dumps({
        "a.txt": [info.st_size, info.st_mtime_ns, sha],
    }))
    path.write_text("AFTER!")
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    after = cp.snapshot(work, "after")["commit"]
    assert cp.changes(work, before, after)
    assert cp.get_ref(work, "old", "before") == before


class FakeWatcher:
    """Reports exactly the events a test declares, like FSEventsWatcher."""

    device = "volume"

    def __init__(self, since=None, device=None):
        resumed = since is not None and device == self.device
        self.base = since if resumed else 100
        self.cursor, self.events, self.complete = self.base, set(), resumed

    def event(self, *paths):
        self.cursor += 1
        self.events.update(paths)

    def sync(self):
        return Sync(
            cursor=self.cursor, paths=frozenset(self.events), complete=self.complete, reset=0,
        )

    def commit(self, sync, *, full):
        self.events -= sync.paths
        self.complete = self.complete or full

    def close(self):
        pass


@pytest.fixture
def watched(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    started = []

    def factory(root, marks, since, device):
        started.append((since, device))
        return FakeWatcher(since, device)

    cp = Checkpoints(tmp_path / "data", max_file_bytes=1024, watcher_factory=factory)
    return cp, work, started


def write_old(path, text):
    """Write a file whose mtime is outside the same-tick re-hash window."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    old = time.time_ns() - 10_000_000_000
    os.utime(path, ns=(old, old))


def statuses(cp, work, before, after):
    return {f["path"]: f["status"] for f in cp.changes(work, before["commit"], after["commit"])}


def test_incremental_snapshot_stats_only_files_with_events(watched):
    cp, work, _ = watched
    for i in range(200):
        write_old(work / f"many/{i}.txt", str(i))
    for name in ("a.txt", "b.txt", "gone.txt"):
        write_old(work / name, "before")
    before = cp.snapshot(work, "before")
    assert before["scan"] == "full"
    watcher = cp.watchers[cp.repo(work)]

    write_old(work / "a.txt", "AFTER!")
    watcher.event("a.txt")
    # Without an event, unchanged state is trusted (the watcher reports all writes).
    write_old(work / "b.txt", "AFTER!")
    # Creation and deletion come from Git's listing, events or not.
    write_old(work / "new.txt", "new")
    (work / "gone.txt").unlink()
    after = cp.snapshot(work, "after")
    assert after["scan"] == "incremental"
    assert statuses(cp, work, before, after) == {
        "a.txt": "modified", "new.txt": "added", "gone.txt": "deleted",
    }
    # b.txt was neither stat'ed nor hashed.
    assert after["scanned"]["b.txt"] == before["scanned"]["b.txt"]
    assert not watcher.events


def test_incremental_snapshot_ignores_gitignore_and_tracking_changes(watched):
    cp, work, _ = watched
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    write_old(work / ".gitignore", "logs/\n")
    write_old(work / "gen/out.txt", "x")
    write_old(work / "logs/run.log", "x")
    before = cp.snapshot(work, "before")
    assert set(before["scanned"]) == {".gitignore", "gen/out.txt", "logs/run.log"}
    write_old(work / ".gitignore", "gen/\n")
    cp.watchers[cp.repo(work)].event(".gitignore")
    subprocess.run(["git", "-C", str(work), "add", "-f", "gen/out.txt"], check=True)
    after = cp.snapshot(work, "after")
    assert after["scan"] == "incremental"
    assert statuses(cp, work, before, after) == {".gitignore": "modified"}


def test_directory_events_recheck_known_files_below_them(watched):
    cp, work, _ = watched
    write_old(work / "dir/a.txt", "one")
    write_old(work / "other/a.txt", "two")
    before = cp.snapshot(work, "before")
    (work / "dir").rename(work / "old")
    (work / "other").rename(work / "dir")
    # Renaming a directory reports the directory, not each file inside it.
    cp.watchers[cp.repo(work)].event("dir", "other", "old")
    after = cp.snapshot(work, "after")
    assert after["scan"] == "incremental"
    assert statuses(cp, work, before, after) == {
        "dir/a.txt": "modified", "other/a.txt": "deleted", "old/a.txt": "added",
    }


def test_lost_events_fall_back_to_a_full_scan(watched):
    cp, work, _ = watched
    write_old(work / "a.txt", "before")
    before = cp.snapshot(work, "before")
    watcher = cp.watchers[cp.repo(work)]
    watcher.complete = False
    write_old(work / "a.txt", "AFTER!")
    after = cp.snapshot(work, "after")
    assert after["scan"] == "full"
    assert statuses(cp, work, before, after) == {"a.txt": "modified"}
    assert cp.snapshot(work, "again")["scan"] == "unchanged"


def test_watcher_resumes_from_the_saved_cursor(watched, tmp_path):
    cp, work, started = watched
    write_old(work / "a.txt", "x")
    cp.snapshot(work, "first")
    cp.watchers[cp.repo(work)].event("a.txt")
    cp.snapshot(work, "second")
    assert started == [(None, None)]
    restarted = []
    cp2 = Checkpoints(
        tmp_path / "data", max_file_bytes=1024,
        watcher_factory=lambda root, marks, since, device: restarted.append((since, device))
        or FakeWatcher(since, device),
    )
    assert cp2.snapshot(work, "third")["scan"] == "unchanged"
    assert restarted == [(101, "volume")]


def test_undo_snapshots_never_replace_the_saved_state(watched):
    cp, work, _ = watched
    write_old(work / "a.txt", "before")
    before = cp.snapshot(work, "before")
    write_old(work / "a.txt", "AFTER!")
    cp.watchers[cp.repo(work)].event("a.txt")
    after = cp.snapshot(work, "after")
    state = (cp.repo(work) / "snapshot-state.json").read_text()
    cp.restore(work, before["commit"], after["commit"])
    assert (work / "a.txt").read_text() == "before"
    assert (cp.repo(work) / "snapshot-state.json").read_text() == state


def test_stale_paths_match_unicode_forms_and_descendants():
    import unicodedata

    nfd = unicodedata.normalize("NFD", "ガイド/資料.txt")
    known = {nfd, "dir/a.txt", "dir/sub/b.txt", "dirt.txt", "x.txt"}
    events = {unicodedata.normalize("NFC", "ガイド"), "dir"}
    assert stale_paths(known, events) == {nfd, "dir/a.txt", "dir/sub/b.txt"}


def test_pruning_runs_keeps_blobs_of_the_saved_state(setup):
    cp, work = setup
    write_old(work / "a.txt", "content")
    commit = cp.snapshot(work, "run")["commit"]
    cp.set_ref(work, "r1", "before", commit)
    repo = cp.repo(work)
    assert cp.delete_runs(repo, {"r1"}) == 1
    # The saved state still references its blobs, so no file needs re-hashing.
    assert cp.snapshot(work, "next")["files"] == 1
    # Without the state ref (older releases), missing blobs are re-hashed.
    cp.git(repo, "update-ref", "-d", STATE_REF)
    cp.git(repo, "gc", "--prune=now", "--quiet")
    commit = cp.snapshot(work, "after prune")["commit"]
    assert cp.git(repo, "cat-file", "-p", cp.tree(repo, commit)["a.txt"][1]) == b"content"


def test_saved_index_deltas_build_the_same_tree_as_a_full_rebuild(watched, tmp_path):
    cp, work, _ = watched
    write_old(work / "x", "file that becomes a directory")
    write_old(work / "dir/y.txt", "directory that becomes a file")
    write_old(work / "keep/a.txt", "a")
    write_old(work / "tool.sh", "#!/bin/sh\n")
    cp.snapshot(work, "first")
    watcher = cp.watchers[cp.repo(work)]
    (work / "x").unlink()
    write_old(work / "x/inner.txt", "now a directory")
    (work / "dir/y.txt").unlink()
    (work / "dir").rmdir()
    write_old(work / "dir", "now a file")
    write_old(work / "keep/b.txt", "b")
    (work / "tool.sh").chmod(0o755)
    watcher.event("x", "dir", "tool.sh")
    result = cp.snapshot(work, "second")
    assert result["scan"] == "incremental"
    fresh = Checkpoints(tmp_path / "fresh", max_file_bytes=1024).snapshot(work, "fresh")
    repo = cp.repo(work)
    tree = cp.git(repo, "rev-parse", result["commit"] + "^{tree}")
    fresh_repo = Checkpoints(tmp_path / "fresh", 1024).repo(work)
    assert tree == cp.git(fresh_repo, "rev-parse", fresh["commit"] + "^{tree}")
    assert cp.tree(repo, result["commit"])["tool.sh"][0] == "100755"


def test_a_mismatched_saved_index_is_rebuilt(watched):
    cp, work, _ = watched
    write_old(work / "a.txt", "a")
    first = cp.snapshot(work, "first")
    repo = cp.repo(work)
    # Simulate a crash between saving the index and saving the state.
    write_old(work / "b.txt", "b")
    other = Checkpoints(repo.parent.parent / "other", 1024)
    other_repo = other.repo(work)
    other.snapshot(work, "other")
    (repo / "snapshot-index").write_bytes((other_repo / "snapshot-index").read_bytes())
    (work / "b.txt").unlink()
    second = cp.snapshot(work, "second")
    assert cp.tree(repo, second["commit"]) == cp.tree(repo, first["commit"])


def test_quiet_workspace_reuses_the_saved_tree_without_listing(watched, monkeypatch):
    cp, work, _ = watched
    write_old(work / "a.txt", "a")
    first = cp.snapshot(work, "first")
    monkeypatch.setattr(checkpoint_module, "scan_files", lambda *a, **k: pytest.fail("listed"))
    quiet = cp.snapshot(work, "quiet")
    assert quiet["scan"] == "unchanged"
    assert quiet["scanned"] == first["scanned"] and quiet["files"] == 1
    assert cp.tree(cp.repo(work), quiet["commit"]) == cp.tree(cp.repo(work), first["commit"])
    monkeypatch.undo()
    watcher = cp.watchers[cp.repo(work)]
    write_old(work / "b.txt", "b")
    watcher.event("b.txt")
    assert cp.snapshot(work, "event")["scan"] == "incremental"


def test_quiet_snapshot_requires_the_same_size_limit(watched, tmp_path):
    cp, work, _ = watched
    write_old(work / "fresh.txt", "a file over four bytes")
    cp.snapshot(work, "first")
    assert cp.snapshot(work, "quiet")["scan"] == "unchanged"
    smaller = Checkpoints(
        tmp_path / "data", max_file_bytes=4,
        watcher_factory=lambda root, marks, since, device: FakeWatcher(since, device),
    )
    result = smaller.snapshot(work, "smaller limit")
    assert result["scan"] == "incremental" and result["skipped"] == ["fresh.txt"]


def test_waiting_snapshot_reports_the_holder_progress(watched):
    import threading

    cp, work, _ = watched
    write_old(work / "a.txt", "a")
    repo = cp.repo(work)
    holder = cp.locked(repo)
    cp.progress[repo] = (2000, 50000)
    reported, done = [], threading.Event()

    def run():
        cp.snapshot(work, "waiting", progress=lambda *p: reported.append(p))
        done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        time.sleep(1.2)
        assert not done.is_set() and reported and reported[0] == (2000, 50000)
    finally:
        del cp.progress[repo]
        holder.release()
    thread.join(5)
    assert done.is_set()


def test_hashing_reports_progress_and_stops_when_closed(setup, monkeypatch):
    cp, work = setup
    monkeypatch.setattr(checkpoint_module, "HASH_BATCH", 2)
    for i in range(5):
        write_old(work / f"{i}.txt", str(i))
    reported = []
    cp.snapshot(work, "first", progress=lambda *p: reported.append(p))
    assert reported == [(2, 5), (4, 5), (5, 5)]
    state = (cp.repo(work) / "snapshot-state.json").read_text()
    for i in range(4):
        write_old(work / f"new{i}.txt", "new")

    def close_after_first_batch(*progress):
        cp.close()

    with pytest.raises(CheckpointCancelled):
        cp.snapshot(work, "cancelled", progress=close_after_first_batch)
    assert (cp.repo(work) / "snapshot-state.json").read_text() == state
