import asyncio

import pytest

from app.attachments import file_snapshot
from app.config import Folder, Settings, Skill
from app.sandbox import Sandbox, SandboxUnavailable, command_time_limit


def test_timeout_bounds():
    settings = Settings(_env_file=None)
    assert command_time_limit(settings, 10) == 60
    assert command_time_limit(settings, 180) == 180
    assert command_time_limit(settings, 1000) == 600
    assert command_time_limit(settings) == 600
    assert command_time_limit(Settings(_env_file=None, command_timeout=5), 10) == 5
    assert command_time_limit(Settings(_env_file=None, command_timeout_min=1), 10) == 10


def test_snapshot_prunes_generated_environments(tmp_path):
    for directory in ['.venv', 'node_modules', '.git', '__pycache__']:
        folder = tmp_path / directory
        folder.mkdir()
        (folder / 'generated').write_text('ignored')
    (tmp_path / 'result.txt').write_text('output')
    assert list(file_snapshot(tmp_path)) == ['result.txt']


def test_skill_mounts_are_read_only_and_network_remains_disabled(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    skills = []
    for sid in ("review", "brief"):
        folder = tmp_path / sid
        folder.mkdir()
        (folder / "SKILL.md").write_text(f"---\nname: {sid}\ndescription: Test {sid}\n---\nUse local files.")
        skills.append(Skill(id=sid, label=sid, path=folder))
    sandbox = Sandbox(Settings(_env_file=None), Folder(id="w", label="Work", path=work), "test", skills, [], tmp_path / "input")
    args = sandbox.arguments()
    mounts = [args[i + 1] for i, value in enumerate(args) if value == "--mount"]
    for skill in skills:
        assert f"type=bind,src={skill.path},dst=/skills/{skill.id},readonly" in mounts
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" in args

@pytest.mark.parametrize("grace_error", [RuntimeError("exec failed"), TimeoutError("exec timed out")])
def test_close_forces_removal_when_graceful_stop_fails(tmp_path, monkeypatch, grace_error):
    sandbox = Sandbox(Settings(_env_file=None), Folder(id="w", label="w", path=tmp_path),
                      "test", [], [], tmp_path / "input")
    sandbox.started = True
    sandbox.commands.add("/tmp/test-command")
    calls = []

    async def fake_docker(*args, **kwargs):
        calls.append(args[0])
        if args[0] == "exec":
            raise grace_error
        return ""

    monkeypatch.setattr("app.sandbox.docker", fake_docker)
    asyncio.run(sandbox.close())
    assert calls == ["exec", "rm"]


def test_close_reports_unconfirmed_container_removal(tmp_path, monkeypatch):
    sandbox = Sandbox(Settings(_env_file=None), Folder(id="w", label="w", path=tmp_path),
                      "test", [], [], tmp_path / "input")
    sandbox.started = True

    async def fake_docker(*args, **kwargs):
        raise RuntimeError("Docker unavailable")

    monkeypatch.setattr("app.sandbox.docker", fake_docker)
    with pytest.raises(RuntimeError, match="Docker unavailable"):
        asyncio.run(sandbox.close())


def test_close_before_start_does_not_touch_docker(tmp_path, monkeypatch):
    sandbox = Sandbox(Settings(_env_file=None), Folder(id="w", label="w", path=tmp_path),
                      "test", [], [], tmp_path / "input")
    calls = []

    async def fake_docker(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr("app.sandbox.docker", fake_docker)
    asyncio.run(sandbox.close())
    assert calls == []
    assert sandbox.started is False


def _sandbox(tmp_path):
    return Sandbox(
        Settings(_env_file=None),
        Folder(id="w", label="w", path=tmp_path),
        "test",
        [],
        [],
        tmp_path / "input",
    )


@pytest.mark.parametrize(
    "failure, match",
    [
        (lambda: FileNotFoundError(2, "No such file or directory"), "not installed or not on PATH"),
        (
            lambda: RuntimeError(
                "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                "Is the docker daemon running?"
            ),
            "daemon is not running",
        ),
        (
            lambda: RuntimeError(
                "error during connect: this error may indicate that the docker daemon is not running"
            ),
            "daemon is not running",
        ),
        (
            lambda: RuntimeError("Unable to find image 'missing:latest'"),
            r"could not be started.*missing:latest",
        ),
    ],
)
def test_start_failure_stays_unstarted_and_explains_the_cause(tmp_path, monkeypatch, failure, match):
    sandbox = _sandbox(tmp_path)
    calls = []

    async def fake_docker(*args, **kwargs):
        calls.append(args[0])
        raise failure()

    monkeypatch.setattr("app.sandbox.docker", fake_docker)
    with pytest.raises(SandboxUnavailable, match=match):
        asyncio.run(sandbox.start())
    assert sandbox.started is False
    assert calls == ["run", "rm"]
    calls.clear()
    asyncio.run(sandbox.close())
    assert calls == []
