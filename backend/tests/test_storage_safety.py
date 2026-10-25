import asyncio
import threading
from unittest.mock import patch

import pytest
from test_api import app_client  # noqa: F401 - shared isolated API fixture

from app.agent_runner import RunManager
from test_agent import setup, Client, FakeSandbox, message


def test_deleting_cleanup_failed_chat_does_not_erase_recovery(tmp_path):
    class FailedClose(FakeSandbox):
        async def close(self):
            raise RuntimeError('test: removal was not confirmed')
    async def scenario():
        manager, store, client, request = setup(tmp_path, [[message()]], sandbox=FailedClose, checkpoints=False)
        run = manager.start(request)
        await manager.tasks[run['id']]
        assert store.needs_cleanup(run['id'])
        assert manager.poisoned_workspaces
        deleted = False
        try:
            store.delete_conversation(request.conversation_id)
            deleted = True
        except ValueError:
            pass
        calls = []
        async def cleanup(*args, **kwargs):
            calls.append(args)
            raise RuntimeError('test: removal still cannot be confirmed')
        restarted = RunManager(manager.settings, manager.config, store,
                               client_factory=lambda *_: Client([]), sandbox_factory=FakeSandbox)
        with patch('app.agent_runner.docker', cleanup):
            await restarted.recover()
        cid = store.create_conversation('work')['id']
        accepted = False
        try:
            restarted.validate(request.model_copy(update={'conversation_id': cid}))
            accepted = True
        except ValueError:
            pass
        await manager.shutdown()
        await restarted.shutdown()
        assert not deleted
        assert calls == [('rm', '-f', 'chat-agent-' + run['id'])]
        assert restarted.poisoned_workspaces
        assert not accepted
    asyncio.run(scenario())


def test_prune_snapshot_does_not_remove_new_run_checkpoint(tmp_path):
    async def scenario():
        entered = threading.Event()
        release = threading.Event()
        started = asyncio.Event()
        class WaitingSandbox(FakeSandbox):
            async def start(self):
                started.set()
                await asyncio.Future()
        manager, store, client, request = setup(tmp_path, [[message()]], sandbox=WaitingSandbox, workspace_watch=False)
        cp = manager.checkpoints
        original_repos = cp.repos
        first = True
        def paused_repos():
            nonlocal first
            if first:
                first = False
                entered.set()
                assert release.wait(10)
            return original_repos()
        with patch.object(cp, 'repos', paused_repos):
            prune = asyncio.create_task(asyncio.to_thread(manager.prune_checkpoints, 30))
            assert await asyncio.to_thread(entered.wait, 5)
            run = manager.start(request)
            await asyncio.wait_for(started.wait(), 5)
            before = {str(repo): sorted(cp.run_ids(repo)) for repo in original_repos()}
            assert any(run['id'] in ids for ids in before.values())
            release.set()
            await asyncio.wait_for(prune, 10)
            after = {str(repo): sorted(cp.run_ids(repo)) for repo in original_repos()}
        await manager.stop(run['id'])
        await manager.shutdown()
        assert any(run['id'] in ids for ids in after.values()), 'Maintenance classified a newly started run as orphan and deleted its checkpoint'
    asyncio.run(scenario())


def test_orphan_prune_does_not_remove_new_live_conversation_upload(tmp_path):
    async def scenario():
        from io import BytesIO
        from fastapi import UploadFile
        from app.attachments import save_upload
        manager, store, _, _ = setup(tmp_path, [], checkpoints=False)
        entered, release = threading.Event(), threading.Event()
        original = store.conversation_ids
        first = True
        def paused_ids():
            nonlocal first
            ids = original()
            if first:
                first = False
                entered.set()
                assert release.wait(10)
            return ids
        with patch.object(store, 'conversation_ids', paused_ids):
            prune = asyncio.create_task(asyncio.to_thread(manager.prune_orphan_attachments))
            assert await asyncio.to_thread(entered.wait, 5)
            cid = store.create_conversation('work')['id']
            added = await save_upload(store, cid, UploadFile(filename='important.txt', file=BytesIO(b'isolated important data')), 1000)
            from pathlib import Path
            path = Path(store.attachment(added['id'], cid)['path'])
            assert path.exists()
            release.set()
            await asyncio.wait_for(prune, 10)
            await manager.shutdown()
            assert path.exists(), 'Orphan cleanup permanently removed an upload belonging to an existing conversation'
    asyncio.run(scenario())


