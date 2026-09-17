import asyncio
import os

import pytest
from app.agent_runner import RunManager
from app.config import Folder, RuntimeConfig, Settings, Skill
from app.schemas import RunCreate
from app.storage import Store
from openai import NotFoundError, PermissionDeniedError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_TESTS") != "1",
        reason="Set RUN_LIVE_TESTS=1 for paid API smoke tests",
    ),
]


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-6-astra"])
def test_live_local_shell(tmp_path, model):
    async def scenario():
        settings = Settings(
            data_dir=tmp_path / "data", max_model_rounds=8, run_timeout=180
        )
        if not settings.openai_api_key:
            pytest.skip("OpenAI credential unavailable")
        work = tmp_path / "work"
        work.mkdir()
        (work / "sample.txt").write_text("before")
        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: smoke-edit\ndescription: Edit the smoke test file.\n---\nRead /workspace/sample.txt, replace its content with exactly after, and read it back. Do not modify any other files."
        )
        config = RuntimeConfig(
            workspaces=[Folder(id="w", label="w", path=work)],
            skills=[Skill(id="smoke", label="Smoke", path=skill_path)],
        )
        store = Store(settings.data_dir)
        manager = RunManager(settings, config, store)
        try:
            try:
                await manager.client("openai").models.retrieve(model)
            except (NotFoundError, PermissionDeniedError):
                pytest.skip(f"{model} is not available to the configured API account")
            req = RunCreate(
                conversation_id=store.create_conversation("w")["id"],
                model=model,
                reasoning_effort="low",
                skill_ids=["smoke"],
                input="Use the smoke-edit skill. Read its SKILL.md before performing the file edit, then reply briefly.",
            )
            run = manager.start(req)
            await manager.tasks[run["id"]]
            assert store.run(run["id"])["status"] == "completed", [
                e for e in store.events(run["id"]) if e["type"] == "error"
            ]
            assert (work / "sample.txt").read_text().strip() == "after"
            commands = [
                e["data"]["command"]
                for e in store.events(run["id"])
                if e["type"] == "command"
            ]
            assert any("/skills/smoke" in command for command in commands)
            assert any(
                e["type"] == "artifacts"
                and any(f["path"] == "sample.txt" for f in e["data"]["files"])
                for e in store.events(run["id"])
            )
        finally:
            await manager.shutdown()

    asyncio.run(scenario())
