import asyncio
import json
import sys
import tempfile
import types
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.chat_service import ChatOrchestrator
from app.main import app, state
from app.skills_runtime.base import Skill
from app.storage import ChatStore

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from skills.docx_auto_commenter.skill import DocxAutoCommenterSkill  # noqa: E402


class FakeProvider:
    def __init__(self) -> None:
        self.chat_calls = 0
        self.stream_calls = 0

    async def chat(self, **kwargs):
        del kwargs
        self.chat_calls += 1
        return "assistant result"

    async def stream_chat(self, **kwargs):
        del kwargs
        self.stream_calls += 1
        yield "assistant result"


class FakeProviders:
    def __init__(self, provider):
        self.provider = provider

    def get(self, provider_id: str):
        assert provider_id == "openai"
        return self.provider


class FakeSkills:
    def __init__(self, skill: Skill):
        self.skill = skill

    def get(self, skill_id: str):
        if skill_id == self.skill.metadata.id:
            return self.skill
        return None

    def list_skills(self):
        return [self.skill]


def _minimal_docx_bytes(*paragraphs: str) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for text in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr/></w:body>"
        "</w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )

    with tempfile.NamedTemporaryFile(suffix=".docx") as handle:
        with ZipFile(handle.name, "w") as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", package_rels)
            archive.writestr("word/document.xml", document_xml)
            archive.writestr("word/_rels/document.xml.rels", document_rels)
        return Path(handle.name).read_bytes()


def _write_attachment_files(
    tmp_path: Path,
    conversation_id: str,
    attachment_id: str,
    *,
    parsed_text: str | None = None,
) -> tuple[Path, Path]:
    attachment_dir = tmp_path / "attachments" / conversation_id / attachment_id
    attachment_dir.mkdir(parents=True, exist_ok=True)
    docx_path = attachment_dir / "original.docx"
    parsed_path = attachment_dir / "parsed.md"
    docx_path.write_bytes(_minimal_docx_bytes("This sentence is unclear.", "Second paragraph stays the same."))
    parsed_path.write_text(
        parsed_text or "This sentence is unclear.\n\nSecond paragraph stays the same.",
        encoding="utf-8",
    )
    return docx_path, parsed_path


def _set_state(tmp_path: Path, *, skill: Skill) -> FakeProvider:
    provider = FakeProvider()
    state.store = ChatStore(
        db_path=tmp_path / "chat-test.db",
        attachments_root=tmp_path / "attachments",
        generated_files_root=tmp_path / "generated_files",
    )
    state.providers = FakeProviders(provider)
    state.skills = FakeSkills(skill)
    state.chat = ChatOrchestrator(store=state.store, skills=state.skills)
    return provider


def test_skill_requires_openai_responses_model() -> None:
    skill = DocxAutoCommenterSkill()
    result = asyncio.run(
        skill.run(
            user_text="読みやすくしてください",
            history=[],
            skill_context={"provider_id": "google", "model": "gemini-2.5-flash", "attachments": []},
        )
    )
    assert "OpenAI / Azure OpenAI" in result.llm_context
    assert result.artifacts[0].type == "markdown"


