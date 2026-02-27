import asyncio
from types import SimpleNamespace
from typing import Any

from app.config import Settings
from app.providers.openai_provider import OpenAIProvider
from app.schemas import ChatMessage, ChatRequest

EXPECTED_WEB_TOOL = {
    "type": "web_search_preview",
    "user_location": {"type": "approximate", "country": "JP"},
}


class FakeResponse:
    def __init__(self, output_text: str, payload: dict[str, Any]) -> None:
        self.output_text = output_text
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return self._payload


class FakeEvent:
    def __init__(self, event_type: str, delta: str | None = None, payload: dict[str, Any] | None = None) -> None:
        self.type = event_type
        self.delta = delta
        self._payload = payload or {}

    def model_dump(self) -> dict[str, Any]:
        return self._payload


class FakeAsyncIterator:
    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self._index = 0

    def __aiter__(self) -> "FakeAsyncIterator":
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event


class FakeResponsesAPI:
    def __init__(self, response: FakeResponse, stream_events: list[Any] | None = None) -> None:
        self.response = response
        self.stream_events = stream_events or []
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return FakeAsyncIterator(self.stream_events)
        return self.response


class FakeChatCompletionsAPI:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return FakeAsyncIterator([])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def _provider_with_fake_client(monkeypatch, *, responses_api: FakeResponsesAPI, chat_api: FakeChatCompletionsAPI) -> OpenAIProvider:
    fake_client = SimpleNamespace(
        responses=responses_api,
        chat=SimpleNamespace(completions=chat_api),
    )
    monkeypatch.setattr("app.providers.openai_provider.build_openai_client", lambda **_: fake_client)
    return OpenAIProvider(settings=Settings(_env_file=None), api_key="test-key", provider_id="openai")


def test_chat_request_accepts_optional_enable_web_tool() -> None:
    payload = ChatRequest(provider_id="openai", model="gpt-5.2-2025-12-11", user_input="hello")
    assert payload.enable_web_tool is None


def test_openai_responses_with_web_tool_adds_tools_and_sources(monkeypatch) -> None:
    response = FakeResponse(
        output_text="Answer",
        payload={
            "output": [
                {
                    "content": [
                        {"annotations": [{"url": "https://example.com/a"}, {"url": "https://example.com/b"}]}
                    ]
                }
            ]
        },
    )
    responses_api = FakeResponsesAPI(response=response)
    chat_api = FakeChatCompletionsAPI(content="unused")
    provider = _provider_with_fake_client(monkeypatch, responses_api=responses_api, chat_api=chat_api)

    async def run() -> None:
        output = await provider.chat(
            model="gpt-5.2-2025-12-11",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=None,
            max_tokens=None,
            reasoning_effort=None,
            enable_web_tool=True,
        )
        assert "Sources:" in output
        assert "https://example.com/a" in output
        assert responses_api.calls[0]["tools"] == [EXPECTED_WEB_TOOL]

    asyncio.run(run())


def test_openai_responses_without_web_tool_does_not_send_tools(monkeypatch) -> None:
    response = FakeResponse(output_text="Answer", payload={})
    responses_api = FakeResponsesAPI(response=response)
    chat_api = FakeChatCompletionsAPI(content="unused")
    provider = _provider_with_fake_client(monkeypatch, responses_api=responses_api, chat_api=chat_api)

    async def run() -> None:
        output = await provider.chat(
            model="gpt-5.2-2025-12-11",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=None,
            max_tokens=None,
            reasoning_effort=None,
            enable_web_tool=False,
        )
        assert output == "Answer"
        assert "tools" not in responses_api.calls[0]

    asyncio.run(run())


def test_openai_chat_completions_ignores_web_tool(monkeypatch) -> None:
    response = FakeResponse(output_text="unused", payload={})
    responses_api = FakeResponsesAPI(response=response)
    chat_api = FakeChatCompletionsAPI(content="chat output")
    provider = _provider_with_fake_client(monkeypatch, responses_api=responses_api, chat_api=chat_api)

    async def run() -> None:
        output = await provider.chat(
            model="gpt-4o-mini",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.3,
            max_tokens=None,
            reasoning_effort=None,
            enable_web_tool=True,
        )
        assert output == "chat output"
        assert len(responses_api.calls) == 0

    asyncio.run(run())


def test_openai_responses_stream_appends_sources(monkeypatch) -> None:
    response = FakeResponse(output_text="unused", payload={})
    events = [
        FakeEvent("response.output_text.delta", delta="Hello"),
        FakeEvent(
            "response.completed",
            payload={"response": {"output": [{"content": [{"url": "https://example.com/stream"}]}]}},
        ),
    ]
    responses_api = FakeResponsesAPI(response=response, stream_events=events)
    chat_api = FakeChatCompletionsAPI(content="unused")
    provider = _provider_with_fake_client(monkeypatch, responses_api=responses_api, chat_api=chat_api)

    async def run() -> None:
        chunks: list[str] = []
        async for chunk in provider.stream_chat(
            model="gpt-5.2-2025-12-11",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=None,
            max_tokens=None,
            reasoning_effort=None,
            enable_web_tool=True,
        ):
            chunks.append(chunk)
        assert chunks[0] == "Hello"
        assert any("Sources:" in chunk for chunk in chunks[1:])
        assert responses_api.calls[0]["tools"] == [EXPECTED_WEB_TOOL]

    asyncio.run(run())
