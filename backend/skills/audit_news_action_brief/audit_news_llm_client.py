import json
import asyncio
from time import monotonic
from typing import Any

from app.config import get_settings
from app.openai_client import build_openai_client

_SUPPORTED_PROVIDERS = {"openai", "azure_openai"}

_WEB_SEARCH_TOOL = {
    "type": "web_search_preview",
    "user_location": {"type": "approximate", "country": "JP"},
}
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_TS = 0.0
_MIN_REQUEST_INTERVAL_SEC = 3.0


def _resolve_credentials(provider_id: str) -> tuple[str, str | None]:
    """Return (api_key, base_url) for the given provider."""
    settings = get_settings()
    if provider_id == "azure_openai":
        api_key = (settings.azure_openai_api_key or "").strip()
        base_url: str | None = settings.azure_openai_base_url if api_key else None
        return api_key, base_url
    api_key = (settings.openai_api_key or "").strip()
    return api_key, None


async def run_json_prompt_with_web(
    *,
    provider_id: str,
    model: str,
    prompt: str,
    max_output_tokens: int = 1200,
    reasoning_effort: str | None = "high",
    max_retries: int = 4,
) -> str:
    if provider_id not in _SUPPORTED_PROVIDERS:
        return ""

    api_key, base_url = _resolve_credentials(provider_id)
    if not api_key:
        return ""

    settings = get_settings()
    client = build_openai_client(settings=settings, api_key=api_key, base_url=base_url)
    kwargs: dict[str, Any] = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "tools": [_WEB_SEARCH_TOOL],
        "max_output_tokens": max_output_tokens,
    }
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}

    global _LAST_REQUEST_TS
    for attempt in range(max_retries + 1):
        try:
            async with _REQUEST_LOCK:
                now = monotonic()
                wait_sec = _MIN_REQUEST_INTERVAL_SEC - (now - _LAST_REQUEST_TS)
                if wait_sec > 0:
                    await asyncio.sleep(wait_sec)
                response = await client.responses.create(**kwargs)
                _LAST_REQUEST_TS = monotonic()
            return getattr(response, "output_text", "") or ""
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code == 429 and attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            if isinstance(status_code, int) and status_code >= 500 and attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            return ""
    return ""


async def run_json_prompt(
    *,
    provider_id: str,
    model: str,
    prompt: str,
    max_output_tokens: int = 450,
    reasoning_effort: str | None = "medium",
    max_retries: int = 4,
) -> str:
    """Like run_json_prompt_with_web but without the web_search_preview tool."""
    if provider_id not in _SUPPORTED_PROVIDERS:
        return ""

    api_key, base_url = _resolve_credentials(provider_id)
    if not api_key:
        return ""

    settings = get_settings()
    client = build_openai_client(settings=settings, api_key=api_key, base_url=base_url)
    kwargs: dict[str, Any] = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "max_output_tokens": max_output_tokens,
    }
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}

    global _LAST_REQUEST_TS
    for attempt in range(max_retries + 1):
        try:
            async with _REQUEST_LOCK:
                now = monotonic()
                wait_sec = _MIN_REQUEST_INTERVAL_SEC - (now - _LAST_REQUEST_TS)
                if wait_sec > 0:
                    await asyncio.sleep(wait_sec)
                response = await client.responses.create(**kwargs)
                _LAST_REQUEST_TS = monotonic()
            return getattr(response, "output_text", "") or ""
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code == 429 and attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            if isinstance(status_code, int) and status_code >= 500 and attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            return ""
    return ""


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
