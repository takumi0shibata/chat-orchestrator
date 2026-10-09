import asyncio
import copy
import json
import shlex
from types import SimpleNamespace as NS

import pytest

from app.agent_runner import RunManager
from app.config import Deployment, Folder, MCPServer, RuntimeConfig, Settings, Skill
from app.patch_tool import apply_operation
from app.sandbox import CommandTimeoutError
from app.schemas import Approval, RunCreate
from app.storage import Store


class Stream:
    def __init__(self, output, tokens=10):
        self.output, self.tokens, self.closed = output, tokens, False

    async def __aiter__(self):
        for i in self.output:
            if i["type"] == "reasoning":
                for index, part in enumerate(i.get("summary", [])):
                    yield NS(
                        type="response.reasoning_summary_text.delta",
                        delta=part["text"],
                        item_id=i["id"],
                        summary_index=index,
                    )
            if i["type"] == "message":
                yield NS(type="response.output_item.added", item=i)
                yield NS(
                    type="response.output_text.delta",
                    delta=i["content"][0]["text"],
                    item_id=i["id"],
                )
                yield NS(type="response.output_item.done", item=i)
        yield NS(
            type="response.completed",
            response=NS(
                output=self.output, id="resp_1", usage={"input_tokens": self.tokens}
            ),
        )

    async def close(self):
        self.closed = True


class Client:
    def __init__(self, outputs, tokens=10):
        self.responses = self
        self.outputs, self.calls, self.compacts, self.streams = (
            list(outputs),
            [],
            [],
            [],
        )
        self.title_calls = []
        self.tokens = tokens

    async def create(self, **kwargs):
        if not kwargs.get("stream"):
            self.title_calls.append(copy.deepcopy(kwargs))
            return NS(
                output_text="編集タスク",
                output=[message()],
                id="title_resp_1",
                usage={"input_tokens": 12, "output_tokens": 3},
            )
        self.calls.append(copy.deepcopy(kwargs))
        result = Stream(self.outputs.pop(0), self.tokens)
        self.streams.append(result)
        return result

    async def compact(self, **kwargs):
        self.compacts.append(copy.deepcopy(kwargs))
        return NS(
            id="compact_resp_1",
            usage={"input_tokens": 100, "output_tokens": 20},
            output=[
                {"type": "compaction", "id": "cmp_1", "encrypted_content": "encrypted"}
            ]
        )

    async def close(self):
        pass


class FakeSandbox:
    instances = []

    def __init__(self, *args):
        self.closed = False
        self.commands = []
        self.skills = args[3]
        self.workspace = args[1].path
        self.patches = []
        self.instances.append(self)

    async def view_image(self, path):
        if path != "plot.png":
            return dict(status="failed", output=f"Image not found: {path}", path=path)
        return dict(status="completed", output="Image /workspace/plot.png (2x1 image/png)",
                    path="/workspace/plot.png", mime="image/png", width=2, height=1,
                    original_width=2, original_height=1, thumbnail="data:image/jpeg;base64,AA==",
                    image_url="data:image/png;base64,iVBORw0KGgo=")

    async def apply_patch(self, operation):
        self.patches.append(operation)
        return apply_operation(str(self.workspace), operation)

    async def start(self):
        pass

    async def close(self):
        self.closed = True

    async def execute(self, command, emit, timeout):
        self.commands.append(command)
        await emit("stdout", "result")
        return dict(
            stdout="result",
            stderr="",
            outcome=dict(type="exit", exit_code=1 if command == "fail" else 0),
        )


def shell(command, call="call_1"):
    return {
        "type": "shell_call",
        "id": "shell_" + call,
        "call_id": call,
        "action": {"commands": [command], "max_output_length": 4096},
    }


def message():
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "完了", "annotations": []}],
    }


def setup(tmp_path, outputs, provider="openai", sandbox=FakeSandbox, **settings):
    workspace = tmp_path / "work"
    workspace.mkdir(exist_ok=True)
    s = Settings(_env_file=None, data_dir=tmp_path / "data", **settings)
    cfg = RuntimeConfig(
        workspaces=[Folder(id="work", label="Work", path=workspace)],
        azure_models=[Deployment(model="gpt-6-astra", deployment="azure-astra")],
    )
    store = Store(s.data_dir)
    cid = store.create_conversation("work")["id"]
    client = Client(outputs)
    manager = RunManager(
        s, cfg, store, client_factory=lambda *_: client, sandbox_factory=sandbox
    )
    request = RunCreate(
        conversation_id=cid,
        input="編集してください",
        provider=provider,
        model="azure-astra" if provider == "azure_openai" else "gpt-5.6-sol",
    )
    return manager, store, client, request


def run_environment(call):
    """The latest run environment message in a request's input."""
    prefix = "Run environment for the next user message"
    message = next(
        item for item in reversed(call["input"])
        if item.get("role") == "developer" and item["content"][0]["text"].startswith(prefix)
    )
    return json.loads(message["content"][0]["text"].split("): ", 1)[1])


@pytest.mark.parametrize("provider", ["openai", "azure_openai"])
@pytest.mark.parametrize("host_system, host_os", [("Darwin", "macOS"), ("Linux", "Linux")])
def test_fixed_sandbox_instructions_survive_rounds_and_compaction(
    tmp_path, monkeypatch, provider, host_system, host_os
):
    monkeypatch.setattr("app.agent_runner.platform.system", lambda: host_system)

    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [[shell("ls")], [message()]], provider,
            compact_token_threshold=1000,
        )
        workspace = tmp_path / "work space's 資料"
        workspace.mkdir()
        manager.config.workspaces[0].path = workspace.resolve()
        client.tokens = 1100
        run = manager.start(request)
        await manager.tasks[run["id"]]

        assert store.run(run["id"])["status"] == "completed"
        assert len(client.calls) == 2
        assert len(client.compacts) == 1
        events = store.events(run["id"])
        start = next(e for e in events if e["type"] == "compaction_start")
        done = next(e for e in events if e["type"] == "compaction")
        assert start["seq"] < done["seq"]
        assert start["data"] == {"tokens": 1100, "threshold": 1000}
        assert done["data"]["tokens_before"] == 1100 and done["data"]["threshold"] == 1000
        instructions = client.calls[0]["instructions"]
        assert all(call["instructions"] == instructions for call in client.calls)
        assert client.compacts[0]["instructions"] == instructions
        for requirement in (
            "even if the user requests changes",
            "pip install", "brew install", "curl installers",
            "online or offline",
            "Host installs do not change the sandbox runtime",
            "Never delegate environment changes, image rebuilds or unsupported computation",
            "Use existing alternatives; if none suffice",
            "Shell cannot access the internet, DNS or host network services",
            "Do not download, probe, retry connectivity failures or repair networking",
            "separate provider-side network path",
            "you cannot control it or read its output",
            "Request only inputs usable with installed tools",
            "end with an explicit pending request",
            "verify the actual files in /workspace",
        ):
            assert requirement in instructions
        environment = run_environment(client.calls[1])
        assert environment["host_os"] == host_os
        assert environment["host_workspace_path"] == str(workspace.resolve())
        assert environment["sandbox_workspace_path"] == "/workspace"
        assert shlex.split(environment["host_workspace_cd"]) == ["cd", str(workspace.resolve())]
        assert environment["web_search_enabled"] is False
        assert environment["remote_mcp_servers"] == []
        assert environment["resource_directories"] == []
        assert environment["available_skills"] == []
        assert environment["explicit_skill_ids"] == []
        await manager.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["openai", "azure_openai"])
