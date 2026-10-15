"""Milyonus-Imece: scaling, independence, IRADE routing/veto, gates, full runs."""

import json
import random
import re

import pytest
from pydantic import ValidationError

from milyonus.config.schema import ImeceConfig, MilyonusConfig
from milyonus.imece.agents import (
    AgentReply,
    AgentSpec,
    PoolExhausted,
    Swarm,
    parse_json,
    safe_registry,
)
from milyonus.imece.gates import approve, assign
from milyonus.imece.irade import (
    Calibrator,
    DecisionRequest,
    Irade,
    IradeSettings,
    Option,
)
from milyonus.imece.observer import Observer
from milyonus.imece.orchestrator import Imece, ImeceSettings
from milyonus.imece.scale import BLOCKS, MIN_TOTAL, SPECS, ScaleError, allocate
from milyonus.tools.registry import Tool, ToolRegistry

# ── a deterministic collective ──────────────────────────────────────────────


def _ids(pattern: str, text: str) -> list[str]:
    return re.findall(pattern, text)


class FakeCollective:
    """Answers every role with well-formed JSON; records every spec it saw."""

    def __init__(self, verdicts=("accept",), scores=None, tokens=10, safety=0.8):
        self.specs: list[AgentSpec] = []
        self.verdicts = list(verdicts)
        self.tokens = tokens
        self.safety = safety
        self.scores = scores  # perspective -> {option_index: total}

    async def __call__(self, spec: AgentSpec) -> AgentReply:
        self.specs.append(spec)
        return AgentReply(self.answer(spec), self.tokens)

    def answer(self, spec: AgentSpec) -> str:
        b, ctx = spec.block, spec.context
        if b == "framing":
            return json.dumps(
                {
                    "problem": "framed problem",
                    "success_criteria": ["answer is correct", "answer is explained"],
                    "disciplines": ["math", "writing"],
                    "divergences": ["cells disagreed on scope"],
                }
            )
        if b == "test_design":
            return json.dumps({"tests": [{"check": "answer is correct", "how": "compare"}]})
        if b == "test_exec":
            ids = _ids(r"## Candidate (\S+)", ctx)
            return json.dumps(
                {"results": [{"candidate": i, "test": "T1", "pass": True} for i in ids]}
            )
        if b in ("red_team", "evidence_audit", "compliance"):
            return json.dumps({"findings": []}) if "## Candidate" in ctx else "- verified"
        if b == "plan":
            return json.dumps({"title": f"plan {len(self.specs)}", "steps": ["s"]})
        if b == "command":
            return json.dumps(
                {"approaches": [{"name": "alpha", "idea": "a"}, {"name": "beta", "idea": "b"}]}
            )
        if b == "irade":
            ids = _ids(r"## Option (\S+)", ctx)
            perspective = spec.seat.split(":", 1)[1]
            scores = {}
            for n, oid in enumerate(ids):
                v = 0.8
                if self.scores:
                    v = self.scores.get(perspective, {}).get(n, 0.8)
                scores[oid] = dict.fromkeys(("correctness", "cost", "speed"), v) | {
                    "safety": self.safety,
                    "legal": 0.9,
                    "reversibility": 0.9,
                }
            best = max(ids, key=lambda o: scores[o]["correctness"])
            return json.dumps(
                {"scores": scores, "choice": best, "confidence": 0.9, "rationale": "r"}
            )
        if b == "integration" and "integrity" in spec.role:
            return json.dumps({"ok": True, "issues": []})
        if b == "approval":
            v = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
            return json.dumps({"verdict": v, "reasons": [] if v == "accept" else ["missing proof"]})
        if b == "observer":
            return json.dumps({"issues": ["observer note"], "changes": []})
        return f"## Solution\nPROCESS-ONLY candidate {len(self.specs)} by {spec.role}"

    def by_block(self, block: str) -> list[AgentSpec]:
        return [s for s in self.specs if s.block == block]


# ── scale ───────────────────────────────────────────────────────────────────


def test_reference_distribution_is_exact_at_10000():
    a = allocate(10_000)
    assert all(a[b.key] == b.weight for b in BLOCKS)


@pytest.mark.parametrize("n", [MIN_TOTAL, 24, 50, 120, 333, 999, 5000])
def test_allocation_sums_and_respects_floors(n):
    a = allocate(n)
    assert sum(a.counts.values()) == n
    assert all(a[b.key] >= b.floor for b in BLOCKS)
    assert a["framing"] >= 5 and a["approval"] >= 1


def test_too_few_agents_is_an_error():
    with pytest.raises(ScaleError):
        allocate(MIN_TOTAL - 1)


