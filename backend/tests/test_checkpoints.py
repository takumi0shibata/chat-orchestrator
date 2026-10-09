import json
import os
import subprocess

import pytest

from app.checkpoints import CheckpointConflict, Checkpoints


@pytest.fixture
def setup(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    return Checkpoints(tmp_path / "data", max_file_bytes=1024), work


def test_snapshot_ignores_user_git_rules_and_restores(setup):
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
        "data.bin": "modified", "ignored/out.txt": "modified", "keep.txt": "deleted",
        "nested/inner.txt": "modified", "new dir/created [1].txt": "added",
    }
    assert changes["ignored/out.txt"]["added"] == 1
    patch, truncated = cp.patch(work, before["commit"], after["commit"], "ignored/out.txt")
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


def test_unchanged_snapshot_reuses_blobs_and_tree(setup, monkeypatch):
    cp, work = setup
    (work / "a.txt").write_text("unchanged\n")
    os.utime(work / "a.txt", (1, 1))
    before = cp.snapshot(work, "before")
    cache = cp.repo(work) / "snapshot-cache.json"
    cache_mtime = cache.stat().st_mtime_ns
    calls = []
    git = cp.git

    def record(repo, *args, **kwargs):
        calls.append(args)
        return git(repo, *args, **kwargs)

    monkeypatch.setattr(cp, "git", record)
    after = cp.snapshot(work, "after")
    assert after["hashed_files"] == 0
    assert [args[0] for args in calls] == ["commit-tree"]
    assert cache.stat().st_mtime_ns == cache_mtime
    assert cp.changes(work, before["commit"], after["commit"]) == []


def test_incremental_tree_matches_fresh_snapshot_and_undo(setup, tmp_path):
    cp, work = setup
    for path, content in {"a.txt": "old\n", "remove": "bye", "keep": "same"}.items():
        (work / path).write_text(content)
        os.utime(work / path, (1, 1))
    before = cp.snapshot(work, "before")
    (work / "a.txt").write_text("new\n")
    (work / "a.txt").chmod(0o755)
    (work / "remove").unlink()
    (work / "remove").mkdir()
    (work / "remove/new.bin").write_bytes(b"\0new")
    after = cp.snapshot(work, "after")
    assert after["hashed_files"] == 2
    fresh = Checkpoints(tmp_path / "fresh", 1024)
    fresh_commit = fresh.snapshot(work, "fresh")["commit"]
    assert cp.tree(cp.repo(work), after["commit"]) == fresh.tree(fresh.repo(work), fresh_commit)
    assert {f["path"] for f in cp.changes(work, before["commit"], after["commit"])} == {
        "a.txt", "remove", "remove/new.bin",
    }
    # Undo a normal content/mode change without the pre-existing directory/file
    # restore restriction.
    stable = cp.snapshot(work, "stable")["commit"]
    (work / "a.txt").write_text("last\n")
    latest = cp.snapshot(work, "latest")["commit"]
    cp.restore(work, stable, latest)
    assert (work / "a.txt").read_text() == "new\n"
    assert (work / "a.txt").stat().st_mode & 0o111


def test_cache_detects_same_size_edit_with_preserved_mtime(setup):
    cp, work = setup
    path = work / "a.txt"
    path.write_text("one")
    os.utime(path, (1, 1))
    before = cp.snapshot(work, "before")["commit"]
    path.write_text("two")
    os.utime(path, (1, 1))
    after = cp.snapshot(work, "after")
    assert after["hashed_files"] == 1
    assert [f["path"] for f in cp.changes(work, before, after["commit"])] == ["a.txt"]


@pytest.mark.parametrize("cache_text", ["{broken", '{"a.txt":[3,1,"old-format"]}'])
def test_old_or_invalid_cache_rebuilds_without_losing_checkpoints(setup, cache_text):
    cp, work = setup
    (work / "a.txt").write_text("one")
    before = cp.snapshot(work, "before")["commit"]
    cp.set_ref(work, "old-run", "before", before)
    (cp.repo(work) / "snapshot-cache.json").write_text(cache_text)
    after = cp.snapshot(work, "after")
    assert after["hashed_files"] == 1
    assert cp.get_ref(work, "old-run", "before") == before
    assert cp.changes(work, before, after["commit"]) == []


def test_failed_tree_update_keeps_previous_cache(setup, monkeypatch):
    cp, work = setup
    (work / "a.txt").write_text("old")
    cp.snapshot(work, "before")
    cache = cp.repo(work) / "snapshot-cache.json"
    old = cache.read_bytes()
    (work / "a.txt").write_text("new")
    git = cp.git

    def fail(repo, *args, **kwargs):
        if args[0] == "write-tree":
            raise RuntimeError("simulated interruption")
        return git(repo, *args, **kwargs)

    monkeypatch.setattr(cp, "git", fail)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        cp.snapshot(work, "failed")
    assert cache.read_bytes() == old
    monkeypatch.setattr(cp, "git", git)
    result = cp.snapshot(work, "retry")
    sha = cp.tree(cp.repo(work), result["commit"])["a.txt"][1]
    assert cp.git(cp.repo(work), "cat-file", "blob", sha) == b"new"


def test_prune_invalidates_cached_objects(setup):
    cp, work = setup
    (work / "a.txt").write_text("old")
    first = cp.snapshot(work, "first")["commit"]
    cp.set_ref(work, "keep", "before", first)
    (work / "a.txt").write_text("new")
    os.utime(work / "a.txt", (1, 1))
    second = cp.snapshot(work, "second")["commit"]
    cp.set_ref(work, "delete", "before", second)
    assert cp.delete_runs(cp.repo(work), {"delete"}) == 1
    result = cp.snapshot(work, "after-prune")
    sha = cp.tree(cp.repo(work), result["commit"])["a.txt"][1]
    assert cp.git(cp.repo(work), "cat-file", "blob", sha) == b"new"
    assert cp.get_ref(work, "keep", "before") == first


def test_checkpoint_storage_inside_workspace_is_never_snapshotted(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.txt").write_text("content")
    cp = Checkpoints(work / "app-data/checkpoints", 1024 * 1024)
    for label in ("first", "second"):
        result = cp.snapshot(work, label)
        assert set(cp.tree(cp.repo(work), result["commit"])) == {"a.txt"}


def test_recent_files_remain_rechecked_and_special_paths_round_trip(setup):
    cp, work = setup
    name = '日本語 "quoted"\tfile\\.txt'
    (work / name).write_text("one")
    before = cp.snapshot(work, "before")["commit"]
    assert cp.snapshot(work, "recent")["hashed_files"] == 1
    (work / name).write_text("two")
    after = cp.snapshot(work, "after")["commit"]
    cp.restore(work, before, after)
    assert (work / name).read_text() == "one"
    assert json.loads((cp.repo(work) / "snapshot-cache.json").read_text())["version"] == 2
