from pathlib import Path

import pytest

from app.skills_runtime.manager import SkillManager


SKILL_TEMPLATE = """from typing import Any

from app.skills_runtime.base import Skill, SkillCategory, SkillExecutionResult, SkillMetadata, context_only_result


class TempSkill(Skill):
    metadata = SkillMetadata(
        id="{skill_id}",
        name="{name}",
        description="{description}",
        primary_category=SkillCategory(id="{category_id}", label="{category_label}"),
        tags={tags},
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> SkillExecutionResult:
        del history, skill_context
        return context_only_result(user_text)


def build_skill() -> Skill:
    return TempSkill()
"""


def _write_skill(
    root: Path,
    *,
    folder_name: str,
    skill_id: str,
    name: str = "Temp Skill",
    description: str = "Temporary skill",
    category_id: str = "general",
    category_label: str = "General",
    tags: list[str] | None = None,
    readme: bool = True,
    manifest_override: str | None = None,
) -> None:
    skill_dir = root / folder_name
    skill_dir.mkdir(parents=True)
    tags = tags or ["general", "temp"]
    (skill_dir / "skill.py").write_text(
        SKILL_TEMPLATE.format(
            skill_id=skill_id,
            name=name,
            description=description,
            category_id=category_id,
            category_label=category_label,
            tags=tags,
        ),
        encoding="utf-8",
    )
    manifest = manifest_override or f"""id: {skill_id}
name: {name}
description: {description}
primary_category:
  id: {category_id}
  label: {category_label}
tags:
  - {tags[0]}
  - {tags[1]}
entrypoint: skill.py
factory: build_skill
readme: README.md
"""
    (skill_dir / "skill.yaml").write_text(manifest, encoding="utf-8")
    if readme:
        (skill_dir / "README.md").write_text("# Temp Skill\n", encoding="utf-8")


def test_skill_manager_loads_manifest_driven_skill(tmp_path: Path) -> None:
    _write_skill(tmp_path, folder_name="temp_skill", skill_id="temp_skill")

    manager = SkillManager(tmp_path)
    manager.load()

    loaded = manager.get("temp_skill")
    assert loaded is not None
    assert loaded.metadata.id == "temp_skill"
    assert loaded.metadata.tags == ["general", "temp"]


def test_skill_manager_requires_readme(tmp_path: Path) -> None:
    _write_skill(tmp_path, folder_name="temp_skill", skill_id="temp_skill", readme=False)

    manager = SkillManager(tmp_path)
    with pytest.raises(ValueError, match="Skill README not found"):
        manager.load()


def test_skill_manager_rejects_duplicate_ids(tmp_path: Path) -> None:
    _write_skill(tmp_path, folder_name="temp_skill_a", skill_id="shared_skill")
    _write_skill(tmp_path, folder_name="temp_skill_b", skill_id="shared_skill")

    manager = SkillManager(tmp_path)
    with pytest.raises(ValueError, match="Duplicate skill id"):
        manager.load()


def test_skill_manager_rejects_metadata_mismatch(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        folder_name="temp_skill",
        skill_id="temp_skill",
        manifest_override="""id: temp_skill
name: Different Name
description: Temporary skill
primary_category:
  id: general
  label: General
tags:
  - general
  - temp
entrypoint: skill.py
factory: build_skill
readme: README.md
""",
    )

    manager = SkillManager(tmp_path)
    with pytest.raises(ValueError, match="Skill metadata mismatch"):
        manager.load()