def test_swarming_only_between_flexible_blocks():
    a = allocate(120)
    moved = a.borrow("production", "test_exec", 10, "surge")
    assert moved == 10
    assert a.effective("test_exec") == a["test_exec"] + 10
    assert a.effective("production") == a["production"] - 10
    for independent in (
        "framing",
        "test_design",
        "red_team",
        "evidence_audit",
        "approval",
        "observer",
    ):
        assert SPECS[independent].kind == "independent"
        with pytest.raises(ScaleError):
            a.borrow("production", independent, 1)
        with pytest.raises(ScaleError):
            a.borrow(independent, "production", 1)


def test_assign_spreads_work():
    assert assign(5, ["a", "b"]) == [["a"], ["b"], ["a"], ["b"], ["a"]]
    assert assign(2, ["a", "b", "c"]) == [["a", "c"], ["b"]]
    assert assign(0, ["a"]) == []


# ── agents ──────────────────────────────────────────────────────────────────


def test_parse_json_fenced_and_bare():
    assert parse_json('x ```json\n{"a": 1}\n``` y') == {"a": 1}
    assert parse_json('noise {"b": 2} noise') == {"b": 2}
    assert parse_json("no json here") is None


def test_safe_registry_drops_side_effect_tools():
    reg = ToolRegistry()
    for name, risk in (
        ("read_file", "safe"),
        ("write_file", "caution"),
        ("web_fetch", "caution"),
        ("run_shell", "danger"),
    ):
        reg.register(Tool(name=name, description="d", parameters={}, handler=None, risk=risk))  # type: ignore[arg-type]
    assert safe_registry(reg).names() == ["read_file"]
    assert sorted(safe_registry(reg, frozenset({"web_fetch"})).names()) == [
        "read_file",
        "web_fetch",
    ]
    assert "run_shell" not in safe_registry(reg, frozenset({"run_shell"})).names()


@pytest.mark.asyncio
async def test_swarm_pool_exhaustion_raises():
    fake = FakeCollective(tokens=100)
    swarm = Swarm(fake, max_parallel=1, max_tokens=150)
    spec = AgentSpec("production", "b", "g", "c", ["s"])
    await swarm.run([spec, spec])
    with pytest.raises(PoolExhausted):
        await swarm.run([spec])


@pytest.mark.asyncio
async def test_failed_agent_does_not_sink_phase():
    async def flaky(spec):
        if spec.role == "bad":
            raise RuntimeError("boom")
        return AgentReply("ok", 1)

    swarm = Swarm(flaky)
    out = await swarm.run(
        [AgentSpec("p", "bad", "g", "c", ["s"]), AgentSpec("p", "good", "g", "c", ["s"])]
    )
    assert out[1] == "ok" and out[0].startswith("(agent failed")


# ── IRADE ───────────────────────────────────────────────────────────────────


def _req(**kw):
    base = {
        "kind": "synthesis",
        "question": "which?",
        "options": [Option("A", "option a"), Option("B", "option b")],
        "impact": "high",
    }
    return DecisionRequest(**(base | kw))


@pytest.mark.asyncio
async def test_veto_beats_a_high_total():
    # Option 0 has the best total but one member scores its safety below the hard floor.
    fake = FakeCollective()

    def answer(spec, _orig=fake.answer):
        data = json.loads(_orig(spec))
        if spec.block == "irade":
            data["scores"]["A"] = dict.fromkeys(data["scores"]["A"], 1.0)
            if spec.seat == "council:risk":
                data["scores"]["A"]["safety"] = 0.1
            data["choice"] = "A"
        return json.dumps(data)

    fake.answer = answer  # type: ignore[method-assign]
    seen = {}

    async def human(req, dec):
        seen["escalations"] = dec.escalations
        return "A"  # the human has the last word, even over a veto

    irade = Irade(Swarm(fake), rng=random.Random(0))
    d = await irade.decide(_req())
    assert d.totals["A"] > d.totals["B"]
    assert "A" in d.vetoed and "safety" in d.vetoed["A"]
    # Every member wanted the vetoed option, so the council cannot agree on the
    # survivor: the veto escalates all the way to the human instead of silently passing.
    assert d.tier == 4 and d.choice is None
    d2 = await Irade(Swarm(fake), human=human, rng=random.Random(0)).decide(_req())
    assert d2.choice == "A" and any("vote share" in e for e in seen["escalations"])


@pytest.mark.asyncio
async def test_fast_path_uses_three_members_when_they_agree():
    fake = FakeCollective()
    irade = Irade(Swarm(fake), rng=random.Random(0))
    d = await irade.decide(_req())
    assert d.tier == 2 and d.choice == "A"
    assert len(fake.by_block("irade")) == 3


