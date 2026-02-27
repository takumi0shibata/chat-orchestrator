import asyncio
import json
import re
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from skills.audit_news_action_brief.skill import (  # noqa: E402
    AuditNewsActionBriefSkill,
    NewsCandidate,
    ParsedRequest,
)


async def _fake_parse_ok(self, *, user_text, provider_id, model):
    del self, user_text, provider_id, model
    return ParsedRequest(
        client_name="A食品株式会社",
        client_industry="食品",
        watch_competitors=["Bフーズ"],
        lookback_days=7,
        focus_topics=["原材料価格"],
    )


async def _fake_collect_with_noise(self, *, parsed, provider_id, model):
    del self, parsed, provider_id, model
    now = datetime.now(UTC)
    return [
        NewsCandidate(
            title="Bフーズ、主力工場の稼働停止",
            url="https://www.reuters.com/world/japan/bfoods-stop",
            source="Reuters",
            published_at=now - timedelta(days=1),
            snippet="同業の生産停止で供給と価格に影響が出る可能性。",
            category="competitor",
        ),
        NewsCandidate(
            title="Bフーズ、主力工場の稼働停止",
            url="https://www.reuters.com/world/japan/bfoods-stop?utm=dup",
            source="Reuters",
            published_at=now - timedelta(days=1),
            snippet="重複ニュース。",
            category="competitor",
        ),
        NewsCandidate(
            title="食品向け原材料価格が急騰",
            url="https://www.nikkei.com/article/macro-1",
            source="NIKKEI",
            published_at=now - timedelta(days=2),
            snippet="原材料コスト上昇が利益率を圧迫。",
            category="macro",
        ),
        NewsCandidate(
            title="会計監査に関する新ガイダンス",
            url="https://www.fsa.go.jp/news/audit-guidance",
            source="金融庁",
            published_at=now - timedelta(days=3),
            snippet="内部統制評価と注記確認に影響。",
            category="regulatory",
        ),
        NewsCandidate(
            title="古いニュース",
            url="https://example.com/old-news",
            source="Example",
            published_at=now - timedelta(days=14),
            snippet="期間外。",
            category="macro",
        ),
        NewsCandidate(
            title="為替ボラティリティ上昇",
            url="https://www.bloomberg.com/news/yen-vol",
            source="Bloomberg",
            published_at=now - timedelta(days=1),
            snippet="輸入原材料の評価影響が見込まれる。",
            category="macro",
        ),
        NewsCandidate(
            title="同業が大型リコール発表",
            url="https://www.jpx.co.jp/disclosure/recall",
            source="JPX",
            published_at=now - timedelta(days=1),
            snippet="品質コスト見積りと引当の妥当性に影響。",
            category="competitor",
        ),
    ]


def _extract_payload(output: str) -> dict:
    match = re.search(r"```audit-news-json\s*\n([\s\S]*?)```", output)
    assert match is not None
    return json.loads(match.group(1))


def test_skill_requires_openai_responses_model() -> None:
    skill = AuditNewsActionBriefSkill()
    output = asyncio.run(
        skill.run(
            user_text="A食品の監査ニュース",
            history=[],
            skill_context={"provider_id": "google", "model": "gemini-2.5-flash"},
        )
    )
    assert "OpenAI Responses API" in output


def test_skill_prompts_for_missing_required_fields() -> None:
    skill = AuditNewsActionBriefSkill()

    async def _fake_parse_missing(self, *, user_text, provider_id, model):
        del self, user_text, provider_id, model
        return ParsedRequest(client_name=None, client_industry=None, watch_competitors=[], lookback_days=7, focus_topics=[])

    skill._parse_request = types.MethodType(_fake_parse_missing, skill)

    output = asyncio.run(
        skill.run(
            user_text="今週の監査ニュース",
            history=[],
            skill_context={"provider_id": "openai", "model": "gpt-5.2-2025-12-11"},
        )
    )

    assert "不足情報" in output
    assert "監査クライアント名" in output
    assert "監査クライアントの業種" in output


def test_skill_filters_old_dedupes_and_limits_to_top_alerts() -> None:
    skill = AuditNewsActionBriefSkill()
    skill._parse_request = types.MethodType(_fake_parse_ok, skill)
    skill._collect_news_candidates = types.MethodType(_fake_collect_with_noise, skill)

    output = asyncio.run(
        skill.run(
            user_text="A食品株式会社の監査ニュース",
            history=[],
            skill_context={"provider_id": "openai", "model": "gpt-5.2-2025-12-11"},
        )
    )

    payload = _extract_payload(output)
    alerts = payload["alerts"]

    assert payload["schema"] == "audit_news_action_brief/v1"
    assert len(alerts) <= 5
    assert "古いニュース" not in output

    scores = [int(row["score"]) for row in alerts]
    assert scores == sorted(scores, reverse=True)

    alert_ids = [row["alert_id"] for row in alerts]
    assert len(alert_ids) == len(set(alert_ids))
