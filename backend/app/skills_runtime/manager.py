from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import yaml

from app.skills_runtime.base import Skill, SkillCategory, SkillManifest, SkillMetadata


def _default_ability_input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "task": {
                "type": "string",
                "description": "Optional ability-specific instruction or query.",
            }
        },
    }


def _validate_ability_input_schema(raw: object, *, manifest_path: Path) -> dict[str, object]:
    if raw is None:
        return _default_ability_input_schema()
    if not isinstance(raw, dict):
        raise ValueError(f"Skill ability input_schema must be a mapping: {manifest_path}")
    if raw.get("type") != "object":
        raise ValueError(f"Skill ability input_schema.type must be 'object': {manifest_path}")
    properties = raw.get("properties")
    if properties is not None and not isinstance(properties, dict):
        raise ValueError(f"Skill ability input_schema.properties must be a mapping: {manifest_path}")
    return raw


class SkillManager:
    def __init__(self, skills_root: Path) -> None:
        self.skills_root = skills_root
        self._skills: dict[str, Skill] = {}

    def load(self) -> None:
        self._skills = {}
        if not self.skills_root.exists():
            return

        for entry in sorted(self.skills_root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue

            manifest = self._load_manifest(entry)
            skill = self._build_skill(entry=entry, manifest=manifest)

            if manifest.metadata.id in self._skills:
                raise ValueError(f"Duplicate skill id: {manifest.metadata.id}")
            self._skills[manifest.metadata.id] = skill

    def list_skills(self) -> list[Skill]:
        return [self._skills[key] for key in sorted(self._skills)]

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def _load_manifest(self, entry: Path) -> SkillManifest:
        manifest_path = entry / "skill.yaml"
        if not manifest_path.is_file():
            raise ValueError(f"Missing skill manifest: {manifest_path}")

        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Skill manifest must be a mapping: {manifest_path}")
        category_raw = raw.get("primary_category") or {}
        if not isinstance(category_raw, dict):
            raise ValueError(f"Skill primary_category must be a mapping: {manifest_path}")
        tags_raw = raw.get("tags") or []
        if not isinstance(tags_raw, list):
            raise ValueError(f"Skill tags must be a list: {manifest_path}")
        ability_raw = raw.get("ability") or {}
        if not isinstance(ability_raw, dict):
            raise ValueError(f"Skill ability must be a mapping: {manifest_path}")
        input_schema = _validate_ability_input_schema(
            ability_raw.get("input_schema", raw.get("input_schema")),
            manifest_path=manifest_path,
        )

        metadata = SkillMetadata(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or ""),
            description=str(raw.get("description") or ""),
            primary_category=SkillCategory(
                id=str(category_raw.get("id") or ""),
                label=str(category_raw.get("label") or ""),
            ),
            tags=[str(tag) for tag in tags_raw],
        )
        manifest = SkillManifest(
            metadata=metadata,
            entrypoint=str(raw.get("entrypoint") or "skill.py"),
            factory=str(raw.get("factory") or "build_skill"),
            readme=str(raw.get("readme") or "README.md"),
            ability_input_schema=input_schema,
        )

        module_path = entry / manifest.module_path
        readme_path = entry / manifest.readme_path
        if not module_path.is_file():
            raise ValueError(f"Skill entrypoint not found: {module_path}")
        if not readme_path.is_file():
            raise ValueError(f"Skill README not found: {readme_path}")

        return manifest

    def _build_skill(self, *, entry: Path, manifest: SkillManifest) -> Skill:
        module = self._load_module(module_path=entry / manifest.module_path, module_name=f"skill_{entry.name}")
        factory = getattr(module, manifest.factory, None)
        if factory is None or not callable(factory):
            raise ValueError(f"Skill factory `{manifest.factory}` not found in {entry / manifest.module_path}")

        skill = factory()
        if not isinstance(skill, Skill):
            raise TypeError(f"Skill factory `{manifest.factory}` must return Skill")

        current_metadata = getattr(skill, "metadata", None)
        if current_metadata is not None and current_metadata.as_comparable() != manifest.metadata.as_comparable():
            raise ValueError(
                f"Skill metadata mismatch for {manifest.metadata.id}: "
                f"manifest={manifest.metadata.as_comparable()} runtime={current_metadata.as_comparable()}"
            )

        skill.metadata = manifest.metadata
        skill.ability_input_schema = manifest.ability_input_schema
        return skill

    def _load_module(self, *, module_path: Path, module_name: str) -> ModuleType:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if not spec or not spec.loader:
            raise ValueError(f"Failed to load skill module: {module_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
