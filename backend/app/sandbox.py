import asyncio
import codecs
import json
import os
from pathlib import Path
from uuid import uuid4

PATCH_TOOL = (Path(__file__).parent / "patch_tool.py").read_text()
IMAGE_TOOL = (Path(__file__).parent / "image_tool.py").read_text()
SHELL_PROCESS = (Path(__file__).parent / "shell_process.py").read_text()


class CommandTimeoutError(TimeoutError):
    def __init__(self, timeout_seconds):
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Command time limit reached ({timeout_seconds:g}s).")


class SandboxStartError(RuntimeError):
    """Startup failed; a creation attempt may still require confirmed cleanup."""


async def docker(*args, timeout=30):
    process = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException as error:
        if process.returncode is None:
            process.kill()
        await process.wait()
        if isinstance(error, TimeoutError):
            raise TimeoutError(f"Docker {args[0]} timed out after {timeout:g}s") from error
        raise
    if process.returncode:
        raise RuntimeError(
            stderr.decode(errors="replace")[-4000:] or "Docker command failed"
        )
    return stdout.decode(errors="replace").strip()


def command_time_limit(settings, requested=None):
    """Model hints are clamped to the configured floor and hard ceiling."""
    return min(settings.command_timeout, max(
        settings.command_timeout_min, requested or settings.command_timeout
    ))