@pytest.mark.asyncio
async def test_disagreement_escalates_to_full_council_with_evidence():
    scores = {
        "correctness": {0: 0.9, 1: 0.2},
        "risk": {0: 0.1, 1: 0.95},
        "devils_advocate": {0: 0.2, 1: 0.9},
    }
    fake = FakeCollective(scores=scores)
    asked = []

    async def evidence(req):
        asked.append(req.kind)
        return "extra evidence"

    irade = Irade(Swarm(fake), evidence=evidence, rng=random.Random(0))
    d = await irade.decide(_req())
    assert d.tier >= 3
    assert asked == ["synthesis"]
    assert len(fake.by_block("irade")) == 3 + 5
    assert any("spread" in e or "vote share" in e for e in d.escalations)


@pytest.mark.asyncio
async def test_irreversible_goes_to_human_and_stops_without_one():
    fake = FakeCollective()
    irade = Irade(Swarm(fake), rng=random.Random(0))
    d = await irade.decide(_req(reversible=False))
    assert d.tier == 4 and d.stopped

    async def human(req, dec):
        return "B"

    irade2 = Irade(Swarm(FakeCollective()), human=human, rng=random.Random(0))
    d2 = await irade2.decide(_req(reversible=False))
    assert d2.tier == 4 and d2.choice == "B"


@pytest.mark.asyncio
async def test_low_impact_novel_then_precedent_then_policy():
    fake = FakeCollective()
    irade = Irade(Swarm(fake), settings=IradeSettings(audit_rate=0.0), rng=random.Random(0))
    first = await irade.decide(_req(kind="naming", impact="low"))
    assert first.tier == 2  # novel decision kind -> council
    again = await irade.decide(_req(kind="naming", impact="low"))
    assert again.tier == 1 and again.choice == first.choice  # JEV precedent
    other = await irade.decide(_req(kind="naming", question="another", impact="low"))
    assert other.tier == 0  # known kind, reversible, low impact -> policy


@pytest.mark.asyncio
async def test_random_audit_samples_low_tiers():
    fake = FakeCollective()
    irade = Irade(Swarm(fake), settings=IradeSettings(audit_rate=1.0), rng=random.Random(0))
    await irade.decide(_req(kind="naming", impact="low"))
    d = await irade.decide(_req(kind="naming", question="q2", impact="low"))
    assert d.tier == 0 and d.audit is not None


def test_calibrator_replaces_confidence_with_hit_rate(tmp_path):
    cal = Calibrator(tmp_path / "cal.jsonl")
    for ok in (True, False, False, False, False):
        cal.record(0.85, ok)
    assert cal.adjust(0.82) == pytest.approx(0.2)
    assert Calibrator(tmp_path / "cal.jsonl").adjust(0.82) == pytest.approx(0.2)  # persisted
    assert cal.adjust(0.3) == 0.3  # too few samples -> unchanged


# ── gates ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kapi3_is_blind_and_majority_based():
    fake = FakeCollective(verdicts=("accept", "reject", "accept"))
    v = await approve(
        Swarm(fake, max_parallel=1),
        request="R",
        criteria=["c1"],
        deliverable="D",
        evidence="E",
        n_agents=3,
    )
    assert v.accepted and v.accepts == 2 and v.rejects == 1
    assert v.reasons == ["missing proof"]


# ── observer ────────────────────────────────────────────────────────────────


def test_observer_flags_groupthink_and_collapse():
    o = Observer()
    o.check_candidates(["the same long answer text"] * 5, ["alpha"] * 5)
    assert any("groupthink" in w for w in o.warnings)
    assert any("collapse" in w for w in o.warnings)


# ── full runs ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_run_accepted_uses_every_block():
    fake = FakeCollective()
    imece = Imece(fake, ImeceSettings(agents=60, max_parallel=16), rng=random.Random(0))
    res = await imece.run("what is 2+2?")
    assert res.status == "accepted", res.notes
    assert res.deliverable
    alloc = imece.alloc
    for spec in BLOCKS:
        if spec.key == "human_interface" or alloc[spec.key] == 0:
            continue
        assert res.calls_by_block.get(spec.key, 0) >= 1, spec.key
    # Every builder slot really ran as a subagent.
    builders = [s for s in fake.by_block("production") if s.role.startswith("builder")]
    assert len(builders) == alloc["production"]
    assert res.retrospective == ["observer note"]


