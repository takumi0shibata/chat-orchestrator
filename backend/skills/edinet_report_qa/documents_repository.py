import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
DOC_TYPE_CODES = {"120", "130"}


@dataclass
class FilingMatch:
    doc_id: str
    doc_type_code: str
    submit_datetime: str
    filer_name: str
    period_end: str | None


class DocumentsRepository:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        cache_root: Path,
        ttl_hours: int,
        force_refresh: bool = False,
    ):
        self.client = client
        self.api_key = api_key
        self.cache_root = cache_root
        self.ttl_hours = max(1, ttl_hours)
        self.force_refresh = force_refresh
        self._docs_cache: dict[str, list[dict[str, Any]]] = {}
        self._documents_cache_dir = self.cache_root / "documents"
        self._documents_cache_dir.mkdir(parents=True, exist_ok=True)

    async def get_documents_for_date(self, target_date: date, api_errors: list[str]) -> list[dict[str, Any]]:
        date_key = target_date.isoformat()
        if date_key in self._docs_cache:
            return self._docs_cache[date_key]

        meta_path = self._documents_cache_dir / f"meta_{date_key}.json"
        docs_path = self._documents_cache_dir / f"docs_{date_key}.json"
        cached_meta = None if self.force_refresh else self._read_json_file(meta_path)
        cached_docs = [] if self.force_refresh else self._read_docs_payload(docs_path)

        remote_meta = await self._fetch_documents_payload(target_date=target_date, fetch_type=1, api_errors=api_errors)
        if remote_meta is not None:
            self._write_json_file(meta_path, remote_meta)
            if cached_docs and self._same_metadata(remote_meta, cached_meta):
                self._docs_cache[date_key] = cached_docs
                return cached_docs

            remote_docs = await self._fetch_documents_payload(target_date=target_date, fetch_type=2, api_errors=api_errors)
            if remote_docs is not None:
                self._write_json_file(docs_path, remote_docs)
                docs = self._extract_docs(remote_docs)
                self._docs_cache[date_key] = docs
                return docs

        if cached_docs and self._is_cache_fresh(docs_path):
            self._docs_cache[date_key] = cached_docs
            return cached_docs

        self._docs_cache[date_key] = []
        return []

    async def find_latest_annual_filing(
        self,
        *,
        edinet_code: str,
        company_name: str,
        lookback_days: int,
        fiscal_year: int | None,
        period_end_year: int | None = None,
        period_end_month: int | None = None,
        api_errors: list[str],
    ) -> FilingMatch | None:
        candidates: list[dict[str, Any]] = []
        max_days = max(7, min(3650, lookback_days))
        for offset in range(max_days):
            target_date = (datetime.now(UTC) - timedelta(days=offset)).date()
            docs = await self.get_documents_for_date(target_date, api_errors)
            for doc in docs:
                if str(doc.get("docTypeCode") or "") not in DOC_TYPE_CODES:
                    continue
                if str(doc.get("edinetCode") or "") != edinet_code:
                    continue
                period_end = str(doc.get("periodEnd") or "")
                if period_end_year is not None and period_end_month is not None:
                    if not self._matches_period_end(period_end, period_end_year, period_end_month):
                        continue
                if fiscal_year is not None and not self._matches_fiscal_year(period_end, fiscal_year):
                    continue
                candidates.append(doc)

        if not candidates:
            return None

        candidates.sort(key=self._doc_sort_key, reverse=True)
        top = candidates[0]
        return FilingMatch(
            doc_id=str(top.get("docID") or ""),
            doc_type_code=str(top.get("docTypeCode") or ""),
            submit_datetime=str(top.get("submitDateTime") or top.get("submitDate") or ""),
            filer_name=str(top.get("filerName") or company_name),
            period_end=str(top.get("periodEnd") or "") or None,
        )

    async def collect_recent_company_entries(self, *, lookback_days: int, api_errors: list[str]) -> list[dict[str, str]]:
        entries: dict[str, dict[str, str]] = {}
        max_days = min(max(30, lookback_days), 400)
        for offset in range(max_days):
            target_date = (datetime.now(UTC) - timedelta(days=offset)).date()
            docs = await self.get_documents_for_date(target_date, api_errors)
            for doc in docs:
                if str(doc.get("docTypeCode") or "") not in DOC_TYPE_CODES:
                    continue
                edinet_code = str(doc.get("edinetCode") or "").strip()
                company_name = str(doc.get("filerName") or "").strip()
                if not edinet_code or not company_name:
                    continue
                existing = entries.get(edinet_code)
                if existing and existing["submit_datetime"] >= self._doc_sort_key(doc):
                    continue
                entries[edinet_code] = {
                    "edinet_code": edinet_code,
                    "sec_code": re.sub(r"\D", "", str(doc.get("secCode") or ""))[:4],
                    "company_name": company_name,
                    "submit_datetime": self._doc_sort_key(doc),
                }
        return list(entries.values())

    async def download_xbrl(self, *, doc_id: str, api_errors: list[str]) -> Path | None:
        doc_dir = self.cache_root / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)

        if not self.force_refresh:
            cached = self._find_cached_xbrl(doc_dir)
            if cached is not None:
                return cached

        zip_path = doc_dir / f"{doc_id}.zip"
        extract_dir = doc_dir / "extracted"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        response = await self.client.get(
            f"{EDINET_API_BASE}/documents/{doc_id}",
            params={"type": 1, "Subscription-Key": self.api_key},
            headers={"Subscription-Key": self.api_key},
        )
        if response.status_code != 200:
            api_errors.append(f"documents/{doc_id}?type=1 status={response.status_code}")
            return None

        zip_path.write_bytes(response.content)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile:
            api_errors.append(f"documents/{doc_id}?type=1 invalid_zip")
            return None

        for file_path in extract_dir.rglob("*.xbrl"):
            if "PublicDoc" in file_path.parts:
                return file_path
        api_errors.append(f"documents/{doc_id}?type=1 no_xbrl")
        return None

    def _find_cached_xbrl(self, doc_dir: Path) -> Path | None:
        now = datetime.now(UTC)
        for file_path in doc_dir.rglob("*.xbrl"):
            if "PublicDoc" not in file_path.parts:
                continue
            age = now - datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
            if age <= timedelta(hours=self.ttl_hours):
                return file_path
        return None

    async def _fetch_documents_payload(
        self,
        *,
        target_date: date,
        fetch_type: int,
        api_errors: list[str],
    ) -> dict[str, Any] | None:
        response = await self.client.get(
            f"{EDINET_API_BASE}/documents.json",
            params={
                "date": target_date.isoformat(),
                "type": fetch_type,
                "Subscription-Key": self.api_key,
            },
            headers={"Subscription-Key": self.api_key},
        )
        if response.status_code != 200:
            api_errors.append(
                f"documents.json date={target_date.isoformat()} type={fetch_type} status={response.status_code}"
            )
            return None
        try:
            payload = response.json()
        except Exception:
            api_errors.append(f"documents.json date={target_date.isoformat()} type={fetch_type} invalid_json")
            return None
        if not isinstance(payload, dict):
            api_errors.append(f"documents.json date={target_date.isoformat()} type={fetch_type} unexpected_payload")
            return None
        return payload

    def _read_json_file(self, path: Path) -> dict[str, Any] | None:
        if not path.exists() or not self._is_cache_fresh(path):
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _read_docs_payload(self, path: Path) -> list[dict[str, Any]]:
        payload = self._read_json_file(path)
        if payload is None:
            return []
        return self._extract_docs(payload)

    def _extract_docs(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = payload.get("results")
        return rows if isinstance(rows, list) else []

    def _write_json_file(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            return

    def _same_metadata(self, current: dict[str, Any], cached: dict[str, Any] | None) -> bool:
        if cached is None:
            return False
        return self._metadata_fingerprint(current) == self._metadata_fingerprint(cached)

    def _metadata_fingerprint(self, payload: dict[str, Any]) -> tuple[Any, Any, Any]:
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        resultset = payload.get("resultset") if isinstance(payload.get("resultset"), dict) else {}
        count = resultset.get("count")
        process = metadata.get("processDateTime") or metadata.get("timeStamp") or metadata.get("resultset")
        status = metadata.get("status") or metadata.get("message")
        return (count, process, status)

    def _is_cache_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        age = datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return age <= timedelta(hours=self.ttl_hours)

    def _doc_sort_key(self, doc: dict[str, Any]) -> str:
        submit = str(doc.get("submitDateTime") or "")
        if submit:
            return submit
        date_value = str(doc.get("submitDate") or "")
        time_value = str(doc.get("submitTime") or "")
        return f"{date_value}T{time_value}"

    def _matches_fiscal_year(self, period_end: str, fiscal_year: int) -> bool:
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", period_end or "")
        if not match:
            return False
        year = int(match.group(1))
        month = int(match.group(2))
        # 3月決算などで「2024年度」が2025-03-31になるケースを許容。
        guessed_fy = year - 1 if month <= 6 else year
        return fiscal_year in {year, guessed_fy}

    def _matches_period_end(self, period_end: str, year: int, month: int) -> bool:
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", period_end or "")
        if not match:
            return False
        return int(match.group(1)) == year and int(match.group(2)) == month
