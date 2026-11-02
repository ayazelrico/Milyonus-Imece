"""uv run python -m evals.imece.run --config FILE --backend macos --task clamp"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from milyonus.cli.imece_cmd import _seat_providers
from milyonus.config.env import load_env
from milyonus.config.loader import load_config
from milyonus.imece.agents import LLMAgentFn
from milyonus.imece.benchmark import TASKS, run_benchmark
from milyonus.imece.irade import IradeSettings
from milyonus.imece.orchestrator import ImeceSettings


async def main(args) -> int:
    load_env()
    cfg = load_config(args.config)
    seats, warnings = _seat_providers(cfg)
    for warning in warnings:
        print(f"warning: {warning}", flush=True)
    if warnings and not args.allow_shared_models:
        raise ValueError(
            "benchmark requires distinct council models and a separate approval model; use --allow-shared-models for explicitly labelled development runs"
        )
    ic = cfg.imece
    settings = ImeceSettings(
        agents=args.agents,
        max_parallel=ic.max_parallel,
        max_tokens=args.max_tokens,
        max_rounds=ic.max_rounds,
        max_clusters=ic.max_clusters,
        shortlist=ic.shortlist,
        pass_threshold=ic.pass_threshold,
        cell_size=ic.cell_size,
        verification="python",
        sandbox_backend=args.backend,
        sandbox_image=ic.sandbox_image,
        test_timeout=ic.test_timeout,
        agent_timeout=ic.agent_timeout,
        irade=IradeSettings(
            veto_floor=ic.veto_floor,
            hard_veto_floor=ic.hard_veto_floor,
            spread_threshold=ic.spread_threshold,
            audit_rate=ic.audit_rate,
        ),
    )
    prices = {}
    if args.live_prices:
        import httpx

        from milyonus.observability.cost import set_price

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get("https://openrouter.ai/api/v1/models")
            response.raise_for_status()
        wanted = {p.model for p in seats.values()}
        for model in response.json()["data"]:
            if model["id"] in wanted:
                price = model["pricing"]
                inp, out = (
                    float(price["prompt"]) * 1_000_000,
                    float(price["completion"]) * 1_000_000,
                )
                set_price(model["id"], inp, out)
                prices[model["id"]] = {"input_per_m": inp, "output_per_m": out}
    selected = tuple(t for t in TASKS if not args.task or t.id in args.task)
    real_agent = LLMAgentFn(seats=seats, max_output_tokens=ic.max_output_tokens)
    transcripts = []

    async def recorded(spec):
        try:
            reply = await real_agent(spec)
        except Exception as exc:
            from milyonus.security.redact import redact

            transcripts.append(
                {"spec": asdict(spec), "error": redact(f"{type(exc).__name__}: {exc}")}
            )
            raise
        transcripts.append({"spec": asdict(spec), "reply": asdict(reply)})
        return reply

    report = await run_benchmark(
        recorded,
        settings,
        tasks=selected,
        repeats=args.repeats,
        source="real-model",
        on_phase=lambda phase: print(phase, flush=True),
    )
    report["generated_at"] = datetime.now(UTC).isoformat()
    report["transcripts"] = transcripts
    report["models"] = {seat: p.model for seat, p in seats.items()}
    report["independence_warnings"] = warnings
    report["catalog_prices"] = prices
    report["price_note"] = (
        "Token-based catalog estimate, not a billing receipt; provider surcharges/caching/discounts may differ."
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"report: {args.out}")
    return 0 if report["summary"]["verified_successes"] == len(report["runs"]) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", type=Path, default=Path("imece-benchmark.json"))
    parser.add_argument("--backend", choices=("docker", "macos"), default="docker")
    parser.add_argument("--agents", type=int, default=17)
    parser.add_argument("--max-tokens", type=int, default=250_000)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--task", action="append", choices=[t.id for t in TASKS])
    parser.add_argument("--live-prices", action="store_true")
    parser.add_argument("--allow-shared-models", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
