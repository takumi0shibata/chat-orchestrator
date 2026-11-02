import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from test_api import app_client  # noqa: F401 - isolated API fixture


def test_failed_attachment_batch_keeps_only_existing_uploads(app_client):
    http, work, _ = app_client
    store = http.app.state.store
    cid = store.create_conversation("work")["id"]
    original = work / "original.txt"
    original.write_text("user data")
    http.app.state.manager.settings.max_upload_bytes = 8
    files = [("files", ("same.txt", b"keep", "text/plain"))]
    existing = http.post("/api/attachments", data={"conversation_id": cid}, files=files).json()[0]
    retained = Path(store.attachment(existing["id"], cid)["path"])
    response = http.post("/api/attachments", data={"conversation_id": cid}, files=[
        *files, ("files", ("large.txt", b"too many bytes", "text/plain")),
    ])
    assert response.status_code == 400
    with store.connect() as connection:
        assert [row["id"] for row in connection.execute("SELECT id FROM attachments")] == [existing["id"]]
    assert [p for p in (store.root / "attachments").rglob("*") if p.is_file()] == [retained]
    assert retained.read_bytes() == b"keep" and original.read_text() == "user data"
    retry = http.post("/api/attachments", data={"conversation_id": cid}, files=files * 2)
    assert retry.status_code == 200 and len(retry.json()) == 2
    assert retained.read_bytes() == b"keep"


@pytest.mark.parametrize("phase,error", [
    ("read", OSError), ("read", asyncio.CancelledError),
    ("close", OSError), ("close", asyncio.CancelledError),
])
def test_batch_rolls_back_on_read_or_close_failure(tmp_path, phase, error):
    from app.attachments import save_uploads
    from app.storage import Store

    class BrokenUpload(UploadFile):
        async def read(self, size=-1):
            if phase == "read":
                raise error("isolated upload failure")
            return await super().read(size)

        async def close(self):
            await super().close()
            if phase == "close":
                raise error("isolated close failure")

    async def scenario():
        store = Store(tmp_path / "data")
        cid = store.create_conversation("work")["id"]
        existing = (await save_uploads(store, cid, [UploadFile(BytesIO(b"keep"), filename="same.txt")], 100))[0]
        retained = Path(store.attachment(existing["id"], cid)["path"])
        with pytest.raises(error):
            await save_uploads(store, cid, [
                UploadFile(BytesIO(b"new"), filename="same.txt"),
                BrokenUpload(BytesIO(b"bad"), filename="broken.txt"),
            ], 100)
        with store.connect() as connection:
            assert [row["id"] for row in connection.execute("SELECT id FROM attachments")] == [existing["id"]]
        assert [p for p in (store.root / "attachments").rglob("*") if p.is_file()] == [retained]
        assert retained.read_bytes() == b"keep"
    asyncio.run(scenario())


def test_batch_rolls_back_partial_database_insert(tmp_path, monkeypatch):
    import sqlite3
    from app.attachments import save_uploads
    from app.storage import Store

    async def scenario():
        store = Store(tmp_path / "data")
        cid = store.create_conversation("work")["id"]
        existing = (await save_uploads(store, cid, [UploadFile(BytesIO(b"keep"), filename="same.txt")], 100))[0]
        retained = Path(store.attachment(existing["id"], cid)["path"])
        register = store.add_attachments

        def conflict(attachments):
            register([attachments[0], {**attachments[1], "id": attachments[0]["id"]}])

        monkeypatch.setattr(store, "add_attachments", conflict)
        with pytest.raises(sqlite3.IntegrityError):
            await save_uploads(store, cid, [
                UploadFile(BytesIO(b"new"), filename="same.txt"),
                UploadFile(BytesIO(b"more"), filename="second.txt"),
            ], 100)
        with store.connect() as connection:
            assert [row["id"] for row in connection.execute("SELECT id FROM attachments")] == [existing["id"]]
        assert [p for p in (store.root / "attachments").rglob("*") if p.is_file()] == [retained]
        assert retained.read_bytes() == b"keep"
    asyncio.run(scenario())
