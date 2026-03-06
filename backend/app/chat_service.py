from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from fastapi import HTTPException

from app.schemas import ChatMessage, ChatRequest
from app.skills_runtime.base import SkillExecutionResult
from app.skills_runtime.manager import SkillManager
from app.storage import ChatStore


@dataclass
class PreparedChatTurn:
    conversation_id: str
    user_input: str
    prepared_messages: list[ChatMessage]
    skill_result: SkillExecutionResult | None
    effective_web_tool: bool | None


class ChatOrchestrator:
    def __init__(self, *, store: ChatStore, skills: SkillManager) -> None:
        self.store = store
        self.skills = skills

    async def prepare_turn(self, payload: ChatRequest) -> PreparedChatTurn:
        if not payload.user_input.strip():
            raise HTTPException(status_code=400, detail="user_input cannot be empty")

        conversation_id = self.store.ensure_conversation(payload.conversation_id)
        history = self.store.get_messages(conversation_id)
        user_input = payload.user_input.strip()
        prepared_messages = [*history, ChatMessage(role="user", content=user_input)]
        skill_result: SkillExecutionResult | None = None

        if payload.skill_id:
            skill = self.skills.get(payload.skill_id)
            if not skill:
                raise HTTPException(status_code=400, detail=f"Unknown skill: {payload.skill_id}")
            skill_history = [{"role": item.role, "content": item.content} for item in prepared_messages]
            skill_result = await skill.run(
                user_text=user_input,
                history=skill_history,
                skill_context={"provider_id": payload.provider_id, "model": payload.model},
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
        )

    def persist_user_message(self, *, conversation_id: str, user_input: str) -> None:
        self.store.ensure_title_from_user_input(conversation_id, user_input)
        self.store.add_message(conversation_id, ChatMessage(role="user", content=user_input))

    def build_assistant_message(
        self,
        *,
        content: str,
        skill_id: str | None,
        skill_result: SkillExecutionResult | None,
    ) -> ChatMessage:
        return ChatMessage(
            role="assistant",
            content=content,
            artifacts=list(skill_result.artifacts) if skill_result else [],
            skill_id=skill_id,
        )

    def persist_assistant_message(
        self,
        *,
        conversation_id: str,
        message: ChatMessage,
        skill_result: SkillExecutionResult | None,
    ) -> None:
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
