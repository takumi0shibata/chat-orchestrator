import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent_runner import RunManager
from app.config import AzureConnection, Deployment, Folder, RuntimeConfig, Settings
from app.main import create_app
from app.model_catalog import pricing_for
from app.provider_routes import ProviderRoutes, azure_base_url
from app.schemas import RunCreate
from app.storage import Store
from test_agent import Client, FakeSandbox, message


def connection():
    return AzureConnection(id="new", label="新リージョン", endpoint_env="TEST_AZURE_ENDPOINT", api_key_env="TEST_AZURE_KEY")


def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_AZURE_ENDPOINT", "https://new.openai.azure.com/")
    monkeypatch.setenv("TEST_AZURE_KEY", "new-private-key")
    settings = Settings(_env_file=None, openai_api_key=None,
                        azure_openai_endpoint="https://old.openai.azure.com/",
                        azure_openai_api_key="old-private-key", data_dir=tmp_path / "data",
                        http_proxy=None, https_proxy=None, all_proxy=None)
    work = tmp_path / "work"
    work.mkdir()
    config = RuntimeConfig(
        workspaces=[Folder(id="w", label="Work", path=work)], azure_connections=[connection()],
        azure_models=[
            Deployment(model="gpt-5.6-luna", deployment="shared-name"),
            Deployment(id="new-astra", model="gpt-6-astra", deployment="astra-actual", connection_id="new"),
            Deployment(id="new-sol", model="gpt-6-sol", deployment="shared-name", connection_id="new"),
            Deployment(id="new-luna", model="gpt-6-luna", deployment="luna-actual", connection_id="new"),
        ],
    )
    return settings, config


def test_environment_file_precedence_and_no_process_mutation(tmp_path, monkeypatch):
    backend_env, root_env = tmp_path / "backend.env", tmp_path / "root.env"
    backend_env.write_text("TEST_AZURE_KEY=backend\nTEST_AZURE_ENDPOINT=https://backend.example.com\n")
    root_env.write_text("TEST_AZURE_KEY=root\n")
    monkeypatch.delenv("TEST_AZURE_KEY", raising=False)
    monkeypatch.delenv("TEST_AZURE_ENDPOINT", raising=False)
    settings = Settings(_env_file=(backend_env, root_env))
    assert settings.credential_env("TEST_AZURE_KEY") == "root"
    assert settings.credential_env("TEST_AZURE_ENDPOINT") == "https://backend.example.com"
    import os
    assert "TEST_AZURE_KEY" not in os.environ
    monkeypatch.setenv("TEST_AZURE_KEY", "process")
    assert Settings(_env_file=(backend_env, root_env)).credential_env("TEST_AZURE_KEY") == "process"
    monkeypatch.delenv("TEST_AZURE_KEY")
    assert Settings(_env_file=None).credential_env("TEST_AZURE_KEY") is None


@pytest.mark.parametrize("endpoint", [
    "http://resource.example.com", "https://resource.example.com/openai/deployments/x",
    "https://resource.example.com/openai/v1/responses", "https://secret@resource.example.com",
    "https://resource.example.com?key=secret", "https://resource.example.com#fragment",
    "https:///missing", "https://resource.example.com:bad", "https://[broken",
])
def test_invalid_endpoint_is_a_sanitized_configuration_error(endpoint, monkeypatch):
    monkeypatch.setenv("TEST_AZURE_ENDPOINT", endpoint)
    monkeypatch.setenv("TEST_AZURE_KEY", "private-key")
    with pytest.raises(ValueError, match="connection new, variable TEST_AZURE_ENDPOINT") as error:
        ProviderRoutes(Settings(_env_file=None), RuntimeConfig(azure_connections=[connection()]))
    assert endpoint not in str(error.value)
    assert "private-key" not in str(error.value)


def test_endpoint_normalization():
    assert azure_base_url(" https://Resource.Example.com/ ", "x") == "https://resource.example.com/openai/v1"
    assert azure_base_url("https://resource.example.com/openai/v1/", "x") == "https://resource.example.com/openai/v1"


