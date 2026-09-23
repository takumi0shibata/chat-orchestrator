import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as main_module
import app.terminal as terminal_module
from app.config import Settings
from app.main import create_app
from app.terminal import HostTerminal, shell_environment, terminal_size


def test_terminal_environment_excludes_backend_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-key")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("LANG", "ja_JP.UTF-8")
    shell, env = shell_environment()
    assert os.path.isabs(shell)
    assert env["LANG"] == "ja_JP.UTF-8"
    assert "OPENAI_API_KEY" not in env
    assert "AZURE_OPENAI_API_KEY" not in env
    assert "private-key" not in repr(env)
    with pytest.raises(ValueError):
        terminal_size(True, 24)
    with pytest.raises(ValueError):
        terminal_size(80, 0)


def test_host_pty_is_interactive_resizable_and_closes(tmp_path, monkeypatch):
    monkeypatch.setattr(terminal_module, "shell_environment", lambda: (
        "/bin/sh", {"HOME": str(tmp_path), "USER": "test", "LOGNAME": "test",
                    "SHELL": "/bin/sh", "PATH": "/usr/bin:/bin", "TERM": "xterm-256color"},
    ))

    async def read_until(session, marker):
        output = b""
        while marker not in output:
            chunk = await asyncio.wait_for(session.read(), timeout=5)
            assert chunk, output
            output += chunk
        return output

    async def scenario():
        session = HostTerminal(tmp_path)
        await session.start(80, 24)
        try:
            await session.write("printf '日本語:%s\\n' \"$PWD\"\n".encode())
            output = await read_until(session, str(tmp_path.resolve()).encode())
            assert "日本語".encode() in output
            session.resize(91, 31)
            await session.write(b"stty size\n")
            assert b"31 91" in await read_until(session, b"31 91")
            await session.write(b"sleep 30\n")
            await asyncio.sleep(0.1)
            await session.write(b"\x03")
            await session.write(b"printf 'AFTER_INTERRUPT\\n'\n")
            assert b"AFTER_INTERRUPT" in await read_until(session, b"AFTER_INTERRUPT")
        finally:
            await session.close()
        assert session.process.returncode is not None
        assert session.master is None

    asyncio.run(scenario())


@pytest.fixture
def terminal_client(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = tmp_path / "runtime.toml"
    runtime.write_text(f'[[workspaces]]\nid="work"\nlabel="Work"\npath="{workspace}"\n')
    settings = Settings(_env_file=None, runtime_config=runtime, data_dir=tmp_path / "data")
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, app, workspace


def test_terminal_websocket_rejects_untrusted_connections(terminal_client, monkeypatch):
    client, app, _ = terminal_client
    monkeypatch.setattr(main_module, "HostTerminal", lambda _: pytest.fail("Shell was spawned"))
    for path, headers in (
        ("/api/terminals/work", {}),
        ("/api/terminals/work", {"origin": "https://evil.example"}),
        ("/api/terminals/missing", {"origin": "http://localhost:5173"}),
        ("/api/terminals/work", {"origin": "http://localhost:5173", "host": "evil.example"}),
    ):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(path, headers=headers):
                pass
    assert not app.state.terminals


def test_terminal_websocket_stream_and_disconnect(terminal_client, monkeypatch):
    client, app, workspace = terminal_client
    monkeypatch.setattr(terminal_module, "shell_environment", lambda: (
        "/bin/sh", {"HOME": str(workspace), "USER": "test", "LOGNAME": "test",
                    "SHELL": "/bin/sh", "PATH": "/usr/bin:/bin", "TERM": "xterm-256color"},
    ))
    with client.websocket_connect(
        "/api/terminals/work", headers={"origin": "http://localhost:5173"}
    ) as socket:
        socket.send_json({"type": "init", "cols": 80, "rows": 24})
        socket.send_json({"type": "resize", "cols": 92, "rows": 30})
        socket.send_bytes(b"stty size; printf 'SOCKET_OK\\n'\n")
        output = b""
        while b"SOCKET_OK" not in output or b"30 92" not in output:
            frame = socket.receive()
            assert frame.get("bytes") is not None, frame
            output += frame["bytes"]
        assert b"30 92" in output
        terminal_session = next(iter(app.state.terminals))
    deadline = time.monotonic() + 2
    while (app.state.terminals or terminal_session.process.returncode is None) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not app.state.terminals
    assert terminal_session.process.returncode is not None


def test_terminal_websocket_reports_shell_exit(terminal_client, monkeypatch):
    client, _, workspace = terminal_client
    monkeypatch.setattr(terminal_module, "shell_environment", lambda: (
        "/bin/sh", {"HOME": str(workspace), "USER": "test", "LOGNAME": "test",
                    "SHELL": "/bin/sh", "PATH": "/usr/bin:/bin", "TERM": "xterm-256color"},
    ))
    with client.websocket_connect(
        "/api/terminals/work", headers={"origin": "http://localhost:5173"}
    ) as socket:
        socket.send_json({"type": "init", "cols": 80, "rows": 24})
        socket.send_bytes(b"exit 7\n")
        while True:
            frame = socket.receive()
            if frame.get("text") is not None:
                message = json.loads(frame["text"])
                assert message == {"type": "exit", "code": 7}
                break
