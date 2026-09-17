from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationCreate(Request):
    workspace_id: str


class RunCreate(Request):
    conversation_id: str
    provider: Literal["openai", "azure_openai"] = "openai"
    model: str = "gpt-5.6-sol"
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
