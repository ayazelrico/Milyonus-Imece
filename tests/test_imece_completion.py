"""Completion regressions: dishonest evidence, mutation, isolation and scale."""

import asyncio
import json
import os
import sys
from dataclasses import replace

import pytest

from milyonus.imece.agents import AgentReply, AgentSpec, Swarm
from milyonus.imece.benchmark import summarize
from milyonus.imece.execution import PythonExecutor, python_files
from milyonus.imece.gates import Frame, approve, reality
from milyonus.imece.gates import TestCase as Case
from milyonus.imece.irade import Irade, Option, _read_scores
from milyonus.imece.orchestrator import Candidate, Imece, ImeceSettings
from test_imece import FakeCollective, _req


async def evaluate(answer, *, tests=None, reviewer='{"findings": []}'):
    async def agent(spec):
        return AgentReply(answer if spec.block == "test_exec" else reviewer)

    return (
        await reality(
            Swarm(agent),
            Frame("r", "p", ("c",)),
            [Candidate("C", "a", 0, "solution")],
            tests if tests is not None else [Case("T1", "one"), Case("T2", "two")],
            test_exec=1,
            red_team=1,
            evidence_audit=1,
            compliance=0,
            pass_threshold=1,
        )
    )["C"]


@pytest.mark.parametrize(
    "rows",
    [
        [{"candidate": "C", "test": "T1", "pass": True}],
        [{"candidate": "C", "test": t, "pass": "false"} for t in ("T1", "T2")],
        [{"candidate": "C", "test": t, "pass": True} for t in ("T1", "T1", "T2")],
        [{"candidate": "OTHER", "test": t, "pass": True} for t in ("T1", "T2")],
    ],
)
async def test_incomplete_duplicate_or_invalid_votes_never_pass(rows):
    assert not (await evaluate(json.dumps({"results": rows}))).passed


@pytest.mark.parametrize(
    "review",
    [
        "broken",
        "{}",
        '{"findings":"none"}',
        '{"findings":[{"candidate":"C","severity":"unknown","text":"bad"}]}',
    ],
)
async def test_failed_independent_review_is_not_a_clean_bill(review):
    answer = json.dumps(
        {"results": [{"candidate": "C", "test": t, "pass": True} for t in ("T1", "T2")]}
    )
    report = await evaluate(answer, reviewer=review)
    assert not report.passed and report.worst() == "critical"


async def test_zero_tests_never_pass_even_at_zero_threshold():
    assert not (await evaluate('{"results": []}', tests=[])).passed


async def test_conditional_only_is_not_acceptance():
    fake = FakeCollective(verdicts=("conditional",))
    verdict = await approve(
        Swarm(fake), request="r", criteria=["c"], deliverable="d", evidence="e", n_agents=1
    )
    assert not verdict.accepted


async def test_framing_failures_cannot_fabricate_a_valid_run():
    async def broken(spec):
        return AgentReply("broken")

    result = await Imece(broken, ImeceSettings(agents=17)).run("task")
    assert result.status == "rejected" and "framing quorum" in result.notes[0]


@pytest.mark.parametrize("mutation", ["revision", "polish"])
async def test_changed_deliverable_is_retested_before_decision_or_approval(mutation):
    fake = FakeCollective()
    original = fake.answer

    def answer(spec):
        if mutation == "revision" and spec.role.startswith("author revising"):
            return "BROKEN"
        if mutation == "polish" and spec.block == "polish":
            return "BROKEN"
        if spec.block == "test_exec" and "BROKEN" in spec.context:
            data = json.loads(original(spec))
            for r in data["results"]:
                r["pass"] = False
            return json.dumps(data)
        return original(spec)

    fake.answer = answer
    result = await Imece(fake, ImeceSettings(agents=120, max_rounds=1)).run("task")
    assert result.status == "rejected"
    assert not fake.by_block("approval")
    if mutation == "revision":
        assert not any(s.block == "irade" and "primary basis" in s.goal for s in fake.specs)


async def test_layered_councils_consider_every_option_in_bounded_packets():
    fake = FakeCollective()
    req = replace(_req(), options=[Option(f"O{i}", str(i)) for i in range(100)])
    result = await Irade(Swarm(fake)).decide_layered(req, cell_size=9)
    assert result.choice == "O0"
    packets = fake.by_block("irade")
    assert all(s.context.count("## Option ") <= 9 for s in packets)
    assert all(any(f"## Option O{i}\n" in s.context for s in packets) for i in range(100))


async def test_hierarchical_command_reads_every_contribution():
    fake = FakeCollective()
    engine = Imece(fake)
    await engine._summarize(Frame("r", "p", ("c",)), [f"EVIDENCE-{i}" for i in range(100)], "recon")
    cells = [s for s in fake.by_block("command") if "coordinator level 0" in s.role]
    assert len(cells) == 12
    assert all(
        any(f"EVIDENCE-{i}\n" in s.context or s.context.endswith(f"EVIDENCE-{i}") for s in cells)
        for i in range(100)
    )
    assert all(s.context.count("## Member ") <= 9 for s in cells)


