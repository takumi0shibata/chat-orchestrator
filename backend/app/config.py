from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    _backend_env = Path(__file__).resolve().parents[1] / ".env"
    _repo_env = Path(__file__).resolve().parents[2] / ".env"
    model_config = SettingsConfigDict(
        env_file=(str(_backend_env), str(_repo_env)),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Chat Orchestrator API"
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    openai_api_key: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_mode: str = "responses"
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    edinet_api_key: str | None = None
    edinet_cache_dir: str | None = None
    edinet_cache_ttl_hours: int = 24
    edinet_lookback_days: int = 365

    default_openai_model: str = "gpt-4o-mini"
    default_azure_openai_model: str | None = None
    default_anthropic_model: str = "claude-3-5-haiku-latest"
    default_google_model: str = "gemini-2.5-flash"
    default_deepseek_model: str = "deepseek-chat"

    @property
    def azure_openai_enabled(self) -> bool:
        return bool(self.azure_openai_api_key and self.azure_openai_endpoint and self.azure_openai_deployment)

    @property
    def azure_openai_base_url(self) -> str:
        endpoint = (self.azure_openai_endpoint or "").rstrip("/")
        return f"{endpoint}/openai/v1/"

    @property
    def azure_openai_default_model(self) -> str:
        return self.default_azure_openai_model or self.azure_openai_deployment or "azure-openai-deployment"

    @property
    def provider_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "openai",
                "label": "OpenAI",
                "enabled": bool(self.openai_api_key),
                "default_model": self.default_openai_model,
            },
            {
                "id": "azure_openai",
                "label": "Azure OpenAI",
                "enabled": self.azure_openai_enabled,
                "default_model": self.azure_openai_default_model,
            },
            {
                "id": "anthropic",
                "label": "Anthropic",
                "enabled": bool(self.anthropic_api_key),
                "default_model": self.default_anthropic_model,
            },
            {
                "id": "google",
                "label": "Google",
                "enabled": bool(self.google_api_key),
                "default_model": self.default_google_model,
            },
            {
                "id": "deepseek",
                "label": "DeepSeek",
                "enabled": bool(self.deepseek_api_key),
                "default_model": self.default_deepseek_model,
            },
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