def test_skill_generates_commented_docx(tmp_path: Path) -> None:
    skill = DocxAutoCommenterSkill()

    async def _fake_plan(self, *, provider_id, model, source_name, review_brief, review_source):
        del self, provider_id, model, source_name, review_brief, review_source
        return [
            {
                "quote": "This sentence is unclear.",
                "issue": "Meaning is vague.",
                "revision_goal": "Clarify the subject.",
                "category": "clarity",
                "priority": "high",
            }
        ]

    async def _fake_finalize(self, *, provider_id, model, source_name, review_brief, review_source, planned_candidates):
        del self, provider_id, model, source_name, review_brief, review_source, planned_candidates
        return [
            {
                "quote": "This sentence is unclear.",
                "comment": "主語が曖昧なので、誰が何をしたのかを明示してください。",
                "category": "clarity",
                "priority": "high",
            }
        ]

    skill._plan_review_candidates = types.MethodType(_fake_plan, skill)
    skill._finalize_review_candidates = types.MethodType(_fake_finalize, skill)

    conversation_id = "conv-1"
    attachment_id = "att-1"
    docx_path, parsed_path = _write_attachment_files(tmp_path, conversation_id, attachment_id)
    result = asyncio.run(
        skill.run(
            user_text="曖昧な表現を直したいです",
            history=[],
            skill_context={
                "provider_id": "openai",
                "model": "gpt-5.4-2026-03-05",
                "conversation_id": conversation_id,
                "generated_files_root": str(tmp_path / "generated_files"),
                "attachments": [
                    {
                        "id": attachment_id,
                        "name": "draft.docx",
                        "original_path": str(docx_path),
                        "parsed_markdown_path": str(parsed_path),
                    }
                ],
            },
        )
    )

    assert len(result.generated_files) == 1
    assert result.assistant_response == "レビューコメントを適用したDOCXを生成しました。適用1件 / スキップ0件。ダウンロードしてください。"
    assert result.options.skip_model_response is True
    generated = result.generated_files[0]
    assert Path(generated.path).exists()
    block = result.artifacts[0]
    assert block.type == "card_list"
    assert block.sections[0].items[0].links[0].url == f"/api/generated-files/{generated.id}/download"

    with ZipFile(generated.path) as archive:
        comments_xml = archive.read("word/comments.xml").decode("utf-8")
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "主語が曖昧なので" in comments_xml
    assert "commentRangeStart" in document_xml
    assert "commentReference" in document_xml


def test_skill_skips_unmatched_quotes_and_does_not_generate_file(tmp_path: Path) -> None:
    skill = DocxAutoCommenterSkill()

    async def _fake_plan(self, *, provider_id, model, source_name, review_brief, review_source):
        del self, provider_id, model, source_name, review_brief, review_source
        return [{"quote": "Missing quote", "issue": "x", "revision_goal": "y", "category": "clarity", "priority": "high"}]

    async def _fake_finalize(self, *, provider_id, model, source_name, review_brief, review_source, planned_candidates):
        del self, provider_id, model, source_name, review_brief, review_source, planned_candidates
        return [{"quote": "Missing quote", "comment": "この表現を修正してください。", "category": "clarity", "priority": "high"}]

    skill._plan_review_candidates = types.MethodType(_fake_plan, skill)
    skill._finalize_review_candidates = types.MethodType(_fake_finalize, skill)

    conversation_id = "conv-2"
    attachment_id = "att-2"
    docx_path, parsed_path = _write_attachment_files(tmp_path, conversation_id, attachment_id)
    result = asyncio.run(
        skill.run(
            user_text="修正",
            history=[],
            skill_context={
                "provider_id": "openai",
                "model": "gpt-5.4-2026-03-05",
                "conversation_id": conversation_id,
                "generated_files_root": str(tmp_path / "generated_files"),
                "attachments": [
                    {
                        "id": attachment_id,
                        "name": "draft.docx",
                        "original_path": str(docx_path),
                        "parsed_markdown_path": str(parsed_path),
                    }
                ],
            },
        )
    )

    assert result.generated_files == []
    assert "本文マッピング失敗" in result.assistant_response
    assert result.options.skip_model_response is True


def test_finalize_falls_back_to_planned_candidates() -> None:
    skill = DocxAutoCommenterSkill()
    planned = [
        {
            "quote": "This sentence is unclear.",
            "issue": "Meaning is vague.",
            "revision_goal": "Clarify the subject.",
            "category": "clarity",
            "priority": "high",
        }
    ]

    finalized = skill._fallback_finalize_candidates(planned)

    assert finalized == [
        {
            "quote": "This sentence is unclear.",
            "comment": "Meaning is vague. Clarify the subject.",
            "category": "clarity",
            "priority": "high",
        }
    ]


def test_extract_candidate_rows_accepts_object_wrapped_list() -> None:
    skill = DocxAutoCommenterSkill()
    rows = skill._extract_candidate_rows(
        '{"comments":[{"quote":"This sentence is unclear.","comment":"Clarify it.","category":"clarity","priority":"high"}]}',
        preferred_keys=("comments", "items"),
    )

    assert rows == [
        {
            "quote": "This sentence is unclear.",
            "comment": "Clarify it.",
            "category": "clarity",
            "priority": "high",
        }
    ]


