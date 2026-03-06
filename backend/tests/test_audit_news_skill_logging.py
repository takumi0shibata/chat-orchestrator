import asyncio
import logging
import sys
import types
from pathlib import Path

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

from skills.audit_news_action_brief import skill as skill_module  # noqa: E402


def _build_parsed_request() -> skill_module.ParsedRequest:
    return skill_module.ParsedRequest(
        client_name="A食品株式会社",
        client_industry="食品",
        watch_competitors=["Bフーズ"],
        lookback_days=7,
        focus_topics=["原材料価格"],
    )


def test_search_category_logs_empty_array(monkeypatch, caplog) -> None:
    async def _fake_run_json_prompt_with_web(**kwargs):
        del kwargs
        return "[]"

    monkeypatch.setattr(skill_module, "run_json_prompt_with_web", _fake_run_json_prompt_with_web)
    caplog.set_level(logging.WARNING, logger="audit_news")

    skill = skill_module.AuditNewsActionBriefSkill()
    items = asyncio.run(
        skill._search_category(
            view="self_company",
            parsed=_build_parsed_request(),
            provider_id="azure_openai",
            model="gpt-5.2-2025-12-11",
            prior_titles=[],
        )
    )

    assert items == []
    assert "_search_category EMPTY array: view=self_company" in caplog.text
    assert "_search_category EMPTY response: view=self_company" not in caplog.text


def test_search_category_logs_empty_response(monkeypatch, caplog) -> None:
    async def _fake_run_json_prompt_with_web(**kwargs):
        del kwargs
        return ""

    monkeypatch.setattr(skill_module, "run_json_prompt_with_web", _fake_run_json_prompt_with_web)
    caplog.set_level(logging.WARNING, logger="audit_news")

    skill = skill_module.AuditNewsActionBriefSkill()
    items = asyncio.run(
        skill._search_category(
            view="macro",
            parsed=_build_parsed_request(),
            provider_id="azure_openai",
            model="gpt-5.2-2025-12-11",
            prior_titles=[],
        )
    )

    assert items == []
    assert "_search_category EMPTY response: view=macro" in caplog.text
    assert "_search_category EMPTY array: view=macro" not in caplog.text
