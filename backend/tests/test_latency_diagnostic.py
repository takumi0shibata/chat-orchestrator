import importlib.util
import json
from pathlib import Path

from app.storage import Store


def test_latency_report_is_read_only_and_omits_content(tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts/diagnose_latency.py"
    spec = importlib.util.spec_from_file_location("diagnose_latency", path)
    diagnostic = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diagnostic)
    assert diagnostic.recent_runs(tmp_path / "absent.db") == []
    assert not (tmp_path / "absent.db").exists()
    store = Store(tmp_path / "data")
    conversation = store.create_conversation("work")
    run = store.create_run(dict(conversation_id=conversation["id"], input="PRIVATE_PROMPT"))
    rows = [
        ("status", {"status": "preparing", "label": "Waiting for workspace availability"}, 0),
        ("status", {"status": "preparing", "label": "Starting sandbox"}, 12),
        ("round", {"number": 1}, 15),
        ("text_delta", {"text": "PRIVATE_RESPONSE"}, 17),
        ("text_delta", {"text": "MORE_PRIVATE_RESPONSE"}, 18),
        ("response", {"continues": False}, 20),
        ("artifacts", {"files": [{"path": "PRIVATE_FILENAME"}]}, 33),
        ("status", {"status": "completed", "label": "PRIVATE_LABEL"}, 34),
    ]
    with store.connect() as db:
        db.execute("UPDATE runs SET created_at=? WHERE id=?", ("2026-10-09T00:00:00+00:00", run["id"]))
        db.execute("DELETE FROM events WHERE run_id=?", (run["id"],))
        db.executemany("INSERT INTO events VALUES(?,?,?,?,?)", [
            (run["id"], i + 1, kind, json.dumps(data), f"2026-10-09T00:00:{seconds:02d}+00:00")
            for i, (kind, data, seconds) in enumerate(rows)
        ])
    before = store.events(run["id"])
    report = diagnostic.recent_runs(store.db)
    assert store.events(run["id"]) == before
    assert "PRIVATE" not in json.dumps(report)
    assert report[0]["checkpoint_events"] == 0
    phases = {r["phase"]: r["since_previous_seconds"] for r in report[0]["timeline"]}
    assert phases["sandbox_start"] == 12
    assert phases["first_model_output"] == 2
    assert phases["sandbox_close_and_scan_after_done"] == 13
    store.event(run["id"], "workspace_scan", dict(
        name="after", duration_ms=4077, files=347246, private="PRIVATE_SCAN_FIELD",
    ))
    measured = diagnostic.recent_runs(store.db)[0]["timeline"][-1]
    assert measured["phase"] == "workspace_scan_after_done"
    assert measured["duration_ms"] == 4077 and measured["files"] == 347246
    assert "PRIVATE" not in json.dumps(measured)
