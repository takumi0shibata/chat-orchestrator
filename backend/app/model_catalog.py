MODELS = {
    "gpt-5.6-sol": {
        "label": "GPT-5.6 Sol",
        "efforts": ["none", "low", "medium", "high", "xhigh", "max"],
    },
    "gpt-5.6-terra": {
        "label": "GPT-5.6 Terra",
        "efforts": ["none", "low", "medium", "high", "xhigh", "max"],
    },
    "gpt-5.6-luna": {
        "label": "GPT-5.6 Luna",
        "efforts": ["low", "medium", "high", "xhigh", "max"],
    },
    "gpt-6-astra": {
        "label": "GPT-6 Astra",
        "efforts": ["low", "medium", "high", "xhigh", "max"],
    },
}


def models_for(provider, config):
    if provider == "openai":
        return [dict(id=k, model=k, **v) for k, v in MODELS.items()]
    if provider == "azure_openai":
        return [
            dict(id=d.deployment, model=d.model, **MODELS[d.model])
            for d in config.azure_models
            if d.model in MODELS
        ]
    return []


def validate_model(provider, model, effort, config):
    capability = next(
        (m for m in models_for(provider, config) if m["id"] == model), None
    )
    if not capability or effort not in capability["efforts"]:
        raise ValueError("Unsupported model/deployment or reasoning effort")
    return capability
