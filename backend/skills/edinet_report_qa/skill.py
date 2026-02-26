import json
import re
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.skills_runtime.base import Skill, SkillMetadata

_SKILL_DIR = Path(__file__).resolve().parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.append(str(_SKILL_DIR))

from company_resolver import CompanyCandidate, CompanyResolver  # noqa: E402
from documents_repository import DocumentsRepository  # noqa: E402
from intent_parser import IntentParser, ParsedIntent  # noqa: E402
from llm_client import extract_json_object, run_json_prompt  # noqa: E402
from section_catalog import SectionCatalog  # noqa: E402
from xbrl_extractor import XbrlExtractor  # noqa: E402


class EdinetReportQASkill(Skill):
    metadata = SkillMetadata(
        id="edinet_report_qa",
        name="EDINET Annual Report QA",
        description=(
            "企業/年度/セクションを質問から解釈してEDINET APIから有価証券報告書XBRLを取得し、"
            "回答補助コンテキストを生成します。"
        ),
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> str:
        settings = get_settings()
        api_key = (settings.edinet_api_key or "").strip()
        if not api_key:
            return "EDINET APIキーが未設定です。`EDINET_API_KEY` を `.env` に設定してください。"

        section_catalog = SectionCatalog.load(self._sections_path())
        parser = IntentParser()
        parsed_intent = await parser.parse(
            user_text=user_text,
            history=history,
            skill_context=skill_context,
            section_catalog=section_catalog,
        )

        selected_sections, section_reasons, unresolved_sections = section_catalog.select_sections(
            question=user_text,
            intent_section_queries=parsed_intent.sections,
            max_sections=3,
        )

        if not parsed_intent.companies:
            return self._build_clarification_response(
                user_text=user_text,
                parsed_intent=parsed_intent,
                unresolved_sections=unresolved_sections,
                section_reasons=section_reasons,
                ambiguity_lines=["企業名またはEDINETコードを特定できませんでした。"],
                candidate_lines=[],
            )

        csv_path = self._local_code_list_path()
        if not csv_path.exists():
            return (
                f"企業コード一覧CSVが見つかりません: `{csv_path}`\n"
                "`backend/skills/edinet_report_qa/docs/EdinetcodeDlInfo.csv` を配置してください。"
            )

        resolver = CompanyResolver(csv_raw=csv_path.read_bytes())
        api_errors: list[str] = []
        extraction_hits = 0

        async with httpx.AsyncClient(timeout=30.0) as client:
            repo = DocumentsRepository(
                client=client,
                api_key=api_key,
                cache_root=self._cache_root(),
                ttl_hours=self._cache_ttl_hours(),
                force_refresh=self._is_retry_request(user_text),
            )

            fallback_entries = await repo.collect_recent_company_entries(
                lookback_days=self._lookback_days(),
                api_errors=api_errors,
            )

            resolutions = await resolver.resolve_many(
                company_queries=parsed_intent.companies,
                question=user_text,
                fallback_entries=fallback_entries,
                disambiguator=lambda q, token, cands: self._disambiguate_company_candidate(
                    question=q,
                    token=token,
                    candidates=cands,
                    skill_context=skill_context,
                ),
            )

            ambiguous = [res for res in resolutions if not res.ok and res.candidates]
            if ambiguous:
                ambiguity_lines: list[str] = []
                candidate_lines: list[str] = []
                for res in ambiguous:
                    ambiguity_lines.append(f"`{res.query}` は候補が複数あり確定できません。")
                    for cand in res.candidates[:3]:
                        candidate_lines.append(
                            f"- {res.query}: {cand.company_name} (EDINET={cand.edinet_code}, 証券={cand.sec_code or '-'})"
                        )
                return self._build_clarification_response(
                    user_text=user_text,
                    parsed_intent=parsed_intent,
                    unresolved_sections=unresolved_sections,
                    section_reasons=section_reasons,
                    ambiguity_lines=ambiguity_lines,
                    candidate_lines=candidate_lines,
                )

            unresolved = [res for res in resolutions if not res.ok]
            if unresolved:
                ambiguity_lines = [f"`{res.query}`: {res.reason}" for res in unresolved]
                return self._build_clarification_response(
                    user_text=user_text,
                    parsed_intent=parsed_intent,
                    unresolved_sections=unresolved_sections,
                    section_reasons=section_reasons,
                    ambiguity_lines=ambiguity_lines,
                    candidate_lines=[],
                )

            lines = [
                "EDINET有報抽出コンテキスト",
                "",
                "## 解釈結果",
                f"- 質問: {user_text}",
                f"- 企業候補: {', '.join(parsed_intent.companies)}",
                f"- 年度: {parsed_intent.fiscal_year if parsed_intent.fiscal_year is not None else '未指定(最新有報を採用)'}",
                f"- 意図解析ソース: {parsed_intent.source}",
                "- 選択セクション:",
            ]
            explicit_periods = parsed_intent.report_periods or self._extract_period_specs(user_text)
            effective_lookback_days = self._effective_lookback_days(explicit_periods=explicit_periods)
            if explicit_periods:
                lines.append(
                    "- 期指定: "
                    + ", ".join([f"{year}年{month}月期" for year, month in explicit_periods])
                )
            for section in selected_sections:
                lines.append(
                    f"  - {section.section_id} {section.title}（理由: {section_reasons.get(section.section_id, '規則ベース')}）"
                )
            if unresolved_sections:
                lines.append(f"- 解決できなかったセクション指定: {', '.join(unresolved_sections)}")

            lines.extend(["", "## 抽出本文"])

            for company in [res for res in resolutions if res.ok]:
                lines.extend(["", f"### {company.company_name or company.query}"])
                target_periods = explicit_periods or [None]
                for period_spec in target_periods:
                    period_year = period_spec[0] if period_spec is not None else None
                    period_month = period_spec[1] if period_spec is not None else None

                    filing = await repo.find_latest_annual_filing(
                        edinet_code=company.edinet_code or "",
                        company_name=company.company_name or company.query,
                        lookback_days=effective_lookback_days,
                        fiscal_year=parsed_intent.fiscal_year if period_spec is None else None,
                        period_end_year=period_year,
                        period_end_month=period_month,
                        api_errors=api_errors,
                    )
                    if filing is None:
                        year_note = (
                            f"{period_year}年{period_month}月期"
                            if period_year is not None and period_month is not None
                            else (
                                f"{parsed_intent.fiscal_year}年度"
                                if parsed_intent.fiscal_year is not None
                                else "最新年度"
                            )
                        )
                        lines.append(
                            f"- {year_note} の有価証券報告書（docTypeCode 120/130）が見つかりませんでした。"
                        )
                        continue

                    lines.append(
                        f"- 採用書類: docID={filing.doc_id}, docType={filing.doc_type_code}, submit={filing.submit_datetime}, periodEnd={filing.period_end or '-'}"
                    )
                    xbrl_path = await repo.download_xbrl(doc_id=filing.doc_id, api_errors=api_errors)
                    if xbrl_path is None:
                        lines.append("- XBRL取得に失敗しました。")
                        continue

                    extractor = XbrlExtractor(xbrl_path=xbrl_path)
                    period_label = (
                        f"{period_year}年{period_month}月期"
                        if period_year is not None and period_month is not None
                        else (filing.period_end or "対象期間")
                    )
                    lines.append(f"- 抽出結果（{period_label}）:")
                    for section in selected_sections:
                        text, source = extractor.extract_first_available(section.tag_candidates)
                        if text is None:
                            lines.append(f"  - {section.section_id} {section.title}: {source}")
                            continue
                        extraction_hits += 1
                        clipped = self._clip_text(text, max_chars=20000)
                        lines.append(
                            f"  - {section.section_id} {section.title} [tag={source}]\n{self._indent(clipped, '    ')}"
                        )

            lines.extend(["", "## 不足・曖昧点"])
            if parsed_intent.needs_clarification:
                reason = parsed_intent.clarification_reason or "質問解釈で追加情報が必要です。"
                lines.append(f"- {reason}")
            else:
                lines.append("- 重大な曖昧点は検出されませんでした。")

            if extraction_hits == 0:
                lines.append("- XBRL本文が抽出できなかったため、最終回答は取得失敗理由の説明に限定してください。")

            if unresolved_sections:
                lines.append(
                    "- セクション辞書に未定義の指定があります。必要なら `backend/skills/edinet_report_qa/docs/sections.json` に追記してください。"
                )

            if api_errors:
                lines.append("- EDINET APIエラー:")
                for err in sorted(set(api_errors)):
                    lines.append(f"  - {err}")

            lines.extend(
                [
                    "",
                    "## 回答ポリシー",
                    "- 上記抽出テキストを根拠として回答すること。",
                    "- 根拠にない推測は避け、不足情報は不足と明示すること。",
                    "- 企業ごとの差異を混同しないこと。",
                ]
            )
            return "\n".join(lines)

    async def _disambiguate_company_candidate(
        self,
        *,
        question: str,
        token: str,
        candidates: list[CompanyCandidate],
        skill_context: dict[str, Any] | None,
    ) -> str | None:
        provider_id = str((skill_context or {}).get("provider_id") or "openai")
        model = str((skill_context or {}).get("model") or "").strip()
        if not model or not candidates:
            return None

        payload = [asdict(item) for item in candidates[:8]]
        prompt = (
            "ユーザー質問と候補企業リストから、最も妥当な1社を選択してください。"
            "JSONオブジェクトのみを返し、形式は {\"edinet_code\": \"E12345\"} または"
            " {\"edinet_code\": null} としてください。"
            f"\n質問: {question}"
            f"\n曖昧トークン: {token}"
            f"\n候補: {json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            output_text = await run_json_prompt(
                provider_id=provider_id,
                model=model,
                prompt=prompt,
                max_output_tokens=120,
            )
        except Exception:
            return None

        parsed = extract_json_object(output_text)
        if not parsed:
            return None
        code = parsed.get("edinet_code")
        if isinstance(code, str) and re.fullmatch(r"E\d{5}", code.strip(), flags=re.IGNORECASE):
            return code.strip().upper()
        return None

    def _build_clarification_response(
        self,
        *,
        user_text: str,
        parsed_intent: ParsedIntent,
        unresolved_sections: list[str],
        section_reasons: dict[str, str],
        ambiguity_lines: list[str],
        candidate_lines: list[str],
    ) -> str:
        lines = [
            "EDINET有報抽出コンテキスト",
            "",
            "## 解釈結果",
            f"- 質問: {user_text}",
            f"- 企業候補: {', '.join(parsed_intent.companies) if parsed_intent.companies else '(抽出なし)'}",
            f"- 年度: {parsed_intent.fiscal_year if parsed_intent.fiscal_year is not None else '未指定(最新有報を採用予定)'}",
            (
                "- 期指定(解析): "
                + ", ".join([f"{year}年{month}月期" for year, month in parsed_intent.report_periods])
                if parsed_intent.report_periods
                else "- 期指定(解析): なし"
            ),
            f"- 意図解析ソース: {parsed_intent.source}",
            "",
            "## 不足・曖昧点",
        ]
        for item in ambiguity_lines:
            lines.append(f"- {item}")
        if parsed_intent.clarification_reason:
            lines.append(f"- 補足: {parsed_intent.clarification_reason}")
        if unresolved_sections:
            lines.append(f"- 解決できなかったセクション指定: {', '.join(unresolved_sections)}")
        if section_reasons:
            lines.append("- 現時点のセクション解釈:")
            for sec_id, reason in section_reasons.items():
                lines.append(f"  - {sec_id}: {reason}")

        if candidate_lines:
            lines.extend(["", "候補:"])
            lines.extend(candidate_lines)

        lines.extend(
            [
                "",
                "次入力テンプレート:",
                "- `会社名(またはEDINETコード) + 年度(例: 2024年度) + 見たい項目(例: 事業等のリスク)`",
                "",
                "## 回答ポリシー",
                "- 現時点では本文根拠が不足しているため、断定回答はしないこと。",
                "- まず不足情報の再指定を促すこと。",
            ]
        )
        return "\n".join(lines)

    def _sections_path(self) -> Path:
        return _SKILL_DIR / "docs" / "sections.json"

    def _local_code_list_path(self) -> Path:
        return _SKILL_DIR / "docs" / "EdinetcodeDlInfo.csv"

    def _cache_root(self) -> Path:
        settings = get_settings()
        if settings.edinet_cache_dir:
            return Path(settings.edinet_cache_dir)
        return Path(tempfile.gettempdir()) / "edinet-skill-cache"

    def _cache_ttl_hours(self) -> int:
        try:
            value = int(get_settings().edinet_cache_ttl_hours)
        except (TypeError, ValueError):
            value = 24
        return max(1, value)

    def _lookback_days(self) -> int:
        try:
            value = int(get_settings().edinet_lookback_days)
        except (TypeError, ValueError):
            value = 365
        return max(7, min(3650, value))

    def _clip_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...（省略）"

    def _indent(self, text: str, prefix: str) -> str:
        return "\n".join(f"{prefix}{line}" for line in text.splitlines())

    def _extract_period_specs(self, text: str) -> list[tuple[int, int]]:
        found: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for match in re.finditer(r"(20\d{2})\s*年\s*(\d{1,2})\s*月期", text):
            year = int(match.group(1))
            month = int(match.group(2))
            key = (year, month)
            if month < 1 or month > 12:
                continue
            if key in seen:
                continue
            seen.add(key)
            found.append(key)
        return found

    def _is_retry_request(self, text: str) -> bool:
        normalized = text.lower()
        retry_markers = [
            "再取得",
            "取り直",
            "再実行",
            "もう一回",
            "再検索",
            "retry",
            "refetch",
            "refresh",
        ]
        return any(marker in normalized for marker in retry_markers)

    def _effective_lookback_days(self, *, explicit_periods: list[tuple[int, int]]) -> int:
        base = self._lookback_days()
        if not explicit_periods:
            return base

        oldest_year, oldest_month = min(explicit_periods)
        # periodEnd(月末)から提出時期(概ね3か月後)を見込んで探索幅を計算する。
        period_end = self._last_day_of_month(oldest_year, oldest_month)
        expected_submit = period_end + timedelta(days=120)
        required = (datetime.now(UTC).date() - expected_submit).days + 45
        return max(base, min(max(7, required), 3650))

    def _last_day_of_month(self, year: int, month: int) -> date:
        if month == 12:
            first_next = date(year + 1, 1, 1)
        else:
            first_next = date(year, month + 1, 1)
        return first_next - timedelta(days=1)


def build_skill() -> Skill:
    return EdinetReportQASkill()
