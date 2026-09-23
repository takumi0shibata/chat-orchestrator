import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.storage import Store


def test_connection_commits_and_closes(tmp_path):
    store = Store(tmp_path)
    with store.connect() as connection:
        connection.execute("CREATE TABLE test_values (value TEXT)")
        connection.execute("INSERT INTO test_values VALUES ('saved')")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with store.connect() as reader:
        assert reader.execute("SELECT value FROM test_values").fetchone()[0] == "saved"


def test_connection_rolls_back_and_closes_on_error(tmp_path):
    store = Store(tmp_path)
    with store.connect() as connection:
        connection.execute("CREATE TABLE test_values (value TEXT)")

    with pytest.raises(RuntimeError, match="abort"):
        with store.connect() as connection:
            connection.execute("INSERT INTO test_values VALUES ('discarded')")
            raise RuntimeError("abort")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with store.connect() as reader:
        assert reader.execute("SELECT COUNT(*) FROM test_values").fetchone()[0] == 0


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX file descriptor limits")
def test_repeated_event_polling_does_not_exhaust_file_descriptors(tmp_path):
    # Isolate the descriptor limit and disabled GC from the pytest process.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent("""
                import gc
                import resource
                import sys
                from pathlib import Path
                from app.storage import Store

                store = Store(Path(sys.argv[1]))
                cid = store.create_conversation("work")["id"]
                rid = store.create_run({"conversation_id": cid, "input": "test"})["id"]
                gc.collect()
                gc.disable()
                soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                limit = 128 if soft == resource.RLIM_INFINITY else min(128, soft)
                resource.setrlimit(resource.RLIMIT_NOFILE, (limit, hard))
                for index in range(500):
                    store.event(rid, "message", {"index": index})
                    assert store.run(rid)["status"] == "preparing"
                    assert store.events(rid, after=index + 1)[0]["data"] == {"index": index}
                store.status(rid, "completed", "Done")
                assert store.run(rid)["status"] == "completed"
            """),
            str(tmp_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_history_search_and_pin_persistence(tmp_path):
    store = Store(tmp_path)
    first = store.create_conversation("work")["id"]
    second = store.create_conversation("work")["id"]
    run = store.create_run({"conversation_id": first, "input": "Review PAPER " + "x" * 70 + "本文のみ検索"})
    store.event(run["id"], "text_delta", {"item_id": "a", "text": "日本語の"})
    store.event(run["id"], "text_delta", {"item_id": "a", "text": "添削結果"})
    store.event(run["id"], "command_output", {"text": "output-only-secret"})
    store.event(run["id"], "text_delta", {"item_id": "b", "text": "別の発言"})
    assert [c["id"] for c in store.conversations("語の添削")] == [first]
    assert [c["id"] for c in store.conversations("paper")] == [first]
    assert [c["id"] for c in store.conversations("本文のみ検索")] == [first]
    assert store.conversations("output-only-secret") == []
    assert store.conversations("結果別の") == []
    stamp = store.conversation(second)["updated_at"]
    store.pin_conversation(second, True)
    restored = Store(tmp_path)
    assert restored.conversations()[0]["id"] == second
    assert restored.conversation(second)["pinned"] is True
    assert restored.conversation(second)["updated_at"] == stamp
    restored.pin_conversation(second, False)
    assert restored.conversation(second)["pinned"] is False
    with pytest.raises(KeyError):
        restored.pin_conversation("missing", True)


def test_migrates_existing_history_without_data_loss(tmp_path):
    with sqlite3.connect(tmp_path / "agent.db") as c:
        c.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, workspace_id TEXT, title TEXT, created_at TEXT, updated_at TEXT, context TEXT, provider TEXT, model TEXT)")
        c.execute("INSERT INTO conversations VALUES ('old','work','Existing','2026','2026','[]',NULL,NULL)")
    store = Store(tmp_path)
    assert store.conversations()[0]["title"] == "Existing"
    assert store.conversation("old")["pinned"] is False
    assert store.conversation("old")["title_status"] == "complete"
    assert store.settings()["title_model"] == "gpt-6-luna"
    assert store.monthly_costs()[0]["usd"] == 0
    Store(tmp_path)  # Migration is safe to run again.


def test_existing_title_model_setting_is_preserved(tmp_path):
    store = Store(tmp_path)
    store.update_settings(title_provider="azure_openai", title_model="azure-old-luna")
    assert Store(tmp_path).settings()["title_model"] == "azure-old-luna"