class Sandbox:
    def __init__(self, settings, workspace, rid, skills, resources, input_dir):
        self.settings = settings
        self.name = "chat-agent-" + rid
        self.workspace = workspace
        self.skills, self.resources, self.input_dir = skills, resources, input_dir
        self.commands = set()
        self._cleanup_required = False

    def arguments(self):
        s = self.settings
        args = [
            "run",
            "-d",
            "--name",
            self.name,
            "--label",
            "chat-orchestrator=agent",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(s.sandbox_pids),
            "--cpus",
            str(s.sandbox_cpus),
            "--memory",
            s.sandbox_memory,
            "--user",
            f"{os.getuid() or 1000}:{os.getgid() or 1000}",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=1g,mode=1777",
            "--env",
            "HOME=/tmp",
            "--env",
            "MPLCONFIGDIR=/tmp/matplotlib",
            "--env",
            "HF_HUB_OFFLINE=1",
            "--env",
            "TRANSFORMERS_OFFLINE=1",
            "--env",
            "HF_DATASETS_OFFLINE=1",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env", "UV_PROJECT_ENVIRONMENT=/opt/runtime/.venv",
            "--env", "UV_NO_SYNC=1",
            "--env", "UV_FROZEN=1",
            "--env", "UV_OFFLINE=1",
            "--env", "GIT_OPTIONAL_LOCKS=0",
            "--env", "GIT_CONFIG_COUNT=2",
            "--env", "GIT_CONFIG_KEY_0=core.fsmonitor",
            "--env", "GIT_CONFIG_VALUE_0=false",
            # File sharing can present host-owned repos with a different uid.
            "--env", "GIT_CONFIG_KEY_1=safe.directory",
            "--env", "GIT_CONFIG_VALUE_1=/workspace",
            "--workdir",
            "/workspace",
            "--mount",
            f"type=bind,src={self.workspace.path},dst=/workspace",
            "--mount",
            f"type=bind,src={self.input_dir},dst=/input,readonly",
        ]
        for skill in self.skills:
            args += [
                "--mount",
                f"type=bind,src={skill.path},dst=/skills/{skill.id},readonly",
            ]
        for resource in self.resources:
            args += [
                "--mount",
                f"type=bind,src={resource.path},dst=/resources/{resource.id},readonly",
            ]
        return args + [s.sandbox_image, "sleep", "infinity"]

    async def start(self):
        self.input_dir.mkdir(parents=True, exist_ok=True)
        # Availability failures here cannot create this run's container. In
        # particular, a stopped daemon must not poison an untouched workspace.
        try:
            version = await docker("info", "--format", "{{.ServerVersion}}", timeout=10)
            # Older Docker CLIs can exit successfully despite daemon errors.
            if not version.strip():
                raise RuntimeError("Docker did not report a server version.")
        except FileNotFoundError as error:
            raise SandboxStartError(
                "Docker is not installed or is not on PATH. "
                "Install Docker or add it to PATH, then send the message again."
            ) from error
        except (RuntimeError, TimeoutError) as error:
            raise SandboxStartError(
                "Docker is not available. Check that Docker is running and accessible, "
                "then send the message again. " + str(error).strip()[:500]
            ) from error
        # Set this before awaiting run: cancellation or a lost reply can happen
        # after the daemon has created a container but before we receive its ID.
        self._cleanup_required = True
        try:
            await docker(*self.arguments(), timeout=60)
        except (OSError, RuntimeError, TimeoutError) as error:
            detail = str(error).strip()
            if any(marker in detail.lower() for marker in (
                "no such image", "unable to find image", "pull access denied",
            )):
                raise SandboxStartError(
                    f"Sandbox image '{self.settings.sandbox_image}' is unavailable. "
                    "Run `make sandbox-build` from the application repository for the default image. "
                    "For a custom SANDBOX_IMAGE, build or pull that image and check the configured name, then retry."
                ) from error
            raise SandboxStartError(
                "The sandbox could not be started. Check Docker and try again. "
                + detail[:500]
            ) from error

    async def close(self):
        if not self._cleanup_required:
            return
        if self.commands:
            try:
                await docker(
                    "exec", self.name, "python", "-I", "-c", SHELL_PROCESS,
                    "stop", *sorted(self.commands), timeout=5,
                )
            except (RuntimeError, TimeoutError):
                # Graceful shutdown is best effort; rm must still confirm shutdown.
                pass
        try:
            await docker("rm", "-f", self.name)
        except RuntimeError as e:
            if "no such container" not in str(e).lower():
                raise
        self._cleanup_required = False

    async def execute(self, command, emit, timeout=None):
        limit = command_time_limit(self.settings, timeout)
        registry = "/tmp/chat-orchestrator-command-" + uuid4().hex
        process = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            self.name,
            "python", "-I", "-c", SHELL_PROCESS, "run", registry, command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.commands.add(registry)
        captured = {"stdout": "", "stderr": ""}
        truncated = set()

        async def read(stream, channel):
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while block := await stream.read(4096):
                text = decoder.decode(block)
                remaining = max(
                    0, self.settings.max_output_chars - len(captured[channel])
                )
                if remaining:
                    piece = text[:remaining]
                    captured[channel] += piece
                    await emit(channel, piece)
                if len(text) > remaining and channel not in truncated:
                    truncated.add(channel)
                    await emit(channel, "\n[Output truncated at the configured limit]\n")
            tail = decoder.decode(b"", final=True)
            if tail and len(captured[channel]) < self.settings.max_output_chars:
                captured[channel] += tail
                await emit(channel, tail)

        readers = [
            asyncio.create_task(read(process.stdout, "stdout")),
            asyncio.create_task(read(process.stderr, "stderr")),
        ]
        try:
            async with asyncio.timeout(limit) as command_timer:
                await process.wait()
                await asyncio.gather(*readers)
            outcome = dict(type="exit", exit_code=process.returncode)
        except (TimeoutError, asyncio.CancelledError) as error:
            # Give Git a chance to release locks before forcing container removal.
            try:
                await asyncio.shield(self.close())
            finally:
                if process.returncode is None:
                    process.kill()
                # The timeout may already have cancelled the stream readers.
                # Drain remaining pipe data so asyncio can finish reaping exec.
                for reader in readers:
                    if not reader.done():
                        reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                await process.communicate()
            if isinstance(error, TimeoutError) and command_timer.expired():
                raise CommandTimeoutError(limit) from error
            raise
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            self.commands.discard(registry)
        for channel in truncated:
            captured[channel] += "\n[output truncated]"
        return {**captured, "outcome": outcome}

    async def run_tool(self, source, request, timeout=60):
        """Run a stdlib tool script in the container so paths resolve there."""
        process = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", self.name, "python", "-I", "-c", source,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(request).encode()), timeout
            )
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            return dict(
                status="failed",
                output="Tool failed: " + stderr.decode(errors="replace")[-2000:],
            )
        return json.loads(stdout)

    async def apply_patch(self, operation):
        result = await self.run_tool(
            PATCH_TOOL, dict(root="/workspace", operation=operation)
        )
        return {"path": operation.get("path"), **result}

    async def view_image(self, path):
        return {"path": path, **await self.run_tool(IMAGE_TOOL, dict(path=path))}
