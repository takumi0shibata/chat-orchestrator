"""Attach a shell to a PTY without forking the running API process."""

import fcntl
import os
import sys
import termios


def main():
    tty_path, shell, ready_fd_text = sys.argv[1:4]
    ready_fd = int(ready_fd_text)
    tty = os.open(tty_path, os.O_RDWR)
    fcntl.ioctl(tty, termios.TIOCSCTTY, 0)
    for target in (0, 1, 2):
        os.dup2(tty, target)
    if tty > 2:
        os.close(tty)
    os.write(ready_fd, b"1")
    os.close(ready_fd)
    os.execve(shell, ["-" + os.path.basename(shell), "-i"], os.environ)


if __name__ == "__main__":
    main()
