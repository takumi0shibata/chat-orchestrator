import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.chat_service import ChatOrchestrator
from app.main import app, state
from app.skills_runtime.manager import SkillManager
from app.storage import ChatStore


class DummyProviders:
    def get(self, provider_id: str):
        raise AssertionError(f"provider access is unexpected in this test: {provider_id}")


def _set_state(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    manager = SkillManager(project_root / "skills")
    manager.load()

    state.store = ChatStore(db_path=tmp_path / "chat-test.db")
    state.providers = DummyProviders()
    state.skills = manager
    state.chat = ChatOrchestrator(store=state.store, skills=state.skills)


def test_list_skills_returns_category_and_tags() -> None:
    expected_categories = {
        "todo_extractor": "general",
        "context_summarizer": "general",
        "docx_auto_commenter": "general",
        "audit_news_action_brief": "audit",
        "boj_timeseries_insight": "finance",
        "edinet_report_qa": "audit",
        "paper_reviewer": "research",
    }

    with tempfile.TemporaryDirectory() as tmp:
        with TestClient(app) as client:
            _set_state(Path(tmp))

            response = client.get("/api/skills")
            assert response.status_code == 200
            payload = response.json()

    by_id = {item["id"]: item for item in payload}
    assert expected_categories.keys() <= by_id.keys()

    for skill_id, expected_category in expected_categories.items():
        item = by_id[skill_id]
        assert item["primary_category"]["id"] == expected_category
        assert item["primary_category"]["label"]
        assert item["tags"]
        assert all(tag.strip() for tag in item["tags"])
