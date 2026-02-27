from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from app.schemas import ChatMessage


class LLMProvider(ABC):
    provider_id: str

    @abstractmethod
    async def chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
        enable_web_tool: bool | None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
        enable_web_tool: bool | None,
    ) -> AsyncGenerator[str, None]:
        raise NotImplementedError
