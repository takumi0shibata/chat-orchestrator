import asyncio
import sys
import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from skills.audit_news_action_brief.skill import AuditNewsActionBriefSkill, NewsItemV3, ParsedRequest  # noqa: E402


async def _fake_parse_ok(self, *, user_text, provider_id, model):
    del self, user_text, provider_id, model
    return ParsedRequest(
        client_name="A食品株式会社",
        client_industry="食品",
        watch_competitors=["Bフーズ"],
        lookback_days=7,
        focus_topics=["原材料価格"],
    )


async def _fake_search_category(self, *, view, parsed, provider_id, model, prior_titles):
    del self, parsed, provider_id, model, prior_titles
    if view == "self_company":
        return [
            NewsItemV3(
                title="A食品、原材料高で通期見通しを下方修正",
                summary="原材料価格上昇で利益率悪化が見込まれる。",
                url="https://example.com/self",
                one_liner_comment="評価前提の見直しが必要。",
                source="NIKKEI",
                published_at="2026-03-01T09:00:00+09:00",
                view=view,
            )
        ]
    if view == "peer_companies":
        return [
            NewsItemV3(
                title="Bフーズ、主力工場の稼働停止",
                summary="供給と価格に影響する可能性。",
                url="https://example.com/peer",
                one_liner_comment="同業リスクとして要確認。",
                source="Reuters",
                published_at="2026-03-02T09:00:00+09:00",
                view=view,
            )
        ]
    return []


def test_skill_requires_openai_responses_model() -> None:
    skill = AuditNewsActionBriefSkill()
    result = asyncio.run(
        skill.run(
            user_text="A食品の監査ニュース",
            history=[],
            skill_context={"provider_id": "google", "model": "gemini-2.5-flash"},
        )
    )
    assert "OpenAI" in result.llm_context
    assert len(result.artifacts) == 1
    assert result.artifacts[0].type == "markdown"


def test_skill_prompts_for_missing_required_fields() -> None:
    skill = AuditNewsActionBriefSkill()

    async def _fake_parse_missing(self, *, user_text, provider_id, model):
        del self, user_text, provider_id, model
        return ParsedRequest(client_name=None, client_industry=None, watch_competitors=[], lookback_days=7, focus_topics=[])

    skill._parse_request = types.MethodType(_fake_parse_missing, skill)
    result = asyncio.run(
        skill.run(
            user_text="今週の監査ニュース",
            history=[],
            skill_context={"provider_id": "openai", "model": "gpt-5.2-2025-12-11"},
        )
    )

    assert "不足情報" in result.llm_context
    assert result.artifacts[0].type == "markdown"


def test_skill_returns_card_list_artifact_and_feedback_targets() -> None:
    skill = AuditNewsActionBriefSkill()
    skill._parse_request = types.MethodType(_fake_parse_ok, skill)
    skill._search_category = types.MethodType(_fake_search_category, skill)

    result = asyncio.run(
        skill.run(
            user_text="A食品株式会社の監査ニュース",
            history=[],
            skill_context={"provider_id": "openai", "model": "gpt-5.2-2025-12-11"},
        )
    )

    assert "## 自社" in result.llm_context
    assert result.options.disable_web_tool is True
    assert len(result.artifacts) == 1
    block = result.artifacts[0]
    assert block.type == "card_list"
    assert [section.id for section in block.sections] == ["self_company", "peer_companies", "macro"]
    assert block.sections[0].items[0].actions[0].type == "feedback"
    assert block.sections[2].items == []
    assert len(result.feedback_targets) == 2
    assert {target.run_id for target in result.feedback_targets} == {result.feedback_targets[0].run_id}
