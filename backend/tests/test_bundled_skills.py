import pytest

from app.config import BUNDLED_SKILLS, Folder, Settings
from app.sandbox import Sandbox
from test_agent import FakeSandbox, run_environment
from test_api import app_client  # noqa: F401 - shared API fixture


@pytest.mark.parametrize("configured", [False, True])
def test_guild_skill_available_without_registration(tmp_path, configured):
    runtime = tmp_path / "runtime.toml"
    if configured:
        runtime.write_text("skills = []\n")
    settings = Settings(_env_file=None, runtime_config=runtime)
    config = settings.load_runtime()
    skill, = config.skills
    assert skill.id == skill.name == "guild-journal"
    assert skill.path == BUNDLED_SKILLS / "guild-journal"
    assert skill.description
    assert len(settings.load_runtime().skills) == 1
    assert runtime.exists() is configured  # Loading does not modify user configuration.


@pytest.mark.parametrize("sid,name", [
    ("review", "review-paper"),
    ("guild-journal", "custom-guild"),
    ("my-guild", "guild-journal"),
])
def test_custom_skills_are_preserved_and_can_replace_bundled_skill(tmp_path, sid, name):
    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Custom workflow\n---\nUse local records.\n")
    runtime = tmp_path / "runtime.toml"
    runtime.write_text(f'[[skills]]\nid = "{sid}"\nlabel = "Custom"\npath = "{custom}"\n')
    config = Settings(_env_file=None, runtime_config=runtime).load_runtime()
    assert config.skills[-1].path == custom
    assert config.skills[-1].name == name
    assert len(config.skills) == (2 if sid == "review" else 1)


def test_bundled_skill_is_mounted_read_only(tmp_path):
    settings = Settings(_env_file=None, runtime_config=tmp_path / "missing.toml")
    config = settings.load_runtime()
    work = tmp_path / "work"
    work.mkdir()
    sandbox = Sandbox(settings, Folder(id="work", label="Work", path=work), "test", config.skills, [], tmp_path / "input")
    args = sandbox.arguments()
    assert f"type=bind,src={BUNDLED_SKILLS / 'guild-journal'},dst=/skills/guild-journal,readonly" in args
    assert args[args.index("--network") + 1] == "none"
    assert not (work / ".chat-orchestrator").exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_guild_skill_exposed_to_ui_and_model_without_creating_records(app_client, explicit):
    http, work, model = app_client
    skill, = http.get("/api/config").json()["skills"]
    assert skill["id"] == skill["name"] == "guild-journal"
    assert skill["label"] == "ギルド記録"
    assert skill["description"]
    assert "path" not in skill
    cid = http.post("/api/conversations", json={"workspace_id": "work"}).json()["id"]
    selected = ["guild-journal"] if explicit else []
    response = http.post("/api/runs", json={"conversation_id": cid, "input": "Explain the guild", "skill_ids": selected})
    assert response.status_code == 200
    rid = response.json()["id"]
    http.get(f"/api/runs/{rid}/events")
    assert http.get(f"/api/runs/{rid}").json()["status"] == "completed"
    call = next(call for call in model.calls if any(tool["type"] == "shell" for tool in call.get("tools", [])))
    environment = run_environment(call)
    available, = environment["available_skills"]
    assert available["name"] == "guild-journal"
    assert available["path"] == "/skills/guild-journal"
    assert environment["explicit_skill_ids"] == selected
    assert FakeSandbox.instances[-1].skills[0].path == BUNDLED_SKILLS / "guild-journal"
    assert not (work / ".chat-orchestrator").exists()
    assert http.post("/api/guild/sync").json()["projects"] == []
