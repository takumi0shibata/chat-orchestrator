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


async def _fake_generate_hypotheses(self, *, parsed, provider_id, model):
    del self, parsed, provider_id, model
    return {
        "self_company": ["原材料高騰が粗利を圧迫", "減損兆候の再評価が必要"],
        "peer_companies": ["競合の供給障害が価格へ波及"],
        "macro": ["為替変動が輸入コストを押し上げ", "会計基準の改定"]
    }


async def _fake_collect_with_noise(self, *, parsed, hypotheses, provider_id, model):
    del self, parsed, hypotheses, provider_id, model
    now = datetime.now(UTC)
    return [
        NewsCandidate(
            title="A食品、原材料高で通期見通しを下方修正",
            url="https://www.nikkei.com/article/afoods-forecast",
            source="NIKKEI",
            published_at=now - timedelta(days=1),
            summary="原材料価格上昇で利益率悪化が見込まれる。",
            one_liner_comment="在庫評価と引当前提の見直しが必要。",
            propagation_note="利益計画下振れで減損兆候の感応度再計算が必要。",
            view="self_company",
            macro_subtype=None,
        ),
        NewsCandidate(
            title="Bフーズ、主力工場の稼働停止",
            url="https://www.reuters.com/world/japan/bfoods-stop",
            source="Reuters",
            published_at=now - timedelta(days=1),
            summary="同業の生産停止で供給と価格に影響。",
            one_liner_comment="調達価格前提の更新が必要。",
            propagation_note="需給逼迫で原価率が上昇する可能性。",
            view="peer_companies",
            macro_subtype=None,
        ),
        NewsCandidate(
            title="Bフーズ、主力工場の稼働停止",
            url="https://www.reuters.com/world/japan/bfoods-stop?utm=dup",
            source="Reuters",
            published_at=now - timedelta(days=1),
            summary="重複ニュース。",
            one_liner_comment="重複。",
            propagation_note="重複。",
            view="peer_companies",
            macro_subtype=None,
        ),
        NewsCandidate(
            title="日銀の政策修正で円相場が変動",
            url="https://www.bloomberg.com/news/yen-vol",
            source="Bloomberg",
            published_at=now - timedelta(days=2),
            summary="為替ボラティリティ上昇。",
            one_liner_comment="輸入原価見積りの再評価を要確認。",
            propagation_note="為替前提の変更が予算と在庫評価へ波及。",
            view="macro",
            macro_subtype="fx",
        ),
        NewsCandidate(
            title="監査基準委、開示制度の改定案を公表",
            url="https://www.fsa.go.jp/news/audit-guidance",
            source="金融庁",
            published_at=now - timedelta(days=3),
            summary="開示および内部統制評価の要求を強化。",
            one_liner_comment="注記・内部統制手続の差分確認が必要。",
            propagation_note="開示要件変更に伴い監査計画の追加手続が必要。",
            view="macro",
            macro_subtype="regulation",
        ),
        NewsCandidate(
            title="古いニュース",
            url="https://example.com/old-news",
            source="Example",
            published_at=now - timedelta(days=20),
            summary="期間外。",
            one_liner_comment="期間外。",
            propagation_note="期間外。",
            view="macro",
            macro_subtype="market",
        ),
    ]


async def _fake_collect_many(self, *, parsed, hypotheses, provider_id, model):
    del self, parsed, hypotheses, provider_id, model
    now = datetime.now(UTC)
    rows: list[NewsCandidate] = []
    for i in range(10):
        rows.append(
            NewsCandidate(
                title=f"自社ニュース {i}",
                url=f"https://example.com/self/{i}",
                source="Example",
                published_at=now - timedelta(days=1),
                summary="自社関連ニュース。",
                one_liner_comment="コメント。",
                propagation_note="波及。",
                view="self_company",
                macro_subtype=None,
            )
        )
        rows.append(
            NewsCandidate(
                title=f"他社ニュース {i}",
                url=f"https://example.com/peer/{i}",
                source="Example",
                published_at=now - timedelta(days=1),
                summary="他社関連ニュース。",
                one_liner_comment="コメント。",
                propagation_note="波及。",
                view="peer_companies",
                macro_subtype=None,
            )
        )
        rows.append(
            NewsCandidate(
                title=f"マクロニュース {i}",
                url=f"https://example.com/macro/{i}",
                source="Example",
                published_at=now - timedelta(days=1),
                summary="マクロ関連ニュース。",
                one_liner_comment="コメント。",
                propagation_note="波及。",
                view="macro",
                macro_subtype="market",
            )
        )
    return rows


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


def test_skill_outputs_v2_views_and_filters_noise() -> None:
    skill = AuditNewsActionBriefSkill()
    skill._parse_request = types.MethodType(_fake_parse_ok, skill)
    skill._generate_hypotheses = types.MethodType(_fake_generate_hypotheses, skill)
    skill._collect_news_candidates = types.MethodType(_fake_collect_with_noise, skill)

    output = asyncio.run(
        skill.run(
            user_text="A食品株式会社の監査ニュース",
            history=[],
            skill_context={"provider_id": "openai", "model": "gpt-5.2-2025-12-11"},
        )
    )

    payload = _extract_payload(output)
    assert payload["schema"] == "audit_news_action_brief/v2"
    assert set(payload["views"].keys()) == {"self_company", "peer_companies", "macro"}
    assert "## 自社" in output
    assert "## 他社" in output
    assert "## マクロ" in output
    assert "古いニュース" not in output

    total = sum(len(payload["views"][key]) for key in ("self_company", "peer_companies", "macro"))
    assert total >= 4

    news_ids = []
    for key in ("self_company", "peer_companies", "macro"):
        for row in payload["views"][key]:
            assert isinstance(row["news_id"], str)
            assert isinstance(row["title"], str)
            assert isinstance(row["summary"], str)
            assert isinstance(row["one_liner_comment"], str)
            assert isinstance(row["propagation_note"], str)
            assert isinstance(row["score"], int)
            news_ids.append(row["news_id"])
    assert len(news_ids) == len(set(news_ids))


def test_skill_caps_total_items_near_target_range() -> None:
    skill = AuditNewsActionBriefSkill()
    skill._parse_request = types.MethodType(_fake_parse_ok, skill)
    skill._generate_hypotheses = types.MethodType(_fake_generate_hypotheses, skill)
    skill._collect_news_candidates = types.MethodType(_fake_collect_many, skill)

    output = asyncio.run(
        skill.run(
            user_text="A食品株式会社の監査ニュース",
            history=[],
            skill_context={"provider_id": "openai", "model": "gpt-5.2-2025-12-11"},
        )
    )
    payload = _extract_payload(output)
    total = sum(len(payload["views"][key]) for key in ("self_company", "peer_companies", "macro"))
    assert total <= 24
