import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.chat_service import ChatOrchestrator
from app.main import app, state
from app.schemas import ChatMessage
from app.skills_runtime.base import CardItem, CardListBlock, CardSection, FeedbackAction, FeedbackChoice
from app.storage import ChatStore


class EmptySkills:
    def get(self, skill_id: str):
        del skill_id
        return None

    def list_skills(self):
        return []


def _set_temp_store(tmp_path: Path) -> None:
    state.store = ChatStore(db_path=tmp_path / "chat-test.db")
    state.chat = ChatOrchestrator(store=state.store, skills=EmptySkills())


def test_generic_feedback_api_accepts_unknown_run_and_item_if_conversation_exists() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            _set_temp_store(Path(tmp))
            conversation_id = state.store.create_conversation()

            response = client.post(
                "/api/skill-feedback",
                json={
                    "conversation_id": conversation_id,
                    "run_id": "run-unknown",
                    "item_id": "item-unknown",
                    "decision": "acted",
                    "note": "start review",
                },
            )
            assert response.status_code == 200
            assert response.json() == {"ok": True}


def test_audit_feedback_api_rejects_invalid_decision() -> None:
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

            state.store.record_feedback_targets(
                conversation_id=conversation_id,
                run_id="run-1",
                item_ids=["a1", "a2", "a3"],
            )
            state.store.add_feedback(
                conversation_id=conversation_id,
                run_id="run-1",
                item_id="a1",
                decision="acted",
                note=None,
            )
            state.store.add_feedback(
                conversation_id=conversation_id,
                run_id="run-1",
                item_id="a2",
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


def test_persisted_messages_restore_selected_feedback_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _set_temp_store(Path(tmp))
        conversation_id = state.store.create_conversation()

        state.store.add_message(
            conversation_id,
            ChatMessage(
                role="assistant",
                content="feedback test",
                skill_id="audit_news_action_brief",
                artifacts=[
                    CardListBlock(
                        title="監査アクションニュース",
                        sections=[
                            CardSection(
                                id="self_company",
                                title="自社",
                                items=[
                                    CardItem(
                                        id="item-1",
                                        title="Item 1",
                                        actions=[
                                            FeedbackAction(
                                                run_id="run-1",
                                                item_id="item-1",
                                                choices=[FeedbackChoice(value="acted", label="対応する")],
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            ),
        )
        state.store.add_feedback(
            conversation_id=conversation_id,
            run_id="run-1",
            item_id="item-1",
            decision="acted",
            note=None,
        )

        messages = state.store.get_messages(conversation_id)
        action = messages[0].artifacts[0].sections[0].items[0].actions[0]
        assert action.selected == "acted"
