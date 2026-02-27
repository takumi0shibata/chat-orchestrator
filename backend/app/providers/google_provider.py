from collections.abc import AsyncGenerator

from google import genai
from google.genai import types

from app.providers.base import LLMProvider
from app.schemas import ChatMessage


class GoogleProvider(LLMProvider):
    provider_id = "google"

    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)

    def _build_request(self, messages: list[ChatMessage]) -> tuple[str | None, list[types.Content]]:
        contents: list[types.Content] = []
        system_prompt = None
        for message in messages:
            if message.role == "system":
                system_prompt = f"{system_prompt}\n{message.content}" if system_prompt else message.content
                continue

            role = "user" if message.role == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=message.content)]))
        return system_prompt, contents

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
        del reasoning_effort, enable_web_tool
        system_prompt, contents = self._build_request(messages)
        config = types.GenerateContentConfig(
            temperature=temperature if temperature is not None else 0.3,
            max_output_tokens=max_tokens,
            system_instruction=system_prompt,
        )
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        return response.text or ""

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
        del reasoning_effort, enable_web_tool
        text = await self.chat(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=None,
            enable_web_tool=None,
        )
        if text:
            yield text
