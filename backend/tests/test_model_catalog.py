from app.config import Deployment, RuntimeConfig
import pytest

from app.model_catalog import models_for, pricing_for, validate_model


def test_gpt_5_6_terra_is_available_for_openai_and_azure():
    config = RuntimeConfig(
        azure_models=[Deployment(model="gpt-5.6-terra", deployment="azure-terra")]
    )

    openai_model = next(
        model for model in models_for("openai", config) if model["id"] == "gpt-5.6-terra"
    )
    assert openai_model == {
        "id": "gpt-5.6-terra",
        "model": "gpt-5.6-terra",
        "label": "GPT-5.6 Terra",
        "efforts": ["none", "low", "medium", "high", "xhigh", "max"],
    }

    azure_model = validate_model("azure_openai", "azure-terra", "max", config)
    assert azure_model["model"] == "gpt-5.6-terra"


@pytest.mark.parametrize("model", ["gpt-6-sol", "gpt-6-luna"])
def test_gpt_6_models_are_available_with_all_supported_efforts(model):
    config = RuntimeConfig()
    capability = validate_model("openai", model, "none", config)
    assert capability == {
        "id": model,
        "model": model,
        "label": "GPT-6 " + model.rsplit("-", 1)[1].title(),
        "efforts": ["none", "low", "medium", "high", "xhigh", "max"],
    }
    validate_model("openai", model, "max", config)
    with pytest.raises(ValueError):
        validate_model("openai", model, "minimal", config)


def test_azure_gpt_6_requires_deployment_registration():
    config = RuntimeConfig()
    assert models_for("azure_openai", config) == []
    with pytest.raises(ValueError):
        validate_model("azure_openai", "azure-sol", "medium", config)

    config.azure_models = [
        Deployment(model="gpt-5.6-luna", deployment="azure-old-luna"),
        Deployment(model="gpt-6-sol", deployment="azure-sol"),
        Deployment(model="gpt-6-luna", deployment="azure-luna"),
    ]
    assert [item["id"] for item in models_for("azure_openai", config)] == [
        "azure-old-luna", "azure-sol", "azure-luna"
    ]
    assert validate_model("azure_openai", "azure-sol", "none", config)["model"] == "gpt-6-sol"
    assert validate_model("azure_openai", "azure-luna", "max", config)["model"] == "gpt-6-luna"
    assert pricing_for("azure_openai", "azure-luna", config)[0] == "gpt-6-luna"