def test_run_instructions_refresh_selected_external_tools_and_resources(
    tmp_path, monkeypatch, provider
):
    token = "private-mcp-test-token"
    monkeypatch.setenv("TEST_MCP_TOKEN", token)
    selections = [
        (False, False, False),
        (True, False, True),
        (False, True, False),
        (True, True, True),
        (False, False, False),
    ]

    async def scenario():
        manager, _, client, request = setup(
            tmp_path, [[message()] for _ in selections], provider,
        )
        manager.config.mcp_servers = [
            MCPServer(
                id="chosen", label="Chosen", url="https://chosen.example/mcp",
                allowed_tools=["search", "fetch"], authorization_env="TEST_MCP_TOKEN",
            ),
            MCPServer(
                id="unused", label="Unused", url="https://unused.example/mcp",
                allowed_tools=["other"],
            ),
        ]
        resources = tmp_path / "models"
        resources.mkdir()
        manager.config.resources = [Folder(id="models", label="Models", path=resources)]

        for web_search, use_mcp, use_resources in selections:
            request.web_search = web_search
            request.mcp_ids = ["chosen"] if use_mcp else []
            request.resource_ids = ["models"] if use_resources else []
            run = manager.start(request)
            await manager.tasks[run["id"]]
            call = client.calls[-1]
            environment = run_environment(call)
            assert environment["web_search_enabled"] is web_search
            assert environment["remote_mcp_servers"] == (
                [{"id": "chosen", "allowed_tools": ["search", "fetch"]}] if use_mcp else []
            )
            assert environment["resource_directories"] == (
                ["/resources/models"] if use_resources else []
            )
            assert any(tool["type"] == "web_search" for tool in call["tools"]) is web_search
            assert [tool["server_label"] for tool in call["tools"] if tool["type"] == "mcp"] == (
                ["chosen"] if use_mcp else []
            )
            assert token not in call["instructions"]
            assert "TEST_MCP_TOKEN" not in call["instructions"]
            assert "https://chosen.example/mcp" not in call["instructions"]
            assert "unused" not in call["instructions"]
        await manager.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["openai", "azure_openai"])
def test_all_skills_available_and_explicit_selection_refreshes_after_compaction(tmp_path, provider):
    async def scenario():
        manager, store, client, request = setup(
            tmp_path,
            [[shell("ls")], [message()], [message()], [message()], [message()]],
            provider,
            compact_token_threshold=1000,
        )
        for sid, name, description in (
            ("review", "academic-writing", "Review paper drafts"),
            ("brief", "morning-brief", "Prepare a morning briefing"),
        ):
            folder = tmp_path / sid
            folder.mkdir()
            (folder / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {description}\n---\n"
                "BODY_ONLY_READ_WHEN_NEEDED\n"
            )
            manager.config.skills.append(Skill(id=sid, label=name, path=folder))
        catalog = [
            {"id": "review", "name": "academic-writing", "description": "Review paper drafts", "path": "/skills/review"},
            {"id": "brief", "name": "morning-brief", "description": "Prepare a morning briefing", "path": "/skills/brief"},
        ]
        client.tokens = 1100
        for ids in ([], ["brief", "review"], ["review"], []):
            request.skill_ids = ids
            calls_before = len(client.calls)
            compacts_before = len(client.compacts)
            run = manager.start(request)
            await manager.tasks[run["id"]]
            assert store.run(run["id"])["status"] == "completed"
            assert store.run(run["id"])["request"]["skill_ids"] == ids
            assert [skill.id for skill in FakeSandbox.instances[-1].skills] == ["review", "brief"]
            calls = client.calls[calls_before:]
            compacts = client.compacts[compacts_before:]
            assert compacts
            for call in [*calls, *compacts]:
                environment = run_environment(call)
                assert environment["available_skills"] == catalog
                assert environment["explicit_skill_ids"] == ids
                assert "smallest relevant set" in call["instructions"]
                assert "read and apply them even when their descriptions" in call["instructions"]
                assert "BODY_ONLY_READ_WHEN_NEEDED" not in str(call)
                assert call["instructions"] == calls[0]["instructions"]
            for call in calls:
                assert call["tools"][0]["environment"]["skills"] == [
                    {key: skill[key] for key in ("name", "description", "path")}
                    for skill in catalog
                ]
        await manager.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("ids", [["unknown"], ["review", "review"]])
def test_explicit_skills_reject_unknown_and_duplicate_ids(tmp_path, ids):
    manager, _, client, request = setup(tmp_path, [[message()]])
    folder = tmp_path / "skill"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: review\ndescription: Review drafts\n---\nReview.")
    manager.config.skills = [Skill(id="review", label="Review", path=folder)]
    request.skill_ids = ids
    before = len(FakeSandbox.instances)
    with pytest.raises(ValueError, match="Unknown or duplicate configured ID"):
        manager.start(request)
    assert len(FakeSandbox.instances) == before
    assert client.calls == []


