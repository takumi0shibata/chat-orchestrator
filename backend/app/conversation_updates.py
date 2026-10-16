"""Wake sidebar subscribers after committed changes, without polling SQLite."""

import asyncio
import json
import threading
from contextlib import contextmanager


class ConversationUpdates:
    def __init__(self):
        self._listeners = {}
        self._lock = threading.Lock()

    @contextmanager
    def subscribe(self):
        changed = asyncio.Event()
        with self._lock:
            self._listeners[changed] = asyncio.get_running_loop()
        try:
            yield changed
        finally:
            with self._lock:
                self._listeners.pop(changed, None)

    def publish(self):
        # Store mutations may run in worker threads as well as the ASGI loop.
        with self._lock:
            listeners = list(self._listeners.items())
        for changed, loop in listeners:
            try:
                loop.call_soon_threadsafe(changed.set)
            except RuntimeError:
                # A disconnected subscriber's event loop may already be closed.
                pass


async def conversation_snapshots(store, heartbeat_seconds=20):
    # Register before reading, so a commit during the initial snapshot is not lost.
    # Every connection gets a fresh snapshot, including after server restarts.
    with store.conversation_updates.subscribe() as changed:
        while True:
            changed.clear()
            yield "retry: 3000\nevent: snapshot\ndata: " + json.dumps(store.conversations(), ensure_ascii=False) + "\n\n"
            while True:
                try:
                    await asyncio.wait_for(changed.wait(), timeout=heartbeat_seconds)
                    break
                except asyncio.TimeoutError:
                    # Keep the connection alive; no database access when idle.
                    yield ": keep-alive\n\n"
