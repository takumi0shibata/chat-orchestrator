import importlib.util
from pathlib import Path

from app.skills_runtime.base import Skill


class SkillManager:
    def __init__(self, skills_root: Path) -> None:
        self.skills_root = skills_root
        self._skills: dict[str, Skill] = {}

    def load(self) -> None:
        if not self.skills_root.exists():
            return

        for entry in self.skills_root.iterdir():
            module_path = entry / "skill.py"
            if not module_path.is_file():
                continue

            spec = importlib.util.spec_from_file_location(f"skill_{entry.name}", module_path)
            if not spec or not spec.loader:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            skill = module.build_skill()
            self._skills[skill.metadata.id] = skill

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)