@pytest.mark.parametrize("provider", ["openai", "azure_openai"])
def test_input_handoff_ends_turn_and_next_run_can_read_shared_file(tmp_path, provider):
    class InputSandbox(FakeSandbox):
        def __init__(self, settings, workspace, *args):
            super().__init__(settings, workspace, *args)
            self.workspace = workspace.path

        async def execute(self, command, emit, timeout):
            assert command == "cat /workspace/data.csv"
            self.commands.append(command)
            output = (self.workspace / "data.csv").read_text()
            await emit("stdout", output)
            return dict(stdout=output, stderr="", outcome=dict(type="exit", exit_code=0))

    async def scenario():
        handoff = message()
        handoff["content"][0]["text"] = "ホスト端末で共有フォルダに data.csv を取得し、完了を返信してください。入力待ちです。"
        manager, store, client, request = setup(
            tmp_path, [[handoff], [shell("cat /workspace/data.csv")], [message()]],
            provider, sandbox=InputSandbox,
        )
        request.input = "外部のCSVを取得して分析してください"
        first = manager.start(request)
        await manager.tasks[first["id"]]
        assert store.run(first["id"])["status"] == "completed"
        assert FakeSandbox.instances[-1].closed
        assert FakeSandbox.instances[-1].commands == []
        assert store.conversation(request.conversation_id)["context"][-1] == handoff

        # The user's host download appears in the shared directory between runs.
        contents = "value\n42\n"
        (manager.config.workspaces[0].path / "data.csv").write_text(contents)
        request.input = "取得しました。続けてください"
        second = manager.start(request)
        await manager.tasks[second["id"]]
        assert store.run(second["id"])["status"] == "completed"
        assert handoff in client.calls[1]["input"]
        assert client.calls[1]["input"][-1]["content"][0]["text"] == request.input
        assert client.calls[2]["input"][-1]["output"][0]["stdout"] == contents
        assert FakeSandbox.instances[-1].closed
        await manager.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["openai", "azure_openai"])
def test_shell_recovery_and_full_context(tmp_path, provider):
    async def scenario():
        reasoning = {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [],
            "encrypted_content": "private-encrypted",
        }
        m, store, c, req = setup(
            tmp_path,
            [[reasoning, shell("fail")], [shell("repair", "call_2")], [message()]],
            provider,
        )
        run = m.start(req)
        await m.tasks[run["id"]]
        assert store.run(run["id"])["status"] == "completed"
        assert len(c.calls) == 3
        assert c.calls[0]["model"] == req.model
        assert c.calls[0]["store"] is False
        assert reasoning in c.calls[1]["input"]
        assert c.calls[1]["input"][-1]["output"][0]["outcome"]["exit_code"] == 1
        assert c.calls[1]["input"][-1]["max_output_length"] == 4096
        assert "skills" in c.calls[0]["tools"][0]["environment"]
        assert all(s.closed for s in c.streams)
        assert FakeSandbox.instances[-1].closed
        assert not any("private-encrypted" in str(e) for e in store.events(run["id"]))
        assert store.conversation(req.conversation_id)["context"][-1] == message()

    asyncio.run(scenario())


def test_compaction(tmp_path):
    async def scenario():
        m, store, c, req = setup(
            tmp_path, [[shell("ls")], [message()]], compact_token_threshold=1000
        )
        c.tokens = 1100
        r = m.start(req)
        await m.tasks[r["id"]]
        assert len(c.compacts) == 1
        assert c.calls[1]["input"][0]["type"] == "compaction"
        assert store.run(r["id"])["status"] == "completed"

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["openai", "azure_openai"])
@pytest.mark.parametrize("restart", [False, True])
def test_compaction_between_completed_turns(tmp_path, provider, restart):
    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [[message()], [message()], [message()]], provider,
            compact_token_threshold=1000,
        )
        client.tokens = 1100
        first = manager.start(request)
        await manager.tasks[first["id"]]
        await asyncio.gather(*manager.title_tasks)
        assert client.compacts == []
        assert store.context_tokens(request.conversation_id) == 1100

        if restart:
            await manager.shutdown()
            store = Store(manager.settings.data_dir)
            manager = RunManager(
                manager.settings, manager.config, store,
                client_factory=lambda *_: client, sandbox_factory=FakeSandbox,
            )
        client.tokens = 10
        request.input = "追加の質問"
        second = manager.start(request)
        await manager.tasks[second["id"]]
        assert store.run(second["id"])["status"] == "completed"
        assert len(client.compacts) == 1
        assert client.compacts[0]["model"] == request.model
        assert message() in client.compacts[0]["input"]
        assert client.compacts[0]["input"][-1]["content"][0]["text"] == request.input
        assert client.calls[1]["input"][0]["type"] == "compaction"

        third = manager.start(request)
        await manager.tasks[third["id"]]
        assert len(client.compacts) == 1
        assert len(client.title_calls) == 1
    asyncio.run(scenario())


def test_compacted_context_is_not_compacted_again_after_api_failure(tmp_path):
    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [[message()], [message()]], compact_token_threshold=1000
        )
        client.tokens = 1100
        first = manager.start(request)
        await manager.tasks[first["id"]]
        await asyncio.gather(*manager.title_tasks)

        original_create = client.create
        async def fail(**kwargs):
            raise RuntimeError("Model unavailable after compaction")
        client.create = fail
        second = manager.start(request)
        await manager.tasks[second["id"]]
        assert store.run(second["id"])["status"] == "failed"
        assert len(client.compacts) == 1
        assert store.context_tokens(request.conversation_id) == 20

        await manager.shutdown()
        client.create, client.tokens = original_create, 10
        manager = RunManager(
            manager.settings, manager.config, Store(manager.settings.data_dir),
            client_factory=lambda *_: client, sandbox_factory=FakeSandbox,
        )
        third = manager.start(request)
        await manager.tasks[third["id"]]
        assert manager.store.run(third["id"])["status"] == "completed"
        assert len(client.compacts) == 1
        assert client.calls[-1]["input"][0]["type"] == "compaction"
    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["openai", "azure_openai"])
def test_configured_output_token_limits(tmp_path, provider):
    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [[message()]], provider,
            max_model_output_tokens=8192, max_title_output_tokens=512,
        )
        store.update_settings(title_provider=provider, title_model=request.model)
        run = manager.start(request)
        await manager.tasks[run["id"]]
        await asyncio.gather(*manager.title_tasks)
        assert client.calls[0]["max_output_tokens"] == 8192
        assert client.title_calls[0]["max_output_tokens"] == 512
    asyncio.run(scenario())


@pytest.mark.parametrize("event_type", ["response.incomplete", "response.failed"])
def test_interrupted_response_records_usage_and_preserves_partial_output(tmp_path, event_type):
    class InterruptedStream(Stream):
        async def __aiter__(self):
            yield NS(type="response.output_text.delta", delta="途中の回答", item_id="partial")
            yield NS(
                type=event_type,
                response=NS(
                    id="interrupted_response", output=[],
                    usage={"input_tokens": 100, "output_tokens": 64},
                    incomplete_details={"reason": "max_output_tokens"},
                ),
            )

    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [], max_model_output_tokens=64
        )
        original_create = client.create
        stream = InterruptedStream([])
        async def create(**kwargs):
            if not kwargs.get("stream"):
                return await original_create(**kwargs)
            client.calls.append(copy.deepcopy(kwargs))
            return stream
        client.create = create
        run = manager.start(request)
        await manager.tasks[run["id"]]
        await asyncio.gather(*manager.title_tasks)
        assert store.run(run["id"])["status"] == "failed"
        assert len(client.calls) == 1
        assert stream.closed
        assert "途中の回答" in str(store.conversation(request.conversation_id)["context"])
        with store.connect() as connection:
            usage = connection.execute(
                "SELECT input_tokens,output_tokens FROM llm_costs WHERE response_id='interrupted_response'"
            ).fetchone()
        assert tuple(usage) == (100, 64)
    asyncio.run(scenario())


