from typing import Any

from app.skills_runtime.base import (
    Skill,
    SkillCategory,
    SkillExecutionResult,
    SkillMetadata,
    context_only_result,
    get_skill_progress,
)


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
        progress = get_skill_progress(skill_context)
        await progress.update(stage="inspect_input", label="入力を確認しています")
        attachments = (skill_context or {}).get("attachments", [])
        del history, attachments
        await progress.update(stage="build_context", label="結果を整えています")
        return context_only_result(f"Input: {user_text}")


def build_skill() -> Skill:
    return ExampleSkill()
