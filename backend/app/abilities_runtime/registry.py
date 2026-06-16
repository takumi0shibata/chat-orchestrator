from __future__ import annotations

from typing import Any

from app.abilities_runtime.base import (
    Ability,
    AbilityAttachment,
    AbilityExecutionResult,
    AbilityInvocation,
    AbilityMetadata,
    DEFAULT_ABILITY_INPUT_SCHEMA,
    validate_ability_input_schema,
)
from app.skills_runtime.base import (
    SKILL_RUNTIME_CONTEXT_KEY,
    Skill,
    SkillProgressReporter,
    SkillRuntimeContext,
)


class SkillAbility(Ability):
    def __init__(self, skill: Skill) -> None:
        self.skill = skill
        input_schema = getattr(skill, "ability_input_schema", DEFAULT_ABILITY_INPUT_SCHEMA)
        self.metadata = AbilityMetadata(
            id=skill.metadata.id,
            name=skill.metadata.name,
            description=skill.metadata.description,
            primary_category={
                "id": skill.metadata.primary_category.id,
                "label": skill.metadata.primary_category.label,
            },
            tags=list(skill.metadata.tags),
            input_schema=validate_ability_input_schema(input_schema),
        )

    async def run(self, invocation: AbilityInvocation) -> AbilityExecutionResult:
        skill_context: dict[str, Any] = {
            "provider_id": invocation.runtime.provider_id,
            "model": invocation.runtime.model,
            "conversation_id": invocation.runtime.conversation_id,
            "generated_files_root": invocation.runtime.generated_files_root,
            "attachments": [self._attachment_descriptor(item) for item in invocation.attachments],
            "ability_params": dict(invocation.params),
            SKILL_RUNTIME_CONTEXT_KEY: SkillRuntimeContext(progress=invocation.progress),
        }
        skill_context.update(invocation.runtime.metadata)
        result = await self.skill.run(
            user_text=invocation.user_text,
            history=invocation.history,
            skill_context=skill_context,
        )
        return AbilityExecutionResult.from_skill_result(
            ability_id=self.metadata.id,
            ability_name=self.metadata.name,
            result=result,
        )

    def _attachment_descriptor(self, attachment: AbilityAttachment) -> dict[str, str | int | None]:
        return {
            "id": attachment.id,
            "name": attachment.name,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size_bytes,
            "original_path": attachment.original_path,
            "parsed_markdown_path": attachment.parsed_markdown_path,
        }


class AbilityRegistry:
    def __init__(self) -> None:
        self._abilities: dict[str, Ability] = {}

    @classmethod
    def from_skills(cls, skills: list[Skill]) -> "AbilityRegistry":
        registry = cls()
        for skill in skills:
            registry.register(SkillAbility(skill))
        return registry

    def register(self, ability: Ability) -> None:
        ability_id = ability.metadata.id
        if ability_id in self._abilities:
            raise ValueError(f"Duplicate ability id: {ability_id}")
        validate_ability_input_schema(ability.metadata.input_schema)
        self._abilities[ability_id] = ability

    def list_abilities(self) -> list[Ability]:
        return [self._abilities[key] for key in sorted(self._abilities)]

    def get(self, ability_id: str) -> Ability | None:
        return self._abilities.get(ability_id)

    def resolve(
        self,
        *,
        ability_ids: list[str] | None,
        legacy_skill_id: str | None,
    ) -> list[Ability]:
        requested_ids = [item.strip() for item in ability_ids or [] if item.strip()]
        if legacy_skill_id and not requested_ids:
            requested_ids = [legacy_skill_id.strip()]
        if not requested_ids:
            return self.list_abilities()

        resolved: list[Ability] = []
        missing: list[str] = []
        for ability_id in requested_ids:
            ability = self.get(ability_id)
            if ability is None:
                missing.append(ability_id)
            else:
                resolved.append(ability)
        if missing:
            raise KeyError(", ".join(missing))
        return resolved
