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
        snippet: str,
        category: str,
    ) -> None:
        self.title = title
        self.url = url
        self.source = source
        self.published_at = published_at
        self.snippet = snippet
        self.category = category


class AuditNewsActionBriefSkill(Skill):
    metadata = SkillMetadata(
        id="audit_news_action_brief",
        name="Audit News Action Brief",
        description=(
            "監査クライアントの業種・競合・マクロ・規制ニュースを直近期間で探索し、"
            "監査人が行動を起こすべき候補を優先度付きで返します。"
        ),
    )

    _MAX_ALERTS = 5
    _MAX_MONITOR = 5
    _ACTION_THRESHOLD = 65

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

        run_id = str(uuid4())
        lookback_days = max(1, min(parsed.lookback_days, 30))
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

        candidates = await self._collect_news_candidates(parsed=parsed, provider_id=provider_id, model=model)

        filtered, dropped_old, dropped_dup = self._filter_and_dedupe(candidates=candidates, cutoff=cutoff)
        scored = [self._build_alert_payload(item=item, parsed=parsed) for item in filtered]
        scored.sort(key=lambda row: row["score"], reverse=True)

        action_candidates = [row for row in scored if int(row.get("score", 0)) >= self._ACTION_THRESHOLD]
        monitor_candidates = [row for row in scored if int(row.get("score", 0)) < self._ACTION_THRESHOLD]

        action_items = action_candidates[: self._MAX_ALERTS]
        monitor_items = monitor_candidates[: self._MAX_MONITOR]
        if len(action_items) < self._MAX_ALERTS:
            remaining = self._MAX_ALERTS - len(action_items)
            overflow = action_candidates[self._MAX_ALERTS : self._MAX_ALERTS + remaining]
            monitor_items = (overflow + monitor_items)[: self._MAX_MONITOR]

        payload = {
            "schema": "audit_news_action_brief/v1",
            "run_id": run_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "client": {
                "name": parsed.client_name,
                "industry": parsed.client_industry,
                "lookback_days": lookback_days,
                "focus_topics": parsed.focus_topics,
                "watch_competitors": parsed.watch_competitors,
            },
            "alerts": action_items,
        }

        lines = [
            "監査アクションニュースブリーフ",
            "",
            "## 今回の前提",
            f"- クライアント: {parsed.client_name}",
            f"- 業種: {parsed.client_industry}",
            f"- 監視期間: 直近{lookback_days}日",
            f"- 競合監視: {', '.join(parsed.watch_competitors) if parsed.watch_competitors else '未指定'}",
            f"- 注力トピック: {', '.join(parsed.focus_topics) if parsed.focus_topics else '未指定'}",
            "",
            "## Action Required（優先度順）",
        ]

        if not action_items:
            if scored:
                top = scored[0]
                lines.extend(
                    [
                        "- 今回はアラート閾値を超えるニュースはありませんでした。",
                        (
                            f"- ただし収集ニュースの中では `{top['title']}` が相対的に最重要でした。"
                            "現時点では追加対応は不要ですが、継続監視を推奨します。"
                        ),
                    ]
                )
            else:
                lines.append("- 行動喚起できるニュース候補は見つかりませんでした。期間や業種指定を広げて再実行してください。")
        else:
            for idx, alert in enumerate(action_items, start=1):
                lines.extend(
                    [
                        f"{idx}. [{alert['priority'].upper()}] {alert['title']}",
                        f"- 公開日: {alert['published_at']}",
                        f"- カテゴリ: {alert['category']}",
                        f"- 想定影響: {alert['impact_hypothesis']}",
                        f"- 推奨監査アクション: {alert['recommended_audit_action']}",
                        f"- スコア: {alert['score']}",
                        f"- URL: {alert['url']}",
                    ]
                )

        lines.extend(["", "## Monitor"])
        if not monitor_items:
            lines.append("- 現時点で追加モニタ候補はありません。")
        else:
            for alert in monitor_items:
                lines.append(f"- {alert['title']} ({alert['source']}, {alert['published_at']}, score={alert['score']})")

        lines.extend(
            [
                "",
                "## 除外理由（ノイズ管理）",
                f"- 期間外により除外: {dropped_old}件",
                f"- 重複により除外: {dropped_dup}件",
                "",
                "## 回答ポリシー",
                "- 直近ニュースを優先し、監査手続に直結する行動を提示する。",
                "- 根拠にない断定を避け、追加確認が必要な点は明示する。",
                "- クライアント直球ニュースは既知の可能性を考慮し優先度を抑制する。",
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
            max_output_tokens=400,
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

    async def _collect_news_candidates(
        self,
        *,
        parsed: ParsedRequest,
        provider_id: str,
        model: str,
    ) -> list[NewsCandidate]:
        competitor_hint = ", ".join(parsed.watch_competitors) if parsed.watch_competitors else "主要競合"
        focus_hint = ", ".join(parsed.focus_topics) if parsed.focus_topics else "特になし"

        bucket_queries = {
            "competitor": (
                f"{parsed.client_industry} 業界 競合 {competitor_hint} 業績 生産 障害 訴訟 リコール "
                f"{parsed.client_name} 影響 監査"
            ),
            "macro": (
                f"{parsed.client_industry} 金利 為替 原材料価格 関税 景気 指標 政策変更 "
                f"{parsed.client_name} 影響 監査 {focus_hint}"
            ),
            "regulatory": (
                f"金融庁 監査 開示 会計基準 ガバナンス 内部統制 {parsed.client_industry} "
                f"{parsed.client_name} 監査対応"
            ),
        }

        gathered: list[NewsCandidate] = []
        for category, query in bucket_queries.items():
            gathered.extend(
                await self._search_bucket_news(
                    category=category,
                    query=query,
                    parsed=parsed,
                    provider_id=provider_id,
                    model=model,
                )
            )
        return gathered

    async def _search_bucket_news(
        self,
        *,
        category: str,
        query: str,
        parsed: ParsedRequest,
        provider_id: str,
        model: str,
    ) -> list[NewsCandidate]:
        prompt = (
            "あなたは監査人向けのニュースアナリストです。Web検索を使い、"
            "日本語中心で直近ニュースを収集してください。"
            "JSON配列のみを返し、各要素は"
            "{\"title\":string,\"url\":string,\"source\":string,\"published_at\":string,\"snippet\":string}。"
            "published_atは可能ならISO-8601形式。"
            "5件以内。\n"
            f"クライアント: {parsed.client_name}\n"
            f"業種: {parsed.client_industry}\n"
            f"カテゴリ: {category}\n"
            f"検索クエリ: {query}\n"
            f"期間条件: 直近{parsed.lookback_days}日を優先。"
        )
        raw = await run_json_prompt_with_web(
            provider_id=provider_id,
            model=model,
            prompt=prompt,
            max_output_tokens=1000,
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

            out.append(
                NewsCandidate(
                    title=title,
                    url=url,
                    source=self._clean_str(row.get("source")) or self._source_from_url(url),
                    published_at=self._parse_datetime(self._clean_str(row.get("published_at")) or ""),
                    snippet=self._clean_str(row.get("snippet")) or "",
                    category=category,
                )
            )
        return out

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

    def _build_alert_payload(self, *, item: NewsCandidate, parsed: ParsedRequest) -> dict[str, Any]:
        days_old = 3
        if item.published_at is not None:
            days_old = max(0, (datetime.now(UTC) - item.published_at).days)

        score = 45
        score += max(0, 20 - min(days_old, 20))

        if item.category == "regulatory":
            score += 18
        elif item.category == "macro":
            score += 12
        else:
            score += 10

        if self._is_trusted_source(item.url):
            score += 8

        if parsed.client_name and parsed.client_name in item.title:
            score -= 12

        if len(item.snippet) < 40:
            score -= 8

        score = max(0, min(100, score))
        priority = "high" if score >= 80 else "medium" if score >= 65 else "low"

        impact_hypothesis = self._impact_hypothesis(item=item, parsed=parsed)
        recommended_action = self._recommended_action(item=item, parsed=parsed)

        published = item.published_at.isoformat() if item.published_at else "unknown"
        alert_id = self._build_alert_id(item=item)
        return {
            "alert_id": alert_id,
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "published_at": published,
            "category": item.category,
            "impact_hypothesis": impact_hypothesis,
            "recommended_audit_action": recommended_action,
            "priority": priority,
            "score": score,
        }

    def _impact_hypothesis(self, *, item: NewsCandidate, parsed: ParsedRequest) -> str:
        if item.category == "competitor":
            return (
                f"同業の変化が {parsed.client_name} の売上見通し・在庫評価・引当見積りへ波及し、"
                "会計見積りの前提が変化する可能性があります。"
            )
        if item.category == "macro":
            return (
                f"マクロ環境変化が {parsed.client_name} の資金繰り/収益性/調達コストへ影響し、"
                "継続企業や減損兆候の再評価が必要となる可能性があります。"
            )
        return (
            "規制・開示要件の更新が監査計画、内部統制評価、注記確認手続の追加を"
            "必要とする可能性があります。"
        )

    def _recommended_action(self, *, item: NewsCandidate, parsed: ParsedRequest) -> str:
        base = f"担当チームで {parsed.client_name} への影響仮説を当日中に共有し、"
        if item.category == "competitor":
            return base + "関連する会計見積り（売上/在庫/引当）について追加質問票を準備する。"
        if item.category == "macro":
            return base + "資金計画・減損兆候・感応度分析の更新要否を経営者に照会する。"
        return base + "最新規制に照らした開示・内部統制手続の差分レビューを実施する。"

    def _build_alert_id(self, *, item: NewsCandidate) -> str:
        key = f"{self._normalize_url(item.url)}|{self._normalize_title(item.title)}"
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
