from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationCreate(Request):
    workspace_id: str


class ConversationUpdate(Request):
    pinned: bool


class AppSettingsUpdate(Request):
    title_provider: Literal["openai", "azure_openai"] | None = None
    title_model: str | None = None
    theme_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    def title_selection(self):
        if (self.title_provider is None) != (self.title_model is None):
            raise ValueError("Title provider and model must be updated together")
        return self.title_provider, self.title_model


class RunCreate(Request):
    conversation_id: str
    provider: Literal["openai", "azure_openai"] = "openai"
    model: str = "gpt-6-sol"
    reasoning_effort: str = "medium"
    input: str = Field(default="", max_length=1000000)
    attachment_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    mcp_ids: list[str] = Field(default_factory=list)
    web_search: bool = False
    direct_attachment_ids: list[str] = Field(default_factory=list)


class Approval(Request):
    request_id: str
    approve: bool
