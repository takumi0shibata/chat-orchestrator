import re
from typing import Any

from app.skills_runtime.base import Skill, SkillMetadata


class TodoExtractorSkill(Skill):
    metadata = SkillMetadata(
        id="todo_extractor",
        name="TODO Extractor",
        description="入力文から行動可能なTODOを抽出して箇条書き化します。",
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> str:
        parts = re.split(r"[。.!?\n]", user_text)
        candidates = [p.strip() for p in parts if p.strip()]
        bullets = []
        for item in candidates:
            if len(item) < 4:
                continue
            bullets.append(f"- {item}")
        if not bullets:
            return "- TODO候補は見つかりませんでした。"
        return "\n".join(bullets[:8])


def build_skill() -> Skill:
    return TodoExtractorSkill()
