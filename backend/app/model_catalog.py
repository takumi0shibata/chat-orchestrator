from collections.abc import Iterable
from dataclasses import dataclass

REASONING_EFFORT_OPTIONS_5 = ("none", "low", "medium", "high", "xhigh")
REASONING_EFFORT_OPTIONS_4 = ("minimal", "low", "medium", "high")
REASONING_EFFORT_OPTIONS_3 = ("low", "medium", "high")


@dataclass(frozen=True)
class ModelCapability:
    id: str
    label: str
    api_mode: str
    supports_temperature: bool
    supports_reasoning_effort: bool
    supports_image_input: bool
    default_temperature: float | None
    default_reasoning_effort: str | None
    reasoning_effort_options: tuple[str, ...] = ()


OPENAI_MODELS: list[ModelCapability] = [
    ModelCapability(
        id="gpt-5.4-2026-03-05",
        label="GPT-5.4",
        api_mode="responses",
        supports_temperature=False,
        supports_reasoning_effort=True,
        supports_image_input=True,
        default_temperature=None,
        default_reasoning_effort="medium",
        reasoning_effort_options=REASONING_EFFORT_OPTIONS_5,
    ),
    ModelCapability(
        id="gpt-5-mini-2025-08-07",
        label="GPT-5 mini",
        api_mode="responses",
        supports_temperature=False,
        supports_reasoning_effort=True,
        supports_image_input=True,
        default_temperature=None,
        default_reasoning_effort="medium",
        reasoning_effort_options=REASONING_EFFORT_OPTIONS_4,
    ),
]

AZURE_OPENAI_MODELS: list[ModelCapability] = [
    ModelCapability(
        id="gpt-5.4-2026-03-05",
        label="GPT-5.4",
        api_mode="responses",
        supports_temperature=False,
        supports_reasoning_effort=True,
        supports_image_input=True,
        default_temperature=None,
        default_reasoning_effort="medium",
        reasoning_effort_options=REASONING_EFFORT_OPTIONS_5,
    ),
]

ANTHROPIC_MODELS: list[ModelCapability] = [
    ModelCapability(
        id="claude-3-5-haiku-latest",
        label="Claude 3.5 Haiku",
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=False,
        supports_image_input=False,
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
        supports_image_input=False,
        default_temperature=0.3,
        default_reasoning_effort=None,
    ),
    ModelCapability(
        id="gemini-3-flash-preview",
        label="Gemini 3 Flash",
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=True,
        supports_image_input=False,
        default_temperature=0.3,
        default_reasoning_effort="medium",
        reasoning_effort_options=REASONING_EFFORT_OPTIONS_3,
    ),
]

DEEPSEEK_MODELS: list[ModelCapability] = [
    ModelCapability(
        id="deepseek-chat",
        label="DeepSeek Chat",
        api_mode="chat_completions",
        supports_temperature=True,
        supports_reasoning_effort=False,
        supports_image_input=False,
        default_temperature=0.3,
        default_reasoning_effort=None,
    )
]

PROVIDER_MODELS: dict[str, list[ModelCapability]] = {
    "openai": OPENAI_MODELS,
    "azure_openai": AZURE_OPENAI_MODELS,
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
        supports_image_input=False,
        default_temperature=0.3,
        default_reasoning_effort=None,
    )


def to_api(items: Iterable[ModelCapability]) -> list[dict[str, str | bool | float | None | list[str]]]:
    return [
        {
            "id": item.id,
            "label": item.label,
            "api_mode": item.api_mode,
            "supports_temperature": item.supports_temperature,
            "supports_reasoning_effort": item.supports_reasoning_effort,
            "supports_image_input": item.supports_image_input,
            "default_temperature": item.default_temperature,
            "default_reasoning_effort": item.default_reasoning_effort,
            "reasoning_effort_options": list(item.reasoning_effort_options),
        }
        for item in items
    ]
