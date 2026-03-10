from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.model_catalog import get_model_capability
from app.skills_runtime.base import (
    CardItem,
    CardLine,
    CardListBlock,
    CardSection,
    GeneratedFileArtifact,
    LinkItem,
    MarkdownBlock,
    MetadataItem,
    Skill,
    SkillCategory,
    SkillExecutionOptions,
    SkillExecutionResult,
    SkillMetadata,
    get_skill_progress,
)

_SKILL_DIR = Path(__file__).resolve().parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

from docx_comments import AppliedComment, DocxCommentGenerator, SkippedComment  # noqa: E402
from llm_client import extract_json_array, extract_json_object, run_json_prompt  # noqa: E402

DEFAULT_REVIEW_BRIEF = "明確性・簡潔性・論理の流れ・表現の自然さ"
MAX_REVIEW_SOURCE_CHARS = 12000
MAX_CANDIDATES = 10
PLAN_MAX_OUTPUT_TOKENS = 10000
FINAL_MAX_OUTPUT_TOKENS = 10000
DIRECT_MAX_OUTPUT_TOKENS = 10000
INCIDENTAL_FILENAME_RE = re.compile(r"^\s*[^/\\\n]+\.(docx|doc|pdf|txt|md)\s*$", re.IGNORECASE)

PLAN_SCHEMA = {
    "name": "docx_review_observations",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "observations": {
                "type": "array",
                "maxItems": MAX_CANDIDATES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "quote": {"type": "string"},
                        "issue": {"type": "string"},
                        "revision_goal": {"type": "string"},
                        "category": {"type": "string"},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["quote", "issue", "revision_goal", "category", "priority"],
                },
            }
        },
        "required": ["observations"],
    },
}

FINAL_SCHEMA = {
    "name": "docx_review_comments",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "comments": {
                "type": "array",
                "maxItems": MAX_CANDIDATES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "quote": {"type": "string"},
                        "comment": {"type": "string"},
                        "category": {"type": "string"},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["quote", "comment", "category", "priority"],
                },
            }
        },
        "required": ["comments"],
    },
}


