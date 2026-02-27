from collections.abc import AsyncGenerator
import re
from typing import Any

from app.model_catalog import get_model_capability
from app.openai_client import build_openai_client
from app.providers.base import LLMProvider
from app.schemas import ChatMessage
from app.config import Settings


class OpenAIProvider(LLMProvider):
    provider_id = "openai"
    _WEB_SEARCH_TOOL = {
        "type": "web_search_preview",
        "user_location": {"type": "approximate", "country": "JP"},
    }
    _MAX_SOURCE_URLS = 5
    _URL_PATTERN = re.compile(r"https?://[^\s)>\]}\"']+")

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

    def _responses_tools(self, *, api_mode: str, enable_web_tool: bool | None) -> list[dict[str, str]] | None:
        if api_mode != "responses" or enable_web_tool is not True:
            return None
        return [self._WEB_SEARCH_TOOL]

    def _to_jsonable(self, node: Any) -> Any:
        if hasattr(node, "model_dump"):
            return self._to_jsonable(node.model_dump())
        if isinstance(node, dict):
            return {str(key): self._to_jsonable(value) for key, value in node.items()}
        if isinstance(node, (list, tuple)):
            return [self._to_jsonable(item) for item in node]
        return node

    def _extract_source_urls(self, node: Any) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        queue: list[Any] = [self._to_jsonable(node)]

        while queue:
            current = queue.pop(0)
            if isinstance(current, dict):
                for key, value in current.items():
                    if isinstance(value, str):
                        key_name = str(key).lower()
                        if key_name in {"url", "uri", "href", "link"} and value.startswith(("http://", "https://")):
                            if value not in seen:
                                seen.add(value)
                                urls.append(value)
                        for match in self._URL_PATTERN.findall(value):
                            if match not in seen:
                                seen.add(match)
                                urls.append(match)
                    elif isinstance(value, (dict, list, tuple)):
                        queue.append(value)
            elif isinstance(current, (list, tuple)):
                queue.extend(current)
            elif isinstance(current, str):
                for match in self._URL_PATTERN.findall(current):
                    if match not in seen:
                        seen.add(match)
                        urls.append(match)

        return urls[: self._MAX_SOURCE_URLS]

    def _append_sources(self, text: str, urls: list[str]) -> str:
        if not urls:
            return text
        base = text.rstrip()
        sources = "\n".join(f"- {url}" for url in urls)
        if base:
            return f"{base}\n\nSources:\n{sources}"
        return f"Sources:\n{sources}"

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
        tools = self._responses_tools(api_mode=api_mode, enable_web_tool=enable_web_tool)

        if api_mode == "responses":
            if tools:
                kwargs["tools"] = tools
            response = await self.client.responses.create(
                model=model,
                input=self._responses_input(messages),
                **kwargs,
            )
            text = response.output_text or ""
            if tools:
                return self._append_sources(text, self._extract_source_urls(response))
            return text

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
        enable_web_tool: bool | None,
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
        tools = self._responses_tools(api_mode=api_mode, enable_web_tool=enable_web_tool)

        if api_mode == "responses":
            if tools:
                kwargs["tools"] = tools
            stream = await self.client.responses.create(
                model=model,
                input=self._responses_input(messages),
                stream=True,
                **kwargs,
            )
            source_urls: list[str] = []
            seen_sources: set[str] = set()
            async for event in stream:
                if tools:
                    for url in self._extract_source_urls(event):
                        if url not in seen_sources and len(source_urls) < self._MAX_SOURCE_URLS:
                            seen_sources.add(url)
                            source_urls.append(url)
                if getattr(event, "type", "") == "response.output_text.delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        yield delta
            if tools and source_urls:
                yield f"\n\n{self._append_sources('', source_urls)}"
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
