from app.model_catalog import get_model_capability, list_models


def test_azure_openai_models_exist_in_catalog() -> None:
    models = list_models("azure_openai")
    assert models
    assert any(model.id == "gpt-5.2-2025-12-11" for model in models)


def test_azure_openai_model_capability_for_responses() -> None:
    capability = get_model_capability("azure_openai", "gpt-5.2-2025-12-11")
    assert capability.api_mode == "responses"
    assert capability.supports_temperature is False
    assert capability.supports_reasoning_effort is True
