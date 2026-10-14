import os
import time
import unicodedata

import pytest

from app import workspace_watch
from app.checkpoints import Checkpoints
from app.workspace_watch import FSEventsWatcher

pytestmark = pytest.mark.skipif(workspace_watch.CS is None, reason="macOS FSEvents only")


@pytest.fixture
def dirs(tmp_path):
    work, marks = tmp_path / "work", tmp_path / "marks"
    work.mkdir()
    return work, marks


@pytest.fixture
def watchers():
    started = []
    yield started
    for watcher in started:
        watcher.close()


def start(watchers, work, marks, since=None, device=None):
    watcher = FSEventsWatcher.create(work, marks, since, device)
    assert watcher is not None
    watchers.append(watcher)
    return watcher


def primed(watchers, work, marks):
    watcher = start(watchers, work, marks)
    first = watcher.sync()
    # Without saved history, completeness needs a full scan first.
    assert first is not None and not first.complete
    watcher.commit(first, full=True)
    return watcher


def test_sync_reports_changed_paths_after_the_barrier(dirs, watchers):
    work, marks = dirs
    (work / "existing.txt").write_text("old")
    watcher = primed(watchers, work, marks)
    (work / "existing.txt").write_text("new")
    (work / "dir").mkdir()
    (work / "dir/created.txt").write_text("x")
    (work / "node_modules").mkdir()
    (work / "node_modules/pkg.js").write_text("x")
    nfd = unicodedata.normalize("NFD", "ガイド.txt")
    (work / nfd).write_text("x")
    sync = watcher.sync()
    assert sync.complete
    assert {"existing.txt", "dir/created.txt", "ガイド.txt"} <= sync.paths
    assert not any(p.startswith("node_modules") for p in sync.paths)
    assert not os.listdir(marks)
    watcher.commit(sync, full=False)
    assert watcher.sync().paths == frozenset()


def test_events_after_the_cursor_survive_commit(dirs, watchers):
    work, marks = dirs
    watcher = primed(watchers, work, marks)
    (work / "a.txt").write_text("1")
    sync = watcher.sync()
    (work / "a.txt").write_text("2")
    later = watcher.sync()
    watcher.commit(sync, full=False)
    assert "a.txt" in watcher.sync().paths
    watcher.commit(later, full=False)
    assert "a.txt" not in watcher.sync().paths


def test_git_directory_events_make_a_sync_not_quiet(dirs, watchers):
    work, marks = dirs
    (work / ".git").mkdir()
    watcher = primed(watchers, work, marks)
    assert watcher.sync().quiet
    # Index writes can change tracked files without events on those files.
    (work / ".git/index").write_text("x")
    sync = watcher.sync()
    assert not sync.quiet and not sync.paths
    watcher.commit(sync, full=False)
    assert watcher.sync().quiet


def test_history_replays_changes_made_while_stopped(dirs, watchers):
    work, marks = dirs
    (work / "a.txt").write_text("before")
    watcher = primed(watchers, work, marks)
    cursor, device = watcher.sync().cursor, watcher.device
    watcher.close()
    (work / "a.txt").write_text("changed while the backend was down")
    time.sleep(0.5)
    resumed = start(watchers, work, marks, cursor, device)
    sync = resumed.sync()
    assert sync.complete and "a.txt" in sync.paths
    # A different event database cannot be resumed.
    other = start(watchers, work, marks, cursor, "another-volume")
    assert not other.sync().complete


def test_checkpoints_detect_same_size_writes_from_events(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    path = work / "a.txt"
    path.write_text("before")
    old = time.time_ns() - 10_000_000_000
    os.utime(path, ns=(old, old))
    cp = Checkpoints(tmp_path / "data", 1024, FSEventsWatcher.create)
    try:
        before = cp.snapshot(work, "before")
        assert before["scan"] == "full"
        path.write_text("AFTER!")
        os.utime(path, ns=(old, old))
        after = cp.snapshot(work, "after")
        assert after["scan"] == "incremental"
        assert [f["path"] for f in cp.changes(work, before["commit"], after["commit"])] == ["a.txt"]
    finally:
        cp.close()
