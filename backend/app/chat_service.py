from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.schemas import AttachmentSummary, ChatMessage, ChatRequest, StoredAttachment
from app.skills_runtime.base import (
    SKILL_RUNTIME_CONTEXT_KEY,
    SkillExecutionResult,
    SkillProgressReporter,
    SkillRuntimeContext,
)
from app.skills_runtime.manager import SkillManager
from app.storage import ChatStore


@dataclass
class PreparedChatTurn:
    conversation_id: str
    user_input: str
    prepared_messages: list[ChatMessage]
    skill_result: SkillExecutionResult | None
    effective_web_tool: bool | None
    attachments: list[StoredAttachment]


class ChatOrchestrator:
    def __init__(self, *, store: ChatStore, skills: SkillManager) -> None:
        self.store = store
        self.skills = skills

    async def prepare_turn(
        self,
        payload: ChatRequest,
        *,
        progress_reporter: SkillProgressReporter | None = None,
    ) -> PreparedChatTurn:
        conversation_id = self.store.ensure_conversation(payload.conversation_id)
        user_input = payload.user_input.strip()
        attachment_ids = [attachment_id.strip() for attachment_id in payload.attachment_ids if attachment_id.strip()]
        if not user_input and not attachment_ids:
            raise HTTPException(status_code=400, detail="user_input or attachment_ids is required")

        attachments = self.store.get_attachments(conversation_id=conversation_id, attachment_ids=attachment_ids)
        if len(attachments) != len(attachment_ids):
            found_ids = {attachment.id for attachment in attachments}
            missing = [attachment_id for attachment_id in attachment_ids if attachment_id not in found_ids]
            raise HTTPException(status_code=400, detail=f"Unknown attachment ids: {', '.join(missing)}")

        history = self.store.get_messages(conversation_id)
        prepared_user_input = user_input or "Please use the attached files as the primary context."
        prepared_messages = [
            *history,
            ChatMessage(
                role="user",
                content=prepared_user_input,
                attachments=self._attachment_summaries(attachments),
            ),
        ]
        skill_result: SkillExecutionResult | None = None

        if attachments and not payload.skill_id:
            prepared_messages = [
                ChatMessage(role="system", content=self._attachment_context(attachments)),
                *prepared_messages,
            ]

        if payload.skill_id:
            skill = self.skills.get(payload.skill_id)
            if not skill:
                raise HTTPException(status_code=400, detail=f"Unknown skill: {payload.skill_id}")
            skill_progress = progress_reporter or SkillProgressReporter()
            skill_history = [{"role": item.role, "content": item.content} for item in prepared_messages]
            skill_result = await skill.run(
                user_text=user_input,
                history=skill_history,
                skill_context={
                    "provider_id": payload.provider_id,
                    "model": payload.model,
                    "conversation_id": conversation_id,
                    "generated_files_root": str(self.store.generated_files_root),
                    "attachments": [self._skill_attachment_descriptor(attachment) for attachment in attachments],
                    SKILL_RUNTIME_CONTEXT_KEY: SkillRuntimeContext(progress=skill_progress),
                },
            )
            if skill_result.llm_context.strip():
                prepared_messages = [
                    ChatMessage(
                        role="system",
                        content=(
                            "You have supplemental context from a local skill. Use it when relevant.\n"
                            f"[Skill:{payload.skill_id}]\n{skill_result.llm_context}"
                        ),
                    ),
                    *prepared_messages,
                ]

        effective_web_tool = payload.enable_web_tool
        if skill_result and skill_result.options.disable_web_tool:
            effective_web_tool = False

        return PreparedChatTurn(
            conversation_id=conversation_id,
            user_input=user_input,
            prepared_messages=prepared_messages,
            skill_result=skill_result,
            effective_web_tool=effective_web_tool,
            attachments=attachments,
        )

    def persist_user_message(
        self,
        *,
        conversation_id: str,
        user_input: str,
        attachments: list[StoredAttachment],
    ) -> None:
        self.store.ensure_title_from_user_input(
            conversation_id,
            user_input,
            fallback_attachment_name=attachments[0].name if attachments else None,
        )
        message_id = self.store.add_message(
            conversation_id,
            ChatMessage(
                role="user",
                content=user_input,
                attachments=self._attachment_summaries(attachments),
            ),
        )
        self.store.attach_pending_attachments(
            conversation_id=conversation_id,
            attachment_ids=[attachment.id for attachment in attachments],
            message_id=message_id,
        )

    def build_assistant_message(
        self,
        *,
        content: str,
        skill_id: str | None,
        skill_result: SkillExecutionResult | None,
    ) -> ChatMessage:
        resolved_content = self.resolve_assistant_content(content=content, skill_result=skill_result)
        return ChatMessage(
            role="assistant",
            content=resolved_content,
            artifacts=list(skill_result.artifacts) if skill_result else [],
            skill_id=skill_id,
        )

    def should_skip_model_response(self, skill_result: SkillExecutionResult | None) -> bool:
        return bool(skill_result and skill_result.options.skip_model_response)

    def resolve_assistant_content(self, *, content: str, skill_result: SkillExecutionResult | None) -> str:
        if not self.should_skip_model_response(skill_result):
            return content
        if skill_result and skill_result.assistant_response is not None:
            return skill_result.assistant_response
        return content

    def persist_assistant_message(
        self,
        *,
        conversation_id: str,
        message: ChatMessage,
        skill_result: SkillExecutionResult | None,
    ) -> None:
        if skill_result and skill_result.generated_files:
            for generated_file in skill_result.generated_files:
                self.store.add_generated_file(
                    file_id=generated_file.id,
                    conversation_id=conversation_id,
                    skill_id=message.skill_id or "local_skill",
                    source_attachment_id=generated_file.source_attachment_id,
                    name=generated_file.name,
                    content_type=generated_file.content_type,
                    path=generated_file.path,
                )
        self.store.add_message(conversation_id, message)
        if skill_result and skill_result.feedback_targets:
            grouped: dict[str, list[str]] = defaultdict(list)
            for target in skill_result.feedback_targets:
                grouped[target.run_id].append(target.item_id)
            for run_id, item_ids in grouped.items():
                self.store.record_feedback_targets(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    item_ids=item_ids,
                )

    def _attachment_summaries(self, attachments: list[StoredAttachment]) -> list[AttachmentSummary]:
        return [
            AttachmentSummary(
                id=attachment.id,
                name=attachment.name,
                content_type=attachment.content_type,
                size_bytes=attachment.size_bytes,
            )
            for attachment in attachments
        ]

    def _attachment_context(self, attachments: list[StoredAttachment]) -> str:
        sections: list[str] = ["You have supplemental context from uploaded attachments. Use it when relevant."]
        for attachment in attachments:
            text = Path(attachment.parsed_markdown_path).read_text(encoding="utf-8").strip()
            sections.append(f"[Attachment:{attachment.name}]\n{text}")
        return "\n\n".join(sections)

    def _skill_attachment_descriptor(self, attachment: StoredAttachment) -> dict[str, str | int | None]:
        return {
            "id": attachment.id,
            "name": attachment.name,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size_bytes,
            "original_path": attachment.original_path,
            "parsed_markdown_path": attachment.parsed_markdown_path,
        }
