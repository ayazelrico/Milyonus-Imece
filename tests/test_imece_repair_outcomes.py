"""Repair evidence needs a usable response and complete paired outcomes."""

import pytest
from evals.imece.efficiency import repair_family_outcomes

from milyonus.imece.agents import AgentReply, PoolExhausted
from milyonus.imece.gates import Frame, GateReport
from milyonus.imece.orchestrator import Candidate, Imece, ImeceSettings, RunResult
from milyonus.skills.repair import RepairSkill

FAILED = "production_gate_rejected"
BRIEFING = {"round": 2, "name": "example", "skill_sha256": "a" * 64, "response_received": True}


def trial(task, history, *, briefing=(), status="accepted", verified=True, repeat=0):
    return {
        "task": task,
        "repeat": repeat,
        "status": status,
        "oracle_passed": verified,
        "report": {
            "rounds": len(history),
            "round_outcomes": history,
            "applied_repair_skills": list(briefing),
        },
    }


@pytest.mark.parametrize(
    "condition",
    [
        "met",
        "regression",
        "incomplete",
        "misordered",
        "empty",
        "one_task",
        "control_exposed",
        "legacy_briefing",
    ],
)
def test_repair_threshold_uses_complete_matrix_and_confirmed_exposure(condition):
    tasks = ["a", "b"] if condition != "one_task" else ["a", "a"]
    base = [trial(task, [FAILED, FAILED, "accepted"], repeat=i) for i, task in enumerate(tasks)]
    cand = [
        trial(task, [FAILED, "accepted"], briefing=[BRIEFING], repeat=i)
        for i, task in enumerate(tasks)
    ]
    if condition == "regression":
        cand[0]["oracle_passed"] = False
    elif condition == "incomplete":
        cand[0].update(status="budget", oracle_passed=False)
    elif condition == "misordered":
        cand[0]["report"]["round_outcomes"] = ["accepted", FAILED]
    elif condition == "empty":
        cand[0].update(status="rejected", oracle_passed=False)
        cand[0]["report"].update(rounds=0, round_outcomes=[], applied_repair_skills=[])
    elif condition == "control_exposed":
        base[0]["report"]["applied_repair_skills"] = [BRIEFING]
    elif condition == "legacy_briefing":
        cand[0]["report"]["applied_repair_skills"] = [
            {k: v for k, v in BRIEFING.items() if k != "response_received"}
        ]
    result = repair_family_outcomes(base, cand, {"a": "family", "b": "family"})["family"]
    expected = {"met": True, "regression": False}.get(condition)
    assert result["paired_trials"] == 2
    assert result["observed_family_threshold_met"] is expected
    if condition in {"incomplete", "misordered", "empty"}:
        assert result["incomplete_pairs"] == 1 and result["failed_round_reduction"] is None


@pytest.mark.parametrize("response", ["usable", "empty", "budget"])
async def test_repair_briefing_is_recorded_only_after_usable_reply(monkeypatch, response):
    monkeypatch.setattr(
        "milyonus.imece.orchestrator.load_repair_skill",
        lambda name: RepairSkill(name, "a" * 64, "Example"),
    )

    async def agent(spec):
        if spec.seat == "repair":
            assert "Example" in spec.context
            if response == "budget":
                raise PoolExhausted("budget exhausted")
            return AgentReply("artifact" if response == "usable" else "", 1)
        return AgentReply("other artifact", 1)

    imece = Imece(agent, ImeceSettings(agents=17, repair_skill="example"))
    result = RunResult("rejected", "r")
    production = imece._produce(
        2,
        Frame("r", "p", ("correct",)),
        "",
        "",
        "",
        [("alpha", "solve")],
        [],
        repair=(Candidate("A", "alpha", 0, "code"), GateReport("A")),
        builders=1,
        result=result,
    )
    if response == "budget":
        with pytest.raises(PoolExhausted):
            await production
    else:
        await production
    assert result.applied_repair_skills == ([BRIEFING] if response == "usable" else [])
