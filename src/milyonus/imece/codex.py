"""Text-only Codex exec JSONL adapter; never uses a raw model API.

CLI authentication stays with Codex. The runner supplies a Seatbelt guard that
blocks repository/oracle reads independently of prompt instructions. This local
CLI guard currently requires macOS; there is no unguarded fallback.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from milyonus.imece.agents import AgentReply, AgentSpec
from milyonus.imece.antigravity import _kill_process_group, _read_bounded_stream, build_agy_prompt


class CodexError(RuntimeError):
    """Failed/incomplete CLI call; usage and charge may be unknown."""


# These switches were inspected in the bundled CLI's local features/help output.
DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "hooks",
    "multi_agent",
    "multi_agent_v2",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "view_image",
    "code_mode",
    "code_mode_host",
    "skill_search",
    "skill_mcp_dependency_install",
    "tool_suggest",
    "memories",
    "shell_snapshot",
    "goals",
    "sleep_tool",
    "in_app_browser",
    "in_app_local_automation",
)
POLICY_VERSION = "text-only-seatbelt-oracle-deny-v2"
DISABLED_CODE_MODE_NOTICE = (
    "Code Mode is unavailable because code-mode host is disabled. "
    "Code mode will fail closed; enable `features.code_mode_host` "
    "and install `codex-code-mode-host`."
)


def discover_codex(executable: str | None = None) -> dict:
    """Validate local help/version, preferring bundled binaries over npm shims.

    Only local metadata commands run here, including during --prepare. An
    explicitly supplied executable must validate; it never silently falls back.
    """
    home = Path.home()
    candidates = (
        [executable]
        if executable
        else [
            "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
            "/Applications/Codex.app/Contents/Resources/codex",
            str(
                home
                / ".codex/plugins/.plugin-appserver/codex-cli/CodexCLI.app/Contents/MacOS/codex"
            ),
            shutil.which("codex"),
        ]
    )
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(shutil.which(candidate) or candidate).expanduser().resolve()
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="imece-cli-discovery-") as cwd:
                results = [
                    subprocess.run(
                        [str(path), *argv],
                        cwd=cwd,
                        env=cli_environment(),
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=True,
                    ).stdout
                    for argv in (("--version",), ("exec", "--help"), ("--help",))
                ]
            version, help_text, root_help = results
            required = (
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--sandbox",
                "--model",
                "--strict-config",
            )
            if not version.startswith("codex-cli ") or any(s not in help_text for s in required):
                continue
            if "--no-daemon" not in root_help:
                continue
            with path.open("rb") as binary:
                checksum = hashlib.file_digest(binary, "sha256").hexdigest()
            return {
                "executable": str(path),
                "version": version.strip(),
                "sha256": checksum,
            }
        except (OSError, subprocess.SubprocessError, UnicodeError):
            continue
    raise CodexError(
        "no supported Codex executable; supply --executable with a validated bundled CLI"
    )


def cli_environment() -> dict[str, str]:
    """Allow native CLI account login without inheriting API keys or hooks."""
    allowed = ("HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TZ", "CODEX_HOME")
    return {k: os.environ[k] for k in allowed if k in os.environ}


def oracle_guard(protected_paths: tuple[Path, ...]) -> list[str]:
    """OS-enforced deny for the repo, checkpoints and temporary oracle trees.

    Cwd isolation/read-only alone still permits host reads. This outer policy
    also applies to CLI child tools, independently of Codex's inner sandbox.
    Network is left to the CLI for inference; model web/MCP tools are disabled.
    """
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise CodexError("CLI oracle isolation requires macOS sandbox-exec; no unsafe fallback")
    paths = sorted({str(p.resolve()) for p in protected_paths})
    if not paths or "/" in paths:
        raise ValueError("explicit repository/oracle paths required")
    selectors = " ".join(f"(subpath {json.dumps(p)})" for p in paths)
    # Executor temp trees can coexist with model calls in other tasks/processes.
    selectors += ' (regex #".*/milyonus-exec-[^/]+(/.*)?$")'
    profile = (
        f"(version 1)(allow default)(deny file-read* {selectors})(deny file-write* {selectors})"
    )
    return ["/usr/bin/sandbox-exec", "-p", profile]


def parse_codex_jsonl(output: bytes) -> AgentReply:
    """Consume exec events, requiring one completed turn and actual usage.

    cached_input_tokens is a subset of input_tokens: do not add it twice.
    Dollar billing is absent from exec JSONL and remains unknown.
    """
    try:
        events = [json.loads(line) for line in output.decode("utf-8").splitlines() if line.strip()]
    except (ValueError, UnicodeError) as exc:
        raise CodexError("invalid Codex JSONL") from exc
    messages = []
    usage = None
    completed = False
    started = False
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise CodexError("invalid Codex event")
        kind = event["type"]
        if completed:
            raise CodexError("events after turn.completed")
        if kind in ("error", "turn.failed"):
            raise CodexError("Codex reported a failed turn; charge reconciliation required")
        if kind.startswith("item."):
            item = event.get("item")
            if not isinstance(item, dict):
                raise CodexError("invalid Codex item")
            # This exact CLI startup diagnostic confirms our disabled host. It
            # precedes the turn and cannot stand in for tool execution or usage.
            if (
                not started
                and kind == "item.completed"
                and item.get("type") == "error"
                and item.get("message") == DISABLED_CODE_MODE_NOTICE
            ):
                continue
            # Fail closed on tool activity and future unknown item types.
            if item.get("type") not in ("agent_message", "reasoning"):
                from milyonus.security.redact import redact

                detail = redact(str(item.get("message", item.get("type"))))[:1000]
                raise CodexError(
                    f"tool activity or unsupported Codex item; result rejected: {detail}"
                )
            if kind == "item.completed" and item["type"] == "agent_message":
                message = item.get("text")
                if not isinstance(message, str):
                    raise CodexError("invalid Codex agent message")
                messages.append(message)
        elif kind == "turn.completed":
            completed, usage = True, event.get("usage")
        elif kind == "turn.started":
            started = True
        elif kind not in ("thread.started", "turn.started"):
            raise CodexError(f"unsupported Codex event type: {kind}")
    if not completed or not isinstance(usage, dict) or not messages or not messages[-1].strip():
        raise CodexError("incomplete Codex turn, missing text or usage")
    for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
        value = usage.get(key)
        if type(value) is not int or value < 0:
            raise CodexError(f"missing or invalid Codex usage.{key}")
    if usage["cached_input_tokens"] > usage["input_tokens"]:
        raise CodexError("cached input exceeds input tokens")
    return AgentReply(
        text=messages[-1],
        tokens=usage["input_tokens"] + usage["output_tokens"],
        cost_usd=None,
        cost_estimated=False,
    )


@dataclass
class CodexAgentFn:
    model: str
    executable: str
    protected_paths: tuple[Path, ...]
    timeout: float = 300
    max_parallel: int = 4
    max_output_bytes: int = 10 * 1024 * 1024
    _sem: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.model.strip() or self.max_parallel < 1 or self.max_output_bytes < 1:
            raise ValueError("model, positive concurrency and output limit required")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("finite positive timeout required")
        self._guard = oracle_guard(self.protected_paths)
        self._sem = asyncio.Semaphore(self.max_parallel)

    async def __call__(self, spec: AgentSpec) -> AgentReply:
        spec.contract().validate()
        async with self._sem:
            with tempfile.TemporaryDirectory(prefix="imece-codex-") as cwd:
                cmd = [
                    *self._guard,
                    self.executable,
                    "--no-daemon",
                    "exec",
                    "--json",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--strict-config",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--model",
                    self.model,
                ]
                overrides = {
                    "approval_policy": "never",
                    "web_search": "disabled",
                    "model_provider": "openai",
                    "forced_login_method": "chatgpt",
                    "project_doc_max_bytes": 0,
                    "mcp_servers": {},
                    "features": dict.fromkeys(DISABLED_FEATURES, False),
                }

                # Inline TOML tables use '=' rather than JSON ':' separators.
                def toml(value):
                    if isinstance(value, dict):
                        return "{" + ",".join(f"{k}={toml(v)}" for k, v in value.items()) + "}"
                    return json.dumps(value)

                for key, value in overrides.items():
                    cmd.extend(("-c", f"{key}={toml(value)}"))
                cmd.append("-")  # exec prompt is stdin, not a positional subcommand
                env = cli_environment()
                env["TMPDIR"] = cwd
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=cwd,
                    env=env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
                tasks = []
                try:
                    async with asyncio.timeout(self.timeout):
                        assert proc.stdin and proc.stdout and proc.stderr
                        tasks = [
                            asyncio.create_task(_read_bounded_stream(s, self.max_output_bytes))
                            for s in (proc.stdout, proc.stderr)
                        ]
                        proc.stdin.write(build_agy_prompt(spec).encode("utf-8"))
                        await proc.stdin.drain()
                        proc.stdin.close()
                        stdout, stderr = await asyncio.gather(*tasks)
                        await proc.wait()
                        if proc.returncode:
                            from milyonus.security.redact import redact

                            diagnostic = redact(bytes(stderr).decode("utf-8", "replace"))[-1500:]
                            raise CodexError(
                                f"Codex exited {proc.returncode}; usage/charge unknown; "
                                f"diagnostic: {diagnostic}"
                            )
                        return parse_codex_jsonl(bytes(stdout))
                except TimeoutError as exc:
                    raise CodexError(
                        f"Codex timed out after {self.timeout}s; usage/charge unknown"
                    ) from exc
                finally:
                    _kill_process_group(proc)  # includes descendants after leader exit
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    with contextlib.suppress(ProcessLookupError):
                        await proc.wait()
