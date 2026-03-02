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

from audit_news_llm_client import extract_json_array, extract_json_object, run_json_prompt, run_json_prompt_with_web  # noqa: E402


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


class NewsItemV3:
    def __init__(
        self,
        *,
        title: str,
        summary: str,
        url: str,
        one_liner_comment: str,
        source: str,
        published_at: str,
        view: str,
    ) -> None:
        self.title = title
        self.summary = summary
        self.url = url
        self.one_liner_comment = one_liner_comment
        self.source = source
        self.published_at = published_at
        self.view = view


class AuditNewsActionBriefSkill(Skill):
    metadata = SkillMetadata(
        id="audit_news_action_brief",
        name="Audit News Action Brief",
        description=(
            "監査クライアントの自社・他社・マクロニュースを戦略的に探索し、"
            "監査上有益なニュースをカテゴリ別に提示します。"
        ),
    )

    _MAX_LOOKBACK_DAYS = 30

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

        # Step 1: Parse request (no web search needed)
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
        run_id = str(uuid4())

        # Step 2: Search self_company (serial)
        self_items = await self._search_category(
            view="self_company",
            parsed=parsed,
            provider_id=provider_id,
            model=model,
            prior_titles=[],
        )

        # Step 3: Search peer_companies (serial)
        peer_items = await self._search_category(
            view="peer_companies",
            parsed=parsed,
            provider_id=provider_id,
            model=model,
            prior_titles=[item.title for item in self_items],
        )

        # Step 4: Search macro (serial)
        macro_items = await self._search_category(
            view="macro",
            parsed=parsed,
            provider_id=provider_id,
            model=model,
            prior_titles=[item.title for item in self_items + peer_items],
        )

        # Build v3 payload
        payload = {
            "schema": "audit_news_action_brief/v3",
            "run_id": run_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "client": {
                "name": parsed.client_name,
                "industry": parsed.client_industry,
                "lookback_days": lookback_days,
                "focus_topics": parsed.focus_topics,
                "watch_competitors": parsed.watch_competitors,
            },
            "views": {
                "self_company": [self._item_to_dict(item) for item in self_items],
                "peer_companies": [self._item_to_dict(item) for item in peer_items],
                "macro": [self._item_to_dict(item) for item in macro_items],
            },
        }

        # Build markdown output
        lines = [
            "監査アクションニュースブリーフ v3",
            "",
            "## 今回の前提",
            f"- クライアント: {parsed.client_name}",
            f"- 業種: {parsed.client_industry}",
            f"- 監視期間: 直近{lookback_days}日",
            f"- 競合監視: {', '.join(parsed.watch_competitors) if parsed.watch_competitors else '未指定'}",
            f"- 注力トピック: {', '.join(parsed.focus_topics) if parsed.focus_topics else '未指定'}",
            "",
            "## 自社",
        ]
        lines.extend(self._render_items(self_items))
        lines.extend(["", "## 他社"])
        lines.extend(self._render_items(peer_items))
        lines.extend(["", "## マクロ"])
        lines.extend(self._render_items(macro_items))
        lines.extend([
            "",
            "```audit-news-json",
            json.dumps(payload, ensure_ascii=False),
            "```",
        ])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Request parsing
    # ------------------------------------------------------------------

    async def _parse_request(self, *, user_text: str, provider_id: str, model: str) -> ParsedRequest:
        prompt = (
            "ユーザー要求から監査ニュース探索条件を抽出してください。"
            "JSONオブジェクトのみを返し、形式は"
            '{"client_name":string|null,"client_industry":string|null,'
            '"watch_competitors":string[],"lookback_days":number|null,"focus_topics":string[]}。'
            "lookback_daysが無ければnull。\n"
            f"ユーザー要求: {user_text}"
        )
        raw = await run_json_prompt(
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

    # ------------------------------------------------------------------
    # Category search
    # ------------------------------------------------------------------

    async def _search_category(
        self,
        *,
        view: str,
        parsed: ParsedRequest,
        provider_id: str,
        model: str,
        prior_titles: list[str],
    ) -> list[NewsItemV3]:
        prompt = self._build_category_prompt(view=view, parsed=parsed, prior_titles=prior_titles)
        raw = await run_json_prompt_with_web(
            provider_id=provider_id,
            model=model,
            prompt=prompt,
            max_output_tokens=2000,
            reasoning_effort="high",
        )
        rows = extract_json_array(raw)
        if rows is None:
            return []

        out: list[NewsItemV3] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()

        for row in rows:
            if not isinstance(row, dict):
                continue

            title = self._clean_str(row.get("title"))
            url = self._clean_str(row.get("url"))
            if not title or not url:
                continue

            normalized_url = self._normalize_url(url)
            normalized_title = self._normalize_title(title)
            if normalized_url in seen_urls or normalized_title in seen_titles:
                continue
            seen_urls.add(normalized_url)
            seen_titles.add(normalized_title)

            summary = self._clean_str(row.get("summary")) or ""
            one_liner_comment = self._clean_str(row.get("one_liner_comment")) or ""
            if not summary:
                summary = one_liner_comment
            if not one_liner_comment:
                one_liner_comment = summary

            published_at = self._clean_str(row.get("published_at")) or "unknown"

            out.append(
                NewsItemV3(
                    title=title,
                    summary=summary,
                    url=url,
                    one_liner_comment=one_liner_comment,
                    source=self._clean_str(row.get("source")) or self._source_from_url(url),
                    published_at=published_at,
                    view=view,
                )
            )
        return out

    def _build_category_prompt(
        self,
        *,
        view: str,
        parsed: ParsedRequest,
        prior_titles: list[str],
    ) -> str:
        competitors = ", ".join(parsed.watch_competitors) if parsed.watch_competitors else "未指定"
        focus_topics = ", ".join(parsed.focus_topics) if parsed.focus_topics else "未指定"

        shared = (
            "あなたは日本の公認会計士向けのニュースアナリストです。\n"
            "監査クライアントに関連するニュースをWeb検索で収集してください。\n\n"
            "## 監査クライアント情報\n"
            f"- 企業名: {parsed.client_name}\n"
            f"- 業種: {parsed.client_industry}\n"
            f"- 競合企業: {competitors}\n"
            f"- 注力トピック: {focus_topics}\n"
            f"- 対象期間: 直近{parsed.lookback_days}日\n\n"
            "## 検索の基本方針\n"
            "- 日本語ソースを優先しますが、重要な英語ソースも含めてください\n"
            "- 信頼性の高いソース（日経、ロイター、Bloomberg、官公庁等）を優先してください\n"
            "- 必ず指定件数のニュースを返してください。重要度が低くても構いません\n\n"
        )

        if view == "self_company":
            view_prompt = (
                f"## 今回の検索カテゴリ: 自社（{parsed.client_name}）\n\n"
                f"{parsed.client_name}に直接関連する最新ニュースを**2〜3件**探してください。\n\n"
                "### 注意点\n"
                "- 監査人はクライアントのことをよく知っています。単なる日常的なプレスリリースではなく、\n"
                "  監査上のリスク判断に影響しうるニュースのみを選んでください\n"
                "- 例: 業績下方修正、減損リスク、訴訟、リコール、規制対応、重要な開示変更\n"
                "- 既知の情報より、新しい展開や想定外の事象を重視してください\n"
            )
        elif view == "peer_companies":
            view_prompt = (
                f"## 今回の検索カテゴリ: 他社（同業・競合企業）\n\n"
                f"{parsed.client_name}の競合企業や同業他社（{parsed.client_industry}）に関する"
                "最新ニュースを**3〜5件**探してください。\n\n"
                "### 注意点\n"
                "- 同業他社の業績動向、事業戦略、M&A、人事、業界再編など幅広く拾ってください\n"
                f"- {parsed.client_name}への直接的な影響がなくても、同じ業界の動きとして監査人が知っておくべきニュースを含めてください\n"
                "- 特に注目: 競合の業績発表、リコール、不正、価格改定、市場シェア変動\n"
                f"- 一言コメントでは、{parsed.client_name}の監査にどう関連しうるか簡潔に触れてください\n"
            )
        else:
            view_prompt = (
                f"## 今回の検索カテゴリ: マクロ経済\n\n"
                f"{parsed.client_industry}に関連しうるマクロ経済ニュースを**3〜5件**探してください。\n\n"
                "### 注意点\n"
                "- 為替、金利、原材料価格、関税、規制変更、会計基準改正、景気指標など幅広く拾ってください\n"
                f"- {parsed.client_industry}と直接関係が薄くても、企業の財務に影響しうるマクロ動向であれば含めてください\n"
                "- 特に注目: 日銀政策、為替動向、エネルギー価格、主要国の経済政策、業界規制\n"
                f"- 一言コメントでは、{parsed.client_name}の財務諸表のどこに影響しうるか簡潔に触れてください\n"
            )

        dedup_section = ""
        if prior_titles:
            titles_json = json.dumps(prior_titles, ensure_ascii=False)
            dedup_section = (
                "\n### 既に収集済みのニュース（重複回避のため）\n"
                f"{titles_json}\n"
            )

        output_format = (
            "\n### 出力形式\n"
            "JSON配列のみを返してください。各要素:\n"
            "{\n"
            '  "title": "ニュースのタイトル",\n'
            '  "summary": "2〜3文の概要（監査上の意味を含める）",\n'
            '  "url": "ソースURL",\n'
            '  "one_liner_comment": "監査人への一言コメント",\n'
            '  "source": "ソース名（例: 日経新聞）",\n'
            '  "published_at": "公開日（ISO-8601形式、不明なら unknown）"\n'
            "}\n"
        )

        return shared + view_prompt + dedup_section + output_format

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _item_to_dict(self, item: NewsItemV3) -> dict[str, Any]:
        news_id = self._build_news_id(url=item.url, title=item.title, view=item.view)
        return {
            "news_id": news_id,
            "title": item.title,
            "summary": item.summary,
            "url": item.url,
            "one_liner_comment": item.one_liner_comment,
            "source": item.source,
            "published_at": item.published_at,
            "view": item.view,
        }

    def _render_items(self, items: list[NewsItemV3]) -> list[str]:
        if not items:
            return ["- 該当ニュースは見つかりませんでした。"]
        lines: list[str] = []
        for idx, item in enumerate(items, start=1):
            lines.extend([
                f"{idx}. {item.title}",
                f"- 概要: {item.summary}",
                f"- URL: {item.url}",
                f"- 一言コメント: {item.one_liner_comment}",
            ])
        return lines

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _build_news_id(self, *, url: str, title: str, view: str) -> str:
        key = f"{self._normalize_url(url)}|{self._normalize_title(title)}|{view}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

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


def build_skill() -> Skill:
    return AuditNewsActionBriefSkill()
