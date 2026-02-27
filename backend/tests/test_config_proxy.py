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
