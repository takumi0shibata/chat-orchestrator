from typing import Any

import pytest

from app.abilities_runtime.base import Ability, AbilityExecutionResult, AbilityInvocation, AbilityMetadata
from app.abilities_runtime.registry import AbilityRegistry
from app.skills_runtime.base import SkillCategory, SkillMetadata, context_only_result
from app.skills_runtime.manager import SkillManager


class FakeAbility(Ability):
    def __init__(self, ability_id: str, input_schema: dict[str, Any] | None = None) -> None:
        self.metadata = AbilityMetadata(
            id=ability_id,
            name=ability_id,
            description="Temporary ability",
            primary_category={"id": "general", "label": "General"},
            tags=["general"],
            input_schema=input_schema or {"type": "object", "properties": {}, "additionalProperties": True},
        )

    async def run(self, invocation: AbilityInvocation) -> AbilityExecutionResult:
        del invocation
        return AbilityExecutionResult(ability_id=self.metadata.id, ability_name=self.metadata.name)


def test_ability_registry_rejects_duplicate_ids() -> None:
    registry = AbilityRegistry()
    registry.register(FakeAbility("same"))

    with pytest.raises(ValueError, match="Duplicate ability id"):
        registry.register(FakeAbility("same"))


def test_ability_registry_rejects_invalid_input_schema() -> None:
    registry = AbilityRegistry()

    with pytest.raises(ValueError, match="input_schema.type"):
        registry.register(FakeAbility("bad", input_schema={"type": "array"}))


def test_skill_manifest_can_define_ability_input_schema(tmp_path) -> None:
    skill_dir = tmp_path / "context"
    skill_dir.mkdir()
    (skill_dir / "README.md").write_text("# Context\n", encoding="utf-8")
    (skill_dir / "skill.yaml").write_text(
        """
id: context
name: Context
description: Adds context.
primary_category:
  id: general
  label: General
tags:
  - general
entrypoint: skill.py
factory: build_skill
readme: README.md
ability:
  input_schema:
    type: object
    additionalProperties: false
    properties:
      topic:
        type: string
""",
        encoding="utf-8",
    )
    (skill_dir / "skill.py").write_text(
        """
from typing import Any

from app.skills_runtime.base import Skill, SkillCategory, SkillExecutionResult, SkillMetadata, context_only_result


class ContextSkill(Skill):
    metadata = SkillMetadata(
        id="context",
        name="Context",
        description="Adds context.",
        primary_category=SkillCategory(id="general", label="General"),
        tags=["general"],
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
    return ContextSkill()
""",
        encoding="utf-8",
    )

    manager = SkillManager(tmp_path)
    manager.load()
    registry = AbilityRegistry.from_skills(manager.list_skills())

    ability = registry.get("context")
    assert ability is not None
    assert ability.metadata.input_schema["additionalProperties"] is False
    assert "topic" in ability.metadata.input_schema["properties"]


def test_skill_manifest_rejects_invalid_ability_schema(tmp_path) -> None:
    skill_dir = tmp_path / "bad"
    skill_dir.mkdir()
    (skill_dir / "README.md").write_text("# Bad\n", encoding="utf-8")
    (skill_dir / "skill.py").write_text(
        """
from typing import Any

from app.skills_runtime.base import Skill, SkillCategory, SkillExecutionResult, SkillMetadata, context_only_result


class BadSkill(Skill):
    metadata = SkillMetadata(
        id="bad",
        name="Bad",
        description="Bad schema.",
        primary_category=SkillCategory(id="general", label="General"),
        tags=["general"],
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
    return BadSkill()
""",
        encoding="utf-8",
    )
    (skill_dir / "skill.yaml").write_text(
        """
id: bad
name: Bad
description: Bad schema.
primary_category:
  id: general
  label: General
tags:
  - general
ability:
  input_schema:
    type: array
""",
        encoding="utf-8",
    )

    manager = SkillManager(tmp_path)
    with pytest.raises(ValueError, match="input_schema.type"):
        manager.load()
