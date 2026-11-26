"""Live İmece War Room hub for Web Surface #7 (PLAN-MOONSHOT M3).

Runs the real `Imece` multi-agent collective in background per-tenant asyncio
tasks, streams phase transitions (`Kapı 1 → 2 → 3`) over durable monotonic SSE
events, supports interactive Emergency Stop (`should_stop`), and attaches a
verifiable `.milyonus-proof.json` capsule to completed runs.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from milyonus.config.loader import load_config
from milyonus.imece.agents import AgentFn, AgentReply, AgentSpec, LLMAgentFn, Stopped
from milyonus.imece.orchestrator import Imece, ImeceSettings
from milyonus.imece.scale import MIN_TOTAL, allocate
from milyonus.memory.store import MemoryStore
from milyonus.providers.router import build_provider
from milyonus.security.proof import build_imece_proof
from milyonus.web.store import WebStore


def _dry_run_agent(task: str, *, step_delay_s: float = 0.0) -> AgentFn:
    """Deterministic zero-spend collective simulator driving the real `Imece` orchestrator."""
    counter = 0

    async def _call(spec: AgentSpec) -> AgentReply:
        nonlocal counter
        counter += 1
        if step_delay_s > 0:
            await asyncio.sleep(step_delay_s)
        b, ctx = spec.block, spec.context
        if b == "framing":
            return AgentReply(
                json.dumps(
                    {
                        "problem": f"Framed objective: {task[:180]}",
                        "success_criteria": [
                            "Directly resolves the stated task",
                            "Verified by independent gate",
                        ],
                        "disciplines": ["architecture", "verification"],
                        "divergences": ["Independent cells compared minimal vs modular structure"],
                    }
                ),
                tokens=24,
            )
        if b == "test_design":
            return AgentReply(
                json.dumps(
                    {"tests": [{"check": "Directly resolves the stated task", "how": "inspect"}]}
                ),
                tokens=18,
            )
        if b == "test_exec":
            ids = re.findall(r"## Candidate (\S+)", ctx)
            return AgentReply(
                json.dumps(
                    {"results": [{"candidate": cid, "test": "T1", "pass": True} for cid in ids]}
                ),
                tokens=16,
            )
        if b in ("red_team", "evidence_audit", "compliance"):
            if "## Candidate" in ctx:
                return AgentReply(json.dumps({"findings": []}), tokens=14)
            return AgentReply("- independent audit verified", tokens=12)
        if b == "plan":
            return AgentReply(
                json.dumps({"title": f"Plan #{counter}", "steps": ["Frame", "Build", "Verify"]}),
                tokens=18,
            )
        if b == "command":
            return AgentReply(
                json.dumps(
                    {
                        "approaches": [
                            {"name": "structured", "idea": "Modular verified decomposition"},
                            {"name": "minimal", "idea": "Compact direct synthesis"},
                        ]
                    }
                ),
                tokens=20,
            )
        if b == "irade":
            ids = re.findall(r"## Option (\S+)", ctx)
            scores: dict[str, dict[str, float]] = {}
            for oid in ids:
                scores[oid] = {
                    "correctness": 0.88,
                    "cost": 0.85,
                    "speed": 0.86,
                    "safety": 0.92,
                    "legal": 0.95,
                    "reversibility": 0.90,
                }
            best = ids[0] if ids else "opt_1"
            return AgentReply(
                json.dumps(
                    {
                        "scores": scores,
                        "choice": best,
                        "confidence": 0.91,
                        "rationale": "Highest verified correctness and safety margin",
                    }
                ),
                tokens=22,
            )
        if b == "integration" and "integrity" in spec.role:
            return AgentReply(json.dumps({"ok": True, "issues": []}), tokens=12)
        if b == "approval":
            return AgentReply(json.dumps({"verdict": "accept", "reasons": []}), tokens=16)
        return AgentReply(
            f"# Verified Deliverable (Dry-Run Collective)\n\n"
            f"**Task:** {task}\n\n"
            f"Produced by role `{spec.role}` and verified through Kapı 1 → Kapı 2 → Kapı 3.\n",
            tokens=30,
        )

    return _call


@dataclass
class ImeceHandle:
    run_id: str
    user_id: str
    stop_event: threading.Event = field(default_factory=threading.Event)
    seq: int = 0
    task: asyncio.Task[None] | None = None


class ImeceRunHub:
    """Manages live İmece War Room runs across tenants with SSE replay & emergency stop."""

    def __init__(self, store: WebStore) -> None:
        self.store = store
        self._handles: dict[str, ImeceHandle] = {}

    def get_handle(self, run_id: str) -> ImeceHandle | None:
        return self._handles.get(run_id)

    def _emit(self, handle: ImeceHandle, typ: str, payload: dict[str, Any]) -> dict[str, Any]:
        handle.seq += 1
        return self.store.append_imece_event(handle.run_id, handle.seq, typ, payload)

    async def start_run(
        self,
        *,
        user_id: str,
        task: str,
        agents: int = MIN_TOTAL,
        verification: Literal["model", "python"] = "model",
        dry_run: bool = True,
        home: Path,
        step_delay_s: float = 0.0,
    ) -> dict[str, Any]:
        clamped_agents = max(MIN_TOTAL, min(10_000, int(agents)))
        alloc = allocate(clamped_agents)
        mode = "dry_run" if dry_run else "live"
        run_id = self.store.create_imece_run(
            user_id=user_id,
            task=task,
            agents=clamped_agents,
            verification=verification,
            mode=mode,
        )
        handle = ImeceHandle(run_id=run_id, user_id=user_id)
        self._handles[run_id] = handle

        async def _execute() -> None:
            t0 = time.perf_counter()
            self._emit(
                handle,
                "imece.started",
                {
                    "run_id": run_id,
                    "agents": clamped_agents,
                    "mode": mode,
                    "allocation": dict(alloc.counts),
                },
            )
            try:
                if dry_run:
                    agent_fn: AgentFn = _dry_run_agent(task, step_delay_s=step_delay_s)
                else:
                    cfg = load_config(home / "config.toml")
                    base = build_provider(cfg.provider)
                    seats = {
                        "pool": base,
                        "framing": base,
                        "test": base,
                        "approval": base,
                        "irade": base,
                    }
                    agent_fn = LLMAgentFn(
                        seats=seats, max_output_tokens=cfg.imece.max_output_tokens
                    )

                settings = ImeceSettings(
                    agents=clamped_agents,
                    max_parallel=4 if dry_run else 8,
                    max_rounds=1,
                    verification="model" if dry_run else verification,
                )

                def _on_phase(phase_name: str) -> None:
                    self.store.update_imece_phase(run_id, phase_name)
                    self._emit(
                        handle,
                        "imece.phase",
                        {
                            "run_id": run_id,
                            "phase": phase_name,
                            "elapsed_s": round(time.perf_counter() - t0, 3),
                        },
                    )

                collective = Imece(
                    agent_fn,
                    settings,
                    should_stop=handle.stop_event.is_set,
                    on_phase=_on_phase,
                )
                result = await collective.run(task)
                report = result.to_dict()
                ms = MemoryStore(home / "state.db")
                try:
                    proof = build_imece_proof(report, subject_id=run_id, memory_store=ms)
                finally:
                    ms.close()
                report["proof"] = proof
                was_stopped = result.status == "stopped"
                accepted = result.status == "accepted"
                final_state = "stopped" if was_stopped else "completed"
                self.store.finish_imece_run(run_id, state=final_state, report=report)
                self._emit(
                    handle,
                    "imece.stopped" if was_stopped else "imece.completed",
                    {
                        "run_id": run_id,
                        "status": result.status,
                        "accepted": accepted,
                        "stopped": was_stopped,
                        "rounds": result.rounds,
                        "used_tokens": result.tokens,
                        "proof_merkle_root": proof["merkle_root"],
                    },
                )
            except Stopped as exc:
                self.store.finish_imece_run(run_id, state="stopped", error=str(exc))
                self._emit(
                    handle,
                    "imece.stopped",
                    {"run_id": run_id, "reason": str(exc)},
                )
            except Exception as exc:  # noqa: BLE001 - surface error over SSE
                self.store.finish_imece_run(run_id, state="error", error=str(exc))
                self._emit(
                    handle,
                    "imece.error",
                    {"run_id": run_id, "message": str(exc)},
                )
            finally:
                self._handles.pop(run_id, None)

        handle.task = asyncio.create_task(_execute())
        return {
            "id": run_id,
            "agents": clamped_agents,
            "mode": mode,
            "allocation": dict(alloc.counts),
        }

    def request_stop(self, run_id: str) -> bool:
        handle = self._handles.get(run_id)
        if handle is None:
            return False
        handle.stop_event.set()
        return True
