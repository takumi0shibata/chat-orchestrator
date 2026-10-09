"""Read-only, on-demand index of opted-in workspace journals. No model calls."""

import hashlib
import os
import re
import stat
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone

from app.storage import now

FOLDER = ".chat-orchestrator"
MAX_FILE_BYTES = 64 * 1024
MAX_PROJECT_BYTES = 512 * 1024
MAX_ACTIVITY_FILES = 30
MAX_DIRECTORY_ENTRIES = 2000
MAX_TASKS = 500
STATES = {
    "未着手": "todo", "todo": "todo",
    "進行中": "in_progress", "in progress": "in_progress",
    "確認待ち": "review", "review": "review",
    "待ち": "waiting", "waiting": "waiting",
    "保留": "paused", "paused": "paused",
    "完了": "done", "done": "done",
}


class WorkspaceUnavailable(OSError):
    pass


@contextmanager
def directory(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise WorkspaceUnavailable from error
    try:
        yield fd
    finally:
        os.close(fd)


def read_document(fd, name, path):
    try:
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None
    with os.fdopen(handle, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{path}: Not a regular file.")
        if info.st_size > MAX_FILE_BYTES:
            raise ValueError(f"{path}: Exceeds the 64 KiB limit.")
        raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError(f"{path}: Exceeds the 64 KiB limit.")
        after = os.fstat(stream.fileno())
        if (info.st_mtime_ns, info.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError(f"{path}: The file is being updated. Please Sync again.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{path}: Save this file as UTF-8.") from None
    return {
        "path": path, "content": content,
        "updated_at": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
    }


def prose_lines(content):
    """Ignore fenced examples when extracting headings and checkbox tasks."""
    fence = None
    for number, line in enumerate(content.splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[marker.end():].strip():
                fence = None
            continue
        if fence is None:
            yield number, line


def plain(text):
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[*`_~]", "", text).strip()


def overview_fields(content):
    sections = {}
    section = ""
    first = []
    for _, line in prose_lines(content):
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            section = plain(heading[1]).casefold()
            sections.setdefault(section, [])
        elif line.strip():
            cleaned = plain(line)
            first.append(cleaned)
            sections.setdefault(section, []).append(cleaned)
    def extract(*keys):
        return " ".join(next((sections[k] for k in keys if sections.get(k)), []))[:600]
    return {
        "summary": extract("現在地", "概要", "summary", "status") or " ".join(first)[:600],
        "next_action": extract("次の一手", "次にやること", "next", "next action"),
    }


def parse_tasks(content):
    tasks = []
    state = "todo"
    state_level = 0
    for number, line in prose_lines(content):
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            name = plain(heading[2]).casefold()
            if name in STATES:
                state, state_level = STATES[name], len(heading[1])
            elif len(heading[1]) <= state_level:
                state, state_level = "todo", 0
            continue
        match = re.match(r"^\s*[-*+]\s+\[([ xX])\]\s+(.+)$", line)
        if not match:
            continue
        title = match[2].strip()
        due = None
        due_match = re.search(r"\s*\(due:\s*(\d{4}-\d{2}-\d{2})\)", title)
        if due_match:
            try:
                due = date.fromisoformat(due_match[1]).isoformat()
            except ValueError:
                raise ValueError(f"tasks.md:{number}: Invalid due date.") from None
            title = title[:due_match.start()] + title[due_match.end():]
        tasks.append({
            "id": f"task-{number}", "title": plain(title),
            "status": "done" if match[1].lower() == "x" else state,
            "due": due, "line": number, "source": "tasks.md",
        })
        if len(tasks) > MAX_TASKS:
            raise ValueError("tasks.md: Up to 500 tasks can be imported.")
    return tasks


def project_status(tasks):
    for state in ("review", "in_progress", "waiting", "todo", "paused", "done"):
        if any(task["status"] == state for task in tasks):
            return state
    return "unknown"


def activity_entry(document):
    lines = list(prose_lines(document["content"]))
    title = next((plain(re.sub(r"^#+\s+", "", line)) for _, line in lines if line.strip()), document["path"])
    body = [plain(line) for _, line in lines if line.strip() and not line.startswith("#")]
    filename_date = document["path"].split("/")[-1][:10]
    try:
        entry_date = date.fromisoformat(filename_date).isoformat()
    except ValueError:
        entry_date = document["updated_at"][:10]
    return {"source": document["path"], "title": title[:200], "summary": " ".join(body)[:300], "date": entry_date}


def source_key(workspace):
    return hashlib.sha256(str(workspace.path).encode()).hexdigest()


def read_project(workspace, synced_at):
    documents = []
    warnings = []
    # Missing workspace != opt-out. An unavailable drive must retain its last snapshot.
    with directory(workspace.path) as root:
        try:
            guild_fd = os.open(FOLDER, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        except FileNotFoundError:
            return None
        try:
            for name in ("overview.md", "tasks.md"):
                document = read_document(guild_fd, name, name)
                if document is not None:
                    documents.append(document)
                else:
                    warnings.append(f"{name} is missing.")
            try:
                activity_fd = os.open("activity", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=guild_fd)
            except FileNotFoundError:
                activity_fd = None
            if activity_fd is not None:
                try:
                    names = []
                    with os.scandir(activity_fd) as entries:
                        for count, entry in enumerate(entries, 1):
                            if count > MAX_DIRECTORY_ENTRIES:
                                raise ValueError("activity/: More than 2,000 directory entries.")
                            if entry.name.endswith(".md"):
                                names.append(entry.name)
                    if len(names) > MAX_ACTIVITY_FILES:
                        warnings.append("Imported the latest 30 journal files by filename.")
                    for name in sorted(names, reverse=True)[:MAX_ACTIVITY_FILES]:
                        document = read_document(activity_fd, name, f"activity/{name}")
                        if document is None:
                            raise ValueError("activity/: The file is being updated. Please Sync again.")
                        documents.append(document)
                        if sum(len(d["content"].encode()) for d in documents) > MAX_PROJECT_BYTES:
                            raise ValueError("Records exceed the 512 KiB project limit.")
                finally:
                    os.close(activity_fd)
        finally:
            os.close(guild_fd)
    contents = {doc["path"]: doc["content"] for doc in documents}
    tasks = parse_tasks(contents.get("tasks.md", ""))
    digest = hashlib.sha256()
    for doc in documents:
        digest.update(doc["path"].encode() + b"\0" + doc["content"].encode() + b"\0")
    return {
        "id": workspace.id, "label": workspace.label, "source_key": source_key(workspace),
        **overview_fields(contents.get("overview.md", "")),
        "status": project_status(tasks), "tasks": tasks, "documents": documents,
        "activity": [activity_entry(doc) for doc in documents if doc["path"].startswith("activity/")],
        "updated_at": max((doc["updated_at"] for doc in documents), default=None),
        "synced_at": synced_at, "fingerprint": digest.hexdigest(),
        "warnings": warnings, "error": None,
    }


class Guild:
    def __init__(self, workspaces, store):
        self.workspaces, self.store = workspaces, store
        self.lock = threading.Lock()

    def snapshot(self):
        snapshot = self.store.guild_snapshot()
        sources = {w.id: source_key(w) for w in self.workspaces}
        snapshot["projects"] = [p for p in snapshot["projects"] if sources.get(p["id"]) == p["source_key"]]
        return snapshot

    def sync(self):
        with self.lock:
            previous = {p["id"]: p for p in self.snapshot()["projects"]}
            snapshot = {"synced_at": now(), "projects": []}
            for workspace in self.workspaces:
                try:
                    project = read_project(workspace, snapshot["synced_at"])
                except (OSError, ValueError) as error:
                    # A disconnected, never-imported workspace has not opted in.
                    if isinstance(error, WorkspaceUnavailable) and workspace.id not in previous:
                        continue
                    project = previous.get(workspace.id, {
                        "id": workspace.id, "source_key": source_key(workspace),
                        "summary": "", "next_action": "", "status": "unknown",
                        "tasks": [], "activity": [], "documents": [], "warnings": [],
                        "updated_at": None, "synced_at": None, "fingerprint": "",
                    }).copy()
                    project["label"] = workspace.label
                    project["error"] = str(error) if isinstance(error, ValueError) else "Unable to read records. Check the folder location, permissions, and symbolic links."
                if project is not None:
                    snapshot["projects"].append(project)
            self.store.save_guild_snapshot(snapshot)
            return snapshot
