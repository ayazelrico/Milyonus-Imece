"""Antigravity CLI AgentFn adapter for Milyonus-Imece.

Invokes the Antigravity CLI binary (`agy`) in headless non-interactive mode as a
subprocess per agent spec:
    agy --model MODEL --mode plan --sandbox --disable-slash-commands         --output-format json --print PROMPT

Guarantees & Constraints:
- Never shell interpolation: uses asyncio.create_subprocess_exec with an argument list.
- Runs inside an empty temporary directory (note: changing cwd alone is not hard filesystem
  or OS sandbox isolation; agy --sandbox flag is passed).
- Enforces strict concurrency limits via an asyncio.Semaphore.
- Process group isolation (start_new_session=True) so timeouts and cancellations kill the entire process tree.
- Process group killing by proc.pid even when leader process has exited, cleaning up orphan descendants.
- Bounded stdout/stderr reading to protect against unbounded memory consumption.
- Strict parsing and validation of agy JSON output schema.
- Rejects non-success status, finished_reason=print_timeout (even if status=SUCCESS),
  empty or non-string response, and missing or invalid usage.total_tokens. Missing token counts
  are strictly rejected and never reported as zero.
- cost_usd is always None unless genuine billing is supplied (never fabricated).
- Prompt explicitly prohibits tool use.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field

from milyonus.imece.agents import AgentReply, AgentSpec

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS: float = 300.0
DEFAULT_MAX_PARALLEL: int = 4
DEFAULT_MAX_OUTPUT_BYTES: int = 10 * 1024 * 1024  # 10 MiB limit

# System instructions prepended to the prompt to prohibit tool use and repo access.
_NO_TOOLS_PROMPT_HEADER = (
    "CRITICAL CONSTRAINT: You are running as a pure text reasoning agent. "
    "You MUST NOT execute any tools, commands, scripts, or file operations. "
    "Do not attempt to read or inspect the environment or external filesystem. "
    "Provide your response directly as text according to the following instructions.\n\n"
)


class AntigravityError(Exception):
    """Raised when the Antigravity CLI invocation fails or produces invalid output."""


def build_agy_prompt(spec: AgentSpec) -> str:
    """Format an AgentSpec into a prompt with explicit tool prohibition."""
    contract = spec.contract()
    briefing = contract.briefing()
    return f"{_NO_TOOLS_PROMPT_HEADER}ROLE: {spec.role}\n\n{briefing}"


def parse_agy_json_output(output_bytes: bytes) -> AgentReply:
    """Parse and strictly validate JSON output from the agy CLI.

    Observed schema:
    {
        "conversation_id": "...",
        "status": "SUCCESS",
        "response": "...",
        "duration_seconds": 2.4,
        "num_turns": 1,
        "usage": {
            "input_tokens": 7560,
            "output_tokens": 1,
            "thinking_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 7561
        }
    }

    Rules:
    - Must be valid JSON and a JSON object (dict).
    - 'status' must equal 'SUCCESS'.
    - 'finished_reason' == 'print_timeout' is rejected even when status is 'SUCCESS'.
    - 'response' must be a non-empty string.
    - 'usage' must be present, containing valid total_tokens (non-negative int).
    - Missing token counts are rejected; missing usage is never reported as zero.
    - Never fabricate tokens or cost; cost_usd is always None unless genuine billing is supplied.
    """
    try:
        text = output_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AntigravityError(f"Output is not valid UTF-8: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AntigravityError(f"Invalid JSON output from agy: {exc}") from exc

    if not isinstance(data, dict):
        raise AntigravityError(f"Expected JSON object from agy, got {type(data).__name__}")

    # Reject finished_reason timeout masquerading as success
    if data.get("finished_reason") == "print_timeout":
        raise AntigravityError(
            "agy output indicated incomplete execution: finished_reason=print_timeout"
        )

    status = data.get("status")
    if status != "SUCCESS":
        error_msg = data.get("error") or data.get("message") or f"status was {status!r}"
        raise AntigravityError(f"agy process reported non-success: {error_msg}")

    response = data.get("response")
    if not isinstance(response, str) or not response.strip():
        raise AntigravityError(
            f"Expected non-empty string 'response' in agy output, got {response!r}"
        )

    # Require actual usage with total_tokens; do not report missing usage as zero
    usage = data.get("usage")
    if usage is None or not isinstance(usage, dict):
        raise AntigravityError(
            "agy output missing required 'usage' dictionary; missing usage must not be reported as zero"
        )

    raw_total = usage.get("total_tokens")
    if raw_total is not None:
        if not isinstance(raw_total, int) or isinstance(raw_total, bool) or raw_total < 0:
            raise AntigravityError(f"Invalid numeric token count for total_tokens: {raw_total!r}")
        total_tokens = raw_total
    else:
        # Fall back to sum of input_tokens and output_tokens if provided
        inp = usage.get("input_tokens")
        out = usage.get("output_tokens")
        if inp is None or out is None:
            raise AntigravityError("agy output usage missing total_tokens and input/output tokens")
        if not isinstance(inp, int) or isinstance(inp, bool) or inp < 0:
            raise AntigravityError(f"Invalid numeric token count for input_tokens: {inp!r}")
        if not isinstance(out, int) or isinstance(out, bool) or out < 0:
            raise AntigravityError(f"Invalid numeric token count for output_tokens: {out!r}")
        total_tokens = inp + out

    # agy CLI output doesn't supply billing cost, so cost_usd is always None.
    # cost_estimated is False because we don't fabricate estimates without billing.
    return AgentReply(
        text=response,
        tokens=total_tokens,
        cost_usd=None,
        cost_estimated=False,
    )


async def _read_bounded_stream(stream: asyncio.StreamReader, limit: int) -> bytearray:
    """Read at most limit bytes; reject larger output without unbounded buffering."""
    buf = bytearray()
    while not stream.at_eof():
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise AntigravityError(f"Output stream exceeded safety limit of {limit} bytes")
    return buf


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Send SIGKILL to the entire process group of proc (pgid == proc.pid when session leader).

    Kills the process group even when the leader process has already exited, cleaning up
    orphan descendants.
    """
    try:
        # With start_new_session=True, proc.pid is the PGID of the created process group.
        # Sending kill to -proc.pid targets the process group even if the leader died.
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()


