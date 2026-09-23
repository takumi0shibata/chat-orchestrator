import asyncio
import copy
from types import SimpleNamespace as NS

import pytest
from app.agent_runner import RunManager
from app.config import Deployment, Folder, MCPServer, RuntimeConfig, Settings
from app.schemas import Approval, RunCreate
from app.storage import Store


class Stream:
    def __init__(self, output, tokens=10):
        self.output, self.tokens, self.closed = output, tokens, False

    async def __aiter__(self):
        for i in self.output:
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
        self.instances.append(self)

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
        s, cfg, store, client_factory=lambda _: client, sandbox_factory=sandbox
    )
    request = RunCreate(
        conversation_id=cid,
        input="編集してください",
        provider=provider,
        model="azure-astra" if provider == "azure_openai" else "gpt-5.6-sol",
    )
    return manager, store, client, request


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
        assert c.calls[0]["tools"][1]["require_approval"] == "always"
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
        assert context[0]["content"][0]["text"] == req.input
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
    assert manager.title_selection() == {
        "title_provider": "azure_openai",
        "title_model": "azure-old-luna",
        "theme_color": "#25262A",
    }

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
            manager.settings, manager.config, store, client_factory=lambda _: client
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
                raise TimeoutError()
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
        assert client.calls[-1]["input"][:-1] == context
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
        assert client.calls[0]["input"][:-1] == context
    asyncio.run(scenario())


def test_short_model_timeout_is_clamped_and_logged(tmp_path):
    class CaptureTimeout(FakeSandbox):
        async def execute(self, command, emit, timeout):
            assert timeout == 60
            raise TimeoutError()
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
