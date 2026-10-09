"""Bounded UTF-8 editing with revision checks and atomic, workspace-only saves."""

import hashlib
import os
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4


MAX_TEXT_BYTES = 1024 * 1024
TEXT_EXTENSIONS = frozenset(
    ".md .markdown .txt .toml .yaml .yml .json .jsonc .jsonl .csv .tsv "
    ".ini .cfg .conf .log .xml .html .htm .css .scss .sass .less .svg "
    ".js .jsx .ts .tsx .mjs .cjs .py .pyi .sh .bash .zsh .fish .sql "
    ".r .c .h .cpp .hpp .rs .go .java .kt .swift .tex .bib .rst .adoc "
    ".properties .env .gitignore .gitattributes .editorconfig".split()
)
TEXT_NAMES = frozenset(
    "dockerfile makefile gemfile procfile license readme .env .gitignore "
    ".gitattributes .editorconfig .npmrc .nvmrc .bashrc .zshrc".split()
)


class FileChanged(ValueError):
    pass


def editable_name(name: str) -> bool:
    name = PurePosixPath(name).name.lower()
    return (
        PurePosixPath(name).suffix in TEXT_EXTENSIONS
        or name in TEXT_NAMES
        or name.startswith(".env.")
    )


@contextmanager
def file_parent(root: Path, relative: str):
    path = PurePosixPath(relative)
    if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("Invalid file path")
    if not editable_name(relative):
        raise ValueError("This file type is not supported by the text editor. Download it to open it in another app.")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, path.name
    finally:
        os.close(fd)


def read_at(parent: int, name: str):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Not a regular file")
        if info.st_size > MAX_TEXT_BYTES:
            raise ValueError("The text editor supports files up to 1 MiB.")
        data = file.read(MAX_TEXT_BYTES + 1)
        if len(data) > MAX_TEXT_BYTES:
            raise ValueError("The text editor supports files up to 1 MiB.")
    decode_text(data)
    return data, info


def decode_text(data: bytes) -> str:
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("The text editor supports UTF-8 text files only.") from None
    if any(ord(char) < 32 and char not in "\t\r\n\f" for char in content):
        raise ValueError("Binary files cannot be edited as text.")
    return content


def document(path: str, data: bytes):
    return dict(
        path=path,
        content=decode_text(data).replace("\r\n", "\n").replace("\r", "\n"),
        revision=hashlib.sha256(data).hexdigest(),
        size=len(data),
    )


def read_text_file(root: Path, path: str):
    with file_parent(root, path) as (parent, name):
        data, _ = read_at(parent, name)
        return document(path, data)


def save_text_file(root: Path, path: str, content: str, revision: str):
    with file_parent(root, path) as (parent, name):
        original, info = read_at(parent, name)
        if hashlib.sha256(original).hexdigest() != revision:
            raise FileChanged("This file changed since it was opened. Copy your edits before reloading the latest version.")
        # The browser uses LF internally; retain the file's BOM and newline convention.
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        original_text = decode_text(original)
        newline = "\r\n" if "\r\n" in original_text else "\r" if "\r" in original_text else "\n"
        data = normalized.replace("\n", newline).encode("utf-8")
        if original.startswith(b"\xef\xbb\xbf"):
            data = b"\xef\xbb\xbf" + data
        if len(data) > MAX_TEXT_BYTES:
            raise ValueError("The text editor supports files up to 1 MiB.")
        decode_text(data)
        temporary = f".editor-{uuid4().hex}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                os.fchmod(file.fileno(), stat.S_IMODE(info.st_mode) & 0o777)
                file.flush()
                os.fsync(file.fileno())
            current, current_info = read_at(parent, name)
            if current != original or (current_info.st_dev, current_info.st_ino) != (info.st_dev, info.st_ino):
                raise FileChanged("This file changed while saving. Copy your edits before reloading the latest version.")
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        return document(path, data)
