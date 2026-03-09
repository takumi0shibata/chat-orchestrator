from typing import Any

from app.skills_runtime.base import Skill, SkillCategory, SkillExecutionResult, SkillMetadata, context_only_result


class ExampleSkill(Skill):
    metadata = SkillMetadata(
        id="example_skill",
        name="Example Skill",
        description="何をする skill かを1文で書く。",
        primary_category=SkillCategory(id="general", label="General"),
        tags=["general", "example"],
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> SkillExecutionResult:
        del history, skill_context
        return context_only_result(f"Input: {user_text}")


def build_skill() -> Skill:
    return ExampleSkill()
