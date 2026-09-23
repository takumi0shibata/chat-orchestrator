MODELS = {
    "gpt-6-sol": {
        "label": "GPT-6 Sol",
        "efforts": ["none", "low", "medium", "high", "xhigh", "max"],
    },
    "gpt-6-luna": {
        "label": "GPT-6 Luna",
        "efforts": ["none", "low", "medium", "high", "xhigh", "max"],
    },
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

# Standard API text-token prices in USD per 1M tokens. These values are kept in
# code so every ledger entry can snapshot the rate that was used at the time.
MODEL_PRICING = {
    "gpt-6-sol": {"input": 2.0, "cached_input": 0.2, "cache_write": 2.5, "output": 10.0},
    "gpt-6-luna": {"input": 0.1, "cached_input": 0.01, "cache_write": 0.125, "output": 0.5},
    "gpt-5.6-sol": {"input": 4.0, "cached_input": 0.4, "cache_write": 5.0, "output": 20.0},
    "gpt-5.6-terra": {"input": 2.0, "cached_input": 0.2, "cache_write": 2.5, "output": 12.0},
    "gpt-5.6-luna": {"input": 0.2, "cached_input": 0.02, "cache_write": 0.25, "output": 1.2},
    "gpt-6-astra": {"input": 10.0, "cached_input": 1.0, "cache_write": 12.5, "output": 50.0},
}


def base_model_for(provider, model, config):
    if provider == "openai":
        return model if model in MODELS else None
    if provider == "azure_openai":
        deployment = next((d for d in config.azure_models if d.deployment == model), None)
        return deployment.model if deployment and deployment.model in MODELS else None
    return None


def pricing_for(provider, model, config):
    base_model = base_model_for(provider, model, config)
    return base_model, MODEL_PRICING.get(base_model)


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