async def test_swarm_concurrency_order_timeout_and_cancellation():
    active = peak = 0

    async def fn(spec):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.001 if spec.role != "slow" else 1)
            return AgentReply(spec.role, 1)
        finally:
            active -= 1

    swarm = Swarm(fn, max_parallel=3, agent_timeout=0.1)
    specs = [AgentSpec("p", str(i), "g", "c", ["s"]) for i in range(40)]
    assert await swarm.run(specs) == [str(i) for i in range(40)]
    assert peak <= 3
    assert (await swarm.run([replace(specs[0], role="slow")]))[0].startswith(
        "(agent failed: TimeoutError"
    )
    assert active == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 2, True, "0.8"])
def test_invalid_council_scores_abstain(value):
    scores = dict.fromkeys(
        ("correctness", "safety", "reversibility", "legal", "cost", "speed"), 0.8
    )
    scores["safety"] = value
    assert _read_scores({"A": scores}, ["A"]) is None


@pytest.mark.parametrize(
    "name",
    ["../escape.py", "/tmp/escape.py", "a/../escape.py", "a\\b.py", ".hidden.py", "solution.py"],
)
def test_artifact_paths_and_duplicates_are_rejected(name):
    text = f"```python file={name}\npass\n```"
    if name == "solution.py":
        text += "\n" + text
    with pytest.raises(ValueError):
        python_files(text)


def test_docker_has_explicit_isolation_and_does_not_mount_the_repository(tmp_path):
    argv = PythonExecutor()._argv(tmp_path, "test-container")
    for flag in [
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=32",
        "--memory=256m",
        "--pull=never",
    ]:
        assert flag in argv
    assert "--privileged" not in argv
    assert f"type=bind,src={tmp_path},dst=/work,readonly" in argv


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt integration")
async def test_real_sandbox_correct_wrong_network_secrets_writes_and_timeout(tmp_path):
    executor = PythonExecutor(backend="macos", timeout=1)
    secret = tmp_path / "secret"
    secret.write_text("private")
    files = {"solution.py": "def add(a,b): return a+b\n"}
    assert (await executor.run(files, "from solution import add; assert add(1,2)==3")).passed
    assert (await executor.run(files, "assert 'def add' in open('solution.py').read()")).passed
    for script in [
        "from solution import add; assert add(1,2)==4",
        "import socket; socket.socket().connect(('1.1.1.1',80))",
        f"open({str(secret)!r}).read()",
        "open('solution.py','w').write('broken')",
        "import subprocess; subprocess.run(['/bin/echo','child'],check=True)",
        "while True: pass",
    ]:
        result = await executor.run(files, script)
        assert not result.passed, script
    assert secret.read_text() == "private"


async def test_unavailable_sandbox_fails_before_any_model_call(monkeypatch):
    monkeypatch.setattr(PythonExecutor, "available", lambda self: False)
    fake = FakeCollective()
    result = await Imece(fake, ImeceSettings(verification="python")).run("task")
    assert result.status == "rejected" and not fake.specs


@pytest.mark.skipif(
    os.environ.get("MILYONUS_TEST_DOCKER") != "1", reason="opt-in Docker integration (CI)"
)
async def test_real_docker_executor_isolated_and_mechanically_scored(tmp_path):
    e = PythonExecutor(timeout=10)
    files = {"solution.py": "def add(a,b): return a+b\n"}
    assert (await e.run(files, "from solution import add; assert add(2,3)==5")).passed
    for script in [
        "from solution import add; assert add(2,3)==6",
        "open('solution.py','w').write('bad')",
        "import socket; socket.create_connection(('1.1.1.1',80),timeout=1)",
    ]:
        assert not (await e.run(files, script)).passed
    e.timeout = 1
    assert not (await e.run(files, "while True: pass")).passed


def test_benchmark_separates_acceptance_from_ground_truth_and_unknown_cost():
    rows = [
        {
            "status": "accepted",
            "oracle_passed": True,
            "tokens": 10,
            "cost_usd": 2.0,
            "confidence": 0.9,
        },
        {
            "status": "accepted",
            "oracle_passed": False,
            "tokens": 20,
            "cost_usd": 4.0,
            "confidence": 0.9,
        },
        {
            "status": "rejected",
            "oracle_passed": False,
            "tokens": 30,
            "cost_usd": 3.0,
            "confidence": None,
        },
    ]
    summary = summarize(rows)
    assert summary["accepted_deliverable_rate"] == pytest.approx(2 / 3)
    assert summary["verified_success_rate"] == pytest.approx(1 / 3)
    assert summary["false_accepts"] == 1
    assert summary["cost_per_accepted_usd"] == 4.5
    assert summary["cost_per_verified_success_usd"] == 9
    assert summary["calibration_ece"] == pytest.approx(0.4)
    assert summarize([rows[0] | {"cost_usd": None}])["cost_usd"] is None
    assert summarize([])["accepted_deliverable_rate"] is None


def test_council_evidence_survives_solution_clipping():
    req = replace(_req(), options=[Option("A", "x" * 5000, "UNIQUE EXECUTED TEST EVIDENCE")])
    packet = Irade(Swarm(FakeCollective()))._spec(req, "correctness")
    assert "UNIQUE EXECUTED TEST EVIDENCE" in packet.context
    assert "x" * 2000 not in packet.context
