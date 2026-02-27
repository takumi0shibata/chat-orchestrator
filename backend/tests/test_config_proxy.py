from app.config import Settings


def test_outbound_proxy_prefers_all_proxy() -> None:
    settings = Settings(
        _env_file=None,
        http_proxy="http://127.0.0.1:18080",
        https_proxy="http://127.0.0.1:18443",
        all_proxy="socks5h://127.0.0.1:1080",
    )
    assert settings.outbound_proxy_url == "socks5h://127.0.0.1:1080"


def test_outbound_proxy_falls_back_to_https_then_http() -> None:
    settings_https = Settings(
        _env_file=None,
        http_proxy="http://127.0.0.1:18080",
        https_proxy="http://127.0.0.1:18443",
        all_proxy="  ",
    )
    assert settings_https.outbound_proxy_url == "http://127.0.0.1:18443"

    settings_http = Settings(_env_file=None, http_proxy="http://127.0.0.1:18080", https_proxy=None, all_proxy=None)
    assert settings_http.outbound_proxy_url == "http://127.0.0.1:18080"


def test_azure_openai_enabled_without_deployment() -> None:
    settings = Settings(
        _env_file=None,
        azure_openai_api_key="test-key",
        azure_openai_endpoint="https://example.openai.azure.com",
    )
    assert settings.azure_openai_enabled is True


def test_azure_openai_default_model_prefers_configured_value() -> None:
    settings = Settings(_env_file=None, default_azure_openai_model="my-azure-deployment")
    assert settings.azure_openai_default_model == "my-azure-deployment"


def test_azure_openai_default_model_uses_catalog_head() -> None:
    settings = Settings(_env_file=None, default_azure_openai_model=None)
    assert settings.azure_openai_default_model == "gpt-5.2-2025-12-11"
