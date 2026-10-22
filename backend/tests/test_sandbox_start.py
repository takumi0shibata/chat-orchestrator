import asyncio
import pytest
from app.sandbox import Sandbox
from test_agent import setup, message


def test_cancel_during_docker_run_still_removes_created_container(tmp_path, monkeypatch):
    async def scenario():
        manager, store, _, request = setup(tmp_path, [[message()]], sandbox=Sandbox, checkpoints=False)
        created = False
        entered = asyncio.Event()
        calls = []
        async def docker(*args, **kwargs):
            nonlocal created
            calls.append(args[0])
            if args[0] == 'run':
                created = True
                entered.set()
                await asyncio.Future()
            elif args[0] == 'rm':
                created = False
            return ''
        monkeypatch.setattr('app.sandbox.docker', docker)
        run = manager.start(request)
        await asyncio.wait_for(entered.wait(), 3)
        await manager.stop(run['id'])
        try:
            assert store.run(run['id'])['status'] == 'stopped'
            assert not created, f'container remains after Stop; docker calls={calls}; needs_cleanup={store.needs_cleanup(run["id"])}'
        finally:
            await manager.shutdown()
    asyncio.run(scenario())


def test_partial_start_timeout_and_failed_removal_remain_blocked(tmp_path, monkeypatch):
    async def scenario():
        manager, store, _, request = setup(tmp_path, [[message()]], sandbox=Sandbox, checkpoints=False)
        calls = []
        async def docker(*args, **kwargs):
            calls.append(args[0])
            if args[0] == 'run':
                raise TimeoutError('Docker run timed out after creating container')
            if args[0] == 'rm':
                raise RuntimeError('Removal cannot be confirmed')
            return ''
        monkeypatch.setattr('app.sandbox.docker', docker)
        run = manager.start(request)
        await manager.tasks[run['id']]
        try:
            assert store.run(run['id'])['status'] == 'failed'
            assert manager.poisoned_workspaces, f'unconfirmed container removal is treated safe; docker calls={calls}; needs_cleanup={store.needs_cleanup(run["id"])}'
            assert store.needs_cleanup(run['id'])
        finally:
            await manager.shutdown()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [FileNotFoundError(2, "Docker not found"), RuntimeError("Cannot connect to Docker daemon"), RuntimeError("Docker socket permission denied"), TimeoutError("Docker info timed out")])
def test_preflight_failure_allows_retry_and_recovery(tmp_path, monkeypatch, failure):
    async def scenario():
        manager, store, _, request = setup(tmp_path, [[message()]], sandbox=Sandbox, checkpoints=False)
        available = False
        calls = []
        async def docker(*args, **kwargs):
            calls.append(args[0])
            if args[0] == "info" and not available:
                raise failure
            return ""
        monkeypatch.setattr("app.sandbox.docker", docker)
        try:
            for _ in range(2):
                failed = manager.start(request)
                await manager.tasks[failed["id"]]
                assert store.run(failed["id"])["status"] == "failed"
                assert not manager.poisoned_workspaces
                assert not store.needs_cleanup(failed["id"])
                assert store.events(failed["id"])[-1]["data"]["label"].startswith("Docker")
            assert calls == ["info", "info"]
            available = True
            retry = manager.start(request)
            await manager.tasks[retry["id"]]
            assert store.run(retry["id"])["status"] == "completed"
            assert calls == ["info", "info", "info", "run", "rm"]
        finally:
            await manager.shutdown()
    asyncio.run(scenario())


def test_cancel_preflight_never_attempts_container_creation(tmp_path, monkeypatch):
    async def scenario():
        manager, store, _, request = setup(tmp_path, [[message()]], sandbox=Sandbox, checkpoints=False)
        entered = asyncio.Event()
        calls = []
        async def docker(*args, **kwargs):
            calls.append(args[0])
            assert args[0] == "info"
            entered.set()
            await asyncio.Future()
        monkeypatch.setattr("app.sandbox.docker", docker)
        run = manager.start(request)
        await asyncio.wait_for(entered.wait(), 3)
        await manager.stop(run["id"])
        assert calls == ["info"]
        assert store.run(run["id"])["status"] == "stopped"
        assert not store.needs_cleanup(run["id"])
        assert not manager.poisoned_workspaces
        await manager.shutdown()
    asyncio.run(scenario())


def test_run_failure_with_confirmed_absence_allows_retry(tmp_path, monkeypatch):
    async def scenario():
        manager, store, _, request = setup(tmp_path, [[message()]], sandbox=Sandbox, checkpoints=False)
        calls = []
        async def docker(*args, **kwargs):
            calls.append(args[0])
            if args[0] == "run":
                raise RuntimeError("No such image")
            if args[0] == "rm":
                raise RuntimeError("No such container")
            return ""
        monkeypatch.setattr("app.sandbox.docker", docker)
        for _ in range(2):
            run = manager.start(request)
            await manager.tasks[run["id"]]
            assert store.run(run["id"])["status"] == "failed"
            assert not manager.poisoned_workspaces
            assert not store.needs_cleanup(run["id"])
        assert calls == ["info", "run", "rm"] * 2
        await manager.shutdown()
    asyncio.run(scenario())