def test_normalize_review_brief_ignores_filename_lines() -> None:
    skill = DocxAutoCommenterSkill()
    review_brief = skill._normalize_review_brief(
        user_text="添付ファイルの論理構成，日本語の完成度を厳しくレビューして\n\n2025_研究指導計画書.docx",
        source_name="2025_研究指導計画書.docx",
    )

    assert review_brief == "添付ファイルの論理構成，日本語の完成度を厳しくレビューして"


def test_skill_prefers_docx_body_over_placeholder_markdown(tmp_path: Path) -> None:
    skill = DocxAutoCommenterSkill()
    captured: dict[str, str] = {}

    async def _fake_plan(self, *, provider_id, model, source_name, review_brief, review_source):
        del self, provider_id, model, source_name, review_brief
        captured["review_source"] = review_source
        return [
            {
                "quote": "This sentence is unclear.",
                "issue": "Meaning is vague.",
                "revision_goal": "Clarify the subject.",
                "category": "clarity",
                "priority": "high",
            }
        ]

    async def _fake_finalize(self, *, provider_id, model, source_name, review_brief, review_source, planned_candidates):
        del self, provider_id, model, source_name, review_brief, review_source, planned_candidates
        return [
            {
                "quote": "This sentence is unclear.",
                "comment": "主語と意図を具体化してください。",
                "category": "clarity",
                "priority": "high",
            }
        ]

    skill._plan_review_candidates = types.MethodType(_fake_plan, skill)
    skill._finalize_review_candidates = types.MethodType(_fake_finalize, skill)

    conversation_id = "conv-placeholder"
    attachment_id = "att-placeholder"
    docx_path, parsed_path = _write_attachment_files(
        tmp_path,
        conversation_id,
        attachment_id,
        parsed_text="[No extractable text in draft.docx]",
    )
    result = asyncio.run(
        skill.run(
            user_text="論理構成と日本語の完成度を厳しくレビューして",
            history=[],
            skill_context={
                "provider_id": "openai",
                "model": "gpt-5.4-2026-03-05",
                "conversation_id": conversation_id,
                "generated_files_root": str(tmp_path / "generated_files"),
                "attachments": [
                    {
                        "id": attachment_id,
                        "name": "draft.docx",
                        "original_path": str(docx_path),
                        "parsed_markdown_path": str(parsed_path),
                    }
                ],
            },
        )
    )

    assert "[No extractable text" not in captured["review_source"]
    assert "This sentence is unclear." in captured["review_source"]
    assert len(result.generated_files) == 1


def test_skill_uses_direct_review_when_plan_is_empty(tmp_path: Path) -> None:
    skill = DocxAutoCommenterSkill()

    async def _fake_plan(self, *, provider_id, model, source_name, review_brief, review_source):
        del self, provider_id, model, source_name, review_brief, review_source
        return []

    async def _fake_direct(self, *, provider_id, model, source_name, review_brief, review_source):
        del self, provider_id, model, source_name, review_brief, review_source
        return [
            {
                "quote": "This sentence is unclear.",
                "comment": "この文は意味が曖昧なので、主語と意図を具体化してください。",
                "category": "clarity",
                "priority": "high",
            }
        ]

    skill._plan_review_candidates = types.MethodType(_fake_plan, skill)
    skill._direct_review_candidates = types.MethodType(_fake_direct, skill)

    conversation_id = "conv-direct"
    attachment_id = "att-direct"
    docx_path, parsed_path = _write_attachment_files(tmp_path, conversation_id, attachment_id)
    result = asyncio.run(
        skill.run(
            user_text="厳しめにレビュー",
            history=[],
            skill_context={
                "provider_id": "openai",
                "model": "gpt-5.4-2026-03-05",
                "conversation_id": conversation_id,
                "generated_files_root": str(tmp_path / "generated_files"),
                "attachments": [
                    {
                        "id": attachment_id,
                        "name": "draft.docx",
                        "original_path": str(docx_path),
                        "parsed_markdown_path": str(parsed_path),
                    }
                ],
            },
        )
    )

    assert len(result.generated_files) == 1


