from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

from app.abilities_runtime.base import (
    Ability,
    AbilityAttachment,
    AbilityExecutionResult,
    AbilityInvocation,
    AbilityRuntimeContext,
)
from app.config import Settings
from app.model_catalog import get_model_capability
from app.openai_client import build_openai_client
from app.schemas import ChatMessage, StoredAttachment
from app.skills_runtime.base import (
    SkillExecutionOptions,
    SkillExecutionResult,
    SkillProgressReporter,
    SkillProgressUpdate,
)


AGENTIC_PROVIDER_IDS = {"openai", "azure_openai"}
_TOOL_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")
_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@dataclass(frozen=True)
class AgentStreamEvent:
    type: str
    payload: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {"type": self.type, **self.payload}


@dataclass
class AgentExecutionResult:
    content: str
    skill_result: SkillExecutionResult
    trace_id: str | None = None
    ability_results: list[AbilityExecutionResult] = field(default_factory=list)


@dataclass
class _AgentRunAccumulator:
    content_parts: list[str] = field(default_factory=list)
    ability_results: list[AbilityExecutionResult] = field(default_factory=list)
    trace_id: str | None = None

    @property
    def content(self) -> str:
        return "".join(self.content_parts)

    def to_execution_result(self, *, final_output: str | None = None) -> AgentExecutionResult:
        content = final_output if final_output is not None and final_output.strip() else self.content
        return AgentExecutionResult(
            content=content,
            trace_id=self.trace_id,
            ability_results=list(self.ability_results),
            skill_result=self._aggregate_skill_result(),
        )

    def _aggregate_skill_result(self) -> SkillExecutionResult:
        llm_context_sections: list[str] = []
        artifacts = []
        feedback_targets = []
        generated_files = []
        disable_web_tool = False
        skip_model_response = False

        for result in self.ability_results:
            if result.llm_context.strip():
                llm_context_sections.append(f"[Ability:{result.ability_id}]\n{result.llm_context.strip()}")
            artifacts.extend(result.artifacts)
            feedback_targets.extend(result.feedback_targets)
            generated_files.extend(result.generated_files)
            disable_web_tool = disable_web_tool or result.options.disable_web_tool
            skip_model_response = skip_model_response or result.options.skip_model_response

        return SkillExecutionResult(
            llm_context="\n\n".join(llm_context_sections),
            artifacts=artifacts,
            options=SkillExecutionOptions(
                disable_web_tool=disable_web_tool,
                skip_model_response=skip_model_response,
            ),
            feedback_targets=feedback_targets,
            generated_files=generated_files,
        )


