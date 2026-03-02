import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import _register_audit_news_alerts, app, state
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


def test_registers_v2_news_ids_for_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app):
            _set_temp_store(Path(tmp))
            conversation_id = state.store.create_conversation()
            skill_output = (
                "監査アクションニュースブリーフ\\n"
                "```audit-news-json\\n"
                "{"
                "\"schema\":\"audit_news_action_brief/v2\","
                "\"run_id\":\"run-v2\","
                "\"generated_at\":\"2026-01-01T00:00:00+00:00\","
                "\"client\":{\"name\":\"A食品\",\"industry\":\"食品\",\"lookback_days\":7,\"focus_topics\":[],\"watch_competitors\":[]},"
                "\"views\":{"
                "\"self_company\":[{\"news_id\":\"n1\",\"title\":\"t1\",\"summary\":\"s\",\"url\":\"u\",\"one_liner_comment\":\"c\",\"source\":\"x\",\"published_at\":\"2026-01-01T00:00:00+00:00\",\"view\":\"self_company\",\"propagation_note\":\"p\",\"score\":80}],"
                "\"peer_companies\":[{\"news_id\":\"n2\",\"title\":\"t2\",\"summary\":\"s\",\"url\":\"u2\",\"one_liner_comment\":\"c\",\"source\":\"x\",\"published_at\":\"2026-01-01T00:00:00+00:00\",\"view\":\"peer_companies\",\"propagation_note\":\"p\",\"score\":70}],"
                "\"macro\":[]"
                "}"
                "}"
                "\\n```"
            )
            _register_audit_news_alerts(
                conversation_id=conversation_id,
                skill_id="audit_news_action_brief",
                skill_output=skill_output,
            )

            metrics = state.store.audit_news_metrics(date_from=None, date_to=None)
            assert metrics["total_alerts"] == 2
