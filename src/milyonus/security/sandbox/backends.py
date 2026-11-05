"""Shell sandbox backends: local, docker, ssh, modal, daytona.

Every backend returns (exit_code, combined_output). Fail-closed: missing
credentials or unavailable runtimes raise SandboxUnavailable — callers must
not fall back to the host shell.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from milyonus.security.redact import redact, safe_env

_MAX_OUTPUT = 100_000
_TIMEOUT = 120.0


class SandboxUnavailable(RuntimeError):
    """Selected backend cannot run; do not silently use the host shell."""


@dataclass(frozen=True, slots=True)
class SandboxResult:
    exit_code: int
    output: str


def supported_backends() -> tuple[str, ...]:
    return ("local", "docker", "ssh", "modal", "daytona")


async def run_sandboxed(
    command: str,
    *,
    root: Path,
    backend: str = "local",
    image: str = "python:3.12-slim",
    timeout: float = _TIMEOUT,
) -> SandboxResult:
    root = root.resolve()
    if backend not in supported_backends():
        raise SandboxUnavailable(f"unknown sandbox backend: {backend}")
    runners = {
        "local": _run_local,
        "docker": _run_docker,
        "ssh": _run_ssh,
        "modal": _run_modal,
        "daytona": _run_daytona,
    }
    return await runners[backend](command, root=root, image=image, timeout=timeout)


async def _collect(proc: asyncio.subprocess.Process, *, limit: int = _MAX_OUTPUT) -> bytes:
    assert proc.stdout is not None
    out = bytearray()
    while chunk := await proc.stdout.read(4096):
        out.extend(chunk[: max(0, limit - len(out))])
    await proc.wait()
    return bytes(out)


async def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    await proc.wait()


async def _run_local(command: str, *, root: Path, image: str, timeout: float) -> SandboxResult:
    del image
    proc = await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-c",
        command,
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=safe_env(dict(os.environ)),
        start_new_session=True,
    )
    try:
        raw = await asyncio.wait_for(_collect(proc), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        await _kill_process_group(proc)
        if isinstance(exc, asyncio.CancelledError):
            raise
        return SandboxResult(-1, f"(timeout: killed after {timeout:.0f}s)")
    text = redact(raw.decode("utf-8", "replace")[:_MAX_OUTPUT])
    return SandboxResult(proc.returncode or 0, text)


async def _run_docker(command: str, *, root: Path, image: str, timeout: float) -> SandboxResult:
    container = "milyonus-shell-" + uuid.uuid4().hex
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
        env=safe_env(dict(os.environ)),
        start_new_session=True,
    )
    try:
        raw = await asyncio.wait_for(_collect(proc), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        await _kill_process_group(proc)
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
        return SandboxResult(-1, f"(timeout: killed after {timeout:.0f}s)")
    text = redact(raw.decode("utf-8", "replace")[:_MAX_OUTPUT])
    return SandboxResult(proc.returncode or 0, text)


async def _run_ssh(command: str, *, root: Path, image: str, timeout: float) -> SandboxResult:
    del image
    target = os.environ.get("MILYONUS_SANDBOX_SSH_TARGET", "").strip()
    if not target:
        raise SandboxUnavailable(
            "ssh sandbox requires MILYONUS_SANDBOX_SSH_TARGET (user@host); "
            "refusing to fall back to the local shell"
        )
    remote_root = os.environ.get("MILYONUS_SANDBOX_SSH_WORKDIR", "/tmp/milyonus-work").strip()
    key = os.environ.get("MILYONUS_SANDBOX_SSH_KEY", "").strip()
    # Sync workspace then run. rsync may be unavailable — fall back to tar over ssh.
    session = f"milyonus-{uuid.uuid4().hex[:10]}"
    remote_dir = f"{remote_root.rstrip('/')}/{session}"
    ssh_base = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if key:
        ssh_base.extend(["-i", key])
    archive = await asyncio.create_subprocess_exec(
        "tar",
        "-C",
        str(root),
        "-czf",
        "-",
        ".",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=safe_env(dict(os.environ)),
    )
    tarball, err = await archive.communicate()
    if archive.returncode != 0:
        raise SandboxUnavailable(f"ssh sandbox pack failed: {err.decode('utf-8', 'replace')}")
    prep = (
        f"mkdir -p {remote_dir!s} && tar -xzf - -C {remote_dir!s} && "
        f"cd {remote_dir!s} && /bin/sh -c {json.dumps(command)}"
    )
    proc = await asyncio.create_subprocess_exec(
        *ssh_base,
        target,
        prep,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=safe_env(dict(os.environ)),
        start_new_session=True,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(tarball)
        await proc.stdin.drain()
        proc.stdin.close()
        raw = await asyncio.wait_for(_collect(proc), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        await _kill_process_group(proc)
        if isinstance(exc, asyncio.CancelledError):
            raise
        return SandboxResult(-1, f"(timeout: killed after {timeout:.0f}s)")
    finally:
        cleanup = await asyncio.create_subprocess_exec(
            *ssh_base,
            target,
            f"rm -rf {remote_dir}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(cleanup.wait(), 10)
    text = redact(raw.decode("utf-8", "replace")[:_MAX_OUTPUT])
    return SandboxResult(proc.returncode or 0, text)


async def _run_modal(command: str, *, root: Path, image: str, timeout: float) -> SandboxResult:
    """Execute via the Modal CLI when configured; never fall back to local."""
    del root, image  # command-only in v1; use docker/ssh when files are required
    has_token = bool(os.environ.get("MODAL_TOKEN_ID") or os.environ.get("MODAL_TOKEN_SECRET"))
    opted_in = os.environ.get("MILYONUS_SANDBOX_MODAL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not has_token and not opted_in:
        raise SandboxUnavailable(
            "modal sandbox requires MILYONUS_SANDBOX_MODAL=1 and a logged-in "
            "Modal CLI (or MODAL_TOKEN_ID/SECRET); refusing local fallback"
        )
    body = (
        "import modal, subprocess, sys\n"
        "app = modal.App('milyonus-shell')\n"
        "image = modal.Image.debian_slim().pip_install()\n"
        f"@app.function(image=image, timeout=int({int(timeout)}))\n"
        "def run(cmd: str) -> tuple[int, str]:\n"
        "    p = subprocess.run(['/bin/sh','-c',cmd], capture_output=True, text=True)\n"
        "    return p.returncode, (p.stdout or '') + (p.stderr or '')\n"
        "@app.local_entrypoint()\n"
        "def main(cmd: str):\n"
        "    code, out = run.remote(cmd)\n"
        "    sys.stdout.write(out)\n"
        "    raise SystemExit(code)\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as script:
        script.write(body)
        script_path = script.name
    try:
        proc = await asyncio.create_subprocess_exec(
            "modal",
            "run",
            script_path,
            "--cmd",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=safe_env(dict(os.environ)),
            start_new_session=True,
        )
        try:
            raw = await asyncio.wait_for(_collect(proc), timeout=timeout + 30)
        except (TimeoutError, asyncio.CancelledError) as exc:
            await _kill_process_group(proc)
            if isinstance(exc, asyncio.CancelledError):
                raise
            return SandboxResult(-1, f"(timeout: killed after {timeout:.0f}s)")
        if proc.returncode == 127:
            raise SandboxUnavailable("modal CLI not found on PATH")
        text = redact(raw.decode("utf-8", "replace")[:_MAX_OUTPUT])
        return SandboxResult(proc.returncode or 0, text)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(script_path)


async def _run_daytona(command: str, *, root: Path, image: str, timeout: float) -> SandboxResult:
    """Daytona sandbox via REST API (DAYTONA_API_KEY + DAYTONA_API_URL)."""
    del root  # workspace sync lands in a follow-up; command-only for v1
    api_url = (os.environ.get("DAYTONA_API_URL") or "").rstrip("/")
    api_key = os.environ.get("DAYTONA_API_KEY", "").strip()
    if not api_url or not api_key:
        raise SandboxUnavailable(
            "daytona sandbox requires DAYTONA_API_URL and DAYTONA_API_KEY; "
            "refusing to fall back to the local shell"
        )
    import httpx

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "command": ["/bin/sh", "-c", command],
        "image": image,
        "timeout": int(timeout),
        "network": False,
    }
    async with httpx.AsyncClient(timeout=timeout + 15) as client:
        try:
            resp = await client.post(f"{api_url}/sandbox/exec", headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise SandboxUnavailable(f"daytona request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise SandboxUnavailable(f"daytona rejected exec: HTTP {resp.status_code}")
    data = resp.json()
    code = int(data.get("exit_code", data.get("exitCode", 1)))
    out = str(data.get("output") or data.get("stdout") or "")
    return SandboxResult(code, redact(out[:_MAX_OUTPUT]))
