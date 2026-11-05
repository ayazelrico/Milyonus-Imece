"""Shell tool: run a command in the working root via a sandbox backend.

Classified "danger": a shell command can do irreversible or outward-reaching
things, so the loop routes it through approval. Output is captured with a
timeout and truncated so a runaway command cannot flood the context.

Backends: local · docker · ssh · modal · daytona. Missing adapters no longer
silently pretend to work — they raise at tool-construction time or fail closed
at execution without falling back to the host shell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from milyonus.security.sandbox import SandboxUnavailable, run_sandboxed, supported_backends
from milyonus.tools.registry import Tool


def make_shell_tool(root: Path, *, backend: str = "local", image: str = "python:3.12-slim") -> Tool:
    root = root.resolve()
    if backend not in supported_backends():
        raise ValueError(
            f"shell sandbox backend not implemented: {backend}; "
            f"use one of {', '.join(supported_backends())}"
        )

    async def run_shell(args: dict[str, Any]) -> str:
        command = args["command"]
        try:
            result = await run_sandboxed(command, root=root, backend=backend, image=image)
        except SandboxUnavailable as exc:
            return f"[sandbox unavailable]\n{exc}"
        return f"[exit code {result.exit_code}]\n{result.output}"

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
