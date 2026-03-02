import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from app.model_catalog import get_model_capability
from app.skills_runtime.base import Skill, SkillMetadata

_SKILL_DIR = Path(__file__).resolve().parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

from audit_news_llm_client import extract_json_array, extract_json_object, run_json_prompt_with_web  # noqa: E402


class ParsedRequest:
    def __init__(
        self,
        *,
        client_name: str | None,
        client_industry: str | None,
        watch_competitors: list[str],
        lookback_days: int,
        focus_topics: list[str],
    ) -> None:
        self.client_name = client_name
        self.client_industry = client_industry
        self.watch_competitors = watch_competitors
        self.lookback_days = lookback_days
        self.focus_topics = focus_topics


class NewsCandidate:
    def __init__(
        self,
        *,
        title: str,
        url: str,
        source: str,
        published_at: datetime | None,
        summary: str,
        one_liner_comment: str,
        propagation_note: str,
        view: str,
        macro_subtype: str | None,
    ) -> None:
        self.title = title
        self.url = url
        self.source = source
        self.published_at = published_at
        self.summary = summary
        self.one_liner_comment = one_liner_comment
        self.propagation_note = propagation_note
        self.view = view
        self.macro_subtype = macro_subtype


class AuditNewsActionBriefSkill(Skill):
    metadata = SkillMetadata(
        id="audit_news_action_brief",
        name="Audit News Action Brief",
        description=(
            "監査クライアントの業種・競合・マクロニュースを仮説先行で深く探索し、"
            "自社・他社・マクロの3視点で監査アクション候補を返します。"
        ),
    )

    _RESEARCH_PROFILE = "deep_standard"
    _PRIMARY_QUERIES_PER_VIEW = 2
    _SUPPLEMENTAL_QUERIES_PER_VIEW = 1
    _MAX_ITEMS_PER_QUERY = 4
    _MIN_ITEMS_PER_VIEW = 4
    _MAX_ITEMS_PER_VIEW_OUTPUT = 8
    _MAX_LOOKBACK_DAYS = 30
    _MAX_TOTAL_TARGET = 24

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> str:
        del history

        context = skill_context or {}
        provider_id = str(context.get("provider_id") or "")
        model = str(context.get("model") or "").strip()

        if provider_id != "openai" or not model:
            return (
                "このSkillは OpenAI Responses API モデル（Web検索有効）専用です。"
                "`provider_id=openai` と `gpt-5.2-2025-12-11` などのResponsesモデルを指定してください。"
            )

        capability = get_model_capability(provider_id, model)
        if capability.api_mode != "responses":
            return (
                "このSkillは OpenAI Responses API モデルが必須です。"
                f"現在のモデル `{model}` は `api_mode={capability.api_mode}` のため利用できません。"
            )

        parsed = await self._parse_request(user_text=user_text, provider_id=provider_id, model=model)
        missing = []
        if not parsed.client_name:
            missing.append("監査クライアント名")
        if not parsed.client_industry:
            missing.append("監査クライアントの業種")
        if missing:
            return (
                "監査アクションニュースブリーフ\n\n"
                "## 不足情報\n"
                + "\n".join([f"- {item} が不足しています。" for item in missing])
                + "\n- 例: `クライアントは〇〇社、業種は食品、直近7日の監査アクションニュース`"
            )

        lookback_days = max(1, min(parsed.lookback_days, self._MAX_LOOKBACK_DAYS))
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        run_id = str(uuid4())

        hypotheses = await self._generate_hypotheses(parsed=parsed, provider_id=provider_id, model=model)
        candidates = await self._collect_news_candidates(
            parsed=parsed,
            hypotheses=hypotheses,
            provider_id=provider_id,
            model=model,
        )

        filtered, dropped_old, dropped_dup = self._filter_and_dedupe(candidates=candidates, cutoff=cutoff)

        scored: list[dict[str, Any]] = []
        for item in filtered:
            scored.append(self._build_news_item(item=item, parsed=parsed))

        view_items = {
            "self_company": [],
            "peer_companies": [],
            "macro": [],
        }
        scored.sort(key=lambda row: int(row.get("score", 0)), reverse=True)
        for row in scored:
            view = str(row.get("view") or "")
            if view not in view_items:
                continue
            if len(view_items[view]) >= self._MAX_ITEMS_PER_VIEW_OUTPUT:
                continue
            view_items[view].append(row)

        # Keep result size centered around the deep-standard target range.
        total_count = sum(len(rows) for rows in view_items.values())
        if total_count > self._MAX_TOTAL_TARGET:
            merged = [*view_items["self_company"], *view_items["peer_companies"], *view_items["macro"]]
            merged.sort(key=lambda row: int(row.get("score", 0)), reverse=True)
            keep_ids = {row["news_id"] for row in merged[: self._MAX_TOTAL_TARGET] if isinstance(row.get("news_id"), str)}
            for view in view_items:
                view_items[view] = [row for row in view_items[view] if row.get("news_id") in keep_ids]

        payload = {
            "schema": "audit_news_action_brief/v2",
            "run_id": run_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "client": {
                "name": parsed.client_name,
                "industry": parsed.client_industry,
                "lookback_days": lookback_days,
                "focus_topics": parsed.focus_topics,
                "watch_competitors": parsed.watch_competitors,
                "research_profile": self._RESEARCH_PROFILE,
            },
            "views": view_items,
        }

        lines = [
            "監査アクションニュースブリーフ v2",
            "",
            "## 今回の前提",
            f"- クライアント: {parsed.client_name}",
            f"- 業種: {parsed.client_industry}",
            f"- 監視期間: 直近{lookback_days}日",
            f"- 競合監視: {', '.join(parsed.watch_competitors) if parsed.watch_competitors else '未指定'}",
            f"- 注力トピック: {', '.join(parsed.focus_topics) if parsed.focus_topics else '未指定'}",
            f"- 調査プロファイル: {self._RESEARCH_PROFILE}",
            "",
            "## 自社",
        ]
        lines.extend(self._render_view_items(view_items["self_company"], view_label="self_company"))
        lines.extend(["", "## 他社"])
        lines.extend(self._render_view_items(view_items["peer_companies"], view_label="peer_companies"))
        lines.extend(["", "## マクロ"])
        lines.extend(self._render_view_items(view_items["macro"], view_label="macro"))

        total_after_filter = sum(len(rows) for rows in view_items.values())
        lines.extend(
            [
                "",
                "## 除外理由（ノイズ管理）",
                f"- 期間外により除外: {dropped_old}件",
                f"- 重複により除外: {dropped_dup}件",
                f"- 最終採用件数: {total_after_filter}件",
                "",
                "```audit-news-json",
                json.dumps(payload, ensure_ascii=False),
                "```",
            ]
        )
        return "\n".join(lines)

    async def _parse_request(self, *, user_text: str, provider_id: str, model: str) -> ParsedRequest:
        prompt = (
            "ユーザー要求から監査ニュース探索条件を抽出してください。"
            "JSONオブジェクトのみを返し、形式は"
            "{\"client_name\":string|null,\"client_industry\":string|null,"
            "\"watch_competitors\":string[],\"lookback_days\":number|null,\"focus_topics\":string[]}。"
            "lookback_daysが無ければnull。\n"
            f"ユーザー要求: {user_text}"
        )
        raw = await run_json_prompt_with_web(
            provider_id=provider_id,
            model=model,
            prompt=prompt,
            max_output_tokens=450,
            reasoning_effort="medium",
        )
        obj = extract_json_object(raw) or {}

        client_name = self._clean_str(obj.get("client_name")) or self._fallback_client_name(user_text)
        client_industry = self._clean_str(obj.get("client_industry")) or self._fallback_industry(user_text)
        competitors = self._clean_str_list(obj.get("watch_competitors"))
        focus_topics = self._clean_str_list(obj.get("focus_topics"))

        lookback_days = 7
        if isinstance(obj.get("lookback_days"), (int, float)):
            lookback_days = int(obj["lookback_days"])

        return ParsedRequest(
            client_name=client_name,
            client_industry=client_industry,
            watch_competitors=competitors,
            lookback_days=lookback_days,
            focus_topics=focus_topics,
        )

    async def _generate_hypotheses(
        self,
        *,
        parsed: ParsedRequest,
        provider_id: str,
        model: str,
    ) -> dict[str, list[str]]:
        prompt = (
            "監査ニュース調査の事前仮説を作成してください。"
            "当該企業への波及経路（要因→財務/内部統制影響→監査論点）を視点別に列挙します。"
            "JSONオブジェクトのみを返し、形式は"
            "{\"self_company\":string[],\"peer_companies\":string[],\"macro\":string[]}。"
            "各配列は最大5件、短文。\n"
            f"クライアント: {parsed.client_name}\n"
            f"業種: {parsed.client_industry}\n"
            f"競合: {', '.join(parsed.watch_competitors) if parsed.watch_competitors else '未指定'}\n"
            f"注力トピック: {', '.join(parsed.focus_topics) if parsed.focus_topics else '未指定'}\n"
            f"監視期間: 直近{parsed.lookback_days}日"
        )
        raw = await run_json_prompt_with_web(
            provider_id=provider_id,
            model=model,
            prompt=prompt,
            max_output_tokens=900,
            reasoning_effort="high",
        )
        obj = extract_json_object(raw) or {}
        hypotheses = {
            "self_company": self._clean_str_list(obj.get("self_company")),
            "peer_companies": self._clean_str_list(obj.get("peer_companies")),
            "macro": self._clean_str_list(obj.get("macro")),
        }
        return hypotheses

    async def _collect_news_candidates(
        self,
        *,
        parsed: ParsedRequest,
        hypotheses: dict[str, list[str]],
        provider_id: str,
        model: str,
    ) -> list[NewsCandidate]:
        primary_queries = self._build_primary_queries(parsed=parsed, hypotheses=hypotheses)

        gathered: list[NewsCandidate] = []
        for view, queries in primary_queries.items():
            for query in queries[: self._PRIMARY_QUERIES_PER_VIEW]:
                gathered.extend(
                    await self._search_view_news(
                        view=view,
                        query=query,
                        parsed=parsed,
                        provider_id=provider_id,
                        model=model,
                        max_items=self._MAX_ITEMS_PER_QUERY,
                    )
                )

        cutoff = datetime.now(UTC) - timedelta(days=max(1, min(parsed.lookback_days, self._MAX_LOOKBACK_DAYS)))
        filtered, _, _ = self._filter_and_dedupe(candidates=gathered, cutoff=cutoff)
        counts = self._count_per_view(filtered)

        for view in ("self_company", "peer_companies", "macro"):
            if counts.get(view, 0) >= self._MIN_ITEMS_PER_VIEW:
                continue
            supplemental_queries = self._build_supplemental_queries(parsed=parsed, hypotheses=hypotheses, view=view)
            for query in supplemental_queries[: self._SUPPLEMENTAL_QUERIES_PER_VIEW]:
                gathered.extend(
                    await self._search_view_news(
                        view=view,
                        query=query,
                        parsed=parsed,
                        provider_id=provider_id,
                        model=model,
                        max_items=self._MAX_ITEMS_PER_QUERY,
                    )
                )

        return gathered

    async def _search_view_news(
        self,
        *,
        view: str,
        query: str,
        parsed: ParsedRequest,
        provider_id: str,
        model: str,
        max_items: int,
    ) -> list[NewsCandidate]:
        prompt = (
            "あなたは監査人向けニュースアナリストです。Web検索を使い、"
            "日本語中心で直近ニュースを収集してください。"
            "JSON配列のみを返し、各要素は"
            "{"
            "\"title\":string,\"url\":string,\"source\":string,\"published_at\":string,"
            "\"summary\":string,\"one_liner_comment\":string,\"propagation_note\":string,"
            "\"macro_subtype\":string|null"
            "}。"
            "macro_subtypeは view=macro の時のみ、"
            "regulation/policy/market/commodity/fx/rates のいずれか。"
            "published_atは可能ならISO-8601形式。"
            f"最大{max_items}件。\n"
            f"クライアント: {parsed.client_name}\n"
            f"業種: {parsed.client_industry}\n"
            f"視点: {view}\n"
            f"検索クエリ: {query}\n"
            f"期間条件: 直近{parsed.lookback_days}日を優先。"
        )
        raw = await run_json_prompt_with_web(
            provider_id=provider_id,
            model=model,
            prompt=prompt,
            max_output_tokens=1600,
            reasoning_effort="high",
        )
        rows = extract_json_array(raw)
        if rows is None:
            return []

        out: list[NewsCandidate] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            title = self._clean_str(row.get("title"))
            url = self._clean_str(row.get("url"))
            if not title or not url:
                continue

            summary = self._clean_str(row.get("summary")) or ""
            one_liner_comment = self._clean_str(row.get("one_liner_comment")) or ""
            propagation_note = self._clean_str(row.get("propagation_note")) or ""
            if not summary:
                summary = one_liner_comment
            if not one_liner_comment:
                one_liner_comment = summary
            if not propagation_note:
                propagation_note = f"{parsed.client_name} への波及可能性は継続確認が必要です。"

            macro_subtype = None
            if view == "macro":
                candidate_subtype = self._clean_str(row.get("macro_subtype"))
                if candidate_subtype in {"regulation", "policy", "market", "commodity", "fx", "rates"}:
                    macro_subtype = candidate_subtype

            out.append(
                NewsCandidate(
                    title=title,
                    url=url,
                    source=self._clean_str(row.get("source")) or self._source_from_url(url),
                    published_at=self._parse_datetime(self._clean_str(row.get("published_at")) or ""),
                    summary=summary,
                    one_liner_comment=one_liner_comment,
                    propagation_note=propagation_note,
                    view=view,
                    macro_subtype=macro_subtype,
                )
            )
        return out

    def _build_primary_queries(self, *, parsed: ParsedRequest, hypotheses: dict[str, list[str]]) -> dict[str, list[str]]:
        competitors = " ".join(parsed.watch_competitors) if parsed.watch_competitors else "主要競合"
        topics = " ".join(parsed.focus_topics) if parsed.focus_topics else "会計見積り"

        self_h = hypotheses.get("self_company") or []
        peer_h = hypotheses.get("peer_companies") or []
        macro_h = hypotheses.get("macro") or []

        out = {
            "self_company": [
                f"{parsed.client_name} {parsed.client_industry} 業績 見通し 開示 リスク 監査 {topics}",
                f"{parsed.client_name} 原価 在庫 減損 引当 継続企業 監査",
                f"{parsed.client_name} サプライチェーン 障害 訴訟 リコール 影響",
            ],
            "peer_companies": [
                f"{parsed.client_industry} 競合 {competitors} 業績 下方修正 生産停止 監査影響",
                f"{parsed.client_industry} 同業 リコール 訴訟 不正 開示",
                f"{parsed.client_industry} 市況 シェア 価格改定 競争環境",
            ],
            "macro": [
                f"{parsed.client_industry} 金利 為替 原材料価格 関税 景気 指標 {parsed.client_name} 影響",
                f"{parsed.client_industry} 政策変更 規制変更 会計基準 開示制度 金融庁",
                f"{parsed.client_industry} 需給 物流 エネルギーコスト インフレ",
            ],
        }

        if self_h:
            out["self_company"][0] = f"{out['self_company'][0]} {' '.join(self_h[:2])}"
            out["self_company"][1] = f"{out['self_company'][1]} {' '.join(self_h[2:4])}"
        if peer_h:
            out["peer_companies"][0] = f"{out['peer_companies'][0]} {' '.join(peer_h[:2])}"
            out["peer_companies"][1] = f"{out['peer_companies'][1]} {' '.join(peer_h[2:4])}"
        if macro_h:
            out["macro"][0] = f"{out['macro'][0]} {' '.join(macro_h[:2])}"
            out["macro"][1] = f"{out['macro'][1]} {' '.join(macro_h[2:4])}"

        return out

    def _build_supplemental_queries(
        self,
        *,
        parsed: ParsedRequest,
        hypotheses: dict[str, list[str]],
        view: str,
    ) -> list[str]:
        hints = hypotheses.get(view) or []
        hint_text = " ".join(hints[:3]) if hints else ""
        if view == "self_company":
            return [
                f"{parsed.client_name} 最新 監査論点 収益性 資金繰り {hint_text}",
                f"{parsed.client_name} IR 開示 重要事象 リスク {hint_text}",
            ]
        if view == "peer_companies":
            competitors = " ".join(parsed.watch_competitors) if parsed.watch_competitors else "同業"
            return [
                f"{parsed.client_industry} {competitors} 最新 トラブル 供給 価格 影響 {hint_text}",
                f"{parsed.client_industry} 競合 監査 注目 開示 リスク {hint_text}",
            ]
        return [
            f"{parsed.client_industry} 規制 政策 速報 {parsed.client_name} 影響 監査 {hint_text}",
            f"{parsed.client_industry} マクロ 指標 為替 金利 原料 市況 {parsed.client_name}",
        ]

    def _count_per_view(self, candidates: list[NewsCandidate]) -> dict[str, int]:
        counts = {"self_company": 0, "peer_companies": 0, "macro": 0}
        for item in candidates:
            if item.view in counts:
                counts[item.view] += 1
        return counts

    def _filter_and_dedupe(
        self,
        *,
        candidates: list[NewsCandidate],
        cutoff: datetime,
    ) -> tuple[list[NewsCandidate], int, int]:
        dropped_old = 0
        dropped_dup = 0
        out: list[NewsCandidate] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()

        for row in candidates:
            if row.published_at is not None and row.published_at < cutoff:
                dropped_old += 1
                continue

            normalized_url = self._normalize_url(row.url)
            normalized_title = self._normalize_title(row.title)
            if normalized_url in seen_urls or normalized_title in seen_titles:
                dropped_dup += 1
                continue

            seen_urls.add(normalized_url)
            seen_titles.add(normalized_title)
            out.append(row)

        return out, dropped_old, dropped_dup

    def _build_news_item(self, *, item: NewsCandidate, parsed: ParsedRequest) -> dict[str, Any]:
        days_old = 4
        if item.published_at is not None:
            days_old = max(0, (datetime.now(UTC) - item.published_at).days)

        score = 42 + max(0, 18 - min(days_old, 18))
        if item.view == "macro":
            score += 12
        elif item.view == "peer_companies":
            score += 10
        else:
            score += 8

        if self._is_trusted_source(item.url):
            score += 8

        if parsed.client_name and parsed.client_name in item.title and item.view == "self_company":
            score += 3

        if len(item.summary) < 30:
            score -= 8
        if len(item.propagation_note) < 24:
            score -= 6

        score = max(0, min(100, score))

        published = item.published_at.isoformat() if item.published_at else "unknown"
        news_id = self._build_news_id(item=item)
        output: dict[str, Any] = {
            "news_id": news_id,
            "title": item.title,
            "summary": item.summary,
            "url": item.url,
            "one_liner_comment": item.one_liner_comment,
            "source": item.source,
            "published_at": published,
            "view": item.view,
            "propagation_note": item.propagation_note,
            "score": score,
        }
        if item.view == "macro" and item.macro_subtype:
            output["macro_subtype"] = item.macro_subtype
        return output

    def _render_view_items(self, items: list[dict[str, Any]], *, view_label: str) -> list[str]:
        if not items:
            return ["- 該当ニュースは見つかりませんでした。"]
        lines: list[str] = []
        for idx, row in enumerate(items, start=1):
            subtype = ""
            if view_label == "macro" and isinstance(row.get("macro_subtype"), str):
                subtype = f" ({row['macro_subtype']})"
            lines.extend(
                [
                    f"{idx}. {row.get('title', 'untitled')}{subtype}",
                    f"- 概要: {row.get('summary', '')}",
                    f"- URL: {row.get('url', '')}",
                    f"- 一言コメント: {row.get('one_liner_comment', '')}",
                    f"- 波及メモ: {row.get('propagation_note', '')}",
                ]
            )
        return lines

    def _build_news_id(self, *, item: NewsCandidate) -> str:
        key = f"{self._normalize_url(item.url)}|{self._normalize_title(item.title)}|{item.view}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def _parse_datetime(self, text: str) -> datetime | None:
        raw = text.strip()
        if not raw:
            return None

        normalized = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            pass

        match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", raw)
        if match:
            year, month, day = map(int, match.groups())
            return datetime(year, month, day, tzinfo=UTC)

        return None

    def _fallback_client_name(self, user_text: str) -> str | None:
        match = re.search(r"([\w\u4e00-\u9fff\u3040-\u30ff・&\-]+)社", user_text)
        if not match:
            return None
        return f"{match.group(1)}社"

    def _fallback_industry(self, user_text: str) -> str | None:
        match = re.search(r"業種[は:：\s]*([\w\u4e00-\u9fff\u3040-\u30ff]+)", user_text)
        if match:
            return match.group(1)
        return None

    def _clean_str(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        out = value.strip()
        return out if out else None

    def _clean_str_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            text = self._clean_str(item)
            if text:
                out.append(text)
        return out

    def _normalize_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        return f"{host}{path}"

    def _normalize_title(self, title: str) -> str:
        return re.sub(r"\s+", "", title.lower())

    def _source_from_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        return parsed.netloc or "unknown"

    def _is_trusted_source(self, raw_url: str) -> bool:
        host = (urlparse(raw_url).netloc or "").lower()
        trusted = (
            "nikkei.com",
            "reuters.com",
            "bloomberg.com",
            "jpx.co.jp",
            "fsa.go.jp",
            "boj.or.jp",
            "meti.go.jp",
        )
        return any(host.endswith(domain) for domain in trusted)


def build_skill() -> Skill:
    return AuditNewsActionBriefSkill()