def test_project_instructions_are_reloaded_without_persisting(tmp_path):
    async def scenario():
        m, store, c, req = setup(
            tmp_path, [[shell("check instructions")], [message()], [message()]]
        )
        instruction_file = m.config.workspaces[0].path / "AGENTS.md"
        instruction_file.write_text("First instruction")

        first = m.start(req)
        await m.tasks[first["id"]]
        first_message = c.calls[0]["input"][0]
        assert first_message["role"] == "user"
        assert "First instruction" in first_message["content"][0]["text"]
        assert "First instruction" in c.calls[1]["input"][0]["content"][0]["text"]
        assert "First instruction" not in str(store.conversation(req.conversation_id)["context"])
        loaded = [
            event
            for event in store.events(first["id"])
            if event["type"] == "project_instructions"
        ]
        assert loaded[0]["data"]["filename"] == "AGENTS.md"

        instruction_file.write_text("Second instruction")
        second = m.start(req)
        await m.tasks[second["id"]]
        second_message = c.calls[2]["input"][0]
        assert "Second instruction" in second_message["content"][0]["text"]
        assert "First instruction" not in second_message["content"][0]["text"]
        assert "Second instruction" not in str(store.conversation(req.conversation_id)["context"])

    asyncio.run(scenario())


def test_mcp_approval_is_run_scoped(tmp_path):
    async def scenario():
        m, store, c, req = setup(
            tmp_path,
            [
                [
                    dict(
                        type="mcp_approval_request",
                        id="approval1",
                        name="search",
                        server_label="research",
                        arguments="{}",
                    )
                ],
                [message()],
            ],
        )
        m.config.mcp_servers = [
            MCPServer(
                id="research",
                label="Research",
                url="https://example.com/mcp",
                allowed_tools=["search"],
            )
        ]
        req.mcp_ids = ["research"]
        run = m.start(req)
        for _ in range(100):
            if (run["id"], "approval1") in m.approvals:
                break
            await asyncio.sleep(0.01)
        with pytest.raises(ValueError):
            m.approve("wrong", Approval(request_id="approval1", approve=True))
        m.approve(run["id"], Approval(request_id="approval1", approve=False))
        await m.tasks[run["id"]]
        assert c.calls[1]["input"][-1] == dict(
            type="mcp_approval_response", approval_request_id="approval1", approve=False
        )
        assert next(t for t in c.calls[0]["tools"] if t["type"] == "mcp")["require_approval"] == "always"
        assert store.run(run["id"])["status"] == "completed"

    asyncio.run(scenario())


def test_stop_kills_execution(tmp_path):
    class Blocking(FakeSandbox):
        async def execute(self, *args):
            await asyncio.Event().wait()

    async def scenario():
        m, store, c, req = setup(tmp_path, [[shell("sleep 100")]], sandbox=Blocking)
        r = m.start(req)
        for _ in range(100):
            if store.run(r["id"])["status"] == "command_running":
                break
            await asyncio.sleep(0.01)
        await m.stop(r["id"])
        assert store.run(r["id"])["status"] == "stopped"
        assert Blocking.instances[-1].closed
        context = store.conversation(req.conversation_id)["context"]
        assert context[0]["role"] == "developer"
        assert context[1]["content"][0]["text"] == req.input
        assert "sleep 100" in str(context)
        assert not any(i.get("type") == "shell_call" for i in context)

    asyncio.run(scenario())


def test_same_workspace_serialized(tmp_path):
    class Serial(FakeSandbox):
        running = 0
        max_running = 0

        async def start(self):
            Serial.running += 1
            Serial.max_running = max(Serial.max_running, Serial.running)
            await asyncio.sleep(0.03)

        async def close(self):
            if not self.closed:
                Serial.running -= 1
            self.closed = True

    async def scenario():
        m, store, c, req = setup(tmp_path, [[message()], [message()]], sandbox=Serial)
        second = req.model_copy(
            update={"conversation_id": store.create_conversation("work")["id"]}
        )
        a = m.start(req)
        b = m.start(second)
        await asyncio.gather(m.tasks[a["id"]], m.tasks[b["id"]])
        assert Serial.max_running == 1
        assert Serial.running == 0

    asyncio.run(scenario())


def test_unknown_or_unsupported_models_rejected(tmp_path):
    m, _, _, req = setup(tmp_path, [])
    m.validate(req.model_copy(update={"model": "gpt-5.6-luna", "reasoning_effort": "high"}))
    with pytest.raises(ValueError):
        m.validate(req.model_copy(update={"model": "other"}))
    with pytest.raises(ValueError):
        m.validate(
            req.model_copy(update={"model": "gpt-6-astra", "reasoning_effort": "none"})
        )


def test_title_model_defaults_and_azure_fallback(tmp_path):
    manager, store, _, _ = setup(tmp_path, [])
    assert manager.title_selection()["title_model"] == "gpt-6-luna"
    manager.config.azure_models.append(
        Deployment(model="gpt-5.6-luna", deployment="azure-old-luna")
    )
    store.update_settings(title_provider="azure_openai", title_model="azure-old-luna")
    assert manager.title_selection()["title_model"] == "azure-old-luna"

    # A missing Azure deployment falls back within Azure's GPT-5.6 family.
    store.update_settings(title_provider="azure_openai", title_model="missing")
    assert manager.title_selection().items() >= {
        "title_provider": "azure_openai",
        "title_model": "azure-old-luna",
        "theme_color": "#25262A",
    }.items()

    manager.config.azure_models.append(
        Deployment(model="gpt-6-luna", deployment="azure-new-luna")
    )
    manager.validate_title_selection("azure_openai", "azure-new-luna")
    store.update_settings(title_provider="azure_openai", title_model="azure-new-luna")
    assert manager.title_selection()["title_model"] == "azure-new-luna"


