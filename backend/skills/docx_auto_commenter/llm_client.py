import asyncio
import json
import logging
from time import monotonic
from typing import Any

from app.config import get_settings
from app.openai_client import build_openai_client

logger = logging.getLogger("docx_auto_commenter")

_SUPPORTED_PROVIDERS = {"openai", "azure_openai"}
_NON_OUTPUT_ITEM_TYPES = {"web_search_call", "function_call", "file_search_call", "computer_call", "reasoning"}
_EMPTY_RETRY_MAX_ATTEMPTS = 2
_EMPTY_RETRY_TOKEN_CAP = 12000
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_TS = 0.0
_MIN_REQUEST_INTERVAL_SEC = 0.0


def _client_kwargs(provider_id: str) -> dict[str, str] | None:
    settings = get_settings()
    if provider_id == "openai":
        api_key = (settings.openai_api_key or "").strip()
        return {"api_key": api_key} if api_key else None
    if provider_id == "azure_openai":
        api_key = (settings.azure_openai_api_key or "").strip()
        base_url = settings.azure_openai_base_url if api_key and settings.azure_openai_enabled else None
        if not api_key or not base_url:
            return None
        return {"api_key": api_key, "base_url": base_url}
    return None


def _to_jsonable(node: Any) -> Any:
    if hasattr(node, "model_dump"):
        return _to_jsonable(node.model_dump())
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


def _coerce_json_value(value: Any) -> str | None:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return None


def _extract_text_and_diagnostics(response: Any) -> tuple[str, dict[str, Any]]:
    direct = getattr(response, "output_text", None)
    parsed_direct = getattr(response, "output_parsed", None)
    if isinstance(parsed_direct, (dict, list)):
        parsed_text = json.dumps(parsed_direct, ensure_ascii=False)
    else:
        parsed_text = None

    if isinstance(direct, str) and direct.strip():
        return direct, {
            "response_status": None,
            "incomplete_reason": None,
            "output_items": 0,
            "output_types": [],
            "content_types": [],
            "included_text_segments": 1,
            "blocked_text_segments": 0,
            "direct_output_text_len": len(direct),
        }
    if isinstance(parsed_text, str) and parsed_text.strip():
        return parsed_text, {
            "response_status": None,
            "incomplete_reason": None,
            "output_items": 0,
            "output_types": [],
            "content_types": [],
            "included_text_segments": 1,
            "blocked_text_segments": 0,
            "direct_output_text_len": len(parsed_text),
        }

    payload = _to_jsonable(response)
    if not isinstance(payload, dict):
        return "", {
            "response_status": None,
            "incomplete_reason": None,
            "output_items": 0,
            "output_types": [],
            "content_types": [],
            "included_text_segments": 0,
            "blocked_text_segments": 0,
            "direct_output_text_len": len(direct) if isinstance(direct, str) else 0,
        }

    output = payload.get("output")
    output_types: list[str] = []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            output_type = item.get("type")
            if isinstance(output_type, str) and output_type not in output_types:
                output_types.append(output_type)

    diagnostics: dict[str, Any] = {
        "response_status": payload.get("status"),
        "incomplete_reason": payload.get("incomplete_details", {}).get("reason")
        if isinstance(payload.get("incomplete_details"), dict) else None,
        "output_items": len(output) if isinstance(output, list) else 0,
        "output_types": output_types[:8],
        "content_types": [],
        "included_text_segments": 0,
        "blocked_text_segments": 0,
        "direct_output_text_len": len(direct) if isinstance(direct, str) else 0,
    }

    output_parsed = payload.get("output_parsed")
    if isinstance(output_parsed, (dict, list)):
        return json.dumps(output_parsed, ensure_ascii=False), diagnostics

    chunks: list[str] = []
    if not isinstance(output, list):
        return "", diagnostics

    content_types_seen: list[str] = []

    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        is_non_output = isinstance(item_type, str) and item_type in _NON_OUTPUT_ITEM_TYPES
        if not is_non_output:
            for key in ("output_text", "text"):
                value = _coerce_text_value(item.get(key))
                if isinstance(value, str) and value.strip():
                    chunks.append(value)
                    diagnostics["included_text_segments"] = int(diagnostics["included_text_segments"]) + 1
            parsed_value = _coerce_json_value(item.get("parsed"))
            if isinstance(parsed_value, str) and parsed_value.strip():
                chunks.append(parsed_value)
                diagnostics["included_text_segments"] = int(diagnostics["included_text_segments"]) + 1
        content_items = item.get("content")
        if not isinstance(content_items, list):
            continue
        for content in content_items:
            if not isinstance(content, dict):
                continue
            content_type = content.get("type")
            if isinstance(content_type, str) and content_type not in content_types_seen:
                content_types_seen.append(content_type)
            is_blocked_content = isinstance(content_type, str) and content_type.startswith("input_")
            for key in ("output_text", "text"):
                value = _coerce_text_value(content.get(key))
                if not isinstance(value, str) or not value.strip():
                    continue
                if is_non_output or is_blocked_content:
                    diagnostics["blocked_text_segments"] = int(diagnostics["blocked_text_segments"]) + 1
                    continue
                chunks.append(value)
                diagnostics["included_text_segments"] = int(diagnostics["included_text_segments"]) + 1
            parsed_value = _coerce_json_value(content.get("parsed"))
            if not isinstance(parsed_value, str) or not parsed_value.strip():
                continue
            if is_non_output or is_blocked_content:
                diagnostics["blocked_text_segments"] = int(diagnostics["blocked_text_segments"]) + 1
                continue
            chunks.append(parsed_value)
            diagnostics["included_text_segments"] = int(diagnostics["included_text_segments"]) + 1

    diagnostics["content_types"] = content_types_seen[:12]
    return "\n".join(chunks).strip(), diagnostics


