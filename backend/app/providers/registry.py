from fastapi import HTTPException

from app.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider
from app.providers.google_provider import GoogleProvider
from app.providers.openai_provider import OpenAIProvider


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: dict[str, LLMProvider] = {}
        self._build_registry()

    def _build_registry(self) -> None:
        if self.settings.openai_api_key:
            self._providers["openai"] = OpenAIProvider(
                api_key=self.settings.openai_api_key,
                provider_id="openai",
            )
        if self.settings.anthropic_api_key:
            self._providers["anthropic"] = AnthropicProvider(api_key=self.settings.anthropic_api_key)
        if self.settings.google_api_key:
            self._providers["google"] = GoogleProvider(api_key=self.settings.google_api_key)
        if self.settings.deepseek_api_key:
            self._providers["deepseek"] = OpenAIProvider(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
                provider_id="deepseek",
            )

    def get(self, provider_id: str) -> LLMProvider:
        provider = self._providers.get(provider_id)
        if not provider:
            raise HTTPException(status_code=400, detail=f"Provider is not enabled: {provider_id}")
        return provider