def test_model_round_limit(tmp_path):
    async def scenario():
        m, store, c, req = setup(tmp_path, [[shell("ls")]], max_model_rounds=1)
        r = m.start(req)
        await m.tasks[r["id"]]
        assert store.run(r["id"])["status"] == "failed"
        assert FakeSandbox.instances[-1].closed

    asyncio.run(scenario())


def test_200_files_not_injected_into_model_context(tmp_path):
    async def scenario():
        manager, store, client, request = setup(tmp_path, [[shell("ls")], [message()]])
        for i in range(200):
            (tmp_path / "work" / f"{i}.txt").write_text("UNREAD_FILE_SENTINEL")
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert "UNREAD_FILE_SENTINEL" not in str(client.calls)
        assert store.run(run["id"])["status"] == "completed"

    asyncio.run(scenario())


def test_server_restart_cleans_interrupted_run(tmp_path, monkeypatch):
    async def scenario():
        manager, store, client, request = setup(tmp_path, [])
        run = store.create_run(request.model_dump())
        calls = []

        async def cleanup(*args, **kwargs):
            calls.append(args)

        monkeypatch.setattr("app.agent_runner.docker", cleanup)
        await manager.recover()
        assert store.run(run["id"])["status"] == "failed"
        assert calls == [("rm", "-f", "chat-agent-" + run["id"])]
        assert not store.needs_cleanup(run["id"])

    asyncio.run(scenario())


def test_cleanup_failure_blocks_workspace_then_recovers(tmp_path, monkeypatch):
    class FailingClose(FakeSandbox):
        async def close(self):
            raise RuntimeError("daemon disconnected")

    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [[message()]], sandbox=FailingClose
        )
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert store.run(run["id"])["status"] == "failed"
        assert store.needs_cleanup(run["id"])
        with pytest.raises(ValueError, match="blocked"):
            manager.start(request)

        async def cleanup(*args, **kwargs):
            pass

        monkeypatch.setattr("app.agent_runner.docker", cleanup)
        recovered = RunManager(
            manager.settings, manager.config, store, client_factory=lambda *_: client
        )
        await recovered.recover()
        assert not store.needs_cleanup(run["id"])
        assert not recovered.poisoned_workspaces

    asyncio.run(scenario())


def test_repeated_stop_waits_for_cleanup(tmp_path):
    class SlowClose(FakeSandbox):
        async def execute(self, *args):
            await asyncio.Event().wait()

        async def close(self):
            await asyncio.sleep(0.05)
            self.closed = True

    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [[shell("sleep 100")]], sandbox=SlowClose
        )
        run = manager.start(request)
        while store.run(run["id"])["status"] != "command_running":
            await asyncio.sleep(0.01)
        await asyncio.gather(manager.stop(run["id"]), manager.stop(run["id"]))
        assert SlowClose.instances[-1].closed
        assert store.run(run["id"])["status"] == "stopped"
        assert not next(iter(manager.locks.values())).locked()

    asyncio.run(scenario())


def test_response_events_identify_final_messages(tmp_path):
    async def scenario():
        m, store, _, req = setup(tmp_path, [[message(), shell("ls")], [message()]])
        run = m.start(req)
        await m.tasks[run["id"]]
        events = store.events(run["id"])
        responses = [e["data"] for e in events if e["type"] == "response"]
        assert [(e["round"], e["continues"], e["final_item_ids"]) for e in responses] == [
            (1, True, []), (2, False, ["msg_1"])
        ]
        assert [e["data"]["round"] for e in events if e["type"] == "text_delta"] == [1, 2]
    asyncio.run(scenario())


def test_reasoning_summary_streams_and_conversation_shares_cache_key(tmp_path):
    async def scenario():
        reasoning = {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [
                {"type": "summary_text", "text": "**Plan**"},
                {"type": "summary_text", "text": "Check files"},
            ],
            "encrypted_content": "private-encrypted",
        }
        manager, store, client, request = setup(
            tmp_path, [[reasoning, shell("ls")], [message()]]
        )
        run = manager.start(request)
        await manager.tasks[run["id"]]
        events = store.events(run["id"])
        assert [
            (e["data"]["item_id"], e["data"]["summary_index"], e["data"]["round"], e["data"]["text"])
            for e in events if e["type"] == "reasoning_delta"
        ] == [("rs_1", 0, 1, "**Plan**"), ("rs_1", 1, 1, "Check files")]
        assert [call["reasoning"] for call in client.calls] == [
            {"effort": "medium", "summary": "auto"}
        ] * 2
        assert {call["prompt_cache_key"] for call in client.calls} == {
            request.conversation_id
        }

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "summary, effort, expected",
    [
        ("off", "medium", {"effort": "medium"}),
        ("detailed", "high", {"effort": "high", "summary": "detailed"}),
        ("auto", "none", {"effort": "none"}),
    ],
)
def test_reasoning_summary_setting(tmp_path, summary, effort, expected):
    async def scenario():
        manager, _, client, request = setup(
            tmp_path, [[message()]], reasoning_summary=summary
        )
        request = request.model_copy(
            update={"model": "gpt-6-sol", "reasoning_effort": effort}
        )
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert client.calls[0]["reasoning"] == expected

    asyncio.run(scenario())


def test_final_phase_is_emitted_before_text(tmp_path):
    async def scenario():
        final = {**message(), "phase": "final_answer"}
        manager, store, _, request = setup(tmp_path, [[final]])
        run = manager.start(request)
        await manager.tasks[run["id"]]
        events = store.events(run["id"])
        phase = next(e for e in events if e["type"] == "message_phase")
        delta = next(e for e in events if e["type"] == "text_delta")
        assert phase["seq"] < delta["seq"]
        assert phase["data"] == {
            "item_id": final["id"], "round": 1, "phase": "final_answer"
        }
        assert len([e for e in events if e["type"] == "message_phase"]) == 1

    asyncio.run(scenario())


