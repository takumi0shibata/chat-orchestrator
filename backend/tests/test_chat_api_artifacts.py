import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.chat_service import ChatOrchestrator
from app.main import app, state
from app.skills_runtime.base import LineChartBlock, LineChartPoint, SkillCategory, SkillExecutionResult, SkillMetadata
from app.storage import ChatStore


class FakeProvider:
    async def chat(self, **kwargs):
        del kwargs
        return "assistant result"

    async def stream_chat(self, **kwargs):
        del kwargs
        yield "assistant "
        yield "result"


class FakeProviders:
    def __init__(self, provider):
        self.provider = provider

    def get(self, provider_id: str):
        assert provider_id == "openai"
        return self.provider


class FakeSkill:
    metadata = SkillMetadata(
        id="chart_skill",
        name="Chart Skill",
        description="Returns a chart artifact",
        primary_category=SkillCategory(id="general", label="General"),
        tags=["general", "chart"],
    )

    async def run(self, user_text: str, history: list[dict[str, str]], skill_context=None):
        del user_text, history, skill_context
        return SkillExecutionResult(
            llm_context="Skill context",
            artifacts=[
                LineChartBlock(
                    title="Series",
                    frequency="M",
                    points=[
                        LineChartPoint(time="2026-01", value=1.0, raw="1.0"),
                        LineChartPoint(time="2026-02", value=2.0, raw="2.0"),
                    ],
                )
            ],
        )


class FakeSkills:
    def __init__(self, skill):
        self.skill = skill

    def get(self, skill_id: str):
        if skill_id == self.skill.metadata.id:
            return self.skill
        return None

    def list_skills(self):
        return [self.skill]


def _set_state(tmp_path: Path) -> None:
    state.store = ChatStore(db_path=tmp_path / "chat-test.db")
    state.providers = FakeProviders(FakeProvider())
    state.skills = FakeSkills(FakeSkill())
    state.chat = ChatOrchestrator(store=state.store, skills=state.skills)


def _chat_payload(conversation_id: str) -> dict:
    return {
        "provider_id": "openai",
        "model": "gpt-4o-mini",
        "conversation_id": conversation_id,
        "user_input": "show me the series",
        "skill_id": "chart_skill",
    }


def test_chat_and_stream_return_equivalent_message_payloads() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            _set_state(Path(tmp))
            conversation_id = state.store.create_conversation()

            sync_response = client.post("/api/chat", json=_chat_payload(conversation_id))
            assert sync_response.status_code == 200
            sync_message = sync_response.json()["message"]
            assert sync_message["artifacts"][0]["type"] == "line_chart"

            stream_response = client.post("/api/chat/stream", json=_chat_payload(conversation_id))
            assert stream_response.status_code == 200
            events = [json.loads(line) for line in stream_response.text.strip().splitlines()]
            done_event = next(event for event in events if event["type"] == "done")
            assert done_event["message"] == sync_message


def test_chat_messages_endpoint_returns_persisted_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            _set_state(Path(tmp))
            conversation_id = state.store.create_conversation()

            response = client.post("/api/chat", json=_chat_payload(conversation_id))
            assert response.status_code == 200

            messages_response = client.get(f"/api/conversations/{conversation_id}/messages")
            assert messages_response.status_code == 200
            assistant_message = messages_response.json()[-1]
            assert assistant_message["content"] == "assistant result"
            assert assistant_message["artifacts"][0]["type"] == "line_chart"
