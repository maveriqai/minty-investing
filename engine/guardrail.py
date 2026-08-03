"""Harness-agnostic no-order-execution policy.

Kept independent of any concrete harness (Claude Agent SDK or otherwise) so
the same policy object can drive every guardrail layer a harness offers,
instead of each layer hand-listing tool names separately and risking drift.
See docs/vision.md §5 (Non-negotiables) — order execution is never
permitted from any Minty-driven session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ORDER_TOOL_NAMES = frozenset(
    {
        "place_order",
        "modify_order",
        "cancel_order",
        "place_gtt_order",
        "modify_gtt_order",
        "delete_gtt_order",
    }
)


@dataclass(frozen=True)
class GuardrailPolicy:
    """Denies the six Kite order-tool names regardless of which MCP server
    they're namespaced under (`kite`, `kite_gateway`, or any future one)."""

    denied_tool_suffixes: frozenset[str] = field(default_factory=lambda: ORDER_TOOL_NAMES)

    def denied_tool_names(self, server_names: list[str]) -> set[str]:
        """Full `mcp__<server>__<tool>` names for every (server, denied tool) pair."""
        return {
            f"mcp__{server}__{tool}" for server in server_names for tool in self.denied_tool_suffixes
        }

    def is_denied(self, full_tool_name: str) -> bool:
        """True if `full_tool_name` (e.g. `mcp__kite_gateway__place_order`) is
        an order tool under any server — matches on suffix, not a hand-listed
        set of full names, so it can't silently miss a new server."""
        if "__" not in full_tool_name:
            return False
        return full_tool_name.rsplit("__", 1)[-1] in self.denied_tool_suffixes
