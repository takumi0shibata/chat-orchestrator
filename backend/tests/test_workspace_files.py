import subprocess
from pathlib import Path

import pytest

from app.attachments import file_snapshot
from app.workspace_files import scan_files


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


@pytest.mark.parametrize("repository", [False, True])
def test_gitignore_rules_and_directory_pruning(tmp_path, monkeypatch, repository):
    if repository:
        git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(
        "generated/\n*.log\n!keep.log\n/root-only.txt\ncache/*\n!cache/keep.txt\n"
    )
    for name in ["generated/deep/blob", "discard.log", "keep.log", "root-only.txt",
                 "sub/root-only.txt", "sub/local.log", "sub/drop.tmp", "cache/drop.txt",
                 "cache/keep.txt", "node_modules/pkg/file", "日本語 [1].txt"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content")
    (tmp_path / "sub/.gitignore").write_text("!local.log\n*.tmp\n")
    original = Path.lstat
    checked = []

    def record(path, *args, **kwargs):
        # Ignored entries must never reach Python's per-file stat loop.
        checked.append(path)
        assert not path.is_relative_to(tmp_path / "generated")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", record)
    files = scan_files(tmp_path)
    assert set(files) == {
        ".gitignore", "keep.log", "sub/.gitignore", "sub/root-only.txt", "sub/local.log",
        "cache/keep.txt", "日本語 [1].txt",
    }
    assert set(file_snapshot(tmp_path)) == set(files)
    assert not any(p.name == "discard.log" for p in checked)
    if not repository:
        assert not (tmp_path / ".git").exists()


def test_tracked_ignored_files_and_index_unchanged(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("output/\n*.log\n")
    (tmp_path / "output").mkdir()
    (tmp_path / "output/tracked.log").write_text("keep")
    (tmp_path / "output/untracked.log").write_text("ignore")
    git(tmp_path, "add", "-f", "output/tracked.log")
    index = (tmp_path / ".git/index").read_bytes()
    assert set(scan_files(tmp_path)) == {".gitignore", "output/tracked.log"}
    assert (tmp_path / ".git/index").read_bytes() == index
    # Starting from a repository subdirectory must preserve tracked exceptions.
    assert set(scan_files(tmp_path / "output")) == {"tracked.log"}


def test_nested_repositories_and_worktrees(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    git(root, "init", "-q")
    nested = root / "nested"
    nested.mkdir()
    git(nested, "init", "-q")
    (nested / ".gitignore").write_text("*.log\n")
    (nested / "keep").write_text("one")
    (nested / "ignored.log").write_text("ignored")
    git(nested, "add", ".")
    git(nested, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "initial")
    linked = root / "linked"
    git(nested, "worktree", "add", "--detach", str(linked))
    (linked / "ignored.log").write_text("ignored")
    # Parent records a gitlink rather than the nested repository's individual files.
    git(root, "add", "nested")
    assert set(scan_files(root)) == {
        "nested/.gitignore", "nested/keep", "linked/.gitignore", "linked/keep",
    }


def test_tracked_paths_cannot_follow_replaced_directory_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    git(root, "init", "-q")
    (root / "dir").mkdir()
    (root / "dir/file").write_text("inside")
    git(root, "add", "dir/file")
    (root / "dir/file").unlink()
    (root / "dir").rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_text("outside")
    (root / "dir").symlink_to(outside, target_is_directory=True)
    (root / "file-link").symlink_to(outside / "file")
    assert scan_files(root) == {}


def test_git_environment_and_fsmonitor_are_not_used(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    (tmp_path / "keep").write_text("content")
    git(tmp_path, "add", "keep")
    git(tmp_path, "config", "core.fsmonitor", "false-command-must-not-run")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "missing.git"))
    monkeypatch.setenv("GIT_WORK_TREE", "/")
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "missing-index"))
    assert set(scan_files(tmp_path)) == {"keep"}
    assert not (tmp_path / "missing-index").exists()