class DocxAutoCommenterSkill(Skill):
    metadata = SkillMetadata(
        id="docx_auto_commenter",
        name="DOCX Auto Commenter",
        description="添付したDOCXをLLMで全文レビューし、Wordコメントを埋め込んだ新しいDOCXを返します。",
        primary_category=SkillCategory(id="general", label="General"),
        tags=["general", "docx", "review"],
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> SkillExecutionResult:
        del history

        context = skill_context or {}
        provider_id = str(context.get("provider_id") or "")
        model = str(context.get("model") or "").strip()
        progress = get_skill_progress(skill_context)
        await progress.update(stage="validate_input", label="入力を確認しています")
        if not self._supports_llm(provider_id=provider_id, model=model):
            return self._failure_result(
                assistant_response=(
                    "候補生成失敗: このSkillは OpenAI / Azure OpenAI の Responses API モデル専用です。"
                    " `gpt-5.4-2026-03-05` などを選択してください。"
                ),
                details=[],
            )

        attachments = context.get("attachments") or []
        if len(attachments) != 1:
            return self._failure_result(
                assistant_response="添付ファイル条件エラー: レビュー対象の `.docx` を 1 件だけ添付してください。",
                details=[],
            )

        attachment = attachments[0]
        original_path = Path(str(attachment.get("original_path") or ""))
        parsed_markdown_path = Path(str(attachment.get("parsed_markdown_path") or ""))
        source_name = str(attachment.get("name") or "").strip()
        if original_path.suffix.lower() != ".docx":
            return self._failure_result(
                assistant_response="添付ファイル形式エラー: `.docx` 形式の Word ファイルだけ対応しています。",
                source_name=source_name or None,
                details=[],
            )
        if not original_path.exists():
            return self._failure_result(
                assistant_response="原本ファイルが見つかりません。ファイルを再アップロードして再実行してください。",
                source_name=source_name or None,
                details=[f"Missing source path: {original_path}"],
            )

        conversation_id = str(context.get("conversation_id") or "").strip()
        generated_files_root = Path(str(context.get("generated_files_root") or "")).expanduser()
        if not conversation_id or not str(generated_files_root):
            return self._failure_result(
                assistant_response="内部設定エラー: 生成ファイルの保存先を解決できませんでした。",
                source_name=source_name or None,
                details=[],
            )

        generator = DocxCommentGenerator(source_path=original_path)
        await progress.update(stage="load_document", label="文書を読み込んでいます")
        generator.load()

        review_brief = self._normalize_review_brief(user_text=user_text, source_name=source_name)
        document_text = generator.review_text(max_chars=MAX_REVIEW_SOURCE_CHARS)
        markdown_source = ""
        if parsed_markdown_path.exists():
            markdown_source = parsed_markdown_path.read_text(encoding="utf-8").strip()
        review_source = (document_text or markdown_source).strip()
        if not review_source:
            return self._failure_result(
                assistant_response="本文抽出失敗: DOCX からレビュー本文を取り出せませんでした。ファイルを再アップロードしてください。",
                source_name=source_name or None,
                review_brief=review_brief,
                details=[],
            )

        await progress.update(stage="plan_comments", label="レビュー観点を抽出しています")
        planned_candidates = await self._plan_review_candidates(
            provider_id=provider_id,
            model=model,
            source_name=source_name,
            review_brief=review_brief,
            review_source=review_source,
        )
        if not planned_candidates:
            await progress.update(stage="draft_comments", label="コメント案を生成しています")
            finalized_candidates = await self._direct_review_candidates(
                provider_id=provider_id,
                model=model,
                source_name=source_name,
                review_brief=review_brief,
                review_source=review_source,
            )
        else:
            await progress.update(stage="draft_comments", label="コメント案を生成しています")
            finalized_candidates = await self._finalize_review_candidates(
                provider_id=provider_id,
                model=model,
                source_name=source_name,
                review_brief=review_brief,
                review_source=review_source,
                planned_candidates=planned_candidates,
            )

        if not finalized_candidates:
            return self._failure_result(
                assistant_response=(
                    "候補生成失敗: 文書から Word コメント候補を安定して生成できませんでした。"
                    " 修正方針を 1-2 文で具体化して再実行してください。"
                ),
                source_name=source_name or None,
                review_brief=review_brief,
                details=[],
            )

        await progress.update(stage="apply_comments", label="コメントを反映しています")
        applied, skipped = generator.apply_comments(finalized_candidates[:MAX_CANDIDATES])
        if not applied:
            return self._failure_result(
                assistant_response=self._mapping_failure_message(skipped),
                source_name=source_name or None,
                review_brief=review_brief,
                details=[f"{item.quote}: {item.reason}" for item in skipped[:5]],
            )

        await progress.update(stage="save_output", label="出力ファイルを保存しています")
        generated_file = self._save_generated_file(
            conversation_id=conversation_id,
            generated_files_root=generated_files_root,
            source_name=source_name,
            source_attachment_id=str(attachment.get("id") or "") or None,
            generator=generator,
        )
        return self._build_success_result(
            review_brief=review_brief,
            source_name=source_name,
            applied=applied,
            skipped=skipped,
            generated_file=generated_file,
        )

    def _save_generated_file(
        self,
        *,
        conversation_id: str,
        generated_files_root: Path,
        source_name: str,
        source_attachment_id: str | None,
        generator: DocxCommentGenerator,
    ) -> GeneratedFileArtifact:
        file_id = str(uuid4())
        output_dir = generated_files_root / conversation_id / file_id
        output_name = f"{Path(source_name).stem}.commented.docx"
        output_path = output_dir / output_name
        generator.save(output_path)
        return GeneratedFileArtifact(
            id=file_id,
            name=output_name,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            path=str(output_path),
            source_attachment_id=source_attachment_id,
        )

    async def _plan_review_candidates(
        self,
        *,
        provider_id: str,
        model: str,
        source_name: str,
        review_brief: str,
        review_source: str,
    ) -> list[dict[str, str]]:
        prompt = (
            "次の文書をレビューし、Wordコメント候補の下書きをJSONオブジェクトのみで返してください。"
            '形式は {"observations":[{"quote":string,"issue":string,"revision_goal":string,"category":string,"priority":"high"|"medium"|"low"}]}。'
            " quote は文書中にそのまま存在する短い連続文字列に限定し、最大120文字。"
            f"\n\n文書名: {source_name}\n観点: {review_brief}\n\n文書:\n{review_source[:MAX_REVIEW_SOURCE_CHARS]}"
        )
        raw = await run_json_prompt(
            provider_id=provider_id,
            model=model,
            prompt=prompt,
            max_output_tokens=PLAN_MAX_OUTPUT_TOKENS,
            reasoning_effort="high",
            json_schema=PLAN_SCHEMA,
        )
        observations = self._extract_candidate_rows(raw, preferred_keys=("observations", "items", "candidates", "comments"))
        if not observations:
            return []
        return [self._normalize_planned_candidate(item) for item in observations if isinstance(item, dict)]

    async def _finalize_review_candidates(
        self,
        *,
        provider_id: str,
        model: str,
        source_name: str,
        review_brief: str,
        review_source: str,
        planned_candidates: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not planned_candidates:
            return []

        prompt = (
            "次のレビュー下書きを、Wordコメントとしてそのまま使える最終JSON配列に整形してください。"
            ' 各要素は {"quote":string,"comment":string,"category":string,"priority":"high"|"medium"|"low"}。'
            f" 最大 {MAX_CANDIDATES} 件。 comment は日本語で、問題点と修正方針が分かる1-2文にしてください。"
            " quote は元文書の連続文字列をそのまま維持してください。"
            f"\n\n文書名: {source_name}\n観点: {review_brief}\n\n文書:\n{review_source[:MAX_REVIEW_SOURCE_CHARS]}\n\n"
            f"下書き:\n{json.dumps(planned_candidates[:12], ensure_ascii=False)}"
        )
        raw = await run_json_prompt(
            provider_id=provider_id,
            model=model,
            prompt=prompt,
            max_output_tokens=FINAL_MAX_OUTPUT_TOKENS,
            reasoning_effort="medium",
            json_schema=FINAL_SCHEMA,
        )
        rows = self._extract_candidate_rows(raw, preferred_keys=("comments", "items", "candidates", "observations"))
        if not rows:
            return self._fallback_finalize_candidates(planned_candidates)
        normalized = [self._normalize_final_candidate(item) for item in rows if isinstance(item, dict)]
        finalized = [item for item in normalized if item.get("quote") and item.get("comment")]
        if finalized:
            return finalized
        return self._fallback_finalize_candidates(planned_candidates)

    async def _direct_review_candidates(
        self,
        *,
        provider_id: str,
        model: str,
        source_name: str,
        review_brief: str,
        review_source: str,
    ) -> list[dict[str, str]]:
        prompt = (
            "次の文書をレビューし、Wordコメントとしてそのまま使えるJSONオブジェクトのみを返してください。"
            ' 形式は {"comments":[{"quote":string,"comment":string,"category":string,"priority":"high"|"medium"|"low"}]}。'
            f" 最大 {MAX_CANDIDATES} 件。 quote は文書中にそのまま存在する短い連続文字列に限定し、comment は日本語で簡潔にしてください。"
            f"\n\n文書名: {source_name}\n観点: {review_brief}\n\n文書:\n{review_source[:MAX_REVIEW_SOURCE_CHARS]}"
        )
        raw = await run_json_prompt(
            provider_id=provider_id,
            model=model,
            prompt=prompt,
            max_output_tokens=DIRECT_MAX_OUTPUT_TOKENS,
            reasoning_effort="high",
            json_schema=FINAL_SCHEMA,
        )
        rows = self._extract_candidate_rows(raw, preferred_keys=("comments", "items", "candidates", "observations"))
        normalized = [self._normalize_final_candidate(item) for item in rows if isinstance(item, dict)]
        return [item for item in normalized if item.get("quote") and item.get("comment")]

    def _normalize_review_brief(self, *, user_text: str, source_name: str) -> str:
        normalized_name = source_name.strip().lower()
        lines: list[str] = []
        for raw_line in user_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if INCIDENTAL_FILENAME_RE.match(line):
                continue
            if normalized_name and lowered == normalized_name:
                continue
            lines.append(line)
        merged = " ".join(lines).strip()
        return merged or DEFAULT_REVIEW_BRIEF

    def _supports_llm(self, *, provider_id: str, model: str) -> bool:
        if provider_id not in {"openai", "azure_openai"} or not model:
            return False
        return get_model_capability(provider_id, model).api_mode == "responses"

    def _normalize_planned_candidate(self, item: dict[str, Any]) -> dict[str, str]:
        return {
            "quote": self._clean_text(item.get("quote"), max_chars=120),
            "issue": self._clean_text(item.get("issue"), max_chars=240),
            "revision_goal": self._clean_text(item.get("revision_goal"), max_chars=240),
            "category": self._clean_label(item.get("category")),
            "priority": self._clean_priority(item.get("priority")),
        }

    def _normalize_final_candidate(self, item: dict[str, Any]) -> dict[str, str]:
        return {
            "quote": self._clean_text(item.get("quote"), max_chars=120),
            "comment": self._clean_text(item.get("comment"), max_chars=280),
            "category": self._clean_label(item.get("category")),
            "priority": self._clean_priority(item.get("priority")),
        }

    def _extract_candidate_rows(self, raw: str, *, preferred_keys: tuple[str, ...]) -> list[dict[str, Any]]:
        rows = extract_json_array(raw)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]

        obj = extract_json_object(raw) or {}
        for key in preferred_keys:
            value = obj.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _fallback_finalize_candidates(self, planned_candidates: list[dict[str, str]]) -> list[dict[str, str]]:
        finalized: list[dict[str, str]] = []
        for candidate in planned_candidates[:MAX_CANDIDATES]:
            quote = candidate.get("quote") or ""
            if not quote:
                continue
            issue = candidate.get("issue") or ""
            revision_goal = candidate.get("revision_goal") or ""
            comment = " ".join(part for part in (issue, revision_goal) if part).strip()
            if not comment:
                comment = "この箇所は表現を見直してください。"
            finalized.append(
                {
                    "quote": quote,
                    "comment": self._clean_text(comment, max_chars=280),
                    "category": self._clean_label(candidate.get("category")),
                    "priority": self._clean_priority(candidate.get("priority")),
                }
            )
        return finalized

    def _clean_text(self, value: Any, *, max_chars: int) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join(value.strip().split())[:max_chars]

    def _clean_label(self, value: Any) -> str:
        cleaned = self._clean_text(value, max_chars=40).lower()
        return cleaned or "general"

    def _clean_priority(self, value: Any) -> str:
        cleaned = self._clean_text(value, max_chars=10).lower()
        if cleaned in {"high", "medium", "low"}:
            return cleaned
        return "medium"

    def _build_success_result(
        self,
        *,
        review_brief: str,
        source_name: str,
        applied: list[AppliedComment],
        skipped: list[SkippedComment],
        generated_file: GeneratedFileArtifact,
    ) -> SkillExecutionResult:
        assistant_response = (
            f"レビューコメントを適用したDOCXを生成しました。適用{len(applied)}件 / スキップ{len(skipped)}件。ダウンロードしてください。"
        )
        lines = [
            f"レビュー方針: {review_brief}",
            f"適用コメント数: {len(applied)}",
            f"スキップ数: {len(skipped)}",
        ]
        if applied:
            lines.append("主な適用コメント:")
            for item in applied[:3]:
                lines.append(f"- [{item.priority}] {item.quote} -> {item.comment}")
        if skipped:
            lines.append("主なスキップ理由:")
            for item in skipped[:5]:
                lines.append(f"- {item.quote}: {item.reason}")

        artifacts = [
            CardListBlock(
                title="DOCX auto comment result",
                sections=[
                    CardSection(
                        id="docx_auto_commenter_result",
                        title="Review result",
                        summary="LLM が抽出した候補をもとに Word コメントを付与しました。",
                        items=[
                            CardItem(
                                id="docx_auto_commenter_summary",
                                title="Generated document",
                                metadata=[
                                    MetadataItem(label="Source", value=source_name),
                                    MetadataItem(label="Applied", value=str(len(applied))),
                                    MetadataItem(label="Skipped", value=str(len(skipped))),
                                ],
                                lines=[
                                    CardLine(label="Review brief", value=review_brief),
                                    CardLine(label="Applied comments", value=str(len(applied))),
                                    CardLine(label="Skipped comments", value=str(len(skipped))),
                                ]
                                + [
                                    CardLine(label="Skipped", value=f"{item.quote}: {item.reason}")
                                    for item in skipped[:3]
                                ],
                                links=[
                                    LinkItem(
                                        label="Download commented DOCX",
                                        url=f"/api/generated-files/{generated_file.id}/download",
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
        return SkillExecutionResult(
            llm_context="\n".join(lines),
            assistant_response=assistant_response,
            artifacts=artifacts,
            options=SkillExecutionOptions(disable_web_tool=True, skip_model_response=True),
            generated_files=[generated_file],
        )

    def _failure_result(
        self,
        *,
        assistant_response: str,
        details: list[str],
        source_name: str | None = None,
        review_brief: str | None = None,
    ) -> SkillExecutionResult:
        lines = [assistant_response]
        if source_name:
            lines.append(f"対象ファイル: {source_name}")
        if review_brief:
            lines.append(f"レビュー方針: {review_brief}")
        lines.extend([f"- {detail}" for detail in details])
        message = "\n".join(lines)
        return SkillExecutionResult(
            llm_context=message,
            assistant_response=assistant_response,
            artifacts=[MarkdownBlock(content=message)],
            options=SkillExecutionOptions(disable_web_tool=True, skip_model_response=True),
        )

    def _mapping_failure_message(self, skipped: list[SkippedComment]) -> str:
        if skipped and all("multiple locations" in item.reason for item in skipped):
            return (
                "一意マッピング失敗: LLM が選んだ引用が文書内で複数箇所に一致したため、コメント付きDOCXを生成できませんでした。"
            )
        if skipped and all("not found" in item.reason for item in skipped):
            return "本文マッピング失敗: コメント候補の引用を文書本文で一致させられず、コメント付きDOCXを生成できませんでした。"
        return "コメント適用失敗: コメント候補は生成されましたが、本文へ安全に適用できませんでした。"


def build_skill() -> Skill:
    return DocxAutoCommenterSkill()