def test_builtin_tool_commentary_is_not_a_final_message(tmp_path):
    async def scenario():
        before = {**message(), "id": "before", "phase": "commentary"}
        after = {**message(), "id": "after"}
        output = [before, {"id": "web", "type": "web_search_call"}, after]
        m, store, _, req = setup(tmp_path, [output])
        run = m.start(req)
        await m.tasks[run["id"]]
        response = next(e["data"] for e in store.events(run["id"]) if e["type"] == "response")
        assert response["continues"] is False
        assert response["final_item_ids"] == ["after"]
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["timeout", "api", "disconnect", "startup"])
def test_failed_run_preserves_instruction_and_partial_history(tmp_path, failure):
    class FailingSandbox(FakeSandbox):
        async def start(self):
            if failure == "startup":
                raise RuntimeError("Sandbox unavailable")

        async def execute(self, command, emit, timeout):
            if command == "slow":
                await emit("stdout", "partial write")
                raise CommandTimeoutError(timeout)
            return await super().execute(command, emit, timeout)

    async def scenario():
        batch = shell("edited once")
        batch["action"]["commands"] += ["slow", "never executed"]
        m, store, client, req = setup(tmp_path, [[batch]], sandbox=FailingSandbox)
        original_create = client.create
        if failure == "api":
            async def create(**kwargs):
                raise RuntimeError("Model unavailable")
            client.create = create
        elif failure == "disconnect":
            class BrokenStream(Stream):
                async def __aiter__(self):
                    yield NS(type="response.output_text.delta", delta="途中経過", item_id="partial")
            async def create(**kwargs):
                return BrokenStream([])
            client.create = create
        run = m.start(req)
        await m.tasks[run["id"]]
        assert store.run(run["id"])["status"] == "failed"
        context = store.conversation(req.conversation_id)["context"]
        assert req.input in str(context)
        assert not any(i.get("type") == "shell_call" for i in context)
        if failure == "timeout":
            assert "edited once" in str(context) and "partial write" in str(context)
            assert "never executed" not in str(context)
        if failure == "disconnect":
            assert "途中経過" in str(context)
        store.preserve_interrupted_context(run["id"])
        assert store.conversation(req.conversation_id)["context"] == context
        client.create = original_create
        client.outputs = [[message()]]
        m.sandbox_factory = FakeSandbox
        req.input = "続けてください"
        resumed = m.start(req)
        await m.tasks[resumed["id"]]
        assert client.calls[-1]["input"][:len(context)] == context
        assert FakeSandbox.instances[-1].commands == []
    asyncio.run(scenario())


def test_restart_preserves_started_command_without_replaying(tmp_path, monkeypatch):
    async def scenario():
        m, store, client, req = setup(tmp_path, [[message()]])
        run = store.create_run(req.model_dump())
        store.save_context(req.conversation_id, [{"role": "user", "content": req.input}], req.provider, req.model, rid=run["id"])
        store.event(run["id"], "command", {"command": "already started"})
        async def cleanup(*args, **kwargs):
            pass
        monkeypatch.setattr("app.agent_runner.docker", cleanup)
        await m.recover()
        context = store.conversation(req.conversation_id)["context"]
        assert "already started" in str(context) and "restart" in str(context)
        await m.recover()
        assert store.conversation(req.conversation_id)["context"] == context
        req.input = "続けて"
        resumed = m.start(req)
        await m.tasks[resumed["id"]]
        assert client.calls[0]["input"][:len(context)] == context
    asyncio.run(scenario())


def test_short_model_timeout_is_clamped_and_logged(tmp_path):
    class CaptureTimeout(FakeSandbox):
        async def execute(self, command, emit, timeout):
            assert timeout == 60
            raise CommandTimeoutError(timeout)
    async def scenario():
        call = shell("find .")
        call["action"]["timeout_ms"] = 10000
        m, store, _, req = setup(tmp_path, [[call]], sandbox=CaptureTimeout)
        run = m.start(req)
        await m.tasks[run["id"]]
        command = next(e["data"] for e in store.events(run["id"]) if e["type"] == "command")
        done = next(e["data"] for e in store.events(run["id"]) if e["type"] == "command_done")
        assert command["timeout_seconds"] == 60
        assert command["requested_timeout_ms"] == 10000
        assert done["outcome"]["timeout_seconds"] == 60
        error = next(e["data"] for e in store.events(run["id"]) if e["type"] == "error")
        assert error["scope"] == "command"
        assert error["timeout_seconds"] == 60
        assert "60s" in error["message"]
        assert "3600" not in error["message"]
        assert "Command time limit reached" in str(store.conversation(req.conversation_id)["context"])
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["startup", "model"])
def test_operation_timeout_is_not_reported_as_run_timeout(tmp_path, stage):
    class StartupTimeout(FakeSandbox):
        async def start(self):
            raise TimeoutError("Docker startup timed out after 60s")

    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [[message()]],
            sandbox=StartupTimeout if stage == "startup" else FakeSandbox,
        )
        if stage == "model":
            async def create(**kwargs):
                raise TimeoutError("Model request timed out")
            client.create = create
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert store.run(run["id"])["status"] == "failed"
        error = next(e["data"] for e in store.events(run["id"]) if e["type"] == "error")
        assert error["scope"] == "operation"
        assert "3600" not in error["message"]
        assert ("Docker startup" if stage == "startup" else "Model request") in error["message"]
        assert FakeSandbox.instances[-1].closed
        assert not manager.locks[str(manager.config.workspaces[0].path)].locked()

    asyncio.run(scenario())


def test_run_timeout_during_command_reports_only_run_limit(tmp_path):
    class SlowSandbox(FakeSandbox):
        async def execute(self, command, emit, timeout):
            await emit("stdout", "search started")
            await asyncio.Event().wait()

    async def scenario():
        manager, store, _, request = setup(
            tmp_path, [[shell("rg pattern .")]], sandbox=SlowSandbox, run_timeout=1,
        )
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert store.run(run["id"])["status"] == "failed"
        events = store.events(run["id"])
        error = next(e["data"] for e in events if e["type"] == "error")
        assert error["scope"] == "run"
        assert error["timeout_seconds"] == 1
        assert "Run time limit reached (1s)" in error["message"]
        assert not any(e["type"] == "command_done" and e["data"]["outcome"]["type"] == "timeout" for e in events)
        assert "search started" in str(store.conversation(request.conversation_id)["context"])
        assert FakeSandbox.instances[-1].closed
        assert not manager.locks[str(manager.config.workspaces[0].path)].locked()

    asyncio.run(scenario())


def test_first_message_generates_one_title_with_selected_model_and_records_cost(tmp_path):
    async def scenario():
        m, store, client, req = setup(tmp_path, [[message()]])
        store.update_settings(title_provider="azure_openai", title_model="azure-astra")
        run = m.start(req)
        await m.tasks[run["id"]]
        for _ in range(20):
            if store.conversation(req.conversation_id)["title_status"] == "complete":
                break
            await asyncio.sleep(0)
        assert store.conversation(req.conversation_id)["title"] == "編集タスク"
        assert len(client.title_calls) == 1
        assert client.title_calls[0]["model"] == "azure-astra"
        assert client.title_calls[0]["reasoning"] == {"effort": "low"}
        assert any(e["type"] == "conversation_title" for e in store.events(run["id"]))

        client.outputs = [[message()]]
        second = m.start(req)
        await m.tasks[second["id"]]
        assert len(client.title_calls) == 1
        with store.connect() as connection:
            kinds = [row[0] for row in connection.execute("SELECT kind FROM llm_costs ORDER BY kind")]
        assert "title" in kinds and "response" in kinds

    asyncio.run(scenario())


