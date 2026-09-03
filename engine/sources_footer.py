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

Issue #36: a multi-candidate skill run (e.g. screen-indian-stocks over 25
names) produced a ~70-line wall here — one line per candidate per data
source, with no distinction between a name merely bulk-fetched and one
actually discussed in depth. `build_footer` now groups captures by
`(mcp_server, tool_name)` and collapses any group larger than
`_ITEMIZE_THRESHOLD` into one summary line, rather than itemizing every
path — no new "was this discussed in depth" signal needed: a bulk screen
phase naturally produces one large group per source, while a smaller
in-depth pass (e.g. red-flag-scan's per-source calls for a handful of
names) naturally stays under the threshold and keeps its itemized lines.
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

# A group of more than this many distinct captured paths for one
# (mcp_server, tool_name) pair gets collapsed into a single summary line
# instead of one line per path (issue #36). Chosen to sit comfortably
# above a typical in-depth pass (e.g. red-flag-scan's handful of
# per-source calls for a handful of names) and below a typical bulk-screen
# phase (dozens of candidates), so the two naturally separate without
# needing an explicit "discussed in depth" signal.
_ITEMIZE_THRESHOLD = 5

# The literal, fixed prefix every non-empty `build_footer` output starts
# with — exported so a caller (engine/interactive.py, splitting the
# model's own text from the engine-appended footer for rendering) can
# find it without duplicating this string.
FOOTER_MARKER = "\n\n---\n**Sources**"

# A standalone disclaimer, no Sources list, for a turn that discusses
# already-grounded findings (cited inline from an earlier turn/session)
# but made no fresh captures of its own — `build_footer` above correctly
# returns "" for that case (nothing new to cite), but the review turn for
# issue #14's staged-candidates pipeline still needs the disclaimer, since
# it's discussing money-adjacent figures (issue #65). `ClaudeSession.send`
# yields this verbatim when `force_disclaimer=True` and the normal
# captures-based footer didn't already fire; `_split_footer`
# (engine/interactive.py) recognizes it the same way it recognizes
# FOOTER_MARKER, so it gets the same distinct rendering treatment.
DISCLAIMER_ONLY_FOOTER = f"\n\n---\n*{DISCLAIMER}*\n"


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

    Then groups the surviving captures by `(mcp_server, tool_name)`,
    preserving first-seen group order. A group with more than
    `_ITEMIZE_THRESHOLD` distinct paths becomes one summary line
    ("fetched for N candidates"); a smaller group keeps today's itemized
    per-path lines (issue #36).
    """
    if not captures:
        return ""

    seen: set[Path] = set()
    grouped: dict[tuple[str, str], list[Path]] = {}
    group_order: list[tuple[str, str]] = []
    for mcp_server, tool_name, saved_path in captures:
        if saved_path in seen:
            continue
        seen.add(saved_path)
        key = (mcp_server, tool_name)
        if key not in grouped:
            grouped[key] = []
            group_order.append(key)
        grouped[key].append(saved_path)

    lines: list[str] = []
    for mcp_server, tool_name in group_order:
        paths = grouped[(mcp_server, tool_name)]
        if len(paths) > _ITEMIZE_THRESHOLD:
            lines.append(
                f"- {_label(mcp_server)}.{tool_name} — fetched for {len(paths)} candidates "
                f"(as of {as_of}) — see `workspace/data/`"
            )
            continue
        for saved_path in paths:
            try:
                relative = saved_path.relative_to(workspace_root)
            except ValueError:
                relative = saved_path
            lines.append(f"- {_label(mcp_server)}.{tool_name} (as of {as_of}) — `{relative}`")

    return FOOTER_MARKER + "\n" + "\n".join(lines) + f"\n\n*{DISCLAIMER}*\n"


__all__ = ["DISCLAIMER", "DISCLAIMER_ONLY_FOOTER", "FOOTER_MARKER", "build_footer"]
