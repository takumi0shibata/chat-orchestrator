import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Awaitable


@dataclass
class CompanyCandidate:
    edinet_code: str
    company_name: str
    sec_code: str | None
    source: str


@dataclass
class CompanyResolution:
    query: str
    edinet_code: str | None
    sec_code: str | None
    company_name: str | None
    reason: str
    candidates: list[CompanyCandidate] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.edinet_code)


Disambiguator = Callable[[str, str, list[CompanyCandidate]], Awaitable[str | None]]


class CompanyResolver:
    def __init__(self, csv_raw: bytes):
        self._index = self._parse_code_list_csv(csv_raw)
        self._by_edinet = {row["edinet_code"]: row for row in self._index}
        self._by_sec: dict[str, list[dict[str, str]]] = {}
        self._by_name_norm: dict[str, list[dict[str, str]]] = {}
        for row in self._index:
            if row["sec_code"]:
                self._by_sec.setdefault(row["sec_code"], []).append(row)
            name_norm = _norm_text(row["company_name"])
            if name_norm:
                self._by_name_norm.setdefault(name_norm, []).append(row)

    @classmethod
    def from_csv_path(cls, path: str) -> "CompanyResolver":
        return cls(csv_raw=open(path, "rb").read())

    async def resolve_many(
        self,
        *,
        company_queries: list[str],
        question: str,
        fallback_entries: list[dict[str, str]],
        disambiguator: Disambiguator | None,
    ) -> list[CompanyResolution]:
        seen: set[str] = set()
        results: list[CompanyResolution] = []

        for query in self._dedupe_preserve_order(company_queries):
            candidates = self._find_candidates(query)
            if not candidates:
                candidates = self._find_candidates_in_fallback(query, fallback_entries)

            if len(candidates) == 1:
                picked = candidates[0]
                if picked.edinet_code in seen:
                    continue
                seen.add(picked.edinet_code)
                results.append(
                    CompanyResolution(
                        query=query,
                        edinet_code=picked.edinet_code,
                        sec_code=picked.sec_code,
                        company_name=picked.company_name,
                        reason=f"{picked.source}一致",
                    )
                )
                continue

            if len(candidates) > 1 and disambiguator is not None:
                picked_code = await disambiguator(question, query, candidates)
                picked = next((cand for cand in candidates if cand.edinet_code == picked_code), None)
                if picked is not None and picked.edinet_code not in seen:
                    seen.add(picked.edinet_code)
                    results.append(
                        CompanyResolution(
                            query=query,
                            edinet_code=picked.edinet_code,
                            sec_code=picked.sec_code,
                            company_name=picked.company_name,
                            reason=f"LLM候補選択({picked.source})",
                        )
                    )
                    continue

            if len(candidates) > 1:
                results.append(
                    CompanyResolution(
                        query=query,
                        edinet_code=None,
                        sec_code=None,
                        company_name=None,
                        reason="候補が複数あります",
                        candidates=candidates[:5],
                    )
                )
            else:
                results.append(
                    CompanyResolution(
                        query=query,
                        edinet_code=None,
                        sec_code=None,
                        company_name=None,
                        reason="企業候補を特定できませんでした",
                    )
                )
        return results

    def _find_candidates(self, query: str) -> list[CompanyCandidate]:
        token = query.strip()
        if not token:
            return []
        normalized = _norm_text(token)

        edinet_match = re.fullmatch(r"E\d{5}", normalized.upper())
        if edinet_match:
            edinet = edinet_match.group(0)
            row = self._by_edinet.get(edinet)
            if row:
                return [self._to_candidate(row, "CSV")]
            return [CompanyCandidate(edinet_code=edinet, company_name=edinet, sec_code=None, source="コード指定")]

        sec_match = re.fullmatch(r"\d{4}", normalized)
        if sec_match:
            rows = self._by_sec.get(sec_match.group(0), [])
            return [self._to_candidate(row, "CSV") for row in rows]

        exact = self._by_name_norm.get(normalized, [])
        if exact:
            return [self._to_candidate(row, "CSV") for row in exact]

        contains = [
            self._to_candidate(row, "CSV")
            for row in self._index
            if normalized and normalized in _norm_text(row["company_name"])
        ]
        return contains[:8]

    def _find_candidates_in_fallback(
        self,
        query: str,
        fallback_entries: list[dict[str, str]],
    ) -> list[CompanyCandidate]:
        normalized = _norm_text(query)
        if not normalized:
            return []

        exact: list[CompanyCandidate] = []
        partial: list[CompanyCandidate] = []

        for row in fallback_entries:
            name = str(row.get("company_name") or "").strip()
            edinet = str(row.get("edinet_code") or "").strip()
            if not name or not edinet:
                continue
            sec_code = str(row.get("sec_code") or "").strip() or None
            row_name_norm = _norm_text(name)
            candidate = CompanyCandidate(
                edinet_code=edinet,
                company_name=name,
                sec_code=sec_code,
                source="APIメタデータ",
            )
            if row_name_norm == normalized:
                exact.append(candidate)
            elif normalized in row_name_norm:
                partial.append(candidate)

        merged = exact if exact else partial
        by_code: dict[str, CompanyCandidate] = {}
        for item in merged:
            by_code[item.edinet_code] = item
        return list(by_code.values())[:8]

    def _to_candidate(self, row: dict[str, str], source: str) -> CompanyCandidate:
        return CompanyCandidate(
            edinet_code=row["edinet_code"],
            company_name=row["company_name"],
            sec_code=row.get("sec_code") or None,
            source=source,
        )

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
            header: _norm_text(header) for header in reader.fieldnames if header is not None
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

    def _dedupe_preserve_order(self, items: list[str]) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for item in items:
            key = _norm_text(item)
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output


def _norm_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower().strip()
    normalized = normalized.replace("株式会社", "")
    normalized = normalized.replace("(株)", "")
    normalized = normalized.replace(" ", "")
    normalized = normalized.replace("　", "")
    return normalized
