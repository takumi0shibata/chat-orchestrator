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


class TodoExtractorSkill(Skill):
    metadata = SkillMetadata(
        id="todo_extractor",
        name="TODO Extractor",
        description="入力文から行動可能なTODOを抽出して箇条書き化します。",
        primary_category=SkillCategory(id="general", label="General"),
        tags=["general", "todo", "productivity"],
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> SkillExecutionResult:
        progress = get_skill_progress(skill_context)
        await progress.update(stage="parse_input", label="入力を分解しています")
        parts = re.split(r"[。.!?\n]", user_text)
        candidates = [p.strip() for p in parts if p.strip()]
        await progress.update(stage="extract_todos", label="TODO候補を整理しています")
        bullets = []
        for item in candidates:
            if len(item) < 4:
                continue
            bullets.append(f"- {item}")
        if not bullets:
            return context_only_result("- TODO候補は見つかりませんでした。")
        return context_only_result("\n".join(bullets[:8]))


def build_skill() -> Skill:
    return TodoExtractorSkill()