class AgentRunner:
    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings

    def can_run(self, *, provider_id: str, model: str) -> bool:
        if provider_id not in AGENTIC_PROVIDER_IDS:
            return False
        return get_model_capability(provider_id, model).api_mode == "responses"

    async def run(
        self,
        *,
        provider_id: str,
        model: str,
        messages: list[ChatMessage],
        attachments: list[StoredAttachment],
        abilities: list[Ability],
        conversation_id: str,
        generated_files_root: str,
        user_text: str,
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
        enable_web_tool: bool | None,
    ) -> AgentExecutionResult:
        self._ensure_agentic_supported(provider_id=provider_id, model=model)
        sdk = import_agents_sdk()
        accumulator = _AgentRunAccumulator()
        agent, run_config = self._build_agent(
            sdk=sdk,
            provider_id=provider_id,
            model=model,
            abilities=abilities,
            attachments=attachments,
            messages=messages,
            conversation_id=conversation_id,
            generated_files_root=generated_files_root,
            user_text=user_text,
            accumulator=accumulator,
            event_callback=None,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            enable_web_tool=enable_web_tool,
        )
        result = await sdk.Runner.run(
            agent,
            input=self._agent_input(messages=messages, attachments=attachments),
            run_config=run_config,
        )
        return accumulator.to_execution_result(final_output=_final_output(result))

    async def stream(
        self,
        *,
        provider_id: str,
        model: str,
        messages: list[ChatMessage],
        attachments: list[StoredAttachment],
        abilities: list[Ability],
        conversation_id: str,
        generated_files_root: str,
        user_text: str,
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
        enable_web_tool: bool | None,
    ) -> AsyncGenerator[AgentStreamEvent | AgentExecutionResult, None]:
        self._ensure_agentic_supported(provider_id=provider_id, model=model)
        sdk = import_agents_sdk()
        queue: asyncio.Queue[AgentStreamEvent | None] = asyncio.Queue()
        accumulator = _AgentRunAccumulator()

        async def emit(event: AgentStreamEvent) -> None:
            await queue.put(event)

        agent, run_config = self._build_agent(
            sdk=sdk,
            provider_id=provider_id,
            model=model,
            abilities=abilities,
            attachments=attachments,
            messages=messages,
            conversation_id=conversation_id,
            generated_files_root=generated_files_root,
            user_text=user_text,
            accumulator=accumulator,
            event_callback=emit,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            enable_web_tool=enable_web_tool,
        )

        streamed_result = sdk.Runner.run_streamed(
            agent,
            input=self._agent_input(messages=messages, attachments=attachments),
            run_config=run_config,
        )

        async def pump_sdk_events() -> None:
            try:
                async for event in streamed_result.stream_events():
                    await self._handle_sdk_stream_event(
                        event=event,
                        sdk=sdk,
                        queue=queue,
                        accumulator=accumulator,
                    )
                final_trace_id = _trace_id(streamed_result)
                if final_trace_id:
                    accumulator.trace_id = final_trace_id
                    await queue.put(
                        AgentStreamEvent(
                            type="trace_ref",
                            payload={"trace_id": final_trace_id},
                        )
                    )
                await queue.put(
                    AgentStreamEvent(
                        type="agent_status",
                        payload={"status": "done", "stage": "completed", "label": "完了しました"},
                    )
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(pump_sdk_events())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        yield accumulator.to_execution_result(final_output=_final_output(streamed_result))

    def _ensure_agentic_supported(self, *, provider_id: str, model: str) -> None:
        if not self.can_run(provider_id=provider_id, model=model):
            raise ValueError("Agentic execution is supported only for OpenAI/Azure OpenAI Responses models.")

    def _build_agent(
        self,
        *,
        sdk: Any,
        provider_id: str,
        model: str,
        abilities: list[Ability],
        attachments: list[StoredAttachment],
        messages: list[ChatMessage],
        conversation_id: str,
        generated_files_root: str,
        user_text: str,
        accumulator: _AgentRunAccumulator,
        event_callback: Callable[[AgentStreamEvent], Awaitable[None]] | None,
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
        enable_web_tool: bool | None,
    ) -> tuple[Any, Any]:
        tools = [
            self._build_ability_tool(
                sdk=sdk,
                ability=ability,
                provider_id=provider_id,
                model=model,
                attachments=attachments,
                messages=messages,
                conversation_id=conversation_id,
                generated_files_root=generated_files_root,
                user_text=user_text,
                accumulator=accumulator,
                event_callback=event_callback,
            )
            for ability in abilities
        ]

        if enable_web_tool:
            tools.append(_build_web_search_tool(sdk))

        agent = sdk.Agent(
            name="Chat Orchestrator Agent",
            instructions=self._instructions(abilities=abilities, web_enabled=bool(enable_web_tool)),
            model=model,
            model_settings=self._model_settings(
                sdk=sdk,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            ),
            tools=tools,
        )
        run_config = sdk.RunConfig(model_provider=self._model_provider(sdk=sdk, provider_id=provider_id))
        return agent, run_config

    def _build_ability_tool(
        self,
        *,
        sdk: Any,
        ability: Ability,
        provider_id: str,
        model: str,
        attachments: list[StoredAttachment],
        messages: list[ChatMessage],
        conversation_id: str,
        generated_files_root: str,
        user_text: str,
        accumulator: _AgentRunAccumulator,
        event_callback: Callable[[AgentStreamEvent], Awaitable[None]] | None,
    ) -> Any:
        tool_name = _tool_name(ability.metadata.id)

        async def on_invoke_tool(_: Any, args: str) -> str:
            params = _parse_tool_args(args)
            await _emit(
                event_callback,
                AgentStreamEvent(
                    type="ability_started",
                    payload={
                        "ability_id": ability.metadata.id,
                        "ability_name": ability.metadata.name,
                        "input_summary": _summarize_params(params),
                    },
                ),
            )

            async def on_progress(update: SkillProgressUpdate) -> None:
                await _emit(
                    event_callback,
                    AgentStreamEvent(
                        type="agent_status",
                        payload={
                            "status": "running",
                            "stage": update.stage,
                            "label": update.label,
                            "ability_id": ability.metadata.id,
                        },
                    ),
                )

            result = await ability.run(
                AbilityInvocation(
                    user_text=user_text,
                    history=[{"role": item.role, "content": item.content} for item in messages],
                    attachments=[_ability_attachment(item) for item in attachments],
                    runtime=AbilityRuntimeContext(
                        provider_id=provider_id,
                        model=model,
                        conversation_id=conversation_id,
                        generated_files_root=generated_files_root,
                    ),
                    params=params,
                    progress=SkillProgressReporter(callback=on_progress),
                )
            )
            accumulator.ability_results.append(result)
            await _emit(
                event_callback,
                AgentStreamEvent(
                    type="ability_completed",
                    payload={
                        "ability_id": result.ability_id,
                        "ability_name": result.ability_name,
                        "result_summary": result.summary,
                    },
                ),
            )
            for artifact in result.artifacts:
                await _emit(
                    event_callback,
                    AgentStreamEvent(
                        type="artifact",
                        payload={
                            "ability_id": result.ability_id,
                            "ability_name": result.ability_name,
                            "artifact": artifact.model_dump(mode="json"),
                        },
                    ),
                )
            return _tool_output(result)

        return sdk.FunctionTool(
            name=tool_name,
            description=ability.metadata.description,
            params_json_schema=ability.metadata.input_schema,
            on_invoke_tool=on_invoke_tool,
            strict_json_schema=False,
        )

    def _model_provider(self, *, sdk: Any, provider_id: str) -> Any:
        api_key, base_url = self._resolve_openai_credentials(provider_id)
        client = build_openai_client(settings=self.settings, api_key=api_key, base_url=base_url)
        return sdk.OpenAIProvider(openai_client=client, use_responses=True)

    def _resolve_openai_credentials(self, provider_id: str) -> tuple[str, str | None]:
        if provider_id == "azure_openai":
            api_key = (self.settings.azure_openai_api_key or "").strip()
            if not api_key or not self.settings.azure_openai_enabled:
                raise ValueError("Azure OpenAI is not configured.")
            return api_key, self.settings.azure_openai_base_url
        api_key = (self.settings.openai_api_key or "").strip()
        if not api_key:
            raise ValueError("OpenAI is not configured.")
        return api_key, None

    def _model_settings(
        self,
        *,
        sdk: Any,
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
    ) -> Any:
        kwargs: dict[str, Any] = {"truncation": "auto"}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if reasoning_effort and reasoning_effort != "none":
            reasoning = _build_reasoning(reasoning_effort)
            kwargs["reasoning"] = reasoning if reasoning is not None else {"effort": reasoning_effort}
        return sdk.ModelSettings(**kwargs)

    def _agent_input(self, *, messages: list[ChatMessage], attachments: list[StoredAttachment]) -> list[dict[str, Any]]:
        image_attachments = [item for item in attachments if item.content_type.lower() in _IMAGE_CONTENT_TYPES]
        if not image_attachments:
            return [{"role": item.role, "content": item.content} for item in messages]

        last_user_index = next((index for index in range(len(messages) - 1, -1, -1) if messages[index].role == "user"), -1)
        payload: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            if index != last_user_index:
                payload.append({"role": message.role, "content": message.content})
                continue
            content: list[dict[str, str]] = []
            if message.content:
                content.append({"type": "input_text", "text": message.content})
            for attachment in image_attachments:
                content.append(
                    {
                        "type": "input_image",
                        "image_url": _attachment_data_url(attachment),
                        "detail": "auto",
                    }
                )
            payload.append({"role": message.role, "content": content})
        return payload

    def _instructions(self, *, abilities: list[Ability], web_enabled: bool) -> str:
        ability_lines = "\n".join(
            f"- `{_tool_name(ability.metadata.id)}`: {ability.metadata.description}" for ability in abilities
        )
        web_line = "- Hosted web search is available when fresh public information is needed." if web_enabled else ""
        return (
            "You are an agentic chat orchestrator. Answer the user directly, but use abilities when they can "
            "produce concrete context, artifacts, files, or domain-specific results. Do not expose hidden reasoning. "
            "When using an ability, rely on its tool output and explain the result in the final answer.\n\n"
            "Available abilities:\n"
            f"{ability_lines or '- No local abilities are available.'}\n"
            f"{web_line}"
        ).strip()

    async def _handle_sdk_stream_event(
        self,
        *,
        event: Any,
        sdk: Any,
        queue: asyncio.Queue[AgentStreamEvent | None],
        accumulator: _AgentRunAccumulator,
    ) -> None:
        event_type = getattr(event, "type", "")
        if event_type == "raw_response_event":
            data = getattr(event, "data", None)
            if getattr(data, "type", "") == "response.output_text.delta":
                delta = getattr(data, "delta", None)
                if delta:
                    accumulator.content_parts.append(delta)
                    await queue.put(AgentStreamEvent(type="chunk", payload={"delta": delta}))
            return

        if event_type == "agent_updated_stream_event":
            return

        if event_type != "run_item_stream_event":
            return

        name = getattr(event, "name", "")
        if name == "message_output_created" and not accumulator.content_parts:
            text = _message_output_text(sdk=sdk, item=getattr(event, "item", None))
            if text:
                accumulator.content_parts.append(text)
                await queue.put(AgentStreamEvent(type="chunk", payload={"delta": text}))


def import_agents_sdk() -> Any:
    try:
        from agents import (  # type: ignore[import-not-found]
            Agent,
            FunctionTool,
            ItemHelpers,
            ModelSettings,
            OpenAIProvider,
            RunConfig,
            Runner,
            WebSearchTool,
        )
    except ImportError as exc:
        raise RuntimeError("openai-agents is required for execution_mode='agentic'. Run `uv sync`.") from exc
    return SimpleNamespace(
        Agent=Agent,
        FunctionTool=FunctionTool,
        ItemHelpers=ItemHelpers,
        ModelSettings=ModelSettings,
        OpenAIProvider=OpenAIProvider,
        RunConfig=RunConfig,
        Runner=Runner,
        WebSearchTool=WebSearchTool,
    )


def _build_reasoning(effort: str) -> Any | None:
    try:
        from openai.types.shared import Reasoning
    except ImportError:
        return None
    return Reasoning(effort=effort)


def _build_web_search_tool(sdk: Any) -> Any:
    try:
        return sdk.WebSearchTool(user_location={"type": "approximate", "country": "JP"})
    except TypeError:
        return sdk.WebSearchTool()


async def _emit(
    callback: Callable[[AgentStreamEvent], Awaitable[None]] | None,
    event: AgentStreamEvent,
) -> None:
    if callback is not None:
        await callback(event)


def _ability_attachment(attachment: StoredAttachment) -> AbilityAttachment:
    return AbilityAttachment(
        id=attachment.id,
        name=attachment.name,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        original_path=attachment.original_path,
        parsed_markdown_path=attachment.parsed_markdown_path,
    )


def _tool_name(ability_id: str) -> str:
    normalized = _TOOL_NAME_RE.sub("_", ability_id.strip()).strip("_")
    if not normalized:
        normalized = "ability"
    if normalized[0].isdigit():
        normalized = f"ability_{normalized}"
    return normalized


def _parse_tool_args(args: str) -> dict[str, Any]:
    if not args.strip():
        return {}
    try:
        parsed = json.loads(args)
    except json.JSONDecodeError:
        return {"task": args}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _summarize_params(params: dict[str, Any]) -> str:
    if not params:
        return ""
    raw = json.dumps(params, ensure_ascii=False, sort_keys=True)
    return raw[:240]


def _tool_output(result: AbilityExecutionResult) -> str:
    payload = {
        "ability_id": result.ability_id,
        "summary": result.summary,
        "llm_context": result.llm_context,
        "assistant_response": result.assistant_response,
        "artifacts": [item.model_dump(mode="json") for item in result.artifacts],
        "generated_files": [item.model_dump(mode="json") for item in result.generated_files],
    }
    return json.dumps(payload, ensure_ascii=False)


def _final_output(result: Any) -> str | None:
    value = getattr(result, "final_output", None)
    return value if isinstance(value, str) else None


def _trace_id(result: Any) -> str | None:
    for name in ("trace_id", "last_trace_id"):
        value = getattr(result, name, None)
        if isinstance(value, str) and value:
            return value
    trace = getattr(result, "trace", None)
    value = getattr(trace, "trace_id", None)
    return value if isinstance(value, str) and value else None


def _message_output_text(*, sdk: Any, item: Any) -> str:
    helper = getattr(sdk, "ItemHelpers", None)
    if helper is None or item is None:
        return ""
    try:
        value = helper.text_message_output(item)
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _attachment_data_url(attachment: StoredAttachment) -> str:
    raw = Path(attachment.original_path).read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{attachment.content_type};base64,{encoded}"
