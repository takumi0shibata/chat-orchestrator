"""Explicit SIWC integration test against a user's authorized local connection."""
import asyncio
import json
import os
from pathlib import Path

import pytest

from app.agent_runner import RunManager
from app.config import Folder, RuntimeConfig, Settings
from app.storage import Store
from app.schemas import RunCreate

pytestmark = [pytest.mark.live, pytest.mark.skipif(
    os.environ.get("RUN_CHATGPT_LIVE_TESTS") != "1",
    reason="Explicitly enable RUN_CHATGPT_LIVE_TESTS with CHATGPT_AUTH_FILE; uses ChatGPT plan allowance and Docker",
)]


def test_native_compaction_restart_continuation_and_docker_shell(tmp_path):
    async def scenario():
        source = Path(os.environ["CHATGPT_AUTH_FILE"])
        settings = Settings(_env_file=None, data_dir=tmp_path / "data", compact_token_threshold=2048,
                            max_model_rounds=8, run_timeout=180)
        work = tmp_path / "work"
        work.mkdir()
        config = RuntimeConfig(workspaces=[Folder(id="w", label="SIWC test", path=work)])
        store = Store(settings.data_dir)
        model = os.environ.get("CHATGPT_TEST_MODEL", "gpt-6-luna")

        async def manager():
            instance = RunManager(settings, config, store)
            instance.chatgpt_auth.record = json.loads(source.read_text())
            # A single stopped app/test process owns rotating credentials.
            instance.chatgpt_auth.path = source
            await instance.chatgpt_auth.models()
            store.update_settings(title_provider="chatgpt", title_model=model)
            return instance

        async def run(instance, request):
            result = instance.start(request)
            await instance.tasks[result["id"]]
            events = store.events(result["id"], limit=100000)
            assert store.run(result["id"])["status"] == "completed", [e for e in events if e["type"] == "error"]
            return events

        instance = await manager()
        cid = store.create_conversation("w")["id"]
        request = RunCreate(conversation_id=cid, provider="chatgpt", model=model, reasoning_effort="low",
                            input="Remember the test value: indigo-42. The following records are irrelevant filler.\n" +
                            "\n".join(f"Record {i}: synthetic test data only." for i in range(500)) +
                            "\nDo not use tools. Acknowledge with OK only.")
        try:
            events = await run(instance, request)
            assert any(e["type"] == "compaction" and e["data"].get("mode") == "server" for e in events)
            retained = store.conversation(cid)["context"]
            assert retained[0]["type"] == "compaction"
            assert "Record 499" not in json.dumps(retained)
        finally:
            await instance.shutdown()

        # Reopen both runtime and stored history before asking the model to use
        # the remembered value. The second prompt does not include that value.
        instance = await manager()
        try:
            request.input = "Use Shell to write the test value I asked you to remember to /workspace/compaction-smoke.txt, then read it back. Do not guess the value."
            events = await run(instance, request)
            assert (work / "compaction-smoke.txt").read_text().strip() == "indigo-42"
            assert any(e["type"] == "command_done" and e["data"]["outcome"].get("exit_code") == 0 for e in events)
            request.input = "What was the remembered test value? Reply with the value only."
            events = await run(instance, request)
            assert "indigo-42" in "".join(e["data"]["text"] for e in events if e["type"] == "text_delta")
        finally:
            await instance.shutdown()
    asyncio.run(scenario())
