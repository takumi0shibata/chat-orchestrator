import json
from typing import Any

from anthropic import AsyncAnthropic
from google import genai
from google.genai import types
from openai import AsyncOpenAI

from app.config import get_settings


def _openai_client_kwargs(provider_id: str) -> dict[str, str] | None:
    settings = get_settings()
    if provider_id == "openai":
        api_key = (settings.openai_api_key or "").strip()
        return {"api_key": api_key} if api_key else None
    if provider_id == "azure_openai":
        api_key = (settings.azure_openai_api_key or "").strip()
        endpoint = (settings.azure_openai_endpoint or "").strip().rstrip("/")
        if not api_key or not endpoint:
            return None
        return {"api_key": api_key, "base_url": f"{endpoint}/openai/v1/"}
    if provider_id == "deepseek":
        api_key = (settings.deepseek_api_key or "").strip()
        base_url = (settings.deepseek_base_url or "").strip()
        if not api_key:
            return None
        return {"api_key": api_key, "base_url": base_url} if base_url else {"api_key": api_key}
    return None


async def run_json_prompt(
    *,
    provider_id: str,
    model: str,
    prompt: str,
    max_output_tokens: int = 300,
) -> str:
    kwargs = _openai_client_kwargs(provider_id)
    if kwargs is not None:
        client = AsyncOpenAI(**kwargs)
        response = await client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=max_output_tokens,
        )
        return getattr(response, "output_text", "") or ""

    settings = get_settings()
    if provider_id == "anthropic" and settings.anthropic_api_key:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=max_output_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        chunks: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        return "\n".join(chunks)

    if provider_id == "google" and settings.google_api_key:
        client = genai.Client(api_key=settings.google_api_key)
        response = await client.aio.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=max_output_tokens,
            ),
        )
        return response.text or ""

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
