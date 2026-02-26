from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapability:
    id: str
    label: str
    api_mode: str
    supports_temperature: bool
    supports_reasoning_effort: bool
    default_temperature: float | None
    default_reasoning_effort: str | None


OPENAI_MODELS: list[ModelCapability] = [
    ModelCapability(
        id="gpt-4o-mini",
        label="GPT-4o mini",
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=False,
        default_temperature=0.3,
        default_reasoning_effort=None,
    ),
    ModelCapability(
        id="gpt-4.1",
        label="GPT-4.1",
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=False,
        default_temperature=0.3,
        default_reasoning_effort=None,
    ),
    ModelCapability(
        id="gpt-5.2-2025-12-11",
        label="GPT-5.2",
        api_mode="responses",
        supports_temperature=False,
        supports_reasoning_effort=True,
        default_temperature=None,
        default_reasoning_effort="medium",
    ),
]

ANTHROPIC_MODELS: list[ModelCapability] = [
    ModelCapability(
        id="claude-3-5-haiku-latest",
        label="Claude 3.5 Haiku",
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=False,
        default_temperature=0.3,
        default_reasoning_effort=None,
    )
]

GOOGLE_MODELS: list[ModelCapability] = [
    ModelCapability(
        id="gemini-2.5-flash",
        label="Gemini 2.5 Flash",
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=False,
        default_temperature=0.3,
        default_reasoning_effort=None,
    ),
    ModelCapability(
        id="gemini-3-flash-preview",
        label="Gemini 3 Flash",
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=True,
        default_temperature=0.3,
        default_reasoning_effort="medium",
    )
]

DEEPSEEK_MODELS: list[ModelCapability] = [
    ModelCapability(
        id="deepseek-chat",
        label="DeepSeek Chat",
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=False,
        default_temperature=0.3,
        default_reasoning_effort=None,
    )
]

PROVIDER_MODELS: dict[str, list[ModelCapability]] = {
    "openai": OPENAI_MODELS,
    "anthropic": ANTHROPIC_MODELS,
    "google": GOOGLE_MODELS,
    "deepseek": DEEPSEEK_MODELS,
}


def list_models(provider_id: str) -> list[ModelCapability]:
    return PROVIDER_MODELS.get(provider_id, [])


def get_model_capability(provider_id: str, model: str) -> ModelCapability:
    for candidate in list_models(provider_id):
        if candidate.id == model:
            return candidate
    return ModelCapability(
        id=model,
        label=model,
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=False,
        default_temperature=0.3,
        default_reasoning_effort=None,
    )


def to_api(items: Iterable[ModelCapability]) -> list[dict[str, str | bool | float | None]]:
    return [
        {
            "id": item.id,
            "label": item.label,
            "api_mode": item.api_mode,
            "supports_temperature": item.supports_temperature,
            "supports_reasoning_effort": item.supports_reasoning_effort,
            "default_temperature": item.default_temperature,
            "default_reasoning_effort": item.default_reasoning_effort,
        }
        for item in items
    ]
