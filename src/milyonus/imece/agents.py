"""Running imece agents as real subagents, many at once.

Every imece agent is one subagent run under a delegation contract (goal +
context + success criteria). Agents in the same phase run concurrently, capped
by `max_parallel`, and all of them draw from one shared token pool so a run with
hundreds of agents cannot spend without limit.

The agent function is injectable: production uses `LLMAgentFn` (a real
AgentLoop per agent); tests pass a deterministic fake.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from milyonus.core.budget import Budget
from milyonus.core.loop import AgentLoop
from milyonus.delegation.subagent import DelegationContract, _restricted_registry
from milyonus.observability.cost import cost_of
from milyonus.providers.base import Message, Provider
from milyonus.tools.registry import ToolRegistry


@dataclass(slots=True)
class AgentSpec:
    """One agent's job. `seat` names the model seat it runs on (see providers)."""

    block: str
    role: str
    goal: str
    context: str
    success_criteria: list[str]
    seat: str = "pool"
    forbidden: list[str] = field(default_factory=list)
    use_tools: bool = False

    def contract(self) -> DelegationContract:
        return DelegationContract(
            goal=self.goal,
            context=self.context,
            success_criteria=self.success_criteria,
            forbidden=self.forbidden,
        )


@dataclass(slots=True)
class AgentReply:
    text: str
    tokens: int = 0
    cost_usd: float | None = None
    cost_estimated: bool = True


AgentFn = Callable[[AgentSpec], Awaitable[AgentReply]]


class PoolExhausted(Exception):
    """The shared token pool ran out; the run stops with what it has."""


class AdmissionDenied(PoolExhausted):
    """The configured budget rejected the call before any provider dispatch."""


class Stopped(Exception):
    """The operator requested that execution stop."""


class FatalAgentStateError(ValueError):
    """Agent state could not be trusted or persisted; abort the run."""


@dataclass(slots=True)
class AgentEvent:
    block: str
    role: str
    seat: str
    tokens: int
    ok: bool
    cost_usd: float | None = None
    cost_estimated: bool = True
    usage_known: bool = True