@dataclass
class AntigravityAgentFn:
    """AgentFn adapter that runs agy subprocesses in isolated temporary directories.

    Args:
        model: Model name to pass to agy.
        agy_bin: Path to the agy executable (defaults to "agy").
        timeout: Subprocess execution timeout in seconds.
        max_parallel: Maximum concurrent agy subprocesses allowed.
        max_output_bytes: Maximum allowed bytes for stdout/stderr to prevent memory exhaustion.
        extra_env: Optional environment variables to merge into the subprocess environment.
    """

    model: str
    agy_bin: str = "agy"
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_parallel: int = DEFAULT_MAX_PARALLEL
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    extra_env: Mapping[str, str] | None = None
    command_prefix: tuple[str, ...] = ()
    environment: Mapping[str, str] | None = None
    quota_retries: int = 12
    quota_backoff_s: float = 30.0
    _sem: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_parallel < 1:
            raise ValueError(f"max_parallel must be >= 1, got {self.max_parallel}")
        if self.timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {self.timeout}")
        self._sem = asyncio.Semaphore(self.max_parallel)

    async def __call__(self, spec: AgentSpec) -> AgentReply:
        prompt = build_agy_prompt(spec)
        async with self._sem:
            attempt = 0
            while True:
                try:
                    return await self._run_subprocess(prompt)
                except AntigravityError as exc:
                    msg = str(exc)
                    exhausted = (
                        "RESOURCE_EXHAUSTED" in msg
                        or "Individual quota reached" in msg
                        or "quota reached" in msg.lower()
                    )
                    if not exhausted or attempt >= self.quota_retries:
                        raise
                    attempt += 1
                    delay = min(600.0, self.quota_backoff_s * (2 ** (attempt - 1)))
                    logger.warning(
                        "agy quota exhausted for model=%s; retry %s/%s in %.0fs",
                        self.model,
                        attempt,
                        self.quota_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)

    async def _run_subprocess(self, prompt: str) -> AgentReply:
        cmd = [
            *self.command_prefix,
            self.agy_bin,
            "--model",
            self.model,
            "--mode",
            "plan",
            "--sandbox",
            "--disable-slash-commands",
            "--output-format",
            "json",
            "--print",
            prompt,
        ]

        env = dict(self.environment) if self.environment is not None else os.environ.copy()
        if self.extra_env:
            env.update(self.extra_env)

        # Empty directory so the subprocess has no repo/workspace files
        with tempfile.TemporaryDirectory(prefix="agy_sandbox_") as tmpdir:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir,
                env=env,
                start_new_session=True,  # Isolate in own process group for clean kill
            )

            try:
                # Read stdout and stderr with limits concurrently under timeout
                async with asyncio.timeout(self.timeout):
                    assert proc.stdout is not None
                    assert proc.stderr is not None
                    stdout_task = asyncio.create_task(
                        _read_bounded_stream(proc.stdout, self.max_output_bytes)
                    )
                    stderr_task = asyncio.create_task(
                        _read_bounded_stream(proc.stderr, self.max_output_bytes)
                    )
                    try:
                        stdout_bytes, stderr_bytes = await asyncio.gather(stdout_task, stderr_task)
                    except BaseException:
                        stdout_task.cancel()
                        stderr_task.cancel()
                        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                        raise

                    await proc.wait()
            except TimeoutError as exc:
                _kill_process_group(proc)
                await proc.wait()
                raise AntigravityError(f"agy subprocess timed out after {self.timeout}s") from exc
            except BaseException:
                # Cancellation or unexpected error: clean up process group immediately
                _kill_process_group(proc)
                await proc.wait()
                raise

            if proc.returncode != 0:
                err_text = bytes(stderr_bytes).decode("utf-8", errors="replace").strip()
                out_text = bytes(stdout_bytes).decode("utf-8", errors="replace").strip()
                msg = err_text or out_text or f"exit code {proc.returncode}"
                raise AntigravityError(f"agy process failed (code {proc.returncode}): {msg}")

            return parse_agy_json_output(bytes(stdout_bytes))
