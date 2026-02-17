import csv
import html as html_module
import io
import json
import re
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from lxml import etree
from openai import AsyncOpenAI

from app.config import get_settings
from app.skills_runtime.base import Skill, SkillMetadata

EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
EDINET_CODELIST_CSV = (
    "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/EdinetcodeDl?mode=2"
)
DOC_TYPE_CODES = {"120", "130"}
DEFAULT_LOOKBACK_DAYS = 365


@dataclass
class SectionDefinition:
    section_id: str
    title: str
    tag_candidates: list[str]
    keywords: list[str]


@dataclass
class CompanyResolution:
    query: str
    edinet_code: str | None
    sec_code: str | None
    company_name: str | None
    reason: str

    @property
    def ok(self) -> bool:
        return bool(self.edinet_code)


@dataclass
class FilingMatch:
    doc_id: str
    doc_type_code: str
    submit_datetime: str
    filer_name: str
    period_end: str | None


class XbrlExtractor:
    def __init__(self, xbrl_path: Path):
        parser = etree.XMLParser(recover=True)
        self.tree = etree.parse(str(xbrl_path), parser=parser)
        self.root = self.tree.getroot()
        self._available_tags = {
            etree.QName(el).localname for el in self.root.iter() if isinstance(el.tag, str)
        }
        self._id_index: dict[str, Any] = {}
        for el in self.root.iter():
            if not isinstance(el.tag, str):
                continue
            el_id = el.get("id")
            if el_id:
                self._id_index[el_id] = el

    def extract_first_available(self, tag_candidates: list[str]) -> tuple[str | None, str]:
        if not tag_candidates:
            return None, "未対応セクション（XBRLタグ未定義）"

        selected_tag = next((tag for tag in tag_candidates if tag in self._available_tags), None)
        if selected_tag is None:
            return None, "対応タグが該当XBRL内に見つかりませんでした"

        texts: list[str] = []
        for el in self.root.iter():
            if not isinstance(el.tag, str):
                continue
            if etree.QName(el).localname != selected_tag:
                continue
            raw_payload = self._collect_payload_with_continuation(el)
            if not raw_payload:
                continue
            decoded = html_module.unescape(raw_payload)
            plain_text = self._html_to_text(decoded)
            if plain_text.strip():
                texts.append(plain_text.strip())

        if not texts:
            return None, f"{selected_tag} は見つかりましたが本文抽出できませんでした"

        return "\n\n".join(texts), selected_tag

    def _collect_payload_with_continuation(self, el: Any) -> str:
        chunks: list[str] = []
        head = self._element_payload(el)
        if head:
            chunks.append(head)

        continued_at = el.get("continuedAt")
        visited: set[str] = set()
        while continued_at and continued_at not in visited:
            visited.add(continued_at)
            cont = self._id_index.get(continued_at)
            if cont is None:
                break
            cont_payload = self._element_payload(cont)
            if cont_payload:
                chunks.append(cont_payload)
            continued_at = cont.get("continuedAt")

        return "".join(chunks).strip()

    def _element_payload(self, el: Any) -> str:
        parts: list[str] = []
        if el.text:
            parts.append(el.text)
        for child in el:
            parts.append(etree.tostring(child, encoding="unicode"))
        return "".join(parts)

    def _html_to_text(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content, "html.parser")
        for table in soup.find_all("table"):
            table_rows: list[str] = []
            for tr in table.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
                if cells:
                    table_rows.append(" | ".join(cells))
            replacement = "\n".join(table_rows) if table_rows else table.get_text(" ", strip=True)
            table.replace_with(f"\n{replacement}\n")

        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)


