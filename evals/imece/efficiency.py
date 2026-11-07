"""Phase-specific observations on complete paired trials; no inferred dollar gain."""

from __future__ import annotations

import re
from collections import Counter


def _gate_sample(row: dict):
    report = row.get("report") or {}
    metrics = report.get("metrics", {})
    started = metrics.get("gate_processes_started")
    if type(started) is not int or started < 0:
        return None
    workload = Counter()
    reused = 0
    for gate in report.get("gate_reports", []):
        for check in gate.get("test_results", []):
            identity = check.get("evidence_id")
            if (
                not isinstance(identity, str)
                or not identity
                or type(check.get("reused")) is not bool
            ):
                return None
            workload[identity] += 1
            reused += check["reused"]
    if not workload or sum(workload.values()) != started + reused:
        return None
    metadata = metrics.get("gate_metadata_processes_started")
    return workload, started, metadata if type(metadata) is int and metadata >= 0 else None


def paired_efficiency(
    base: list[dict], cand: list[dict], baseline_summary: dict, candidate_summary: dict
) -> dict:
    indexed = {(r["task"], r["repeat"]): r for r in cand}
    matched = base_calls = cand_calls = 0
    metadata_pairs = base_metadata = cand_metadata = 0
    for row in base:
        other = indexed[row["task"], row["repeat"]]
        left, right = _gate_sample(row), _gate_sample(other)
        if left is not None and right is not None and left[0] == right[0]:
            matched += 1
            base_calls += left[1]
            cand_calls += right[1]
            if left[2] is not None and right[2] is not None:
                metadata_pairs += 1
                base_metadata += left[2]
                cand_metadata += right[2]
    reduction = 1 - cand_calls / base_calls if base_calls else None
    metadata_complete = matched > 0 and metadata_pairs == matched
    base_total = base_calls + base_metadata if metadata_complete else None
    cand_total = cand_calls + cand_metadata if metadata_complete else None
    b = baseline_summary["tokens_per_verified_success"]
    c = candidate_summary["tokens_per_verified_success"]
    ratio = c / b if b is not None and b > 0 and c is not None else None
    return {
        "gate_trials_with_identical_workload": matched,
        "gate_trials_total": len(base),
        "matched_baseline_processes": base_calls,
        "matched_candidate_processes": cand_calls,
        "matched_process_reduction": reduction,
        "matched_gate_trials_with_metadata_counts": metadata_pairs,
        "matched_baseline_gate_metadata_processes": base_metadata if metadata_complete else None,
        "matched_candidate_gate_metadata_processes": cand_metadata if metadata_complete else None,
        "matched_baseline_total_gate_processes": base_total,
        "matched_candidate_total_gate_processes": cand_total,
        "matched_total_gate_process_reduction": (
            1 - cand_total / base_total if base_total and cand_total is not None else None
        ),
        "full_matrix_gate_reduction_at_least_60pct": (
            reduction >= 0.6 if reduction is not None and matched == len(base) else None
        ),
        "candidate_to_baseline_tokens_per_verified_success": ratio,
        "token_cost_at_most_half": ratio <= 0.5 if ratio is not None else None,
    }


def repair_family_outcomes(base: list[dict], cand: list[dict], families: dict[str, str]) -> dict:
    """Use the frozen task assignment, including trials where no repair was attempted."""
    right = {(r["task"], r["repeat"]): r for r in cand}
    result = {}
    exposed_tasks: dict[str, set[str]] = {}
    rejected = {
        "no_candidate",
        "production_gate_rejected",
        "revision_gate_rejected",
        "integration_gate_rejected",
        "polish_gate_rejected",
        "approval_rejected",
    }
    terminal = rejected | {"accepted"}

    def skill_briefing(trial):
        report = trial.get("report") or {}
        briefings = report.get("applied_repair_skills", [])
        rounds = report.get("rounds")
        if not isinstance(briefings, list):
            return None
        if not briefings:
            return False
        if type(rounds) is not int or any(
            not isinstance(entry, dict)
            or entry.get("response_received") is not True
            or type(entry.get("round")) is not int
            or not 2 <= entry["round"] <= rounds
            or not isinstance(entry.get("name"), str)
            or not entry["name"].strip()
            or not isinstance(entry.get("skill_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", entry["skill_sha256"])
            for entry in briefings
        ):
            return None
        return True

    def failed_rounds(trial):
        report = trial.get("report") or {}
        history, rounds = report.get("round_outcomes"), report.get("rounds")
        status = trial["status"]
        if (
            status not in ("accepted", "rejected")
            or not isinstance(history, list)
            or not history
            or type(rounds) is not int
            or len(history) != rounds
            or any(not isinstance(outcome, str) or outcome not in terminal for outcome in history)
            or history.count("accepted") != int(status == "accepted")
            or (status == "accepted" and history[-1] != "accepted")
        ):
            return None
        return sum(outcome in rejected for outcome in history)

    for row in base:
        family = families.get(row["task"])
        if family is None:
            continue
        group = result.setdefault(
            family,
            {
                "paired_trials": 0,
                "candidate_trials_with_skill_briefing": 0,
                "baseline_trials_with_skill_briefing": 0,
                "pairs_with_invalid_skill_briefing": 0,
                "baseline_verified_in_exposed_pairs": 0,
                "candidate_verified_in_exposed_pairs": 0,
                "incomplete_pairs": 0,
                "baseline_failed_rounds": 0,
                "candidate_failed_rounds": 0,
                "baseline_verified": 0,
                "candidate_verified": 0,
            },
        )
        other = right[row["task"], row["repeat"]]
        group["paired_trials"] += 1
        baseline_exposed, exposed = skill_briefing(row), skill_briefing(other)
        group["pairs_with_invalid_skill_briefing"] += int(
            baseline_exposed is None or exposed is None
        )
        group["candidate_trials_with_skill_briefing"] += int(exposed is True)
        group["baseline_trials_with_skill_briefing"] += int(baseline_exposed is True)
        if exposed:
            exposed_tasks.setdefault(family, set()).add(row["task"])
        for label, trial in (("baseline", row), ("candidate", other)):
            verified = int(trial["status"] == "accepted" and trial["oracle_passed"])
            group[label + "_verified"] += verified
            if exposed:
                group[label + "_verified_in_exposed_pairs"] += verified
        b, c = failed_rounds(row), failed_rounds(other)
        if b is not None and c is not None:
            group["baseline_failed_rounds"] += b
            group["candidate_failed_rounds"] += c
        else:
            group["incomplete_pairs"] += 1

    for family, group in result.items():
        b, c = group["baseline_failed_rounds"], group["candidate_failed_rounds"]
        group["failed_round_reduction"] = 1 - c / b if b and not group["incomplete_pairs"] else None
        group["verified_rate_change_pp"] = (
            100
            * (group["candidate_verified"] - group["baseline_verified"])
            / group["paired_trials"]
        )
        group["candidate_distinct_tasks_with_skill_briefing"] = len(exposed_tasks.get(family, ()))
        group["observed_family_threshold_met"] = None
        if (
            group["failed_round_reduction"] is not None
            and group["candidate_distinct_tasks_with_skill_briefing"] >= 2
            and group["baseline_trials_with_skill_briefing"] == 0
            and group["pairs_with_invalid_skill_briefing"] == 0
        ):
            group["observed_family_threshold_met"] = (
                group["failed_round_reduction"] >= 0.5
                and group["candidate_verified"] >= group["baseline_verified"]
                and group["candidate_verified_in_exposed_pairs"]
                >= group["baseline_verified_in_exposed_pairs"]
            )
    return result
