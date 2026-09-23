"""Short-lived host terminal sessions owned by a WebSocket connection."""

import asyncio
import errno
import fcntl
import os
import pwd
import signal
import struct
import sys
import termios
from pathlib import Path


def shell_environment():
    account = pwd.getpwuid(os.getuid())
    shell = account.pw_shell if account.pw_shell and os.access(account.pw_shell, os.X_OK) else "/bin/sh"
    env = {
        "HOME": account.pw_dir,
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "SHELL": shell,
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
    }
    for key, value in os.environ.items():
        if key == "LANG" or key == "LC_ALL" or key.startswith("LC_"):
            env[key] = value
    return shell, env


def terminal_size(cols, rows):
    if (
        not isinstance(cols, int) or isinstance(cols, bool)
        or not isinstance(rows, int) or isinstance(rows, bool)
        or not 20 <= cols <= 500 or not 5 <= rows <= 200
    ):
        raise ValueError("Invalid terminal size")
    return cols, rows


async def wait_fd(fd, writable=False):
    loop = asyncio.get_running_loop()
    ready = loop.create_future()
    callback = lambda: None if ready.done() else ready.set_result(None)
    add = loop.add_writer if writable else loop.add_reader
    remove = loop.remove_writer if writable else loop.remove_reader
    add(fd, callback)
    try:
        await ready
    finally:
        remove(fd)


async def wait_process_exit(process, timeout):
    deadline = asyncio.get_running_loop().time() + timeout
    while process.returncode is None and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.025)
    return process.returncode is not None


class HostTerminal:
    def __init__(self, workspace):
        self.workspace = workspace
        self.master = None
        self.process = None
        self.closed = False

    async def start(self, cols, rows):
        cols, rows = terminal_size(cols, rows)
        shell, env = shell_environment()
        master, slave = os.openpty()
        ready_read, ready_write = os.pipe()
        self.master = master
        try:
            tty_path = os.ttyname(slave)
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            os.set_blocking(master, False)
            os.set_blocking(ready_read, False)
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).with_name("terminal_child.py")),
                tty_path, shell, str(ready_write),
                cwd=str(self.workspace), env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(ready_write,),
            )
            os.close(ready_write)
            ready_write = -1
            await asyncio.wait_for(wait_fd(ready_read), timeout=5)
            if os.read(ready_read, 1) != b"1":
                raise RuntimeError("Terminal shell could not start")
            if self.closed:
                raise RuntimeError("Terminal was closed while starting")
        except BaseException:
            await self.close()
            raise
        finally:
            os.close(ready_read)
            if ready_write >= 0:
                os.close(ready_write)
            os.close(slave)

    def resize(self, cols, rows):
        cols, rows = terminal_size(cols, rows)
        if self.master is not None:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def read(self):
        while self.master is not None:
            try:
                return os.read(self.master, 16384)
            except BlockingIOError:
                await wait_fd(self.master)
            except OSError as error:
                if error.errno in (errno.EIO, errno.EBADF):
                    return b""
                raise
        return b""

    async def write(self, data):
        if len(data) > 65536:
            raise ValueError("Terminal input frame too large")
        offset = 0
        while offset < len(data) and self.master is not None:
            try:
                offset += os.write(self.master, data[offset:])
            except BlockingIOError:
                await wait_fd(self.master, writable=True)

    async def close(self):
        self.closed = True
        process = self.process
        master = self.master
        self.master = None
        groups = set()
        if process is not None:
            groups.add(process.pid)
            if master is not None:
                try:
                    groups.add(os.tcgetpgrp(master))
                except OSError:
                    pass
        if master is not None:
            os.close(master)
        if process is not None:
            if not await wait_process_exit(process, 0.7):
                for group in groups:
                    if group <= 0 or group == os.getpgrp():
                        continue
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                if process.returncode is None:
                    try:
                        process.kill()
                    except (ProcessLookupError, PermissionError):
                        pass
                await wait_process_exit(process, 0.7)