@pytest.mark.parametrize("config", [
    dict(azure_connections=[connection(), connection()]),
    dict(azure_connections=[connection().model_copy(update={"id": "default"})]),
    dict(azure_models=[Deployment(model="gpt-6-sol", deployment="sol", connection_id="missing")]),
    dict(azure_models=[Deployment(model="gpt-6-sol", deployment="same"), Deployment(model="gpt-6-luna", deployment="same")]),
])
def test_invalid_references_and_duplicates(config):
    with pytest.raises(ValidationError):
        RuntimeConfig(**config)


def test_available_models_and_same_deployment_names(tmp_path, monkeypatch, caplog):
    settings, config = configured(tmp_path, monkeypatch)
    routes = ProviderRoutes(settings, config)
    assert [m["id"] for m in routes.models("azure_openai")] == ["shared-name", "new-astra", "new-sol", "new-luna"]
    assert routes.resolve("azure_openai", "new-sol").deployment == "shared-name"
    assert routes.resolve("azure_openai", "shared-name").connection.api_key == "old-private-key"
    assert routes.resolve("azure_openai", "new-sol").connection.api_key == "new-private-key"
    assert pricing_for("azure_openai", "new-sol", config)[0] == "gpt-6-sol"
    monkeypatch.delenv("TEST_AZURE_KEY")
    missing = ProviderRoutes(Settings(_env_file=None, azure_openai_endpoint=settings.azure_openai_endpoint,
                                     azure_openai_api_key=settings.azure_openai_api_key), config)
    assert [m["id"] for m in missing.models("azure_openai")] == ["shared-name"]
    assert "TEST_AZURE_KEY" in caplog.text and "new-private-key" not in caplog.text
    with pytest.raises(ValueError, match="unavailable"):
        missing.resolve("azure_openai", "new-sol")


def test_chat_title_compaction_clients_and_binding(tmp_path, monkeypatch):
    async def scenario():
        settings, config = configured(tmp_path, monkeypatch)
        settings.compact_token_threshold = 1000
        from test_agent import shell
        clients = {
            "https://new.openai.azure.com/openai/v1": Client([[shell("ls")], [message()], [message()]], tokens=2000),
            "https://old.openai.azure.com/openai/v1": Client([[message()]]),
        }
        created = []
        closed = []
        def build(**kwargs):
            created.append(kwargs)
            client = clients[kwargs["base_url"]]
            async def close():
                closed.append(kwargs["base_url"])
            client.close = close
            return client
        monkeypatch.setattr("app.agent_runner.build_openai_client", build)
        store = Store(settings.data_dir)
        store.update_settings(title_provider="azure_openai", title_model="shared-name")
        manager = RunManager(settings, config, store, sandbox_factory=FakeSandbox)
        cid = store.create_conversation("w")["id"]
        request = RunCreate(conversation_id=cid, provider="azure_openai", model="new-sol", input="作業")
        run = manager.start(request)
        # Binding happens before asynchronous work or a context checkpoint.
        assert store.conversation(cid)["azure_connection_id"] == "new"
        await manager.tasks[run["id"]]
        await asyncio.gather(*manager.title_tasks)
        assert store.run(run["id"])["status"] == "completed"
        new, old = clients.values()
        assert all(call["model"] == "shared-name" for call in new.calls + new.compacts)
        assert new.compacts
        assert old.title_calls[0]["model"] == "shared-name"
        assert created[0]["api_key"] == "new-private-key"
        assert created[1]["api_key"] == "old-private-key"
        assert manager.client("azure_openai", "new-luna") is new
        store.update_settings(title_provider="azure_openai", title_model="new-luna")
        await manager.generate_title(run["id"], request)
        assert new.title_calls[0]["model"] == "luna-actual"
        next_run = manager.start(request.model_copy(update={"model": "new-astra"}))
        await manager.tasks[next_run["id"]]
        assert new.calls[-1]["model"] == "astra-actual"
        with pytest.raises(ValueError, match="新規チャット"):
            manager.start(request.model_copy(update={"model": "shared-name"}))
        assert len(created) == 2
        assert manager.redact("new-private-key old-private-key") == "[redacted] [redacted]"
        await manager.shutdown()
        assert sorted(closed) == sorted(clients)
    asyncio.run(scenario())


