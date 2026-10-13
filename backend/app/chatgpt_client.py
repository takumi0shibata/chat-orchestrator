"""Responses adapter for the SIWC preview, separate from API-key transports."""

from app.openai_client import build_openai_client


def workspace_tools(view_image):
    return [dict(
        type="namespace", name="workspace", description="Tools in the local Docker workspace",
        tools=[dict(
            type="function", name="shell", description=(
                "Execute shell commands sequentially inside the local Linux Docker sandbox. "
                "Use /workspace for editable files, /input for attachments, /skills for skills, "
                "and /resources for selected resources. Network access is disabled."
            ), strict=True,
            parameters=dict(
                type="object", additionalProperties=False,
                properties=dict(
                    commands=dict(type="array", items=dict(type="string"), minItems=1, maxItems=20),
                    timeout_ms=dict(type=["integer", "null"]),
                ), required=["commands", "timeout_ms"],
            ),
        ), view_image],
    )]


async def completed_response(stream):
    """Read through the terminal event; partial text is never treated as success."""
    response = None
    try:
        async for event in stream:
            if event.type == "response.completed":
                response = event.response
            elif event.type in ("response.failed", "response.incomplete", "error"):
                raise RuntimeError("ChatGPT request failed or was incomplete. Check plan usage and connection.")
        if response is None:
            raise RuntimeError("ChatGPT stream ended before response.completed.")
        return response
    finally:
        await stream.close()


def response_text(response):
    if getattr(response, "output_text", None):
        return response.output_text
    parts = []
    for item in response.output:
        item = item if isinstance(item, dict) else item.model_dump()
        if item.get("type") == "message":
            parts.extend(part.get("text", "") for part in item.get("content", [])
                         if part.get("type") == "output_text")
    return "".join(parts)


class ChatGPTStream:
    """SIWC may omit output in the terminal response; retain completed items."""
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        items = {}
        async for event in self.stream:
            if event.type == "response.output_item.done":
                items[event.output_index] = event.item
            elif event.type == "response.completed" and not event.response.output:
                event.response.output = [items[index] for index in sorted(items)]
            yield event

    async def close(self):
        await self.stream.close()


class ChatGPTClient:
    def __init__(self, settings, auth):
        self.auth = auth
        self.client = build_openai_client(settings=settings, api_key="not-connected")
        self.client.max_retries = 0  # never automatically replay tool/billing requests
        self.responses = self

    async def create(self, **kwargs):
        self.client.api_key = await self.auth.access_token()
        # Callers use the same application contract; SIWC has a narrower wire contract.
        kwargs.pop("max_output_tokens", None)
        kwargs.pop("prompt_cache_key", None)
        if isinstance(kwargs.get("input"), str):
            kwargs["input"] = [dict(role="user", content=kwargs["input"])]
        kwargs.update(store=False, stream=True)
        return ChatGPTStream(await self.client.responses.create(**kwargs))

    async def compact(self, *, model, input, instructions):
        self.client.api_key = await self.auth.access_token()
        return await self.client.responses.compact(
            model=model, input=input, instructions=instructions,
        )

    async def close(self):
        await self.client.close()
