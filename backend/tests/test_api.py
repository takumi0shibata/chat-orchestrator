import pytest
from app.agent_runner import RunManager
from app.attachments import open_regular
from app.config import Folder, RuntimeConfig, Settings, Skill
from app.main import create_app
from fastapi.testclient import TestClient
from test_agent import Client, FakeSandbox, message


@pytest.fixture
def app_client(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    config = tmp_path / "runtime.toml"
    config.write_text(f'[[workspaces]]\nid="work"\nlabel="Work"\npath="{work}"\n')
    settings = Settings(
        _env_file=None,
        runtime_config=config,
        data_dir=tmp_path / "data",
        openai_api_key="test-key",
    )
    client = Client([[message()], [message()]])
    app = create_app(
        settings,
        lambda s, c, st: RunManager(
            s, c, st, client_factory=lambda _: client, sandbox_factory=FakeSandbox
        ),
    )
    with TestClient(app) as http:
        yield http, work, client


def test_config_no_credentials_and_origins(app_client):
    http, work, _ = app_client
    config = http.get("/api/config").json()
    assert [p["id"] for p in config["providers"]] == ["openai", "azure_openai"]
    assert config["providers"][0]["models"][0]["id"] == "gpt-6-sol"
    assert config["providers"][1]["models"] == []
    assert "test-key" not in str(config)
    assert (
        http.post(
            "/api/conversations",
            json={"workspace_id": "work"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert http.get("/api/config", headers={"Host": "evil.example"}).status_code == 400
    assert (
        http.post("/api/conversations", json={"workspace_id": "other"}).status_code
        == 400
    )
    assert http.get("/api/skills").status_code == 404


def test_run_events_replay_delete_preserves_original(app_client):
    http, work, _ = app_client
    original = work / "original.txt"
    original.write_text("original")
    cid = http.post("/api/conversations", json={"workspace_id": "work"}).json()["id"]
    r = http.post("/api/runs", json={"conversation_id": cid, "input": "hello"}).json()
    assert r["request"]["model"] == "gpt-6-sol"
    first = http.get(f"/api/runs/{r['id']}/events").text.strip().splitlines()
    import json

    events = [json.loads(x) for x in first if x.strip()]
    assert events[-1]["data"]["status"] == "completed"
    after = events[1]["seq"]
    replay = (
        http.get(f"/api/runs/{r['id']}/events?after={after}").text.strip().splitlines()
    )
    assert [json.loads(x) for x in replay] == events[2:]
    assert (
        http.get(f"/api/conversations/{cid}").json()["runs"][0]["status"] == "completed"
    )
    assert http.delete(f"/api/conversations/{cid}").status_code == 200
    assert original.read_text() == "original"


def test_files_boundaries_and_upload(app_client):
    http, work, _ = app_client
    cid = http.post("/api/conversations", json={"workspace_id": "work"}).json()["id"]
    for i in range(200):
        (work / f"{i}.txt").write_text("test")
    secret = work.parent / "secret"
    secret.write_text("private")
    (work / "escape").symlink_to(secret)
    assert len(http.get(f"/api/conversations/{cid}/files").json()) == 200
    for path in ("../secret", str(secret), "escape"):
        assert (
            http.get(
                f"/api/conversations/{cid}/download", params={"path": path}
            ).status_code
            == 400
        )
    assert (
        http.get(f"/api/conversations/{cid}/download", params={"path": "0.txt"}).content
        == b"test"
    )
    result = http.post(
        "/api/attachments",
        data={"conversation_id": cid},
        files={"files": ("../x.txt", b"abc", "text/plain")},
    ).json()[0]
    assert result["name"] == "x.txt"
    another = http.post("/api/conversations", json={"workspace_id": "work"}).json()[
        "id"
    ]
    assert (
        http.post(
            "/api/runs",
            json={
                "conversation_id": another,
                "input": "x",
                "attachment_ids": [result["id"]],
            },
        ).status_code
        == 404
    )
    assert (
        http.post(
            "/api/runs",
            json={
                "conversation_id": cid,
                "input": "x",
                "attachment_ids": [result["id"]],
                "direct_attachment_ids": [result["id"]],
            },
        ).status_code
        == 400
    )


def test_skills_and_overlap(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: analyze\ndescription: Analyze CSV\n---\nRead instructions."
    )
    parsed = Skill(id="csv", label="CSV", path=skill)
    assert parsed.name == "analyze"
    with pytest.raises(ValueError):
        RuntimeConfig(
            workspaces=[
                Folder(id="a", label="A", path=tmp_path),
                Folder(id="b", label="B", path=skill),
            ]
        )


def test_open_regular_rejects_symlink_parent(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_text("private")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        open_regular(root, "link/file")


def test_sdk_azure_base_url_and_proxy():
    from app.openai_client import build_openai_client

    s = Settings(
        _env_file=None,
        azure_openai_endpoint="https://example.openai.azure.com/",
        http_proxy=None,
        https_proxy=None,
        all_proxy=None,
    )
    client = build_openai_client(
        settings=s, api_key="test", base_url=s.azure_openai_base_url
    )
    assert str(client.base_url) == "https://example.openai.azure.com/openai/v1/"
    import asyncio

    asyncio.run(client.close())
    s.azure_openai_endpoint = "https://example.openai.azure.com/openai/v1/"
    assert s.azure_openai_base_url == "https://example.openai.azure.com/openai/v1"


def test_upload_limits_and_signature(tmp_path):
    from app.attachments import direct_input

    pdf = tmp_path / "file.pdf"
    pdf.write_bytes(b"not a PDF")
    with pytest.raises(ValueError, match="signature"):
        direct_input(dict(path=str(pdf), size=9, name="file.pdf"))
    pdf.write_bytes(b"%PDF-1.7\n")
    assert (
        direct_input(dict(path=str(pdf), size=9, name="file.pdf"))["type"]
        == "input_file"
    )
    with pytest.raises(ValueError, match="20 MiB"):
        direct_input(dict(path=str(pdf), size=21 * 1024 * 1024, name="file.pdf"))


def test_search_and_pin_api(app_client):
    http, _, _ = app_client
    c = http.post("/api/conversations", json={"workspace_id": "work"}).json()
    assert c["pinned"] is False
    result = http.patch(f"/api/conversations/{c['id']}", json={"pinned": True})
    assert result.status_code == 200
    assert result.json()["pinned"] is True
    assert result.json()["updated_at"] == c["updated_at"]
    assert "context" not in result.json()
    assert http.get("/api/conversations", params={"q": "新しい"}).json()[0]["id"] == c["id"]
    assert http.get("/api/conversations?q=missing").json() == []
    assert http.patch("/api/conversations/missing", json={"pinned": True}).status_code == 404
    assert http.patch(f"/api/conversations/{c['id']}", json={"unknown": True}).status_code == 422


def test_settings_and_monthly_cost_api(app_client):
    http, _, _ = app_client
    settings = http.get("/api/settings").json()
    assert settings == {
        "title_provider": "openai",
        "title_model": "gpt-6-luna",
        "theme_color": "#25262A",
    }
    updated = http.patch("/api/settings", json={"theme_color": "#abcdef"})
    assert updated.status_code == 200
    assert updated.json()["theme_color"] == "#ABCDEF"
    assert http.patch("/api/settings", json={"theme_color": "red"}).status_code == 422
    assert http.patch("/api/settings", json={"title_model": "gpt-5.6-sol"}).status_code == 400
    assert http.patch(
        "/api/settings",
        json={"title_provider": "openai", "title_model": "missing"},
    ).status_code == 400
    costs = http.get("/api/costs/monthly").json()
    assert costs["currency"] == "USD" and costs["estimated"] is True
    assert costs["exclusions"] == ["tool_fees"]
    assert costs["months"][0]["usd"] == 0


def test_japanese_artifact_download(app_client):
    from urllib.parse import quote
    http, work, _ = app_client
    cid = http.post("/api/conversations", json={"workspace_id": "work"}).json()["id"]
    (work / "reviews").mkdir()
    for extension in ("docx", "md"):
        path = f"reviews/結果.{extension}"
        (work / path).write_bytes(b"artifact")
        response = http.get(f"/api/conversations/{cid}/download?path={quote(path, safe='')}")
        assert response.status_code == 200
        assert response.content == b"artifact"
        assert "attachment" in response.headers["content-disposition"]
        assert quote(f"結果.{extension}") in response.headers["content-disposition"]
