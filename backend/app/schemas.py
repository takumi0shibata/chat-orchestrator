from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    provider_id: str = Field(description="Provider id, e.g. openai")
    model: str = Field(description="Model name")
    user_input: str
    conversation_id: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    skill_id: str | None = None


class ChatResponse(BaseModel):
    provider_id: str
    model: str
    output: str
    conversation_id: str
    skill_output: str | None = None


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
    default_temperature: float | None
    default_reasoning_effort: str | None


class SkillInfo(BaseModel):
    id: str
    name: str
    description: str


class ConversationInfo(BaseModel):
    id: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str
    message_count: int


class ExtractedAttachment(BaseModel):
    name: str
    content: str


class ExtractAttachmentsResponse(BaseModel):
    files: list[ExtractedAttachment]