def test_registered_azure_gpt_6_deployments_route_chat_and_title(tmp_path):
    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [[message()]], provider="azure_openai"
        )
        manager.config.azure_models.extend([
            Deployment(model="gpt-6-sol", deployment="azure-new-sol"),
            Deployment(model="gpt-6-luna", deployment="azure-new-luna"),
        ])
        store.update_settings(
            title_provider="azure_openai", title_model="azure-new-luna"
        )
        request = request.model_copy(update={"model": "azure-new-sol"})
        run = manager.start(request)
        await manager.tasks[run["id"]]
        for _ in range(20):
            if client.title_calls:
                break
            await asyncio.sleep(0)
        assert store.run(run["id"])["status"] == "completed"
        assert client.calls[0]["model"] == "azure-new-sol"
        assert client.title_calls[0]["model"] == "azure-new-luna"

    asyncio.run(scenario())


def test_cost_calculation_uses_cache_and_long_context_rates(tmp_path):
    m, store, _, _ = setup(tmp_path, [[message()]])
    m.record_usage(
        "priced-response",
        "openai",
        "gpt-5.6-luna",
        "response",
        {
            "input_tokens": 300_000,
            "input_tokens_details": {"cached_tokens": 100_000, "cache_write_tokens": 50_000},
            "output_tokens": 1_000,
        },
    )
    m.record_usage(
        "priced-response", "openai", "gpt-5.6-luna", "response", {"input_tokens": 1}
    )
    with store.connect() as connection:
        row = connection.execute("SELECT * FROM llm_costs WHERE response_id='priced-response'").fetchone()
        assert connection.execute("SELECT COUNT(*) FROM llm_costs").fetchone()[0] == 1
    assert row["input_rate_nano"] == 400
    assert row["cached_rate_nano"] == 40
    assert row["cache_write_rate_nano"] == 500
    assert row["output_rate_nano"] == 1800
    assert row["cost_nano_usd"] == 90_800_000
    assert store.monthly_costs()[0]["usd"] == pytest.approx(0.0908)


@pytest.mark.parametrize(
    ("model", "input_tokens", "expected_rates", "expected_cost"),
    [
        ("gpt-6-sol", 1_000, (2_000, 200, 2_500, 10_000), 4_690_000),
        ("gpt-6-sol", 300_000, (4_000, 400, 5_000, 15_000), 905_000_000),
        ("gpt-6.1-sol", 1_000, (2_000, 100, 2_500, 10_000), 4_670_000),
        ("gpt-6.1-sol", 300_000, (4_000, 200, 5_000, 15_000), 885_000_000),
        ("gpt-6-luna", 1_000, (100, 10, 125, 500), 234_500),
        ("gpt-6-luna", 300_000, (200, 20, 250, 750), 45_250_000),
    ],
)
def test_gpt_6_cost_rates(tmp_path, model, input_tokens, expected_rates, expected_cost):
    manager, store, _, _ = setup(tmp_path, [])
    cached, cache_write, output = (
        (200, 100, 300) if input_tokens == 1_000 else (100_000, 50_000, 1_000)
    )
    manager.record_usage(
        "priced-response", "openai", model, "response",
        {
            "input_tokens": input_tokens,
            "input_tokens_details": {
                "cached_tokens": cached,
                "cache_write_tokens": cache_write,
            },
            "output_tokens": output,
        },
    )
    with store.connect() as connection:
        row = connection.execute("SELECT * FROM llm_costs WHERE response_id='priced-response'").fetchone()
    assert (
        row["input_rate_nano"], row["cached_rate_nano"],
        row["cache_write_rate_nano"], row["output_rate_nano"],
    ) == expected_rates
    assert row["cost_nano_usd"] == expected_cost


def patch_call(operation, call="patch_1"):
    return {"type": "apply_patch_call", "id": "apc_" + call, "call_id": call,
            "status": "completed", "operation": operation}


def test_apply_patch_edits_and_run_can_be_reverted(tmp_path):
    async def scenario():
        manager, store, client, request = setup(tmp_path, [
            [patch_call(dict(type="update_file", path="a.txt", diff="@@\n-one\n+two\n")),
             patch_call(dict(type="update_file", path="a.txt", diff="@@\n-missing\n+x\n"), "patch_2"),
             patch_call(dict(type="create_file", path="new/b.txt", diff="+hello\n"), "patch_3")],
            [message()],
        ])
        work = tmp_path / "work"
        (work / "a.txt").write_text("one\n")
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert store.run(run["id"])["status"] == "completed"
        assert {"type": "apply_patch"} in client.calls[0]["tools"]
        assert "apply_patch" in client.calls[0]["instructions"]
        outputs = [i for i in client.calls[1]["input"] if i.get("type") == "apply_patch_call_output"]
        assert [(o["call_id"], o["status"]) for o in outputs] == [
            ("patch_1", "completed"), ("patch_2", "failed"), ("patch_3", "completed")
        ]
        assert "context not found" in outputs[1]["output"]
        events = store.events(run["id"])
        done = [e["data"] for e in events if e["type"] == "patch_done"]
        assert done[0]["added"] == 1 and "+two" in done[0]["diff"]
        assert [e["data"]["name"] for e in events if e["type"] == "checkpoint"] == ["before", "after"]
        assert (work / "a.txt").read_text() == "two\n"

        changes = await manager.changes(run["id"])
        assert changes["available"] and not changes["reverted"]
        assert {f["path"]: f["status"] for f in changes["files"]} == {
            "a.txt": "modified", "new/b.txt": "added",
        }
        diff = await manager.diff(run["id"], "a.txt")
        assert "-one\n+two" in diff["diff"]
        result = await manager.revert(run["id"])
        assert result["restored"] == ["a.txt", "new/b.txt"]
        assert (work / "a.txt").read_text() == "one\n"
        assert not (work / "new/b.txt").exists()
        assert (await manager.changes(run["id"]))["reverted"]
        with pytest.raises(ValueError, match="already been reverted"):
            await manager.revert(run["id"])
        assert store.events(run["id"])[-1]["type"] == "reverted"

    asyncio.run(scenario())


