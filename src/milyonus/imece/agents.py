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


AgentFn = Callable[[AgentSpec], Awaitable[AgentReply]]


class PoolExhausted(Exception):
    """The shared token pool ran out; the run stops with what it has."""


@dataclass(slots=True)
class AgentEvent:
    block: str
    role: str
    seat: str
    tokens: int
    ok: bool


class Swarm:
    """Runs agent specs concurrently against a shared token pool."""

    def __init__(self, agent_fn: AgentFn, *, max_parallel: int = 8, max_tokens: int = 2_000_000):
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        self._fn = agent_fn
        self._sem = asyncio.Semaphore(max_parallel)
        self.max_tokens = max_tokens
        self.used_tokens = 0
        self.events: list[AgentEvent] = []

    def exhausted(self) -> bool:
        return self.used_tokens >= self.max_tokens

    async def _one(self, spec: AgentSpec) -> str:
        async with self._sem:
            if self.exhausted():
                raise PoolExhausted(f"token pool exhausted ({self.used_tokens}/{self.max_tokens})")
            try:
                reply = await self._fn(spec)
            except PoolExhausted:
                raise
            except Exception as exc:  # one failed agent must not sink the phase
                self.events.append(AgentEvent(spec.block, spec.role, spec.seat, 0, False))
                return f"(agent failed: {type(exc).__name__}: {exc})"
            self.used_tokens += reply.tokens
            if not reply.text.strip() or reply.text.startswith("(budget exhausted"):
                # An empty answer (e.g. a reasoning model that spent its whole
                # output budget thinking) is a failed agent, not a candidate.
                self.events.append(
                    AgentEvent(spec.block, spec.role, spec.seat, reply.tokens, False)
                )
                return "(agent failed: empty reply)"
            self.events.append(AgentEvent(spec.block, spec.role, spec.seat, reply.tokens, True))
            return reply.text

    async def run(self, specs: Sequence[AgentSpec]) -> list[str]:
        """Run all specs; results come back in the same order."""
        return list(await asyncio.gather(*(self._one(s) for s in specs)))

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
        if tool is not None and (tool.risk == "safe" or name in allow):
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
        )
        history = [Message(role="user", content=contract.briefing())]
        text = await loop.run_turn(history)
        return AgentReply(text=text, tokens=budget.used_tokens)


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
