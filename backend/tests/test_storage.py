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