class EdinetReportQASkill(Skill):
    metadata = SkillMetadata(
        id="edinet_report_qa",
        name="EDINET Annual Report QA",
        description=(
            "企業を特定してEDINET APIから有価証券報告書XBRLを取得し、"
            "質問に関連するセクションを抽出して回答補助コンテキストを生成します。"
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
            return (
                "EDINET APIキーが未設定です。`EDINET_API_KEY` を `.env` に設定してください。"
            )
        explicit_codes = self._extract_explicit_edinet_codes(user_text)
        if not explicit_codes:
            return (
                "企業指定はEDINETコードで入力してください。形式: `[E00001, E12345]`\n"
                "例: `[E02144, E01777] の事業等のリスクを比較して`"
            )

        section_defs = self._build_sections()
        selected, routing_reasons = await self._route_sections(
            user_text,
            section_defs,
            skill_context=skill_context,
        )

        context_text = self._build_company_context(user_text=user_text, history=history)
        docs_by_date: dict[str, list[dict[str, Any]]] = {}
        extraction_hits = 0
        api_errors: list[str] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            code_index = await self._load_code_index(client=client)
            warnings: list[str] = []
            resolutions = self._build_resolutions_from_edinet_codes(
                explicit_codes=explicit_codes,
                code_index=code_index or [],
            )
            if not code_index:
                warnings.append("EDINETコード一覧CSVを取得できなかったため、企業名はコード表示になります。")
            ok_companies = [res for res in resolutions if res.ok]

            lines = [
                "EDINET有報抽出コンテキスト",
                f"質問: {user_text}",
                "",
                "選択セクション（上位）:",
            ]
            for sec in selected:
                reason = routing_reasons.get(sec.section_id, "規則ベース")
                lines.append(f"- {sec.section_id} {sec.title}（理由: {reason}）")
            if warnings:
                lines.extend(["", "注意:"])
                for warning in warnings:
                    lines.append(f"- {warning}")

            unresolved = [res for res in resolutions if not res.ok]
            if unresolved:
                lines.extend(["", "企業解決できなかった入力:"])
                for res in unresolved:
                    lines.append(f"- `{res.query}`: {res.reason}")

            if not ok_companies:
                lines.extend(
                    [
                        "",
                        "企業を特定できなかったため抽出処理を実行できませんでした。",
                        "EDINETコードを `[E12345]` 形式で指定してください。",
                    ]
                )
                return "\n".join(lines)

            for company in ok_companies:
                lines.extend(["", f"## {company.company_name or company.query}"])
                filing = await self._find_latest_annual_filing(
                    client=client,
                    api_key=api_key,
                    company=company,
                    docs_by_date=docs_by_date,
                    api_errors=api_errors,
                )
                if filing is None:
                    lines.append("- 有価証券報告書（docTypeCode 120/130）が検索範囲で見つかりませんでした。")
                    continue

                lines.append(
                    f"- 採用書類: docID={filing.doc_id}, docType={filing.doc_type_code}, submit={filing.submit_datetime}"
                )
                xbrl_path = await self._prepare_xbrl_file(
                    client=client,
                    api_key=api_key,
                    doc_id=filing.doc_id,
                    api_errors=api_errors,
                )
                if xbrl_path is None:
                    lines.append("- XBRL取得に失敗しました。")
                    continue

                extractor = XbrlExtractor(xbrl_path=xbrl_path)
                unsupported_sections: list[str] = []
                lines.append("- 抽出結果:")
                for section in selected:
                    text, source = extractor.extract_first_available(section.tag_candidates)
                    if text is None:
                        if not section.tag_candidates:
                            unsupported_sections.append(f"{section.section_id} {section.title}")
                        lines.append(f"  - {section.section_id} {section.title}: {source}")
                        continue
                    clipped = self._clip_text(text, max_chars=20000)
                    extraction_hits += 1
                    lines.append(
                        f"  - {section.section_id} {section.title} [tag={source}]\n{self._indent(clipped, '    ')}"
                    )

                if unsupported_sections:
                    lines.append("- 未対応セクション:")
                    for item in unsupported_sections:
                        lines.append(f"  - {item}")

            if api_errors:
                lines.extend(["", "EDINET APIエラー:"])
                for err in sorted(set(api_errors)):
                    lines.append(f"- {err}")

            lines.extend(
                [
                    "",
                    "回答ガイド:",
                    "- 上記抽出テキストを根拠として回答すること。",
                    "- 根拠にない推測は避け、不足情報は不足と明示すること。",
                    "- 企業ごとの差異を混同しないこと。",
                ]
            )
            if extraction_hits == 0:
                lines.extend(
                    [
                        "- 今回はXBRL本文を取得できていないため、一般知識ベースで回答しないこと。",
                        "- 取得失敗理由のみを簡潔に伝え、再実行に必要な情報（企業コード/年度）を案内すること。",
                    ]
                )
            return "\n".join(lines)

    def _build_resolutions_from_edinet_codes(
        self,
        *,
        explicit_codes: list[str],
        code_index: list[dict[str, str]],
    ) -> list[CompanyResolution]:
        by_edinet = {row["edinet_code"]: row for row in code_index if row.get("edinet_code")}
        results: list[CompanyResolution] = []
        seen: set[str] = set()
        for code in explicit_codes:
            upper = code.upper()
            if upper in seen:
                continue
            seen.add(upper)
            row = by_edinet.get(upper)
            if row:
                results.append(
                    CompanyResolution(
                        query=upper,
                        edinet_code=upper,
                        sec_code=(row.get("sec_code") or None),
                        company_name=(row.get("company_name") or upper),
                        reason="EDINETコード指定",
                    )
                )
            else:
                results.append(
                    CompanyResolution(
                        query=upper,
                        edinet_code=upper,
                        sec_code=None,
                        company_name=upper,
                        reason="EDINETコード指定（企業名未解決）",
                    )
                )
        return results

    def _build_company_context(self, user_text: str, history: list[dict[str, str]]) -> str:
        recent_user_messages = [
            item.get("content", "")
            for item in history[-8:]
            if item.get("role") == "user" and item.get("content")
        ]
        return "\n".join([*recent_user_messages, user_text])

    def _resolve_companies(
        self,
        *,
        context_text: str,
        code_index: list[dict[str, str]],
    ) -> list[CompanyResolution]:
        tokens = self._extract_company_tokens(context_text)
        if not tokens:
            return [
                CompanyResolution(
                    query="(未指定)",
                    edinet_code=None,
                    sec_code=None,
                    company_name=None,
                    reason="企業指定が検出できませんでした",
                )
            ]

        edinet_map = {row["edinet_code"]: row for row in code_index if row["edinet_code"]}
        sec_map = {row["sec_code"]: row for row in code_index if row["sec_code"]}
        normalized_name_map: dict[str, list[dict[str, str]]] = {}
        for row in code_index:
            name_norm = self._norm_text(row["company_name"])
            if not name_norm:
                continue
            normalized_name_map.setdefault(name_norm, []).append(row)

        results: list[CompanyResolution] = []
        seen_edinet: set[str] = set()
        for token in tokens:
            normalized = self._norm_text(token)
            if not normalized:
                continue

            edinet_match = re.fullmatch(r"E\d{5}", normalized.upper())
            if edinet_match:
                row = edinet_map.get(edinet_match.group(0))
                if row:
                    if row["edinet_code"] in seen_edinet:
                        continue
                    seen_edinet.add(row["edinet_code"])
                    results.append(self._build_company_resolution(token, row, "EDINETコード一致"))
                else:
                    results.append(
                        CompanyResolution(
                            query=token,
                            edinet_code=None,
                            sec_code=None,
                            company_name=None,
                            reason="EDINETコードがコード一覧に見つかりません",
                        )
                    )
                continue

            sec_match = re.fullmatch(r"\d{4}", normalized)
            if sec_match:
                row = sec_map.get(sec_match.group(0))
                if row:
                    if row["edinet_code"] in seen_edinet:
                        continue
                    seen_edinet.add(row["edinet_code"])
                    results.append(self._build_company_resolution(token, row, "証券コード一致"))
                else:
                    results.append(
                        CompanyResolution(
                            query=token,
                            edinet_code=None,
                            sec_code=sec_match.group(0),
                            company_name=None,
                            reason="証券コードがコード一覧に見つかりません",
                        )
                    )
                continue

            exact = normalized_name_map.get(normalized, [])
            if len(exact) == 1:
                row = exact[0]
                if row["edinet_code"] in seen_edinet:
                    continue
                seen_edinet.add(row["edinet_code"])
                results.append(self._build_company_resolution(token, row, "社名完全一致"))
                continue
            if len(exact) > 1:
                results.append(
                    CompanyResolution(
                        query=token,
                        edinet_code=None,
                        sec_code=None,
                        company_name=None,
                        reason="同名の候補が複数あります。EDINETコードか証券コードを指定してください",
                    )
                )
                continue

            contains = [
                row
                for row in code_index
                if normalized in self._norm_text(row["company_name"])
            ]
            if len(contains) == 1:
                row = contains[0]
                if row["edinet_code"] in seen_edinet:
                    continue
                seen_edinet.add(row["edinet_code"])
                results.append(self._build_company_resolution(token, row, "社名部分一致"))
                continue
            if len(contains) > 1:
                results.append(
                    CompanyResolution(
                        query=token,
                        edinet_code=None,
                        sec_code=None,
                        company_name=None,
                        reason="社名候補が複数あります。EDINETコードか証券コードを指定してください",
                    )
                )
                continue

            results.append(
                CompanyResolution(
                    query=token,
                    edinet_code=None,
                    sec_code=None,
                    company_name=None,
                    reason="企業候補をコード一覧から特定できませんでした",
                )
            )

        return results

    def _build_company_resolution(
        self,
        query: str,
        row: dict[str, str],
        reason: str,
    ) -> CompanyResolution:
        return CompanyResolution(
            query=query,
            edinet_code=row["edinet_code"],
            sec_code=row["sec_code"],
            company_name=row["company_name"],
            reason=reason,
        )

    async def _load_code_index(self, client: httpx.AsyncClient) -> list[dict[str, str]] | None:
        cache_root = self._cache_root()
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_file = cache_root / "edinet_code_list.csv"
        ttl_hours = self._cache_ttl_hours()

        if cache_file.exists():
            age = datetime.now(UTC) - datetime.fromtimestamp(cache_file.stat().st_mtime, tz=UTC)
            if age <= timedelta(hours=ttl_hours):
                parsed = self._parse_code_list_csv(cache_file.read_bytes())
                if parsed:
                    return parsed

        response = await client.get(
            EDINET_CODELIST_CSV,
            headers={"User-Agent": "chat-orchestrator/edinet-skill"},
        )
        if response.status_code != 200:
            return None
        cache_file.write_bytes(response.content)
        return self._parse_code_list_csv(response.content)

    def _parse_code_list_csv(self, raw: bytes) -> list[dict[str, str]]:
        text = ""
        for encoding in ("utf-8-sig", "cp932", "shift_jis"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if not text:
            return []

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return []

        normalized_headers = {
            header: self._norm_text(header) for header in reader.fieldnames if header is not None
        }

        def pick_header(candidates: list[str]) -> str | None:
            for original, normalized in normalized_headers.items():
                if any(c in normalized for c in candidates):
                    return original
            return None

        edinet_h = pick_header(["edinet", "edinetコード"])
        sec_h = pick_header(["証券コード", "sec"])
        company_h = pick_header(["提出者名", "会社名", "商号", "提出者"])
        if edinet_h is None or company_h is None:
            return []

        rows: list[dict[str, str]] = []
        for row in reader:
            edinet_code = (row.get(edinet_h, "") or "").strip()
            company_name = (row.get(company_h, "") or "").strip()
            sec_code_raw = (row.get(sec_h, "") or "").strip() if sec_h else ""
            sec_code = re.sub(r"\D", "", sec_code_raw)[:4] if sec_code_raw else ""
            if not edinet_code or not company_name:
                continue
            rows.append(
                {
                    "edinet_code": edinet_code,
                    "sec_code": sec_code,
                    "company_name": company_name,
                }
            )

        return rows

    async def _find_latest_annual_filing(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        company: CompanyResolution,
        docs_by_date: dict[str, list[dict[str, Any]]],
        api_errors: list[str],
    ) -> FilingMatch | None:
        lookback_days = self._lookback_days()
        candidates: list[dict[str, Any]] = []

        for offset in range(lookback_days):
            target_date = (datetime.now(UTC) - timedelta(days=offset)).date()
            key = target_date.isoformat()
            daily_docs = docs_by_date.get(key)
            if daily_docs is None:
                response = await client.get(
                    f"{EDINET_API_BASE}/documents.json",
                    params={"date": key, "type": 2, "Subscription-Key": api_key},
                    headers={"Subscription-Key": api_key},
                )
                if response.status_code != 200:
                    api_errors.append(f"documents.json date={key} status={response.status_code}")
                    continue
                payload = response.json()
                daily_docs = payload.get("results", []) if isinstance(payload, dict) else []
                docs_by_date[key] = daily_docs

            for doc in daily_docs:
                if doc.get("docTypeCode") not in DOC_TYPE_CODES:
                    continue
                if doc.get("edinetCode") != company.edinet_code:
                    continue
                candidates.append(doc)

        if not candidates:
            return None

        candidates.sort(key=self._doc_sort_key, reverse=True)
        top = candidates[0]
        return FilingMatch(
            doc_id=str(top.get("docID", "")),
            doc_type_code=str(top.get("docTypeCode", "")),
            submit_datetime=str(top.get("submitDateTime") or top.get("submitDate") or ""),
            filer_name=str(top.get("filerName") or company.company_name or company.query),
            period_end=(top.get("periodEnd") or None),
        )

    async def _resolve_companies_without_code_index(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        context_text: str,
        docs_by_date: dict[str, list[dict[str, Any]]],
    ) -> list[CompanyResolution]:
        tokens = self._extract_company_tokens(context_text)
        if not tokens:
            return [
                CompanyResolution(
                    query="(未指定)",
                    edinet_code=None,
                    sec_code=None,
                    company_name=None,
                    reason="企業指定が検出できませんでした",
                )
            ]

        lookback_days = min(self._lookback_days(), 400)
        latest_by_edinet: dict[str, dict[str, Any]] = {}
        for offset in range(lookback_days):
            target_date = (datetime.now(UTC) - timedelta(days=offset)).date()
            key = target_date.isoformat()
            daily_docs = docs_by_date.get(key)
            if daily_docs is None:
                response = await client.get(
                    f"{EDINET_API_BASE}/documents.json",
                    params={"date": key, "type": 2, "Subscription-Key": api_key},
                    headers={"Subscription-Key": api_key},
                )
                if response.status_code != 200:
                    continue
                payload = response.json()
                daily_docs = payload.get("results", []) if isinstance(payload, dict) else []
                docs_by_date[key] = daily_docs

            for doc in daily_docs:
                if doc.get("docTypeCode") not in DOC_TYPE_CODES:
                    continue
                edinet_code = str(doc.get("edinetCode") or "")
                if not edinet_code:
                    continue
                current = latest_by_edinet.get(edinet_code)
                if current is None or self._doc_sort_key(doc) > self._doc_sort_key(current):
                    latest_by_edinet[edinet_code] = doc

        if not latest_by_edinet:
            return [
                CompanyResolution(
                    query=token,
                    edinet_code=None,
                    sec_code=None,
                    company_name=None,
                    reason="提出書類メタデータから企業を特定できませんでした",
                )
                for token in tokens
            ]

        entries: list[dict[str, str]] = []
        sec_map: dict[str, list[dict[str, str]]] = {}
        for doc in latest_by_edinet.values():
            entry = {
                "edinet_code": str(doc.get("edinetCode") or ""),
                "company_name": str(doc.get("filerName") or "").strip(),
                "sec_code": re.sub(r"\D", "", str(doc.get("secCode") or ""))[:4],
            }
            if not entry["edinet_code"] or not entry["company_name"]:
                continue
            entries.append(entry)
            if entry["sec_code"]:
                sec_map.setdefault(entry["sec_code"], []).append(entry)

        results: list[CompanyResolution] = []
        seen_edinet: set[str] = set()
        for token in tokens:
            normalized = self._norm_text(token)
            if not normalized:
                continue

            edinet_match = re.fullmatch(r"E\d{5}", normalized.upper())
            if edinet_match:
                row = next((e for e in entries if e["edinet_code"] == edinet_match.group(0)), None)
                if row:
                    if row["edinet_code"] in seen_edinet:
                        continue
                    seen_edinet.add(row["edinet_code"])
                    results.append(self._build_company_resolution(token, row, "EDINETコード一致（提出書類メタデータ）"))
                else:
                    results.append(
                        CompanyResolution(
                            query=token,
                            edinet_code=None,
                            sec_code=None,
                            company_name=None,
                            reason="EDINETコードが提出書類メタデータ範囲に見つかりません",
                        )
                    )
                continue

            sec_match = re.fullmatch(r"\d{4}", normalized)
            if sec_match:
                matches = sec_map.get(sec_match.group(0), [])
                if len(matches) == 1:
                    row = matches[0]
                    if row["edinet_code"] in seen_edinet:
                        continue
                    seen_edinet.add(row["edinet_code"])
                    results.append(self._build_company_resolution(token, row, "証券コード一致（提出書類メタデータ）"))
                    continue
                if len(matches) > 1:
                    results.append(
                        CompanyResolution(
                            query=token,
                            edinet_code=None,
                            sec_code=sec_match.group(0),
                            company_name=None,
                            reason="証券コード候補が複数あります。EDINETコード指定を推奨します",
                        )
                    )
                    continue

            name_matches = [
                e for e in entries if normalized in self._norm_text(e["company_name"])
            ]
            if len(name_matches) == 1:
                row = name_matches[0]
                if row["edinet_code"] in seen_edinet:
                    continue
                seen_edinet.add(row["edinet_code"])
                results.append(self._build_company_resolution(token, row, "社名一致（提出書類メタデータ）"))
            elif len(name_matches) > 1:
                results.append(
                    CompanyResolution(
                        query=token,
                        edinet_code=None,
                        sec_code=None,
                        company_name=None,
                        reason="社名候補が複数あります。EDINETコードか証券コードを指定してください",
                    )
                )
            else:
                results.append(
                    CompanyResolution(
                        query=token,
                        edinet_code=None,
                        sec_code=None,
                        company_name=None,
                        reason="提出書類メタデータ内で企業候補を特定できませんでした",
                    )
                )

        return results

    def _doc_sort_key(self, doc: dict[str, Any]) -> str:
        submit = str(doc.get("submitDateTime") or "")
        if submit:
            return submit
        date = str(doc.get("submitDate") or "")
        time = str(doc.get("submitTime") or "")
        return f"{date}T{time}"

    async def _prepare_xbrl_file(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        doc_id: str,
        api_errors: list[str],
    ) -> Path | None:
        cache_root = self._cache_root()
        doc_dir = cache_root / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        ttl_hours = self._cache_ttl_hours()

        cached = self._find_cached_xbrl(doc_dir=doc_dir, ttl_hours=ttl_hours)
        if cached is not None:
            return cached

        zip_path = doc_dir / f"{doc_id}.zip"
        extract_dir = doc_dir / "extracted"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        response = await client.get(
            f"{EDINET_API_BASE}/documents/{doc_id}",
            params={"type": 1, "Subscription-Key": api_key},
            headers={"Subscription-Key": api_key},
        )
        if response.status_code != 200:
            api_errors.append(f"documents/{doc_id}?type=1 status={response.status_code}")
            return None
        zip_path.write_bytes(response.content)

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile:
            return None

        for file_path in extract_dir.rglob("*.xbrl"):
            if "PublicDoc" in file_path.parts:
                return file_path
        return None

    def _find_cached_xbrl(self, *, doc_dir: Path, ttl_hours: int) -> Path | None:
        now = datetime.now(UTC)
        for file_path in doc_dir.rglob("*.xbrl"):
            if "PublicDoc" not in file_path.parts:
                continue
            age = now - datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
            if age <= timedelta(hours=ttl_hours):
                return file_path
        return None

    async def _route_sections(
        self,
        question: str,
        sections: list[SectionDefinition],
        skill_context: dict[str, Any] | None = None,
    ) -> tuple[list[SectionDefinition], dict[str, str]]:
        scored: dict[str, int] = {section.section_id: 0 for section in sections}
        normalized_q = self._norm_text(question)
        for section in sections:
            for keyword in section.keywords:
                if keyword and keyword in normalized_q:
                    scored[section.section_id] += 2
            if section.section_id.startswith("2-"):
                scored[section.section_id] += 1

        ranked_ids = sorted(scored.keys(), key=lambda sec_id: scored[sec_id], reverse=True)
        selected_ids = [sec_id for sec_id in ranked_ids if scored[sec_id] > 0][:3]
        if not selected_ids:
            selected_ids = ["2-4", "2-3", "1-3"]

        reasons = {sec_id: "規則ベース" for sec_id in selected_ids}
        selected = [section for section in sections if section.section_id in selected_ids]

        if not self._router_llm_enabled():
            return selected, reasons

        reranked = await self._rerank_sections_by_llm(
            question=question,
            sections=selected,
            skill_context=skill_context,
        )
        if not reranked:
            return selected, reasons

        by_id = {section.section_id: section for section in selected}
        final_ids = [sec_id for sec_id in reranked if sec_id in by_id][:3]
        if not final_ids:
            return selected, reasons
        reasons.update({sec_id: "LLM再ランキング" for sec_id in final_ids})
        return [by_id[sec_id] for sec_id in final_ids], reasons

    async def _rerank_sections_by_llm(
        self,
        *,
        question: str,
        sections: list[SectionDefinition],
        skill_context: dict[str, Any] | None = None,
    ) -> list[str]:
        settings = get_settings()
        provider_id = str((skill_context or {}).get("provider_id") or "openai")
        selected_model = str((skill_context or {}).get("model") or "").strip()
        model = selected_model or (settings.edinet_router_model or "gpt-4o-mini").strip() or "gpt-4o-mini"

        client_kwargs = self._build_router_client_kwargs(provider_id=provider_id, settings=settings)
        if client_kwargs is None:
            return []

        client = AsyncOpenAI(**client_kwargs)
        candidates = [{"id": sec.section_id, "title": sec.title} for sec in sections]
        prompt = (
            "あなたは有価証券報告書のセクション選択器です。"
            "質問に答えるのに必要なセクションIDを最大3件、優先順でJSON配列のみで返してください。"
            f"\n質問: {question}\n候補: {json.dumps(candidates, ensure_ascii=False)}"
        )

        try:
            response = await client.responses.create(
                model=model,
                input=prompt,
                max_output_tokens=120,
            )
        except Exception:
            return []

        output_text = getattr(response, "output_text", None) or ""
        if not output_text:
            return []
        return self._extract_section_ids_from_text(output_text=output_text)

    def _build_router_client_kwargs(self, *, provider_id: str, settings: Any) -> dict[str, str] | None:
        if provider_id == "openai":
            api_key = (settings.openai_api_key or "").strip()
            if not api_key:
                return None
            return {"api_key": api_key}

        if provider_id == "azure_openai":
            api_key = (settings.azure_openai_api_key or "").strip()
            endpoint = (settings.azure_openai_endpoint or "").strip().rstrip("/")
            if not api_key or not endpoint:
                return None
            return {"api_key": api_key, "base_url": f"{endpoint}/openai/v1/"}

        if provider_id == "deepseek":
            api_key = (settings.deepseek_api_key or "").strip()
            base_url = (settings.deepseek_base_url or "").strip()
            if not api_key:
                return None
            return {"api_key": api_key, "base_url": base_url} if base_url else {"api_key": api_key}

        return None

    def _extract_section_ids_from_text(self, *, output_text: str) -> list[str]:
        text = output_text.strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if isinstance(item, str)]
        except json.JSONDecodeError:
            pass

        match = re.search(r"\[[^\]]*\]", text, flags=re.DOTALL)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return [str(item) for item in parsed if isinstance(item, str)]
        except json.JSONDecodeError:
            return []
        return []

    def _extract_company_tokens(self, text: str) -> list[str]:
        tokens: set[str] = set()
        for match in re.findall(r"E\d{5}", text, flags=re.IGNORECASE):
            tokens.add(match.upper())
        for match in re.findall(r"証券コード\s*[:：]?\s*(\d{4})", text):
            tokens.add(match)
        for match in re.findall(r"\b\d{4}\b", text):
            tokens.add(match)

        split_parts = re.split(r"[、,\n]|と|および|及び|ならびに", text)
        for part in split_parts:
            cleaned = self._clean_company_token(self._trim_non_company_suffix(part))
            if cleaned:
                tokens.add(cleaned)

        company_like = re.findall(
            r"([一-龥ぁ-んァ-ヶA-Za-z0-9・ー＆&\-]+?(?:株式会社|ホールディングス|グループ|HD|自動車))",
            text,
        )
        for name in company_like:
            cleaned = self._clean_company_token(name)
            if cleaned:
                tokens.add(cleaned)

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
        filtered = [tok for tok in tokens if self._norm_text(tok) not in stopwords]
        return sorted(filtered, key=len)

    def _extract_explicit_edinet_codes(self, text: str) -> list[str]:
        codes: list[str] = []
        bracket_segments = re.findall(r"\[([^\]]+)\]", text)
        for segment in bracket_segments:
            for match in re.findall(r"E\d{5}", segment, flags=re.IGNORECASE):
                code = match.upper()
                if code not in codes:
                    codes.append(code)
        if codes:
            return codes
        for match in re.findall(r"\bE\d{5}\b", text, flags=re.IGNORECASE):
            code = match.upper()
            if code not in codes:
                codes.append(code)
        return codes

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
        if not cleaned:
            return None
        if len(cleaned) <= 1:
            return None
        if len(cleaned) > 80:
            return None
        return cleaned

    def _build_sections(self) -> list[SectionDefinition]:
        defs = [
            ("1-1", "主要な経営指標等の推移", ["BusinessResultsOfGroupTextBlock"], ["経営指標", "kpi", "推移"]),
            ("1-2", "沿革", ["CompanyHistoryTextBlock"], ["沿革", "歴史", "創業"]),
            ("1-3", "事業の内容", ["DescriptionOfBusinessTextBlock"], ["事業", "ビジネスモデル", "セグメント"]),
            ("1-4", "関係会社の状況", ["OverviewOfAffiliatedEntitiesTextBlock"], ["関係会社", "子会社", "関連会社"]),
            ("1-5", "従業員の状況", ["InformationAboutEmployeesTextBlock"], ["従業員", "社員", "人員"]),
            (
                "2-1",
                "経営方針、経営環境及び対処すべき課題等",
                [
                    "BusinessPolicyBusinessEnvironmentIssuesToAddressEtcTextBlock",
                    "OverviewOfBusinessResultsTextBlock",
                ],
                ["経営方針", "経営環境", "課題", "対処"],
            ),
            (
                "2-2",
                "サステナビリティに関する考え方及び取組",
                ["DisclosureOfSustainabilityRelatedFinancialInformationTextBlock"],
                ["サステナビリティ", "esg", "気候", "脱炭素", "人的資本"],
            ),
            (
                "2-3",
                "事業等のリスク",
                [
                    "BusinessRisksTextBlock",
                    "MaterialMattersRelatingToGoingConcernEtcBusinessRisksTextBlock",
                ],
                ["リスク", "不確実性", "懸念", "継続企業"],
            ),
            (
                "2-4",
                "経営者による財政状態、経営成績及びキャッシュ・フローの状況の分析",
                ["ManagementAnalysisOfFinancialPositionOperatingResultsAndCashFlowsTextBlock"],
                ["財政状態", "経営成績", "キャッシュフロー", "md&a", "分析"],
            ),
            ("2-5", "重要な契約等", [], ["契約", "提携", "ライセンス"]),
            ("2-6", "研究開発活動", [], ["研究開発", "r&d"]),
            ("3-1", "設備投資等の概要", [], ["設備投資", "capex"]),
            ("3-2", "主要な設備の状況", [], ["設備", "工場", "拠点"]),
            ("3-3", "設備の新設、除却等の計画", [], ["新設", "除却", "設備計画"]),
            ("4-1-1", "株式の総数等", [], ["株式数", "発行済株式", "株数"]),
            ("4-1-5", "所有者別状況", [], ["所有者別", "株主構成"]),
            ("4-1-6", "大株主の状況", [], ["大株主", "主要株主"]),
            ("4-3", "配当政策", [], ["配当", "配当政策", "配当性向"]),
            ("4-4-1", "コーポレート・ガバナンスの概要", [], ["コーポレートガバナンス", "ガバナンス"]),
            ("4-4-2", "役員の状況", [], ["役員", "取締役", "監査役"]),
            ("4-4-3", "監査の状況", [], ["監査", "内部監査", "会計監査"]),
            ("4-4-4", "役員の報酬等", [], ["報酬", "役員報酬"]),
            ("5-1-1", "連結財務諸表", [], ["連結財務諸表", "連結"]),
            ("5-1-2", "その他（連結）", [], ["連結注記", "連結その他"]),
            ("5-2-1", "財務諸表（単体）", [], ["財務諸表", "単体", "貸借対照表", "損益計算書"]),
            ("5-2-2", "主な資産及び負債の内容", [], ["資産", "負債"]),
            ("5-2-3", "その他（単体）", [], ["単体その他"]),
            ("6", "提出会社の株式事務の概要", [], ["株式事務"]),
            ("7-1", "提出会社の親会社等の情報", [], ["親会社"]),
            ("7-2", "その他の参考情報", [], ["参考情報"]),
            ("8", "提出会社の保証会社等の情報", [], ["保証会社"]),
        ]
        return [
            SectionDefinition(
                section_id=section_id,
                title=title,
                tag_candidates=tags,
                keywords=keywords,
            )
            for section_id, title, tags, keywords in defs
        ]

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
            value = DEFAULT_LOOKBACK_DAYS
        return max(7, min(730, value))

    def _router_llm_enabled(self) -> bool:
        return bool(get_settings().edinet_router_enable_llm)

    def _clip_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...（省略）"

    def _indent(self, text: str, prefix: str) -> str:
        return "\n".join(f"{prefix}{line}" for line in text.splitlines())

    def _norm_text(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text).lower().strip()
        normalized = normalized.replace("株式会社", "")
        normalized = normalized.replace("(株)", "")
        normalized = normalized.replace(" ", "")
        normalized = normalized.replace("　", "")
        return normalized


def build_skill() -> Skill:
    return EdinetReportQASkill()
