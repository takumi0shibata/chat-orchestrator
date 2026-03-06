from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


@dataclass
class SkillMetadata:
    id: str
    name: str
    description: str


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


class SkillExecutionResult(SkillModel):
    llm_context: str = ""
    artifacts: list[UiBlock] = Field(default_factory=list)
    options: SkillExecutionOptions = Field(default_factory=SkillExecutionOptions)
    feedback_targets: list[FeedbackTarget] = Field(default_factory=list)


def context_only_result(text: str) -> SkillExecutionResult:
    return SkillExecutionResult(llm_context=text)


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
