import asyncio
import logging
import sys
import types
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Keep unit tests isolated from optional runtime deps (pydantic, real OpenAI client).
fake_config = types.ModuleType("app.config")
fake_config.get_settings = lambda: types.SimpleNamespace(
    openai_api_key="test",
    azure_openai_api_key="test",
    azure_openai_base_url="https://example.openai.azure.com/openai/v1/",
    outbound_proxy_url=None,
)
sys.modules.setdefault("app.config", fake_config)

fake_openai_client = types.ModuleType("app.openai_client")
fake_openai_client.build_openai_client = lambda **kwargs: None
sys.modules.setdefault("app.openai_client", fake_openai_client)

from skills.audit_news_action_brief import audit_news_llm_client as llm_client  # noqa: E402


class FakeResponse:
    def __init__(self, *, output_text: str, payload: dict[str, Any]) -> None:
        self.output_text = output_text
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return self._payload


class FakeResponsesAPI:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return self.response


def _set_up_fakes(monkeypatch, *, response: FakeResponse) -> FakeResponsesAPI:
    fake_responses = FakeResponsesAPI(response=response)
    fake_client = types.SimpleNamespace(responses=fake_responses)
    fake_settings = types.SimpleNamespace(
        openai_api_key="openai-test-key",
        azure_openai_api_key="azure-test-key",
        azure_openai_base_url="https://example.openai.azure.com/openai/v1/",
        outbound_proxy_url=None,
    )

    monkeypatch.setattr(llm_client, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(llm_client, "build_openai_client", lambda **_: fake_client)
    monkeypatch.setattr(llm_client, "_MIN_REQUEST_INTERVAL_SEC", 0.0)
    monkeypatch.setattr(llm_client, "_LAST_REQUEST_TS", 0.0)
    monkeypatch.setattr(llm_client, "_REQUEST_LOCK", asyncio.Lock())
    return fake_responses


def test_run_json_prompt_with_web_falls_back_to_content_text(monkeypatch) -> None:
    response = FakeResponse(
        output_text="",
        payload={
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": '[{"title":"fallback-result"}]'},
                    ],
                }
            ]
        },
    )
    fake_responses = _set_up_fakes(monkeypatch, response=response)

    result = asyncio.run(
        llm_client.run_json_prompt_with_web(
            provider_id="azure_openai",
            model="gpt-5.2-2025-12-11",
            prompt="test prompt",
            max_retries=0,
        )
    )

    assert result == '[{"title":"fallback-result"}]'
    assert fake_responses.calls[0]["tools"] == [llm_client._WEB_SEARCH_TOOL]


def test_run_json_prompt_keeps_existing_output_text(monkeypatch) -> None:
    response = FakeResponse(
        output_text='[{"title":"direct-result"}]',
        payload={
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": '[{"title":"fallback-should-not-win"}]'},
                    ],
                }
            ]
        },
    )
    fake_responses = _set_up_fakes(monkeypatch, response=response)

    result = asyncio.run(
        llm_client.run_json_prompt(
            provider_id="openai",
            model="gpt-5.2-2025-12-11",
            prompt="test prompt",
            max_retries=0,
        )
    )

    assert result == '[{"title":"direct-result"}]'
    assert "tools" not in fake_responses.calls[0]


def test_run_json_prompt_with_web_logs_empty_text_diagnostics(monkeypatch, caplog) -> None:
    response = FakeResponse(
        output_text="",
        payload={
            "output": [
                {
                    "type": "web_search_call",
                    "content": [
                        {"type": "input_text", "text": "query only"},
                    ],
                }
            ]
        },
    )
    _set_up_fakes(monkeypatch, response=response)

    caplog.set_level(logging.WARNING, logger="audit_news")
    result = asyncio.run(
        llm_client.run_json_prompt_with_web(
            provider_id="azure_openai",
            model="gpt-5.2-2025-12-11",
            prompt="test prompt",
            max_retries=0,
        )
    )

    assert result == ""
    assert "run_json_prompt_with_web empty text" in caplog.text
    assert "provider=azure_openai" in caplog.text
    assert "model=gpt-5.2-2025-12-11" in caplog.text
    assert "output_types=web_search_call" in caplog.text
