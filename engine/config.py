"""Shared `ToolConfig` construction for engine entrypoints (`run.py`,
`interactive.py`) — kept in one place so single-shot and session mode can't
drift on MCP wiring, guardrail, or skill discovery.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.guardrail import GuardrailPolicy
from engine.harnesses.base import ToolConfig

REPO_ROOT = Path(__file__).parent.parent

# The SDK's stdio transport bounds one NDJSON message (a single tool
# result) at 1MB by default — not cumulative conversation size, one
# message. Found live porting red-flag-scan: a real run crashed with
# "JSON message exceeded maximum buffer size of 1048576 bytes" on its
# first real Layer 2 call. The old repo measured this properly rather than
# guessing: get_announcements with the exact yesterday/today bound
# measured 86 bytes-4KB for real symbols; a *mistaken* unbounded call (a
# plausible prompt-adherence slip, not just theoretical) measured
# 2.0-3.0MB for large-caps like TCS/RELIANCE/SBIN. 10MB gives comfortable
# headroom above that measured worst case. Applies engine-wide, not just
# to morning-digest — any skill pulling filings/news/shareholding data can
# hit this.
_MAX_BUFFER_SIZE = 10_000_000


def _minty_skill_names() -> list[str]:
    """Explicit skill list, not "all" — `skills="all"` also pulls in
    unrelated global/user-level skills installed on the host, which a
    Minty-dedicated engine shouldn't surface. Empty list (not an error) if
    `.claude/skills/` doesn't exist — lets the engine still run for plain
    conversation and Layer 1/2 tool use even before any skill is ported.

    Reads `.claude/skills/`, not the top-level `skills/` directory —
    corrected after live-testing this port. `docs/vision.md` §4 originally
    assumed the engine could read canonical `skills/` directly since it
    "owns skill loading, not bound to Claude Code's discovery." Verified
    live that this is false at the plumbing level:
    `setting_sources=["project"]` + `skills=[...]` *is* Claude Code's own
    project-skill discovery (the Agent SDK's transport shells out to the
    `claude` CLI, see claude_agent_sdk.py's docstring), and that mechanism
    only ever reads `.claude/skills/` — confirmed by dumping a live
    `SystemMessage`'s own `skills` field, which listed unrelated host/CLI
    skills and *not* this project's own until `.claude/skills/` (not
    `skills/`) held the same content. `skills/` still exists for
    `README.md`/`THIRD-PARTY-NOTICES.md`; the actual skill packages
    (SKILL.md + scripts/) live only in `.claude/skills/` now — one
    canonical copy, not the old repo's canonical-plus-generated-view split
    (there's no second harness needing a different structure yet to
    justify that machinery — see docs/vision.md §3's Codex section).
    """
    skills_dir = REPO_ROOT / ".claude" / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir())


def build_tool_config(
    *, builtin_tools: list[str] | None = None, max_buffer_size: int | None = None
) -> ToolConfig:
    mcp_config = json.loads((REPO_ROOT / ".mcp.json").read_text())
    return ToolConfig(
        mcp_servers=mcp_config["mcpServers"],
        guardrail=GuardrailPolicy(),
        skills=_minty_skill_names(),
        # bypassPermissions (required for headless/no-TTY query() and reused
        # for interactive Sessions too, see claude_agent_sdk.py's docstring)
        # auto-approves every built-in tool, not just MCP tools. Restrict to
        # what Minty actually needs; no Edit/NotebookEdit, which nothing here
        # has a use for yet.
        builtin_tools=builtin_tools if builtin_tools is not None else ["Read", "Write", "Bash"],
        max_buffer_size=max_buffer_size if max_buffer_size is not None else _MAX_BUFFER_SIZE,
    )
