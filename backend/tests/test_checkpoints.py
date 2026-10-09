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
