"""Frozen experiment identity and fail-closed 5X comparison (no API calls)."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import random
import re
from dataclasses import asdict
from typing import Any

from evals.imece.efficiency import paired_efficiency, repair_family_outcomes
from milyonus.imece.benchmark import BenchmarkTask, _matches, _score_artifact, summarize

TREATMENT_SETTINGS = frozenset(
    {"adaptive_production", "approved_evidence", "repair_skill", "repair_skill_sha256"}
)


def execution_controls(settings: dict) -> dict:
    return {k: v for k, v in settings.items() if k not in TREATMENT_SETTINGS}


def describe_treatments(baseline: dict, candidate: dict) -> dict:
    factors = [
        k
        for k in sorted(TREATMENT_SETTINGS)
        if baseline.get("settings", {}).get(k) != candidate.get("settings", {}).get(k)
    ]
    builtin = {"kind": "builtin", "instructions_hash": None}
    if baseline.get("cli_prompt_treatment", builtin) != candidate.get(
        "cli_prompt_treatment", builtin
    ):
        factors.append("cli_prompt")
    if baseline.get("implementation_hash") != candidate.get("implementation_hash"):
        factors.append("implementation")
    return {
        "factors": factors,
        "single_factor": len(factors) == 1,
        "isolated_compact_prompt": factors == ["cli_prompt"],
        "note": "Joint treatment results cannot be attributed to an individual factor.",
    }


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def manifest(
    *,
    tasks: tuple[BenchmarkTask, ...],
    settings,
    models: dict,
    runtime: dict,
    seed: int,
    repeats: int,
    revision: str,
) -> dict:
    if repeats < 1 or not tasks or len({t.id for t in tasks}) != len(tasks):
        raise ValueError("nonempty unique tasks and positive repeats required")
    protocol = {
        "schema_version": 2,
        "scorer_hash": digest([inspect.getsource(_score_artifact), inspect.getsource(_matches)]),
        "tasks": [
            {
                "id": t.id,
                "contract": digest(t.request),
                "oracle": digest([t.oracle, t.cases]),
                "scoring_mode": "host_cases" if t.cases else "uncertified_script",
            }
            for t in tasks
        ],
        "models": models,
        "runtime": runtime,
        "seed": seed,
        "repeats": repeats,
        "limits": {k: getattr(settings, k) for k in ("max_tokens", "max_rounds", "test_timeout")},
        "execution_controls": execution_controls(asdict(settings)),
    }
    return {
        "protocol": protocol,
        "protocol_hash": digest(protocol),
        "settings": asdict(settings),
        "revision": revision,
    }


def validate_rows(rows: list[dict], protocol: dict, *, complete: bool = False) -> list[dict]:
    """Validate a unique subset before any resume/replay or new model calls."""
    tasks, repeats = protocol["tasks"], protocol["repeats"]
    if (
        type(repeats) is not int
        or repeats < 1
        or not tasks
        or any(not isinstance(t.get("id"), str) or not t["id"] for t in tasks)
        or len({t["id"] for t in tasks}) != len(tasks)
    ):
        raise ValueError("invalid task matrix")
    if not isinstance(rows, list):
        raise ValueError("invalid task/repeat matrix")
    expected = {(t["id"], i) for t in tasks for i in range(repeats)}
    actual = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("task"), str)
            or type(row.get("repeat")) is not int
        ):
            raise ValueError("invalid task/repeat matrix")
        key = (row["task"], row["repeat"])
        if key not in expected or key in actual:
            raise ValueError("out-of-range or duplicate task/repeat matrix")
        actual.add(key)
        cost = row.get("cost_usd")
        if cost is not None and (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(cost)
            or cost < 0
        ):
            raise ValueError("invalid cost")
        tokens = row.get("tokens")
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ValueError("invalid tokens")
        for field in ("seconds", "elapsed_s"):
            if field in row and (
                type(row[field]) not in (int, float)
                or not math.isfinite(row[field])
                or row[field] < 0
            ):
                raise ValueError(f"invalid {field}")
        for field in ("unknown_usage_calls", "observed_tokens"):
            if field in row and (type(row[field]) is not int or row[field] < 0):
                raise ValueError(f"invalid {field}")
        if "cost_estimated" in row and type(row["cost_estimated"]) is not bool:
            raise ValueError("invalid cost estimate flag")
        confidence = row.get("confidence")
        if confidence is not None and (
            type(confidence) not in (int, float)
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("invalid confidence")
        if (
            row.get("status") not in ("accepted", "rejected", "stopped", "budget", "error")
            or type(row.get("oracle_passed")) is not bool
        ):
            raise ValueError("invalid outcome")
    if complete and actual != expected:
        raise ValueError("incomplete task/repeat matrix")
    return rows


def validate_report(report: dict) -> list[dict]:
    if "state" in report and report["state"] != "complete":
        raise ValueError("report is not complete")
    m = report["manifest"]
    p = m["protocol"]
    if digest(p) != m["protocol_hash"]:
        raise ValueError("manifest hash mismatch")
    engine = p.get("runtime", {}).get("engine")
    if engine is not None and report.get("source") != engine:
        raise ValueError("report source differs from engine manifest")
    if (
        engine in ("codex", "antigravity") or report.get("source") in ("codex", "antigravity")
    ) and report.get("ledger") is not None:
        raise ValueError("CLI report cannot contain a provider ledger; external receipts required")
    if "execution_controls" in p and p["execution_controls"] != execution_controls(m["settings"]):
        raise ValueError("settings differ from frozen execution controls")
    return validate_rows(report["runs"], p, complete=True)


def wilson(successes: int, n: int) -> list[float] | None:
    if not n:
        return None
    z = 1.959963984540054
    p = successes / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [max(0, center - half), min(1, center + half)]


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _cli_independence_verified(protocol: dict, audit: dict) -> bool:
    """Check externally reviewed provenance, not merely distinct CLI aliases.

    The caller must first validate the attestation against both complete reports.
    No provider lookup or authenticity check of the external evidence is implied.
    """
    council = (
        "council:correctness",
        "council:risk",
        "council:user_impact",
        "council:cost_speed",
        "council:devils_advocate",
    )
    critical = ("pool", "approval", *council)
    models = protocol.get("models")
    evidence = audit.get("model_independence")
    if (
        not isinstance(models, dict)
        or not isinstance(evidence, dict)
        or not _nonempty_string(evidence.get("reference"))
        or not isinstance(evidence.get("seats"), dict)
    ):
        return False
    if models.get("repair", models.get("pool")) != models.get("pool"):
        critical = (*critical, "repair")
    aliases, provenance, vendors = set(), set(), set()
    for seat in critical:
        alias = models.get(seat)
        reviewed = evidence["seats"].get(seat)
        if (
            not _nonempty_string(alias)
            or not isinstance(reviewed, dict)
            or reviewed.get("alias") != alias
            or not _nonempty_string(reviewed.get("vendor"))
            or not _nonempty_string(reviewed.get("model"))
        ):
            return False
        normalized_alias = alias.strip().casefold()
        vendor = reviewed["vendor"].strip().casefold()
        identity = (vendor, reviewed["model"].strip().casefold())
        if normalized_alias in aliases or identity in provenance:
            return False
        aliases.add(normalized_alias)
        provenance.add(identity)
        # Each council member and approval must have a different actual vendor.
        if seat in (*council, "approval"):
            if vendor in vendors:
                return False
            vendors.add(vendor)
    return True


def _cli_alias_warning(models: dict) -> str:
    """Recognize only the exact warning emitted by the CLI report writer."""
    groups: dict[str, list[str]] = {}
    for seat, model in models.items():
        groups.setdefault(model, []).append(seat)
    shared = {model: seats for model, seats in groups.items() if len(seats) > 1}
    return (
        f"Shared CLI model identifiers by seat: {json.dumps(shared, ensure_ascii=False)}. "
        "CLI model identifiers are aliases, not evidence of independent models or providers. "
        "Distinct aliases do not establish council or approval independence."
    )


def compare(
    baseline: dict,
    candidate: dict,
    *,
    audit: dict | None = None,
    baseline_receipts: dict | None = None,
    candidate_receipts: dict | None = None,
) -> dict:
    """No cherry-picking: require the complete matching experiment matrix.

    Confidence interval uses paired task-cluster bootstrap: repeats of a task
    are correlated, so they are resampled together. Audit is an explicit external
    attestation tied to both report hashes, never inferred from a test pass.
    """
    base, cand = validate_report(baseline), validate_report(candidate)
    if baseline["manifest"]["protocol_hash"] != candidate["manifest"]["protocol_hash"]:
        raise ValueError(
            "incomparable protocols (oracle, models, runtime, seeds or limits changed)"
        )
    # Keep raw reports immutable: hashes attest the original transcript, and
    # separate receipt hashes attest the external accounting used for the ratio.
    settlements = {}
    if (baseline_receipts is None) != (candidate_receipts is None):
        raise ValueError("supply receipts for both versions or neither")
    if baseline_receipts is not None:
        from evals.imece.billing import reconcile

        for role, report, statement, rows in (
            ("baseline", baseline, baseline_receipts, base),
            ("candidate", candidate, candidate_receipts, cand),
        ):
            if (
                report.get("source") not in ("codex", "antigravity")
                or report.get("ledger") is not None
            ):
                raise ValueError("external receipts are only supported for unpriced CLI reports")
            settlement = reconcile(report, statement)
            settlements[role] = settlement
            costs = {(r["task"], r["repeat"]): float(r["usd"]) for r in settlement["trials"]}
            adjusted = [
                dict(r, cost_usd=costs[r["task"], r["repeat"]], cost_estimated=False) for r in rows
            ]
            if role == "baseline":
                base = adjusted
            else:
                cand = adjusted
    b, c = summarize(base), summarize(cand)
    blockers = []
    protocol = baseline["manifest"]["protocol"]
    if "execution_controls" not in protocol:
        blockers.append("shared execution controls were not frozen")
    if any(t.get("scoring_mode") != "host_cases" for t in protocol["tasks"]):
        blockers.append("host-side case scoring required for certification")
    audit_valid = (
        isinstance(audit, dict)
        and audit.get("baseline_hash") == digest(baseline)
        and audit.get("candidate_hash") == digest(candidate)
        and type(audit.get("critical_findings")) is int
        and audit["critical_findings"] == 0
        and _nonempty_string(audit.get("reviewer"))
        and _nonempty_string(audit.get("reference"))
    )
    cli_reports = protocol.get("runtime", {}).get("engine") in ("codex", "antigravity") or any(
        r.get("source") in ("codex", "antigravity") for r in (baseline, candidate)
    )
    independence_verified = (
        cli_reports and audit_valid and _cli_independence_verified(protocol, audit)
    )
    if cli_reports and not independence_verified:
        blockers.append("CLI model independence evidence missing or invalid")
    if len(base) < 250 or len(protocol["tasks"]) < 50 or protocol["repeats"] < 5:
        blockers.append("requires at least 50 tasks × 5 repeats per version")
    valid_sources = ("real-model", "antigravity", "codex")
    if baseline.get("source") not in valid_sources or candidate.get("source") not in valid_sources:
        blockers.append("real-model evidence required")
    image = protocol.get("runtime", {}).get("image", "")
    has_pinned_digest = (
        isinstance(image, str)
        and "@sha256:" in image
        and bool(re.search(r"@sha256:[0-9a-f]{64}$", image))
    )
    if protocol.get("runtime", {}).get("backend") != "docker" or not has_pinned_digest:
        blockers.append("pinned Docker image required")
    for role, report in (("baseline", baseline), ("candidate", candidate)):
        warnings = report.get("independence_warnings")
        if independence_verified:
            models = protocol["models"]
            # Malformed mappings/warnings cannot be used to erase unrelated warnings.
            known_warning = (
                _cli_alias_warning(models)
                if all(_nonempty_string(k) and _nonempty_string(v) for k, v in models.items())
                else None
            )
            unresolved = warnings is not None and (
                not isinstance(warnings, list)
                or any(known_warning is None or warning != known_warning for warning in warnings)
            )
        else:
            unresolved = bool(warnings)
        if unresolved:
            blockers.append("independence warning detected")
        ledger = report.get("ledger")
        if ledger is None:
            settlement = settlements.get(role)
            if (
                not settlement
                or not audit_valid
                or audit.get(f"{role}_receipts_hash") != settlement["receipts_hash"]
            ):
                blockers.append("unresolved charges or reservation overruns")
            else:
                from evals.imece.billing import money

                ceiling = protocol["limits"].get("declared_budget_usd")
                if ceiling is None or money(settlement["total_usd"]) > money(ceiling):
                    blockers.append("predeclared experiment budget missing or exceeded")
        else:
            if not isinstance(ledger, dict) or any(
                type(ledger.get(field)) is not int or ledger[field] != 0
                for field in ("unknown_calls", "overruns")
            ):
                blockers.append("unresolved charges or reservation overruns")
    gain = None
    if b["cost_estimated"] or c["cost_estimated"]:
        blockers.append("verified billing required; estimated costs cannot establish 5X")
    if b["cost_usd"] is None or c["cost_usd"] is None or b["cost_usd"] <= 0 or c["cost_usd"] <= 0:
        blockers.append("complete positive total costs required")
    elif not b["verified_successes"]:
        blockers.append("baseline has no verified successes")
    else:
        gain = (c["verified_successes"] / c["cost_usd"]) / (b["verified_successes"] / b["cost_usd"])
        if gain < 5:
            blockers.append("measured gain below 5X")
    if c["verified_success_rate"] < b["verified_success_rate"] - 0.02:
        blockers.append("verified success rate dropped by more than 2 percentage points")
    if b["false_accepts"] or c["false_accepts"]:
        blockers.append("observed false acceptance")
    if not audit_valid:
        blockers.append("independent audit attestation missing or mismatched")
    interval = None
    if gain is not None:
        tasks = sorted({r["task"] for r in base})
        bs = {t: summarize([r for r in base if r["task"] == t]) for t in tasks}
        cs = {t: summarize([r for r in cand if r["task"] == t]) for t in tasks}
        rng = random.Random(0)
        samples = []
        for _ in range(2000):
            selection = rng.choices(tasks, k=len(tasks))
            bv = sum(bs[t]["verified_successes"] for t in selection)
            cv = sum(cs[t]["verified_successes"] for t in selection)
            bc = sum(bs[t]["cost_usd"] for t in selection)
            cc = sum(cs[t]["cost_usd"] for t in selection)
            if bv and bc and cc:
                samples.append((cv / cc) / (bv / bc))
        if samples:
            samples.sort()
            interval = [
                samples[int(0.025 * (len(samples) - 1))],
                samples[int(0.975 * (len(samples) - 1))],
            ]
    return {
        "accepted_5x": not blockers,
        "treatments": describe_treatments(baseline["manifest"], candidate["manifest"]),
        "blockers": list(dict.fromkeys(blockers)),
        "gain": gain,
        "receipt_hashes": {k: v["receipts_hash"] for k, v in settlements.items()},
        "gain_task_bootstrap_95pct": interval,
        "phase_efficiency": paired_efficiency(base, cand, b, c),
        "repair_families": repair_family_outcomes(base, cand, protocol.get("failure_families", {})),
        "baseline": b,
        "candidate": c,
        "baseline_success_wilson_95pct": wilson(b["verified_successes"], len(base)),
        "candidate_success_wilson_95pct": wilson(c["verified_successes"], len(cand)),
        "note": "Intervals describe this corpus, not production generalization; audit attestation requires human provenance review.",
    }
