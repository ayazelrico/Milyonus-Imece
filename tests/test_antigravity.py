"""Tests for the Antigravity CLI AgentFn adapter."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from milyonus.imece.agents import AgentReply, AgentSpec
from milyonus.imece.antigravity import (
    AntigravityAgentFn,
    AntigravityError,
    build_agy_prompt,
    parse_agy_json_output,
)


def _make_fake_agy(script_content: str, directory: Path) -> Path:
    """Create an executable fake `agy` script."""
    fake_bin = directory / "fake_agy"
    with open(fake_bin, "w", encoding="utf-8") as f:
        f.write(script_content)
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake_bin


@pytest.fixture
def sample_spec() -> AgentSpec:
    return AgentSpec(
        block="explore",
        role="Search Specialist",
        goal="Identify three architectural approaches",
        context="We need to build a distributed cache",
        success_criteria=["Must list 3 distinct options", "Include latency tradeoffs"],
    )


def test_build_agy_prompt_prohibits_tools(sample_spec: AgentSpec) -> None:
    prompt = build_agy_prompt(sample_spec)
    assert "CRITICAL CONSTRAINT" in prompt
    assert "MUST NOT execute any tools" in prompt
    assert "ROLE: Search Specialist" in prompt
    assert sample_spec.goal in prompt


def test_parse_agy_json_output_valid() -> None:
    raw = json.dumps(
        {
            "conversation_id": "test-123",
            "status": "SUCCESS",
            "response": "READY\n",
            "duration_seconds": 2.4,
            "num_turns": 1,
            "usage": {
                "input_tokens": 7560,
                "output_tokens": 1,
                "thinking_tokens": 0,
                "cache_read_tokens": 0,
                "total_tokens": 7561,
            },
        }
    ).encode("utf-8")

    reply = parse_agy_json_output(raw)
    assert isinstance(reply, AgentReply)
    assert reply.text == "READY\n"
    assert reply.tokens == 7561
    assert reply.cost_usd is None
    assert reply.cost_estimated is False


def test_parse_agy_json_output_missing_usage() -> None:
    raw = json.dumps(
        {
            "conversation_id": "test-123",
            "status": "SUCCESS",
            "response": "Completed task successfully",
        }
    ).encode("utf-8")

    with pytest.raises(AntigravityError, match="missing required.*usage"):
        parse_agy_json_output(raw)


def test_parse_agy_json_output_non_success_status() -> None:
    raw = json.dumps(
        {
            "status": "ERROR",
            "error": "Model quota exceeded",
        }
    ).encode("utf-8")

    with pytest.raises(AntigravityError, match="non-success"):
        parse_agy_json_output(raw)


def test_parse_agy_json_output_invalid_json() -> None:
    with pytest.raises(AntigravityError, match="Invalid JSON"):
        parse_agy_json_output(b"NOT JSON AT ALL")


def test_parse_agy_json_output_non_string_response() -> None:
    raw = json.dumps(
        {
            "status": "SUCCESS",
            "response": {"nested": "not a string"},
        }
    ).encode("utf-8")

    with pytest.raises(AntigravityError, match="Expected non-empty string 'response'"):
        parse_agy_json_output(raw)


def test_parse_agy_json_output_invalid_numeric_tokens() -> None:
    # String tokens instead of int
    raw1 = json.dumps(
        {
            "status": "SUCCESS",
            "response": "ok",
            "usage": {"total_tokens": "invalid"},
        }
    ).encode("utf-8")
    with pytest.raises(AntigravityError, match="Invalid numeric token count"):
        parse_agy_json_output(raw1)

    # Boolean tokens (bool is a subclass of int in Python)
    raw2 = json.dumps(
        {
            "status": "SUCCESS",
            "response": "ok",
            "usage": {"total_tokens": True},
        }
    ).encode("utf-8")
    with pytest.raises(AntigravityError, match="Invalid numeric token count"):
        parse_agy_json_output(raw2)

    # Negative tokens
    raw3 = json.dumps(
        {
            "status": "SUCCESS",
            "response": "ok",
            "usage": {"total_tokens": -5},
        }
    ).encode("utf-8")
    with pytest.raises(AntigravityError, match="Invalid numeric token count"):
        parse_agy_json_output(raw3)


@pytest.mark.asyncio
async def test_fake_subprocess_valid_execution(tmp_path: Path, sample_spec: AgentSpec) -> None:
    """Tests normal execution with a fake agy executable, verifying flags & args."""
    # Fake script records received arguments and cwd into a log file, then outputs valid JSON.
    log_file = tmp_path / "received_args.json"
    script = f"""#!{sys.executable}
