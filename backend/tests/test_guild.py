import os

import pytest

from app.config import Folder
from app.guild import Guild, MAX_FILE_BYTES, parse_tasks
from app.storage import Store
from test_api import app_client  # noqa: F401 - shared API fixture


def workspace(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    return Folder(id=name, label=name.upper(), path=path)


def journal(work, summary="比較実験が完了"):
    folder = work.path / ".chat-orchestrator"
    folder.mkdir(exist_ok=True)
    (folder / "overview.md").write_text(f"# 研究\n## 現在地\n{summary}\n## 次の一手\n比較条件を決める\n")
    (folder / "tasks.md").write_text("# TODO\n## 確認待ち\n- [ ] **比較条件**を決める (due: 2026-10-16)\n## 進行中\n- [ ] 分析結果を整理\n- [x] 実験を実施\n")
    (folder / "activity").mkdir(exist_ok=True)
    (folder / "activity" / "2026-10-09.md").write_text("# 比較実験が完了\n条件Aで精度が向上。\n")
    return folder


def test_opt_in_manual_sync_and_persistent_cache(tmp_path):
    opted = workspace(tmp_path, "opted")
    other = workspace(tmp_path, "other")
    store = Store(tmp_path / "state")
    guild = Guild([opted, other], store)
    assert guild.snapshot() == {"synced_at": None, "projects": []}
    assert guild.sync()["projects"] == []
    assert not (other.path / ".chat-orchestrator").exists()
    folder = journal(opted)
    assert guild.snapshot()["projects"] == []  # GET never scans files.
    project, = guild.sync()["projects"]
    assert project["summary"] == "比較実験が完了"
    assert project["next_action"] == "比較条件を決める"
    assert project["status"] == "review"
    assert project["tasks"][0] == {
        "id": "task-3", "title": "比較条件を決める", "status": "review",
        "due": "2026-10-16", "line": 3, "source": "tasks.md",
    }
    assert project["tasks"][2]["status"] == "done"
    assert project["activity"][0]["date"] == "2026-10-09"
    assert project["activity"][0]["summary"] == "条件Aで精度が向上。"
    # A restart preserves the last successful import. Editing a source does not auto-sync.
    (folder / "overview.md").write_text("## 現在地\n改訂後")
    restarted = Guild([opted, other], Store(store.root))
    assert restarted.snapshot()["projects"][0]["summary"] == "比較実験が完了"
    updated = restarted.sync()["projects"][0]
    assert updated["summary"] == "改訂後"
    assert updated["fingerprint"] != project["fingerprint"]
    assert restarted.sync()["projects"][0]["fingerprint"] == updated["fingerprint"]
    folder.rename(opted.path / "archived-journal")
    assert restarted.sync()["projects"] == []
    assert not (opted.path / ".chat-orchestrator").exists()


@pytest.mark.parametrize("failure", ["utf8", "size", "symlink", "fifo", "directory", "invalid_due", "offline"])
def test_failed_project_keeps_last_snapshot_without_blocking_others(tmp_path, failure):
    first, second = workspace(tmp_path, "first"), workspace(tmp_path, "second")
    folder = journal(first)
    journal(second)
    guild = Guild([first, second], Store(tmp_path / "state"))
    old = guild.sync()["projects"][0]
    tasks = folder / "tasks.md"
    tasks.unlink()
    if failure == "utf8":
        tasks.write_bytes(b"\xff")
    elif failure == "size":
        tasks.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    elif failure == "symlink":
        secret = tmp_path / "secret"
        secret.write_text("must-not-be-read")
        tasks.symlink_to(secret)
    elif failure == "fifo":
        os.mkfifo(tasks)
    elif failure == "directory":
        tasks.mkdir()
    elif failure == "invalid_due":
        tasks.write_text("- [ ] task (due: 2026-99-99)")
    else:
        first.path.rename(tmp_path / "offline")
    journal(second, "別プロジェクトは更新")
    snapshot = guild.sync()
    stale, fresh = snapshot["projects"]
    assert stale["error"]
    assert stale["synced_at"] == old["synced_at"]
    assert stale["tasks"] == old["tasks"]
    assert "must-not-be-read" not in str(snapshot)
    assert fresh["summary"] == "別プロジェクトは更新"
    assert fresh["error"] is None


@pytest.mark.parametrize("kind", ["root", "activity"])
def test_folder_symlinks_are_never_followed(tmp_path, kind):
    work = workspace(tmp_path, "work")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "overview.md").write_text("secret")
    (outside / "2026-10-09.md").write_text("secret")
    folder = work.path / ".chat-orchestrator"
    if kind == "root":
        folder.symlink_to(outside, target_is_directory=True)
    else:
        folder.mkdir()
        (folder / "activity").symlink_to(outside, target_is_directory=True)
    result = Guild([work], Store(tmp_path / "state")).sync()
    assert result["projects"][0]["error"]
    assert result["projects"][0]["documents"] == []
    assert "secret" not in str(result)