@pytest.mark.asyncio
async def test_independent_blocks_never_see_the_process():
    fake = FakeCollective()
    await Imece(fake, ImeceSettings(agents=40), rng=random.Random(0)).run("task")
    # Test design works from the frame alone — never a candidate.
    assert fake.by_block("test_design")
    assert all("PROCESS-ONLY" not in s.context for s in fake.by_block("test_design"))
    # Kapı 3 sees request, criteria, deliverable, evidence — no plans, no council talk.
    for s in fake.by_block("approval"):
        assert "Selected plan" not in s.context and "IRADE" not in s.context
        assert "Framed problem" not in s.context
    # Framing cells are independent of each other's output.
    cells = [s for s in fake.by_block("framing") if s.role.startswith("framing cell")]
    assert len(cells) == 5 and all("Independent framings" not in s.context for s in cells)
    # Cross-critics are never the author's own approach.
    for s in fake.by_block("production"):
        if s.role.startswith("cross-critic"):
            assert "not the author" in s.role


@pytest.mark.asyncio
async def test_rejection_feeds_a_second_round():
    fake = FakeCollective(verdicts=("reject", "accept"))
    res = await Imece(fake, ImeceSettings(agents=17, max_rounds=2), rng=random.Random(0)).run("t")
    assert res.status == "accepted" and res.rounds == 2
    round2_plans = [s for s in fake.by_block("plan") if "missing proof" in s.context]
    assert round2_plans


@pytest.mark.asyncio
async def test_budget_exhaustion_stops_cleanly():
    fake = FakeCollective(tokens=1000)
    res = await Imece(fake, ImeceSettings(agents=17, max_tokens=10_000), rng=random.Random(0)).run(
        "t"
    )
    assert res.status == "budget"


@pytest.mark.asyncio
async def test_human_stop_between_phases():
    calls = {"n": 0}

    def should_stop():
        calls["n"] += 1
        return calls["n"] > 2

    res = await Imece(FakeCollective(), ImeceSettings(agents=17), should_stop=should_stop).run("t")
    assert res.status == "stopped"


@pytest.mark.asyncio
async def test_unsafe_candidates_stop_at_synthesis_without_human():
    fake = FakeCollective(safety=0.05)  # every option vetoed on safety
    res = await Imece(fake, ImeceSettings(agents=17), rng=random.Random(0)).run("t")
    assert res.status == "stopped"


# ── config ──────────────────────────────────────────────────────────────────


def test_imece_config_defaults_and_validation():
    assert MilyonusConfig().imece.agents == 120
    with pytest.raises(ValidationError):
        ImeceConfig(agents=5)
    with pytest.raises(ValidationError):
        ImeceConfig.model_validate({"seats": {"nonsense": {"name": "anthropic"}}})
    with pytest.raises(ValidationError):
        ImeceConfig.model_validate({"allow_tools": ["run_shell"]})
    ok = ImeceConfig.model_validate(
        {"seats": {"council_risk": {"name": "openai", "model": "m"}}, "allow_tools": ["web_fetch"]}
    )
    assert ok.seats["council_risk"].model == "m"


@pytest.mark.asyncio
async def test_empty_reply_counts_as_failed_agent():
    async def thinker(spec):
        return AgentReply("", 4000)  # reasoning model spent everything thinking

    swarm = Swarm(thinker)
    [out] = await swarm.run([AgentSpec("production", "b", "g", "c", ["s"])])
    assert out.startswith("(agent failed")
    assert swarm.events[0].ok is False and swarm.used_tokens == 4000


def test_only_compliance_or_severe_findings_mark_irreversible():
    from milyonus.imece.gates import Finding, GateReport

    low = GateReport("c", findings=[Finding("red_team", "low", "aside", needs_human=True)])
    assert not low.needs_human()
    severe = GateReport("c", findings=[Finding("red_team", "high", "x", needs_human=True)])
    assert severe.needs_human()
    comp = GateReport("c", findings=[Finding("compliance", "low", "x", needs_human=True)])
    assert comp.needs_human()


@pytest.mark.asyncio
async def test_unreadable_votes_abstain_instead_of_vetoing():
    fake = FakeCollective()

    def answer(spec, _orig=fake.answer):
        if spec.seat in ("council:risk", "council:devils_advocate"):
            return "sorry, I cannot produce JSON"  # broken replies
        return _orig(spec)

    fake.answer = answer  # type: ignore[method-assign]
    irade = Irade(Swarm(fake), rng=random.Random(0))
    d = await irade.decide(_req(impact="strategic"))
    # 3 of 5 readable: quorum met, nothing vetoed, broken members abstain.
    assert d.choice == "A" and not d.vetoed
    assert sorted(d.abstained) == ["devils_advocate", "risk"]


@pytest.mark.asyncio
async def test_no_quorum_escalates_instead_of_vetoing():
    async def broken(spec):
        return AgentReply("not json", 1)

    d = await Irade(Swarm(broken), rng=random.Random(0)).decide(_req())
    assert d.tier == 4 and d.choice is None and not d.vetoed
    assert any("quorum" in e for e in d.escalations)
