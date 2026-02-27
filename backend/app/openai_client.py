from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from app.config import Settings


def build_openai_client(
    *,
    settings: Settings,
    api_key: str,
    base_url: str | None = None,
) -> AsyncOpenAI:
    kwargs = {"api_key": api_key, "base_url": base_url}
    proxy_url = settings.outbound_proxy_url
    if proxy_url:
        kwargs["http_client"] = DefaultAsyncHttpxClient(proxy=proxy_url)
    return AsyncOpenAI(**kwargs)
