"""The agent loop — the single core every surface (CLI, gateway, cron) shares.

One turn: build the request from history, stream a completion, and if the model
asked for tools, execute them (via an approval hook) and feed results back until
the model produces a final answer or the budget is exhausted. Streaming text is
delivered through an async callback so the TUI can render tokens live.

Security posture in F1: dangerous tools are gated by `approve`, an injected
callback. F4 replaces the default approve with the RiskEngine.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from milyonus.core.budget import Budget
from milyonus.providers.base import (
    CompletionRequest,
    Message,
    Provider,
    ToolCall,
    ToolResult,
)
from milyonus.security.risk import RiskEngine
from milyonus.tools.registry import ToolRegistry

# Called before a non-safe tool runs. No approval handler means deny.
ApproveFn = Callable[[ToolCall, str], Awaitable[bool]]

# Streaming sinks. on_text gets assistant text chunks; on_tool announces a call.
TextSink = Callable[[str], Awaitable[None]]
ToolSink = Callable[[ToolCall], Awaitable[None]]
DeniedSink = Callable[[ToolCall, str], Awaitable[None]]


async def _deny_default(_call: ToolCall, _risk: str) -> bool:
    return False


async def _noop_text(_s: str) -> None:  # pragma: no cover - trivial
    return None


async def _noop_tool(_c: ToolCall) -> None:  # pragma: no cover - trivial
    return None


async def _noop_denied(_c: ToolCall, _reason: str) -> None:
    return None


@dataclass
class AgentLoop:
    provider: Provider
    tools: ToolRegistry
    system_prompt: str
    budget: Budget = field(default_factory=Budget)
    approve: ApproveFn = _deny_default
    on_text: TextSink = _noop_text
    on_tool: ToolSink = _noop_tool
    on_denied: DeniedSink = _noop_denied
    max_output_tokens: int = 4096
    # Optional observability. When set, the loop records model/tool events for
    # evaluation. Passive and off by default — existing behavior is unchanged.
    tracer: object | None = None
    risk_engine: RiskEngine = field(default_factory=RiskEngine)

    async def run_turn(self, history: list[Message]) -> str:
        """Advance the conversation until a final assistant message. `history`
        is mutated in place with the new assistant/tool messages."""
        import time as _time

        while True:
            if self.budget.exhausted():
                note = "(budget exhausted — task stopped here)"
                history.append(Message(role="assistant", content=note))
                return note

            request = CompletionRequest(
                system=self.system_prompt,
                messages=history,
                tools=self.tools.schemas(),
                max_output_tokens=self.max_output_tokens,
            )

            if self.tracer is not None:
                self.tracer.start_model_call()
            text_parts: list[str] = []
            pending: list[ToolCall] = []
            usage_in = usage_out = 0
            stop_reason: str | None = None
            async for event in self.provider.stream(request):
                if event.kind == "text":
                    text_parts.append(event.delta)
                    await self.on_text(event.delta)
                elif event.kind == "tool_call" and event.tool_call is not None:
                    pending.append(event.tool_call)
                    await self.on_tool(event.tool_call)
                elif event.kind == "usage" and event.usage is not None:
                    usage_in, usage_out = event.usage.input_tokens, event.usage.output_tokens
                elif event.kind == "done":
                    stop_reason = event.stop_reason
            # One iteration per request, even if a provider omits usage. Usage
            # events may be cumulative snapshots; only count the final one.
            self.budget.record(input_tokens=usage_in, output_tokens=usage_out)
            if self.tracer is not None:
                self.tracer.end_model_call(
                    input_tokens=usage_in, output_tokens=usage_out, stop_reason=stop_reason
                )

            assistant_text = "".join(text_parts)
            history.append(
                Message(
                    role="assistant",
                    content=assistant_text,
                    tool_calls=list(pending),
                )
            )

            if not pending:
                return assistant_text

            # Execute the requested tools and append their results.
            results: list[ToolResult] = []
            for call in pending:
                tool = self.tools.get(call.name)
                risk = tool.risk if tool else "danger"
                approved: bool | None = None
                decision, reason, _findings = self.risk_engine.classify(call, risk)
                if decision != "auto":
                    approved = decision != "block" and await self.approve(call, risk)
                    if not approved:
                        await self.on_denied(call, reason)
                        if self.tracer is not None:
                            self.tracer.record_tool_call(
                                name=call.name,
                                arguments=call.arguments,
                                is_error=True,
                                duration_s=0.0,
                                approved=False,
                            )
                        results.append(
                            ToolResult(
                                call_id=call.id,
                                content=f"(tool denied: {reason})",
                                is_error=True,
                            )
                        )
                        continue
                t0 = _time.perf_counter()
                content, is_error = await self.tools.run(call.name, call.arguments)
                if self.tracer is not None:
                    self.tracer.record_tool_call(
                        name=call.name,
                        arguments=call.arguments,
                        is_error=is_error,
                        duration_s=_time.perf_counter() - t0,
                        approved=approved,
                    )
                results.append(ToolResult(call_id=call.id, content=content, is_error=is_error))
            history.append(Message(role="tool", tool_results=results))
            # loop continues: model sees tool results and responds


def build_history(user_messages: Sequence[str]) -> list[Message]:  # pragma: no cover
    return [Message(role="user", content=m) for m in user_messages]
