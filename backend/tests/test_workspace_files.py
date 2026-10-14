import os
import subprocess
import sys
import unicodedata

import pytest

from app.attachments import file_snapshot
from app.workspace_files import scan_files


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def write(root, *names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content")


def test_gitignore_rules_do_not_hide_files(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("generated/\n*.log\n")
    (tmp_path / ".git/info/exclude").write_text("excluded.txt\n")
    write(tmp_path, "generated/deep/blob", "debug.log", "excluded.txt", "日本語 [1].txt")
    files = scan_files(tmp_path)
    assert set(files) == {
        ".gitignore", "generated/deep/blob", "debug.log", "excluded.txt", "日本語 [1].txt",
    }
    assert set(file_snapshot(tmp_path)) == set(files)


def test_excluded_directories_and_symlinks_are_skipped(tmp_path):
    write(tmp_path, "keep.txt", "node_modules/pkg/file", "sub/.venv/lib.py", "sub/__pycache__/x.pyc")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    write(outside, "file")
    (tmp_path / "dir-link").symlink_to(outside, target_is_directory=True)
    (tmp_path / "file-link").symlink_to(outside / "file")
    os.mkfifo(tmp_path / "pipe")
    assert set(scan_files(tmp_path)) == {"keep.txt"}


def test_nested_repositories_include_their_files_but_not_git_data(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    git(nested, "init", "-q")
    write(nested, "keep", "ignored.log")
    (nested / ".gitignore").write_text("*.log\n")
    git(nested, "add", ".")
    git(nested, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "initial")
    git(nested, "worktree", "add", "-q", "--detach", str(tmp_path / "linked"))
    assert set(scan_files(tmp_path)) == {
        "nested/.gitignore", "nested/keep", "nested/ignored.log",
        "linked/.gitignore", "linked/keep",
    }


def test_reused_states_skip_stat_unless_stale(tmp_path):
    write(tmp_path, "a.txt", "b.txt")
    first = scan_files(tmp_path)
    (tmp_path / "a.txt").write_text("changed")
    (tmp_path / "b.txt").write_text("changed")
    write(tmp_path, "new.txt")
    second = scan_files(tmp_path, reuse=first, stale={"b.txt"})
    # Reused states are trusted as is; stale and new files are stat'ed.
    assert second["a.txt"] is first["a.txt"]
    assert second["b.txt"] != first["b.txt"] and "new.txt" in second
    (tmp_path / "a.txt").unlink()
    assert "a.txt" not in scan_files(tmp_path, reuse=first)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS stores decomposed names as given")
def test_decomposed_names_use_precomposed_keys(tmp_path):
    (tmp_path / unicodedata.normalize("NFD", "ガイド.txt")).write_text("x")
    assert list(scan_files(tmp_path)) == [unicodedata.normalize("NFC", "ガイド.txt")]
