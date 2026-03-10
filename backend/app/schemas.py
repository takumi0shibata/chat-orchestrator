from typing import Literal

from pydantic import BaseModel, Field

from app.skills_runtime.base import UiBlock

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str
    artifacts: list[UiBlock] = Field(default_factory=list)
    skill_id: str | None = None
    attachments: list["AttachmentSummary"] = Field(default_factory=list)


class ChatRequest(BaseModel):
    provider_id: str = Field(description="Provider id, e.g. openai")
    model: str = Field(description="Model name")
    user_input: str
    attachment_ids: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: ReasoningEffort | None = None
    enable_web_tool: bool | None = None
    skill_id: str | None = None


class ChatResponse(BaseModel):
    provider_id: str
    model: str
    conversation_id: str
    message: ChatMessage
    output: str


class ProviderInfo(BaseModel):
    id: str
    label: str
    enabled: bool
    default_model: str


class ModelInfo(BaseModel):
    id: str
    label: str
    api_mode: str
    supports_temperature: bool
    supports_reasoning_effort: bool
    supports_image_input: bool
    default_temperature: float | None
    default_reasoning_effort: ReasoningEffort | None
    reasoning_effort_options: list[ReasoningEffort] = Field(default_factory=list)


class SkillCategoryInfo(BaseModel):
    id: str
    label: str


class SkillInfo(BaseModel):
    id: str
    name: str
    description: str
    primary_category: SkillCategoryInfo
    tags: list[str]


class ConversationInfo(BaseModel):
    id: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str
    message_count: int


class AttachmentSummary(BaseModel):
    id: str
    name: str
    content_type: str
    size_bytes: int


class StoredAttachment(AttachmentSummary):
    conversation_id: str
    message_id: int | None = None
    original_path: str
    parsed_markdown_path: str
    created_at: str | None = None


class StoredGeneratedFile(BaseModel):
    id: str
    conversation_id: str
    skill_id: str
    source_attachment_id: str | None = None
    name: str
    content_type: str
    path: str
    created_at: str | None = None


class ExtractAttachmentsResponse(BaseModel):
    files: list[AttachmentSummary]


class SkillFeedbackRequest(BaseModel):
    conversation_id: str
    run_id: str
    item_id: str
    decision: str
    note: str | None = None


class SkillFeedbackResponse(BaseModel):
    ok: bool


class AuditNewsFeedbackRequest(BaseModel):
    conversation_id: str
    run_id: str
    alert_id: str
    decision: str
    note: str | None = None


class AuditNewsMetricsResponse(BaseModel):
    total_alerts: int
    total_feedback: int
    acted_count: int
    action_rate: float
