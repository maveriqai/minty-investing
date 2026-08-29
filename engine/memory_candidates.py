"""Post-turn memory-candidate staging — issue #14, piece 2/3.

Piece 1 (`_REMEMBER_SYSTEM_PROMPT`, `engine/harnesses/claude_agent_sdk.py`)
only covers the case where the user explicitly asks Minty to remember
something. This module covers the other case docs/next-phase-plan.md §8
describes: something durable surfaces in a turn without the user framing
it as a "remember this" ask — a stated preference mentioned in passing, an
open thread worth tracking. That judgment call is inherently uncertain in
a way piece 1's isn't, so it's kept out of notes.md entirely: `stage`
appends to this file, never notes.md, so nothing lands in the hand-curated
file (CLAUDE.md: ≤2000 words) without a human actually looking at it —
`read_and_clear` is only ever called from the session-start review flow
(`engine/interactive.py`'s `_repl`), which surfaces every candidate to the
user before any of it can reach `update_workspace_notes`.

Deliberately append-then-clear, not append-forever: `read_and_clear`
empties the file the moment its content has been handed to a turn for
review, so a candidate is never shown twice. A failure during that review
turn itself is caught and the content restored, rather than lost
(`engine/interactive.py`'s `_repl`, found in review of issue #14) — the
remaining risk window is narrower: a crash after the review turn succeeds
but before the user actually replies still loses the pending decision,
though by then the candidates have already been shown on screen and
recorded in the session transcript, not silently gone. Accepted, same
class of low-stakes risk as the session-transcript same-second collision
(issue #13 review, finding 6): staging content, not the user's actual
data, and a human hadn't acted on it yet either way.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from engine.time_ist import now_ist
from engine.workspace import WORKSPACE_ROOT_ARG_DESCRIPTION as _WORKSPACE_ROOT_DESCRIPTION
from engine.workspace import resolve_workspace_root_arg as _resolve_workspace_root


def candidates_path(workspace_root: Path) -> Path:
    """The one staging file for this workspace — shared across sessions
    (unlike session_transcript's per-session file), since a candidate
    raised in one REPL run should still surface at the start of the next
    one if nobody's reviewed it yet."""
    return workspace_root / "memory_candidates.md"


def append_candidate(path: Path, content: str, grounding: str, *, now: datetime | None = None) -> None:
    """Appends one staged candidate. `grounding` is the model's own short
    account of what backs the claim (a data file, "from this turn's
    discussion") — carried along so the session-start review can show the
    user *why* this was flagged, not just the bare claim."""
    now = now or now_ist()
    timestamp = now.strftime("%Y-%m-%d %H:%M IST")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"## candidate ({timestamp})\n\n{content}\n\nGrounding: {grounding}\n\n")


def read_and_clear(path: Path) -> str:
    """Empty string if there's nothing staged (including if the file was
    never created). Clears the file as part of the same call — see the
    module docstring for why this isn't split into a separate step."""
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    path.write_text("", encoding="utf-8")
    return text.strip()


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_root": {"type": "string", "description": _WORKSPACE_ROOT_DESCRIPTION},
        "content": {
            "type": "string",
            "description": (
                "One or two sentences describing the durable fact you noticed — a "
                "stated preference, an open thread, a decision. Not a summary of "
                "the whole turn, just the specific thing worth remembering."
            ),
        },
        "grounding": {
            "type": "string",
            "description": (
                "A short note on what backs this — the data file it came from, or "
                "'from this turn's discussion' if it's just something the user said."
            ),
        },
    },
    "required": ["workspace_root", "content", "grounding"],
}


async def _handler(args: dict[str, Any]) -> dict[str, Any]:
    workspace_root = _resolve_workspace_root(args.get("workspace_root", ""))
    if workspace_root is None:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"'workspace_root' must be an existing workspace directory — got {args.get('workspace_root')!r}",
                }
            ],
            "is_error": True,
        }
    append_candidate(candidates_path(workspace_root), args["content"], args["grounding"])
    return {"content": [{"type": "text", "text": "staged for review at the start of the next session"}]}


def build_memory_candidate_tool() -> SdkMcpTool[Any]:
    return tool(
        "stage_memory_candidate",
        "Stage something durable you noticed this turn that the user did NOT "
        "explicitly ask you to remember — a preference mentioned in passing, an "
        "open thread, a decision. Never writes notes.md directly: this only "
        "queues the candidate for the user to confirm or discard at the start of "
        "the next session. Don't use this for one-off, point-in-time content "
        "(a price, a single day's number) — same rule as notes.md itself. If the "
        "user DID explicitly ask you to remember something, use "
        "update_workspace_notes directly instead, not this.",
        _INPUT_SCHEMA,
    )(_handler)


def build_memory_candidate_server() -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="memory_candidates", tools=[build_memory_candidate_tool()])


__all__ = [
    "append_candidate",
    "build_memory_candidate_server",
    "build_memory_candidate_tool",
    "candidates_path",
    "read_and_clear",
]
