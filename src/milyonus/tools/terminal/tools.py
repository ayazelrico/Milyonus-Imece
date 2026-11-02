"""Shell tool: run a command in the working root.

Classified "danger": a shell command can do irreversible or outward-reaching
things, so the loop routes it through approval (F4 RiskEngine will refine this;
in F1 the flag is honored by the CLI approval prompt). Output is captured with a
timeout and truncated so a runaway command cannot flood the context.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import uuid
from pathlib import Path
from typing import Any

from milyonus.security.redact import redact, safe_env
from milyonus.tools.registry import Tool

_MAX_OUTPUT = 100_000
_TIMEOUT = 120.0


def make_shell_tool(root: Path, *, backend: str = "local", image: str = "python:3.12-slim") -> Tool:
    root = root.resolve()
    if backend not in ("local", "docker"):
        raise ValueError(f"shell sandbox backend not implemented: {backend}; use local or docker")

    async def run_shell(args: dict[str, Any]) -> str:
        command = args["command"]
        container = "milyonus-shell-" + uuid.uuid4().hex
        argv = ["/bin/sh", "-c", command]
        if backend == "docker":
            argv = [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--name",
                container,
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=64",
                "--memory=512m",
                "--cpus=1",
                "--user",
                f"{os.getuid() or 65534}:{os.getgid() or 65534}",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=32m",
                "--mount",
                f"type=bind,src={root},dst=/work",
                "--workdir=/work",
                image,
                "/bin/sh",
                "-c",
                command,
            ]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=safe_env(dict(os.environ)),  # strip secrets from the child env
            start_new_session=True,
        )
        out = bytearray()

        async def collect():
            while chunk := await proc.stdout.read(4096):
                out.extend(chunk[: max(0, _MAX_OUTPUT - len(out))])
            await proc.wait()

        try:
            await asyncio.wait_for(collect(), timeout=_TIMEOUT)
        except (TimeoutError, asyncio.CancelledError) as exc:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            if backend == "docker":
                cleanup = await asyncio.create_subprocess_exec(
                    "docker",
                    "rm",
                    "-f",
                    container,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(cleanup.wait(), 5)
                except TimeoutError:
                    cleanup.kill()
                    await cleanup.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return f"(timeout: killed after {_TIMEOUT:.0f}s)"
        text = redact(out.decode("utf-8", "replace")[:_MAX_OUTPUT])
        return f"[exit code {proc.returncode}]\n{text}"

    return Tool(
        name="run_shell",
        description="Run a shell command in the working root.",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string", "description": "Command to run"}},
            "required": ["command"],
        },
        handler=run_shell,
        risk="danger",
    )
