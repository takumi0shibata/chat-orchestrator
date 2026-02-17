from collections.abc import AsyncGenerator

from anthropic import AsyncAnthropic

from app.providers.base import LLMProvider
from app.schemas import ChatMessage


class AnthropicProvider(LLMProvider):
    provider_id = "anthropic"

    def __init__(self, api_key: str) -> None:
        self.client = AsyncAnthropic(api_key=api_key)

    def _split_messages(self, messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, str]]]:
        system_prompts = [m.content for m in messages if m.role == "system"]
        chat_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in {"user", "assistant"}
        ]
        return ("\n".join(system_prompts) if system_prompts else None, chat_messages)

    async def chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
    ) -> str:
        del reasoning_effort
        system_prompt, chat_messages = self._split_messages(messages)
        response = await self.client.messages.create(
            model=model,
            system=system_prompt,
            max_tokens=max_tokens or 1024,
            temperature=temperature if temperature is not None else 0.3,
            messages=chat_messages,
        )
        chunks: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        return "\n".join(chunks)

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
    ) -> AsyncGenerator[str, None]:
        del reasoning_effort
        system_prompt, chat_messages = self._split_messages(messages)
        async with self.client.messages.stream(
            model=model,
            system=system_prompt,
            max_tokens=max_tokens or 1024,
            temperature=temperature if temperature is not None else 0.3,
            messages=chat_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
