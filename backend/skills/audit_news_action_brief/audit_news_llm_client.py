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
_NON_OUTPUT_ITEM_TYPES = {"web_search_call", "function_call", "file_search_call", "computer_call", "reasoning"}


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


def _extract_response_text(response: Any) -> tuple[str, dict[str, Any]]:
    direct = getattr(response, "output_text", None)
    payload = _to_jsonable(response)
    if not isinstance(payload, dict):
        return (direct if isinstance(direct, str) else ""), {
            "response_status": None,
            "incomplete_reason": None,
            "output_items": 0,
            "output_types": [],
            "content_types": [],
            "included_text_segments": 0,
            "blocked_text_segments": 0,
            "direct_output_text_len": len(direct) if isinstance(direct, str) else 0,
        }

    output_types = _summarize_output_types(payload)
    diag: dict[str, Any] = {
        "response_status": payload.get("status"),
        "incomplete_reason": payload.get("incomplete_details", {}).get("reason")
        if isinstance(payload.get("incomplete_details"), dict) else None,
        "output_items": 0,
        "output_types": output_types,
        "content_types": [],
        "included_text_segments": 0,
        "blocked_text_segments": 0,
        "direct_output_text_len": len(direct) if isinstance(direct, str) else 0,
    }
    if isinstance(direct, str) and direct.strip():
        return direct, diag

    segments: list[str] = []
    content_types_seen: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        diag["output_items"] = len(output)
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            is_item_non_output = isinstance(item_type, str) and item_type in _NON_OUTPUT_ITEM_TYPES
            if not is_item_non_output:
                for key in ("output_text", "text"):
                    text = _coerce_text_value(item.get(key))
                    if isinstance(text, str) and text.strip():
                        segments.append(text)
                        diag["included_text_segments"] = int(diag["included_text_segments"]) + 1
                    elif text:
                        diag["blocked_text_segments"] = int(diag["blocked_text_segments"]) + 1

            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                content_type = content_item.get("type")
                if isinstance(content_type, str) and content_type not in content_types_seen:
                    content_types_seen.append(content_type)
                is_blocked_content = isinstance(content_type, str) and content_type.startswith("input_")
                for key in ("output_text", "text"):
                    text = _coerce_text_value(content_item.get(key))
                    if not isinstance(text, str) or not text.strip():
                        continue
                    if is_item_non_output or is_blocked_content:
                        diag["blocked_text_segments"] = int(diag["blocked_text_segments"]) + 1
                        continue
                    if isinstance(text, str) and text.strip():
                        segments.append(text)
                        diag["included_text_segments"] = int(diag["included_text_segments"]) + 1

    diag["content_types"] = content_types_seen[:12]
    fallback_text = "\n".join(segments).strip()
    return fallback_text, diag


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

    did_empty_retry = False
    current_max_output_tokens = max_output_tokens
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
            result, diagnostics = _extract_response_text(response)
            if not result:
                logger.warning(
                    "run_json_prompt_with_web empty text: provider=%s, model=%s, diagnostics=%s",
                    provider_id, model, json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":")),
                )
                if not did_empty_retry:
                    did_empty_retry = True
                    incomplete_reason = diagnostics.get("incomplete_reason")
                    if incomplete_reason == "max_output_tokens" and current_max_output_tokens < 4000:
                        current_max_output_tokens = min(4000, max(current_max_output_tokens + 1000, current_max_output_tokens * 2))
                        kwargs["max_output_tokens"] = current_max_output_tokens
                        logger.warning(
                            "run_json_prompt_with_web empty text retry: provider=%s, model=%s, reason=%s, max_output_tokens=%d",
                            provider_id, model, incomplete_reason, current_max_output_tokens,
                        )
                    else:
                        logger.warning(
                            "run_json_prompt_with_web empty text retry: provider=%s, model=%s, reason=%s",
                            provider_id, model, incomplete_reason or "unknown",
                        )
                    continue
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

    did_empty_retry = False
    current_max_output_tokens = max_output_tokens
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
            result, diagnostics = _extract_response_text(response)
            if not result:
                logger.warning(
                    "run_json_prompt empty text: provider=%s, model=%s, diagnostics=%s",
                    provider_id, model, json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":")),
                )
                if not did_empty_retry:
                    did_empty_retry = True
                    incomplete_reason = diagnostics.get("incomplete_reason")
                    if incomplete_reason == "max_output_tokens" and current_max_output_tokens < 2000:
                        current_max_output_tokens = min(2000, max(current_max_output_tokens + 400, current_max_output_tokens * 2))
                        kwargs["max_output_tokens"] = current_max_output_tokens
                        logger.warning(
                            "run_json_prompt empty text retry: provider=%s, model=%s, reason=%s, max_output_tokens=%d",
                            provider_id, model, incomplete_reason, current_max_output_tokens,
                        )
                    else:
                        logger.warning(
                            "run_json_prompt empty text retry: provider=%s, model=%s, reason=%s",
                            provider_id, model, incomplete_reason or "unknown",
                        )
                    continue
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