class Swarm:
    """Runs agent specs concurrently against a shared token pool."""

    def __init__(
        self,
        agent_fn: AgentFn,
        *,
        max_parallel: int = 8,
        max_tokens: int = 2_000_000,
        agent_timeout: float = 300.0,
        should_stop: Callable[[], bool] | None = None,
    ):
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        self._fn = agent_fn
        self.max_parallel = max_parallel
        self.agent_timeout = agent_timeout
        self._should_stop = should_stop
        self._sem = asyncio.Semaphore(max_parallel)
        self._workers: set[asyncio.Task[None]] = set()
        self._fatal_error: FatalAgentStateError | None = None
        self.max_tokens = max_tokens
        self.used_tokens = 0
        self.events: list[AgentEvent] = []

    def exhausted(self) -> bool:
        return self.used_tokens >= self.max_tokens

    async def _one(self, spec: AgentSpec) -> str:
        async with self._sem:
            if self._fatal_error is not None:
                raise self._fatal_error from None
            if self._should_stop and self._should_stop():
                raise Stopped("operator stopped queued work")
            if self.exhausted():
                raise PoolExhausted(f"token pool exhausted ({self.used_tokens}/{self.max_tokens})")
            try:
                reply = await asyncio.wait_for(self._fn(spec), self.agent_timeout)
            except FatalAgentStateError as exc:
                if self._fatal_error is None:
                    self._fatal_error = exc
                raise
            except (PoolExhausted, Stopped):
                raise
            except asyncio.CancelledError:
                # A dispatched call may still have consumed quota.
                self.events.append(
                    AgentEvent(spec.block, spec.role, spec.seat, 0, False, usage_known=False)
                )
                raise
            except Exception as exc:  # one failed agent must not sink the phase
                self.events.append(
                    AgentEvent(spec.block, spec.role, spec.seat, 0, False, usage_known=False)
                )
                return f"(agent failed: {type(exc).__name__}: {exc})"
            self.used_tokens += reply.tokens
            if not reply.text.strip() or reply.text.startswith("(budget exhausted"):
                # An empty answer (e.g. a reasoning model that spent its whole
                # output budget thinking) is a failed agent, not a candidate.
                self.events.append(
                    AgentEvent(
                        spec.block,
                        spec.role,
                        spec.seat,
                        reply.tokens,
                        False,
                        reply.cost_usd,
                        reply.cost_estimated,
                    )
                )
                return "(agent failed: empty reply)"
            self.events.append(
                AgentEvent(
                    spec.block,
                    spec.role,
                    spec.seat,
                    reply.tokens,
                    True,
                    reply.cost_usd,
                    reply.cost_estimated,
                )
            )
            return reply.text

    async def run(self, specs: Sequence[AgentSpec]) -> list[str]:
        """Run all specs; results come back in the same order."""
        # Bounded workers, rather than one asyncio task per agent. A 100k-agent
        # run has O(parallelism) live tasks, with deterministic output order.
        out = [""] * len(specs)
        jobs = iter(enumerate(specs))

        async def worker() -> None:
            for index, spec in jobs:
                out[index] = await self._one(spec)

        workers = [asyncio.create_task(worker()) for _ in range(min(len(specs), self.max_parallel))]
        self._workers.update(workers)
        batch = asyncio.gather(*workers)
        try:
            if self._should_stop:
                while not batch.done():
                    await asyncio.wait([batch], timeout=0.25)
                    if self._should_stop():
                        raise Stopped("operator stopped active work")
            await batch
        except BaseException:
            # Parallel batches share the journal. Drain them before reporting a
            # budget or stop result because cancellation can expose a write failure.
            active_workers = tuple(self._workers)
            for task in active_workers:
                if not task.done() and not task.cancelling():
                    task.cancel()
            await asyncio.gather(batch, *active_workers, return_exceptions=True)
            if self._fatal_error is not None:
                raise self._fatal_error from None
            raise
        finally:
            self._workers.difference_update(workers)
        return out

    def failed_by_block(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.events:
            if not e.ok:
                out[e.block] = out.get(e.block, 0) + 1
        return out

    def calls_by_block(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.events:
            out[e.block] = out.get(e.block, 0) + 1
        return out


_SUBAGENT_SYSTEM = (
    "You are one agent in Milyonus-Imece, a large collective. You see only the "
    "briefing below — not the other agents' work. Do your one job, stay inside "
    "your role, and when asked for JSON reply with a single JSON object only."
)


def safe_registry(parent: ToolRegistry, allow: frozenset[str] = frozenset()) -> ToolRegistry:
    """Only `safe` tools (plus explicitly allowed read-only ones such as
    `web_fetch`), from the already-restricted child set.

    Hundreds of agents run in parallel with no human at the keyboard, so no
    imece agent may call a caution/danger tool (writes, sends, shell). Anything
    with side effects belongs to a tier-4 decision, not to a worker.
    """
    child = ToolRegistry()
    restricted = _restricted_registry(parent)
    for name in restricted.names():
        tool = restricted.get(name)
        if tool is not None and (tool.risk == "safe" or (name == "web_fetch" and name in allow)):
            child.register(tool)
    return child


@dataclass
class LLMAgentFn:
    """Real subagents: one AgentLoop per spec, on the provider for its seat.

    `seats` maps seat name -> Provider. Unknown seats fall back to "pool".
    Agents get no tools unless the spec asks for them, and even then only the
    restricted (non-delegating, non-memory-writing) toolset.
    """

    seats: dict[str, Provider]
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    allow_tools: frozenset[str] = frozenset()
    max_output_tokens: int = 4096
    max_iterations_with_tools: int = 8

    async def __call__(self, spec: AgentSpec) -> AgentReply:
        contract = spec.contract()
        contract.validate()
        provider = self.seats.get(spec.seat) or self.seats["pool"]
        tools = safe_registry(self.tools, self.allow_tools) if spec.use_tools else ToolRegistry()
        budget = Budget(max_iterations=self.max_iterations_with_tools if spec.use_tools else 1)
        loop = AgentLoop(
            provider=provider,
            tools=tools,
            system_prompt=f"{_SUBAGENT_SYSTEM}\n\nYour role: {spec.role}.",
            budget=budget,
            max_output_tokens=self.max_output_tokens,
            approve=self._approve_readonly,
        )
        history = [Message(role="user", content=contract.briefing())]
        text = await loop.run_turn(history)
        cost = cost_of(provider.model, budget.input_tokens, budget.output_tokens)
        return AgentReply(
            text=text,
            tokens=budget.used_tokens,
            cost_usd=cost.usd if budget.used_tokens > 0 else None,
            cost_estimated=cost.estimated,
        )

    async def _approve_readonly(self, call, _risk: str) -> bool:
        return call.name == "web_fetch" and call.name in self.allow_tools


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_json(text: str) -> dict[str, Any] | None:
    """Pull one JSON object out of a model reply (fenced or bare)."""
    candidates = [m.group(1) for m in _FENCE.finditer(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            value = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def clip(text: str, limit: int = 1500) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