def test_endpoint_changes_block_history_but_key_rotation_does_not(tmp_path, monkeypatch):
    settings, config = configured(tmp_path, monkeypatch)
    store = Store(settings.data_dir)
    cid = store.create_conversation("w")["id"]
    request = RunCreate(conversation_id=cid, provider="azure_openai", model="new-sol", input="作業")
    run = store.create_run(request.model_dump(), azure_binding=("new", "https://new.openai.azure.com/openai/v1"))
    store.status(run["id"], "failed", "test")
    monkeypatch.setenv("TEST_AZURE_KEY", "rotated-key")
    rotated = Settings(_env_file=None, data_dir=settings.data_dir)
    manager = RunManager(rotated, config, store, client_factory=lambda *_: Client([]))
    manager.validate(request)
    monkeypatch.setenv("TEST_AZURE_ENDPOINT", "https://changed.openai.azure.com")
    manager = RunManager(Settings(_env_file=None), config, store, client_factory=lambda *_: Client([]))
    with pytest.raises(ValueError, match="新規チャット"):
        manager.validate(request)
    # The storage transaction also rejects a mismatched binding independently.
    with pytest.raises(ValueError, match="新規チャット"):
        store.create_run(request.model_dump(), azure_binding=("new", "https://changed.openai.azure.com/openai/v1"))
    assert len(store.runs(cid)) == 1


@pytest.mark.parametrize("legacy_available", [True, False])
def test_legacy_database_migration(tmp_path, monkeypatch, legacy_available):
    settings, config = configured(tmp_path, monkeypatch)
    store = Store(settings.data_dir)
    cid = store.create_conversation("w")["id"]
    history = [{"role": "user", "content": "previous"}]
    store.save_context(cid, history, "azure_openai", "shared-name")
    # Recreate the schema as it existed before the feature.
    with store.connect() as db:
        db.execute("ALTER TABLE conversations DROP COLUMN azure_connection_id")
        db.execute("ALTER TABLE conversations DROP COLUMN azure_endpoint")
    migrated = Store(settings.data_dir)
    assert migrated.conversation(cid)["azure_connection_id"] == "default"
    if not legacy_available:
        settings.azure_openai_endpoint = settings.azure_openai_api_key = None
    manager = RunManager(settings, config, migrated)
    assert migrated.conversation(cid)["context"] == history
    request = RunCreate(conversation_id=cid, provider="azure_openai", model="new-sol", input="続き")
    with pytest.raises(ValueError, match="新規チャット"):
        manager.validate(request)
    if legacy_available:
        assert migrated.conversation(cid)["azure_endpoint"] == "https://old.openai.azure.com/openai/v1"
        route = manager.routes.resolve("azure_openai", "shared-name")
        assert route.connection.id == "default"
        monkeypatch.setattr("app.agent_runner.build_openai_client", lambda **_: Client([]))
        manager.validate(request.model_copy(update={"model": "shared-name"}))
    else:
        assert migrated.conversation(cid)["azure_endpoint"] is None
        with pytest.raises(ValueError, match="新規チャット"):
            manager.validate(request.model_copy(update={"model": "shared-name"}))