@pytest.mark.parametrize('cleanup_completed', [False, True])
def test_delete_api_retains_unconfirmed_cleanup_records(app_client, cleanup_completed):
    http, _, _ = app_client
    store = http.app.state.store
    cid = store.create_conversation('work')['id']
    run = store.create_run({'conversation_id': cid})
    store.status(run['id'], 'failed', 'Cleanup failed')
    store.event(run['id'], 'sandbox_cleanup_failed', {})
    if cleanup_completed:
        store.event(run['id'], 'sandbox_cleanup_completed', {})
    response = http.delete(f'/api/conversations/{cid}')
    if cleanup_completed:
        assert response.status_code == 200
    else:
        assert response.status_code == 400
        assert 'until sandbox cleanup is confirmed' in response.json()['detail']
        assert store.conversation(cid)
        assert store.needs_cleanup(run['id'])


@pytest.mark.parametrize('mutation', ['run', 'upload', 'delete'])
def test_cancelled_cleanup_holds_writes_until_worker_finishes(app_client, monkeypatch, mutation):
    from io import BytesIO
    from fastapi import UploadFile
    from app.schemas import CheckpointPrune, RunCreate
    import app.main as main

    http, _, _ = app_client
    manager, store = http.app.state.manager, http.app.state.store
    cid = store.create_conversation('work')['id']
    entered, release = threading.Event(), threading.Event()
    original_prune = manager.prune_checkpoints
    def prune(days):
        entered.set()
        assert release.wait(10)
        return original_prune(days)
    monkeypatch.setattr(manager, 'prune_checkpoints', prune)
    routes = {(route.path, method): route.endpoint for route in http.app.routes
              for method in getattr(route, 'methods', [])}
    writes = []
    if mutation == 'run':
        original = manager.start
        def start(body):
            writes.append('run')
            return original(body)
        monkeypatch.setattr(manager, 'start', start)
        operation = lambda: routes['/api/runs', 'POST'](RunCreate(
            conversation_id=cid, input='test', model='gpt-6-sol'))
    elif mutation == 'upload':
        original = main.save_upload
        async def upload(*args):
            writes.append('upload')
            return await original(*args)
        monkeypatch.setattr(main, 'save_upload', upload)
        operation = lambda: routes['/api/attachments', 'POST'](
            conversation_id=cid, files=[UploadFile(filename='test.txt', file=BytesIO(b'test'))])
    else:
        original = store.delete_conversation
        def delete(target):
            writes.append('delete')
            return original(target)
        monkeypatch.setattr(store, 'delete_conversation', delete)
        operation = lambda: routes['/api/conversations/{cid}', 'DELETE'](cid)

    async def scenario():
        cleanup = asyncio.create_task(routes['/api/storage/checkpoints/prune', 'POST'](
            CheckpointPrune(older_than_days=30)))
        pending = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            pending = asyncio.create_task(operation())
            await asyncio.sleep(0)
            assert not writes
            cleanup.cancel()
            await asyncio.sleep(0)
            cleanup.cancel()
            await asyncio.sleep(0)
            assert not writes
            assert not cleanup.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await cleanup
            result = await pending
            assert writes == [mutation]
            if mutation == 'run':
                task = manager.tasks.get(result['id'])
                if task:
                    await task
                assert store.run(result['id'])['status'] == 'completed'
            elif mutation == 'upload':
                from pathlib import Path
                assert Path(store.attachment(result[0]['id'], cid)['path']).read_bytes() == b'test'
        finally:
            release.set()
            await asyncio.gather(cleanup, *([pending] if pending else []), return_exceptions=True)
    http.portal.call(scenario)
