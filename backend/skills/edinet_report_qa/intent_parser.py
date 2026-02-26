import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.append(str(_MODULE_DIR))

from llm_client import extract_json_object, run_json_prompt
from section_catalog import SectionCatalog


@dataclass
class ParsedIntent:
    companies: list[str]
    fiscal_year: int | None
    report_periods: list[tuple[int, int]]
    sections: list[str]
    needs_clarification: bool
    clarification_reason: str
    source: str


class IntentParser:
    async def parse(
        self,
        *,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, str] | None,
        section_catalog: SectionCatalog,
    ) -> ParsedIntent:
        llm_parsed = await self._parse_by_llm(
            user_text=user_text,
            history=history,
            skill_context=skill_context,
            section_catalog=section_catalog,
        )
        if llm_parsed is not None:
            return llm_parsed

        return self._parse_by_rules(user_text=user_text, history=history)

    async def _parse_by_llm(
        self,
        *,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, str] | None,
        section_catalog: SectionCatalog,
    ) -> ParsedIntent | None:
        provider_id = str((skill_context or {}).get("provider_id") or "openai")
        model = str((skill_context or {}).get("model") or "").strip()
        if not model:
            return None

        recent_user = [
            item.get("content", "")
            for item in history[-8:]
            if item.get("role") == "user" and item.get("content")
        ]
        section_hints = [
            {"id": sec.section_id, "title": sec.title, "aliases": sec.aliases}
            for sec in section_catalog.sections
        ]

        prompt = (
            "あなたは有価証券報告書QAの意図解析器です。"
            "質問文を読み、対象企業・年度・参照セクションをJSONで抽出してください。"
            "説明文は不要で、JSONオブジェクトのみを返してください。"
            "\n出力スキーマ:\n"
            "{\n"
            '  "companies": string[],\n'
            '  "fiscal_year": number | null,\n'
            '  "report_periods": [{"year": number, "month": number}],\n'
            '  "sections": string[],\n'
            '  "needs_clarification": boolean,\n'
            '  "clarification_reason": string\n'
            "}\n"
            "注意:\n"
            "- sections は section id か title を返す\n"
            "- 年度指定が無ければ fiscal_year は null\n"
            "- report_periods は比較に必要な決算期を過不足なく推定する\n"
            "- report_periods が空なら fiscal_year を使う\n"
            "- 企業が推定不能なら needs_clarification=true\n"
            f"\n会話履歴(直近ユーザー発話): {json.dumps(recent_user, ensure_ascii=False)}"
            f"\nセクション候補: {json.dumps(section_hints, ensure_ascii=False)}"
            f"\nユーザー質問: {user_text}"
        )

        try:
            output_text = await run_json_prompt(
                provider_id=provider_id,
                model=model,
                prompt=prompt,
                max_output_tokens=400,
            )
        except Exception:
            return None

        parsed = extract_json_object(output_text)
        if parsed is None:
            return None

        companies = [str(item).strip() for item in parsed.get("companies", []) if str(item).strip()]
        fiscal_year = parsed.get("fiscal_year")
        if isinstance(fiscal_year, str) and fiscal_year.isdigit():
            fiscal_year = int(fiscal_year)
        if not isinstance(fiscal_year, int):
            fiscal_year = None

        report_periods = self._extract_period_specs_from_json(parsed.get("report_periods"))
        if not report_periods:
            report_periods = self._extract_period_specs(f"{user_text}\n" + "\n".join(recent_user))

        sections = [str(item).strip() for item in parsed.get("sections", []) if str(item).strip()]
        needs_clarification = bool(parsed.get("needs_clarification", False))
        clarification_reason = str(parsed.get("clarification_reason") or "").strip()

        if not companies:
            companies = self._extract_company_tokens(f"{user_text}\n" + "\n".join(recent_user))
            if companies and not clarification_reason:
                clarification_reason = "LLM抽出が空のため規則抽出を利用"

        return ParsedIntent(
            companies=companies,
            fiscal_year=fiscal_year,
            report_periods=report_periods,
            sections=sections,
            needs_clarification=needs_clarification,
            clarification_reason=clarification_reason,
            source="llm",
        )

    def _parse_by_rules(self, *, user_text: str, history: list[dict[str, str]]) -> ParsedIntent:
        context = "\n".join(
            [
                item.get("content", "")
                for item in history[-8:]
                if item.get("role") == "user" and item.get("content")
            ]
        )
        combined = f"{context}\n{user_text}".strip()

        companies = self._extract_company_tokens(combined)
        fiscal_year = self._extract_fiscal_year(combined)
        report_periods = self._extract_period_specs(combined)
        sections = self._extract_section_tokens(user_text)

        needs_clarification = not companies
        reason = "企業名が抽出できませんでした" if needs_clarification else ""

        return ParsedIntent(
            companies=companies,
            fiscal_year=fiscal_year,
            report_periods=report_periods,
            sections=sections,
            needs_clarification=needs_clarification,
            clarification_reason=reason,
            source="rule",
        )

    def _extract_fiscal_year(self, text: str) -> int | None:
        patterns = [
            r"(20\d{2})\s*年度",
            r"fy\s*(20\d{2})",
            r"(20\d{2})\s*年",
        ]
        normalized = unicodedata.normalize("NFKC", text).lower()
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            year = int(match.group(1))
            if 1990 <= year <= 2100:
                return year
        return None

    def _extract_period_specs_from_json(self, value: object) -> list[tuple[int, int]]:
        if not isinstance(value, list):
            return []
        items: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for row in value:
            if not isinstance(row, dict):
                continue
            year = row.get("year")
            month = row.get("month")
            if isinstance(year, str) and year.isdigit():
                year = int(year)
            if isinstance(month, str) and month.isdigit():
                month = int(month)
            if not isinstance(year, int) or not isinstance(month, int):
                continue
            if year < 1990 or year > 2100 or month < 1 or month > 12:
                continue
            key = (year, month)
            if key in seen:
                continue
            seen.add(key)
            items.append(key)
        return items

    def _extract_period_specs(self, text: str) -> list[tuple[int, int]]:
        normalized = unicodedata.normalize("NFKC", text)
        found: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        patterns = [
            r"(20\d{2})\s*年\s*(\d{1,2})\s*月期",
            r"(20\d{2})\s*/\s*(\d{1,2})\s*期",
            r"(20\d{2})\s*-\s*(\d{1,2})\s*期",
            r"(20\d{2})\s*\.\s*(\d{1,2})\s*期",
            r"(20\d{2})\s*/\s*(\d{1,2})(?!\d)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, normalized):
                year = int(match.group(1))
                month = int(match.group(2))
                key = (year, month)
                if year < 1990 or year > 2100 or month < 1 or month > 12:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                found.append(key)
        return found

    def _extract_section_tokens(self, text: str) -> list[str]:
        hits: list[str] = []
        for pattern in [r"\b\d-\d(?:-\d)?\b", r"\b\d\b"]:
            for match in re.findall(pattern, text):
                hits.append(match)
        for literal in ["事業等のリスク", "サステナビリティ", "経営成績", "キャッシュ・フロー", "配当政策", "ガバナンス"]:
            if literal in text:
                hits.append(literal)
        return hits

    def _extract_company_tokens(self, text: str) -> list[str]:
        tokens: list[str] = []

        for match in re.findall(r"E\d{5}", text, flags=re.IGNORECASE):
            code = match.upper()
            if code not in tokens:
                tokens.append(code)

        for match in re.findall(r"証券コード\s*[:：]?\s*(\d{4})", text):
            if match not in tokens:
                tokens.append(match)

        split_parts = re.split(r"[、,\n]|と|および|及び|ならびに", text)
        stopwords = {
            "有価証券報告書",
            "有報",
            "edinet",
            "api",
            "xbrl",
            "会社",
            "企業",
            "質問",
            "分析",
            "について",
            "教えて",
            "調べて",
            "見て",
            "して",
            "ください",
        }

        for part in split_parts:
            cleaned = self._clean_company_token(self._trim_non_company_suffix(part))
            if not cleaned:
                continue
            if _norm_text(cleaned) in stopwords:
                continue
            if cleaned not in tokens:
                tokens.append(cleaned)

        company_like = re.findall(
            r"([一-龥ぁ-んァ-ヶA-Za-z0-9・ー＆&\-]+?(?:株式会社|ホールディングス|グループ|HD|自動車))",
            text,
        )
        for name in company_like:
            cleaned = self._clean_company_token(name)
            if cleaned and cleaned not in tokens:
                tokens.append(cleaned)

        return tokens

    def _trim_non_company_suffix(self, text: str) -> str:
        trimmed = re.sub(
            r"(の)?(事業|リスク|比較|分析|業績|強み|弱み|課題|概要|状況|について).*$",
            "",
            text,
        )
        return trimmed.strip()

    def _clean_company_token(self, text: str) -> str | None:
        cleaned = text.strip().strip("。.!?()（）[]「」『』\"'")
        cleaned = re.sub(r"^(と|および|及び|ならびに)", "", cleaned).strip()
        cleaned = re.sub(r"^証券コード\s*[:：]?\s*", "", cleaned).strip()
        if not cleaned or len(cleaned) <= 1 or len(cleaned) > 80:
            return None
        return cleaned


def _norm_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower().strip()
    normalized = normalized.replace("株式会社", "")
    normalized = normalized.replace("(株)", "")
    normalized = normalized.replace(" ", "")
    normalized = normalized.replace("　", "")
    return normalized
