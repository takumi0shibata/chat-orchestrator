import base64
import os
import stat
from pathlib import Path, PurePosixPath
from uuid import uuid4

from fastapi import UploadFile


def safe_path(root: Path, relative: str, *, directory=False):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("Invalid file path")
    root = root.resolve()
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symbolic links are not accessible")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root) or (not directory and not resolved.is_file()):
        raise ValueError("Not an allowed regular file")
    return resolved


def open_regular(root: Path, relative: str):
    # Open each component relative to an already-open directory (no symlink race).
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or PurePosixPath(relative).is_absolute()
        or ".." in parts
        or "\\" in relative
    ):
        raise ValueError("Invalid file path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = next_fd
        result = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
        )
        if not stat.S_ISREG(os.fstat(result).st_mode):
            os.close(result)
            raise ValueError("Not a regular file")
        return os.fdopen(result, "rb")
    finally:
        os.close(fd)


def list_files(root: Path, relative=""):
    parts = PurePosixPath(relative).parts
    if PurePosixPath(relative).is_absolute() or ".." in parts or "\\" in relative:
        raise ValueError("Invalid directory path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        entries = []
        for name in os.listdir(fd):
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                continue
            directory = stat.S_ISDIR(info.st_mode)
            entries.append(
                dict(
                    name=name,
                    path=str(PurePosixPath(relative) / name),
                    directory=directory,
                    size=0 if directory else info.st_size,
                )
            )
        return sorted(entries, key=lambda e: (not e["directory"], e["name"].lower()))
    finally:
        os.close(fd)


async def save_upload(store, cid, upload: UploadFile, limit):
    store.conversation(cid)
    aid = uuid4().hex
    name = Path((upload.filename or "attachment").replace("\\", "/")).name
    name = "".join(c for c in name if c.isprintable())[:200] or "attachment"
    path = store.root / "attachments" / cid / aid / name
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with path.open("xb") as f:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError("Attachment exceeds upload size limit")
                f.write(chunk)
        data = dict(
            id=aid,
            conversation_id=cid,
            name=name,
            content_type=upload.content_type or "application/octet-stream",
            size=size,
            path=str(path),
        )
        store.add_attachment(data)
        return {k: v for k, v in data.items() if k != "path"}
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def direct_input(attachment):
    path = Path(attachment["path"])
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(suffix)
    if not mime or attachment["size"] > 20 * 1024 * 1024:
        raise ValueError(
            "Direct model input supports PNG, JPEG, WebP and PDF up to 20 MiB each"
        )
    raw = path.read_bytes()
    signatures = {
        ".png": b"\x89PNG\r\n\x1a\n",
        ".jpg": b"\xff\xd8\xff",
        ".jpeg": b"\xff\xd8\xff",
        ".pdf": b"%PDF-",
    }
    if suffix in signatures and not raw.startswith(signatures[suffix]):
        raise ValueError("File signature does not match its extension")
    if suffix == ".webp" and not (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"):
        raise ValueError("Invalid WebP")
    data = f"data:{mime};base64," + base64.b64encode(raw).decode()
    if suffix == ".pdf":
        return dict(type="input_file", filename=attachment["name"], file_data=data)
    return dict(type="input_image", image_url=data, detail="auto")


def file_snapshot(root: Path):
    """Metadata only: never reads document contents or follows directory symlinks."""
    result = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [
            d for d in dirs
            if d not in {".venv", "venv", "node_modules", ".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
            and not (Path(folder) / d).is_symlink()
        ]
        for name in files:
            p = Path(folder) / name
            try:
                info = p.lstat()
                if stat.S_ISREG(info.st_mode):
                    result[str(p.relative_to(root))] = (info.st_size, info.st_mtime_ns)
            except FileNotFoundError:
                continue
    return result
