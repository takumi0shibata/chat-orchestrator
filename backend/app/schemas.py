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
    default_provider: Literal["openai", "azure_openai"] | None = None
    default_model: str | None = None
    default_effort: str | None = None
    default_web_search: bool | None = None
    # 0 clears the budget.
    monthly_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    # Forget the saved new-chat model and fall back to the built-in default.
    reset_default_model: bool = False

    def title_selection(self):
        if (self.title_provider is None) != (self.title_model is None):
            raise ValueError("Title provider and model must be updated together")
        return self.title_provider, self.title_model

    def default_selection(self):
        values = (self.default_provider, self.default_model, self.default_effort)
        if any(v is not None for v in values) and any(v is None for v in values):
            raise ValueError("Default provider, model and effort must be updated together")
        return values


class CheckpointPrune(Request):
    older_than_days: int = Field(ge=0, le=3650)


class RunCreate(Request):
    conversation_id: str
    provider: Literal["openai", "azure_openai"] = "openai"
    model: str = "gpt-6.1-sol"
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


class Revert(Request):
    force: bool = False
