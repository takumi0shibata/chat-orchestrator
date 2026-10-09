import asyncio
import hashlib
import os

import pytest

from app import text_files
from test_api import app_client


@pytest.mark.parametrize("extension", ["md", "txt", "toml", "yaml", "yml", "json", "csv", "py"])
def test_text_file_read_save_and_conflict(app_client, extension):
    http, work, _ = app_client
    (work / "notes").mkdir()
    path = f"notes/日本語 draft.{extension}"
    target = work / path
    target.write_text("original\n", encoding="utf-8")
    target.chmod(0o754)
    cid = http.post("/api/conversations", json={"workspace_id": "work"}).json()["id"]
    endpoint = f"/api/conversations/{cid}/file"
    response = http.get(endpoint, params={"path": path})
    assert response.status_code == 200
    original = response.json()
    assert original["content"] == "original\n"
    assert original["revision"] == hashlib.sha256(b"original\n").hexdigest()
    saved = http.put(endpoint, params={"path": path}, json={"content": "更新\n", "revision": original["revision"]})
    assert saved.status_code == 200
    assert saved.json()["content"] == "更新\n"
    assert saved.json()["revision"] != original["revision"]
    assert target.read_bytes() == "更新\n".encode()
    assert target.stat().st_mode & 0o777 == 0o754
    conflict = http.put(endpoint, params={"path": path}, json={"content": "stale", "revision": original["revision"]})
    assert conflict.status_code == 409
    assert target.read_text() == "更新\n"
    emptied = http.put(endpoint, params={"path": path}, json={"content": "", "revision": saved.json()["revision"]})
    assert emptied.status_code == 200
    assert target.read_bytes() == b""
    assert not list(target.parent.glob(".editor-*.tmp"))


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_editor_preserves_encoding_and_newlines(tmp_path, newline, bom):
    path = tmp_path / "note.txt"
    path.write_bytes(bom + f"one{newline}two{newline}".encode())
    original = text_files.read_text_file(tmp_path, path.name)
    assert original["content"] == "one\ntwo\n"
    saved = text_files.save_text_file(tmp_path, path.name, "変更\nsecond\n", original["revision"])
    assert path.read_bytes() == bom + f"変更{newline}second{newline}".encode()
    assert saved["content"] == "変更\nsecond\n"


def test_editor_rejects_invalid_paths_and_content(app_client):
    http, work, _ = app_client
    outside = work.parent / "outside.txt"
    outside.write_text("private")
    (work / "link.txt").symlink_to(outside)
    (work / "linked-dir").symlink_to(work.parent, target_is_directory=True)
    (work / "directory.txt").mkdir()
    os.mkfifo(work / "pipe.txt")
    (work / "binary.txt").write_bytes(b"a\x00b")
    (work / "shiftjis.txt").write_bytes("日本語".encode("shift_jis"))
    (work / "large.txt").write_bytes(b"x" * (text_files.MAX_TEXT_BYTES + 1))
    (work / "office.docx").write_bytes(b"ascii is still not a text document")
    (work / "report.pdf").write_bytes(b"%PDF-1.4")
    cid = http.post("/api/conversations", json={"workspace_id": "work"}).json()["id"]
    endpoint = f"/api/conversations/{cid}/file"
    for path in ("../outside.txt", str(outside), "link.txt", "linked-dir/outside.txt", "directory.txt", "pipe.txt", "missing.txt", "binary.txt", "shiftjis.txt", "large.txt", "office.docx", "report.pdf", "", "..\\outside.txt"):
        assert http.get(endpoint, params={"path": path}).status_code == 400, path
        assert http.put(endpoint, params={"path": path}, json={"content": "overwrite", "revision": "0" * 64}).status_code == 400, path
    assert outside.read_text() == "private"
    assert not (work / "missing.txt").exists()
    assert http.get("/api/conversations/missing/file", params={"path": "note.txt"}).status_code == 404


def test_save_validates_new_content_and_blocks_active_workspace(app_client):
    http, work, _ = app_client
    target = work / "note.txt"
    target.write_text("original")
    cid = http.post("/api/conversations", json={"workspace_id": "work"}).json()["id"]
    endpoint = f"/api/conversations/{cid}/file?path=note.txt"
    revision = http.get(endpoint).json()["revision"]
    for content in ("x\x00y", "あ" * (text_files.MAX_TEXT_BYTES // 3 + 1)):
        assert http.put(endpoint, json={"content": content, "revision": revision}).status_code == 400
        assert target.read_text() == "original"
    assert http.put(endpoint, json={"content": "changed"}).status_code == 422
    lock = http.app.state.manager.locks.setdefault(str(work), asyncio.Lock())
    http.portal.call(lock.acquire)
    try:
        assert http.get(endpoint).status_code == 200
        blocked = http.put(endpoint, json={"content": "changed", "revision": revision})
        assert blocked.status_code == 409
        assert "workspace is busy" in blocked.json()["detail"]
        assert target.read_text() == "original"
    finally:
        http.portal.call(lock.release)
    assert http.put(endpoint, json={"content": "changed", "revision": revision}).status_code == 200


def test_save_failure_preserves_original_and_removes_temp(tmp_path, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_text("original")
    original = text_files.read_text_file(tmp_path, target.name)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(text_files.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        text_files.save_text_file(tmp_path, target.name, "changed", original["revision"])
    assert target.read_text() == "original"
    assert list(tmp_path.iterdir()) == [target]


def test_save_detects_external_change_during_write(tmp_path, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_text("original")
    original = text_files.read_text_file(tmp_path, target.name)
    monkeypatch.setattr(text_files.os, "fsync", lambda _: target.write_text("external edit"))
    with pytest.raises(text_files.FileChanged):
        text_files.save_text_file(tmp_path, target.name, "changed", original["revision"])
    assert target.read_text() == "external edit"
    assert list(tmp_path.iterdir()) == [target]