def test_interrupted_legacy_run_is_bound_before_recovery(tmp_path, monkeypatch):
    settings, config = configured(tmp_path, monkeypatch)
    store = Store(settings.data_dir)
    cid = store.create_conversation("w")["id"]
    request = RunCreate(conversation_id=cid, provider="azure_openai", model="shared-name", input="previous")
    run = store.create_run(request.model_dump())
    store.status(run["id"], "failed", "interrupted")
    with store.connect() as db:
        db.execute("ALTER TABLE conversations DROP COLUMN azure_connection_id")
        db.execute("ALTER TABLE conversations DROP COLUMN azure_endpoint")
    migrated = Store(settings.data_dir)
    manager = RunManager(settings, config, migrated)
    assert migrated.conversation(cid)["azure_connection_id"] == "default"
    assert migrated.conversation(cid)["azure_endpoint"] == "https://old.openai.azure.com/openai/v1"
    with pytest.raises(ValueError, match="change provider"):
        manager.validate(request.model_copy(update={"provider": "openai", "model": "gpt-6-sol"}))
    with pytest.raises(ValueError, match="新規チャット"):
        manager.validate(request.model_copy(update={"model": "new-sol"}))


def test_rejected_run_does_not_bind_conversation(tmp_path):
    import sqlite3
    store = Store(tmp_path)
    cid = store.create_conversation("w")["id"]
    request = RunCreate(conversation_id=cid, provider="azure_openai", model="sol", input="work")
    store.create_run(request.model_dump())
    with pytest.raises(sqlite3.IntegrityError):
        store.create_run(request.model_dump(), azure_binding=("new", "https://new.openai.azure.com/openai/v1"))
    assert store.conversation(cid)["azure_connection_id"] is None
    assert store.conversation(cid)["provider"] is None


def test_config_api_works_without_legacy_credentials_and_hides_secrets(tmp_path, monkeypatch):
    settings, config = configured(tmp_path, monkeypatch)
    settings.azure_openai_api_key = settings.azure_openai_endpoint = None
    monkeypatch.setattr(Settings, "load_runtime", lambda _: config)
    clients = {}
    def build(**kwargs):
        client = clients.setdefault(kwargs["base_url"], Client([[message()]]))
        return client
    monkeypatch.setattr("app.agent_runner.build_openai_client", build)
    app = create_app(settings, lambda s, c, st: RunManager(s, c, st, sandbox_factory=FakeSandbox))
    with TestClient(app) as http:
        azure = http.get("/api/config").json()["providers"][1]
        assert azure["enabled"]
        assert [m["id"] for m in azure["models"]] == ["new-astra", "new-sol", "new-luna"]
        assert azure["models"][1]["connection_label"] == "新リージョン"
        assert http.patch("/api/settings", json={"title_provider": "azure_openai", "title_model": "new-luna"}).status_code == 200
        cid = http.post("/api/conversations", json={"workspace_id": "w"}).json()["id"]
        assert http.post("/api/runs", json={"conversation_id": cid, "provider": "azure_openai", "model": "new-sol", "input": "test"}).status_code == 200
        responses = [http.get("/api/config").json(), http.get("/api/conversations").json(),
                     http.get(f"/api/conversations/{cid}").json(),
                     http.patch(f"/api/conversations/{cid}", json={"pinned": True}).json()]
        assert responses[2]["azure_connection_id"] == "new"
        public = json.dumps(responses)
        assert "new-private-key" not in public
        assert "https://new.openai.azure.com" not in public
        assert "azure_endpoint" not in public


def test_failed_title_redacts_connection_keys(tmp_path, monkeypatch, caplog):
    async def scenario():
        settings, config = configured(tmp_path, monkeypatch)
        store = Store(settings.data_dir)
        store.update_settings(title_provider="azure_openai", title_model="new-luna")
        client = Client([])
        async def fail(**kwargs):
            raise ValueError("server returned new-private-key")
        client.create = fail
        monkeypatch.setattr("app.agent_runner.build_openai_client", lambda **_: client)
        manager = RunManager(settings, config, store)
        cid = store.create_conversation("w")["id"]
        request = RunCreate(conversation_id=cid, input="作業")
        run = store.create_run(request.model_dump())
        await manager.generate_title(run["id"], request)
        await manager.shutdown()
    asyncio.run(scenario())
    assert "new-private-key" not in caplog.text
    assert "[redacted]" in caplog.text
