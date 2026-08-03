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


def _minty_skill_names() -> list[str]:
    """Explicit skill list, not "all" — `skills="all"` also pulls in
    unrelated global/user-level skills installed on the host, which a
    Minty-dedicated engine shouldn't surface. Empty list (not an error) when
    `skills/` doesn't exist yet — skills haven't been ported into this repo
    yet, but the engine itself should still run for plain conversation and
    Layer 1/2 tool use in the meantime.
    """
    skills_dir = REPO_ROOT / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir())


def build_tool_config(*, builtin_tools: list[str] | None = None) -> ToolConfig:
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
    )
