from collections.abc import AsyncGenerator
from typing import Any

from app.model_catalog import get_model_capability
from app.openai_client import build_openai_client
from app.providers.base import LLMProvider
from app.schemas import ChatMessage
from app.config import Settings


class OpenAIProvider(LLMProvider):
    provider_id = "openai"

    def __init__(
        self,
        settings: Settings,
        api_key: str,
        base_url: str | None = None,
        provider_id: str = "openai",
        default_api_mode: str | None = None,
    ) -> None:
        self.client = build_openai_client(settings=settings, api_key=api_key, base_url=base_url)
        self.provider_id = provider_id
        self.default_api_mode = default_api_mode

    def _chat_messages(self, messages: list[ChatMessage]) -> list[dict[str, str]]:
        return [m.model_dump() for m in messages]

    def _responses_input(self, messages: list[ChatMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    def _build_optional_kwargs(
        self,
        *,
        capability_api_mode: str,
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}

        if capability_api_mode == "responses":
            if max_tokens is not None:
                kwargs["max_output_tokens"] = max_tokens
            if reasoning_effort:
                kwargs["reasoning"] = {"effort": reasoning_effort}
        else:
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens

        return kwargs

    async def chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
    ) -> str:
        capability = get_model_capability(self.provider_id, model)
        api_mode = self.default_api_mode or capability.api_mode
        supports_temperature = capability.supports_temperature and api_mode != "responses"
        supports_reasoning_effort = capability.supports_reasoning_effort and api_mode == "responses"
        kwargs = self._build_optional_kwargs(
            capability_api_mode=api_mode,
            temperature=temperature if supports_temperature else None,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort if supports_reasoning_effort else None,
        )

        if api_mode == "responses":
            response = await self.client.responses.create(
                model=model,
                input=self._responses_input(messages),
                **kwargs,
            )
            return response.output_text or ""

        response = await self.client.chat.completions.create(
            model=model,
            messages=self._chat_messages(messages),
            **kwargs,
        )
        return response.choices[0].message.content or ""

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
    ) -> AsyncGenerator[str, None]:
        capability = get_model_capability(self.provider_id, model)
        api_mode = self.default_api_mode or capability.api_mode
        supports_temperature = capability.supports_temperature and api_mode != "responses"
        supports_reasoning_effort = capability.supports_reasoning_effort and api_mode == "responses"
        kwargs = self._build_optional_kwargs(
            capability_api_mode=api_mode,
            temperature=temperature if supports_temperature else None,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort if supports_reasoning_effort else None,
        )

        if api_mode == "responses":
            stream = await self.client.responses.create(
                model=model,
                input=self._responses_input(messages),
                stream=True,
                **kwargs,
            )
            async for event in stream:
                if getattr(event, "type", "") == "response.output_text.delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        yield delta
            return

        stream = await self.client.chat.completions.create(
            model=model,
            messages=self._chat_messages(messages),
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
