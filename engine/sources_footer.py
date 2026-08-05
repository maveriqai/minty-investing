"""Builds and the engine appends the Sources footer + SEBI disclaimer that
docs/vision.md §5 requires on every grounded output — mechanically, from
what `engine/tool_capture.py` actually saved to a workspace's `data/` this
turn, rather than leaving "remember to write one" as a model responsibility.

This is the same fix shape as `engine/tool_capture.py` (auto-capture) and
`engine/workspace_notes.py` (fixed save path): live-testing across several
skill runs this session (2026-08-04) found zero of them actually closing
with a Sources footer or the SEBI disclaimer, despite every skill's own
SKILL.md documenting it as a required last step — the same class of
"prose-only closing step gets dropped" failure notes.md hit before
`update_workspace_notes` existed. Removing it as a model decision is the
same fix: `ClaudeSession.send()` (engine/harnesses/claude_agent_sdk.py)
appends `build_footer()`'s output itself once a turn's captures are known,
so it's structurally impossible to skip rather than hoped-for.

Deliberately keyed off `tool_capture.CAPTURE_SPECS`' capture events, not
each envelope's own embedded `source`/`as_of` fields — Layer 1
(`kite_gateway`, a plain passthrough to Kite's hosted MCP) never carries
that envelope shape the way Layer 2 tools do, so parsing embedded fields
would need two different code paths. The capture event itself already
carries everything the footer needs (which tool, which file, today's
date), for both layers uniformly.
"""

from __future__ import annotations

from pathlib import Path

# Kept byte-for-byte identical to the blockquote in docs/vision.md §5 —
# that's the documented source of truth, this is the literal string used.
DISCLAIMER = (
    "Minty is a research tool, not investment advice. This is educational "
    "analysis of publicly available data. Consult a SEBI-registered "
    "investment adviser before acting."
)

_SOURCE_LABELS: dict[str, str] = {
    "kite_gateway": "Kite (Zerodha)",
    "india_price": "india_price",
    "india_filings": "india_filings",
    "india_macro": "india_macro",
    "india_news": "india_news",
}


def _label(mcp_server: str) -> str:
    return _SOURCE_LABELS.get(mcp_server, mcp_server)


def build_footer(captures: list[tuple[str, str, Path]], *, as_of: str, workspace_root: Path) -> str:
    """`captures` is `(mcp_server, tool_name, saved_path)` per successful
    auto-capture this turn, in call order. Empty string (nothing to append)
    if `captures` is empty — a turn that captured nothing made no grounded
    claims to source, so appending a footer to it would be noise, not
    grounding (e.g. a plain chit-chat reply, or "login done").

    De-duplicates by saved path, keeping first-seen order, since the same
    file can legitimately be written twice in one turn (e.g. an auto-capture
    retry after a too-large first payload — see the live-test transcripts).
    """
    if not captures:
        return ""

    seen: set[Path] = set()
    lines: list[str] = []
    for mcp_server, tool_name, saved_path in captures:
        if saved_path in seen:
            continue
        seen.add(saved_path)
        try:
            relative = saved_path.relative_to(workspace_root)
        except ValueError:
            relative = saved_path
        lines.append(f"- {_label(mcp_server)}.{tool_name} (as of {as_of}) — `{relative}`")

    return "\n\n---\n**Sources**\n" + "\n".join(lines) + f"\n\n*{DISCLAIMER}*\n"


__all__ = ["DISCLAIMER", "build_footer"]
