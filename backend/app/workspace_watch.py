"""File events that let checkpoints skip unchanged files (macOS FSEvents).

Directories are listed on every snapshot, so created and deleted files never
depend on events. Events only tell which already known files may have new
content or metadata, and an event-free sync lets a snapshot reuse its saved
tree without listing. When completeness cannot be
proven (dropped events, history unavailable, no barrier), the caller must fall
back to a full scan.

A barrier file is written in an app-owned directory watched by the same stream.
Event IDs are ordered per stream, so once the barrier event arrives every
earlier workspace event, including writes made through Docker bind mounts, has
been delivered. FSEventStreamFlushSync does not provide this from another thread.
"""

import logging
import os
import sys
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.workspace_files import EXCLUDED_DIRS

log = logging.getLogger(__name__)

try:
    if sys.platform != "darwin":
        raise ImportError
    import CoreServices as CS
except ImportError:  # Linux, or the optional dependency is missing.
    CS = None

# Beyond this many pending paths a full scan is cheaper than tracking them.
MAX_PENDING = 100_000


def nfc(path):
    return path if path.isascii() else unicodedata.normalize("NFC", path)


@dataclass(frozen=True)
class Sync:
    cursor: int  # Every workspace event up to this ID has been delivered.
    paths: frozenset  # Relative NFC paths with events (files and directories).
    complete: bool  # False when events were lost since the last full scan.
    reset: int

    @property
    def quiet(self):
        """No event since the last saved snapshot could change its contents."""
        return self.complete and not self.paths


class FSEventsWatcher:
    def __init__(self, root: Path, marks: Path, since=None, device=None):
        self.root = nfc(os.path.realpath(root))
        self.marks = os.path.realpath(marks)
        self.device = CS.CFUUIDCreateString(
            None, CS.FSEventsCopyUUIDForDevice(os.stat(root).st_dev)
        )
        # Resume from a persisted cursor only on the same event database.
        resumed = since is not None and device == self.device
        self.base = since if resumed else CS.FSEventsGetCurrentEventId()
        self.lock = threading.Lock()
        self.pending = {}
        self.awaiting, self.seen_marks = set(), {}
        self.history = threading.Event()
        self.mark_arrived = threading.Condition(self.lock)
        # A watcher starting without history must be primed by a full scan.
        self.resets = 0 if resumed else 1
        self.cleared = 0
        self.stream = self.loop = None
        self.started = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="fsevents")
        self.thread.start()
        if not self.started.wait(10) or self.stream is None:
            raise OSError("Could not start file events")

    @classmethod
    def create(cls, root, marks, since=None, device=None):
        """Return a watcher, or None where file events cannot be trusted."""
        if CS is None:
            return None
        marks.mkdir(parents=True, exist_ok=True)
        try:
            # The barrier only orders events within one volume's history.
            if os.stat(root).st_dev != os.stat(marks).st_dev:
                return None
            if CS.FSEventsCopyUUIDForDevice(os.stat(root).st_dev) is None:
                return None  # No persistent event history (e.g. network volumes).
            return cls(root, marks, since, device)
        except Exception as error:
            log.warning("File events unavailable for %s: %s", root, error)
            return None

    def _run(self):
        try:
            flags = (
                CS.kFSEventStreamCreateFlagFileEvents | CS.kFSEventStreamCreateFlagNoDefer
                | CS.kFSEventStreamCreateFlagUseCFTypes | CS.kFSEventStreamCreateFlagWatchRoot
            )
            self.stream = CS.FSEventStreamCreate(
                None, self._callback, None, [self.root, self.marks], self.base, 0.02, flags,
            )
            self.loop = CS.CFRunLoopGetCurrent()
            CS.FSEventStreamScheduleWithRunLoop(self.stream, self.loop, CS.kCFRunLoopDefaultMode)
            if not CS.FSEventStreamStart(self.stream):
                raise OSError("FSEventStreamStart failed")
        except Exception as error:
            log.warning("File events failed for %s: %s", self.root, error)
            self.stream = None
            self.started.set()
            return
        self.started.set()
        CS.CFRunLoopRun()
        CS.FSEventStreamStop(self.stream)
        CS.FSEventStreamInvalidate(self.stream)
        CS.FSEventStreamRelease(self.stream)

    LOST = 0
    if CS is not None:
        LOST = (
            CS.kFSEventStreamEventFlagMustScanSubDirs | CS.kFSEventStreamEventFlagUserDropped
            | CS.kFSEventStreamEventFlagKernelDropped | CS.kFSEventStreamEventFlagEventIdsWrapped
            | CS.kFSEventStreamEventFlagRootChanged
        )
        DIRECTORY_ENTRY = (
            CS.kFSEventStreamEventFlagItemCreated | CS.kFSEventStreamEventFlagItemRemoved
            | CS.kFSEventStreamEventFlagItemRenamed
        )

    def _callback(self, stream, info, count, paths, flags, ids):
        with self.lock:
            for path, flag, event in zip(paths, flags, ids, strict=True):
                if flag & CS.kFSEventStreamEventFlagHistoryDone:
                    self.history.set()
                    continue
                if flag & self.LOST:
                    self.resets += 1
                    self.pending.clear()
                    continue
                path = str(path)
                if os.path.dirname(path) == self.marks:
                    if os.path.basename(path) in self.awaiting:
                        self.seen_marks[os.path.basename(path)] = event
                        self.mark_arrived.notify_all()
                    continue
                path = nfc(path)
                if not path.startswith(self.root + "/"):
                    continue  # The root itself: directory mtimes only.
                relative = path[len(self.root) + 1:]
                if EXCLUDED_DIRS.intersection(relative.split("/")):
                    continue  # Never selected.
                if flag & CS.kFSEventStreamEventFlagItemIsDir and not flag & self.DIRECTORY_ENTRY:
                    continue  # Directory mtime changes; entries have their own events.
                self.pending[relative] = max(event, self.pending.get(relative, 0))
            if len(self.pending) > MAX_PENDING:
                self.resets += 1
                self.pending.clear()

    def sync(self, timeout=30):
        """Wait until all events so far are delivered, or return None."""
        if not self.thread.is_alive() or not self.history.wait(timeout):
            return None
        name = uuid.uuid4().hex
        mark = os.path.join(self.marks, name)
        with self.lock:
            self.awaiting.add(name)
        try:
            with open(mark, "w"):
                pass
            with self.lock:
                if not self.mark_arrived.wait_for(lambda: name in self.seen_marks, timeout):
                    return None
                return Sync(
                    cursor=self.seen_marks[name], paths=frozenset(self.pending),
                    complete=self.resets == self.cleared, reset=self.resets,
                )
        finally:
            with self.lock:
                self.awaiting.discard(name)
                self.seen_marks.pop(name, None)
            Path(mark).unlink(missing_ok=True)

    def commit(self, sync, *, full):
        """Forget events reflected in a saved snapshot."""
        with self.lock:
            for path in sync.paths:
                if self.pending.get(path, sync.cursor + 1) <= sync.cursor:
                    del self.pending[path]
            if full:
                self.cleared = max(self.cleared, sync.reset)

    def close(self):
        # Stopping before CFRunLoopRun starts is a no-op, so retry briefly.
        for _ in range(50):
            if not self.thread.is_alive():
                return
            CS.CFRunLoopStop(self.loop)
            self.thread.join(0.1)