def test_empty_folder_and_recent_log_limit(tmp_path):
    work = workspace(tmp_path, "work")
    folder = work.path / ".chat-orchestrator"
    folder.mkdir()
    guild = Guild([work], Store(tmp_path / "state"))
    project = guild.sync()["projects"][0]
    assert project["status"] == "unknown"
    assert len(project["warnings"]) == 2
    assert project["updated_at"] is None
    activity = folder / "activity"
    activity.mkdir()
    for i in range(35):
        (activity / f"2026-10-09-{i:02}.md").write_text(f"# 記録{i}")
    project = guild.sync()["projects"][0]
    assert len(project["activity"]) == 30
    assert project["activity"][0]["title"] == "記録34"
    assert "30 journal" in project["warnings"][-1]


def test_reconfigured_workspace_does_not_reuse_old_data(tmp_path):
    work, replacement = workspace(tmp_path, "work"), workspace(tmp_path, "replacement")
    journal(work)
    store = Store(tmp_path / "state")
    Guild([work], store).sync()
    changed = Folder(id="work", label="New", path=replacement.path)
    assert Guild([changed], store).snapshot()["projects"] == []
    assert Guild([], store).snapshot()["projects"] == []


def test_unavailable_workspace_without_a_previous_opt_in_is_not_added(tmp_path):
    work = workspace(tmp_path, "work")
    work.path.rmdir()
    assert Guild([work], Store(tmp_path / "state")).sync()["projects"] == []


def test_task_sections_fences_and_plain_checkboxes():
    tasks = parse_tasks("""# TODO
- [ ] default
## 進行中
### 分析
- [ ] running
````md
## 確認待ち
- [ ] example
```
- [ ] still example
````
## 待ち
- [ ] waiting
## 別の節
- [ ] default again
## 完了
- [ ] explicit done
- [X] checked
""")
    assert [t["title"] for t in tasks] == ["default", "running", "waiting", "default again", "explicit done", "checked"]
    assert [t["status"] for t in tasks] == ["todo", "in_progress", "waiting", "todo", "done", "done"]


def test_guild_api_no_models_and_no_workspace_writes(app_client):
    http, work, model = app_client
    assert http.get("/api/guild").json() == {"synced_at": None, "projects": []}
    assert http.post("/api/guild/sync").json()["projects"] == []
    folder = journal(Folder(id="work", label="Work", path=work))
    before = {str(p): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    result = http.post("/api/guild/sync")
    assert result.status_code == 200
    assert result.json()["projects"][0]["label"] == "Work"
    assert http.get("/api/guild").json() == result.json()
    assert before == {str(p): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    assert http.get("/api/conversations").json() == []
    assert model.calls == model.title_calls == model.compacts == []
    assert http.post("/api/guild/sync", headers={"Origin": "https://evil.example"}).status_code == 403
