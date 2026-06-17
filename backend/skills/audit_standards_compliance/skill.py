from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from app.skills_runtime.base import (
    Skill,
    SkillCategory,
    SkillExecutionResult,
    SkillMetadata,
    context_only_result,
    get_skill_progress,
)


_SKILL_DIR = Path(__file__).resolve().parent
_DOCS_DIR = _SKILL_DIR / "docs"
_MANIFEST_PATH = _DOCS_DIR / "manifest.json"

_TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,}")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

_PHRASE_EXPANSIONS: dict[str, list[str]] = {
    "監査証拠": ["十分かつ適切", "アサーション", "証拠", "audit evidence"],
    "独立性": ["倫理", "阻害要因", "セーフガード", "independence"],
    "倫理": ["独立性", "阻害要因", "セーフガード", "ethics"],
    "ifrs": ["financial reporting framework", "IFRS"],
    "日本基準": ["JGAAP", "企業会計基準", "会計基準"],
    "品質管理": ["quality management", "審査", "業務品質"],
    "継続企業": ["going concern", "不確実性"],
    "後発事象": ["subsequent events"],
    "重要性": ["materiality", "虚偽表示"],
}


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    title: str
    issuer: str
    jurisdiction: str
    standard_family: str
    effective_date: str
    version: str
    source_url: str
    file_path: Path
    is_authoritative: bool
    license_note: str


@dataclass(frozen=True)
class DocumentChunk:
    document: SourceDocument
    chunk_id: str
    heading_path: tuple[str, ...]
    text: str

    @property
    def section_label(self) -> str:
        if not self.heading_path:
            return "-"
        return " > ".join(self.heading_path[-3:])


@dataclass(frozen=True)
class SearchHit:
    chunk: DocumentChunk
    score: float
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class SearchPlan:
    query: str
    jurisdictions: tuple[str, ...]
    standard_families: tuple[str, ...]
    terms: tuple[str, ...]
    max_sources: int


