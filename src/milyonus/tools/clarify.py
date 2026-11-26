"""Budgeted clarification tool (PLAN §6.1).

When uncertainty and cost are both high, the agent may ask the user one crisp
question rather than guessing or acting blindly. Limited to `max_per_turn`
calls per turn (default 1) so the agent cannot loop on questions. Subagents
never receive this tool.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from milyonus.tools.registry import Tool

ClarifyFn = Callable[[str, list[str]], Awaitable[str]]


@dataclass
class ClarifyBudget:
    """Per-turn counter enforcing at most `max_per_turn` clarification prompts."""

    max_per_turn: int = 1
    used: int = 0

    def reset(self) -> None:
        self.used = 0

    def consume(self) -> bool:
        if self.used >= self.max_per_turn:
            return False
        self.used += 1
        return True


def make_clarify_tool(
    ask: ClarifyFn | None = None,
    *,
    budget: ClarifyBudget | None = None,
    max_per_turn: int = 1,
) -> Tool:
    """Build the `clarify` tool. Safe risk class (read-only user interaction)."""
    counter = budget if budget is not None else ClarifyBudget(max_per_turn=max_per_turn)

    async def handler(args: dict[str, Any]) -> str:
        question = str(args.get("question", "")).strip()
        if not question:
            return "Error: 'question' must be a non-empty string."
        raw_options = args.get("options") or []
        options = [str(o).strip() for o in raw_options if str(o).strip()][:5]
        if not counter.consume():
            return (
                "(clarify budget exhausted for this turn — at most "
                f"{counter.max_per_turn} clarifying question per turn; "
                "state your assumptions clearly and proceed safely)"
            )
        if ask is None:
            return (
                "(no interactive user attached to answer clarification — "
                "state assumptions and proceed with safe reversible steps only)"
            )
        answer = (await ask(question, options)).strip()
        return answer or "(user gave an empty response)"

    return Tool(
        name="clarify",
        description=(
            "Ask the user ONE concise clarifying question when ambiguity would "
            "cause wasted work or an irreversible mistake. Budgeted to at most "
            "once per turn."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "One crisp, specific question for the user.",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional short choices (up to 5).",
                },
            },
            "required": ["question"],
        },
        handler=handler,
        risk="safe",
    )
