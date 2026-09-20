import asyncio
import codecs
import os


async def docker(*args, timeout=30):
    process = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
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
        await docker(*self.arguments(), timeout=60)

    async def close(self):
        try:
            await docker("rm", "-f", self.name)
        except RuntimeError as e:
            if "No such container" not in str(e):
                raise

    async def execute(self, command, emit, timeout=None):
        limit = command_time_limit(self.settings, timeout)
        process = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            self.name,
            "bash",
            "-c",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
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
                    await emit(channel, "\n[出力を上限で省略しました]\n")
            tail = decoder.decode(b"", final=True)
            if tail and len(captured[channel]) < self.settings.max_output_chars:
                captured[channel] += tail
                await emit(channel, tail)

        readers = [
            asyncio.create_task(read(process.stdout, "stdout")),
            asyncio.create_task(read(process.stderr, "stderr")),
        ]
        try:
            async with asyncio.timeout(limit):
                await process.wait()
                await asyncio.gather(*readers)
            outcome = dict(type="exit", exit_code=process.returncode)
        except (TimeoutError, asyncio.CancelledError):
            # Killing only docker exec leaves descendants running; remove the container.
            await asyncio.shield(self.close())
            if process.returncode is None:
                process.kill()
            await process.wait()
            await asyncio.gather(*readers, return_exceptions=True)
            raise
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
        for channel in truncated:
            captured[channel] += "\n[output truncated]"
        return {**captured, "outcome": outcome}
