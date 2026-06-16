import asyncio
from types import SimpleNamespace
from typing import Any

from app.abilities_runtime.base import Ability, AbilityExecutionResult, AbilityInvocation, AbilityMetadata
from app.agent_runner import AgentExecutionResult, AgentRunner
from app.config import Settings
from app.schemas import ChatMessage


class FakeAbility(Ability):
    metadata = AbilityMetadata(
        id="context_lookup",
        name="Context Lookup",
        description="Looks up context.",
        primary_category={"id": "general", "label": "General"},
        tags=["general"],
        input_schema={"type": "object", "properties": {"task": {"type": "string"}}, "additionalProperties": True},
    )

    async def run(self, invocation: AbilityInvocation) -> AbilityExecutionResult:
        return AbilityExecutionResult(
            ability_id=self.metadata.id,
            ability_name=self.metadata.name,
            summary=f"looked up {invocation.params.get('task', '')}".strip(),
            llm_context="context result",
        )


class FakeFunctionTool:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class FakeModelSettings:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class FakeOpenAIProvider:
    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.calls.append(kwargs)


class FakeAgent:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class FakeRunConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class FakeRunner:
    @staticmethod
    async def run(agent: FakeAgent, *, input: Any, run_config: FakeRunConfig) -> Any:
        del input, run_config
        await agent.tools[0].on_invoke_tool(None, '{"task":"customer"}')
        return SimpleNamespace(final_output="final answer", trace_id="trace_sync")

    @staticmethod
    def run_streamed(agent: FakeAgent, *, input: Any, run_config: FakeRunConfig) -> Any:
        del input, run_config

        class Streamed:
            final_output = "stream final"
            trace_id = "trace_stream"

            async def stream_events(self):
                await agent.tools[0].on_invoke_tool(None, '{"task":"stream"}')
                yield SimpleNamespace(
                    type="raw_response_event",
                    data=SimpleNamespace(type="response.output_text.delta", delta="stream "),
                )
                yield SimpleNamespace(
                    type="raw_response_event",
                    data=SimpleNamespace(type="response.output_text.delta", delta="answer"),
                )

        return Streamed()


class FakeWebSearchTool:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class FakeItemHelpers:
    @staticmethod
    def text_message_output(_: Any) -> str:
        return ""


def fake_sdk() -> Any:
    return SimpleNamespace(
        Agent=FakeAgent,
        FunctionTool=FakeFunctionTool,
        ItemHelpers=FakeItemHelpers,
        ModelSettings=FakeModelSettings,
        OpenAIProvider=FakeOpenAIProvider,
        RunConfig=FakeRunConfig,
        Runner=FakeRunner,
        WebSearchTool=FakeWebSearchTool,
    )


def test_agent_runner_invokes_ability_tool_and_aggregates_result(monkeypatch) -> None:
    monkeypatch.setattr("app.agent_runner.import_agents_sdk", fake_sdk)
    monkeypatch.setattr("app.agent_runner.build_openai_client", lambda **kwargs: {"client_kwargs": kwargs})
    runner = AgentRunner(settings=Settings(_env_file=None, openai_api_key="test-key"))

    async def run() -> None:
        result = await runner.run(
            provider_id="openai",
            model="gpt-5.4-2026-03-05",
            messages=[ChatMessage(role="user", content="Find context")],
            attachments=[],
            abilities=[FakeAbility()],
            conversation_id="conv-1",
            generated_files_root="/tmp/generated",
            user_text="Find context",
            temperature=None,
            max_tokens=100,
            reasoning_effort="high",
            enable_web_tool=False,
        )
        assert result.content == "final answer"
        assert result.skill_result.llm_context == "[Ability:context_lookup]\ncontext result"
        assert result.ability_results[0].summary == "looked up customer"

    asyncio.run(run())


def test_agent_runner_streams_agent_and_ability_events(monkeypatch) -> None:
    monkeypatch.setattr("app.agent_runner.import_agents_sdk", fake_sdk)
    monkeypatch.setattr("app.agent_runner.build_openai_client", lambda **kwargs: {"client_kwargs": kwargs})
    runner = AgentRunner(settings=Settings(_env_file=None, openai_api_key="test-key"))

    async def run() -> None:
        events: list[dict[str, Any]] = []
        final: AgentExecutionResult | None = None
        async for item in runner.stream(
            provider_id="openai",
            model="gpt-5.4-2026-03-05",
            messages=[ChatMessage(role="user", content="Find context")],
            attachments=[],
            abilities=[FakeAbility()],
            conversation_id="conv-1",
            generated_files_root="/tmp/generated",
            user_text="Find context",
            temperature=None,
            max_tokens=None,
            reasoning_effort=None,
            enable_web_tool=True,
        ):
            if isinstance(item, AgentExecutionResult):
                final = item
            else:
                events.append(item.to_payload())

        assert [event["type"] for event in events] == [
            "ability_started",
            "ability_completed",
            "chunk",
            "chunk",
            "trace_ref",
            "agent_status",
        ]
        assert final is not None
        assert final.content == "stream final"
        assert final.trace_id == "trace_stream"

    asyncio.run(run())


def test_agent_runner_passes_azure_base_url_to_agents_provider(monkeypatch) -> None:
    monkeypatch.setattr("app.agent_runner.import_agents_sdk", fake_sdk)
    captured_client_kwargs: dict[str, Any] = {}

    def fake_client(**kwargs: Any) -> object:
        captured_client_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr("app.agent_runner.build_openai_client", fake_client)
    FakeOpenAIProvider.calls.clear()
    runner = AgentRunner(
        settings=Settings(
            _env_file=None,
            azure_openai_api_key="azure-key",
            azure_openai_endpoint="https://example.openai.azure.com",
        )
    )

    async def run() -> None:
        await runner.run(
            provider_id="azure_openai",
            model="gpt-5.4-2026-03-05",
            messages=[ChatMessage(role="user", content="Hello")],
            attachments=[],
            abilities=[FakeAbility()],
            conversation_id="conv-1",
            generated_files_root="/tmp/generated",
            user_text="Hello",
            temperature=None,
            max_tokens=None,
            reasoning_effort=None,
            enable_web_tool=False,
        )

    asyncio.run(run())

    assert captured_client_kwargs["api_key"] == "azure-key"
    assert captured_client_kwargs["base_url"] == "https://example.openai.azure.com/openai/v1/"
    assert FakeOpenAIProvider.calls[0]["use_responses"] is True
