from pathlib import Path

from fastapi.testclient import TestClient

from app.chat_service import ChatOrchestrator
from app.main import app, state
from app.skills_runtime.base import Skill, SkillCategory, SkillExecutionResult, SkillMetadata, context_only_result
from app.storage import ChatStore


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return "assistant result"

    async def stream_chat(self, **kwargs):
        self.calls.append(kwargs)
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


def _upload_attachment(
    client: TestClient,
    conversation_id: str,
    *,
    name: str,
    content: bytes,
    content_type: str,
) -> dict:
    response = client.post(
        "/api/attachments/extract",
        data={"conversation_id": conversation_id},
        files=[("files", (name, content, content_type))],
    )
    assert response.status_code == 200
    payload = response.json()["files"]
    assert len(payload) == 1
    return payload[0]


def _chat_payload(
    conversation_id: str,
    *,
    user_input: str,
    attachment_ids: list[str],
    skill_id: str | None = None,
    model: str = "gpt-4o-mini",
) -> dict:
    return {
        "provider_id": "openai",
        "model": model,
        "conversation_id": conversation_id,
        "user_input": user_input,
        "attachment_ids": attachment_ids,
        "skill_id": skill_id,
    }


def test_attachment_upload_persists_file_and_hides_extracted_body(tmp_path: Path) -> None:
    with TestClient(app) as client:
        _set_state(tmp_path)
        conversation_id = state.store.create_conversation()

        attachment = _upload_attachment(
            client,
            conversation_id,
            name="brief.txt",
            content=b"hello attachment",
            content_type="text/plain",
        )
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


def test_image_upload_persists_file_and_placeholder(tmp_path: Path) -> None:
    with TestClient(app) as client:
        _set_state(tmp_path)
        conversation_id = state.store.create_conversation()

        image = _upload_attachment(
            client,
            conversation_id,
            name="diagram.png",
            content=b"\x89PNG\r\n\x1a\nfake",
            content_type="image/png",
        )

        stored = state.store.get_attachments(conversation_id=conversation_id, attachment_ids=[image["id"]])
        assert len(stored) == 1
        assert Path(stored[0].original_path).read_bytes() == b"\x89PNG\r\n\x1a\nfake"
        assert Path(stored[0].parsed_markdown_path).read_text(encoding="utf-8") == "[Image attachment: diagram.png]"


def test_normal_chat_injects_attachment_context_without_persisting_body(tmp_path: Path) -> None:
    with TestClient(app) as client:
        provider = _set_state(tmp_path)
        conversation_id = state.store.create_conversation()
        attachment = _upload_attachment(
            client,
            conversation_id,
            name="notes.txt",
            content=b"attachment body",
            content_type="text/plain",
        )

        response = client.post(
            "/api/chat",
            json=_chat_payload(conversation_id, user_input="Summarize this", attachment_ids=[attachment["id"]]),
        )
        assert response.status_code == 200

        assert len(provider.calls) == 1
        messages = provider.calls[0]["messages"]
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
        attachment = _upload_attachment(
            client,
            conversation_id,
            name="paper.txt",
            content=b"skill attachment body",
            content_type="text/plain",
        )

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

        sent_messages = provider.calls[0]["messages"]
        assert all("skill attachment body" not in message.content for message in sent_messages)


def test_mixed_chat_injects_only_document_context_and_passes_images_to_provider(tmp_path: Path) -> None:
    with TestClient(app) as client:
        provider = _set_state(tmp_path)
        conversation_id = state.store.create_conversation()
        document = _upload_attachment(
            client,
            conversation_id,
            name="notes.txt",
            content=b"document body",
            content_type="text/plain",
        )
        image = _upload_attachment(
            client,
            conversation_id,
            name="chart.png",
            content=b"\x89PNG\r\n\x1a\nchart",
            content_type="image/png",
        )

        response = client.post(
            "/api/chat",
            json=_chat_payload(
                conversation_id,
                user_input="Describe the uploaded materials",
                attachment_ids=[document["id"], image["id"]],
                model="gpt-5.4-2026-03-05",
            ),
        )
        assert response.status_code == 200

        provider_call = provider.calls[0]
        messages = provider_call["messages"]
        assert messages[0].role == "system"
        assert "document body" in messages[0].content
        assert "[Image attachment:" not in messages[0].content
        assert [attachment.id for attachment in provider_call["attachments"]] == [document["id"], image["id"]]

        history = client.get(f"/api/conversations/{conversation_id}/messages")
        assert history.status_code == 200
        user_message = history.json()[0]
        assert sorted(user_message["attachments"], key=lambda item: item["id"]) == sorted(
            [document, image],
            key=lambda item: item["id"],
        )


def test_image_attachment_requires_image_capable_model(tmp_path: Path) -> None:
    with TestClient(app) as client:
        provider = _set_state(tmp_path)
        conversation_id = state.store.create_conversation()
        image = _upload_attachment(
            client,
            conversation_id,
            name="photo.png",
            content=b"\x89PNG\r\n\x1a\nimage",
            content_type="image/png",
        )

        response = client.post(
            "/api/chat",
            json=_chat_payload(
                conversation_id,
                user_input="What is in this image?",
                attachment_ids=[image["id"]],
            ),
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Model does not support image input: gpt-4o-mini"
        assert provider.calls == []


def test_attachment_only_chat_uses_attachment_name_for_title(tmp_path: Path) -> None:
    with TestClient(app) as client:
        _set_state(tmp_path)
        conversation_id = state.store.create_conversation()
        attachment = _upload_attachment(
            client,
            conversation_id,
            name="report.txt",
            content=b"report body",
            content_type="text/plain",
        )

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
