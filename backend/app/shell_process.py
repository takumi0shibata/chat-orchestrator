"""Stdlib-only command supervisor, executed inside the sandbox with python -I.

The registry lock closes the race between starting a command and stopping it.
Registries live in the container's tmpfs, never in the shared repository.
"""

import fcntl
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def registry(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (path / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path


def run(path, command):
    with registry(path) as state:
        if (state / "stopped").exists():
            return 128 + signal.SIGTERM
        child = subprocess.Popen(["bash", "-c", command], start_new_session=True)
        (state / "pgid").write_text(str(child.pid))
    code = child.wait()
    return code if code >= 0 else 128 - code


def stop(paths, grace=2):
    groups = set()
    for path in paths:
        with registry(path) as state:
            (state / "stopped").touch()
            try:
                group = int((state / "pgid").read_text())
            except FileNotFoundError:
                continue
            try:
                os.killpg(group, signal.SIGTERM)
                groups.add(group)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + grace
    while groups and time.monotonic() < deadline:
        for group in tuple(groups):
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                groups.remove(group)
        if groups:
            time.sleep(min(0.025, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    if sys.argv[1] == "run":
        sys.exit(run(*sys.argv[2:]))
    elif sys.argv[1] == "stop":
        stop(sys.argv[2:])
    else:
        raise ValueError("Unknown supervisor operation")
