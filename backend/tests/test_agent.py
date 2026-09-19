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
                yield NS(
                    type="response.output_text.delta",
                    delta=i["content"][0]["text"],
                    item_id=i["id"],
                )
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
        self.tokens = tokens

    async def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        result = Stream(self.outputs.pop(0), self.tokens)
        self.streams.append(result)
        return result

    async def compact(self, **kwargs):
        self.compacts.append(copy.deepcopy(kwargs))
        return NS(
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
        assert store.conversation(req.conversation_id)["context"] == []

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
