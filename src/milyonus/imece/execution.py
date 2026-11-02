"""Execute Python artifacts against independent tests, never on the bare host.

Docker is the portable backend; macOS Seatbelt supports local development.
No backend, missing artifacts, empty tests, timeout and bad output all fail
closed. The workers never receive this executor as an agent-callable tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from milyonus.security.redact import redact

_FILES = re.compile(r"^```python\s+file=([^\s`]+)\s*\n(.*?)^```\s*$", re.M | re.S)
_LIMIT = 16_384


def _validate_path(name: str) -> None:
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or path.suffix != ".py"
        or name != path.as_posix()
        or any(p.startswith((".", "_milyonus")) for p in path.parts)
    ):
        raise ValueError(f"invalid Python artifact path: {name}")


def python_files(deliverable: str) -> dict[str, str]:
    """Only explicitly named Python files; refuse ambiguous/path-traversal input."""
    files: dict[str, str] = {}
    for name, code in _FILES.findall(deliverable):
        _validate_path(name)
        if name in files:
            raise ValueError(f"duplicate Python artifact path: {name}")
        files[name] = code
    if len(files) > 32 or sum(len(c.encode()) for c in files.values()) > 256_000:
        raise ValueError("Python artifact exceeds file/size limits")
    return files


@dataclass(frozen=True)
class ExecutionResult:
    passed: bool
    output: str
    returncode: int | None = None
    backend: str = ""


@dataclass
class PythonExecutor:
    backend: Literal["docker", "macos"] = "docker"
    image: str = "python:3.12-slim"
    timeout: float = 10.0
    max_parallel: int = 4

    def __post_init__(self) -> None:
        if self.timeout <= 0 or self.max_parallel < 1:
            raise ValueError("execution timeout and concurrency must be positive")
        self._sem = asyncio.Semaphore(self.max_parallel)

    def available(self) -> bool:
        if self.backend == "docker":
            return shutil.which("docker") is not None
        return sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists()

    def _argv(self, root: Path, container: str) -> list[str]:
        # Resource limits run before importing any untrusted code. Every test
        # starts a fresh interpreter; candidate and oracle mounts are read-only.
        bootstrap = (
            "import resource,sys,runpy;"
            "resource.setrlimit(resource.RLIMIT_CPU,(5,5));"
            "resource.setrlimit(resource.RLIMIT_FSIZE,(1048576,1048576));"
            "resource.setrlimit(resource.RLIMIT_NOFILE,(64,64));"
            "sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[2],run_name='__main__')"
        )
        if self.backend == "docker":
            return [
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
                "--pids-limit=32",
                "--memory=256m",
                "--memory-swap=256m",
                "--cpus=1",
                "--user=65534:65534",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
                "--mount",
                f"type=bind,src={root},dst=/work,readonly",
                "--workdir=/work/code",
                self.image,
                "python",
                "-I",
                "-B",
                "-c",
                bootstrap,
                "/work/code",
                "/work/oracle.py",
            ]
        runtime = str(Path(sys.base_prefix).resolve())
        executable = str(Path(sys.executable).resolve())
        # Deny by default: no network, fork, arbitrary host reads, or writes.
        # Seatbelt is for macOS development; Docker also adds memory/PID caps.
        reads = ["/System", "/usr", "/Library/Apple", runtime, str(root)]
        profile = (
            "(version 1)(deny default)"
            "(allow sysctl-read)(allow mach-lookup)(allow signal (target self))"
            f"(allow process-exec (literal {json.dumps(executable)}))"
            "(allow file-read-metadata)"
            "(allow file-read* "
            + " ".join(f"(subpath {json.dumps(p)})" for p in reads)
            + " "
            + " ".join(f"(literal {json.dumps(str(p))})" for p in Path(runtime).parents)
            + ' (literal "/dev/null") (literal "/dev/urandom")'
            ' (literal "/dev/random"))'
        )
        return [
            "/usr/bin/sandbox-exec",
            "-p",
            profile,
            executable,
            "-I",
            "-B",
            "-c",
            bootstrap,
            str(root / "code"),
            str(root / "oracle.py"),
        ]

    async def run(self, files: dict[str, str], test: str) -> ExecutionResult:
        if not files or not test.strip():
            return ExecutionResult(
                False, "missing Python artifacts or executable test", backend=self.backend
            )
        # Validate caller-supplied mappings as strictly as extracted artifacts.
        try:
            for name in files:
                _validate_path(name)
            if len(files) > 32 or sum(len(c.encode()) for c in files.values()) > 256_000:
                raise ValueError("Python artifact exceeds file/size limits")
        except ValueError as exc:
            return ExecutionResult(False, str(exc), backend=self.backend)
        if not self.available():
            return ExecutionResult(
                False, f"sandbox unavailable: {self.backend}", backend=self.backend
            )
        async with self._sem:
            with tempfile.TemporaryDirectory(prefix="milyonus-exec-") as tmp:
                root = Path(tmp).resolve()
                root.chmod(0o755)
                (root / "code").mkdir()
                for name, content in files.items():
                    path = root / "code" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                    path.chmod(0o444)
                (root / "oracle.py").write_text(test, encoding="utf-8")
                (root / "oracle.py").chmod(0o444)
                container = "milyonus-test-" + uuid.uuid4().hex
                proc = await asyncio.create_subprocess_exec(
                    *self._argv(root, container),
                    cwd=root / "code",
                    env={"PATH": os.defpath, "LANG": "C.UTF-8"},
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
                output = bytearray()

                async def collect() -> None:
                    assert proc.stdout is not None
                    while chunk := await proc.stdout.read(4096):
                        output.extend(chunk[: max(0, _LIMIT - len(output))])
                    await proc.wait()

                try:
                    await asyncio.wait_for(collect(), self.timeout)
                except (TimeoutError, asyncio.CancelledError) as exc:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    await proc.wait()
                    if self.backend == "docker":
                        cleanup = await asyncio.create_subprocess_exec(
                            "docker",
                            "rm",
                            "-f",
                            container,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(cleanup.wait(), 5)
                        if cleanup.returncode is None:
                            cleanup.kill()
                            await cleanup.wait()
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    return ExecutionResult(False, "sandbox test timed out", backend=self.backend)
                return ExecutionResult(
                    proc.returncode == 0,
                    redact(output.decode("utf-8", "replace")),
                    proc.returncode,
                    self.backend,
                )
