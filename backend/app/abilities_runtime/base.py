from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import Field

from app.skills_runtime.base import (
    FeedbackTarget,
    GeneratedFileArtifact,
    SkillExecutionOptions,
    SkillExecutionResult,
    SkillModel,
    SkillProgressReporter,
    UiBlock,
)


DEFAULT_ABILITY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "task": {
            "type": "string",
            "description": "Optional ability-specific instruction or query.",
        }
    },
}


class AbilityMetadata(SkillModel):
    id: str
    name: str
    description: str
    primary_category: dict[str, str]
    tags: list[str]
    input_schema: dict[str, Any] = Field(default_factory=lambda: dict(DEFAULT_ABILITY_INPUT_SCHEMA))


class AbilityAttachment(SkillModel):
    id: str
    name: str
    content_type: str
    size_bytes: int
    original_path: str
    parsed_markdown_path: str


@dataclass(frozen=True)
class AbilityRuntimeContext:
    provider_id: str
    model: str
    conversation_id: str
    generated_files_root: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AbilityInvocation:
    user_text: str
    history: list[dict[str, str]]
    attachments: list[AbilityAttachment]
    runtime: AbilityRuntimeContext
    params: dict[str, Any] = field(default_factory=dict)
    progress: SkillProgressReporter = field(default_factory=SkillProgressReporter)


class AbilityExecutionResult(SkillModel):
    ability_id: str
    ability_name: str
    summary: str = ""
    llm_context: str = ""
    assistant_response: str | None = None
    artifacts: list[UiBlock] = Field(default_factory=list)
    options: SkillExecutionOptions = Field(default_factory=SkillExecutionOptions)
    feedback_targets: list[FeedbackTarget] = Field(default_factory=list)
    generated_files: list[GeneratedFileArtifact] = Field(default_factory=list)

    def to_skill_result(self) -> SkillExecutionResult:
        return SkillExecutionResult(
            llm_context=self.llm_context,
            assistant_response=self.assistant_response,
            artifacts=list(self.artifacts),
            options=self.options,
            feedback_targets=list(self.feedback_targets),
            generated_files=list(self.generated_files),
        )

    @classmethod
    def from_skill_result(
        cls,
        *,
        ability_id: str,
        ability_name: str,
        result: SkillExecutionResult,
    ) -> "AbilityExecutionResult":
        return cls(
            ability_id=ability_id,
            ability_name=ability_name,
            summary=_summarize_skill_result(result),
            llm_context=result.llm_context,
            assistant_response=result.assistant_response,
            artifacts=list(result.artifacts),
            options=result.options,
            feedback_targets=list(result.feedback_targets),
            generated_files=list(result.generated_files),
        )


ProgressCallback = Callable[[str, str], Awaitable[None]]


class Ability(ABC):
    metadata: AbilityMetadata

    @abstractmethod
    async def run(self, invocation: AbilityInvocation) -> AbilityExecutionResult:
        raise NotImplementedError


def validate_ability_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise ValueError("Ability input_schema must be a mapping")
    schema_type = schema.get("type")
    if schema_type != "object":
        raise ValueError("Ability input_schema.type must be 'object'")
    properties = schema.get("properties")
    if properties is not None and not isinstance(properties, dict):
        raise ValueError("Ability input_schema.properties must be a mapping")
    return schema


def _summarize_skill_result(result: SkillExecutionResult) -> str:
    if result.assistant_response and result.assistant_response.strip():
        return result.assistant_response.strip()[:500]
    if result.llm_context.strip():
        return result.llm_context.strip()[:500]
    if result.generated_files:
        names = ", ".join(item.name for item in result.generated_files[:3])
        return f"Generated files: {names}"
    if result.artifacts:
        return f"Produced {len(result.artifacts)} artifact(s)."
    return "Completed."
