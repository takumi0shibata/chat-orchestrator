import asyncio
import json
import sys
import types
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from skills.docx_auto_commenter import llm_client  # noqa: E402


class FakeResponse:
    def __init__(self, *, output_text: str, payload: dict[str, Any]) -> None:
        self.output_text = output_text
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return self._payload


class FakeResponsesAPI:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self._index = 0

    async def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if self._index >= len(self.responses):
            return self.responses[-1]
        response = self.responses[self._index]
        self._index += 1
        return response


def _set_up_fakes(monkeypatch, *, response: FakeResponse | list[FakeResponse]) -> FakeResponsesAPI:
    responses = response if isinstance(response, list) else [response]
    fake_responses = FakeResponsesAPI(responses=responses)
    fake_client = types.SimpleNamespace(responses=fake_responses)
    fake_settings = types.SimpleNamespace(
        openai_api_key="openai-test-key",
        azure_openai_api_key="azure-test-key",
        azure_openai_base_url="https://example.openai.azure.com/openai/v1/",
        azure_openai_enabled=True,
    )

    monkeypatch.setattr(llm_client, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(llm_client, "build_openai_client", lambda **_: fake_client)
    monkeypatch.setattr(llm_client, "_MIN_REQUEST_INTERVAL_SEC", 0.0)
    monkeypatch.setattr(llm_client, "_LAST_REQUEST_TS", 0.0)
    monkeypatch.setattr(llm_client, "_REQUEST_LOCK", asyncio.Lock())
    return fake_responses


def test_extract_text_handles_none_output_and_content() -> None:
    assert llm_client._extract_text({"output": None}) == ""
    assert llm_client._extract_text({"output": [{"type": "message", "content": None}]}) == ""


def test_extract_text_reads_nested_text_value() -> None:
    text = llm_client._extract_text(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": {"value": '{"comments":[{"quote":"A","comment":"B","category":"clarity","priority":"high"}]}'},
                        }
                    ],
                }
            ]
        }
    )

    assert text == '{"comments":[{"quote":"A","comment":"B","category":"clarity","priority":"high"}]}'


def test_extract_text_reads_parsed_payload() -> None:
    text = llm_client._extract_text(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "parsed": {
                                "comments": [
                                    {"quote": "A", "comment": "B", "category": "clarity", "priority": "high"}
                                ]
                            },
                        }
                    ],
                }
            ]
        }
    )

    assert json.loads(text) == {
        "comments": [{"quote": "A", "comment": "B", "category": "clarity", "priority": "high"}]
    }


def test_run_json_prompt_retries_empty_and_expands_max_output_tokens(monkeypatch) -> None:
    first = FakeResponse(
        output_text="",
        payload={
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": {"value": ""}}]}],
        },
    )
    second = FakeResponse(
        output_text="",
        payload={
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": {
                                "value": '{"comments":[{"quote":"A","comment":"B","category":"clarity","priority":"high"}]}'
                            },
                        }
                    ],
                }
            ],
        },
    )
    fake_responses = _set_up_fakes(monkeypatch, response=[first, second])

    result = asyncio.run(
        llm_client.run_json_prompt(
            provider_id="openai",
            model="gpt-5.4-2026-03-05",
            prompt="test prompt",
            max_output_tokens=2600,
            max_retries=1,
        )
    )

    assert result == '{"comments":[{"quote":"A","comment":"B","category":"clarity","priority":"high"}]}'
    assert len(fake_responses.calls) == 2
    assert fake_responses.calls[0]["max_output_tokens"] == 2600
    assert fake_responses.calls[1]["max_output_tokens"] == 5200