def test_chat_api_persists_generated_file_and_downloads_it(tmp_path: Path) -> None:
    skill = DocxAutoCommenterSkill()

    async def _fake_plan(self, *, provider_id, model, source_name, review_brief, review_source):
        del self, provider_id, model, source_name, review_brief, review_source
        return [{"quote": "This sentence is unclear.", "issue": "x", "revision_goal": "y", "category": "clarity", "priority": "high"}]

    async def _fake_finalize(self, *, provider_id, model, source_name, review_brief, review_source, planned_candidates):
        del self, provider_id, model, source_name, review_brief, review_source, planned_candidates
        return [{"quote": "This sentence is unclear.", "comment": "具体的な主語を追記してください。", "category": "clarity", "priority": "high"}]

    skill._plan_review_candidates = types.MethodType(_fake_plan, skill)
    skill._finalize_review_candidates = types.MethodType(_fake_finalize, skill)

    with TestClient(app) as client:
        provider = _set_state(tmp_path, skill=skill)
        conversation_id = state.store.create_conversation()
        attachment_id = "att-3"
        docx_path, parsed_path = _write_attachment_files(tmp_path, conversation_id, attachment_id)
        state.store.add_attachment(
            attachment_id=attachment_id,
            conversation_id=conversation_id,
            name="draft.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=docx_path.stat().st_size,
            original_path=str(docx_path),
            parsed_markdown_path=str(parsed_path),
        )

        response = client.post(
            "/api/chat",
            json={
                "provider_id": "openai",
                "model": "gpt-5.4-2026-03-05",
                "conversation_id": conversation_id,
                "user_input": "曖昧さを直してください",
                "attachment_ids": [attachment_id],
                "skill_id": skill.metadata.id,
            },
        )
        assert response.status_code == 200
        assert response.json()["output"] == "レビューコメントを適用したDOCXを生成しました。適用1件 / スキップ0件。ダウンロードしてください。"
        message = response.json()["message"]
        assert message["content"] == "レビューコメントを適用したDOCXを生成しました。適用1件 / スキップ0件。ダウンロードしてください。"
        link = message["artifacts"][0]["sections"][0]["items"][0]["links"][0]["url"]
        download = client.get(link)
        assert download.status_code == 200
        assert download.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert download.headers["content-disposition"].endswith('.commented.docx"')

        generated_files = state.store.list_generated_files(conversation_id=conversation_id)
        assert len(generated_files) == 1
        assert Path(generated_files[0].path).exists()
        assert provider.chat_calls == 0
        assert provider.stream_calls == 0


def test_stream_chat_uses_skill_response_without_provider_call(tmp_path: Path) -> None:
    skill = DocxAutoCommenterSkill()

    async def _fake_plan(self, *, provider_id, model, source_name, review_brief, review_source):
        del self, provider_id, model, source_name, review_brief, review_source
        return [{"quote": "This sentence is unclear.", "issue": "x", "revision_goal": "y", "category": "clarity", "priority": "high"}]

    async def _fake_finalize(self, *, provider_id, model, source_name, review_brief, review_source, planned_candidates):
        del self, provider_id, model, source_name, review_brief, review_source, planned_candidates
        return [{"quote": "This sentence is unclear.", "comment": "具体的な主語を追記してください。", "category": "clarity", "priority": "high"}]

    skill._plan_review_candidates = types.MethodType(_fake_plan, skill)
    skill._finalize_review_candidates = types.MethodType(_fake_finalize, skill)

    with TestClient(app) as client:
        provider = _set_state(tmp_path, skill=skill)
        conversation_id = state.store.create_conversation()
        attachment_id = "att-4"
        docx_path, parsed_path = _write_attachment_files(tmp_path, conversation_id, attachment_id)
        state.store.add_attachment(
            attachment_id=attachment_id,
            conversation_id=conversation_id,
            name="draft.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=docx_path.stat().st_size,
            original_path=str(docx_path),
            parsed_markdown_path=str(parsed_path),
        )

        response = client.post(
            "/api/chat/stream",
            json={
                "provider_id": "openai",
                "model": "gpt-5.4-2026-03-05",
                "conversation_id": conversation_id,
                "user_input": "2025_研究指導計画書.docx\n論理構成と日本語の完成度を厳しくレビューして",
                "attachment_ids": [attachment_id],
                "skill_id": skill.metadata.id,
            },
        )
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.strip().splitlines()]
        assert [event["type"] for event in events] == ["skill_status", "skill_status", "done"]
        assert events[-1]["message"]["content"] == "レビューコメントを適用したDOCXを生成しました。適用1件 / スキップ0件。ダウンロードしてください。"
        assert provider.chat_calls == 0
        assert provider.stream_calls == 0
