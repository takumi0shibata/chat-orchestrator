from pathlib import Path

from fastapi.testclient import TestClient

from app.chat_service import ChatOrchestrator
from app.main import app, state
from app.skills_runtime.base import Skill, SkillCategory, SkillExecutionResult, SkillMetadata, context_only_result
from app.storage import ChatStore


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs["messages"])
        return "assistant result"

    async def stream_chat(self, **kwargs):
        self.calls.append(kwargs["messages"])
        yield "assistant result"


class FakeProviders:
    def __init__(self, provider):
        self.provider = provider

    def get(self, provider_id: str):
        assert provider_id == "openai"
        return self.provider


class AttachmentAwareSkill(Skill):
    metadata = SkillMetadata(
        id="attachment_skill",
        name="Attachment Skill",
        description="Reads attachments from skill_context",
        primary_category=SkillCategory(id="general", label="General"),
        tags=["general", "attachment"],
    )

    def __init__(self) -> None:
        self.captured_contexts: list[dict] = []

    async def run(self, user_text: str, history: list[dict[str, str]], skill_context=None):
        del user_text, history
        self.captured_contexts.append(skill_context or {})
        return context_only_result("")


class FakeSkills:
    def __init__(self, skill: Skill):
        self.skill = skill

    def get(self, skill_id: str):
        if skill_id == self.skill.metadata.id:
            return self.skill
        return None

    def list_skills(self):
        return [self.skill]


def _set_state(tmp_path: Path, *, skill: Skill | None = None) -> RecordingProvider:
    provider = RecordingProvider()
    state.store = ChatStore(
        db_path=tmp_path / "chat-test.db",
        attachments_root=tmp_path / "attachments",
    )
    state.providers = FakeProviders(provider)
    active_skill = skill or AttachmentAwareSkill()
    state.skills = FakeSkills(active_skill)
    state.chat = ChatOrchestrator(store=state.store, skills=state.skills)
    return provider


def _upload_attachment(client: TestClient, conversation_id: str, *, name: str, content: bytes) -> dict:
    response = client.post(
        "/api/attachments/extract",
        data={"conversation_id": conversation_id},
        files=[("files", (name, content, "text/plain"))],
    )
    assert response.status_code == 200
    payload = response.json()["files"]
    assert len(payload) == 1
    return payload[0]


def _chat_payload(conversation_id: str, *, user_input: str, attachment_ids: list[str], skill_id: str | None = None) -> dict:
    return {
        "provider_id": "openai",
        "model": "gpt-4o-mini",
        "conversation_id": conversation_id,
        "user_input": user_input,
        "attachment_ids": attachment_ids,
        "skill_id": skill_id,
    }


def test_attachment_upload_persists_file_and_hides_extracted_body(tmp_path: Path) -> None:
    with TestClient(app) as client:
        _set_state(tmp_path)
        conversation_id = state.store.create_conversation()

        attachment = _upload_attachment(client, conversation_id, name="brief.txt", content=b"hello attachment")
        assert attachment == {
            "id": attachment["id"],
            "name": "brief.txt",
            "content_type": "text/plain",
            "size_bytes": 16,
        }

        stored = state.store.get_attachments(conversation_id=conversation_id, attachment_ids=[attachment["id"]])
        assert len(stored) == 1
        assert Path(stored[0].original_path).read_bytes() == b"hello attachment"
        assert Path(stored[0].parsed_markdown_path).read_text(encoding="utf-8") == "hello attachment"


def test_normal_chat_injects_attachment_context_without_persisting_body(tmp_path: Path) -> None:
    with TestClient(app) as client:
        provider = _set_state(tmp_path)
        conversation_id = state.store.create_conversation()
        attachment = _upload_attachment(client, conversation_id, name="notes.txt", content=b"attachment body")

        response = client.post(
            "/api/chat",
            json=_chat_payload(conversation_id, user_input="Summarize this", attachment_ids=[attachment["id"]]),
        )
        assert response.status_code == 200

        assert len(provider.calls) == 1
        messages = provider.calls[0]
        assert messages[0].role == "system"
        assert "attachment body" in messages[0].content
        assert messages[-1].role == "user"
        assert messages[-1].content == "Summarize this"

        history = client.get(f"/api/conversations/{conversation_id}/messages")
        assert history.status_code == 200
        user_message = history.json()[0]
        assert user_message["content"] == "Summarize this"
        assert user_message["attachments"] == [attachment]
        assert "attachment body" not in user_message["content"]


def test_skill_chat_uses_attachment_descriptors_without_double_injection(tmp_path: Path) -> None:
    skill = AttachmentAwareSkill()
    with TestClient(app) as client:
        provider = _set_state(tmp_path, skill=skill)
        conversation_id = state.store.create_conversation()
        attachment = _upload_attachment(client, conversation_id, name="paper.txt", content=b"skill attachment body")

        response = client.post(
            "/api/chat",
            json=_chat_payload(
                conversation_id,
                user_input="",
                attachment_ids=[attachment["id"]],
                skill_id=skill.metadata.id,
            ),
        )
        assert response.status_code == 200

        assert len(skill.captured_contexts) == 1
        context = skill.captured_contexts[0]
        descriptors = context["attachments"]
        assert len(descriptors) == 1
        descriptor = descriptors[0]
        assert Path(descriptor["original_path"]).read_bytes() == b"skill attachment body"
        assert Path(descriptor["parsed_markdown_path"]).read_text(encoding="utf-8") == "skill attachment body"

        sent_messages = provider.calls[0]
        assert all("skill attachment body" not in message.content for message in sent_messages)


def test_attachment_only_chat_uses_attachment_name_for_title(tmp_path: Path) -> None:
    with TestClient(app) as client:
        _set_state(tmp_path)
        conversation_id = state.store.create_conversation()
        attachment = _upload_attachment(client, conversation_id, name="report.txt", content=b"report body")

        response = client.post(
            "/api/chat",
            json=_chat_payload(conversation_id, user_input="", attachment_ids=[attachment["id"]]),
        )
        assert response.status_code == 200

        conversations = client.get("/api/conversations")
        assert conversations.status_code == 200
        by_id = {item["id"]: item for item in conversations.json()}
        assert by_id[conversation_id]["title"] == "report.txt"

        history = client.get(f"/api/conversations/{conversation_id}/messages")
        assert history.status_code == 200
        user_message = history.json()[0]
        assert user_message["content"] == ""
        assert user_message["attachments"] == [attachment]
