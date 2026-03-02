import json
import asyncio
import logging
from time import monotonic
from typing import Any

from app.config import get_settings
from app.openai_client import build_openai_client

logger = logging.getLogger("audit_news")

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


def _to_jsonable(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        try:
            return _to_jsonable(node.model_dump())
        except Exception:
            return node
    if isinstance(node, dict):
        return {str(key): _to_jsonable(value) for key, value in node.items()}
    if isinstance(node, (list, tuple)):
        return [_to_jsonable(item) for item in node]
    return node


def _coerce_text_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("value", "text", "output_text"):
            nested = value.get(key)
            if isinstance(nested, str):
                return nested
    return None


def _summarize_output_types(payload: dict[str, Any]) -> list[str]:
    output = payload.get("output")
    if not isinstance(output, list):
        return []
    out: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        output_type = item.get("type")
        if isinstance(output_type, str) and output_type not in out:
            out.append(output_type)
    return out[:8]


def _extract_response_text(response: Any) -> tuple[str, list[str]]:
    direct = getattr(response, "output_text", None)
    payload = _to_jsonable(response)
    if not isinstance(payload, dict):
        return (direct if isinstance(direct, str) else ""), []

    output_types = _summarize_output_types(payload)
    if isinstance(direct, str) and direct.strip():
        return direct, output_types

    segments: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type in (None, "message", "output_text", "text"):
                for key in ("output_text", "text"):
                    text = _coerce_text_value(item.get(key))
                    if isinstance(text, str) and text.strip():
                        segments.append(text)

            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                content_type = content_item.get("type")
                if content_type not in (None, "output_text", "text"):
                    continue
                for key in ("output_text", "text"):
                    text = _coerce_text_value(content_item.get(key))
                    if isinstance(text, str) and text.strip():
                        segments.append(text)

    fallback_text = "\n".join(segments).strip()
    return fallback_text, output_types


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
            result, output_types = _extract_response_text(response)
            if not result:
                logger.warning(
                    "run_json_prompt_with_web empty text: provider=%s, model=%s, output_types=%s",
                    provider_id, model, ",".join(output_types) if output_types else "none",
                )
            logger.info("run_json_prompt_with_web OK: provider=%s, model=%s, response_len=%d", provider_id, model, len(result))
            return result
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            logger.warning(
                "run_json_prompt_with_web error: model=%s, attempt=%d/%d, status=%s, error=%s",
                model, attempt + 1, max_retries + 1, status_code, exc,
            )
            if status_code == 429 and attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            if isinstance(status_code, int) and status_code >= 500 and attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            logger.error("run_json_prompt_with_web giving up: model=%s, final_status=%s", model, status_code)
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
            result, output_types = _extract_response_text(response)
            if not result:
                logger.warning(
                    "run_json_prompt empty text: provider=%s, model=%s, output_types=%s",
                    provider_id, model, ",".join(output_types) if output_types else "none",
                )
            logger.info("run_json_prompt OK: provider=%s, model=%s, response_len=%d", provider_id, model, len(result))
            return result
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            logger.warning(
                "run_json_prompt error: model=%s, attempt=%d/%d, status=%s, error=%s",
                model, attempt + 1, max_retries + 1, status_code, exc,
            )
            if status_code == 429 and attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            if isinstance(status_code, int) and status_code >= 500 and attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            logger.error("run_json_prompt giving up: model=%s, final_status=%s", model, status_code)
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
