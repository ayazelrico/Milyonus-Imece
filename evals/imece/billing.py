"""Reconcile CLI call receipts against a complete, immutable benchmark report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from evals.imece.protocol import digest, validate_report


def money(value: object) -> Decimal:
    if not isinstance(value, str) or len(value) > 32:
        raise ValueError("expected a decimal USD string")
    try:
        n = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid USD amount") from exc
    if not n.is_finite() or n < 0 or n.as_tuple().exponent < -12 or n > 10**9:
        raise ValueError("invalid USD amount or unsupported precision")
    return n


def reconcile(report: dict, receipts: dict) -> dict:
    rows = validate_report(report)
    report_hash = digest(report)
    if not isinstance(receipts, dict):
        raise ValueError("receipts must be an object")
    if receipts.get("report_hash") != report_hash or receipts.get("currency") != "USD":
        raise ValueError("receipts must identify the exact report and use USD")
    if (
        not isinstance(receipts.get("statement_reference"), str)
        or not receipts["statement_reference"].strip()
    ):
        raise ValueError("missing external billing statement reference")
    row_keys = {(r["task"], r["repeat"]) for r in rows}
    calls = {}
    transcripts = report.get("transcripts")
    if not isinstance(transcripts, list):
        raise ValueError("report must contain CLI transcripts")
    for entry in transcripts:
        if not isinstance(entry, dict):
            raise ValueError("CLI call record must be an object")
        call_id = entry.get("call_id")
        trial = (entry.get("task"), entry.get("repeat"))
        if (
            not isinstance(call_id, str)
            or not call_id
            or call_id in calls
            or not isinstance(trial[0], str)
            or type(trial[1]) is not int
            or trial not in row_keys
        ):
            raise ValueError("unattributed or duplicate CLI call; cannot reconcile this report")
        calls[call_id] = trial
    if not calls:
        raise ValueError("no recorded CLI calls")
    seen, references = set(), set()
    totals = Counter()
    charges = receipts.get("charges")
    if not isinstance(charges, list):
        raise ValueError("receipt charges must be a list")
    for line in charges:
        if not isinstance(line, dict) or set(line) != {"call_id", "line_reference", "usd"}:
            raise ValueError("each charge requires call_id, line_reference and usd")
        call_id, ref = line["call_id"], line["line_reference"]
        if (
            not isinstance(call_id, str)
            or call_id not in calls
            or call_id in seen
            or not isinstance(ref, str)
            or not ref.strip()
            or ref in references
        ):
            raise ValueError("unknown call, duplicate charge, or invalid billing line reference")
        seen.add(call_id)
        references.add(ref)
        totals[calls[call_id]] += money(line["usd"])
    if seen != calls.keys():
        raise ValueError("every attempted call needs a receipt, including failures")
    total = sum(totals.values(), Decimal(0))
    if total != money(receipts.get("total_usd")):
        raise ValueError("sum of itemized charges differs from statement total")
    return {
        "source_report_hash": report_hash,
        "receipts_hash": digest(receipts),
        "statement_reference": receipts["statement_reference"],
        "currency": "USD",
        "calls_reconciled": len(calls),
        "total_usd": str(total),
        "trials": [{"task": t, "repeat": i, "usd": str(totals[t, i])} for t, i in sorted(row_keys)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("receipts", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = reconcile(json.loads(args.report.read_text()), json.loads(args.receipts.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
