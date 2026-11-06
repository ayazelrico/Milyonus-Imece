"""Explicit no-change reviews can omit writers, never independent re-testing."""

import json
import os

import pytest

from milyonus.imece.agents import AgentReply
from milyonus.imece.gates import Finding, Frame, GateReport
from milyonus.imece.orchestrator import Candidate, Imece, ImeceSettings, RunResult
from test_imece import FakeCollective

ARTIFACT = "```python file=solution.py\ndef twice(x): return x*2\n```"
CLEAN = '{"revision_needed": false, "findings": []}'


def scenario(answer=CLEAN, *, adaptive=True):
    specs = []

    async def agent(spec):
        specs.append(spec)
        text = answer if spec.role.startswith("cross-critic") else "revised candidate"
        return AgentReply(text, 1)

    imece = Imece(
        agent, ImeceSettings(agents=17, verification="python", adaptive_production=adaptive)
    )
    candidates = [Candidate("A", "alpha", 0, ARTIFACT), Candidate("B", "beta", 1, ARTIFACT)]
    reports = {
        c.id: GateReport(
            c.id,
            passed=True,
            verification="python:docker",
            test_results=[
                {
                    "test": "T1",
                    "passed": True,
                    "returncode": 0,
                    "source": "python:docker",
                    "failure_class": None,
                    "output_truncated": False,
                    "environment_id": "a" * 64,
                }
            ],
        )
        for c in candidates
    }
    return imece, candidates, reports, specs


async def test_unanimous_clean_reviews_keep_exact_candidates_and_omit_writers():
    imece, candidates, reports, specs = scenario()
    result = RunResult("rejected", "r")
    revised = await imece._cross_critique(
        candidates, Frame("r", "p", ("correct",)), reports=reports, result=result
    )
    assert revised == candidates and all(a is b for a, b in zip(revised, candidates, strict=True))
    assert len(specs) == 2 and all(s.role.startswith("cross-critic") for s in specs)
    assert all("Other candidate for crossover" in s.context for s in specs)
    assert imece.observer.metrics["revision_calls_avoided"] == 2
    assert "re-testing remains required" in result.notes[0]


@pytest.mark.parametrize(
    "answer",
    [
        "no issues",
        "```json\n" + CLEAN + "\n```",
        '{"revision_needed": 0, "findings": []}',
        '{"revision_needed": false, "findings": ["change needed"]}',
        '{"revision_needed": true, "findings": ["change needed"]}',
        '{"revision_needed": false, "findings": [], "extra": true}',
        '{"revision_needed": true, "revision_needed": false, "findings": []}',
    ],
)
async def test_non_clean_or_malformed_reviews_keep_normal_revision(answer):
    imece, candidates, reports, specs = scenario(answer)
    revised = await imece._cross_critique(
        candidates, Frame("r", "p", ("correct",)), reports=reports
    )
    assert len(specs) == 4 and all(c.solution == "revised candidate" for c in revised)
    assert "revision_calls_avoided" not in imece.observer.metrics


@pytest.mark.parametrize(
    "proof",
    [
        "nonadaptive",
        "missing",
        "failed",
        "finding",
        "model",
        "environment",
        "mixed_environment",
        "truncated",
        "empty",
        "contract",
    ],
)
async def test_ineligible_gate_evidence_cannot_omit_writers(proof):
    imece, candidates, reports, specs = scenario(adaptive=proof != "nonadaptive")
    frame = Frame("r", "p", ("correct",))
    if proof == "missing":
        reports = None
    elif proof == "failed":
        reports["A"].passed = False
    elif proof == "finding":
        reports["A"].findings.append(Finding("audit", "low", "review this"))
    elif proof == "model":
        reports["A"].verification = "model"
    elif proof == "environment":
        reports["A"].test_results[0]["environment_id"] = None
    elif proof == "mixed_environment":
        reports["A"].test_results[0]["environment_id"] = "b" * 64
    elif proof == "truncated":
        reports["A"].test_results[0]["output_truncated"] = True
    elif proof == "empty":
        reports["A"].test_results = []
    elif proof == "contract":
        frame = None
    await imece._cross_critique(candidates, frame, reports=reports)
    assert len(specs) == 4 and "revision_calls_avoided" not in imece.observer.metrics


async def test_one_actionable_critique_preserves_revision_for_every_candidate():
    imece, candidates, reports, specs = scenario()
    calls = 0

    async def mixed(spec):
        nonlocal calls
        specs.append(spec)
        calls += 1
        return AgentReply(
            CLEAN if calls == 1 else '{"revision_needed": true, "findings": ["fix"]}', 1
        )

    imece.swarm._fn = mixed
    await imece._cross_critique(candidates, Frame("r", "p", ("correct",)), reports=reports)
    assert len(specs) == 4 and "revision_calls_avoided" not in imece.observer.metrics


@pytest.mark.skipif(os.environ.get("MILYONUS_TEST_DOCKER") != "1", reason="Docker opt-in")
@pytest.mark.parametrize("bad_merge", [False, True])
async def test_real_docker_clean_revision_keeps_retest_and_final_gates(bad_merge):
    from evals.imece.cache_probe import DEFAULT_IMAGE

    class Collective(FakeCollective):
        def answer(self, spec):
            if spec.block == "test_design":
                return json.dumps(
                    {
                        "tests": [
                            {
                                "check": "twice works",
                                "python": "from solution import twice; assert twice(3)==6",
                            }
                        ]
                    }
                )
            if spec.block == "production":
                return CLEAN if spec.role.startswith("cross-critic") else ARTIFACT
            if spec.block == "integration" and "integrity" not in spec.role:
                return ARTIFACT.replace("x*2", "x*3") if bad_merge else ARTIFACT
            return super().answer(spec)

    fake = Collective()
    result = await Imece(
        fake,
        ImeceSettings(
            agents=17,
            max_rounds=1,
            verification="python",
            sandbox_image=DEFAULT_IMAGE,
            adaptive_production=True,
        ),
    ).run("Return twice(x)")
    assert result.metrics["revision_calls_avoided"] == 2
    assert not any(s.role.startswith("author revising") for s in fake.specs)
    assert len(result.gate_reports) >= 5  # production, unchanged re-test, integration
    assert result.status == ("rejected" if bad_merge else "accepted")
    if bad_merge:
        assert result.round_outcomes == ["integration_gate_rejected"]
        assert not fake.by_block("approval")
    else:
        assert fake.by_block("approval")
