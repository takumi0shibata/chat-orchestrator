import os
import shlex
import signal
import subprocess
import sys
import time
from contextlib import contextmanager

import pytest

from app.config import Folder, Settings
from app.sandbox import SHELL_PROCESS, Sandbox
from app.shell_process import stop


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("Command did not reach the expected state")
        time.sleep(0.01)


@contextmanager
def supervised(tmp_path, command, **kwargs):
    state = tmp_path / "command"
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", SHELL_PROCESS, "run", str(state), command],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs,
    )
    try:
        yield process, state
    finally:
        # Also reap commands that intentionally ignore SIGTERM in a test.
        if (state / "pgid").exists():
            try:
                os.killpg(int((state / "pgid").read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def git(work, *args, **kwargs):
    return subprocess.run(
        ["git", "-C", str(work), *args], capture_output=True, check=True, **kwargs,
    )


def sandbox_environment(work):
    sandbox = Sandbox(
        Settings(_env_file=None), Folder(id="w", label="w", path=work),
        "test", [], [], work / "input",
    )
    args = sandbox.arguments()
    environment = dict(os.environ)
    for index, value in enumerate(args):
        if value == "--env" and args[index + 1].startswith("GIT_"):
            key, setting = args[index + 1].split("=", 1)
            environment[key] = setting
    return environment


def test_supervisor_preserves_output_and_exit_status(tmp_path):
    with supervised(tmp_path, "printf hello; printf error >&2; exit 7") as (process, _):
        assert process.communicate(timeout=5) == (b"hello", b"error")
        assert process.returncode == 7


def test_stop_before_command_registration_prevents_launch(tmp_path):
    stop([tmp_path / "command"])
    with supervised(tmp_path, "touch launched", cwd=tmp_path) as (process, _):
        process.communicate(timeout=5)
        assert process.returncode == 143
        assert not (tmp_path / "launched").exists()


def test_git_status_preserves_host_index_config_and_existing_lock(tmp_path):
    git(tmp_path, "init", "-q")
    target = tmp_path / "file.txt"
    target.write_text("original\n")
    git(tmp_path, "add", "file.txt")
    hook = tmp_path / "monitor"
    hook.write_text("#!/bin/sh\ntouch monitor-invoked\nsleep 10\n")
    hook.chmod(0o755)
    git(tmp_path, "config", "core.fsmonitor", str(hook))
    index = tmp_path / ".git/index"
    config = tmp_path / ".git/config"
    before = (index.read_bytes(), index.stat().st_mtime_ns, config.read_bytes())
    target.write_text("changed\n")
    env = sandbox_environment(tmp_path)
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert env["GIT_CONFIG_KEY_0"] == "core.fsmonitor"
    result = git(tmp_path, "status", "--short", "--untracked-files=no", env=env, timeout=5)
    assert b"file.txt" in result.stdout
    assert not (tmp_path / "monitor-invoked").exists()
    assert before == (index.read_bytes(), index.stat().st_mtime_ns, config.read_bytes())
    lock = tmp_path / ".git/index.lock"
    lock.write_bytes(b"another process owns this")
    git(tmp_path, "status", "--short", env=env, timeout=5)
    with pytest.raises(subprocess.CalledProcessError):
        git(tmp_path, "add", "file.txt", env=env)
    assert lock.read_bytes() == b"another process owns this"
    lock.unlink()
    git(tmp_path, "add", "file.txt", env=env)
    git(tmp_path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "test", env=env)
    assert git(tmp_path, "show", "HEAD:file.txt", env=env).stdout == b"changed\n"
    assert config.read_bytes() == before[2]


def test_stopping_git_and_filter_releases_lock_for_host_add(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "file.txt").write_text("contents\n")
    (tmp_path / ".gitattributes").write_text("*.txt filter=slow\n")
    source = (
        "import pathlib,signal,time,sys; "
        "signal.signal(signal.SIGTERM, lambda *a: "
        "(pathlib.Path('terminated').touch(), sys.exit(1))); "
        "pathlib.Path('filter-started').touch(); time.sleep(60)"
    )
    filter_command = shlex.join([sys.executable, "-c", source])
    command = shlex.join(["git", "-c", f"filter.slow.clean={filter_command}", "add", "file.txt"])
    with supervised(tmp_path, command, cwd=tmp_path) as (process, state):
        wait_for(lambda: (tmp_path / "filter-started").exists())
        assert (tmp_path / ".git/index.lock").exists()
        stop([state])
        process.communicate(timeout=5)
        assert process.returncode != 0
        assert (tmp_path / "terminated").exists()
        assert not (tmp_path / ".git/index.lock").exists()
        # Host Git can stage immediately after sandbox interruption.
        git(tmp_path, "add", "file.txt")


def test_stop_has_bounded_grace_for_uncooperative_commands(tmp_path):
    source = (
        "import signal,pathlib,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path('ready').touch(); time.sleep(60)"
    )
    with supervised(tmp_path, shlex.join([sys.executable, "-c", source]), cwd=tmp_path) as (process, state):
        wait_for(lambda: (tmp_path / "ready").exists())
        started = time.monotonic()
        stop([state], grace=0.1)
        assert time.monotonic() - started < 1
        assert process.poll() is None
