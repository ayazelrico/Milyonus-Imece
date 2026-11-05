"""Offline 5X protocol, admission, and failure accounting regressions."""

import asyncio
import copy
from decimal import Decimal

import pytest
from evals.imece.data.build_core import TASKS as REFERENCES
from evals.imece.dataset import load_tasks
from evals.imece.protocol import compare, digest, manifest, validate_report

from milyonus.imece.agents import PoolExhausted
from milyonus.imece.ledger import MeteredProvider, ReservationLedger
from milyonus.imece.orchestrator import ImeceSettings
from milyonus.providers.base import CompletionRequest, Message, StreamEvent, Usage


def test_fifty_oracles_match_reference_and_reject_wrong_answer():
    import sys
    import types

    tasks = load_tasks()
    assert len(tasks) == 50
    assert len({category for _, category, *_ in REFERENCES}) == 5
    for task, (task_id, _, _, body, _) in zip(tasks, REFERENCES, strict=True):
        assert task.id == task_id
        module = types.ModuleType("solution")
        exec(
            "def solve(value):\n" + "".join(" " + line + "\n" for line in body.splitlines()),
            module.__dict__,
        )
        old = sys.modules.get("solution")
        sys.modules["solution"] = module
        try:
            exec(task.oracle, {})
            module.solve = lambda _: "__WRONG__"
            with pytest.raises(AssertionError):
                exec(task.oracle, {})
        finally:
            if old is None:
                sys.modules.pop("solution", None)
            else:
                sys.modules["solution"] = old
        assert "cases =" not in task.request


def reports():
    frozen = manifest(
        tasks=load_tasks(),
        settings=ImeceSettings(),
        models={"pool": "fixed"},
        runtime={"backend": "docker", "image": "python@sha256:" + "1" * 64},
        seed=0,
        repeats=5,
        revision="abc",
    )
    base = {
        "manifest": frozen,
        "source": "real-model",
        "ledger": {"unknown_calls": 0, "overruns": 0},
        "runs": [
            {
                "task": t.id,
                "repeat": i,
                "status": "accepted",
                "oracle_passed": True,
                "tokens": 10,
                "cost_usd": 1,
                "cost_estimated": False,
                "confidence": None,
            }
            for t in load_tasks()
            for i in range(5)
        ],
    }
    cand = copy.deepcopy(base)
    for r in cand["runs"]:
        r["cost_usd"] = 0.1
    return base, cand


def test_gate_requires_complete_matrix_and_matching_environment():
    base, cand = reports()
    del cand["runs"][0]
    with pytest.raises(ValueError, match="matrix"):
        compare(base, cand)
    cand = copy.deepcopy(base)
    cand["runs"].append(cand["runs"][0])
    with pytest.raises(ValueError, match="matrix"):
        compare(base, cand)
    cand = copy.deepcopy(base)
    cand["manifest"]["protocol"]["seed"] = 1
    with pytest.raises(ValueError, match="hash mismatch"):
        compare(base, cand)
    cand["manifest"]["protocol_hash"] = digest(cand["manifest"]["protocol"])
    with pytest.raises(ValueError, match="incomparable"):
        compare(base, cand)


def test_five_x_requires_real_audit_and_all_failed_costs():
    base, cand = reports()
    result = compare(base, cand)
    assert result["gain"] == pytest.approx(10)
    assert not result["accepted_5x"]
    audit = {
        "baseline_hash": digest(base),
        "candidate_hash": digest(cand),
        "critical_findings": 0,
        "reviewer": "independent person",
        "reference": "signed report",
    }
    assert compare(base, cand, audit=audit)["accepted_5x"]
    cand["runs"][0]["cost_usd"] = None
    assert not compare(base, cand, audit=audit)["accepted_5x"]
    cand["runs"][0]["cost_usd"] = 1000
    cand["runs"][0]["status"] = "rejected"
    cand["runs"][0]["oracle_passed"] = False
    result = compare(base, cand)
    assert result["gain"] < 1 and not result["accepted_5x"]
    cand["runs"][0]["cost_usd"] = float("nan")
    with pytest.raises(ValueError, match="cost"):
        validate_report(cand)


async def test_parallel_reservations_never_admit_over_budget(tmp_path):
    ledger = ReservationLedger(tmp_path / "budget.db", max_tokens=100, max_usd=1)
    started = []

    async def request():
        try:
            call = ledger.reserve("m", 30, Decimal(".3"))
        except PoolExhausted:
            return False
        started.append(call)
        await asyncio.sleep(0.01)
        ledger.settle(call, 30, Decimal(".3"))
        return True

    assert sum(await asyncio.gather(*(request() for _ in range(20)))) == 3
    assert ledger.summary()["committed_usd"] == pytest.approx(0.9)
    ledger.close()


def test_unknown_and_restart_never_refund_or_retry(tmp_path):
    path = tmp_path / "budget.db"
    ledger = ReservationLedger(path, max_tokens=100, max_usd=1)
    ledger.reserve("m", 30, Decimal(".3"))
    ledger.close()
    ledger = ReservationLedger(path, max_tokens=100, max_usd=1)
    ledger.recover()
    assert ledger.summary()["unknown_calls"] == 1
    assert ledger.summary()["committed_tokens"] == 30
    with pytest.raises(PoolExhausted, match="unresolved"):
        ledger.reserve("m", 1, Decimal(".01"))
    ledger.close()


class Provider:
    name = "fake"
    model = "fixed"

    def __init__(self, mode="ok"):
        self.mode = mode
        self.called = 0

    async def stream(self, request):
        self.called += 1
        yield StreamEvent(kind="text", delta="answer")
        if self.mode == "cancel":
            await asyncio.sleep(10)
        if self.mode != "missing":
            yield StreamEvent(kind="usage", usage=Usage(100, 5))
        yield StreamEvent(kind="done", stop_reason="stop")


