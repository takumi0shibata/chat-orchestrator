import asyncio
import json
import sqlite3

import pytest

from app.conversation_updates import conversation_snapshots
from app.storage import Store


def snapshot(frame):
    assert frame.startswith("retry: 3000\nevent: snapshot\ndata: ")
    assert frame.endswith("\n\n")
    return json.loads(frame.split("data: ", 1)[1])


def test_committed_mutations_notify_but_token_events_and_failed_writes_do_not(tmp_path):
    async def scenario():
        store = Store(tmp_path)
        with store.conversation_updates.subscribe() as changed:
            async def notified():
                await asyncio.wait_for(changed.wait(), timeout=1)
                changed.clear()

            cid = store.create_conversation("work")["id"]
            await notified()
            rid = store.create_run({"conversation_id": cid})["id"]
            await notified()
            store.status(rid, "approval_wait", "Waiting for approval")
            await notified()
            assert store.conversations()[0]["active_run"]["status"] == "approval_wait"
            store.event(rid, "text_delta", {"text": "token"})
            with pytest.raises(sqlite3.IntegrityError):
                store.create_run({"conversation_id": cid})
            await asyncio.sleep(0)
            assert not changed.is_set()
            store.save_context(cid, [], "openai", "test", rid=rid)
            await notified()
            store.finish_title(cid, "New title")
            await notified()
            store.pin_conversation(cid, True)
            await notified()
            store.status(rid, "completed", "Finished")
            await notified()
            assert store.conversation(cid)["has_unread"]
            store.mark_conversation_read(cid, rid)
            await notified()
            assert not store.conversation(cid)["has_unread"]
            store.mark_conversation_read(cid, rid)
            await asyncio.sleep(0)
            assert not changed.is_set()
            store.delete_conversation(cid)
            await notified()
            assert store.conversations() == []
        assert not store.conversation_updates._listeners

    asyncio.run(scenario())


def test_idle_stream_only_sends_heartbeats_and_coalesces_changes(tmp_path, monkeypatch):
    async def scenario():
        store = Store(tmp_path)
        reads = 0
        original = store.conversations

        def counted():
            nonlocal reads
            reads += 1
            return original()

        monkeypatch.setattr(store, "conversations", counted)
        stream = conversation_snapshots(store, heartbeat_seconds=0.01)
        assert snapshot(await anext(stream)) == []
        assert await anext(stream) == ": keep-alive\n\n"
        assert await anext(stream) == ": keep-alive\n\n"
        assert reads == 1
        # No unbounded per-client event queue: a burst becomes one fresh snapshot.
        for _ in range(5):
            store.create_conversation("work")
        await asyncio.sleep(0)
        assert len(snapshot(await anext(stream))) == 5
        assert reads == 2
        assert await anext(stream) == ": keep-alive\n\n"
        assert reads == 2
        await stream.aclose()
        assert not store.conversation_updates._listeners

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["completed", "failed", "stopped"])
def test_threads_broadcast_to_all_clients_and_reconnect_restores_state(tmp_path, status):
    async def scenario():
        store = Store(tmp_path)
        cid = store.create_conversation("work")["id"]
        rid = store.create_run({"conversation_id": cid})["id"]
        streams = [conversation_snapshots(store), conversation_snapshots(store)]
        for stream in streams:
            assert snapshot(await anext(stream))[0]["active_run"]["id"] == rid
        await asyncio.to_thread(store.status, rid, status, "Finished")
        for stream in streams:
            result = snapshot(await asyncio.wait_for(anext(stream), timeout=1))[0]
            assert result["active_run"] is None
            assert result["has_unread"]
            assert result["latest_finished_run"] == {"id": rid, "status": status}
            await stream.aclose()
        # A new process/hub needs no replay cursor: the first frame is authoritative.
        restarted = Store(tmp_path)
        restarted.mark_conversation_read(cid, rid)
        reconnected = conversation_snapshots(restarted)
        assert not snapshot(await anext(reconnected))[0]["has_unread"]
        await reconnected.aclose()

    asyncio.run(scenario())


def test_change_during_snapshot_is_not_lost_and_disconnect_removes_listener(tmp_path, monkeypatch):
    async def scenario():
        store = Store(tmp_path)
        original = store.conversations

        def racing_read():
            rows = original()
            store.create_conversation("work")
            monkeypatch.setattr(store, "conversations", original)
            return rows

        monkeypatch.setattr(store, "conversations", racing_read)
        stream = conversation_snapshots(store)
        assert snapshot(await anext(stream)) == []
        assert len(snapshot(await asyncio.wait_for(anext(stream), timeout=1))) == 1
        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert not store.conversation_updates._listeners

    asyncio.run(scenario())
