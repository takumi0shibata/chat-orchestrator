import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.chat_service import ChatOrchestrator
from app.main import app, state
from app.skills_runtime.base import (
    LineChartBlock,
    LineChartPoint,
    MarkdownBlock,
    SkillCategory,
    SkillExecutionOptions,
    SkillExecutionResult,
    SkillMetadata,
    get_skill_progress,
)
from app.storage import ChatStore


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return "assistant result"

    async def stream_chat(self, **kwargs):
        self.calls.append(kwargs)
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
        del user_text, history
        progress = get_skill_progress(skill_context)
        await progress.update(stage="prepare_chart", label="グラフを準備しています")
        await progress.update(stage="prepare_chart", label="グラフを準備しています")
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


class WebDisabledSkill(FakeSkill):
    async def run(self, user_text: str, history: list[dict[str, str]], skill_context=None):
        del user_text, history, skill_context
        return SkillExecutionResult(
            llm_context="Skill context",
            options=SkillExecutionOptions(disable_web_tool=True),
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


class FakeAbilities:
    def resolve(self, *, ability_ids, legacy_skill_id):
        del legacy_skill_id
        assert ability_ids == ["chart_skill"]
        return [object()]

    def list_abilities(self):
        return []


class FakeAgent:
    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "AgentResult",
            (),
            {
                "content": "agentic answer",
                "skill_result": SkillExecutionResult(
                    artifacts=[
                        MarkdownBlock(
                            content="agentic artifact",
                        )
                    ]
                ),
            },
        )()


def _set_state(tmp_path: Path, *, skill=None) -> FakeProvider:
    provider = FakeProvider()
    state.store = ChatStore(db_path=tmp_path / "chat-test.db")
    state.providers = FakeProviders(provider)
    state.skills = FakeSkills(skill or FakeSkill())
    state.abilities = FakeAbilities()
    state.agent = FakeAgent()
    state.chat = ChatOrchestrator(store=state.store, skills=state.skills)
    return provider


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
            skill_events = [event for event in events if event["type"] == "skill_status"]
            assert skill_events == [
                {
                    "type": "skill_status",
                    "status": "running",
                    "skill_id": "chart_skill",
                    "stage": "starting",
                    "label": "準備しています",
                },
                {
                    "type": "skill_status",
                    "status": "running",
                    "skill_id": "chart_skill",
                    "stage": "prepare_chart",
                    "label": "グラフを準備しています",
                },
                {
                    "type": "skill_status",
                    "status": "done",
                    "skill_id": "chart_skill",
                    "stage": "completed",
                    "label": "完了しました",
                },
            ]
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


def test_chat_defaults_web_tool_on_for_openai_responses_model() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            provider = _set_state(Path(tmp))
            conversation_id = state.store.create_conversation()

            response = client.post(
                "/api/chat",
                json={
                    **_chat_payload(conversation_id),
                    "model": "gpt-5.4-2026-03-05",
                    "skill_id": None,
                },
            )
            assert response.status_code == 200
            assert provider.calls[0]["enable_web_tool"] is True


def test_skill_disable_web_tool_overrides_default_on() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            provider = _set_state(Path(tmp), skill=WebDisabledSkill())
            conversation_id = state.store.create_conversation()

            response = client.post(
                "/api/chat",
                json={
                    **_chat_payload(conversation_id),
                    "model": "gpt-5.4-2026-03-05",
                },
            )
            assert response.status_code == 200
            assert provider.calls[0]["enable_web_tool"] is False


def test_chat_agentic_mode_uses_agent_runner_with_ability_alias() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            _set_state(Path(tmp))
            conversation_id = state.store.create_conversation()

            response = client.post(
                "/api/chat",
                json={
                    "provider_id": "openai",
                    "model": "gpt-5.4-2026-03-05",
                    "conversation_id": conversation_id,
                    "user_input": "run agentically",
                    "execution_mode": "agentic",
                    "ability_ids": ["chart_skill"],
                },
            )
            assert response.status_code == 200
            payload = response.json()

            assert payload["output"] == "agentic answer"
            assert payload["message"]["skill_id"] == "agentic"
            assert payload["message"]["artifacts"][0]["type"] == "markdown"
            assert state.agent.calls[0]["provider_id"] == "openai"
            assert state.agent.calls[0]["enable_web_tool"] is True
            assert state.agent.calls[0]["require_ability_use"] is True
