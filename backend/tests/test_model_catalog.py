from app.model_catalog import get_model_capability, list_models


def test_azure_openai_models_exist_in_catalog() -> None:
    models = list_models("azure_openai")
    assert models
    assert models[0].id == "gpt-5.4-2026-03-05"
    assert any(model.id == "gpt-5.4-2026-03-05" for model in models)


def test_azure_openai_model_capability_for_responses() -> None:
    capability = get_model_capability("azure_openai", "gpt-5.4-2026-03-05")
    assert capability.api_mode == "responses"
    assert capability.supports_temperature is False
    assert capability.supports_reasoning_effort is True
    assert capability.supports_image_input is True
    assert capability.default_reasoning_effort == "medium"
    assert capability.reasoning_effort_options == ("none", "low", "medium", "high", "xhigh")


def test_openai_uses_gpt_54_mini_instead_of_gpt_5_mini() -> None:
    models = list_models("openai")
    model_ids = [model.id for model in models]
    assert "gpt-5.4-mini-2026-03-05" in model_ids
    assert "gpt-5-mini-2025-08-07" not in model_ids

    mini = get_model_capability("openai", "gpt-5.4-mini-2026-03-05")
    assert mini.label == "GPT-5.4 mini"
    assert mini.api_mode == "responses"
    assert mini.supports_reasoning_effort is True
    assert mini.reasoning_effort_options == ("minimal", "low", "medium", "high")


def test_unknown_model_defaults_to_no_image_support() -> None:
    capability = get_model_capability("openai", "unknown-model")
    assert capability.supports_image_input is False
