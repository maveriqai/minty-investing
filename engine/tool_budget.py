"""Per-turn tool-call counts, checked against a skill's own declared
`tool_call_budgets` (SKILL.md frontmatter) — for audit and future-
improvement visibility only. Never blocks a call.

Built after finding, live, that morning-digest's own documented "~20
india_news.get_news calls" ceiling (SKILL.md's Guardrails section) wasn't
actually enforced anywhere: the model called the tool roughly twice per
held symbol (once by raw ticker, once by the resolved company name),
nearly doubling the intended count.

First built as a hard `PreToolUse` deny (same shape as the order-execution
and Bash-scope hooks in engine/harnesses/claude_agent_sdk.py) and then
reconsidered: unlike those two, which block an action that must *never*
happen (irreversible or high-blast-radius), a duplicate news search is a
harmless, reversible read — the actual defect was the SKILL.md prose that
tempted a second call, already fixed there (step 8b). Denying the call
doesn't undo the bad decision that already produced it, and only adds a
confusing tool error to a user-facing digest for what is, at worst, a
cost/politeness concern, not a safety one. So this module only counts —
`engine/interactive.py`'s `_run_turn` prints what it finds as a plain
diagnostic line for whoever is running the engine, never fed back to the
model or used to block anything. Good raw material for a future warning
surfaced to the end user too, once that UX is actually designed.
"""

from __future__ import annotations

from engine.skills import load_tool_call_budgets
from engine.tool_capture import parse_mcp_tool_name


class TurnBudgetTracker:
    """Counts calls against each budgeted (mcp_server, tool_name) pair for
    the turn currently in progress. `record()` always succeeds — nothing
    here can refuse a call."""

    def __init__(self, budgets: dict[tuple[str, str], int]) -> None:
        self._budgets = budgets
        self._counts: dict[tuple[str, str], int] = {}

    def reset(self) -> None:
        """Call at the start of each turn — a budget is a per-turn
        expectation, matching how each SKILL.md documents its own call
        counts (e.g. "up to ~20 calls" per digest run), not a per-session
        one."""
        self._counts = {}

    def record(self, tool_name: str) -> None:
        """Call once per tool-use seen, regardless of outcome. No-op for a
        tool with no declared budget, or a non-MCP-namespaced name — only
        budgeted tools are worth tracking at all."""
        parsed = parse_mcp_tool_name(tool_name)
        if parsed is None or parsed not in self._budgets:
            return
        self._counts[parsed] = self._counts.get(parsed, 0) + 1

    def over_budget(self) -> list[str]:
        """One human-readable line per budgeted tool whose count this turn
        exceeded its declared limit — for the engine to print as a
        diagnostic. Empty when nothing crossed its budget."""
        lines = []
        for parsed, limit in self._budgets.items():
            count = self._counts.get(parsed, 0)
            if count > limit:
                server, tool = parsed
                lines.append(
                    f"{server}.{tool} called {count} times this turn "
                    f"(skill declares an expected ceiling of {limit})"
                )
        return lines


def build_budget_tracker(skill_names: list[str]) -> TurnBudgetTracker:
    """Merges every loaded skill's own declared `tool_call_budgets` — keys
    are "server.tool" strings in SKILL.md, split here into (server, tool)
    tuples to match `parse_mcp_tool_name`'s own shape. Two skills declaring
    different ceilings for the same tool would let the later one (in
    `skill_names` order) win — hasn't happened across the skills ported so
    far, so not worth a conflict policy until it does."""
    budgets: dict[tuple[str, str], int] = {}
    for skill_name in skill_names:
        for key, limit in load_tool_call_budgets(skill_name).items():
            server, _, tool = key.partition(".")
            if tool:
                budgets[(server, tool)] = limit
    return TurnBudgetTracker(budgets)


__all__ = ["TurnBudgetTracker", "build_budget_tracker"]
