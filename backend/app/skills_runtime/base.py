from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Awaitable, Callable, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


@dataclass(frozen=True)
class SkillCategory:
    id: str
    label: str


@dataclass
class SkillMetadata:
    id: str
    name: str
    description: str
    primary_category: SkillCategory
    tags: list[str]

    def __post_init__(self) -> None:
        self.id = self.id.strip()
        self.name = self.name.strip()
        self.description = self.description.strip()
        self.primary_category = SkillCategory(
            id=self.primary_category.id.strip(),
            label=self.primary_category.label.strip(),
        )

        if not self.id:
            raise ValueError("SkillMetadata.id cannot be empty")
        if not self.name:
            raise ValueError("SkillMetadata.name cannot be empty")
        if not self.description:
            raise ValueError("SkillMetadata.description cannot be empty")
        if not self.primary_category.id.strip():
            raise ValueError("SkillMetadata.primary_category.id cannot be empty")
        if not self.primary_category.label.strip():
            raise ValueError("SkillMetadata.primary_category.label cannot be empty")
        if not self.tags:
            raise ValueError("SkillMetadata.tags cannot be empty")

        deduped_tags: list[str] = []
        for tag in self.tags:
            normalized = tag.strip()
            if not normalized:
                raise ValueError("SkillMetadata.tags cannot contain empty values")
            if normalized not in deduped_tags:
                deduped_tags.append(normalized)
        self.tags = deduped_tags

    def as_comparable(self) -> tuple[str, str, str, str, str, tuple[str, ...]]:
        return (
            self.id,
            self.name,
            self.description,
            self.primary_category.id,
            self.primary_category.label,
            tuple(self.tags),
        )


@dataclass(frozen=True)
class SkillManifest:
    metadata: SkillMetadata
    entrypoint: str = "skill.py"
    factory: str = "build_skill"
    readme: str = "README.md"

    @property
    def module_path(self) -> Path:
        return Path(self.entrypoint)

    @property
    def readme_path(self) -> Path:
        return Path(self.readme)


class SkillModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Badge(SkillModel):
    label: str
    tone: Literal["neutral", "low", "medium", "high"] = "neutral"


class MetadataItem(SkillModel):
    label: str
    value: str


class CardLine(SkillModel):
    label: str
    value: str


class LinkItem(SkillModel):
    label: str
    url: str


class FeedbackChoice(SkillModel):
    value: str
    label: str


class FeedbackAction(SkillModel):
    type: Literal["feedback"] = "feedback"
    run_id: str
    item_id: str
    choices: list[FeedbackChoice]
    selected: str | None = None


UiAction: TypeAlias = Annotated[FeedbackAction, Field(discriminator="type")]


class CardItem(SkillModel):
    id: str
    title: str
    badge: Badge | None = None
    metadata: list[MetadataItem] = Field(default_factory=list)
    lines: list[CardLine] = Field(default_factory=list)
    links: list[LinkItem] = Field(default_factory=list)
    actions: list[UiAction] = Field(default_factory=list)


class CardSection(SkillModel):
    id: str
    title: str
    badge: Badge | None = None
    summary: str | None = None
    empty_message: str | None = None
    items: list[CardItem] = Field(default_factory=list)


class MarkdownBlock(SkillModel):
    type: Literal["markdown"] = "markdown"
    content: str


class LineChartPoint(SkillModel):
    time: str
    value: float
    raw: str | None = None


class LineChartBlock(SkillModel):
    type: Literal["line_chart"] = "line_chart"
    title: str
    frequency: str
    points: list[LineChartPoint]


class CardListBlock(SkillModel):
    type: Literal["card_list"] = "card_list"
    title: str | None = None
    sections: list[CardSection] = Field(default_factory=list)


UiBlock: TypeAlias = Annotated[
    MarkdownBlock | LineChartBlock | CardListBlock,
    Field(discriminator="type"),
]

UI_BLOCKS_ADAPTER = TypeAdapter(list[UiBlock])


class FeedbackTarget(SkillModel):
    run_id: str
    item_id: str


class SkillExecutionOptions(SkillModel):
    disable_web_tool: bool = False
    skip_model_response: bool = False


class GeneratedFileArtifact(SkillModel):
    id: str
    name: str
    content_type: str
    path: str
    source_attachment_id: str | None = None


class SkillExecutionResult(SkillModel):
    llm_context: str = ""
    assistant_response: str | None = None
    artifacts: list[UiBlock] = Field(default_factory=list)
    options: SkillExecutionOptions = Field(default_factory=SkillExecutionOptions)
    feedback_targets: list[FeedbackTarget] = Field(default_factory=list)
    generated_files: list[GeneratedFileArtifact] = Field(default_factory=list)


def context_only_result(text: str) -> SkillExecutionResult:
    return SkillExecutionResult(llm_context=text)


class SkillProgressUpdate(SkillModel):
    stage: str
    label: str


@dataclass
class SkillProgressReporter:
    callback: Callable[[SkillProgressUpdate], Awaitable[None]] | None = None
    last_update: SkillProgressUpdate | None = None

    async def update(self, *, stage: str, label: str) -> None:
        normalized_stage = stage.strip()
        normalized_label = label.strip()
        if not normalized_stage:
            raise ValueError("Skill progress stage cannot be empty")
        if not normalized_label:
            raise ValueError("Skill progress label cannot be empty")

        update = SkillProgressUpdate(stage=normalized_stage, label=normalized_label)
        if self.last_update == update:
            return

        self.last_update = update
        if self.callback is None:
            return
        await self.callback(update)


@dataclass(frozen=True)
class SkillRuntimeContext:
    progress: SkillProgressReporter = field(default_factory=SkillProgressReporter)


SKILL_RUNTIME_CONTEXT_KEY = "__skill_runtime__"


def get_skill_progress(skill_context: dict[str, Any] | None) -> SkillProgressReporter:
    runtime = (skill_context or {}).get(SKILL_RUNTIME_CONTEXT_KEY)
    if isinstance(runtime, SkillRuntimeContext):
        return runtime.progress
    return SkillProgressReporter()


class Skill(ABC):
    metadata: SkillMetadata

    @abstractmethod
    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> SkillExecutionResult:
        raise NotImplementedError
