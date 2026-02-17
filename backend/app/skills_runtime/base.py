from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SkillMetadata:
    id: str
    name: str
    description: str


class Skill(ABC):
    metadata: SkillMetadata

    @abstractmethod
    async def run(self, user_text: str, history: list[dict[str, str]]) -> str:
        raise NotImplementedError
