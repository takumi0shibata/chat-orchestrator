import os

import pytest

from app.patch_tool import PatchError, apply_diff, apply_operation


def test_update_hunks_preserve_newlines_and_anchor():
    text = "def a():\n    x = 1\n\ndef b():\n    x = 1\n"
    diff = "@@ def b():\n-    x = 1\n+    x = 2\n"
    assert apply_diff(text, diff) == "def a():\n    x = 1\n\ndef b():\n    x = 2\n"
    assert apply_diff("a\r\nb\r\n", "@@\n a\n-b\n+c\n") == "a\r\nc\r\n"
    assert apply_diff("a\nb", "@@\n-b\n+c\n") == "a\nc"


def test_update_tolerates_whitespace_and_supports_insertions():
    assert apply_diff("x = 1   \ny\n", "@@\n-x = 1\n+x = 2\n") == "x = 2\ny\n"
    assert apply_diff("a\n", "@@\n+b\n*** End of File\n") == "a\nb\n"
    # Context blank lines may arrive without their leading space.
    assert apply_diff("a\n\nb\n", "@@\n a\n\n-b\n+c\n") == "a\n\nc\n"
    assert apply_diff("a\nb\na\nb\n", "@@\n-b\n+B\n@@\n-b\n+C\n") == "a\nB\na\nC\n"


def test_update_reports_missing_context():
    with pytest.raises(PatchError, match="context not found"):
        apply_diff("a\n", "@@\n-missing\n+b\n")
    with pytest.raises(PatchError, match="anchor not found"):
        apply_diff("a\n", "@@ nope\n-a\n+b\n")
    with pytest.raises(PatchError, match="Invalid diff line"):
        apply_diff("a\n", "@@\n*a\n")


def test_operations_apply_inside_root(tmp_path):
    root = str(tmp_path)
    created = apply_operation(root, dict(type="create_file", path="notes/a.txt", diff="+alpha\n+beta\n"))
    assert created["status"] == "completed"
    assert (tmp_path / "notes/a.txt").read_text() == "alpha\nbeta\n"
    assert created["added"] == 2 and "+alpha" in created["diff"]
    updated = apply_operation(root, dict(type="update_file", path=f"{root}/notes/a.txt", diff="@@\n-beta\n+gamma\n"))
    assert updated["output"] == "Updated notes/a.txt (+1 -1)"
    assert (tmp_path / "notes/a.txt").read_text() == "alpha\ngamma\n"
    assert apply_operation(root, dict(type="create_file", path="notes/a.txt", diff="+x\n"))["status"] == "failed"
    deleted = apply_operation(root, dict(type="delete_file", path="notes/a.txt"))
    assert deleted["status"] == "completed" and not (tmp_path / "notes/a.txt").exists()


def test_operations_preserve_permissions(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text("echo a\n")
    script.chmod(0o755)
    apply_operation(str(tmp_path), dict(type="update_file", path="run.sh", diff="@@\n-echo a\n+echo b\n"))
    assert os.stat(script).st_mode & 0o777 == 0o755


@pytest.mark.parametrize("path", ["../escape.txt", "/etc/passwd", "a/../../x", "", "."])
def test_operations_reject_paths_outside_root(tmp_path, path):
    root = tmp_path / "root"
    root.mkdir()
    result = apply_operation(str(root), dict(type="create_file", path=path, diff="+x\n"))
    assert result["status"] == "failed"
    assert not (tmp_path / "escape.txt").exists()


def test_operations_reject_symlinks_and_binary(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("secret\n")
    (root / "link").symlink_to(outside)
    (root / "file-link").symlink_to(outside / "f.txt")
    for path in ("link/f.txt", "link/new.txt", "file-link"):
        op = dict(type="update_file", path=path, diff="@@\n-secret\n+x\n")
        assert apply_operation(str(root), op)["status"] == "failed"
        assert apply_operation(str(root), {**op, "type": "create_file", "diff": "+x\n"})["status"] == "failed"
    assert (outside / "f.txt").read_text() == "secret\n"
    assert not (outside / "new.txt").exists()
    (root / "data.bin").write_bytes(b"\xff\xfe")
    result = apply_operation(str(root), dict(type="update_file", path="data.bin", diff="@@\n+x\n"))
    assert result["status"] == "failed" and "not UTF-8" in result["output"]
    assert apply_operation(str(root), dict(type="delete_file", path="data.bin"))["status"] == "completed"