import sys
import json
import os

with open({str(log_file)!r}, "w") as f:
    json.dump({{"argv": sys.argv, "cwd": os.getcwd()}}, f)

result = {{
    "conversation_id": "conv-42",
    "status": "SUCCESS",
    "response": "Architecture plan verified.",
    "duration_seconds": 1.2,
    "num_turns": 1,
    "usage": {{
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150
    }}
}}
print(json.dumps(result))
sys.exit(0)
"""
    fake_bin = _make_fake_agy(script, tmp_path)
    adapter = AntigravityAgentFn(model="gemini-2.5-flash", agy_bin=str(fake_bin))

    reply = await adapter(sample_spec)
    assert reply.text == "Architecture plan verified."
    assert reply.tokens == 150
    assert reply.cost_usd is None

    # Verify args and cwd safety
    with open(log_file) as f:
        recorded = json.load(f)

    argv = recorded["argv"]
    assert argv[1:3] == ["--model", "gemini-2.5-flash"]
    assert argv[3:5] == ["--mode", "plan"]
    assert argv[5] == "--sandbox"
    assert argv[6] == "--disable-slash-commands"
    assert argv[7:9] == ["--output-format", "json"]
    assert argv[9] == "--print"
    # Prompt is the 10th argument (single argument, no shell interpolation)
    assert len(argv) == 11
    assert "Search Specialist" in argv[10]

    # Verify isolated cwd: it shouldn't be the repo cwd or home dir
    assert "agy_sandbox_" in recorded["cwd"]
    assert not os.path.exists(recorded["cwd"])  # cleaned up after completion


@pytest.mark.asyncio
async def test_fake_subprocess_argument_safety(tmp_path: Path, sample_spec: AgentSpec) -> None:
    """Verifies that shell metacharacters in goal/context are passed literally and never evaluated."""
    log_file = tmp_path / "metachar_args.json"
    script = f"""#!{sys.executable}
import sys
import json

with open({str(log_file)!r}, "w") as f:
    json.dump({{"argv": sys.argv}}, f)

result = {{
    "status": "SUCCESS",
    "response": "safe",
    "usage": {{"total_tokens": 10}}
}}
print(json.dumps(result))
"""
    fake_bin = _make_fake_agy(script, tmp_path)
    adapter = AntigravityAgentFn(model="test-model", agy_bin=str(fake_bin))

    malicious_spec = AgentSpec(
        block="danger",
        role="tester",
        goal="`touch injected.txt` $(rm -rf /) ; echo 'pwned' | cat",
        context="test $VAR && echo dangerous",
        success_criteria=[],
    )

    reply = await adapter(malicious_spec)
    assert reply.text == "safe"

    with open(log_file) as f:
        recorded = json.load(f)

    # Injected characters remained literal in argv
    prompt_arg = recorded["argv"][10]
    assert "`touch injected.txt`" in prompt_arg
    assert "$(rm -rf /)" in prompt_arg
    assert "test $VAR && echo dangerous" in prompt_arg


@pytest.mark.asyncio
async def test_fake_subprocess_invalid_json_output(tmp_path: Path, sample_spec: AgentSpec) -> None:
    script = f"""#!{sys.executable}
import sys
print("Server Error: 502 Bad Gateway (not json)")
sys.exit(0)
"""
    fake_bin = _make_fake_agy(script, tmp_path)
    adapter = AntigravityAgentFn(model="test-model", agy_bin=str(fake_bin))

    with pytest.raises(AntigravityError, match="Invalid JSON"):
        await adapter(sample_spec)


@pytest.mark.asyncio
async def test_fake_subprocess_error_status(tmp_path: Path, sample_spec: AgentSpec) -> None:
    script = f"""#!{sys.executable}
import sys
import json
print(json.dumps({{"status": "FAILURE", "error": "Model crashed"}}))
sys.exit(0)
"""
    fake_bin = _make_fake_agy(script, tmp_path)
    adapter = AntigravityAgentFn(model="test-model", agy_bin=str(fake_bin))

    with pytest.raises(AntigravityError, match="Model crashed"):
        await adapter(sample_spec)


@pytest.mark.asyncio
async def test_fake_subprocess_nonzero_exit_code(tmp_path: Path, sample_spec: AgentSpec) -> None:
    script = f"""#!{sys.executable}
