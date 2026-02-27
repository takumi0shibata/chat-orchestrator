import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, state
from app.storage import ChatStore


def _set_temp_store(tmp_path: Path) -> None:
    state.store = ChatStore(db_path=tmp_path / "chat-test.db")


def test_feedback_api_accepts_unknown_run_and_alert_if_conversation_exists() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            _set_temp_store(Path(tmp))
            conversation_id = state.store.create_conversation()

            response = client.post(
                "/api/skills/audit_news_action_brief/feedback",
                json={
                    "conversation_id": conversation_id,
                    "run_id": "run-unknown",
                    "alert_id": "alert-unknown",
                    "decision": "acted",
                    "note": "start review",
                },
            )
            assert response.status_code == 200
            assert response.json() == {"ok": True}


def test_feedback_api_rejects_invalid_decision() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            _set_temp_store(Path(tmp))
            conversation_id = state.store.create_conversation()

            response = client.post(
                "/api/skills/audit_news_action_brief/feedback",
                json={
                    "conversation_id": conversation_id,
                    "run_id": "run-1",
                    "alert_id": "alert-1",
                    "decision": "invalid",
                },
            )
            assert response.status_code == 400


def test_metrics_api_returns_expected_aggregates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            _set_temp_store(Path(tmp))
            conversation_id = state.store.create_conversation()

            state.store.record_skill_alerts(
                conversation_id=conversation_id,
                run_id="run-1",
                alert_ids=["a1", "a2", "a3"],
            )
            state.store.add_skill_feedback(
                conversation_id=conversation_id,
                run_id="run-1",
                alert_id="a1",
                decision="acted",
                note=None,
            )
            state.store.add_skill_feedback(
                conversation_id=conversation_id,
                run_id="run-1",
                alert_id="a2",
                decision="monitor",
                note=None,
            )

            response = client.get("/api/skills/audit_news_action_brief/metrics")
            assert response.status_code == 200
            payload = response.json()
            assert payload["total_alerts"] == 3
            assert payload["total_feedback"] == 2
            assert payload["acted_count"] == 1
            assert abs(payload["action_rate"] - (1 / 3)) < 1e-3
