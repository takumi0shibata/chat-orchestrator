from app.config import Deployment, RuntimeConfig
from app.model_catalog import models_for, validate_model


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