def _extract_text(response: Any) -> str:
    text, _ = _extract_text_and_diagnostics(response)
    return text


async def run_json_prompt(
    *,
    provider_id: str,
    model: str,
    prompt: str,
    max_output_tokens: int,
    reasoning_effort: str | None = None,
    json_schema: dict[str, Any] | None = None,
    max_retries: int = 2,
) -> str:
    kwargs = _client_kwargs(provider_id)
    if kwargs is None:
        return ""

    settings = get_settings()
    client = build_openai_client(settings=settings, **kwargs)
    request: dict[str, Any] = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "max_output_tokens": max_output_tokens,
    }
    if reasoning_effort:
        request["reasoning"] = {"effort": reasoning_effort}
    if json_schema is not None:
        request["text"] = {
            "format": {
                "type": "json_schema",
                "name": json_schema["name"],
                "schema": json_schema["schema"],
                "strict": True,
            }
        }

    empty_retry_count = 0
    current_max_output_tokens = max_output_tokens
    global _LAST_REQUEST_TS
    for attempt in range(max_retries + 1):
        try:
            async with _REQUEST_LOCK:
                now = monotonic()
                wait_sec = _MIN_REQUEST_INTERVAL_SEC - (now - _LAST_REQUEST_TS)
                if wait_sec > 0:
                    await asyncio.sleep(wait_sec)
                response = await client.responses.create(**request)
                _LAST_REQUEST_TS = monotonic()
            result, diagnostics = _extract_text_and_diagnostics(response)
            if result:
                return result
            logger.warning(
                "run_json_prompt empty text: provider=%s, model=%s, diagnostics=%s",
                provider_id,
                model,
                json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":")),
            )
            if empty_retry_count >= _EMPTY_RETRY_MAX_ATTEMPTS or attempt >= max_retries:
                return ""
            empty_retry_count += 1
            incomplete_reason = diagnostics.get("incomplete_reason")
            if incomplete_reason == "max_output_tokens" and current_max_output_tokens < _EMPTY_RETRY_TOKEN_CAP:
                current_max_output_tokens = min(
                    _EMPTY_RETRY_TOKEN_CAP,
                    max(current_max_output_tokens + 2000, current_max_output_tokens * 2),
                )
                request["max_output_tokens"] = current_max_output_tokens
            continue
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            logger.warning(
                "run_json_prompt error: provider=%s, model=%s, attempt=%d/%d, status=%s, error=%s",
                provider_id,
                model,
                attempt + 1,
                max_retries + 1,
                status_code,
                exc,
            )
            if attempt < max_retries and (status_code == 429 or (isinstance(status_code, int) and status_code >= 500)):
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
