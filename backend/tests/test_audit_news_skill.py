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


async def _fake_collect_with_noise(self, *, parsed, hypotheses, provider_id, model, cutoff):
    del self, parsed, hypotheses, provider_id, model, cutoff
    now = datetime.now(UTC)
    rows = [
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
    return rows, {
        "raw_counts_by_view": {"self_company": 1, "peer_companies": 2, "macro": 3},
        "supplemental_runs_by_view": {"self_company": 0, "peer_companies": 1, "macro": 0},
        "query_logs_by_view": {
            "self_company": [{"stage": "primary", "query": "self-q", "hits": 1}],
            "peer_companies": [
                {"stage": "primary", "query": "peer-q", "hits": 2},
                {"stage": "supplemental", "query": "peer-sup", "hits": 0},
            ],
            "macro": [{"stage": "primary", "query": "macro-q", "hits": 3}],
        },
    }


async def _fake_collect_many(self, *, parsed, hypotheses, provider_id, model, cutoff):
    del self, parsed, hypotheses, provider_id, model, cutoff
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
    return rows, {
        "raw_counts_by_view": {"self_company": 10, "peer_companies": 10, "macro": 10},
        "supplemental_runs_by_view": {"self_company": 0, "peer_companies": 0, "macro": 0},
        "query_logs_by_view": {
            "self_company": [{"stage": "primary", "query": "self-q", "hits": 10}],
            "peer_companies": [{"stage": "primary", "query": "peer-q", "hits": 10}],
            "macro": [{"stage": "primary", "query": "macro-q", "hits": 10}],
        },
    }


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
    assert "debug_stats" in payload
    assert set(payload["debug_stats"].keys()) == {
        "raw_counts_by_view",
        "deduped_counts_by_view",
        "supplemental_runs_by_view",
        "dropped_duplicates_by_view",
        "query_logs_by_view",
    }

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
    assert all(len(payload["views"][key]) >= 2 for key in ("self_company", "peer_companies", "macro"))


def test_filter_dedupe_keeps_same_article_across_views() -> None:
    skill = AuditNewsActionBriefSkill()
    now = datetime.now(UTC)
    rows = [
        NewsCandidate(
            title="同一ニュース",
            url="https://example.com/shared",
            source="Example",
            published_at=now,
            summary="s",
            one_liner_comment="c",
            propagation_note="p",
            view="self_company",
            macro_subtype=None,
        ),
        NewsCandidate(
            title="同一ニュース",
            url="https://example.com/shared",
            source="Example",
            published_at=now,
            summary="s",
            one_liner_comment="c",
            propagation_note="p",
            view="macro",
            macro_subtype="market",
        ),
    ]
    filtered, _, dropped_dup, dropped_dup_by_view = skill._filter_and_dedupe(
        candidates=rows,
        cutoff=now - timedelta(days=1),
    )
    assert len(filtered) == 2
    assert dropped_dup == 0
    assert dropped_dup_by_view == {"self_company": 0, "peer_companies": 0, "macro": 0}


def test_collect_candidates_runs_supplemental_for_missing_view() -> None:
    skill = AuditNewsActionBriefSkill()

    def _fake_primary_queries(self, *, parsed, hypotheses):
        del self, parsed, hypotheses
        return {
            "self_company": ["self-q"],
            "peer_companies": ["peer-q"],
            "macro": ["macro-q"],
        }

    def _fake_supplemental_queries(self, *, parsed, hypotheses, view):
        del self, parsed, hypotheses
        if view == "peer_companies":
            return ["peer-sup"]
        return [f"{view}-sup"]

    async def _fake_search(self, *, view, query, parsed, provider_id, model, max_items):
        del self, parsed, provider_id, model, max_items
        now = datetime.now(UTC)
        if query == "self-q":
            return [
                NewsCandidate(
                    title="self-1",
                    url="https://example.com/self-1",
                    source="Example",
                    published_at=now,
                    summary="s",
                    one_liner_comment="c",
                    propagation_note="p",
                    view=view,
                    macro_subtype=None,
                ),
                NewsCandidate(
                    title="self-2",
                    url="https://example.com/self-2",
                    source="Example",
                    published_at=now,
                    summary="s",
                    one_liner_comment="c",
                    propagation_note="p",
                    view=view,
                    macro_subtype=None,
                ),
            ]
        if query == "macro-q":
            return [
                NewsCandidate(
                    title="macro-1",
                    url="https://example.com/macro-1",
                    source="Example",
                    published_at=now,
                    summary="s",
                    one_liner_comment="c",
                    propagation_note="p",
                    view=view,
                    macro_subtype="market",
                ),
                NewsCandidate(
                    title="macro-2",
                    url="https://example.com/macro-2",
                    source="Example",
                    published_at=now,
                    summary="s",
                    one_liner_comment="c",
                    propagation_note="p",
                    view=view,
                    macro_subtype="market",
                ),
            ]
        if query == "peer-sup":
            return [
                NewsCandidate(
                    title="peer-1",
                    url="https://example.com/peer-1",
                    source="Example",
                    published_at=now,
                    summary="s",
                    one_liner_comment="c",
                    propagation_note="p",
                    view=view,
                    macro_subtype=None,
                ),
                NewsCandidate(
                    title="peer-2",
                    url="https://example.com/peer-2",
                    source="Example",
                    published_at=now,
                    summary="s",
                    one_liner_comment="c",
                    propagation_note="p",
                    view=view,
                    macro_subtype=None,
                ),
            ]
        return []

    skill._build_primary_queries = types.MethodType(_fake_primary_queries, skill)
    skill._build_supplemental_queries = types.MethodType(_fake_supplemental_queries, skill)
    skill._search_view_news = types.MethodType(_fake_search, skill)

    parsed = ParsedRequest(
        client_name="A食品株式会社",
        client_industry="食品",
        watch_competitors=["Bフーズ"],
        lookback_days=7,
        focus_topics=["原材料価格"],
    )
    rows, stats = asyncio.run(
        skill._collect_news_candidates(
            parsed=parsed,
            hypotheses={"self_company": [], "peer_companies": [], "macro": []},
            provider_id="openai",
            model="gpt-5.2-2025-12-11",
            cutoff=datetime.now(UTC) - timedelta(days=7),
        )
    )
    filtered, _, _, _ = skill._filter_and_dedupe(candidates=rows, cutoff=datetime.now(UTC) - timedelta(days=7))
    counts = skill._count_per_view(filtered)
    assert counts["peer_companies"] >= 2
    assert stats["supplemental_runs_by_view"]["peer_companies"] >= 1


def test_macro_and_peer_queries_do_not_embed_client_name() -> None:
    skill = AuditNewsActionBriefSkill()
    parsed = ParsedRequest(
        client_name="A食品株式会社",
        client_industry="食品",
        watch_competitors=["Bフーズ"],
        lookback_days=7,
        focus_topics=["原材料価格"],
    )
    queries = skill._build_primary_queries(
        parsed=parsed,
        hypotheses={"self_company": [], "peer_companies": [], "macro": []},
    )
    assert all(parsed.client_name not in q for q in queries["peer_companies"])
    assert all(parsed.client_name not in q for q in queries["macro"])


def test_output_marks_absence_for_peer_and_macro_with_search_summary() -> None:
    skill = AuditNewsActionBriefSkill()
    skill._parse_request = types.MethodType(_fake_parse_ok, skill)
    skill._generate_hypotheses = types.MethodType(_fake_generate_hypotheses, skill)

    async def _fake_collect_only_self(self, *, parsed, hypotheses, provider_id, model, cutoff):
        del self, parsed, hypotheses, provider_id, model, cutoff
        now = datetime.now(UTC)
        rows = [
            NewsCandidate(
                title="A食品、価格改定を発表",
                url="https://example.com/self-only",
                source="Example",
                published_at=now - timedelta(days=1),
                summary="自社関連のみ。",
                one_liner_comment="コメント。",
                propagation_note="波及。",
                view="self_company",
                macro_subtype=None,
            ),
            NewsCandidate(
                title="A食品、在庫戦略を更新",
                url="https://example.com/self-only-2",
                source="Example",
                published_at=now - timedelta(days=2),
                summary="自社関連のみ。",
                one_liner_comment="コメント。",
                propagation_note="波及。",
                view="self_company",
                macro_subtype=None,
            ),
        ]
        return rows, {
            "raw_counts_by_view": {"self_company": 2, "peer_companies": 0, "macro": 0},
            "supplemental_runs_by_view": {"self_company": 0, "peer_companies": 1, "macro": 1},
            "query_logs_by_view": {
                "self_company": [{"stage": "primary", "query": "self-q", "hits": 2}],
                "peer_companies": [
                    {"stage": "primary", "query": "peer-q", "hits": 0},
                    {"stage": "supplemental", "query": "peer-sup", "hits": 0},
                ],
                "macro": [
                    {"stage": "primary", "query": "macro-q", "hits": 0},
                    {"stage": "supplemental", "query": "macro-sup", "hits": 0},
                ],
            },
        }

    skill._collect_news_candidates = types.MethodType(_fake_collect_only_self, skill)

    output = asyncio.run(
        skill.run(
            user_text="A食品株式会社の監査ニュース",
            history=[],
            skill_context={"provider_id": "openai", "model": "gpt-5.2-2025-12-11"},
        )
    )

    assert "## 他社" in output
    assert "## マクロ" in output
    assert "該当ニュースは見つかりませんでした（探索結果: 0件）。" in output
    assert "他社" in output and "探索クエリ2本（primary 1本, supplemental 1本）を実行" in output
    assert "マクロ" in output and "探索クエリ2本（primary 1本, supplemental 1本）を実行" in output
    assert "クエリ: peer-q / peer-sup" in output
    assert "クエリ: macro-q / macro-sup" in output
    assert "## 探索戦略（デバッグ）" in output


def test_build_search_absence_summary_includes_query_details() -> None:
    skill = AuditNewsActionBriefSkill()
    summary = skill._build_search_absence_summary(
        query_logs=[
            {"stage": "primary", "query": "peer primary q", "hits": 0},
            {"stage": "supplemental", "query": "peer supplemental q", "hits": 0},
            {"stage": "supplemental", "query": "peer extra q", "hits": 0},
        ],
        view_label="peer_companies",
    )
    assert summary is not None
    assert "探索クエリ3本（primary 1本, supplemental 2本）を実行" in summary
    assert "クエリ: peer primary q / peer supplemental q / ...(+1)" in summary