@pytest.mark.parametrize("mode", ["ok", "missing", "cancel"])
async def test_provider_meter_settles_only_complete_known_usage(tmp_path, mode):
    ledger = ReservationLedger(tmp_path / "b.db", max_tokens=10000, max_usd=1)
    provider = MeteredProvider(Provider(mode), ledger, input_per_m=1, output_per_m=2)
    request = CompletionRequest(
        "system", [Message(role="user", content="hello")], max_output_tokens=10
    )

    async def consume():
        return [e async for e in provider.stream(request)]

    if mode == "ok":
        await consume()
        assert ledger.summary()["committed_tokens"] == 105
        assert ledger.summary()["unknown_calls"] == 0
    elif mode == "missing":
        with pytest.raises(PoolExhausted):
            await consume()
        assert ledger.summary()["unknown_calls"] == 1
    else:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(consume(), 0.02)
        assert ledger.summary()["unknown_calls"] == 1
    ledger.close()


def test_overrun_is_visible_and_closes_admission(tmp_path):
    ledger = ReservationLedger(tmp_path / "b.db", max_tokens=100, max_usd=1)
    call = ledger.reserve("m", 20, Decimal(".2"))
    with pytest.raises(PoolExhausted):
        ledger.settle(call, 200, Decimal("2"))
    assert ledger.summary()["overruns"] == 1
    assert ledger.summary()["committed_usd"] == 2
    with pytest.raises(PoolExhausted):
        ledger.reserve("m", 1, Decimal(".01"))
    ledger.close()


async def test_journal_replays_complete_nodes_and_preserves_dag(tmp_path):
    from milyonus.imece.agents import AgentReply, AgentSpec
    from milyonus.imece.journal import AgentJournal

    calls = []

    async def agent(spec):
        calls.append(spec)
        return AgentReply("result", 10, 0.01, False)

    spec = AgentSpec("production", "author", "solve", "context", ["works"])
    path = tmp_path / "journal.db"
    journal = AgentJournal(path, agent, identity={"run": "a"})
    journal.phase("one")
    await asyncio.gather(journal(spec), journal(spec))
    journal.phase("two")
    await journal(spec)
    import json

    parents = json.loads(
        journal.db.execute("SELECT parents FROM nodes WHERE phase='two:0'").fetchone()[0]
    )
    edges = json.loads(
        journal.db.execute("SELECT parents FROM phase_inputs WHERE hash=?", (parents,)).fetchone()[
            0
        ]
    )
    assert len(edges) == 2 and all(len(output_hash) == 64 for _, output_hash in edges)
    journal.close()
    journal = AgentJournal(path, agent, identity={"run": "a"})
    journal.phase("one")
    await asyncio.gather(journal(spec), journal(spec))
    journal.phase("two")
    assert (await journal(spec)).tokens == 10
    assert len(calls) == 3 and journal.replayed == 3
    journal.close()
    with pytest.raises(ValueError, match="identity changed"):
        AgentJournal(path, agent, identity={"run": "b"})


async def test_journal_does_not_retry_uncertain_call(tmp_path):
    from milyonus.imece.agents import AgentSpec
    from milyonus.imece.journal import AgentJournal

    calls = 0

    async def agent(spec):
        nonlocal calls
        calls += 1
        raise TimeoutError("possibly billed")

    spec = AgentSpec("p", "r", "g", "c", ["s"])
    path = tmp_path / "journal.db"
    journal = AgentJournal(path, agent, identity={})
    with pytest.raises(TimeoutError):
        await journal(spec)
    journal.close()
    journal = AgentJournal(path, agent, identity={})
    with pytest.raises(PoolExhausted, match="no automatic retry"):
        await journal(spec)
    assert calls == 1
    journal.close()


@pytest.mark.parametrize("change", ["context", "options", "evidence", "policy"])
async def test_precedents_bind_full_context_options_evidence_and_policy(change):
    from dataclasses import replace

    from milyonus.imece.agents import Swarm
    from milyonus.imece.irade import Irade, IradeSettings, Option
    from test_imece import FakeCollective, _req

    council = Irade(Swarm(FakeCollective()), settings=IradeSettings(audit_rate=0))
    req = _req(kind="naming", impact="low")
    await council.decide(req)
    assert council.initial_tier(req)[0] == 1
    if change == "context":
        req = replace(req, context="different contract")
    elif change == "options":
        req = replace(req, options=[Option("A", "different code"), *req.options[1:]])
    elif change == "evidence":
        req = replace(
            req, options=[replace(req.options[0], evidence="test failed"), *req.options[1:]]
        )
    else:
        council.s.veto_floor = 0.9
    assert council.initial_tier(req)[0] == 2


@pytest.mark.parametrize(
    "ledger",
    [False, [], "", {"unknown_calls": False, "overruns": 0}, {"unknown_calls": 0, "overruns": []}],
)
def test_malformed_ledger_cannot_attest_zero_unresolved_charges(ledger):
    base, cand = reports()
    cand["ledger"] = ledger
    audit = {
        "baseline_hash": digest(base),
        "candidate_hash": digest(cand),
        "critical_findings": 0,
        "reviewer": "independent",
        "reference": "report",
    }
    result = compare(base, cand, audit=audit)
    assert not result["accepted_5x"]
    assert "unresolved charges or reservation overruns" in result["blockers"]


@pytest.mark.parametrize("state", ["prepared", "running", "partial", "interrupted"])
def test_complete_matrix_in_unfinished_checkpoint_is_not_final_evidence(state):
    base, _ = reports()
    base["state"] = state
    with pytest.raises(ValueError, match="not complete"):
        validate_report(base)
