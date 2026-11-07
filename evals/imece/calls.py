"""Shared validation for durable CLI call records."""

import re

from milyonus.imece.journal import fingerprint, validated_reply


def validate_call_entry(entry, *, models: dict, identities: dict, legacy: bool = False) -> None:
    """Validate stored data without filling in missing identity or completion evidence."""
    if not isinstance(entry, dict):
        raise ValueError("CLI call entry must be an object")
    spec = entry.get("spec")
    if (
        not isinstance(spec, dict)
        or set(spec)
        != {
            "block",
            "role",
            "goal",
            "context",
            "success_criteria",
            "seat",
            "forbidden",
            "use_tools",
        }
        or any(not isinstance(spec[k], str) for k in ("block", "role", "goal", "context", "seat"))
        or any(
            not isinstance(spec[k], list) or any(not isinstance(v, str) for v in spec[k])
            for k in ("success_criteria", "forbidden")
        )
        or type(spec["use_tools"]) is not bool
        or spec["seat"] not in models
    ):
        raise ValueError("invalid CLI call spec or seat")
    if legacy:
        # Only the original, unidentified spec+reply/spec+error format is exempt.
        # Identified calls missing a binding must never fall through to this path.
        if set(entry) == {"spec", "reply"}:
            validated_reply(entry["reply"], fingerprint(entry["reply"]))
        elif set(entry) != {"spec", "error"} or not isinstance(entry["error"], str):
            raise ValueError("invalid legacy CLI transcript")
        return
    required = {"call_id", "sequence", "task", "repeat", "journal", "spec", "model", "state"}
    if not required <= set(entry) or set(entry) - required - {"reply", "output_hash", "error"}:
        raise ValueError("invalid modern CLI call fields (journal binding required)")
    if not isinstance(entry["call_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", entry["call_id"]):
        raise ValueError("CLI call ID must be UUID hex")
    if type(entry["sequence"]) is not int or entry["sequence"] < 0:
        raise ValueError("CLI call sequence must be a nonnegative integer")
    task, repeat = entry["task"], entry["repeat"]
    if not isinstance(task, str) or type(repeat) is not int or (task, repeat) not in identities:
        raise ValueError("CLI call task/repeat is outside the frozen run")
    if not isinstance(entry["model"], str) or entry["model"] != models[spec["seat"]]:
        raise ValueError("CLI call model differs from frozen seat routing")
    if entry["state"] not in ("running", "unknown", "completed"):
        raise ValueError("invalid CLI call state")
    binding = entry["journal"]
    if (
        not isinstance(binding, dict)
        or set(binding) != {"identity_hash", "node_id", "spec_hash", "task", "repeat"}
        or any(
            not isinstance(binding[k], str) or not re.fullmatch(r"[0-9a-f]{64}", binding[k])
            for k in ("identity_hash", "node_id", "spec_hash")
        )
        or (
            identities[(task, repeat)] is not None
            and binding["identity_hash"] != identities[(task, repeat)]
        )
        or binding["task"] != task
        or type(binding["repeat"]) is not int
        or binding["repeat"] != repeat
        or binding["spec_hash"] != fingerprint(spec)
    ):
        raise ValueError("CLI call journal binding/spec hash mismatch")
    if entry["state"] == "completed":
        if "error" in entry:
            raise ValueError("completed CLI call contains an error")
        validated_reply(entry.get("reply"), entry.get("output_hash"))
    elif "reply" in entry or "output_hash" in entry:
        raise ValueError("unfinished CLI call contains completion data")
    if "error" in entry and not isinstance(entry["error"], str):
        raise ValueError("CLI call error must be text")


def validate_call_records(
    entries, *, models: dict, identities: dict, allow_legacy: bool = True
) -> None:
    """Require unique, ordered modern calls after an optional legacy prefix."""
    if not isinstance(entries, list):
        raise ValueError("invalid checkpoint transcripts: expected a list")
    seen_ids, seen_nodes = set(), set()
    trial_bindings = {}
    modern_seen = False
    for sequence, entry in enumerate(entries):
        legacy = isinstance(entry, dict) and set(entry) in (
            {"spec", "reply"},
            {"spec", "error"},
        )
        validate_call_entry(entry, models=models, identities=identities, legacy=legacy)
        if legacy:
            if not allow_legacy:
                raise ValueError("unattributed legacy CLI call in frozen report")
            if modern_seen:
                raise ValueError("legacy CLI transcripts must precede modern calls")
            continue
        modern_seen = True
        if entry["call_id"] in seen_ids:
            raise ValueError("duplicate CLI call ID")
        if entry["sequence"] != sequence:
            raise ValueError("CLI call sequence has a gap, duplicate or incorrect order")
        node = (entry["journal"]["identity_hash"], entry["journal"]["node_id"])
        trial = (entry["task"], entry["repeat"])
        if trial_bindings.setdefault(trial, node[0]) != node[0]:
            raise ValueError("inconsistent CLI journal identity for trial")
        if node in seen_nodes:
            raise ValueError("multiple CLI calls bound to one journal node")
        seen_ids.add(entry["call_id"])
        seen_nodes.add(node)
