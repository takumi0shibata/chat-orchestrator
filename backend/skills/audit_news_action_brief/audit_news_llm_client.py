import json
from typing import Any

from app.config import get_settings
from app.openai_client import build_openai_client

_WEB_SEARCH_TOOL = {
    "type": "web_search_preview",
    "user_location": {"type": "approximate", "country": "JP"},
}


async def run_json_prompt_with_web(
    *,
    provider_id: str,
    model: str,
    prompt: str,
    max_output_tokens: int = 1200,
) -> str:
    if provider_id != "openai":
        return ""

    settings = get_settings()
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        return ""

    client = build_openai_client(settings=settings, api_key=api_key)
    response = await client.responses.create(
        model=model,
        input=[{"role": "user", "content": prompt}],
        tools=[_WEB_SEARCH_TOOL],
        max_output_tokens=max_output_tokens,
    )
    return getattr(response, "output_text", "") or ""


def extract_json_object(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_json_array(text: str) -> list[Any] | None:
    raw = text.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        pass

    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None