class AuditStandardsComplianceSkill(Skill):
    metadata = SkillMetadata(
        id="audit_standards_compliance",
        name="Audit Standards Compliance",
        description=(
            "監査基準、会計基準、IFRS、日本基準、JICPA倫理規則、品質管理基準などの"
            "ローカル基準文書を検索し、根拠付き回答のための補助コンテキストを生成します。"
        ),
        primary_category=SkillCategory(id="audit", label="Audit"),
        tags=["audit", "standards", "compliance"],
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> SkillExecutionResult:
        del history
        progress = get_skill_progress(skill_context)
        await progress.update(stage="plan_search", label="基準文書の検索方針を組み立てています")

        params = dict((skill_context or {}).get("ability_params") or {})
        plan = self._build_search_plan(user_text=user_text, params=params)

        await progress.update(stage="load_corpus", label="ローカル基準コーパスを読み込んでいます")
        documents, corpus_warnings = self._load_documents()
        if not documents:
            return context_only_result(self._missing_corpus_context(plan=plan, warnings=corpus_warnings))

        await progress.update(stage="search_sources", label="関連する基準候補を検索しています")
        chunks = [chunk for document in documents for chunk in self._chunk_document(document)]
        hits = self._search(chunks=chunks, plan=plan)

        return context_only_result(
            self._build_context(
                plan=plan,
                documents=documents,
                hits=hits,
                warnings=corpus_warnings,
            )
        )

    def _build_search_plan(self, *, user_text: str, params: dict[str, Any]) -> SearchPlan:
        query = str(params.get("query") or params.get("task") or user_text or "").strip()
        jurisdictions = self._as_str_tuple(params.get("jurisdictions")) or self._infer_jurisdictions(query)
        standard_families = self._as_str_tuple(params.get("standard_families")) or self._infer_standard_families(query)
        max_sources = self._bounded_int(params.get("max_sources"), default=6, minimum=1, maximum=12)
        terms = self._expand_terms(query)
        return SearchPlan(
            query=query,
            jurisdictions=jurisdictions,
            standard_families=standard_families,
            terms=terms,
            max_sources=max_sources,
        )

    def _load_documents(self) -> tuple[list[SourceDocument], list[str]]:
        warnings: list[str] = []
        if not _MANIFEST_PATH.is_file():
            return [], [f"manifest が見つかりません: `{_MANIFEST_PATH}`"]

        raw = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        documents_raw = raw.get("documents", []) if isinstance(raw, dict) else []
        documents: list[SourceDocument] = []
        for item in documents_raw:
            if not isinstance(item, dict):
                continue
            relative_path = str(item.get("file_path") or "").strip()
            file_path = (_DOCS_DIR / relative_path).resolve()
            if not file_path.is_file():
                warnings.append(f"文書ファイルが見つかりません: `{relative_path}`")
                continue
            documents.append(
                SourceDocument(
                    document_id=str(item.get("document_id") or file_path.stem),
                    title=str(item.get("title") or file_path.stem),
                    issuer=str(item.get("issuer") or ""),
                    jurisdiction=str(item.get("jurisdiction") or ""),
                    standard_family=str(item.get("standard_family") or ""),
                    effective_date=str(item.get("effective_date") or ""),
                    version=str(item.get("version") or ""),
                    source_url=str(item.get("source_url") or ""),
                    file_path=file_path,
                    is_authoritative=bool(item.get("is_authoritative")),
                    license_note=str(item.get("license_note") or ""),
                )
            )
        return documents, warnings

    def _chunk_document(self, document: SourceDocument) -> list[DocumentChunk]:
        text = document.file_path.read_text(encoding="utf-8")
        heading_stack: list[str] = []
        chunks: list[DocumentChunk] = []
        buffer: list[str] = []
        chunk_index = 1

        def flush() -> None:
            nonlocal chunk_index
            body = "\n".join(line for line in buffer if line.strip()).strip()
            buffer.clear()
            if not body:
                return
            for part in self._split_long_text(body):
                chunks.append(
                    DocumentChunk(
                        document=document,
                        chunk_id=f"{document.document_id}:{chunk_index}",
                        heading_path=tuple(heading_stack),
                        text=part,
                    )
                )
                chunk_index += 1

        for raw_line in text.splitlines():
            heading_match = _HEADING_RE.match(raw_line)
            if heading_match:
                flush()
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(title)
                continue
            if raw_line.strip():
                buffer.append(raw_line.strip())
            else:
                flush()
        flush()
        return chunks

    def _search(self, *, chunks: list[DocumentChunk], plan: SearchPlan) -> list[SearchHit]:
        hits: list[SearchHit] = []
        query_tokens = set(self._ascii_tokens(plan.query))
        for chunk in chunks:
            metadata_score = self._metadata_score(chunk.document, plan)
            if metadata_score < 0:
                continue

            haystack = self._normalize(
                " ".join(
                    [
                        chunk.document.title,
                        chunk.document.issuer,
                        chunk.document.jurisdiction,
                        chunk.document.standard_family,
                        chunk.section_label,
                        chunk.text,
                    ]
                )
            )
            matched_terms: list[str] = []
            score = metadata_score
            for term in plan.terms:
                normalized_term = self._normalize(term)
                if normalized_term and normalized_term in haystack:
                    matched_terms.append(term)
                    score += 4.0 + min(haystack.count(normalized_term), 3)

            chunk_tokens = set(self._ascii_tokens(haystack))
            score += len(query_tokens & chunk_tokens) * 1.5
            if chunk.document.is_authoritative:
                score += 1.0
            if matched_terms or score >= 3.0:
                hits.append(SearchHit(chunk=chunk, score=score, matched_terms=tuple(dict.fromkeys(matched_terms))))

        hits.sort(key=lambda item: item.score, reverse=True)
        deduped: list[SearchHit] = []
        seen: set[tuple[str, str]] = set()
        for hit in hits:
            key = (hit.chunk.document.document_id, hit.chunk.section_label)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(hit)
            if len(deduped) >= plan.max_sources:
                break
        return deduped

    def _metadata_score(self, document: SourceDocument, plan: SearchPlan) -> float:
        score = 0.0
        if plan.jurisdictions:
            if document.jurisdiction.lower() in {item.lower() for item in plan.jurisdictions}:
                score += 2.0
            else:
                score -= 1.0
        if plan.standard_families:
            if document.standard_family.lower() in {item.lower() for item in plan.standard_families}:
                score += 2.0
            else:
                score -= 1.0
        return score

    def _build_context(
        self,
        *,
        plan: SearchPlan,
        documents: list[SourceDocument],
        hits: list[SearchHit],
        warnings: list[str],
    ) -> str:
        authoritative_count = sum(1 for item in documents if item.is_authoritative)
        lines = [
            "監査基準準拠モード: ローカル根拠検索コンテキスト",
            "",
            "## 回答時の制約",
            "- 下記の採用候補を根拠として使い、根拠文書名・見出し・項番号相当を明示してください。",
            "- 検索結果にない事項は断定せず、「追加確認が必要」と明示してください。",
            "- 基準本文、社内メモ、推論を区別してください。",
            "- 監査意見、法的結論、独立性の最終判断として断定しないでください。",
            "",
            "## 質問解釈",
            f"- 検索クエリ: {plan.query or '(空)'}",
            f"- 推定 jurisdiction: {', '.join(plan.jurisdictions) if plan.jurisdictions else '未指定'}",
            f"- 推定 document family: {', '.join(plan.standard_families) if plan.standard_families else '未指定'}",
            f"- 展開語: {', '.join(plan.terms[:16]) if plan.terms else 'なし'}",
            "",
            "## コーパス状態",
            f"- 登録文書数: {len(documents)}",
            f"- authoritative 文書数: {authoritative_count}",
        ]
        if authoritative_count == 0:
            lines.append("- 注意: 公式基準本文はまだ登録されていません。現在の候補は非公式サンプルまたは社内文書です。")
        for warning in warnings:
            lines.append(f"- 警告: {warning}")

        lines.extend(["", "## 採用候補"])
        if not hits:
            lines.extend(
                [
                    "- 関連候補が見つかりませんでした。",
                    "- `backend/skills/audit_standards_compliance/docs/sources/` に対象文書を追加し、`docs/manifest.json` に登録してください。",
                ]
            )
            return "\n".join(lines)

        for index, hit in enumerate(hits, start=1):
            doc = hit.chunk.document
            authority = "official/authoritative" if doc.is_authoritative else "non-authoritative"
            lines.extend(
                [
                    f"### Source {index}: {doc.title}",
                    f"- document_id: {doc.document_id}",
                    f"- issuer: {doc.issuer or '-'}",
                    f"- jurisdiction: {doc.jurisdiction or '-'}",
                    f"- family: {doc.standard_family or '-'}",
                    f"- section: {hit.chunk.section_label}",
                    f"- effective_date: {doc.effective_date or '-'}",
                    f"- version: {doc.version or '-'}",
                    f"- authority: {authority}",
                    f"- source_url: {doc.source_url or '-'}",
                    f"- matched_terms: {', '.join(hit.matched_terms) if hit.matched_terms else '-'}",
                    f"- score: {hit.score:.2f}",
                    "- excerpt:",
                    self._quote_excerpt(hit.chunk.text),
                    "",
                ]
            )
        return "\n".join(lines).strip()

    def _missing_corpus_context(self, *, plan: SearchPlan, warnings: list[str]) -> str:
        lines = [
            "監査基準準拠モード: ローカル根拠検索コンテキスト",
            "",
            "## コーパス未設定",
            f"- 検索クエリ: {plan.query or '(空)'}",
            "- 基準文書が読み込めませんでした。",
        ]
        for warning in warnings:
            lines.append(f"- 警告: {warning}")
        lines.append("- `docs/sources/` に文書を配置し、`docs/manifest.json` に登録してください。")
        return "\n".join(lines)

    def _infer_jurisdictions(self, query: str) -> tuple[str, ...]:
        lowered = query.lower()
        values: list[str] = []
        if any(term in query for term in ["日本", "JICPA", "監査法人", "日本基準"]) or "jgaap" in lowered:
            values.append("JP")
        if "ifrs" in lowered or "国際財務報告基準" in query:
            values.append("IFRS")
        return tuple(dict.fromkeys(values))

    def _infer_standard_families(self, query: str) -> tuple[str, ...]:
        lowered = query.lower()
        values: list[str] = []
        if any(term in query for term in ["倫理", "独立性", "阻害要因", "セーフガード"]):
            values.append("ethics")
        if any(term in query for term in ["監査", "監査証拠", "重要性", "後発事象", "継続企業"]):
            values.append("auditing")
        if "ifrs" in lowered or "国際財務報告基準" in query:
            values.append("ifrs")
        if any(term in query for term in ["日本基準", "企業会計基準", "会計処理"]):
            values.append("jgaap")
        if "品質管理" in query or "quality management" in lowered:
            values.append("quality_management")
        return tuple(dict.fromkeys(values))

    def _expand_terms(self, query: str) -> tuple[str, ...]:
        terms: list[str] = []
        for token in self._ascii_tokens(query):
            terms.append(token)
        for phrase, expansions in _PHRASE_EXPANSIONS.items():
            if phrase.lower() in query.lower():
                terms.append(phrase)
                terms.extend(expansions)
        for part in re.split(r"[\s、。,.・/／（）()「」『』:：\n]+", query):
            part = part.strip()
            if 2 <= len(part) <= 24:
                terms.append(part)
        return tuple(dict.fromkeys(terms))

    def _split_long_text(self, text: str, limit: int = 900) -> list[str]:
        if len(text) <= limit:
            return [text]
        parts: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= limit:
                parts.append(remaining.strip())
                break
            split_at = max(remaining.rfind("。", 0, limit), remaining.rfind("\n", 0, limit))
            if split_at < limit // 2:
                split_at = limit
            parts.append(remaining[: split_at + 1].strip())
            remaining = remaining[split_at + 1 :].strip()
        return [part for part in parts if part]

    def _quote_excerpt(self, text: str, limit: int = 700) -> str:
        excerpt = re.sub(r"\s+", " ", text).strip()
        if len(excerpt) > limit:
            excerpt = excerpt[: limit - 1].rstrip() + "…"
        return f"> {excerpt}"

    def _normalize(self, text: str) -> str:
        return text.lower().replace("　", " ")

    def _ascii_tokens(self, text: str) -> list[str]:
        return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]

    def _as_str_tuple(self, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list):
            values = [str(item) for item in value]
        else:
            return ()
        return tuple(dict.fromkeys(item.strip() for item in values if item.strip()))

    def _bounded_int(self, value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return min(max(parsed, minimum), maximum)


def build_skill() -> Skill:
    return AuditStandardsComplianceSkill()