def test_checkpoints_can_be_disabled(tmp_path):
    async def scenario():
        manager, store, _, request = setup(tmp_path, [[message()]], checkpoints=False)
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert not [e for e in store.events(run["id"]) if e["type"] == "checkpoint"]
        assert (await manager.changes(run["id"])) == {"available": False, "files": []}

    asyncio.run(scenario())


@pytest.mark.parametrize("checkpoints", [True, False])
def test_ignored_files_excluded_from_artifacts_and_checkpoints(tmp_path, checkpoints):
    class EditingSandbox(FakeSandbox):
        async def start(self):
            (tmp_path / "work/keep.txt").write_text("after")
            (tmp_path / "work/generated/out.txt").write_text("after")

    async def scenario():
        manager, store, _, request = setup(
            tmp_path, [[message()]], sandbox=EditingSandbox, checkpoints=checkpoints,
        )
        work = tmp_path / "work"
        (work / ".gitignore").write_text("generated/\n")
        (work / "generated").mkdir()
        (work / "generated/out.txt").write_text("before")
        (work / "keep.txt").write_text("before")
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert store.run(run["id"])["status"] == "completed"
        artifacts = next(e["data"]["files"] for e in store.events(run["id"]) if e["type"] == "artifacts")
        assert artifacts == [{"path": "keep.txt", "change": "modified"}]
        if checkpoints:
            assert [f["path"] for f in (await manager.changes(run["id"]))["files"]] == ["keep.txt"]
            await manager.revert(run["id"])
            assert (work / "keep.txt").read_text() == "before"
            assert (work / "generated/out.txt").read_text() == "after"

    asyncio.run(scenario())


def function_call(name, arguments, call="fn_1"):
    return {"type": "function_call", "id": "fc_" + call, "call_id": call,
            "name": name, "arguments": arguments}


def test_view_image_returns_image_to_model(tmp_path):
    async def scenario():
        manager, store, client, request = setup(tmp_path, [
            [function_call("view_image", '{"path": "plot.png"}'),
             function_call("view_image", '{"path": "missing.png"}', "fn_2"),
             function_call("view_image", "not json", "fn_3"),
             function_call("delete_everything", "{}", "fn_4")],
            [message()],
        ])
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert store.run(run["id"])["status"] == "completed"
        tool = next(t for t in client.calls[0]["tools"] if t.get("name") == "view_image")
        assert tool["strict"] and tool["parameters"]["required"] == ["path"]
        assert "view_image" in client.calls[0]["instructions"]
        outputs = {i["call_id"]: i["output"] for i in client.calls[1]["input"]
                   if i.get("type") == "function_call_output"}
        assert outputs["fn_1"] == [
            {"type": "input_text", "text": "Image /workspace/plot.png (2x1 image/png)"},
            {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgo=", "detail": "auto"},
        ]
        assert outputs["fn_2"] == "Image not found: missing.png"
        assert outputs["fn_3"] == "Image not found: None"
        assert outputs["fn_4"] == "Unknown function: delete_everything"
        events = store.events(run["id"])
        done = [e["data"] for e in events if e["type"] == "image_view_done"]
        assert done[0]["thumbnail"] == "data:image/jpeg;base64,AA==" and done[0]["width"] == 2
        assert "image_url" not in done[0]
        assert [e["data"]["path"] for e in events if e["type"] == "image_view"] == [
            "plot.png", "missing.png", None,
        ]

    asyncio.run(scenario())


def test_run_settings_do_not_change_cached_prefix(tmp_path):
    async def scenario():
        manager, _, client, request = setup(tmp_path, [[message()], [message()]])
        first = manager.start(request)
        await manager.tasks[first["id"]]
        second = manager.start(request.model_copy(update={"web_search": True, "input": "次"}))
        await manager.tasks[second["id"]]
        one, two = client.calls
        assert one["instructions"] == two["instructions"]
        assert "Run environment" not in one["instructions"]
        # The second request extends the first request's input instead of rewriting it.
        assert two["input"][:len(one["input"])] == one["input"]
        assert run_environment(one)["web_search_enabled"] is False
        assert run_environment(two)["web_search_enabled"] is True
        roles = [item.get("role") for item in two["input"]]
        assert roles[-3:] == ["assistant", "developer", "user"]
        # Unchanged settings are not repeated in history.
        third = manager.start(request.model_copy(update={"web_search": True, "input": "三"}))
        client.outputs.append([message()])
        await manager.tasks[third["id"]]
        roles = [item.get("role") for item in client.calls[-1]["input"]]
        assert roles.count("developer") == 2 and roles[-2:] == ["assistant", "user"]

    asyncio.run(scenario())


def test_apply_patch_tool_can_be_disabled(tmp_path):
    async def scenario():
        manager, _, client, request = setup(tmp_path, [[message()]], apply_patch_tool=False)
        run = manager.start(request)
        await manager.tasks[run["id"]]
        assert {"type": "apply_patch"} not in client.calls[0]["tools"]
        assert "Edit files with Shell." in client.calls[0]["instructions"]
        assert "apply_patch" not in client.calls[0]["instructions"]
        assert "{editing}" not in client.calls[0]["instructions"]

    asyncio.run(scenario())


def test_environment_is_not_duplicated_when_compaction_echoes_it(tmp_path):
    async def scenario():
        manager, store, client, request = setup(
            tmp_path, [[message()], [message()]], compact_token_threshold=1000
        )
        client.tokens = 1100

        async def compact(**kwargs):
            client.compacts.append(copy.deepcopy(kwargs))
            # The API echoes kept messages with an explicit type.
            kept = [{**item, "type": "message"} for item in kwargs["input"] if item.get("role")]
            return NS(id="cmp", usage={"input_tokens": 1, "output_tokens": 1},
                      output=[*kept, {"type": "compaction", "id": "c", "encrypted_content": "x"}])

        client.compact = compact
        for text in ("一", "二"):
            run = manager.start(request.model_copy(update={"input": text}))
            await manager.tasks[run["id"]]
        context = store.conversation(request.conversation_id)["context"]
        environments = [i for i in context if i.get("role") == "developer"]
        assert len(environments) == 1

    asyncio.run(scenario())


def test_storage_cleanup_waits_for_running_tasks(tmp_path):
    async def scenario():
        manager, _, _, _ = setup(tmp_path, [])
        manager.tasks["running"] = asyncio.get_running_loop().create_future()
        with pytest.raises(ValueError, match="Wait for running tasks"):
            manager.prune_checkpoints(0)
        with pytest.raises(ValueError, match="Wait for running tasks"):
            manager.prune_orphan_attachments()
        manager.tasks["running"].set_result(None)
        assert manager.prune_checkpoints(0)["removed_runs"] == 0

    asyncio.run(scenario())