import sys
sys.stderr.write("Fatal configuration error: missing auth\\n")
sys.exit(1)
"""
    fake_bin = _make_fake_agy(script, tmp_path)
    adapter = AntigravityAgentFn(model="test-model", agy_bin=str(fake_bin))

    with pytest.raises(AntigravityError, match="Fatal configuration error: missing auth"):
        await adapter(sample_spec)


@pytest.mark.asyncio
async def test_fake_subprocess_timeout_kills_process_group(
    tmp_path: Path, sample_spec: AgentSpec
) -> None:
    # A fake script that writes its pid, flushes, and sleeps
    pid_file = tmp_path / "proc.pid"
    script = f"""#!{sys.executable}
import time
import os

with open({str(pid_file)!r}, "w") as f:
    f.write(str(os.getpid()))
    f.flush()

# Sleep indefinitely
time.sleep(60)
"""
    fake_bin = _make_fake_agy(script, tmp_path)
    adapter = AntigravityAgentFn(model="test-model", agy_bin=str(fake_bin), timeout=1.0)

    with pytest.raises(AntigravityError, match="timed out"):
        await adapter(sample_spec)

    assert pid_file.exists()
    # Verify pid was killed
    with open(pid_file) as f:
        pid = int(f.read().strip())

    # Wait briefly and verify process is dead
    await asyncio.sleep(0.1)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_fake_subprocess_cancellation_cleanup(tmp_path: Path, sample_spec: AgentSpec) -> None:
    pid_file = tmp_path / "cancel_proc.pid"
    script = f"""#!{sys.executable}
import time
import os

with open({str(pid_file)!r}, "w") as f:
    f.write(str(os.getpid()))

time.sleep(60)
"""
    fake_bin = _make_fake_agy(script, tmp_path)
    adapter = AntigravityAgentFn(model="test-model", agy_bin=str(fake_bin), timeout=10.0)

    task = asyncio.create_task(adapter(sample_spec))
    # Wait until process starts and writes pid
    for _ in range(50):
        if pid_file.exists():
            break
        await asyncio.sleep(0.05)

    with open(pid_file) as f:
        pid = int(f.read().strip())

    # Cancel the asyncio task
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Confirm process was terminated
    await asyncio.sleep(0.1)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_max_parallel_concurrency_limiting(tmp_path: Path) -> None:
    active_count_file = tmp_path / "active_count.txt"
    max_observed_file = tmp_path / "max_observed.txt"
    lock_file = tmp_path / "lock"

    script = f"""#!{sys.executable}
import time
import json
import os
import fcntl

def update_counts():
    with open({str(lock_file)!r}, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        curr = 0
        if os.path.exists({str(active_count_file)!r}):
            with open({str(active_count_file)!r}, "r") as f:
                curr = int(f.read().strip() or "0")
        curr += 1
        with open({str(active_count_file)!r}, "w") as f:
            f.write(str(curr))

        max_seen = 0
        if os.path.exists({str(max_observed_file)!r}):
            with open({str(max_observed_file)!r}, "r") as f:
                max_seen = int(f.read().strip() or "0")
        if curr > max_seen:
            with open({str(max_observed_file)!r}, "w") as f:
                f.write(str(curr))
        fcntl.flock(lf, fcntl.LOCK_UN)

def decrement():
    with open({str(lock_file)!r}, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        curr = 0
        if os.path.exists({str(active_count_file)!r}):
            with open({str(active_count_file)!r}, "r") as f:
                curr = int(f.read().strip() or "0")
        curr -= 1
        with open({str(active_count_file)!r}, "w") as f:
            f.write(str(curr))
        fcntl.flock(lf, fcntl.LOCK_UN)

update_counts()
time.sleep(0.1)
decrement()

result = {{
    "status": "SUCCESS",
    "response": "ok",
    "usage": {{"total_tokens": 10}}
}}
print(json.dumps(result))
"""
    fake_bin = _make_fake_agy(script, tmp_path)
    adapter = AntigravityAgentFn(model="test-model", agy_bin=str(fake_bin), max_parallel=2)

    specs = [
        AgentSpec(
            block="b",
            role=f"worker-{i}",
            goal=f"task {i}",
            context="",
            success_criteria=[],
        )
        for i in range(5)
    ]

    replies = await asyncio.gather(*(adapter(s) for s in specs))
    assert len(replies) == 5

    with open(max_observed_file) as f:
        max_seen = int(f.read().strip())

    assert max_seen <= 2
