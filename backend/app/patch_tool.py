"""Apply Responses API apply_patch operations inside the sandbox.

This module uses only the standard library: its source is sent to the container
and executed there, so path checks resolve against the sandbox filesystem.
"""

import difflib
import json
import os
import posixpath
import sys
import tempfile

MAX_DIFF_CHARS = 20_000


class PatchError(Exception):
    pass


def parse_hunks(diff):
    hunks, current = [], None
    for number, line in enumerate(diff.split("\n"), 1):
        if line.startswith("@@"):
            current = dict(anchor=line[2:].strip(), lines=[], eof=False)
            hunks.append(current)
            continue
        if line == "*** End of File":
            if current is not None:
                current["eof"] = True
            continue
        if line.startswith("*** "):
            continue
        if current is None:
            current = dict(anchor="", lines=[], eof=False)
            hunks.append(current)
        if line == "":
            current["lines"].append((" ", ""))
        elif line[0] in " -+":
            current["lines"].append((line[0], line[1:]))
        else:
            raise PatchError(
                f"Invalid diff line {number}: lines must start with ' ', '-', '+' or '@@'"
            )
    for hunk in hunks:
        # A trailing empty line comes from the final newline, not from context.
        while hunk["lines"] and hunk["lines"][-1] == (" ", ""):
            hunk["lines"].pop()
    return [h for h in hunks if h["lines"] or h["anchor"]]


def find(lines, old, start, eof):
    candidates = [len(lines) - len(old)] if eof else []
    candidates += range(start, len(lines) - len(old) + 1)
    for normalize in (lambda s: s, str.rstrip, str.strip):
        target = [normalize(s) for s in old]
        for index in candidates:
            if index >= start and [normalize(s) for s in lines[index:index + len(old)]] == target:
                return index
    return None


def apply_diff(text, diff):
    newline = "\r\n" if "\r\n" in text else "\n"
    body = text.replace("\r\n", "\n")
    trailing = body.endswith("\n") or body == ""
    lines = body.split("\n")
    if trailing:
        lines.pop()
    cursor = 0
    for number, hunk in enumerate(parse_hunks(diff), 1):
        if hunk["anchor"]:
            anchor = next(
                (i for i in range(cursor, len(lines)) if lines[i].strip() == hunk["anchor"]),
                None,
            )
            if anchor is None:
                raise PatchError(f"Hunk {number}: anchor not found: {hunk['anchor'][:200]}")
            cursor = anchor + 1
        old = [s for tag, s in hunk["lines"] if tag in " -"]
        new = [s for tag, s in hunk["lines"] if tag in " +"]
        if not old:
            position = len(lines) if hunk["eof"] or not hunk["anchor"] else cursor
        else:
            position = find(lines, old, cursor, hunk["eof"])
            if position is None:
                raise PatchError(
                    f"Hunk {number}: context not found. Re-read the file and retry. "
                    f"First expected line: {old[0][:200]!r}"
                )
        lines[position:position + len(old)] = new
        cursor = position + len(new)
    result = "\n".join(lines) + ("\n" if trailing and lines else "")
    return result.replace("\n", newline) if newline != "\n" else result


def created_content(diff):
    lines = diff.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for number, line in enumerate(lines, 1):
        if line and not line.startswith("+"):
            raise PatchError(f"create_file line {number} must start with '+'")
    return "".join(line[1:] + "\n" for line in lines)


def resolve(root, path):
    if not isinstance(path, str) or not path or "\0" in path:
        raise PatchError("A file path is required")
    if path.startswith("/"):
        if not (path + "/").startswith(root.rstrip("/") + "/"):
            raise PatchError(f"Only files under {root} can be patched: {path}")
        path = posixpath.relpath(path, root)
    relative = posixpath.normpath(path)
    if relative in (".", "") or relative.startswith("../") or relative == "..":
        raise PatchError(f"Path must stay inside {root}: {path}")
    target = posixpath.join(root, relative)
    real_root = os.path.realpath(root)
    parent = posixpath.dirname(target)
    while not os.path.lexists(parent):
        parent = posixpath.dirname(parent)
    if not (os.path.realpath(parent) + "/").startswith(real_root + "/") and \
            os.path.realpath(parent) != real_root:
        raise PatchError(f"Path resolves outside {root}: {path}")
    if os.path.islink(target):
        raise PatchError(f"Refusing to patch a symbolic link: {relative}")
    if os.path.isdir(target):
        raise PatchError(f"Path is a directory: {relative}")
    return relative, target


def read_text(target, relative):
    with open(target, "rb") as handle:
        raw = handle.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PatchError(f"{relative} is not UTF-8 text; edit it with Shell") from error


def write_text(target, content):
    directory = posixpath.dirname(target)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".patch-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        if os.path.exists(target):
            os.chmod(temporary, os.stat(target).st_mode & 0o7777)
        else:
            os.chmod(temporary, 0o666 & ~current_umask())
        os.replace(temporary, target)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def current_umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


def summarize(relative, before, after):
    old, new = before.splitlines(), after.splitlines()
    added = removed = 0
    lines = []
    for line in difflib.unified_diff(old, new, f"a/{relative}", f"b/{relative}", lineterm=""):
        lines.append(line)
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    diff = "\n".join(lines)
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n[diff truncated]"
    return dict(diff=diff, added=added, removed=removed)


def apply_operation(root, operation):
    kind = operation.get("type")
    try:
        relative, target = resolve(root, operation.get("path"))
        if kind == "create_file":
            if os.path.lexists(target):
                raise PatchError(f"{relative} already exists; use update_file")
            before, after = "", created_content(operation.get("diff") or "")
            write_text(target, after)
            message = f"Created {relative}"
        elif kind == "update_file":
            if not os.path.isfile(target):
                raise PatchError(f"{relative} does not exist; use create_file")
            before = read_text(target, relative)
            after = apply_diff(before, operation.get("diff") or "")
            if after != before:
                write_text(target, after)
            message = f"Updated {relative}" if after != before else f"No changes to {relative}"
        elif kind == "delete_file":
            if not os.path.isfile(target):
                raise PatchError(f"{relative} does not exist")
            try:
                before = read_text(target, relative)
            except PatchError:
                before = ""
            after = ""
            os.unlink(target)
            message = f"Deleted {relative}"
        else:
            raise PatchError(f"Unsupported operation: {kind}")
    except (PatchError, OSError) as error:
        return dict(status="failed", output=str(error), path=operation.get("path"))
    stats = summarize(relative, before, after)
    output = f"{message} (+{stats['added']} -{stats['removed']})"
    return dict(status="completed", output=output, path=relative, **stats)


if __name__ == "__main__":
    request = json.load(sys.stdin)
    json.dump(apply_operation(request["root"], request["operation"]), sys.stdout)
