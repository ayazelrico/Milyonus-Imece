"""CLI-only evals: --engine codex|antigravity --model MODEL; --prepare makes no model calls."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from evals.imece.dataset import load_suite
from evals.imece.protocol import digest, manifest, validate_rows
from milyonus.config.loader import load_config
from milyonus.config.paths import data_root
from milyonus.config.schema import IMECE_SEATS
from milyonus.imece.agents import AdmissionDenied, FatalAgentStateError
from milyonus.imece.antigravity import AntigravityAgentFn
from milyonus.imece.benchmark import TASKS, run_benchmark, summarize, trial_identity
from milyonus.imece.codex import (
    POLICY_VERSION,
    TEXT_ONLY_INSTRUCTIONS,
    CodexAgentFn,
    cli_environment,
    discover_codex,
    oracle_guard,
)
from milyonus.imece.irade import IradeSettings
from milyonus.imece.journal import (
    current_journal_call,
    fingerprint,
    reconcile_completed_calls,
    validated_reply,
)
from milyonus.imece.orchestrator import ImeceSettings

ROOT = Path(__file__).resolve().parents[2]
SHARED_MODEL_LIMITATION = (
    "CLI model identifiers are aliases, not evidence of independent models or providers. "
    "Distinct aliases do not establish council or approval independence."
)
PRICE_NOTE = (
    "CLI usage is not a billing receipt. Dollar cost is unknown (null), including "
    "failures/cancellations; no subscription-to-token price is invented. Token totals "
    "are null when any call lacks usage; observed_tokens is only a known lower bound."
)


def resolve_seat_models(model: str, overrides: list[str]) -> dict[str, str]:
    """Resolve config seat names (or runtime council names) before CLI discovery."""
    models = {seat.replace("council_", "council:", 1): model for seat in IMECE_SEATS}
    seen = set()
    for override in overrides:
        seat, separator, selected_model = override.partition("=")
        seat = seat.strip().replace("council_", "council:", 1)
        selected_model = selected_model.strip()
        if not separator or not seat or not selected_model:
            raise ValueError("--seat-model requires SEAT=MODEL with nonempty values")
        if seat not in models:
            raise ValueError(f"unknown imece seat: {seat!r}; valid: {', '.join(IMECE_SEATS)}")
        if seat in seen:
            raise ValueError(f"duplicate --seat-model seat: {seat}")
        seen.add(seat)
        models[seat] = selected_model
    if "repair" not in seen:
        models["repair"] = models["pool"]
    return models


def shared_model_limitation(models: dict[str, str]) -> str:
    groups: dict[str, list[str]] = {}
    for seat, model in models.items():
        groups.setdefault(model, []).append(seat)
    shared = {model: seats for model, seats in groups.items() if len(seats) > 1}
    return (
        f"Shared CLI model identifiers by seat: {json.dumps(shared, ensure_ascii=False)}. "
        + SHARED_MODEL_LIMITATION
    )


def atomic_write(path: Path, payload: dict) -> None:
    """Same-directory replace for prepared, initial, partial and final checkpoints."""
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


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
        or binding["identity_hash"] != identities[(task, repeat)]
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


def validate_call_records(entries, *, models: dict, identities: dict) -> None:
    """Require unique, ordered modern calls after an optional legacy prefix."""
    if not isinstance(entries, list):
        raise ValueError("invalid checkpoint transcripts: expected a list")
    seen_ids, seen_nodes = set(), set()
    modern_seen = False
    for sequence, entry in enumerate(entries):
        legacy = isinstance(entry, dict) and set(entry) in (
            {"spec", "reply"},
            {"spec", "error"},
        )
        validate_call_entry(entry, models=models, identities=identities, legacy=legacy)
        if legacy:
            if modern_seen:
                raise ValueError("legacy CLI transcripts must precede modern calls")
            continue
        modern_seen = True
        if entry["call_id"] in seen_ids:
            raise ValueError("duplicate CLI call ID")
        if entry["sequence"] != sequence:
            raise ValueError("CLI call sequence has a gap, duplicate or incorrect order")
        node = (entry["journal"]["identity_hash"], entry["journal"]["node_id"])
        if node in seen_nodes:
            raise ValueError("multiple CLI calls bound to one journal node")
        seen_ids.add(entry["call_id"])
        seen_nodes.add(node)


def validate_journals(
    directory: Path, tasks, repeats: int, frozen: dict, settings, seed: int, *, calls=None
):
    """Reject foreign/orphan files and identity mismatches before any replay/calls."""
    if not directory.exists():
        if calls and any(e.get("journal") is not None for e in calls):
            raise ValueError("bound CLI call has no journal")
        return
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("invalid journal directory")
    expected = {f"{t.id}-{i}.sqlite": (t, i) for t in tasks for i in range(repeats)}
    trial_calls = {}
    for entry in calls or []:
        if entry.get("journal") is None:
            continue
        task_id, repeat = entry.get("task"), entry.get("repeat")
        if (
            not isinstance(task_id, str)
            or type(repeat) is not int
            or f"{task_id}-{repeat}.sqlite" not in expected
            or not (directory / f"{task_id}-{repeat}.sqlite").is_file()
        ):
            raise ValueError("bound CLI call has no matching trial journal")
        trial_calls.setdefault((task_id, repeat), []).append(entry)
    for path in directory.iterdir():
        base = path.name.removesuffix("-wal").removesuffix("-shm").removesuffix("-journal")
        if path.is_symlink() or not path.is_file() or base not in expected:
            raise ValueError(f"orphan/foreign journal: {path.name}")
        if not (directory / base).is_file():
            raise ValueError(f"orphan journal sidecar: {path.name}")
        if path.name != base:
            continue
        task, repeat = expected[base]
        identity = trial_identity(task, repeat, settings, frozen, seed)
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT hash FROM identity WHERE id=1").fetchone()
            if row != (fingerprint(identity),):
                raise ValueError("journal run identity changed")
        if calls is not None:
            reconcile_completed_calls(
                path, identity=identity, calls=trial_calls.get((task.id, repeat), [])
            )


async def main(args) -> int:
    import fcntl

    if args.prepare and args.resume:
        raise ValueError("--prepare and --resume are mutually exclusive")
    if args.out == args.out.with_suffix(".lock"):
        raise ValueError("output cannot use the checkpoint lock path")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return await run(args)


async def run(args) -> int:
    if args.prepare and args.resume:
        raise ValueError("--prepare and --resume are mutually exclusive")
    journal_dir = args.out.with_suffix(".journal")
    ledger_path = args.out.with_suffix(".ledger.sqlite")
    call_dir = args.out.with_suffix(".calls")
    if not args.resume and (
        args.out.exists() or ledger_path.exists() or journal_dir.exists() or call_dir.exists()
    ):
        raise ValueError("output/ledger/journal already exists; choose a new experiment path")
    if args.resume and not args.out.is_file():
        raise ValueError(
            "resume requires an existing experiment checkpoint; orphan journal rejected"
        )
    previous = json.loads(args.out.read_text(encoding="utf-8")) if args.resume else None
    if args.resume and (
        not isinstance(previous, dict)
        or not isinstance(previous.get("manifest"), dict)
        or "runs" not in previous
        or previous.get("source") != args.engine
    ):
        raise ValueError("invalid checkpoint or engine mismatch")
    if ledger_path.exists():
        raise ValueError("CLI-only checkpoint cannot reuse a raw-provider ledger")
    if args.repeats < 1 or args.max_tokens < 1 or not args.model.strip():
        raise ValueError("positive repeats/token budget and explicit model required")
    model_mapping = resolve_seat_models(args.model, getattr(args, "seat_model", None) or [])
    limitation = shared_model_limitation(model_mapping)
    call_limit = getattr(args, "max_cli_calls", None)
    if call_limit is not None and call_limit < 1:
        raise ValueError("--max-cli-calls must be positive")
    if args.task and len(set(args.task)) != len(args.task):
        raise ValueError("duplicate task selection")

    cfg = load_config(args.config)
    ic = cfg.imece
    settings = ImeceSettings(
        agents=args.agents,
        max_parallel=ic.max_parallel,
        max_tokens=args.max_tokens,
        max_rounds=ic.max_rounds,
        max_clusters=ic.max_clusters,
        shortlist=ic.shortlist,
        approved_evidence=tuple(ic.approved_evidence),
        adaptive_production=ic.adaptive_production,
        repair_skill=ic.repair_skill,
        pass_threshold=ic.pass_threshold,
        cell_size=ic.cell_size,
        verification="python",
        sandbox_backend=args.backend,
        sandbox_image=args.image or ic.sandbox_image,
        test_timeout=ic.test_timeout,
        agent_timeout=ic.agent_timeout,
        irade=IradeSettings(
            veto_floor=ic.veto_floor,
            hard_veto_floor=ic.hard_veto_floor,
            spread_threshold=ic.spread_threshold,
            audit_rate=ic.audit_rate,
        ),
    )
    if settings.repair_skill is not None:
        from milyonus.skills.repair import load_repair_skill

        settings.repair_skill_sha256 = load_repair_skill(settings.repair_skill).sha256
    suite = TASKS if args.suite == "smoke" else load_suite(args.suite)
    selected = tuple(t for t in suite if not args.task or t.id in args.task)
    if not selected or (args.task and set(args.task) - {t.id for t in suite}):
        raise ValueError("unknown or empty task selection")
    # Validate the persisted subset first, before executable discovery/replay.
    if previous:
        validate_rows(previous["runs"], previous["manifest"]["protocol"])

    if args.engine == "codex":
        cli = discover_codex(args.executable)
    else:
        executable = shutil.which(args.executable or "agy")
        if not executable:
            raise ValueError("Antigravity CLI not found; supply --executable")
        executable = str(Path(executable).resolve())
        cli = {
            "executable": executable,
            "version": None,
            "sha256": digest(Path(executable).read_bytes().hex()),
        }
    protected = (
        ROOT,
        args.out.resolve(),
        journal_dir.resolve(),
        call_dir.resolve(),
        data_root() / "evidence",
    )
    guard = oracle_guard(protected)  # no unguarded fallback, even for Antigravity
    runtime = {
        "backend": args.backend,
        "image": settings.sandbox_image,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "engine": args.engine,
        "cli": cli,
        "agent_policy": POLICY_VERSION,
    }
    revision = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    frozen = manifest(
        tasks=selected,
        settings=settings,
        models=model_mapping,
        runtime=runtime,
        seed=args.seed,
        repeats=args.repeats,
        revision=revision,
    )
    frozen["implementation_hash"] = digest(
        {
            str(p.relative_to(ROOT)): digest(p.read_text(encoding="utf-8"))
            for root in (ROOT / "src/milyonus", ROOT / "evals/imece")
            for p in sorted(root.rglob("*.py"))
        }
    )
    declared_budget = getattr(args, "declared_budget_usd", None)
    if declared_budget is not None:
        from evals.imece.billing import money

        if money(declared_budget) <= 0:
            raise ValueError("declared USD budget must be positive")
        frozen["protocol"]["limits"]["declared_budget_usd"] = declared_budget
    if getattr(args, "failure_families", None):
        families = json.loads(args.failure_families.read_text(encoding="utf-8"))
        if (
            not isinstance(families, dict)
            or not families
            or set(families) - {task.id for task in selected}
            or not all(
                isinstance(name, str) and name.strip() and name == name.strip()
                for name in families.values()
            )
        ):
            raise ValueError("failure families must map selected task IDs to nonempty family names")
        frozen["protocol"]["failure_families"] = families
    frozen["protocol"]["limits"]["max_cli_calls"] = call_limit
    frozen["protocol_hash"] = digest(frozen["protocol"])
    frozen["capture_reproductions"] = getattr(args, "capture_reproductions", False)
    frozen["engine"] = args.engine
    compact = getattr(args, "compact_cli_instructions", False)
    if compact and args.engine != "codex":
        raise ValueError("compact CLI instructions require the Codex engine")
    frozen["cli_prompt_treatment"] = {
        "kind": "compact-text-only" if compact else "builtin",
        "instructions_hash": digest(TEXT_ONLY_INSTRUCTIONS) if compact else None,
    }
    frozen["max_output_tokens"] = None  # CLI has no enforced per-call output token flag
    frozen["catalog_prices"] = None
    frozen["shared_model_limitation"] = limitation
    # JSON round-trip so tuple/list (and other JSON-normalized) forms match the
    # checkpoint that was written by prepare/resume.
    if previous and previous["manifest"] != json.loads(json.dumps(frozen)):
        raise ValueError(
            "resume manifest differs: code, engine, models, runtime or settings changed"
        )
    checkpoint = (
        previous
        if previous is not None
        else {
            "schema_version": 1,
            "manifest": frozen,
            "source": args.engine,
            "engine": args.engine,
            "models": model_mapping,
            "runs": [],
            "transcripts": [],
            "ledger": None,
            "catalog_prices": None,
            "price_note": PRICE_NOTE,
            "independence_warnings": [limitation],
            "shared_model_limitation": limitation,
        }
    )
    transcripts = checkpoint.get("transcripts")
    identities = {
        (task.id, repeat): fingerprint(trial_identity(task, repeat, settings, frozen, args.seed))
        for task in selected
        for repeat in range(args.repeats)
    }
    validate_call_records(transcripts, models=model_mapping, identities=identities)
    # Merge into a separate list; reject all malformed evidence before changing
    # the checkpoint or reconciling any journal.
    transcripts = list(transcripts)
    # At dispatch time only the current call is written. On restart merge
    # its durable record, whether the crash preceded or followed the row snapshot.
    run_hash = digest(frozen)
    pending_paths = set()
    if call_dir.exists():
        if call_dir.is_symlink() or not call_dir.is_dir():
            raise ValueError("invalid pending call directory")
        by_id = {e["call_id"]: e for e in transcripts if "call_id" in e}
        recovered = []
        for path in sorted(call_dir.iterdir()):
            if re.fullmatch(r"\.[0-9a-f]{32}\.json\.[\w-]+\.tmp", path.name):
                continue  # incomplete atomic write was never dispatched/acknowledged
            if (
                path.is_symlink()
                or not path.is_file()
                or not re.fullmatch(r"[0-9a-f]{32}\.json", path.name)
            ):
                raise ValueError("invalid pending call file")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError(f"invalid pending call JSON: {path.name}") from exc
            if (
                not isinstance(payload, dict)
                or set(payload) != {"manifest_hash", "entry"}
                or payload["manifest_hash"] != run_hash
            ):
                raise ValueError(f"invalid pending call envelope/manifest: {path.name}")
            e = payload["entry"]
            try:
                validate_call_entry(e, models=model_mapping, identities=identities)
            except ValueError as exc:
                raise ValueError(f"invalid pending call {path.name}: {exc}") from exc
            if e["call_id"] != path.stem:
                raise ValueError(f"pending call filename/ID mismatch: {path.name}")
            if path.stem in by_id:
                # A running attempt from a previous process is now uncertain.
                saved = by_id[path.stem]
                if e["state"] == "running" and saved.get("state") == "unknown":
                    e["state"] = "unknown"
                if saved != e:
                    raise ValueError("pending call conflicts with checkpoint")
            else:
                recovered.append(e)
            pending_paths.add(path)
        for entry in sorted(recovered, key=lambda e: e["sequence"]):
            transcripts.append(entry)

    validate_call_records(transcripts, models=model_mapping, identities=identities)
    # Check every journal identity read-only before reconciliation can mutate one.
    validate_journals(journal_dir, selected, args.repeats, frozen, settings, args.seed)
    # Reconcile before checkpointing can remove the durable sidecars, and before
    # any replay or dispatch. Checkpointed replies are durable evidence too.
    validate_journals(
        journal_dir, selected, args.repeats, frozen, settings, args.seed, calls=transcripts
    )
    checkpoint["transcripts"] = transcripts

    def persist_call(entry):
        try:
            call_dir.mkdir(mode=0o700, exist_ok=True)
            path = call_dir / (entry["call_id"] + ".json")
            atomic_write(path, {"manifest_hash": run_hash, "entry": entry})
        except (OSError, ValueError, TypeError) as exc:
            raise FatalAgentStateError("cannot persist CLI call record") from exc
        pending_paths.add(path)

    # An interrupted CLI may have been charged; do not treat it as zero usage.
    for entry in transcripts:
        if entry.get("state") == "running":
            entry["state"] = "unknown"
    row_cursor = len(transcripts)
    # A crash can occur after journal completion but before a row checkpoint.
    # Retain uncertainty conservatively across resume instead of undercounting it.
    uncertain_trials = {
        (t.get("task"), t.get("repeat"))
        for t in transcripts
        if t.get("state") == "unknown" or "error" in t
    }

    def persist(state: str):
        checkpoint["state"] = state
        checkpoint["summary"] = summarize(checkpoint["runs"])
        checkpoint["accounting"] = {
            "cost_usd": None,
            "cost_status": "unknown",
            "token_budget": "completed-calls-only",
            "cli_call_limit": call_limit,
            "cli_calls_reserved": len(transcripts),
            "unknown_usage_calls": sum(
                t.get("state") in ("running", "unknown") for t in transcripts
            ),
        }
        checkpoint["updated_at"] = datetime.now(UTC).isoformat()
        atomic_write(args.out, checkpoint)
        for path in pending_paths:
            path.unlink(missing_ok=True)
        pending_paths.clear()

    if args.prepare:
        persist("prepared")
        print(
            f"prepared {len(selected) * args.repeats} runs; no model calls; checkpoint: {args.out}"
        )
        return 0
    adapters = {}
    for model in dict.fromkeys(model_mapping.values()):
        if args.engine == "codex":
            adapters[model] = CodexAgentFn(
                model=model,
                executable=cli["executable"],
                protected_paths=protected,
                timeout=settings.agent_timeout,
                max_parallel=settings.max_parallel,
                compact_instructions=compact,
            )
        else:
            adapters[model] = AntigravityAgentFn(
                model=model,
                agy_bin=cli["executable"],
                timeout=settings.agent_timeout,
                max_parallel=settings.max_parallel,
                command_prefix=tuple(guard),
                environment=cli_environment(),
            )
    # Keep the existing total concurrency limit across all routed models.
    dispatch_slots = asyncio.Semaphore(settings.max_parallel)

    async def recorded(spec):
        from milyonus.security.redact import redact

        if call_limit is not None and len(transcripts) >= call_limit:
            raise AdmissionDenied("experiment CLI call limit reached before dispatch")
        model = model_mapping[spec.seat]
        binding = current_journal_call.get()
        if binding is None or binding["spec_hash"] != fingerprint(asdict(spec)):
            raise FatalAgentStateError("CLI dispatch outside matching journal node")
        if (binding["task"], binding["repeat"]) in uncertain_trials or (
            None,
            None,
        ) in uncertain_trials:
            raise AdmissionDenied("trial has an uncertain CLI call; reconciliation required")
        entry = {
            "call_id": uuid.uuid4().hex,
            "sequence": len(transcripts),
            "task": binding["task"],
            "repeat": binding["repeat"],
            "journal": dict(binding),
            "spec": asdict(spec),
            "model": model,
            "state": "running",
        }
        transcripts.append(entry)
        persist_call(entry)  # durable before launch
        try:
            async with dispatch_slots:
                reply = await adapters[model](spec)
            try:
                payload = asdict(reply)
                output_hash = fingerprint(payload)
                validated_reply(payload, output_hash)
            except (ValueError, TypeError, OverflowError) as exc:
                raise FatalAgentStateError("invalid completed CLI reply") from exc
        except BaseException as exc:
            # Freeze this trial immediately, not only after a process restart.
            # Other calls already in flight remain accounted for independently.
            uncertain_trials.add((binding["task"], binding["repeat"]))
            entry.update(state="unknown", error=redact(f"{type(exc).__name__}: {exc}"))
            persist_call(entry)
            raise
        entry.update(state="completed", reply=payload, output_hash=output_hash)
        persist_call(entry)
        return reply

    def save_row(row):
        nonlocal row_cursor
        entries = transcripts[row_cursor:]
        if (
            (row["task"], row["repeat"]) in uncertain_trials
            or (None, None) in uncertain_trials
            or any(t.get("state") != "completed" for t in entries)
        ):
            row["observed_tokens"] = row["tokens"]
            row["tokens"] = None
        row_cursor = len(transcripts)
        row["cost_usd"] = None
        checkpoint["runs"].append(row)
        persist("partial")

    initial_row_count = len(checkpoint["runs"])

    def can_begin_trial(task_id, repeat):
        # An existing journal can finish from replay even at the limit. Any
        # genuinely new dispatch still has to pass the admission check.
        return (
            call_limit is None
            or len(transcripts) < call_limit
            or (journal_dir / f"{task_id}-{repeat}.sqlite").is_file()
        )

    persist("running")
    try:
        report = await run_benchmark(
            recorded,
            settings,
            tasks=selected,
            repeats=args.repeats,
            source=args.engine,
            on_phase=lambda phase: print(phase, flush=True),
            seed=args.seed,
            on_row=save_row,
            capture_reproductions=frozen["capture_reproductions"],
            can_begin_trial=can_begin_trial,
            should_stop=lambda: bool(
                len(checkpoint["runs"]) > initial_row_count
                and checkpoint["runs"][-1]["status"] == "budget"
            ),
            completed_rows=checkpoint["runs"],
            journal_dir=journal_dir,
            run_identity=frozen,
        )
    except BaseException:
        persist("interrupted")
        raise
    checkpoint.update(report)
    checkpoint["generated_at"] = datetime.now(UTC).isoformat()
    complete = len(checkpoint["runs"]) == len(selected) * args.repeats
    persist("complete" if complete else "partial")
    print(json.dumps(checkpoint["summary"], indent=2))
    print(f"report: {args.out}")
    return 0 if checkpoint["summary"]["verified_successes"] == len(selected) * args.repeats else 2


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", type=Path, default=Path("imece-benchmark.json"))
    parser.add_argument("--engine", choices=("codex", "antigravity"), required=True)
    parser.add_argument("--model", required=True, help="explicit fallback CLI model identifier")
    parser.add_argument(
        "--compact-cli-instructions",
        action="store_true",
        help="Codex-only explicit prompt treatment: replace built-in instructions with a frozen text-only brief",
    )
    parser.add_argument(
        "--seat-model",
        action="append",
        metavar="SEAT=MODEL",
        help="override an Imece seat's CLI model; repeat for different seats",
    )
    parser.add_argument(
        "--executable", help="CLI executable; Codex auto-discovers validated bundles"
    )
    parser.add_argument("--backend", choices=("docker", "macos"), default="docker")
    parser.add_argument("--agents", type=int, default=17)
    parser.add_argument(
        "--max-cli-calls",
        type=int,
        help="hard limit on all CLI dispatch attempts across this experiment, including resume",
    )
    parser.add_argument(
        "--declared-budget-usd",
        help="record a USD ceiling for retrospective receipt reconciliation; not enforced by CLI",
    )
    parser.add_argument("--max-tokens", type=int, default=250_000)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--task", action="append")
    parser.add_argument(
        "--failure-families",
        type=Path,
        help="predeclared JSON mapping of task IDs to recurring defect families",
    )
    parser.add_argument(
        "--capture-reproductions",
        action="store_true",
        help="include small candidate code and failing generated checks in local reports",
    )
    parser.add_argument("--suite", choices=("smoke", "core-v1", "core-v2"), default="smoke")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--image")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--prepare", action="store_true", help="atomic checkpoint, no model calls")
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(make_parser().parse_args())))
