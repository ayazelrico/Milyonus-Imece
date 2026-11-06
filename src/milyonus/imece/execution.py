"""Execute Python artifacts against independent tests, never on the bare host.

Docker is the portable backend; macOS Seatbelt supports local development.
No backend, missing artifacts, empty tests, timeout and bad output all fail
closed. The workers never receive this executor as an agent-callable tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import sys
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal

from milyonus.security.redact import redact

_FILES = re.compile(r"^```python\s+file=([^\s`]+)\s*\n(.*?)^```\s*$", re.M | re.S)
_LIMIT = 16_384
# These observations do not establish a defect in builder-produced code.
NON_BUILDER_FAILURES = frozenset(
    {
        "oracle_missing",
        "oracle_syntax_error",
        "sandbox_unavailable",
        "timeout",
        "sandbox_launch_error",
        "docker_infrastructure_error",
        "docker_runtime_unverified",
    }
)


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
    evidence_id: str | None = None
    reused: bool = False
    failure_class: str | None = None
    output_truncated: bool = False
    environment_id: str | None = None


class VerificationEnvironmentChanged(RuntimeError):
    """A frozen verification environment disappeared or changed."""


@dataclass
class PythonExecutor:
    backend: Literal["docker", "macos"] = "docker"
    image: str = "python:3.12-slim"
    timeout: float = 10.0
    max_parallel: int = 4
    cache_path: Path | None = None
    approved_evidence: frozenset[str] = frozenset()
    expected_environment_id: str | None = None

    def __post_init__(self) -> None:
        if self.timeout <= 0 or self.max_parallel < 1:
            raise ValueError("execution timeout and concurrency must be positive")
        self._sem = asyncio.Semaphore(self.max_parallel)
        self.processes_started = 0
        self.metadata_processes_started = 0
        self._policy_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    async def _docker_metadata(self, *arguments: str) -> dict | None:
        """Read only selected identity fields, with bounded output and lifetime."""
        async with self._sem:
            proc = None
            try:
                async with asyncio.timeout(5):
                    proc = await asyncio.create_subprocess_exec(
                        shutil.which("docker") or "docker",
                        *arguments,
                        env=self._client_environment(),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    self.metadata_processes_started += 1
                    assert proc.stdout is not None
                    output = bytearray()
                    while chunk := await proc.stdout.read(4096):
                        output.extend(chunk)
                        if len(output) > _LIMIT:
                            return None
                    if await proc.wait() != 0:
                        return None
                    value = json.loads(output)
                    return value if isinstance(value, dict) else None
            except (OSError, TimeoutError, ValueError, UnicodeError):
                return None
            finally:
                if proc is not None:
                    if proc.returncode is None:
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(proc.pid, signal.SIGKILL)
                    await proc.wait()

    async def _docker_identity(self) -> dict | None:
        # A multi-platform digest alone does not identify the selected image.
        # Host architecture also says nothing about a remote Docker daemon.
        image, daemon = await asyncio.gather(
            self._docker_metadata(
                "image",
                "inspect",
                "--format",
                '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}}}',
                self.image,
            ),
            self._docker_metadata(
                "info",
                "--format",
                '{"id":{{json .ID}},"os":{{json .OSType}},"architecture":{{json .Architecture}},'
                '"kernel":{{json .KernelVersion}},"version":{{json .ServerVersion}},'
                '"security":{{json .SecurityOptions}}}',
            ),
        )
        if image is None or daemon is None:
            return None
        if (
            set(image) != {"id", "os", "architecture"}
            or not isinstance(image["id"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image["id"])
            or any(not isinstance(image[k], str) or not image[k] for k in ("os", "architecture"))
            or set(daemon) != {"id", "os", "architecture", "kernel", "version", "security"}
            or any(
                not isinstance(daemon[k], str) or not daemon[k]
                for k in ("id", "os", "architecture", "kernel", "version")
            )
            or not isinstance(daemon["security"], list)
            or any(not isinstance(v, str) for v in daemon["security"])
        ):
            return None
        return {"image": image, "daemon": {**daemon, "security": sorted(daemon["security"])}}

    def available(self) -> bool:
        if self.backend == "docker":
            return shutil.which("docker") is not None
        return sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists()

    def _client_environment(self) -> dict[str, str]:
        environment = {"PATH": os.defpath, "LANG": "C.UTF-8"}
        if self.backend == "docker":
            # These configure the trusted Docker client, never container env.
            for key in (
                "HOME",
                "DOCKER_CONTEXT",
                "DOCKER_HOST",
                "DOCKER_CONFIG",
                "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH",
            ):
                if key in os.environ:
                    environment[key] = os.environ[key]
        return environment

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
                shutil.which("docker") or "docker",
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

    async def verification_environment(self) -> dict | None:
        """Describe the inspected, pinned runtime and actual execution policy."""
        if self.backend != "docker" or not re.fullmatch(r".+@sha256:[0-9a-f]{64}", self.image):
            return None
        runtime_identity = await self._docker_identity()
        if runtime_identity is None:
            return None
        return {
            "backend": self.backend,
            "image": self.image,
            "timeout": self.timeout,
            "executor": self._policy_hash,
            "architecture": platform.machine(),
            "docker": runtime_identity,
            "command": self._argv(Path("/__imece_evidence__"), "imece-evidence"),
        }

    @staticmethod
    def _environment_digest(environment: dict) -> str:
        return hashlib.sha256(
            json.dumps(environment, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()

    async def environment_fingerprint(self) -> str | None:
        environment = await self.verification_environment()
        return self._environment_digest(environment) if environment is not None else None

    def _require_environment(self, observed: str | None) -> None:
        if self.expected_environment_id is not None and observed != self.expected_environment_id:
            raise VerificationEnvironmentChanged(
                "Docker verification environment differs from the frozen run"
            )

    async def verify_environment(self) -> None:
        if self.expected_environment_id is not None:
            self._require_environment(await self.environment_fingerprint())

    async def run(
        self, files: dict[str, str], test: str, *, deterministic: bool = False
    ) -> ExecutionResult:
        # Generated tests are untrusted/non-deterministic by default. Only a
        # trusted caller can opt into reuse with a pinned Docker image.
        if self.backend != "docker" or not re.fullmatch(r".+@sha256:[0-9a-f]{64}", self.image):
            self._require_environment(None)
            return await self._execute(files, test)
        from milyonus.imece.evidence import EvidenceCache, evidence_key

        environment = await self.verification_environment()
        environment_id = self._environment_digest(environment) if environment is not None else None
        self._require_environment(environment_id)
        if environment is None:
            # Missing metadata must never grant reuse of a previous verdict.
            result = await self._execute(files, test)
            # Some client setup failures (e.g. missing Docker context) exit 1,
            # just like an assertion inside a successfully started container.
            if result.failure_class == "candidate_or_oracle_runtime":
                return replace(result, failure_class="docker_runtime_unverified")
            return result
        key = evidence_key(files, test, environment, "isolated-python-v1")
        if self.cache_path is None or (not deterministic and key not in self.approved_evidence):
            return replace(
                await self._execute(files, test), evidence_id=key, environment_id=environment_id
            )
        cache = EvidenceCache(self.cache_path)
        try:
            cached = cache.get(key)
            if cached is not None and cached.environment_id == environment_id:
                return replace(cached, evidence_id=key, reused=True)
            result = replace(
                await self._execute(files, test), evidence_id=key, environment_id=environment_id
            )
            cache.put(key, result)
            return result
        finally:
            cache.close()

    async def _execute(self, files: dict[str, str], test: str) -> ExecutionResult:
        if not test.strip():
            return ExecutionResult(
                False,
                "missing executable test",
                backend=self.backend,
                failure_class="oracle_missing",
            )
        try:
            # Compile only: never import or execute generated oracle code on the host.
            compile(test, "oracle.py", "exec")
        except (SyntaxError, ValueError) as exc:
            return ExecutionResult(
                False,
                redact(f"invalid oracle: {exc}"),
                backend=self.backend,
                failure_class="oracle_syntax_error",
            )
        if not files:
            return ExecutionResult(
                False,
                "missing Python artifacts",
                backend=self.backend,
                failure_class="candidate_missing_files",
            )
        # Validate caller-supplied mappings as strictly as extracted artifacts.
        try:
            for name in files:
                _validate_path(name)
            if len(files) > 32 or sum(len(c.encode()) for c in files.values()) > 256_000:
                raise ValueError("Python artifact exceeds file/size limits")
        except ValueError as exc:
            return ExecutionResult(
                False, str(exc), backend=self.backend, failure_class="candidate_invalid_files"
            )
        if not self.available():
            return ExecutionResult(
                False,
                f"sandbox unavailable: {self.backend}",
                backend=self.backend,
                failure_class="sandbox_unavailable",
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
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *self._argv(root, container),
                        cwd=root / "code",
                        env=self._client_environment(),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        start_new_session=True,
                    )
                except OSError as exc:
                    return ExecutionResult(
                        False,
                        redact(f"sandbox launch failed: {exc}"),
                        backend=self.backend,
                        failure_class=(
                            "sandbox_unavailable"
                            if isinstance(exc, FileNotFoundError)
                            else "sandbox_launch_error"
                        ),
                    )
                self.processes_started += 1
                output = bytearray()
                output_truncated = False

                async def collect() -> None:
                    nonlocal output_truncated
                    assert proc.stdout is not None
                    while chunk := await proc.stdout.read(4096):
                        if len(output) + len(chunk) > _LIMIT:
                            output_truncated = True
                        output.extend(chunk[: max(0, _LIMIT - len(output))])
                    await proc.wait()

                try:
                    await asyncio.wait_for(collect(), self.timeout)
                except (TimeoutError, asyncio.CancelledError) as exc:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    await proc.wait()
                    if self.backend == "docker":
                        # Cleanup must not hide the original timeout/cancellation.
                        with contextlib.suppress(OSError):
                            await self._remove_container(container)
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    return ExecutionResult(
                        False,
                        "sandbox test timed out",
                        backend=self.backend,
                        failure_class="timeout",
                    )
                failure_class = None
                if proc.returncode != 0:
                    # Docker reserves these codes for failures to run the command.
                    # Other exits (including AssertionError) cannot identify which
                    # side of the candidate/oracle contract caused the failure.
                    failure_class = (
                        "docker_infrastructure_error"
                        if self.backend == "docker" and proc.returncode in (125, 126, 127)
                        else "candidate_or_oracle_runtime"
                    )
                return ExecutionResult(
                    proc.returncode == 0,
                    redact(output.decode("utf-8", "replace")),
                    proc.returncode,
                    self.backend,
                    failure_class=failure_class,
                    output_truncated=output_truncated,
                )

    async def _remove_container(self, container: str) -> None:
        cleanup = await asyncio.create_subprocess_exec(
            shutil.which("docker") or "docker",
            "rm",
            "-f",
            container,
            env=self._client_environment(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(cleanup.wait(), 5)
        if cleanup.returncode is None:
            cleanup.kill()
            await cleanup.wait()
